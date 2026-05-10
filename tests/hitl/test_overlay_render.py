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
    """Boundary arrays carry **absolute** image y coordinates (the same
    convention `batch_process.py` writes to the xlsx and what the HITL
    DB stores). render_corrected_overlay subtracts layout.top_y itself
    before handing them to viz.save_overlay."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1
    top_y = img.layout.top_y

    # Pick absolute y values within the panel.
    target_top_y = top_y + 100
    boundaries = {
        "TOP_y": np.full(w, float(target_top_y)),
        "ONL_y": np.full(w, float(top_y + 130)),
        "BM_y":  np.full(w, float(top_y + 160)),
        "DET_top_y":    np.full(w, np.nan),
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

    # Sanity: the TOP boundary (green) should be drawn at the absolute
    # y the caller asked for (no double-offset).
    x_mid = img.layout.left_x + w // 2
    # COLOR_TOP from src/viz.py is (0, 230, 0).
    assert tuple(arr[target_top_y, x_mid]) == (0, 230, 0)


def test_render_draws_detachment_when_DET_present(tmp_path, sample_image_path):
    """Finite DET arrays should produce yellow (DET_top) pixels in the output."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1
    top_y = img.layout.top_y

    boundaries = {
        "TOP_y":        np.full(w, float(top_y + 100)),
        "ONL_y":        np.full(w, float(top_y + 130)),
        "BM_y":         np.full(w, float(top_y + 170)),
        "DET_top_y":    np.full(w, np.nan),
        "DET_bottom_y": np.full(w, np.nan),
    }
    mid = w // 2
    boundaries["DET_top_y"][mid - 100 : mid + 100] = float(top_y + 145)
    boundaries["DET_bottom_y"][mid - 100 : mid + 100] = float(top_y + 165)

    out = tmp_path / "det_overlay.png"
    render_corrected_overlay(sample_image_path, boundaries, out)

    arr = np.array(Image.open(out))
    y_det_top = top_y + 145
    x_mid = img.layout.left_x + mid
    # COLOR_DET_TOP = (255, 230, 0) from src/viz.py
    assert tuple(arr[y_det_top, x_mid]) == (255, 230, 0)


def test_render_handles_width_mismatch(tmp_path, sample_image_path):
    """Shorter arrays should be NaN-padded; longer arrays should be truncated."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1
    top_y = img.layout.top_y

    # Pass arrays that are too short — padding region should have no boundary
    # pixels (NaN is silently skipped by viz.save_overlay).
    short_w = w - 50
    boundaries = {
        "TOP_y": np.full(short_w, float(top_y + 100)),
        "ONL_y": np.full(short_w, float(top_y + 130)),
        "BM_y":  np.full(short_w, float(top_y + 160)),
        "DET_top_y":    np.full(short_w, np.nan),
        "DET_bottom_y": np.full(short_w, np.nan),
    }
    out = tmp_path / "short_overlay.png"
    render_corrected_overlay(sample_image_path, boundaries, out)

    arr = np.array(Image.open(out))
    y_top = top_y + 100
    # Inside the populated range: green pixel present.
    x_inside = img.layout.left_x + (short_w // 2)
    assert tuple(arr[y_top, x_inside]) == (0, 230, 0)
    # Past the populated range (last 50 cols): no green pixel.
    x_past = img.layout.left_x + (w - 5)
    assert tuple(arr[y_top, x_past]) != (0, 230, 0)


def test_render_tolerates_missing_DET_keys(tmp_path, sample_image_path):
    """Calling with only TOP/ONL/BM should work; DET keys default to all-NaN."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1
    top_y = img.layout.top_y

    boundaries = {
        "TOP_y": np.full(w, float(top_y + 100)),
        "ONL_y": np.full(w, float(top_y + 130)),
        "BM_y":  np.full(w, float(top_y + 160)),
        # DET_top_y and DET_bottom_y intentionally absent.
    }
    out = tmp_path / "no_det_overlay.png"
    # Should not raise.
    render_corrected_overlay(sample_image_path, boundaries, out)

    arr = np.array(Image.open(out))
    # Confirm no DET-yellow pixels anywhere in the panel area.
    panel = arr[img.layout.top_y : img.layout.bot_y + 1,
                img.layout.left_x : img.layout.right_x + 1]
    is_yellow = ((panel[..., 0] == 255) & (panel[..., 1] == 230)
                 & (panel[..., 2] == 0))
    assert not is_yellow.any()


def test_render_handles_all_nan_TOP(tmp_path, sample_image_path):
    """All-NaN TOP boundary should not raise and should draw no green pixels."""
    img = load_oct(sample_image_path)
    w = img.layout.right_x - img.layout.left_x + 1
    top_y = img.layout.top_y

    boundaries = {
        "TOP_y": np.full(w, np.nan),
        "ONL_y": np.full(w, float(top_y + 130)),
        "BM_y":  np.full(w, float(top_y + 160)),
        "DET_top_y":    np.full(w, np.nan),
        "DET_bottom_y": np.full(w, np.nan),
    }
    out = tmp_path / "nan_top_overlay.png"
    render_corrected_overlay(sample_image_path, boundaries, out)

    arr = np.array(Image.open(out))
    panel = arr[img.layout.top_y : img.layout.bot_y + 1,
                img.layout.left_x : img.layout.right_x + 1]
    # No green TOP pixels anywhere.
    is_green_top = ((panel[..., 0] == 0) & (panel[..., 1] == 230)
                    & (panel[..., 2] == 0))
    assert not is_green_top.any()
    # ONL (cyan) still drawn.
    is_cyan = ((panel[..., 0] == 0) & (panel[..., 1] == 220)
               & (panel[..., 2] == 220))
    assert is_cyan.any()
