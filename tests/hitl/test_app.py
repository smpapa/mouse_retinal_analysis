"""MainWindow ties storage + sidebar + canvas together."""
import shutil

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pytestqt")

from src.hitl.app import MainWindow


def test_mainwindow_loads_workbook_into_sidebar(qtbot, tmp_path,
                                                oct_results_xlsx,
                                                sample_image_stem):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst,
                     image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    assert win.sidebar.count() >= 1
    # Picking the first image populates the canvas with the editor.
    win.sidebar.setCurrentRow(0)
    assert win.canvas.editor is not None


def test_mainwindow_save_persists_corrections(qtbot, tmp_path,
                                              oct_results_xlsx,
                                              sample_image_stem):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst,
                     image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.select_image(sample_image_stem)
    # Programmatically edit and save.
    win.canvas.set_active_boundary("TOP_y")
    win.canvas.simulate_drag_to(x=0, y=99.0)
    win.save_current_image()
    df = pd.read_excel(dst, sheet_name=sample_image_stem)
    assert df["TOP_y_corrected"].iloc[0] == pytest.approx(99.0)


def test_mainwindow_undo_reverts_edit(qtbot, tmp_path, oct_results_xlsx,
                                      sample_image_stem):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst,
                     image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.select_image(sample_image_stem)
    editor = win._editors[sample_image_stem]
    before = editor.effective("TOP_y").copy()
    win.canvas.set_active_boundary("TOP_y")
    win.canvas.simulate_drag_to(x=0, y=99.0)
    assert editor.effective("TOP_y")[0] == pytest.approx(99.0)
    win._undo()
    assert np.allclose(editor.effective("TOP_y"), before, equal_nan=True)


def test_mainwindow_arrow_keys_navigate(qtbot, tmp_path, oct_results_xlsx):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst,
                     image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.show()
    win.sidebar.setCurrentRow(0)
    first_stem = win.sidebar._stem_for_row[0]
    second_stem = win.sidebar._stem_for_row[1]
    assert win._current_stem == first_stem
    win._next_image()
    assert win._current_stem == second_stem
    win._prev_image()
    assert win._current_stem == first_stem


def test_mainwindow_drag_action_mutually_exclusive_with_erase(qtbot, tmp_path,
                                                              oct_results_xlsx):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst,
                     image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    # Start with drag checked
    assert win.act_drag.isChecked() is True
    win.act_erase.trigger()
    assert win.act_erase.isChecked() is True
    assert win.act_drag.isChecked() is False


def test_mainwindow_close_event_with_dirty_editor_aborts_on_cancel(qtbot, tmp_path,
                                                                    oct_results_xlsx,
                                                                    sample_image_stem,
                                                                    monkeypatch):
    """closeEvent should ignore the close when user cancels the prompt."""
    from PySide6.QtWidgets import QMessageBox
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst, image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.select_image(sample_image_stem)
    # Make the editor dirty.
    win.canvas.set_active_boundary("TOP_y")
    win.canvas.simulate_drag_to(x=0, y=99.0)
    assert win._editors[sample_image_stem].dirty is True

    # Stub QMessageBox.question to return Cancel.
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **kw: QMessageBox.Cancel))

    from PySide6.QtGui import QCloseEvent
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted()


def test_mainwindow_select_image_handles_missing_tiff(qtbot, tmp_path,
                                                      oct_results_xlsx):
    """A missing TIFF should set a status message, not crash."""
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    # Point image_dir at an empty folder so all TIFFs are missing.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    win = MainWindow(workbook_path=dst, image_dir=empty_dir)
    qtbot.addWidget(win)
    # Pick the first image — load_oct will raise FileNotFoundError.
    first_stem = win.sidebar._stem_for_row[0]
    win.select_image(first_stem)
    # Should not have advanced _current_stem to the broken image.
    assert win._current_stem is None
    # Status bar should mention the failure.
    msg = win.statusBar().currentMessage()
    assert "Could not load" in msg or "could not load" in msg.lower()


def test_mainwindow_boundary_toggle_hides_canvas_line(qtbot, tmp_path,
                                                      oct_results_xlsx,
                                                      sample_image_stem):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst, image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.select_image(sample_image_stem)
    # Toggle TOP off via the toolbar's boundary toggle bar.
    win.boundary_toggle._boxes["TOP_y"].setChecked(False)
    assert win.canvas.boundary_visible("TOP_y") is False
    # Other boundaries still visible.
    assert win.canvas.boundary_visible("ONL_y") is True


def test_mainwindow_select_image_sets_panel_geometry(qtbot, tmp_path,
                                                     oct_results_xlsx,
                                                     sample_image_stem):
    """MainWindow should pass the OctImage layout into the canvas so
    boundary lines clip to the B-scan panel and start/center/end markers
    appear, matching the automatic overlay PNG."""
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    win = MainWindow(workbook_path=dst, image_dir=oct_results_xlsx.parent.parent)
    qtbot.addWidget(win)
    win.select_image(sample_image_stem)
    assert win.canvas._panel_left_x is not None
    assert win.canvas._panel_right_x is not None
    assert win.canvas._panel_left_x < win.canvas._panel_right_x
    assert len(win.canvas._panel_marker_items) == 3
