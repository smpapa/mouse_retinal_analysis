"""Boundary visibility toggle bar — 5 checkboxes (TOP/ONL/BM/DET top/DET bottom)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QVBoxLayout, QWidget


# Display order matches the canvas/storage convention.
_BOUNDARIES: tuple[tuple[str, str], ...] = (
    ("TOP_y", "TOP"),
    ("ONL_y", "ONL"),
    ("BM_y", "BM"),
    ("DET_top_y", "DET top"),
    ("DET_bottom_y", "DET bottom"),
)


class BoundaryToggleBar(QWidget):
    """A grouped column of 5 checkboxes that emit visibility changes."""

    visibility_changed = Signal(str, bool)  # (boundary_name, visible)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._boxes: dict[str, QCheckBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Boundaries")
        layout = QVBoxLayout(group)
        for name, label in _BOUNDARIES:
            box = QCheckBox(label)
            box.setChecked(True)
            # default arg captures `name` per Python closure idiom
            box.toggled.connect(
                lambda checked, n=name: self.visibility_changed.emit(n, bool(checked))
            )
            layout.addWidget(box)
            self._boxes[name] = box

        outer.addWidget(group)
        outer.addStretch(1)

    def set_visible(self, name: str, visible: bool) -> None:
        """Programmatic toggle; does NOT re-emit visibility_changed."""
        box = self._boxes.get(name)
        if box is None:
            return
        # blockSignals to avoid round-trip when the parent drives state.
        box.blockSignals(True)
        try:
            box.setChecked(visible)
        finally:
            box.blockSignals(False)

    def is_visible(self, name: str) -> bool:
        box = self._boxes.get(name)
        return bool(box.isChecked()) if box else True
