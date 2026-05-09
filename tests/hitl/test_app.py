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
