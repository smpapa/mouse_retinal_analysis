"""Render an overlay PNG using corrected boundary arrays.

Thin wrapper around the existing renderer (`src/viz.py`). The boundary
arrays passed in are *B-scan-relative* coordinates (same convention as
the analyzer's `BoundaryResult`): per-column y-positions inside the
B-scan crop, with NaN meaning "no value here / unreadable column".

Expected dict keys: ``TOP_y``, ``ONL_y``, ``BM_y``, ``DET_top_y``,
``DET_bottom_y``. DET keys may be omitted (or all-NaN); detachment is
inferred by checking whether ``DET_top_y`` has any finite entries.

Array length should match the B-scan-local width
(``layout.right_x - layout.left_x + 1``). Mismatches are normalised:
shorter arrays are padded with NaN, longer arrays are truncated, so
callers do not have to compute the local width themselves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Make the existing analyzer modules importable. They live under `src/`
# and reference each other with package-less imports
# (`from io_utils import ...`), so we add `src/` to sys.path here.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from io_utils import load_oct                     # noqa: E402
from oct_analyzer import BoundaryResult           # noqa: E402
from viz import save_overlay                      # noqa: E402


_BOUNDARY_KEYS = ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y")


def _fit_to_width(arr: np.ndarray | None, width: int) -> np.ndarray:
    """Return a length-`width` float32 array; pad with NaN or truncate."""
    if arr is None:
        return np.full(width, np.nan, dtype=np.float32)
    a = np.asarray(arr, dtype=np.float32)
    if a.shape[0] == width:
        return a
    if a.shape[0] > width:
        return a[:width].copy()
    out = np.full(width, np.nan, dtype=np.float32)
    out[: a.shape[0]] = a
    return out


def render_corrected_overlay(image_path: str | Path,
                             boundaries: dict[str, np.ndarray],
                             out_path: str | Path) -> Path:
    """Render an overlay PNG using the supplied (corrected) boundary arrays.

    Parameters
    ----------
    image_path : path to the source TIFF.
    boundaries : dict with keys ``TOP_y / ONL_y / BM_y / DET_top_y / DET_bottom_y``.
                 Missing keys are treated as all-NaN.
    out_path   : destination PNG path. Parent directories will be created.

    Returns
    -------
    The path returned by :func:`viz.save_overlay` (same as ``out_path``).
    """
    img = load_oct(image_path)
    w = img.layout.width

    fitted = {k: _fit_to_width(boundaries.get(k), w) for k in _BOUNDARY_KEYS}

    has_det = bool(np.any(np.isfinite(fitted["DET_top_y"])))

    b = BoundaryResult(
        TOP=fitted["TOP_y"],
        ONL=fitted["ONL_y"],
        BM=fitted["BM_y"],
        DET_top=fitted["DET_top_y"],
        DET_bottom=fitted["DET_bottom_y"],
        has_detachment=has_det,
        center_x_local=img.layout.center_x - img.layout.left_x,
    )
    return save_overlay(img, b, out_path)
