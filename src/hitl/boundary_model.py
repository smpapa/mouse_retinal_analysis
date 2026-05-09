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

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# A finite sentinel meaning "user has explicitly NaN'd this column".
# We can't store actual NaNs because we use NaN to mean "untouched".
ERASED_MARKER = -1.0e9
# Any value below this threshold is treated as the erased sentinel.
# Legitimate y coordinates are pixel rows and never reach this magnitude.
ERASED_THRESHOLD = -1.0e8

# Maximum depth of the undo stack.
UNDO_DEPTH = 50

# Gaussian falloff is truncated past this many sigmas.
GAUSSIAN_RADIUS_SIGMAS = 3

# Canonical ordered list of boundary names, used across modules
# (storage columns, canvas line dict, app status bar, etc.). Single
# source of truth so adding a new boundary needs only one edit.
BOUNDARY_NAMES: tuple[str, ...] = (
    "TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y",
)


@dataclass
class _Snapshot:
    name: str
    corrected: np.ndarray
    touched: np.ndarray


@dataclass
class _DragSession:
    name: str
    x_anchor: int
    sigma: float
    single: bool
    baseline: np.ndarray  # snapshot of effective(name) at begin_drag


@dataclass
class _PaintSession:
    name: str
    last_x: int
    last_y: float


@dataclass
class BoundaryEditor:
    width: int
    auto: dict[str, np.ndarray]
    corrected: dict[str, np.ndarray]
    _touched: dict[str, np.ndarray] = field(init=False)
    _undo: deque = field(
        init=False,
        default_factory=lambda: deque(maxlen=UNDO_DEPTH),
    )
    _dirty: bool = field(init=False, default=False)
    _drag: Optional[_DragSession] = field(init=False, default=None)
    _paint: Optional[_PaintSession] = field(init=False, default=None)

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
        # Use a magnitude threshold instead of float equality to remain
        # robust against any future arithmetic on `corr`.
        erased = touched & (corr < ERASED_THRESHOLD)
        moved = touched & ~erased
        out[moved] = corr[moved]
        out[erased] = np.nan
        return out

    # ------------------------------------------------------------- mutations

    def _check_name(self, name: str) -> None:
        if name not in self.auto:
            raise KeyError(
                f"Unknown boundary: {name}. Known: {list(self.auto)}"
            )

    def _push_undo(self, name: str) -> None:
        snap = _Snapshot(
            name=name,
            corrected=self.corrected[name].copy(),
            touched=self._touched[name].copy(),
        )
        self._undo.append(snap)

    def begin_drag(self, name: str, x: int, sigma: float = 5.0,
                   single: bool = False) -> None:
        """Start a drag session.

        Captures a baseline snapshot of `effective(name)` and pushes a
        single undo entry. Subsequent `update_drag` calls apply against
        this baseline (not the current effective value), so repeated
        updates with the same y do not compound.
        """
        self._check_name(name)
        if not (0 <= x < self.width):
            raise ValueError(
                f"x={x} out of range [0, {self.width})"
            )
        self._push_undo(name)
        self._drag = _DragSession(
            name=name,
            x_anchor=x,
            sigma=sigma,
            single=single,
            baseline=self.effective(name).copy(),
        )

    def update_drag(self, y_new: float) -> None:
        """Apply the new y against the captured baseline (idempotent)."""
        if self._drag is None:
            return
        s = self._drag
        x = s.x_anchor
        baseline = s.baseline
        if s.single:
            self._set(s.name, x, y_new)
            self._dirty = True
            return
        anchor = baseline[x]
        if np.isnan(anchor):
            # Nothing to anchor a delta around — just set this column.
            self._set(s.name, x, y_new)
        else:
            delta = y_new - anchor
            radius = int(np.ceil(GAUSSIAN_RADIUS_SIGMAS * s.sigma))
            for dx in range(-radius, radius + 1):
                xx = x + dx
                if 0 <= xx < self.width and not np.isnan(baseline[xx]):
                    weight = float(np.exp(-0.5 * (dx / s.sigma) ** 2))
                    self._set(s.name, xx, baseline[xx] + delta * weight)
        self._dirty = True

    def end_drag(self) -> None:
        """Finish the drag session; subsequent `update_drag` is a no-op."""
        self._drag = None

    def begin_paint(self, name: str, x: int, y: float) -> None:
        """Start a paint-trace session.

        Each subsequent `paint_to(x, y)` writes the boundary along a
        straight line between the previous and current point — every
        integer column in between gets a y from linear interpolation.
        Pushes a single undo entry covering the whole session.
        """
        self._check_name(name)
        x = max(0, min(self.width - 1, int(x)))
        self._push_undo(name)
        self._set(name, x, float(y))
        self._paint = _PaintSession(name=name, last_x=x, last_y=float(y))
        self._dirty = True

    def paint_to(self, x: int, y: float) -> None:
        """Linearly interpolate from the last point to (x, y), writing
        every integer column between."""
        if self._paint is None:
            return
        p = self._paint
        x = max(0, min(self.width - 1, int(x)))
        y = float(y)
        if x == p.last_x:
            self._set(p.name, x, y)
        else:
            step = 1 if x > p.last_x else -1
            dx_total = x - p.last_x
            for xi in range(p.last_x, x + step, step):
                t = (xi - p.last_x) / dx_total
                yi = p.last_y + t * (y - p.last_y)
                self._set(p.name, xi, yi)
        p.last_x = x
        p.last_y = y
        self._dirty = True

    def end_paint(self) -> None:
        """Finish the paint session; subsequent `paint_to` is a no-op."""
        self._paint = None

    def apply_drag(self, name: str, x: int, y_new: float,
                   sigma: float = 5.0, single: bool = False) -> None:
        """One-shot drag: begin + update + end."""
        self._check_name(name)
        x = max(0, min(self.width - 1, x))
        self.begin_drag(name, x, sigma=sigma, single=single)
        self.update_drag(y_new)
        self.end_drag()

    def apply_erase(self, name: str, x_start: int, x_end: int) -> None:
        self._check_name(name)
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
        # Undo is itself a session-level mutation — keep the dirty flag
        # monotonic so storage knows to write on save.
        self._dirty = True

    def mark_clean(self) -> None:
        """Reset the dirty flag; called by storage after a successful save."""
        self._dirty = False

    # ------------------------------------------------------------- internals

    def _set(self, name: str, x: int, y: float) -> None:
        self.corrected[name][x] = y
        self._touched[name][x] = True
