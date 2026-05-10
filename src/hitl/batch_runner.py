"""Background worker that runs `batch_process.batch_run` off the GUI thread.

Used by the HITL editor's "Run Auto Analysis" menu so the long-running
batch job (a few minutes for 96 images) does not freeze the UI. Progress
is reported via Qt signals.

Usage::

    worker = BatchWorker(folder, output_dir)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(...)
    worker.finished.connect(...)
    worker.error.connect(...)
    thread.start()
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal


# Make sibling analysis modules importable.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class BatchWorker(QObject):
    """Runs `batch_process.batch_run` in a worker thread."""

    # current (1-based), total, filename
    progress = Signal(int, int, str)
    # path to oct_results.xlsx
    finished = Signal(str)
    # error message
    error = Signal(str)

    def __init__(self, folder: str | Path, output_dir: str | Path):
        super().__init__()
        self.folder = Path(folder)
        self.output_dir = Path(output_dir)

    def run(self) -> None:
        try:
            from batch_process import batch_run  # type: ignore
            xlsx_path = batch_run(
                self.folder, self.output_dir,
                progress_callback=self._on_progress,
            )
            self.finished.emit(str(xlsx_path))
        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(f"{e}\n\n{tb}")

    def _on_progress(self, i: int, n: int, name: str) -> None:
        self.progress.emit(int(i), int(n), str(name))
