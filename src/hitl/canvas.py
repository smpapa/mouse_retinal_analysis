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
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
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

    # Emitted after a user edit completes (drag end or erase apply) so
    # external observers (e.g. the main window status bar) can refresh.
    edit_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints())
        self.setMouseTracking(True)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        # One QGraphicsPathItem per boundary, reused across refreshes via
        # setPath. Avoids re-creating thousands of QGraphicsLineItems on
        # every drag mousemove.
        self._line_items: dict[str, QGraphicsPathItem] = {}
        # Per-boundary visibility (rendering only — underlying data unchanged).
        self._visible: dict[str, bool] = {name: True for name in COLORS}
        # Scene-x offset of the displayed B-scan image. Boundary arrays are
        # B-scan-local (0..width); add this to map to scene coordinates.
        self._image_offset_x: int = 0
        # B-scan panel x range. When set, boundary lines are clipped to
        # [left_x, right_x] (so they do not bleed onto the IR fundus area)
        # and three vertical marker lines mirror the automatic overlay.
        self._panel_left_x: Optional[int] = None
        self._panel_right_x: Optional[int] = None
        self._panel_marker_items: list[QGraphicsLineItem] = []

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

        ``offset_x`` is the B-scan panel's ``left_x`` in the source TIFF
        (image coordinate where the panel begins; the IR fundus lives to
        its left). It is used purely as the offset to add to B-scan-local
        boundary x indices when mapping them onto the pixmap.

        The pixmap itself is placed at scene origin (0, 0) so the IR fundus
        and the B-scan panel both occupy their natural positions in the
        TIFF — the pixmap is the source TIFF unmodified.
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
        # Pixmap at scene (0, 0). offset_x is *not* a position; it is the
        # boundary coordinate offset (panel start) inside the pixmap.
        self._pixmap_item.setPos(0.0, 0.0)
        self._scene.setSceneRect(0, 0, w, h)
        self._refresh_lines()

    def set_editor(self, editor: BoundaryEditor) -> None:
        self._cancel_drag_if_any()
        self.editor = editor
        self._refresh_lines()

    def set_active_boundary(self, name: str) -> None:
        self._active = name
        self._refresh_lines()

    def set_mode(self, mode: EditMode) -> None:
        self._cancel_drag_if_any()
        self._mode = mode

    def refresh(self) -> None:
        """Public re-render hook for callers that mutated the editor externally."""
        self._refresh_lines()

    def set_boundary_visible(self, name: str, visible: bool) -> None:
        """Show/hide a boundary line. Underlying data is untouched."""
        if name not in self._visible:
            return  # silent: ignore unknown names
        self._visible[name] = bool(visible)
        # Refresh the affected line item only.
        item = self._line_items.get(name)
        if item is not None:
            item.setVisible(self._visible[name])

    def boundary_visible(self, name: str) -> bool:
        return self._visible.get(name, True)

    def _cancel_drag_if_any(self) -> None:
        """Cleanly close any in-progress drag/pan so external state changes are safe."""
        if self._dragging and self.editor is not None and self._mode is EditMode.DRAG:
            # Live drag uses the paint API; close that session too.
            self.editor.end_paint()
            self.editor.end_drag()
        self._dragging = False
        if self._panning:
            self.unsetCursor()
            self._panning = False
            self._pan_last_pos = None

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
        self.edit_finished.emit()

    def simulate_erase(self, x_start: int, x_end: int) -> None:
        if self.editor is None or self._active is None:
            return
        self.editor.apply_erase(self._active, int(x_start), int(x_end))
        self._refresh_lines()
        self.edit_finished.emit()

    # --------------------------------------------------------- mouse handling

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # We treat one gesture at a time. The first button down wins until
        # released — a second button while another is active is ignored.
        if event.button() == Qt.RightButton:
            if self._dragging:
                # Left-drag is in flight; ignore right-button to keep one
                # gesture active at a time.
                event.accept()
                return
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
            if self._panning:
                # Pan is in flight; ignore left-button until the right
                # button is released.
                event.accept()
                return
            scene_pt = self.mapToScene(event.position().toPoint())
            # Convert scene x to B-scan-local x by subtracting the offset.
            x = int(round(scene_pt.x() - self._image_offset_x))
            y = float(scene_pt.y())
            if 0 <= x < self.editor.width:
                if self._mode is EditMode.DRAG:
                    # Live drag uses paint-trace: the boundary follows the
                    # mouse path exactly. Pressing without moving still
                    # writes the press column with the press y.
                    self.editor.begin_paint(self._active, x, y)
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
                # Paint-trace: write every column between the previous and
                # current mouse position by linear interpolation.
                self.editor.paint_to(x, y)
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
                self.editor.end_paint()
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
            self.edit_finished.emit()
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

    def _refresh_lines(self) -> None:
        """Update each boundary's QGraphicsPathItem to match the editor."""
        if self.editor is None:
            return
        for name in COLORS:
            if name not in self.editor.auto:
                continue
            arr = self.editor.effective(name)
            path = self._array_to_path(arr)
            item = self._line_items.get(name)
            if item is None:
                r, g, b = COLORS[name]
                item = QGraphicsPathItem(path)
                pen = QPen(QColor(r, g, b))
                pen.setWidthF(LINE_WIDTH)
                pen.setCosmetic(True)
                item.setPen(pen)
                item.setZValue(10)
                self._scene.addItem(item)
                self._line_items[name] = item
            else:
                item.setPath(path)
            # Active boundary gets a thicker pen.
            is_active = (name == self._active)
            pen = item.pen()
            pen.setWidthF(ACTIVE_LINE_WIDTH if is_active else LINE_WIDTH)
            item.setPen(pen)
            # Apply current visibility (covers newly-created items too).
            item.setVisible(self._visible[name])

    def _array_to_path(self, arr: np.ndarray) -> QPainterPath:
        path = QPainterPath()
        prev_valid = False
        offset = self._image_offset_x
        left = self._panel_left_x
        right = self._panel_right_x
        for x_local, y in enumerate(arr):
            if np.isnan(y):
                prev_valid = False
                continue
            x = x_local + offset + 0.5
            # Clip to panel x range when defined so boundary lines do not
            # bleed onto the IR fundus area on the left.
            if left is not None and x < left:
                prev_valid = False
                continue
            if right is not None and x > right + 1:
                prev_valid = False
                continue
            yf = float(y) + 0.5
            if not prev_valid:
                path.moveTo(x, yf)
                prev_valid = True
            else:
                path.lineTo(x, yf)
        return path

    def set_panel_geometry(self, left_x: int, right_x: int,
                           top_y: int, bot_y: int, center_x: int) -> None:
        """Mark the B-scan panel range and draw start/center/end markers.

        Boundary line rendering is clipped to ``[left_x, right_x]`` so the
        lines do not bleed onto the IR fundus area. Three vertical marker
        lines are drawn (red solid for left/right edges, yellow dashed for
        the geometric center) to mirror the automatic overlay PNG.
        """
        self._panel_left_x = int(left_x)
        self._panel_right_x = int(right_x)
        # Remove any previous marker items.
        for item in self._panel_marker_items:
            self._scene.removeItem(item)
        self._panel_marker_items.clear()
        # Edge markers: solid red lines (matches viz.COLOR_BSCAN_EDGE).
        edge_pen = QPen(QColor(255, 80, 80))
        edge_pen.setWidthF(1.5)
        edge_pen.setCosmetic(True)
        # Center marker: dashed yellow line (matches viz.COLOR_CENTER).
        center_pen = QPen(QColor(255, 255, 0))
        center_pen.setWidthF(1.5)
        center_pen.setCosmetic(True)
        center_pen.setStyle(Qt.DashLine)
        for x, pen in (
            (int(left_x), edge_pen),
            (int(right_x), edge_pen),
            (int(center_x), center_pen),
        ):
            item = self._scene.addLine(
                float(x) + 0.5, float(top_y),
                float(x) + 0.5, float(bot_y),
                pen,
            )
            # Below the boundary line items (z=10).
            item.setZValue(5)
            self._panel_marker_items.append(item)
        # Re-clip existing boundary lines.
        self._refresh_lines()
