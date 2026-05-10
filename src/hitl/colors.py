"""Single source of truth for boundary line colours.

Used by:
  - canvas.OverlayCanvas — drawing lines on the GUI
  - export_annotations._write_annotation_tiff — colours of the
    exported annotation TIFFs (kept identical to the editor's so
    "what you see is what you save")
  - gt_guided._mask_* — re-parses exported TIFFs back into per-column
    y arrays for accuracy reporting

The colours are distinct, high-saturation hues so simple per-channel
thresholds re-parse them reliably without confusing them with the
grayscale OCT content underneath.
"""
from __future__ import annotations


# RGB tuples (uint8).
BOUNDARY_COLORS: dict[str, tuple[int, int, int]] = {
    "TOP_y":        (255, 64, 64),    # red
    "ONL_y":        (64, 255, 64),    # green
    "BM_y":         (64, 128, 255),   # blue
    "DET_top_y":    (255, 255, 64),   # yellow
    "DET_bottom_y": (255, 64, 255),   # magenta
}
