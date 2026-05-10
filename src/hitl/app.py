"""Main window: sidebar + canvas + storage glue."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog,
                                QLabel, QMainWindow, QMessageBox,
                                QProgressDialog, QStatusBar, QToolBar,
                                QVBoxLayout, QWidget)

# Make sibling analysis modules importable.
SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from io_utils import load_oct                                       # noqa: E402

from .batch_runner import BatchWorker                                # noqa: E402
from .boundary_model import (BOUNDARY_NAMES, BoundaryEditor,
                              ERASED_THRESHOLD)                      # noqa: E402
from .boundary_toggle import BoundaryToggleBar                      # noqa: E402
from .canvas import EditMode, OverlayCanvas                         # noqa: E402
from .convert_annotations import convert_legacy_folder               # noqa: E402
from .db import HitlDb                                               # noqa: E402
from .export_annotations import export_annotations                   # noqa: E402
from .overlay_render import render_corrected_overlay                # noqa: E402
from .sidebar import FileEntry, FileListView                        # noqa: E402
from .storage import CorrectedSnapshot                              # noqa: E402


class _ExportWorker(QObject):
    """Background-thread worker that runs HitlDb.export_to_xlsx."""
    finished = Signal(str)   # path that was written
    error = Signal(str)

    def __init__(self, db, out_path):
        super().__init__()
        self.db = db
        self.out_path = out_path

    def run(self):
        try:
            result = self.db.export_to_xlsx(self.out_path)
            self.finished.emit(str(result))
        except Exception as e:
            self.error.emit(str(e))


class _AnnotationExportWorker(QObject):
    """Background-thread worker that runs export_annotations()."""
    progress = Signal(int, int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, db, image_dir, out_dir, formats, only_corrected):
        super().__init__()
        self.db = db
        self.image_dir = image_dir
        self.out_dir = out_dir
        self.formats = formats
        self.only_corrected = only_corrected

    def run(self):
        try:
            result = export_annotations(
                self.db, self.image_dir, self.out_dir,
                formats=self.formats,
                only_corrected=self.only_corrected,
                progress_callback=self._on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, i, n, name):
        self.progress.emit(int(i), int(n), str(name))


class _LegacyConvertWorker(QObject):
    """Background-thread worker for convert_legacy_folder()."""
    progress = Signal(int, int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, legacy_dir, original_image_dir, out_dir):
        super().__init__()
        self.legacy_dir = legacy_dir
        self.original_image_dir = original_image_dir
        self.out_dir = out_dir

    def run(self):
        try:
            result = convert_legacy_folder(
                self.legacy_dir, self.original_image_dir, self.out_dir,
                progress_callback=self._on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, i, n, name):
        self.progress.emit(int(i), int(n), str(name))


class MainWindow(QMainWindow):
    def __init__(self, workbook_path, image_dir):
        super().__init__()
        self.workbook_path = Path(workbook_path)
        self.image_dir = Path(image_dir)
        self._editors: dict[str, BoundaryEditor] = {}
        self._current_stem: str | None = None
        self._scale_y = 3.87  # default; overridden if summary has it.
        # When True, _on_sidebar_image_selected skips the unsaved-changes
        # prompt — used for programmatic reverts after the user cancels.
        self._suppress_dirty_check: bool = False
        # Batch-run worker state. Held as instance attrs so the QThread
        # outlives the method scope; cleared after batch completes.
        self._batch_thread: QThread | None = None
        self._batch_worker: BatchWorker | None = None
        self._progress_dialog: QProgressDialog | None = None
        # SQLite-backed canonical store. Saves go here directly (~5 ms).
        # The xlsx is exported on demand (File > Export to Excel) or
        # automatically on close.
        self._db: HitlDb | None = None
        # Lightweight metadata: stem -> {"filename", "width", "scale_y"}.
        # Populated from the DB so we don't have to re-load the slow xlsx
        # on startup.
        self._image_meta: dict[str, dict] = {}
        # True after at least one save_current_image() in this session
        # (or after Tools > Run Auto Analysis). closeEvent checks this
        # so it doesn't trigger an unnecessary slow xlsx export when
        # the user just opens the editor and closes without editing.
        self._edits_since_export: bool = False

        self._build_ui()
        # If a real workbook exists, open the DB (importing from xlsx if
        # this is the first run). Otherwise leave the UI empty so the
        # user can pick a folder via File > Open Data Folder.
        if self.workbook_path.exists():
            self._open_db_for_workbook()

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
        self._build_menu_bar()
        self.setStatusBar(QStatusBar(self))
        # Persistent hover label (rightmost in the status bar). Updated
        # whenever the canvas reports the column under the cursor; the
        # transient showMessage() text on the left of the status bar is
        # untouched.
        self._hover_label = QLabel("")
        self._hover_label.setStyleSheet("padding-right: 8px;")
        self.statusBar().addPermanentWidget(self._hover_label)
        self.canvas.hovered.connect(self._on_canvas_hover)

    def _build_menu_bar(self) -> None:
        """File / Tools menus driving folder selection + auto analysis."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self.act_open = QAction("&Open Data Folder...", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self._open_data_folder)
        file_menu.addAction(self.act_open)
        file_menu.addSeparator()
        # Reuse the toolbar's Save action so its shortcut and label match.
        file_menu.addAction(self.act_save)
        self.act_export = QAction("&Export to Excel...", self)
        self.act_export.triggered.connect(self._export_to_xlsx)
        file_menu.addAction(self.act_export)

        tools_menu = menubar.addMenu("&Tools")
        self.act_run_batch = QAction("&Run Auto Analysis...", self)
        self.act_run_batch.triggered.connect(self._run_auto_analysis)
        tools_menu.addAction(self.act_run_batch)
        tools_menu.addSeparator()
        self.act_export_annotations = QAction(
            "Export Annotations (CSV + TIFF)...", self
        )
        self.act_export_annotations.triggered.connect(
            self._export_annotations
        )
        tools_menu.addAction(self.act_export_annotations)
        self.act_convert_legacy = QAction(
            "Convert Legacy Annotation TIFFs to HITL Colours...", self
        )
        self.act_convert_legacy.triggered.connect(
            self._convert_legacy_annotations
        )
        tools_menu.addAction(self.act_convert_legacy)

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

    def _open_db_for_workbook(self) -> None:
        """Open (or create) the SQLite store for the current workbook.

        First-time use: imports the xlsx into the DB. Subsequent runs
        skip the import — the DB is now the source of truth.
        """
        db_path = (self.workbook_path.parent / "db" /
                   f"{self.workbook_path.stem}.db")
        try:
            self._db = HitlDb(db_path)
        except Exception as e:
            QMessageBox.critical(self, "DB error",
                                  f"Could not open {db_path}: {e}")
            return
        if self._db.is_empty():
            self.statusBar().showMessage("Importing workbook into DB...")
            try:
                self._db.import_from_xlsx(self.workbook_path)
            except Exception as e:
                QMessageBox.critical(self, "Import failed",
                                      f"Could not import workbook: {e}")
                return
        self._refresh_image_meta_and_sidebar()

    def _refresh_image_meta_and_sidebar(self) -> None:
        """Pull lightweight metadata + sidebar state from the DB."""
        if self._db is None:
            return
        self._image_meta.clear()
        cur = self._db._conn.execute(
            "SELECT stem, filename, width, scale_um_per_px_y FROM images"
        )
        for stem, filename, width, scale in cur.fetchall():
            self._image_meta[stem] = {
                "filename": filename,
                "width": int(width),
                "scale_y": float(scale) if scale else 3.87,
            }
        # Pick the first image's scale as the global default — all
        # images in a session typically share the same scale.
        if self._image_meta:
            self._scale_y = next(iter(self._image_meta.values()))["scale_y"]
        entries = [
            FileEntry(stem=stem,
                       filename=filename,
                       has_corrections=has_corr)
            for stem, filename, has_corr in self._db.list_images()
        ]
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
            current_filename = self._image_meta.get(
                prev, {}).get("filename", prev)
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
        if self._db is None or stem not in self._image_meta:
            return
        meta = self._image_meta[stem]
        img_path = self.image_dir / meta["filename"]
        # Load the TIFF first so a missing/corrupt file doesn't leave the
        # window pointing at a broken image. _current_stem is only updated
        # after the load succeeds.
        try:
            img = load_oct(img_path)
        except Exception as e:
            self.statusBar().showMessage(
                f"Could not load {meta['filename']}: {e}"
            )
            return
        self._current_stem = stem
        if stem not in self._editors:
            rec = self._db.load_image(stem)
            if rec is None:
                self.statusBar().showMessage(f"Image {stem} not in DB.")
                return
            self._editors[stem] = BoundaryEditor(
                width=rec.width,
                auto=rec.auto,
                corrected={k: v.copy() for k, v in rec.corrected.items()},
            )
        self.canvas.set_image(img.rgb, offset_x=img.layout.left_x)
        self.canvas.set_panel_geometry(
            left_x=img.layout.left_x,
            right_x=img.layout.right_x,
            top_y=img.layout.top_y,
            bot_y=img.layout.bot_y,
            center_x=img.layout.center_x,
        )
        self.canvas.set_editor(self._editors[stem])
        self.canvas.set_active_boundary("TOP_y")
        self._refresh_status()

    def save_current_image(self) -> None:
        """Persist the current image's edits to the local DB.

        DB writes are synchronous and fast (~5–50 ms), so there is no
        background queue. The sidebar is marked, the editor cleaned, and
        the corrected overlay PNG re-rendered all in one straight-line
        path.
        """
        if self._current_stem is None or self._db is None:
            return
        editor = self._editors[self._current_stem]
        snap = CorrectedSnapshot(
            stem=self._current_stem,
            corrected={k: editor.corrected[k].copy()
                       for k in editor.corrected},
            timestamp=datetime.now(),
        )
        try:
            self._db.save_corrections(snap)
        except Exception as e:
            QMessageBox.critical(
                self, "Save failed",
                f"Could not write the local DB.\n\nDetails: {e}",
            )
            return
        self._edits_since_export = True
        self.sidebar.mark_corrected(self._current_stem, True)
        editor.mark_clean()
        meta = self._image_meta.get(self._current_stem, {})
        filename = meta.get("filename", self._current_stem)
        # Re-render the corrected overlay PNG. Failure is non-fatal;
        # the DB save already succeeded.
        try:
            img_path = self.image_dir / filename
            out_path = (self.workbook_path.parent /
                        f"{self._current_stem}_overlay_corrected.png")
            boundaries = {k: editor.effective(k) for k in editor.auto}
            render_corrected_overlay(img_path, boundaries, out_path)
        except Exception as e:
            self.statusBar().showMessage(
                f"Saved {filename} (overlay PNG failed: {e})")
            return
        self.statusBar().showMessage(f"Saved {filename}")
        self._refresh_status()

    def _undo(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        editor.undo()
        self.canvas.refresh()
        self._refresh_status()

    def _convert_legacy_annotations(self) -> None:
        """Tools > Convert Legacy Annotation TIFFs to HITL Colours.

        Walks an existing ``annotation/`` folder of Heidelberg-palette
        ``*_annotation.tiff`` files, looks up each matching un-annotated
        TIFF in the data folder, and writes HITL-coloured equivalents
        to a chosen output folder.
        """
        # Default legacy folder: data_dir / annotation
        default_legacy = self.image_dir / "annotation"
        legacy = QFileDialog.getExistingDirectory(
            self, "Select folder with legacy *_annotation.tiff files",
            str(default_legacy if default_legacy.exists()
                else self.image_dir),
        )
        if not legacy:
            return
        legacy_dir = Path(legacy)
        # Source TIFF folder (un-annotated). Default to the editor's
        # current image dir.
        original_dir = QFileDialog.getExistingDirectory(
            self, "Select folder with original (un-annotated) TIFFs",
            str(self.image_dir),
        )
        if not original_dir:
            return
        # Output folder.
        default_out = legacy_dir.parent / "annotation_hitl"
        out_chosen = QFileDialog.getExistingDirectory(
            self, "Choose output folder for converted TIFFs",
            str(default_out),
        )
        if not out_chosen:
            return
        out_dir = Path(out_chosen)

        # Quick inventory.
        n_files = sum(
            1 for _ in (
                list(legacy_dir.glob("*_annotation.tiff"))
                + list(legacy_dir.glob("*_annotation.tif"))
            )
        )
        if n_files == 0:
            QMessageBox.information(
                self, "Nothing to convert",
                f"No *_annotation.tiff files found in:\n{legacy_dir}",
            )
            return

        progress = QProgressDialog(
            f"Converting {n_files} legacy annotation file(s)...",
            None, 0, n_files, self,
        )
        progress.setWindowTitle("Convert Legacy Annotations")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        QApplication.processEvents()

        loop = QEventLoop()
        thread = QThread(self)
        worker = _LegacyConvertWorker(legacy_dir, Path(original_dir), out_dir)
        worker.moveToThread(thread)
        result_holder: dict = {"ok": False, "result": None, "err": None}

        def on_progress(i: int, n: int, name: str):
            progress.setMaximum(n)
            progress.setValue(i)
            progress.setLabelText(f"[{i}/{n}] {name}")

        def on_finished(result: dict):
            result_holder["ok"] = True
            result_holder["result"] = result
            loop.quit()

        def on_error(msg: str):
            result_holder["err"] = msg
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait()
        progress.close()

        if not result_holder["ok"]:
            QMessageBox.critical(
                self, "Conversion failed",
                result_holder["err"] or "Unknown error",
            )
            return
        r = result_holder["result"]
        msg = (
            f"Converted {r['converted']} annotation TIFF(s) to:\n"
            f"{out_dir}"
        )
        if r.get("skipped_no_source"):
            msg += (
                f"\n\n{r['skipped_no_source']} file(s) skipped: "
                "no matching source TIFF found in the original image "
                "folder. Make sure the source TIFFs and the legacy "
                "annotations share the same stem."
            )
        QMessageBox.information(self, "Conversion complete", msg)
        self.statusBar().showMessage(f"Converted to {out_dir}")

    def _export_annotations(self) -> None:
        """Tools > Export Annotations: write CSV + annotation TIFF for
        every image that has user corrections (✓ in the sidebar).

        Output structure:
            <chosen_dir>/
              csv/<stem>.csv
              tiff/<stem>_annotation_hitl.tiff
        """
        if self._db is None:
            QMessageBox.information(
                self, "Nothing to export",
                "Open a data folder first.",
            )
            return
        n_corr = sum(1 for _, _, has in self._db.list_images() if has)
        if n_corr == 0:
            QMessageBox.information(
                self, "No corrections yet",
                "None of the images have user corrections. Edit a few "
                "boundaries and Save first, then come back.",
            )
            return
        # Default output: <workbook_path.parent>/annotations/
        default = self.workbook_path.parent / "annotations"
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose annotation output folder", str(default)
        )
        if not chosen:
            return
        out_dir = Path(chosen)

        # Spawn worker on a QThread; show progress dialog while it runs.
        progress = QProgressDialog(
            f"Exporting annotations for {n_corr} corrected image(s)...",
            None, 0, n_corr, self,
        )
        progress.setWindowTitle("Export Annotations")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        QApplication.processEvents()

        loop = QEventLoop()
        thread = QThread(self)
        worker = _AnnotationExportWorker(
            self._db, self.image_dir, out_dir,
            formats={"csv", "tiff"},
            only_corrected=True,
        )
        worker.moveToThread(thread)

        result_holder: dict = {"ok": False, "result": None, "err": None}

        def on_progress(i: int, n: int, name: str):
            progress.setMaximum(n)
            progress.setValue(i)
            progress.setLabelText(f"[{i}/{n}] {name}")

        def on_finished(result: dict):
            result_holder["ok"] = True
            result_holder["result"] = result
            loop.quit()

        def on_error(msg: str):
            result_holder["ok"] = False
            result_holder["err"] = msg
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait()
        progress.close()

        if not result_holder["ok"]:
            QMessageBox.critical(
                self, "Export failed",
                result_holder["err"] or "Unknown error",
            )
            return
        r = result_holder["result"]
        msg = (
            f"Exported {r['csv_count']} CSV file(s) and "
            f"{r['tiff_count']} annotation TIFF(s) to:\n{out_dir}"
        )
        if r.get("skipped_missing_tiff"):
            msg += (f"\n\n{r['skipped_missing_tiff']} TIFF(s) skipped "
                    "because the source image was not found in the "
                    f"image folder ({self.image_dir}).")
        QMessageBox.information(self, "Export complete", msg)
        self.statusBar().showMessage(
            f"Exported annotations to {out_dir}"
        )

    def _export_to_xlsx(self) -> None:
        """File > Export to Excel — write the current DB state to xlsx."""
        if self._db is None:
            QMessageBox.information(
                self, "Nothing to export",
                "Open a data folder first.",
            )
            return
        # Default to overwriting the source workbook, but let the user
        # pick another path so they can keep snapshots if desired.
        dst, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel",
            str(self.workbook_path),
            "Excel workbook (*.xlsx)",
        )
        if not dst:
            return
        ok, err = self._run_export_with_progress(
            dst,
            label_text=f"Exporting to Excel:\n{Path(dst).name}\n\n"
                       "Writing all sheets — this can take ~10 seconds.",
            window_title="Exporting",
        )
        if not ok:
            QMessageBox.critical(self, "Export failed", err or "")
            return
        self._edits_since_export = False
        self.statusBar().showMessage(f"Exported {dst}")

    def _run_export_with_progress(self, out_path,
                                    label_text: str,
                                    window_title: str = "Exporting"
                                    ) -> tuple[bool, str | None]:
        """Run db.export_to_xlsx on a worker thread; show a busy progress
        dialog while it runs. Returns (success, error_message).

        Blocks via a local QEventLoop until the worker emits finished or
        error, so the caller can treat this as a synchronous operation
        even though the actual save is on another thread (keeping the
        Qt event loop responsive — the dialog re-paints, the cancel
        button stays clickable).
        """
        if self._db is None:
            return False, "No DB"
        progress = QProgressDialog(label_text, None,  # no cancel button
                                     0, 0, self)
        progress.setWindowTitle(window_title)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        QApplication.processEvents()  # ensure dialog paints before we block

        loop = QEventLoop()
        thread = QThread(self)
        worker = _ExportWorker(self._db, out_path)
        worker.moveToThread(thread)

        result: dict = {"ok": False, "err": None}

        def on_finished(path: str):
            result["ok"] = True
            loop.quit()

        def on_error(msg: str):
            result["ok"] = False
            result["err"] = msg
            loop.quit()

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()

        thread.quit()
        thread.wait()
        progress.close()
        return result["ok"], result["err"]

    # ------------------------------------------------------ data folder

    def _open_data_folder(self) -> None:
        """Prompt the user for a TIFF folder and switch to it.

        If an `output/oct_results.xlsx` already exists in that folder we
        load it directly; otherwise offer to run auto analysis.
        """
        start = str(self.image_dir if self.image_dir.exists() else Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select OCT data folder", start
        )
        if not folder:
            return
        folder = Path(folder)
        # The folder must contain at least one TIFF for the editor to be
        # useful. Glob silently to keep this method fast.
        tiffs = list(folder.glob("*.tif")) + list(folder.glob("*.tiff"))
        if not tiffs:
            QMessageBox.warning(
                self, "No TIFFs found",
                f"No .tif/.tiff files in {folder}.",
            )
            return
        workbook_path = folder / "output" / "oct_results.xlsx"
        if workbook_path.exists():
            self._switch_data_folder(folder, workbook_path)
            return
        # No analysis yet — offer to run it now.
        reply = QMessageBox.question(
            self, "No analysis found",
            f"No oct_results.xlsx found in:\n{workbook_path.parent}\n\n"
            f"Found {len(tiffs)} TIFF files in the folder.\n\n"
            "Run auto analysis now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        # Switch the in-memory paths first so _run_auto_analysis uses them,
        # but skip _switch_data_folder's reload (the workbook does not
        # exist yet).
        self.image_dir = folder
        self.workbook_path = workbook_path
        self._editors.clear()
        self._current_stem = None
        self._run_auto_analysis()

    def _switch_data_folder(self, image_dir: Path,
                             workbook_path: Path) -> None:
        """Update paths and reload, prompting first if any editor is dirty."""
        dirty = [s for s, ed in self._editors.items() if ed.dirty]
        if dirty:
            n = len(dirty)
            first_filename = self._image_meta.get(
                dirty[0], {}).get("filename", dirty[0])
            msg = (f"Save changes to {n} image(s) before switching folder?"
                   if n > 1 else
                   f"Save changes to {first_filename} before switching folder?")
            reply = QMessageBox.question(
                self, "Unsaved changes", msg,
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Save:
                for stem in dirty:
                    self._current_stem = stem
                    self.save_current_image()
                if any(ed.dirty for ed in self._editors.values()):
                    return  # save failed — abort the switch
        # Close the previous DB.
        if self._db is not None:
            self._db.close()
            self._db = None
        self.image_dir = Path(image_dir)
        self.workbook_path = Path(workbook_path)
        self._editors.clear()
        self._current_stem = None
        self._image_meta.clear()
        self._open_db_for_workbook()
        self.statusBar().showMessage(f"Loaded {self.workbook_path}")

    # ----------------------------------------------------- batch runner

    def _run_auto_analysis(self) -> None:
        """Run batch_process.batch_run on the current folder in a worker."""
        if not self.image_dir.exists():
            QMessageBox.critical(
                self, "No folder",
                "No data folder selected. Use File > Open Data Folder.",
            )
            return
        tiffs = list(self.image_dir.glob("*.tif")) + \
                list(self.image_dir.glob("*.tiff"))
        if not tiffs:
            QMessageBox.critical(
                self, "No TIFFs",
                f"No .tif/.tiff files in {self.image_dir}.",
            )
            return
        reply = QMessageBox.question(
            self, "Run auto analysis",
            f"Analyze {len(tiffs)} TIFF files in:\n{self.image_dir}\n\n"
            "This may take several minutes. Existing automatic results "
            "will be overwritten; *_corrected columns are preserved.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self._batch_thread is not None:
            QMessageBox.information(
                self, "Already running",
                "An auto analysis run is already in progress.",
            )
            return
        output_dir = self.image_dir / "output"
        # Spin up a worker on its own QThread.
        self._batch_thread = QThread(self)
        self._batch_worker = BatchWorker(self.image_dir, output_dir)
        self._batch_worker.moveToThread(self._batch_thread)
        self._batch_thread.started.connect(self._batch_worker.run)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.error.connect(self._on_batch_error)
        # Modal progress dialog. Cancel currently does not interrupt the
        # worker — it just hides the dialog; the run completes in the
        # background. (Adding interruption would need cooperative checks
        # in batch_run; out of scope.)
        self._progress_dialog = QProgressDialog(
            "Starting auto analysis...", None, 0, len(tiffs), self
        )
        self._progress_dialog.setWindowTitle("Auto Analysis")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setValue(0)
        self._batch_thread.start()

    def _on_batch_progress(self, i: int, n: int, name: str) -> None:
        if self._progress_dialog is None:
            return
        self._progress_dialog.setMaximum(n)
        self._progress_dialog.setValue(i)
        self._progress_dialog.setLabelText(f"[{i}/{n}] {name}")

    def _cleanup_batch_worker(self) -> None:
        if self._batch_thread is not None:
            self._batch_thread.quit()
            self._batch_thread.wait()
            self._batch_thread = None
        self._batch_worker = None
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

    def _on_batch_finished(self, xlsx_path: str) -> None:
        self._cleanup_batch_worker()
        self.workbook_path = Path(xlsx_path)
        # Editors are stale after re-analysis. Re-import the freshly
        # written xlsx into the DB (preserving any prior corrections).
        self._editors.clear()
        self._current_stem = None
        if self._db is not None:
            try:
                self._db.import_from_xlsx(self.workbook_path,
                                           preserve_corrected_in_db=True)
            except Exception as e:
                QMessageBox.critical(self, "Reimport failed", str(e))
            self._refresh_image_meta_and_sidebar()
        else:
            self._open_db_for_workbook()
        QMessageBox.information(
            self, "Done",
            f"Auto analysis complete:\n{xlsx_path}",
        )

    def _on_batch_error(self, msg: str) -> None:
        self._cleanup_batch_worker()
        QMessageBox.critical(self, "Auto analysis failed", msg)

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
        """Prompt save/discard/cancel for unsaved edits, then auto-export
        to xlsx if the DB has any corrections (so external tools always
        see the latest state on disk)."""
        dirty_stems = [stem for stem, ed in self._editors.items() if ed.dirty]
        if dirty_stems:
            n = len(dirty_stems)
            first_filename = self._image_meta.get(
                dirty_stems[0], {}).get("filename", dirty_stems[0])
            msg = (f"Save changes to {first_filename} before closing?"
                   if n == 1 else
                   f"You have unsaved changes in {n} images. "
                   "Save before closing?")
            reply = QMessageBox.question(
                self, "Unsaved changes", msg,
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                for stem in dirty_stems:
                    self._current_stem = stem
                    try:
                        self.save_current_image()
                    except Exception:
                        event.ignore()
                        return
                if any(ed.dirty for ed in self._editors.values()):
                    event.ignore()
                    return
        # Auto-export to xlsx if the user actually saved during this
        # session. We skip the export when the editor is opened and
        # closed without edits, so closing is instant in that case.
        if (self._db is not None and self._edits_since_export
                and self._db.has_corrections()):
            ok, err = self._run_export_with_progress(
                self.workbook_path,
                label_text=("Saving changes to Excel before close:\n"
                            f"{Path(self.workbook_path).name}\n\n"
                            "This usually takes ~10 seconds."),
                window_title="Saving",
            )
            if not ok:
                # Don't block close on a failed export — DB is still
                # canonical and the user can re-export from File menu.
                QMessageBox.warning(
                    self, "Auto-export failed",
                    "DB is saved, but xlsx auto-export failed:\n"
                    f"{err}\n\n"
                    "Use File > Export to Excel later to retry."
                )
        if self._db is not None:
            self._db.close()
            self._db = None
        super().closeEvent(event)

    def _on_canvas_hover(self, x_local: int) -> None:
        """Update the rightmost status-bar label with per-column readings."""
        if x_local < 0 or self._current_stem is None:
            self._hover_label.setText("")
            return
        editor = self._editors.get(self._current_stem)
        if editor is None:
            self._hover_label.setText("")
            return

        def fmt(v) -> str:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "—"
            return f"{int(round(float(v)))}"

        eff = {n: editor.effective(n)[x_local] for n in BOUNDARY_NAMES}
        parts = [f"x={x_local}",
                 f"TOP={fmt(eff['TOP_y'])}",
                 f"ONL={fmt(eff['ONL_y'])}",
                 f"BM={fmt(eff['BM_y'])}"]
        # DET pair only when at least the top is finite.
        det_top = eff["DET_top_y"]
        det_bot = eff["DET_bottom_y"]
        if not (isinstance(det_top, float) and np.isnan(det_top)):
            parts.append(f"DET=({fmt(det_top)},{fmt(det_bot)})")
        # Thicknesses (μm) — only when both endpoints are finite.
        scale = self._scale_y
        bm = eff["BM_y"]
        top = eff["TOP_y"]
        onl = eff["ONL_y"]

        def finite(v) -> bool:
            return not (isinstance(v, float) and np.isnan(v))

        if finite(bm) and finite(top):
            parts.append(f"total={(bm - top) * scale:.1f}μm")
        if finite(bm) and finite(onl):
            parts.append(f"outer={(bm - onl) * scale:.1f}μm")
        if finite(det_top) and finite(det_bot):
            parts.append(f"det={(det_bot - det_top) * scale:.1f}μm")
        self._hover_label.setText("  |  ".join(parts))

    def _refresh_status(self) -> None:
        """Rebuild the status bar message with edited boundaries + dirty marker."""
        if self._current_stem is None:
            return
        meta = self._image_meta.get(self._current_stem)
        if meta is None:
            return
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
        parts = [meta["filename"], f"{meta['width']} cols"]
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
