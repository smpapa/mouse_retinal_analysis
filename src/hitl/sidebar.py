"""Left-side file list with a ✓ marker for images that have corrections."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget


@dataclass
class FileEntry:
    """A single file shown in the sidebar.

    `stem` is the unique key used by the controller; `filename` is the
    display label; `has_corrections` toggles the ✓ marker.
    """

    stem: str
    filename: str
    has_corrections: bool = False


class FileListView(QListWidget):
    image_selected = Signal(str)   # emits stem

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stem_for_row: list[str] = []
        self.currentRowChanged.connect(self._on_row_changed)

    def set_entries(self, entries: list[FileEntry]) -> None:
        """Replace the list contents without emitting `image_selected`.

        Qt's `QListWidget.clear()` followed by the first `addItem(...)` would
        otherwise fire `currentRowChanged(-1 → 0)` mid-population. Callers are
        expected to drive selection explicitly via `setCurrentRow(...)` after
        this returns.
        """
        self.blockSignals(True)
        try:
            self.clear()
            self._stem_for_row = []
            for e in entries:
                self.addItem(self._format(e.has_corrections, e.filename))
                self._stem_for_row.append(e.stem)
        finally:
            self.blockSignals(False)

    def mark_corrected(self, stem: str, has_corrections: bool) -> None:
        """Toggle the ✓ marker for `stem`.

        Raises `KeyError` if `stem` is not in the current list — silently
        ignoring would mask controller/view desync bugs.
        """
        if stem not in self._stem_for_row:
            raise KeyError(stem)
        row = self._stem_for_row.index(stem)
        item = self.item(row)
        # Strip any leading "✓ " prefix or "  " padding then re-prefix.
        text = item.text()
        if text.startswith("✓ "):
            text = text[2:]
        elif text.startswith("  "):
            text = text[2:]
        item.setText(self._format(has_corrections, text))

    @staticmethod
    def _format(has_corrections: bool, filename: str) -> str:
        return f"✓ {filename}" if has_corrections else f"  {filename}"

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._stem_for_row):
            self.image_selected.emit(self._stem_for_row[row])
