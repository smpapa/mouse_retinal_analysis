"""Render overlay images.

The overlay always:
  - draws boundaries only inside the detected B-scan panel
  - skips columns where the boundary value is NaN (gap = unreadable)
  - draws DET top/bottom only when `has_detachment` is True
  - draws a faint center line marker
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from io_utils import OctImage
from oct_analyzer import BoundaryResult


# RGB colour scheme from the spec ("README_ANALYSIS_OCT.md", §출력 이미지 규칙).
COLOR_TOP = (0, 230, 0)         # green
COLOR_ONL = (0, 220, 220)       # cyan
COLOR_BM = (230, 50, 200)       # magenta
COLOR_DET_TOP = (255, 230, 0)   # yellow
COLOR_DET_BOT = (0, 0, 0)       # black
COLOR_CENTER = (255, 255, 0)    # bright yellow (visible center line)
COLOR_BSCAN_EDGE = (255, 80, 80)  # red (visible left/right edges of B-scan)
COLOR_BSCAN_BORDER = (60, 60, 60)


def _draw_pixel(canvas: np.ndarray, y: int, x: int, color) -> None:
    if 0 <= y < canvas.shape[0] and 0 <= x < canvas.shape[1]:
        canvas[y, x] = color


def _draw_boundary(canvas: np.ndarray, ys: np.ndarray,
                   layout, color) -> None:
    """Draw one 1-px boundary inside the B-scan panel.

    `ys` is in B-scan-relative coords; we offset by `layout.top_y / left_x`.
    NaN columns are skipped.
    """
    for x_local, y_local in enumerate(ys):
        if np.isnan(y_local):
            continue
        x = layout.left_x + x_local
        y = layout.top_y + int(round(y_local))
        _draw_pixel(canvas, y, x, color)


def _draw_dashed_vline(canvas: np.ndarray, x: int, y0: int, y1: int,
                       color, dash: int = 6, thickness: int = 2) -> None:
    """Dashed vertical line, ``thickness`` pixels wide."""
    H, W = canvas.shape[:2]
    half = thickness // 2
    for y in range(y0, y1 + 1):
        if (y // dash) % 2 == 0:
            for dx in range(-half, half + thickness % 2):
                xx = x + dx
                if 0 <= xx < W and 0 <= y < H:
                    canvas[y, xx] = color


def _draw_solid_vline(canvas: np.ndarray, x: int, y0: int, y1: int,
                      color, thickness: int = 2) -> None:
    """Solid vertical line, ``thickness`` pixels wide."""
    H, W = canvas.shape[:2]
    half = thickness // 2
    for y in range(max(0, y0), min(H, y1 + 1)):
        for dx in range(-half, half + thickness % 2):
            xx = x + dx
            if 0 <= xx < W:
                canvas[y, xx] = color


def _draw_rect(canvas: np.ndarray, layout, color) -> None:
    H, W = canvas.shape[:2]
    l, r = layout.left_x, layout.right_x
    t, b = layout.top_y, layout.bot_y
    if 0 <= t < H:
        canvas[t, max(0, l):min(W, r + 1)] = color
    if 0 <= b < H:
        canvas[b, max(0, l):min(W, r + 1)] = color
    if 0 <= l < W:
        canvas[max(0, t):min(H, b + 1), l] = color
    if 0 <= r < W:
        canvas[max(0, t):min(H, b + 1), r] = color


def render_overlay(oct_image: OctImage, b: BoundaryResult) -> np.ndarray:
    """Return an HxWx3 uint8 overlay image."""
    canvas = oct_image.rgb.copy()
    l = oct_image.layout

    _draw_rect(canvas, l, COLOR_BSCAN_BORDER)
    # B-scan left/right edges as solid red vertical lines
    _draw_solid_vline(canvas, l.left_x, l.top_y, l.bot_y, COLOR_BSCAN_EDGE)
    _draw_solid_vline(canvas, l.right_x, l.top_y, l.bot_y, COLOR_BSCAN_EDGE)
    # Geometric center as a yellow dashed vertical line
    _draw_dashed_vline(canvas, l.center_x, l.top_y, l.bot_y, COLOR_CENTER)

    _draw_boundary(canvas, b.TOP, l, COLOR_TOP)
    _draw_boundary(canvas, b.ONL, l, COLOR_ONL)
    _draw_boundary(canvas, b.BM, l, COLOR_BM)

    if b.has_detachment:
        _draw_boundary(canvas, b.DET_top, l, COLOR_DET_TOP)
        _draw_boundary(canvas, b.DET_bottom, l, COLOR_DET_BOT)

    return canvas


def save_overlay(oct_image: OctImage, b: BoundaryResult,
                 out_path: str | Path) -> Path:
    canvas = render_overlay(oct_image, b)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(str(out))
    return out
