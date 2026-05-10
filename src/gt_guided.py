"""Annotation TIFF parsing + GT vs raw-detection comparison.

Annotation colour mapping (from inspection of 21_OS_4H_annotation /
21_OS_6H_annotation):

  - BM       : magenta-ish  (R high, G low, B mid)
  - TOP      : green-tinted (saturated greens that don't appear in the
                              source TIFF Heidelberg crosshair markers)
  - ONL      : cyan / blue
  - DET top  : yellow-bright
  - DET bot  : black (drawn on the lower edge of the cavity)

GT is used **only** to report a per-boundary median |Δy| against the raw
detection. Coordinates are never copied into the output.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from io_utils import OctImage


# --------------------------------------------------------- HITL colours
# Annotation TIFFs produced by the HITL editor (and the converter for
# legacy files) use a single, distinct, high-saturation palette
# (see src/hitl/colors.py). Per-channel thresholds re-parse them
# reliably without picking up the OCT grayscale image underneath.
def _mask_top(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (R > 200) & (G < 100) & (B < 100)        # red


def _mask_onl(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (G > 200) & (R < 100) & (B < 100)        # green


def _mask_bm(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # HITL BM is (64, 128, 255). Blue dominant, mid green tolerated.
    return (B > 200) & (R < 100) & (G < 200)        # blue


def _mask_det_top(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (R > 200) & (G > 200) & (B < 100)        # yellow


def _mask_det_bot(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (R > 200) & (G < 100) & (B > 200)        # magenta


# --------------------------------------------------------- legacy masks
# Heidelberg-marked annotation TIFFs (4H/6H images) use a different
# palette (BM magenta-ish, TOP green, ONL cyan, DET top yellow,
# DET bot black). Kept here so:
#   - tools/convert_legacy_annotations can read these files and
#     re-render with HITL colours.
#   - load_gt can transparently fall back to legacy masks when no
#     HITL colours are detected (so users can still validate against
#     un-converted Heidelberg annotations).
def _mask_bm_legacy(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (R > 130) & (G < 100) & (B > 90)


def _mask_top_legacy(rgb: np.ndarray, original_rgb: np.ndarray) -> np.ndarray:
    """Legacy TOP: green pixels in annotation but not in the source TIFF."""
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    is_green = (G > 110) & (G > R + 30) & (G > B + 30)
    Ro, Go, Bo = original_rgb[..., 0], original_rgb[..., 1], original_rgb[..., 2]
    same_as_orig = (R == Ro) & (G == Go) & (B == Bo)
    return is_green & (~same_as_orig)


def _mask_onl_legacy(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (B > 130) & (B > R + 30)                  # cyan / blue


def _mask_det_legacy(rgb: np.ndarray) -> np.ndarray:
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (R > 130) & (G > 130) & (B < 80)          # yellow (single colour)


@dataclass
class GTBoundaries:
    """Per-column GT y arrays in B-scan-relative coords (NaN where missing)."""
    TOP: np.ndarray
    ONL: np.ndarray
    BM: np.ndarray
    DET_top: np.ndarray
    DET_bottom: np.ndarray


def _column_y_from_mask(mask_crop: np.ndarray,
                        y_lo: int = 0, y_hi: int | None = None) -> np.ndarray:
    """Per column, return median y of True pixels in [y_lo, y_hi).

    Restricting to a retinal y range avoids picking up coloured pixels in
    image labels / scale bars that share the colour family. Median (not
    mean) is robust to stray pixels outside the line.
    """
    H, W = mask_crop.shape
    if y_hi is None:
        y_hi = H
    out = np.full(W, np.nan, dtype=np.float32)
    if not mask_crop.any():
        return out
    sub = mask_crop[y_lo:y_hi]
    if not sub.any():
        return out
    ys, xs = np.where(sub)
    if xs.size == 0:
        return out
    ys = ys + y_lo
    order = np.argsort(xs, kind="stable")
    xs_s = xs[order]
    ys_s = ys[order]
    starts = np.searchsorted(xs_s, np.arange(W), side="left")
    ends = np.searchsorted(xs_s, np.arange(W), side="right")
    for x, (s, e) in enumerate(zip(starts, ends)):
        if e > s:
            out[x] = float(np.median(ys_s[s:e]))
    return out


def _split_run(mask_crop: np.ndarray, y_lo: int = 0, y_hi: int | None = None
               ) -> tuple[np.ndarray, np.ndarray]:
    """For DET: per-column (top_y, bottom_y) of the masked region in y range."""
    H, W = mask_crop.shape
    if y_hi is None:
        y_hi = H
    top = np.full(W, np.nan, dtype=np.float32)
    bot = np.full(W, np.nan, dtype=np.float32)
    for x in range(W):
        col = mask_crop[y_lo:y_hi, x]
        if not col.any():
            continue
        ys = np.where(col)[0] + y_lo
        top[x] = float(ys.min())
        bot[x] = float(ys.max())
    return top, bot


def load_gt(annotation_path: str | Path,
            oct_image: OctImage) -> GTBoundaries:
    """Extract per-column GT boundaries from an annotation TIFF.

    Auto-detects the colour scheme:
      - HITL palette (red / green / blue / yellow / magenta) used by
        ``hitl/export_annotations.py`` and the legacy converter.
      - Legacy Heidelberg palette (green / cyan / magenta / yellow /
        black) used by the original 4H/6H annotations.

    The annotation must share the same image dimensions as `oct_image`.
    """
    p = Path(annotation_path)
    anno = np.asarray(Image.open(str(p)).convert("RGB"), dtype=np.uint8)
    if anno.shape[:2] != oct_image.rgb.shape[:2]:
        raise ValueError(
            f"Annotation shape {anno.shape[:2]} does not match "
            f"image shape {oct_image.rgb.shape[:2]}")

    l = oct_image.layout
    crop = lambda m: m[l.top_y:l.bot_y + 1, l.left_x:l.right_x + 1]
    H = l.bot_y - l.top_y + 1
    retinal_y_lo, retinal_y_hi = int(H * 0.10), int(H * 0.55)

    # Try HITL-colour masks first.
    bm_mask = crop(_mask_bm(anno))
    if bm_mask.any():
        top_mask = crop(_mask_top(anno))
        onl_mask = crop(_mask_onl(anno))
        det_top_mask = crop(_mask_det_top(anno))
        det_bot_mask = crop(_mask_det_bot(anno))
        BM = _column_y_from_mask(bm_mask, retinal_y_lo, retinal_y_hi)
        TOP = _column_y_from_mask(top_mask, retinal_y_lo, retinal_y_hi)
        ONL = _column_y_from_mask(onl_mask, retinal_y_lo, retinal_y_hi)
        DET_top = _column_y_from_mask(det_top_mask,
                                        retinal_y_lo, retinal_y_hi)
        DET_bot = _column_y_from_mask(det_bot_mask,
                                        retinal_y_lo, retinal_y_hi)
        return GTBoundaries(TOP=TOP, ONL=ONL, BM=BM,
                            DET_top=DET_top, DET_bottom=DET_bot)

    # Fall back to the legacy Heidelberg palette.
    bm_mask = crop(_mask_bm_legacy(anno))
    top_mask = crop(_mask_top_legacy(anno, oct_image.rgb))
    onl_mask = crop(_mask_onl_legacy(anno))
    det_mask = crop(_mask_det_legacy(anno))
    BM = _column_y_from_mask(bm_mask, retinal_y_lo, retinal_y_hi)
    TOP = _column_y_from_mask(top_mask, retinal_y_lo, retinal_y_hi)
    ONL = _column_y_from_mask(onl_mask, retinal_y_lo, retinal_y_hi)
    DET_top, DET_bot = _split_run(det_mask, retinal_y_lo, retinal_y_hi)
    return GTBoundaries(TOP=TOP, ONL=ONL, BM=BM,
                        DET_top=DET_top, DET_bottom=DET_bot)


def median_abs_error(pred: np.ndarray, gt: np.ndarray) -> float:
    """Median |Δy| over columns where both pred and gt are finite."""
    valid = ~(np.isnan(pred) | np.isnan(gt))
    if not valid.any():
        return float("nan")
    return float(np.median(np.abs(pred[valid] - gt[valid])))


def compare(pred, gt: GTBoundaries) -> dict[str, float]:
    """Return per-boundary median |Δy| (NaN where not comparable).

    `pred` should be a `BoundaryResult` (uses TOP, ONL, BM, DET_top, DET_bottom).
    """
    return {
        "TOP_median_err_px": median_abs_error(pred.TOP, gt.TOP),
        "ONL_median_err_px": median_abs_error(pred.ONL, gt.ONL),
        "BM_median_err_px": median_abs_error(pred.BM, gt.BM),
        "DET_top_median_err_px": median_abs_error(pred.DET_top, gt.DET_top),
        "DET_bottom_median_err_px": median_abs_error(pred.DET_bottom,
                                                      gt.DET_bottom),
    }


def find_annotation(image_path: str | Path) -> Optional[Path]:
    """Locate the matching annotation TIFF if one exists.

    Looks only in the HITL-canonical folder
    ``<parent>/output/annotations/tiff/<stem>_annotation_hitl.{tiff,tif}``.

    The legacy ``<parent>/annotation/<stem>_annotation.tiff`` location
    is intentionally ignored — once the project has been through HITL,
    those legacy files duplicate the canonical HITL-coloured versions
    and only cause confusion. Convert legacy files to HITL colours via
    the editor's "Tools > Convert Legacy Annotation TIFFs to HITL
    Colours..." menu before relying on them.
    """
    p = Path(image_path)
    hitl_dir = p.parent / "output" / "annotations" / "tiff"
    for ext in (".tiff", ".tif"):
        cand = hitl_dir / f"{p.stem}_annotation_hitl{ext}"
        if cand.exists():
            return cand
    return None


