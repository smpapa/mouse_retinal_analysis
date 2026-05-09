"""Main window: sidebar + canvas + storage glue."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QMainWindow,
                                QMessageBox, QStatusBar, QToolBar,
                                QVBoxLayout, QWidget)

# Make sibling analysis modules importable.
SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from io_utils import load_oct                                       # noqa: E402

from .boundary_model import (BOUNDARY_NAMES, BoundaryEditor,
                              ERASED_THRESHOLD)                      # noqa: E402
from .boundary_toggle import BoundaryToggleBar                      # noqa: E402
from .canvas import EditMode, OverlayCanvas                         # noqa: E402
from .overlay_render import render_corrected_overlay                # noqa: E402
from .sidebar import FileEntry, FileListView                        # noqa: E402
from .storage import (CorrectedSnapshot, Workbook,
                      load_workbook, save_corrections)              # noqa: E402


class MainWindow(QMainWindow):
    def __init__(self, workbook_path, image_dir):
        super().__init__()
        self.workbook_path = Path(workbook_path)
        self.image_dir = Path(image_dir)
        self._editors: dict[str, BoundaryEditor] = {}
        self._wb: Workbook | None = None
        self._current_stem: str | None = None
        self._scale_y = 3.87  # default; overridden if summary has it.
        # When True, _on_sidebar_image_selected skips the unsaved-changes
        # prompt — used for programmatic reverts after the user cancels.
        self._suppress_dirty_check: bool = False

        self._build_ui()
        self._reload_workbook()

    def _build_ui(self) -> None:
        self.setWindowTitle("OCT HITL Editor")
        self.canvas = OverlayCanvas()
        self.canvas.edit_finished.connect(self._refresh_status)
        self.setCentralWidget(self.canvas)

        self.sidebar = FileListView()
        # Route through the dirty-check handler instead of select_image
        # directly so we can prompt before discarding unsaved edits.
        self.sidebar.image_selected.connect(self._on_sidebar_image_selected)

        self.boundary_toggle = BoundaryToggleBar()
        self.boundary_toggle.visibility_changed.connect(
            self.canvas.set_boundary_visible
        )

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.sidebar, stretch=1)
        container_layout.addWidget(self.boundary_toggle)

        dock = QDockWidget("Files", self)
        dock.setWidget(container)
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
        # Mutually exclusive selection between drag and erase.
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        mode_group.addAction(self.act_drag)
        mode_group.addAction(self.act_erase)
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

        self._setup_shortcuts()
        self.setStatusBar(QStatusBar(self))

    def _setup_shortcuts(self) -> None:
        # Boundary picker shortcuts: 1..5 select active boundary.
        keys = ["1", "2", "3", "4", "5"]
        for k, name in zip(keys, BOUNDARY_NAMES):
            act = QAction(self)
            act.setShortcut(QKeySequence(k))
            act.triggered.connect(lambda _=False, n=name:
                                  self.canvas.set_active_boundary(n))
            self.addAction(act)

        # Mode shortcuts: D = drag, E = erase. Trigger the action so the
        # checked state in the QActionGroup updates alongside the mode.
        act_d = QAction(self)
        act_d.setShortcut(QKeySequence("D"))
        act_d.triggered.connect(self._activate_drag_mode)
        self.addAction(act_d)

        act_e = QAction(self)
        act_e.setShortcut(QKeySequence("E"))
        act_e.triggered.connect(self._activate_erase_mode)
        self.addAction(act_e)

        # Image navigation: Left/Right arrows step through the sidebar.
        act_prev = QAction(self)
        act_prev.setShortcut(QKeySequence(Qt.Key_Left))
        act_prev.triggered.connect(self._prev_image)
        self.addAction(act_prev)

        act_next = QAction(self)
        act_next.setShortcut(QKeySequence(Qt.Key_Right))
        act_next.triggered.connect(self._next_image)
        self.addAction(act_next)

    def _activate_drag_mode(self) -> None:
        self.canvas.set_mode(EditMode.DRAG)
        self.act_drag.setChecked(True)

    def _activate_erase_mode(self) -> None:
        self.canvas.set_mode(EditMode.ERASE)
        self.act_erase.setChecked(True)

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

    def _on_sidebar_image_selected(self, stem: str) -> None:
        """Sidebar selection handler with unsaved-changes confirmation.

        If the previously-selected image has dirty edits, prompt the user
        to save / discard / cancel before switching. On cancel, revert
        the sidebar selection without re-prompting.
        """
        if self._suppress_dirty_check:
            self.select_image(stem)
            return
        prev = self._current_stem
        if (prev is not None
                and prev != stem
                and self._editors.get(prev) is not None
                and self._editors[prev].dirty):
            current_filename = (self._wb.images[prev].filename
                                if self._wb is not None else prev)
            reply = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {current_filename} before switching?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                # Revert sidebar selection back to the previous stem
                # without re-firing the dirty prompt.
                self._suppress_dirty_check = True
                try:
                    if prev in self.sidebar._stem_for_row:
                        row = self.sidebar._stem_for_row.index(prev)
                        self.sidebar.setCurrentRow(row)
                finally:
                    self._suppress_dirty_check = False
                return
            if reply == QMessageBox.Save:
                self.save_current_image()
            # Discard: fall through and load the new image.
        self.select_image(stem)

    def select_image(self, stem: str) -> None:
        if self._wb is None or stem not in self._wb.images:
            return
        rec = self._wb.images[stem]
        img_path = self.image_dir / rec.filename
        # Load the TIFF first so a missing/corrupt file doesn't leave the
        # window pointing at a broken image. _current_stem is only updated
        # after the load succeeds.
        try:
            img = load_oct(img_path)
        except Exception as e:
            self.statusBar().showMessage(
                f"Could not load {rec.filename}: {e}"
            )
            return
        self._current_stem = stem
        if stem not in self._editors:
            self._editors[stem] = BoundaryEditor(
                width=rec.width,
                auto=rec.auto,
                corrected={k: v.copy() for k, v in rec.corrected.items()},
            )
        self.canvas.set_image(img.rgb, offset_x=img.layout.left_x)
        self.canvas.set_editor(self._editors[stem])
        self.canvas.set_active_boundary("TOP_y")
        self._refresh_status()

    def save_current_image(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        snap = CorrectedSnapshot(
            stem=self._current_stem,
            corrected={k: editor.corrected[k].copy() for k in editor.corrected},
            timestamp=datetime.now(),
        )
        try:
            save_corrections(self.workbook_path, [snap],
                             scale_um_per_px_y=self._scale_y)
        except (PermissionError, OSError) as e:
            # Clean up any leftover .tmp from a partial write before the
            # atomic rename had a chance to run.
            tmp = self.workbook_path.with_suffix(
                self.workbook_path.suffix + ".tmp")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            QMessageBox.critical(
                self, "Save failed",
                f"Could not write {self.workbook_path.name}.\n\n"
                f"If Excel has the file open, close it and try again.\n\n"
                f"Details: {e}",
            )
            return
        # Sidebar marker reflects xlsx state immediately.
        self.sidebar.mark_corrected(self._current_stem, True)
        editor.mark_clean()
        self._refresh_status()
        # Render PNG separately — failure is non-fatal so the user does
        # not lose their save state if rendering hits an edge case.
        # Note: self._wb may go slightly stale after save; full reload
        # only on next app launch.
        rec = self._wb.images[self._current_stem]
        try:
            img_path = self.image_dir / rec.filename
            out_path = (self.workbook_path.parent /
                        f"{self._current_stem}_overlay_corrected.png")
            boundaries = {k: editor.effective(k) for k in editor.auto}
            render_corrected_overlay(img_path, boundaries, out_path)
        except Exception as e:
            self.statusBar().showMessage(
                f"Saved {rec.filename} (overlay PNG failed: {e})")
            return
        self.statusBar().showMessage(f"Saved {rec.filename}")

    def _undo(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        editor.undo()
        self.canvas.refresh()
        self._refresh_status()

    def _prev_image(self) -> None:
        """Move sidebar selection up by one (clamped)."""
        count = self.sidebar.count()
        if count == 0:
            return
        row = self.sidebar.currentRow()
        new_row = max(0, row - 1)
        if new_row != row:
            self.sidebar.setCurrentRow(new_row)

    def _next_image(self) -> None:
        """Move sidebar selection down by one (clamped)."""
        count = self.sidebar.count()
        if count == 0:
            return
        row = self.sidebar.currentRow()
        new_row = min(count - 1, row + 1)
        if new_row != row:
            self.sidebar.setCurrentRow(new_row)

    def closeEvent(self, event) -> None:
        """Prompt save/discard/cancel if any image has unsaved edits."""
        dirty_stems = [stem for stem, ed in self._editors.items() if ed.dirty]
        if not dirty_stems:
            super().closeEvent(event)
            return
        n = len(dirty_stems)
        if n == 1 and self._wb is not None:
            msg = (f"Save changes to "
                   f"{self._wb.images[dirty_stems[0]].filename} "
                   f"before closing?")
        else:
            msg = (f"You have unsaved changes in {n} images. "
                   f"Save before closing?")
        reply = QMessageBox.question(
            self, "Unsaved changes", msg,
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Cancel:
            event.ignore()
            return
        if reply == QMessageBox.Save:
            # Save each dirty image. If any save fails (e.g. PermissionError
            # surfaced via QMessageBox in save_current_image), abort close
            # so the user can address the failure.
            for stem in dirty_stems:
                self._current_stem = stem
                try:
                    self.save_current_image()
                except Exception:
                    event.ignore()
                    return
            # If any editor is still dirty (save_current_image returned
            # early after a write error), abort the close.
            if any(ed.dirty for ed in self._editors.values()):
                event.ignore()
                return
        super().closeEvent(event)

    def _refresh_status(self) -> None:
        """Rebuild the status bar message with edited boundaries + dirty marker."""
        if self._current_stem is None or self._wb is None:
            return
        if self._current_stem not in self._wb.images:
            return
        rec = self._wb.images[self._current_stem]
        editor = self._editors.get(self._current_stem)
        if editor is None:
            return
        edited: list[str] = []
        for name in BOUNDARY_NAMES:
            if name not in editor.corrected:
                continue
            corr = editor.corrected[name]
            # "touched" = any column either set to a finite override or
            # explicitly erased (sentinel below threshold).
            touched = bool(np.any((~np.isnan(corr)) | (corr < ERASED_THRESHOLD)))
            if touched:
                edited.append(name.replace("_y", ""))
        parts = [rec.filename, f"{rec.width} cols"]
        if edited:
            parts.append("edited: " + ", ".join(edited))
        if editor.dirty:
            parts.append("●")
        self.statusBar().showMessage(" | ".join(parts))


def run(workbook_path, image_dir) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(workbook_path=workbook_path, image_dir=image_dir)
    win.resize(1400, 800)
    win.show()
    app.exec()
