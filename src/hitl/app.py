"""Main window: sidebar + canvas + storage glue."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QMainWindow,
                                QStatusBar, QToolBar)

# Make sibling analysis modules importable.
SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from io_utils import load_oct                                       # noqa: E402

from .boundary_model import BoundaryEditor                          # noqa: E402
from .canvas import EditMode, OverlayCanvas                         # noqa: E402
from .overlay_render import render_corrected_overlay                # noqa: E402
from .sidebar import FileEntry, FileListView                        # noqa: E402
from .storage import (CorrectedSnapshot, Workbook,
                      load_workbook, save_corrections, AUTO_COLS)   # noqa: E402


class MainWindow(QMainWindow):
    def __init__(self, workbook_path, image_dir):
        super().__init__()
        self.workbook_path = Path(workbook_path)
        self.image_dir = Path(image_dir)
        self._editors: dict[str, BoundaryEditor] = {}
        self._wb: Workbook | None = None
        self._current_stem: str | None = None
        self._scale_y = 3.87  # default; overridden if summary has it.

        self._build_ui()
        self._reload_workbook()

    def _build_ui(self) -> None:
        self.setWindowTitle("OCT HITL Editor")
        self.canvas = OverlayCanvas()
        self.setCentralWidget(self.canvas)

        self.sidebar = FileListView()
        self.sidebar.image_selected.connect(self.select_image)
        dock = QDockWidget("Files", self)
        dock.setWidget(self.sidebar)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        toolbar = QToolBar("Edit", self)
        self.addToolBar(toolbar)

        self.act_drag = QAction("Drag", self)
        self.act_drag.setCheckable(True)
        self.act_drag.setChecked(True)
        self.act_drag.triggered.connect(
            lambda: self.canvas.set_mode(EditMode.DRAG))
        self.act_erase = QAction("Erase", self)
        self.act_erase.setCheckable(True)
        self.act_erase.triggered.connect(
            lambda: self.canvas.set_mode(EditMode.ERASE))
        toolbar.addAction(self.act_drag)
        toolbar.addAction(self.act_erase)

        toolbar.addSeparator()
        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.triggered.connect(self._undo)
        toolbar.addAction(self.act_undo)

        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence.Save)
        self.act_save.triggered.connect(self.save_current_image)
        toolbar.addAction(self.act_save)

        self._setup_boundary_shortcuts()
        self.setStatusBar(QStatusBar(self))

    def _setup_boundary_shortcuts(self) -> None:
        keys = ["1", "2", "3", "4", "5"]
        names = ["TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"]
        for k, name in zip(keys, names):
            act = QAction(self)
            act.setShortcut(QKeySequence(k))
            act.triggered.connect(lambda _=False, n=name:
                                  self.canvas.set_active_boundary(n))
            self.addAction(act)

    def _reload_workbook(self) -> None:
        self._wb = load_workbook(self.workbook_path)
        # Pull scale_um_per_px_y from summary if present.
        if "scale_um_per_px_y" in self._wb.summary.columns:
            try:
                self._scale_y = float(self._wb.summary["scale_um_per_px_y"].iloc[0])
            except (TypeError, ValueError):
                pass
        entries = []
        for stem, rec in self._wb.images.items():
            has_corr = any(np.any(~np.isnan(arr))
                           for arr in rec.corrected.values())
            entries.append(FileEntry(stem=stem,
                                     filename=rec.filename,
                                     has_corrections=has_corr))
        entries.sort(key=lambda e: e.stem)
        self.sidebar.set_entries(entries)

    def select_image(self, stem: str) -> None:
        if self._wb is None or stem not in self._wb.images:
            return
        self._current_stem = stem
        rec = self._wb.images[stem]
        if stem not in self._editors:
            self._editors[stem] = BoundaryEditor(
                width=rec.width,
                auto=rec.auto,
                corrected={k: v.copy() for k, v in rec.corrected.items()},
            )
        img_path = self.image_dir / rec.filename
        img = load_oct(img_path)
        self.canvas.set_image(img.rgb, offset_x=img.layout.left_x)
        self.canvas.set_editor(self._editors[stem])
        self.canvas.set_active_boundary("TOP_y")
        self.statusBar().showMessage(f"{rec.filename} | {rec.width} cols")

    def save_current_image(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        snap = CorrectedSnapshot(
            stem=self._current_stem,
            corrected={k: editor.corrected[k].copy() for k in editor.corrected},
            timestamp=datetime.now(),
        )
        save_corrections(self.workbook_path, [snap],
                         scale_um_per_px_y=self._scale_y)
        # Render the corrected overlay PNG.
        rec = self._wb.images[self._current_stem]
        img_path = self.image_dir / rec.filename
        out_path = (self.workbook_path.parent /
                    f"{self._current_stem}_overlay_corrected.png")
        boundaries = {k: editor.effective(k) for k in editor.auto}
        render_corrected_overlay(img_path, boundaries, out_path)
        self.sidebar.mark_corrected(self._current_stem, True)
        editor.mark_clean()
        self.statusBar().showMessage(f"Saved {rec.filename}")

    def _undo(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        editor.undo()
        self.canvas._refresh_lines()


def run(workbook_path, image_dir) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(workbook_path=workbook_path, image_dir=image_dir)
    win.resize(1400, 800)
    win.show()
    app.exec()
