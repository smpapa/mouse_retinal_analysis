"""Convert legacy Heidelberg-palette annotation TIFFs to HITL colours.

The 4H/6H training annotations were originally drawn in a different
colour scheme (see ``gt_guided._mask_*_legacy``). After this conversion,
all annotations across the project use the same HITL palette
(see ``hitl.colors.BOUNDARY_COLORS``), which means:

  - The HITL editor's display colours match the on-disk annotations.
  - ``gt_guided.load_gt`` runs against a single canonical palette.
  - Newly exported annotations from the editor stack with the legacy
    ones in one folder.

The legacy file is **never modified** — outputs go to a separate folder
chosen by the caller.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .colors import BOUNDARY_COLORS
from .export_annotations import _write_annotation_tiff


_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gt_guided import (                              # noqa: E402
    _column_y_from_mask,
    _mask_bm_legacy,
    _mask_det_legacy,
    _mask_onl_legacy,
    _mask_top_legacy,
    _split_run,
)
from io_utils import load_oct                          # noqa: E402


def convert_legacy_annotation(legacy_tiff: str | Path,
                                original_tiff: str | Path,
                                out_tiff: str | Path) -> dict:
    """Re-render one Heidelberg-palette annotation in HITL colours.

    Parameters
    ----------
    legacy_tiff : path to the original ``*_annotation.tiff`` (Heidelberg).
    original_tiff : path to the un-annotated source TIFF for the same
                    image — used both to detect "TOP green that is the
                    Heidelberg crosshair vs the human marker" and as
                    the canvas to re-draw on.
    out_tiff : where the new HITL-coloured annotation goes.

    Returns
    -------
    dict with ``found`` mapping each boundary name to True/False
    (whether any legacy pixels were detected).
    """
    img = load_oct(original_tiff)
    legacy = np.asarray(
        Image.open(str(legacy_tiff)).convert("RGB"), dtype=np.uint8
    )
    if legacy.shape[:2] != img.rgb.shape[:2]:
        raise ValueError(
            f"Legacy annotation shape {legacy.shape[:2]} does not match "
            f"original TIFF shape {img.rgb.shape[:2]}"
        )

    layout = img.layout
    crop = lambda m: m[layout.top_y:layout.bot_y + 1,
                       layout.left_x:layout.right_x + 1]
    H = layout.bot_y - layout.top_y + 1
    retinal_y_lo, retinal_y_hi = int(H * 0.10), int(H * 0.55)

    bm_mask = crop(_mask_bm_legacy(legacy))
    top_mask = crop(_mask_top_legacy(legacy, img.rgb))
    onl_mask = crop(_mask_onl_legacy(legacy))
    det_mask = crop(_mask_det_legacy(legacy))

    BM_rel = _column_y_from_mask(bm_mask, retinal_y_lo, retinal_y_hi)
    TOP_rel = _column_y_from_mask(top_mask, retinal_y_lo, retinal_y_hi)
    ONL_rel = _column_y_from_mask(onl_mask, retinal_y_lo, retinal_y_hi)
    DET_top_rel, DET_bot_rel = _split_run(det_mask, retinal_y_lo, retinal_y_hi)

    # Convert B-scan-relative -> absolute (HITL convention).
    effective = {
        "TOP_y":        TOP_rel + layout.top_y,
        "ONL_y":        ONL_rel + layout.top_y,
        "BM_y":         BM_rel + layout.top_y,
        "DET_top_y":    DET_top_rel + layout.top_y,
        "DET_bottom_y": DET_bot_rel + layout.top_y,
    }
    # Adding to NaN gives NaN — so missing-pixel columns stay NaN.

    out_path = Path(out_tiff)
    _write_annotation_tiff(Path(original_tiff), effective, out_path)

    return {
        "found": {
            "TOP_y":        bool(np.any(~np.isnan(TOP_rel))),
            "ONL_y":        bool(np.any(~np.isnan(ONL_rel))),
            "BM_y":         bool(np.any(~np.isnan(BM_rel))),
            "DET_top_y":    bool(np.any(~np.isnan(DET_top_rel))),
            "DET_bottom_y": bool(np.any(~np.isnan(DET_bot_rel))),
        },
        "out_path": str(out_path),
    }


def convert_legacy_folder(legacy_dir: str | Path,
                            original_image_dir: str | Path,
                            out_dir: str | Path,
                            *,
                            progress_callback=None) -> dict:
    """Convert every ``*_annotation.tiff`` / ``*_annotation.tif`` in
    ``legacy_dir`` and write HITL-coloured versions to ``out_dir``.

    Each legacy file's stem (minus ``_annotation``) is matched against
    a TIFF in ``original_image_dir`` (the un-annotated source TIFFs).
    Output filenames use ``_annotation_hitl.tiff`` to make it obvious
    they're the converted variants.

    ``progress_callback(i, n, name)`` is fired before each file.

    Returns ``{"converted": N, "skipped_no_source": M, "details": [...]}``.
    """
    legacy_dir = Path(legacy_dir)
    original_image_dir = Path(original_image_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    legacy_files = sorted(
        list(legacy_dir.glob("*_annotation.tiff"))
        + list(legacy_dir.glob("*_annotation.tif"))
    )
    converted = 0
    skipped_no_source = 0
    details: list[dict] = []

    for i, legacy_p in enumerate(legacy_files, 1):
        stem = legacy_p.name
        for suffix in ("_annotation.tiff", "_annotation.tif"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        if progress_callback is not None:
            try:
                progress_callback(i, len(legacy_files), legacy_p.name)
            except Exception:
                pass
        # Find the un-annotated source TIFF.
        source = None
        for ext in (".tif", ".tiff", ".TIF", ".TIFF"):
            cand = original_image_dir / f"{stem}{ext}"
            if cand.exists():
                source = cand
                break
        if source is None:
            skipped_no_source += 1
            details.append({
                "stem": stem,
                "status": "skipped_no_source",
            })
            continue
        out_path = out_dir / f"{stem}_annotation_hitl.tiff"
        try:
            result = convert_legacy_annotation(legacy_p, source, out_path)
            details.append({
                "stem": stem,
                "status": "ok",
                "out_path": result["out_path"],
                "found": result["found"],
            })
            converted += 1
        except Exception as e:
            details.append({
                "stem": stem,
                "status": "error",
                "error": str(e),
            })

    return {
        "converted": converted,
        "skipped_no_source": skipped_no_source,
        "total_legacy_files": len(legacy_files),
        "details": details,
    }
