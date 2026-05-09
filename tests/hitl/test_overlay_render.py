"""overlay_render writes a corrected overlay PNG by reusing viz.save_overlay."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from src.hitl.overlay_render import render_corrected_overlay

# `io_utils` lives under `src/`; import it the same way the analyzer does so
# we can compute the expected B-scan-local width for the sample image.
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from io_utils import load_oct  # noqa: E402


def test_render_writes_png(tmp_path, sample_image_path):
    """Boundary arrays are B-scan-local width — same convention the analyzer
    emits and `viz.save_overlay` consumes."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1

    boundaries = {
        "TOP_y": np.full(w, 100.0),
        "ONL_y": np.full(w, 130.0),
        "BM_y": np.full(w, 160.0),
        "DET_top_y": np.full(w, np.nan),
        "DET_bottom_y": np.full(w, np.nan),
    }
    out = tmp_path / "test_overlay_corrected.png"
    result = render_corrected_overlay(sample_image_path, boundaries, out)

    assert result == out
    assert out.exists()
    arr = np.array(Image.open(out))
    # Original image is RGB; renderer should preserve that.
    assert arr.ndim == 3 and arr.shape[2] == 3
    # The image should match the source TIFF's spatial dimensions.
    assert arr.shape[:2] == img.rgb.shape[:2]

    # Sanity: the TOP boundary (green) should be drawn at y=100+top_y on
    # at least one column inside the panel, proving the renderer ran.
    y_top = img.layout.top_y + 100
    x_mid = img.layout.left_x + w // 2
    # COLOR_TOP from src/viz.py is (0, 230, 0).
    assert tuple(arr[y_top, x_mid]) == (0, 230, 0)
