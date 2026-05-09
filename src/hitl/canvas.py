"""Interactive Qt canvas for editing OCT boundaries.

`OverlayCanvas` is a `QGraphicsView` that displays the B-scan crop with
the current `effective` boundary lines drawn on top. It dispatches
mouse events to a `BoundaryEditor`:

  - DRAG mode (left-button drag): live Gaussian-falloff drag using the
    drag-session API (`begin_drag` / `update_drag` / `end_drag`) so a
    single user gesture results in exactly one undo entry. Hold Ctrl to
    pin the edit to a single column.
  - ERASE mode (left-button drag): on release, calls `apply_erase` over
    the swept x-range.

Headless test hooks `simulate_drag_to` and `simulate_erase` apply the
same edits without going through the Qt event system.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

from .boundary_model import BoundaryEditor


class EditMode(Enum):
    DRAG = "drag"
    ERASE = "erase"


# Colours used to draw each boundary line (RGB tuples for QPen).
COLORS: dict[str, tuple[int, int, int]] = {
    "TOP_y": (255, 64, 64),         # red
    "ONL_y": (64, 255, 64),         # green
    "BM_y": (64, 128, 255),         # blue
    "DET_top_y": (255, 255, 64),    # yellow
    "DET_bottom_y": (255, 64, 255), # magenta
}

# Pen width for inactive boundary lines; the active boundary is drawn thicker.
LINE_WIDTH = 1
ACTIVE_LINE_WIDTH = 2

# Gaussian sigma (in columns) used for live drags.
DRAG_SIGMA = 5.0


class OverlayCanvas(QGraphicsView):
    """Image canvas with overlaid editable boundary lines."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints())
        self.setMouseTracking(True)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._line_items: dict[str, list] = {}
        # Scene-x offset of the displayed B-scan image. Boundary arrays are
        # B-scan-local (0..width); add this to map to scene coordinates.
        self._image_offset_x: int = 0

        self.editor: Optional[BoundaryEditor] = None
        self._active: Optional[str] = None
        self._mode: EditMode = EditMode.DRAG

        # Drag state for live mouse dragging.
        self._dragging: bool = False
        self._erase_start_x: Optional[int] = None
        self._erase_last_x: Optional[int] = None

        # Right-click pan state.
        self._panning: bool = False
        self._pan_last_pos = None

    # ------------------------------------------------------------- public API

    def set_image(self, image: np.ndarray, offset_x: int = 0) -> None:
        """Display a numpy uint8 image (HxW or HxWx3) as the canvas backdrop.

        ``offset_x`` is the B-scan panel's ``left_x`` in the source TIFF.
        The pixmap is positioned at scene x=offset_x, so boundary arrays
        (which are B-scan-local, 0..width) are drawn at scene x =
        x_local + offset_x and overlay the correct region.
        """
        if image.ndim == 2:
            h, w = image.shape
            rgb = np.repeat(image[:, :, None], 3, axis=2)
        elif image.ndim == 3 and image.shape[2] == 3:
            h, w, _ = image.shape
            rgb = image
        else:
            raise ValueError(
                f"Unsupported image shape {image.shape}; expected HxW or HxWx3"
            )
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
        bytes_per_line = 3 * w
        # QImage does not own the buffer, so .copy() to make a self-owned image.
        qimg = QImage(
            rgb.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888
        ).copy()
        pixmap = QPixmap.fromImage(qimg)
        if self._pixmap_item is None:
            self._pixmap_item = self._scene.addPixmap(pixmap)
        else:
            self._pixmap_item.setPixmap(pixmap)
        self._image_offset_x = int(offset_x)
        self._pixmap_item.setPos(float(self._image_offset_x), 0.0)
        self._scene.setSceneRect(self._image_offset_x, 0, w, h)
        self._refresh_lines()

    def set_editor(self, editor: BoundaryEditor) -> None:
        self.editor = editor
        self._refresh_lines()

    def set_active_boundary(self, name: str) -> None:
        self._active = name
        self._refresh_lines()

    def set_mode(self, mode: EditMode) -> None:
        self._mode = mode

    # --------------------------------------------------------- headless hooks

    def simulate_drag_to(self, x: int, y: float,
                         single: bool = False) -> None:
        """Apply a one-shot drag without going through Qt events.

        Used by tests so the assertion can rely on the value landing
        exactly at `y` at column `x`.
        """
        if self.editor is None or self._active is None:
            return
        self.editor.apply_drag(
            self._active, int(x), float(y),
            sigma=DRAG_SIGMA, single=single,
        )
        self._refresh_lines()

    def simulate_erase(self, x_start: int, x_end: int) -> None:
        if self.editor is None or self._active is None:
            return
        self.editor.apply_erase(self._active, int(x_start), int(x_end))
        self._refresh_lines()

    # --------------------------------------------------------- mouse handling

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            # Right-click drag pans the view. Track manually so we don't
            # interfere with the left-button drag/erase flow.
            self._panning = True
            self._pan_last_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if (event.button() == Qt.LeftButton
                and self.editor is not None
                and self._active is not None):
            scene_pt = self.mapToScene(event.position().toPoint())
            # Convert scene x to B-scan-local x by subtracting the offset.
            x = int(round(scene_pt.x() - self._image_offset_x))
            y = float(scene_pt.y())
            if 0 <= x < self.editor.width:
                if self._mode is EditMode.DRAG:
                    single = bool(event.modifiers() & Qt.ControlModifier)
                    self.editor.begin_drag(
                        self._active, x, sigma=DRAG_SIGMA, single=single,
                    )
                    self.editor.update_drag(y)
                    self._dragging = True
                    self._refresh_lines()
                    return
                elif self._mode is EditMode.ERASE:
                    self._erase_start_x = x
                    self._erase_last_x = x
                    self._dragging = True
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and self._pan_last_pos is not None:
            cur = event.position().toPoint()
            delta = cur - self._pan_last_pos
            self._pan_last_pos = cur
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            event.accept()
            return
        if self._dragging and self.editor is not None and self._active is not None:
            scene_pt = self.mapToScene(event.position().toPoint())
            x = int(round(scene_pt.x() - self._image_offset_x))
            y = float(scene_pt.y())
            if self._mode is EditMode.DRAG:
                self.editor.update_drag(y)
                self._refresh_lines()
                return
            elif self._mode is EditMode.ERASE:
                if 0 <= x < self.editor.width:
                    self._erase_last_x = x
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton and self._panning:
            self._panning = False
            self._pan_last_pos = None
            self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._dragging:
            if (self._mode is EditMode.DRAG
                    and self.editor is not None):
                self.editor.end_drag()
            elif (self._mode is EditMode.ERASE
                    and self.editor is not None
                    and self._active is not None
                    and self._erase_start_x is not None
                    and self._erase_last_x is not None):
                self.editor.apply_erase(
                    self._active,
                    self._erase_start_x,
                    self._erase_last_x,
                )
            self._dragging = False
            self._erase_start_x = None
            self._erase_last_x = None
            self._refresh_lines()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Ctrl + wheel zooms the view; plain wheel falls through to default.
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle == 0:
                return
            factor = 1.25 if angle > 0 else 1 / 1.25
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------- rendering

    def _clear_lines(self) -> None:
        for items in self._line_items.values():
            for item in items:
                self._scene.removeItem(item)
        self._line_items = {}

    def _refresh_lines(self) -> None:
        """Redraw all boundary line segments from the editor's effective values."""
        self._clear_lines()
        if self.editor is None:
            return
        for name in self.editor.auto.keys():
            arr = self.editor.effective(name)
            color = COLORS.get(name, (255, 255, 255))
            pen_width = (
                ACTIVE_LINE_WIDTH if name == self._active else LINE_WIDTH
            )
            pen = QPen()
            pen.setColor(QColor(*color))
            pen.setWidth(pen_width)
            pen.setCosmetic(True)
            items = []
            # Draw connected line segments between adjacent finite points.
            # Boundary x is B-scan-local; add image offset to map to scene.
            offset = self._image_offset_x
            prev_x: Optional[int] = None
            prev_y: Optional[float] = None
            for x in range(arr.shape[0]):
                y = arr[x]
                if np.isnan(y):
                    prev_x = None
                    prev_y = None
                    continue
                if prev_x is not None and prev_y is not None:
                    item = self._scene.addLine(
                        prev_x + 0.5 + offset, prev_y,
                        x + 0.5 + offset, float(y), pen,
                    )
                    items.append(item)
                prev_x = x
                prev_y = float(y)
            self._line_items[name] = items
