"""Per-image boundary state for the HITL editor.

The editor keeps the immutable `auto` arrays from the analyzer plus a
parallel `corrected` array that holds user edits. When `corrected[i]`
is finite, it overrides `auto[i]`; when NaN, the auto value is used.
A dedicated sentinel value `ERASED_MARKER` represents an explicit
NaN ("user wants this column blanked"); we distinguish that from
"untouched" by tracking the `_touched` boolean per element.

The editor also keeps an undo stack of (boundary_name, prev_corrected,
prev_touched) snapshots. Redo would mirror this, but we keep it simple
for now: undo only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# A finite sentinel meaning "user has explicitly NaN'd this column".
# We can't store actual NaNs because we use NaN to mean "untouched".
ERASED_MARKER = -1.0e9


@dataclass
class _Snapshot:
    name: str
    corrected: np.ndarray
    touched: np.ndarray


@dataclass
class BoundaryEditor:
    width: int
    auto: dict[str, np.ndarray]
    corrected: dict[str, np.ndarray]
    _touched: dict[str, np.ndarray] = field(init=False)
    _undo: list[_Snapshot] = field(init=False, default_factory=list)
    _dirty: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._touched = {
            k: ~np.isnan(v) for k, v in self.corrected.items()
        }

    # ----------------------------------------------------------------- query

    @property
    def dirty(self) -> bool:
        return self._dirty

    def effective(self, name: str) -> np.ndarray:
        """Auto values, overridden where corrected is set (and not erased)."""
        out = self.auto[name].copy()
        touched = self._touched[name]
        corr = self.corrected[name]
        # Erased columns become NaN; touched-with-value override auto.
        erased = touched & (corr == ERASED_MARKER)
        moved = touched & ~erased
        out[moved] = corr[moved]
        out[erased] = np.nan
        return out

    # ------------------------------------------------------------- mutations

    def _push_undo(self, name: str) -> None:
        snap = _Snapshot(
            name=name,
            corrected=self.corrected[name].copy(),
            touched=self._touched[name].copy(),
        )
        self._undo.append(snap)
        # Cap the stack so memory stays bounded.
        if len(self._undo) > 50:
            self._undo.pop(0)

    def apply_drag(self, name: str, x: int, y_new: float,
                    sigma: float = 5.0, single: bool = False) -> None:
        if x < 0 or x >= self.width:
            return
        self._push_undo(name)
        eff = self.effective(name)
        if single:
            self._set(name, x, y_new)
        else:
            current = eff[x]
            if np.isnan(current):
                # Nothing to anchor a delta around — just set this column.
                self._set(name, x, y_new)
            else:
                delta = y_new - current
                radius = int(np.ceil(3 * sigma))
                for dx in range(-radius, radius + 1):
                    xx = x + dx
                    if 0 <= xx < self.width and not np.isnan(eff[xx]):
                        weight = float(np.exp(-0.5 * (dx / sigma) ** 2))
                        self._set(name, xx, eff[xx] + delta * weight)
        self._dirty = True

    def apply_erase(self, name: str, x_start: int, x_end: int) -> None:
        x1 = max(0, min(self.width - 1, x_start))
        x2 = max(0, min(self.width - 1, x_end))
        if x1 > x2:
            x1, x2 = x2, x1
        self._push_undo(name)
        for x in range(x1, x2 + 1):
            self.corrected[name][x] = ERASED_MARKER
            self._touched[name][x] = True
        self._dirty = True

    def undo(self) -> None:
        if not self._undo:
            return
        snap = self._undo.pop()
        self.corrected[snap.name] = snap.corrected
        self._touched[snap.name] = snap.touched
        # Recompute dirty: any boundary still has touched entries?
        self._dirty = any(t.any() for t in self._touched.values())

    # ------------------------------------------------------------- internals

    def _set(self, name: str, x: int, y: float) -> None:
        self.corrected[name][x] = y
        self._touched[name][x] = True
