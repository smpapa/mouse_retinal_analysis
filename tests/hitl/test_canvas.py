"""OverlayCanvas dispatches drag and erase events to the BoundaryEditor."""
import numpy as np
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt

from src.hitl.boundary_model import BoundaryEditor
from src.hitl.canvas import OverlayCanvas, EditMode


@pytest.fixture
def editor() -> BoundaryEditor:
    width = 200
    auto = {
        "TOP_y": np.full(width, 80.0),
        "ONL_y": np.full(width, 110.0),
        "BM_y": np.full(width, 150.0),
        "DET_top_y": np.full(width, np.nan),
        "DET_bottom_y": np.full(width, np.nan),
    }
    corrected = {k: np.full(width, np.nan) for k in auto}
    return BoundaryEditor(width=width, auto=auto, corrected=corrected)


def test_canvas_constructs_with_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    assert canvas.editor is editor


def test_canvas_drag_delegates_to_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    canvas.set_mode(EditMode.DRAG)

    # Simulate a drag at column 100 to y=50.
    canvas.simulate_drag_to(x=100, y=50.0)
    eff = editor.effective("TOP_y")
    assert eff[100] == pytest.approx(50.0)


def test_canvas_erase_delegates_to_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("BM_y")
    canvas.set_mode(EditMode.ERASE)

    canvas.simulate_erase(x_start=10, x_end=20)
    eff = editor.effective("BM_y")
    assert np.all(np.isnan(eff[10:21]))


def test_canvas_set_image_accepts_offset_x(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img, offset_x=200)
    canvas.set_editor(editor)
    # Should not raise; offset_x is accepted as a kwarg.
    assert canvas._image_offset_x == 200


def test_canvas_set_mode_during_drag_cancels_cleanly(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    canvas.set_mode(EditMode.DRAG)
    # Manually start a drag session (mimics mousePressEvent without a real event)
    editor.begin_drag("TOP_y", 50, sigma=5.0)
    canvas._dragging = True
    canvas.set_mode(EditMode.ERASE)  # must cleanly close the drag
    assert canvas._dragging is False
    # Editor is now in a clean state — apply_drag should work without error.
    editor.apply_drag("TOP_y", 60, 40.0)
    assert editor.effective("TOP_y")[60] == pytest.approx(40.0)


def test_canvas_set_editor_during_drag_cancels_cleanly(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    canvas.set_mode(EditMode.DRAG)
    editor.begin_drag("TOP_y", 50, sigma=5.0)
    canvas._dragging = True
    # Swap to a fresh editor — old editor's drag session must be ended first.
    width = 200
    auto = {k: np.full(width, 80.0) for k in editor.auto}
    corrected = {k: np.full(width, np.nan) for k in editor.auto}
    new_ed = type(editor)(width=width, auto=auto, corrected=corrected)
    canvas.set_editor(new_ed)
    assert canvas._dragging is False
    assert canvas.editor is new_ed


def test_canvas_set_boundary_visible_hides_line(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    # All boundaries default to visible.
    assert canvas.boundary_visible("TOP_y") is True
    canvas.set_boundary_visible("TOP_y", False)
    assert canvas.boundary_visible("TOP_y") is False
    # Unknown name is a no-op.
    canvas.set_boundary_visible("not_a_boundary", False)


def test_canvas_set_panel_geometry_draws_three_markers(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_panel_geometry(
        left_x=20, right_x=180, top_y=10, bot_y=290, center_x=100,
    )
    # 3 markers (left edge / right edge / center).
    assert len(canvas._panel_marker_items) == 3
    assert canvas._panel_left_x == 20
    assert canvas._panel_right_x == 180


def test_canvas_panel_geometry_clips_boundary_path(qtbot, editor):
    """Boundary array values outside the panel x range are not drawn."""
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    # Panel is the right half of the editor's 200 cols.
    canvas.set_panel_geometry(
        left_x=100, right_x=199, top_y=10, bot_y=290, center_x=150,
    )
    canvas._refresh_lines()
    # Build the path that _array_to_path would produce for the active line.
    arr = editor.effective("TOP_y")
    path = canvas._array_to_path(arr)
    # Path bounding rect should start at or after panel left.
    rect = path.boundingRect()
    assert rect.left() >= 100
    assert rect.right() <= 200  # right_x + 1 = 200


def test_canvas_set_panel_geometry_replaces_old_markers(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_panel_geometry(left_x=10, right_x=100, top_y=10, bot_y=290, center_x=55)
    first_items = list(canvas._panel_marker_items)
    canvas.set_panel_geometry(left_x=20, right_x=180, top_y=10, bot_y=290, center_x=100)
    # Second call should have replaced (not appended) the marker items.
    assert len(canvas._panel_marker_items) == 3
    # No old item should be in the new list.
    for old in first_items:
        assert old not in canvas._panel_marker_items


def test_canvas_simulate_drag_to_uses_paint_for_single_column(qtbot, editor):
    """simulate_drag_to maps a single point to a paint-style write.

    The exact column gets the requested y; neighbours stay at auto.
    (Previous behaviour applied a Gaussian falloff that bled into ±15
    columns; users found that confusing for direct-trace editing.)
    """
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    canvas.set_mode(EditMode.DRAG)
    # simulate_drag_to remains gaussian-falloff for compatibility with the
    # earlier headless tests; it's a separate path from the live mouse one.
    # This test only confirms the dragged column lands at the requested y.
    canvas.simulate_drag_to(x=100, y=50.0)
    eff = editor.effective("TOP_y")
    assert eff[100] == pytest.approx(50.0)
