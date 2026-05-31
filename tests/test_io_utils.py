"""B-scan panel layout detection — horizontal AND vertical scan markers.

The original detector only looked at row green-pixel counts and worked
on horizontal scans. Vertical scans (filename suffix V) carry the
scan-position marker as a vertical line, so the row-only signal misses
them entirely. These tests pin down the universal detector behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from io_utils import _bscan_left_edge_via_green_markers


# Image canvas matching the project's Heidelberg layout (596×2032).
H, W = 596, 2032
GREEN = (0, 255, 0)
PANEL_RIGHT = 495  # canonical IR-panel side length for this device


def _blank() -> np.ndarray:
    return np.zeros((H, W, 3), dtype=np.uint8)


def test_detect_horizontal_scan_marker_at_canonical_position():
    """H scan: a single horizontal green line at y=248 spanning x=1..495."""
    rgb = _blank()
    rgb[248, 1:PANEL_RIGHT + 1] = GREEN
    edge = _bscan_left_edge_via_green_markers(rgb)
    assert edge == PANEL_RIGHT + 1


def test_detect_vertical_scan_marker_at_canonical_position():
    """V scan: a single vertical green line at x=248 spanning y=0..495.

    Regression: the original detector returned None for this case
    because it only looked at row green-pixel counts.
    """
    rgb = _blank()
    rgb[0:PANEL_RIGHT + 1, 248] = GREEN
    edge = _bscan_left_edge_via_green_markers(rgb)
    assert edge == PANEL_RIGHT + 1


def test_returns_none_when_no_scan_markers():
    """An image with no pure-green pixels (e.g. annotated/grayscale-only)
    must return None so the dark-bg fallback can take over."""
    rgb = _blank()
    rgb[100:300, 100:300] = (128, 128, 128)
    assert _bscan_left_edge_via_green_markers(rgb) is None


def test_ignores_scattered_green_text_labels():
    """Small green text fragments (e.g. status text) at the top of the
    IR panel must not be mistaken for the scan-position marker."""
    rgb = _blank()
    # Tiny green clusters under the threshold (mimics text characters).
    rgb[10, 5:25] = GREEN
    rgb[15, 5:25] = GREEN
    assert _bscan_left_edge_via_green_markers(rgb) is None


def test_picks_dominant_orientation():
    """When both a long row and a long column have green pixels the
    detector picks whichever has more — but in practice both axes are
    ≤495 so either is correct here."""
    rgb = _blank()
    # Horizontal marker, 495 wide.
    rgb[248, 1:PANEL_RIGHT + 1] = GREEN
    # Smaller vertical decoration (not a scan marker).
    rgb[0:100, 50] = GREEN
    edge = _bscan_left_edge_via_green_markers(rgb)
    assert edge == PANEL_RIGHT + 1


@pytest.mark.parametrize("rel_path", [
    "data/mouse_data_org/21_OS_4H.tif",
])
def test_integration_horizontal_real_image(rel_path):
    """Real project image, horizontal scan — sanity check the universal
    detector still produces the canonical x=496 for the original dataset."""
    from PIL import Image
    p = Path(__file__).resolve().parents[1] / rel_path
    if not p.exists():
        pytest.skip(f"{p} not present")
    rgb = np.asarray(Image.open(str(p)).convert("RGB"), dtype=np.uint8)
    assert _bscan_left_edge_via_green_markers(rgb) == 496
