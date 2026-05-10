"""Export HITL-corrected boundaries as ML-ready annotations.

Produces two artefacts per image:
  - <out_dir>/csv/<stem>.csv
        x_local, TOP_y, ONL_y, BM_y, DET_top_y, DET_bottom_y,
        total_um, outer_um, det_um
    "Effective" values: corrected if user set, NaN if user erased,
    else auto.

  - <out_dir>/tiff/<stem>_annotation_hitl.tiff
    Original TIFF with the effective boundaries painted as 1-pixel
    coloured lines in the same scheme `gt_guided.py` expects (green
    TOP, cyan ONL, magenta BM, yellow DET top, black DET bot).
    No panel decorations are drawn so the colour masks in
    `gt_guided._mask_*` re-parse cleanly.

Selection: by default only images with at least one user correction
(`has_corrections=True` in the DB) are exported.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from .boundary_model import BOUNDARY_NAMES, ERASED_THRESHOLD
from .db import HitlDb


_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from io_utils import load_oct  # noqa: E402


# Same scheme as src/viz.py and gt_guided.py annotation masks.
_GT_COLORS: dict[str, tuple[int, int, int]] = {
    "TOP_y":        (0, 230, 0),     # green
    "ONL_y":        (0, 220, 220),   # cyan
    "BM_y":         (230, 50, 200),  # magenta
    "DET_top_y":    (255, 230, 0),   # yellow
    "DET_bottom_y": (0, 0, 0),       # black
}


def _compute_effective(auto: dict[str, np.ndarray],
                        corrected: dict[str, np.ndarray]
                        ) -> dict[str, np.ndarray]:
    """Merge auto + corrected to one effective array per boundary.

    Rules:
      - corrected is NaN  -> use auto
      - corrected is finite and >= ERASED_THRESHOLD -> override with corrected
      - corrected < ERASED_THRESHOLD (the ERASED sentinel) -> NaN
    """
    out: dict[str, np.ndarray] = {}
    for name in BOUNDARY_NAMES:
        a = auto[name].copy()
        c = corrected[name]
        finite = (~np.isnan(c)) & (c >= ERASED_THRESHOLD)
        a[finite] = c[finite]
        erased = c < ERASED_THRESHOLD
        a[erased] = np.nan
        out[name] = a
    return out


def _write_csv(out_path: Path,
                effective: dict[str, np.ndarray],
                scale_um_per_px_y: float) -> None:
    """Write a single image's effective boundaries to CSV."""
    width = effective["TOP_y"].shape[0]
    bm = effective["BM_y"]
    top = effective["TOP_y"]
    onl = effective["ONL_y"]
    det_top = effective["DET_top_y"]
    det_bot = effective["DET_bottom_y"]
    df = pd.DataFrame({
        "x_local":      np.arange(width, dtype=int),
        "TOP_y":        top,
        "ONL_y":        onl,
        "BM_y":         bm,
        "DET_top_y":    det_top,
        "DET_bottom_y": det_bot,
        "total_um":     (bm - top) * scale_um_per_px_y,
        "outer_um":     (bm - onl) * scale_um_per_px_y,
        "det_um":       (det_bot - det_top) * scale_um_per_px_y,
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)


def _write_annotation_tiff(tiff_src: Path,
                             effective: dict[str, np.ndarray],
                             out_path: Path) -> None:
    """Render an annotation TIFF that gt_guided.py's masks can re-parse.

    Draws only 1-pixel boundary lines on top of the original image —
    no panel decorations, no center marker — to keep the colour
    extraction in gt_guided clean.
    """
    img = load_oct(tiff_src)
    canvas = img.rgb.copy()
    layout = img.layout
    h, w = canvas.shape[:2]

    for name, color in _GT_COLORS.items():
        arr = effective.get(name)
        if arr is None:
            continue
        for x_local, y_local in enumerate(arr):
            if np.isnan(y_local):
                continue
            x = layout.left_x + int(x_local)
            y = layout.top_y + int(round(float(y_local)))
            if 0 <= y < h and 0 <= x < w:
                canvas[y, x] = color

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(str(out_path))


def export_annotations(db: HitlDb,
                        image_dir: str | Path,
                        out_dir: str | Path,
                        *,
                        formats: set[str] | None = None,
                        only_corrected: bool = True,
                        progress_callback=None) -> dict:
    """Export effective boundaries as CSV + annotation TIFFs.

    Parameters
    ----------
    db : open HitlDb
    image_dir : folder of source TIFFs (used by the TIFF format only)
    out_dir   : root output folder. Subfolders ``csv/`` and ``tiff/``
                are created as needed.
    formats   : subset of {"csv", "tiff"}; default both.
    only_corrected : if True (default), skip images that have no user
                     corrections in the DB.
    progress_callback : optional callable(i, n, filename) fired before
                        each image is processed.

    Returns
    -------
    dict with keys: ``csv_count``, ``tiff_count``, ``skipped_missing_tiff``.
    """
    if formats is None:
        formats = {"csv", "tiff"}
    out_dir = Path(out_dir)
    image_dir = Path(image_dir)

    images = [
        (stem, filename) for stem, filename, has_corr in db.list_images()
        if (not only_corrected) or has_corr
    ]

    csv_dir = out_dir / "csv"
    tiff_dir = out_dir / "tiff"
    if "csv" in formats:
        csv_dir.mkdir(parents=True, exist_ok=True)
    if "tiff" in formats:
        tiff_dir.mkdir(parents=True, exist_ok=True)

    csv_count = 0
    tiff_count = 0
    skipped_missing = 0

    for i, (stem, filename) in enumerate(images, 1):
        if progress_callback is not None:
            try:
                progress_callback(i, len(images), filename)
            except Exception:
                pass
        rec = db.load_image(stem)
        if rec is None:
            continue
        scale = db.get_scale(stem)
        effective = _compute_effective(rec.auto, rec.corrected)

        if "csv" in formats:
            _write_csv(csv_dir / f"{stem}.csv", effective, scale)
            csv_count += 1

        if "tiff" in formats:
            tiff_src = image_dir / filename
            if tiff_src.exists():
                _write_annotation_tiff(
                    tiff_src, effective,
                    tiff_dir / f"{stem}_annotation_hitl.tiff",
                )
                tiff_count += 1
            else:
                skipped_missing += 1

    return {
        "csv_count": csv_count,
        "tiff_count": tiff_count,
        "skipped_missing_tiff": skipped_missing,
        "total_images": len(images),
    }
