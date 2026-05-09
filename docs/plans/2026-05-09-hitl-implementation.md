# HITL Editor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a PySide6 desktop editor that loads `oct_results.xlsx`, lets the user drag boundary points and erase regions per image, and saves corrected boundaries to dedicated `*_corrected` columns + `<basename>_overlay_corrected.png` files.

**Architecture:**
Six modules under `src/hitl/` separated by concern: `storage` (xlsx I/O), `boundary_model` (per-image edit state + undo), `overlay_render` (corrected PNG renderer), `canvas` (QGraphicsView edit surface), `sidebar` (QListWidget file picker), `app` (QMainWindow assembling them). Entry point `main.py`. Logic modules (`storage`, `boundary_model`, `overlay_render`) are TDD with pytest. GUI modules use pytest-qt where practical and have a manual verification checklist.

**Tech Stack:** PySide6 (GUI), pandas + openpyxl (xlsx), numpy + PIL (rendering), pytest + pytest-qt (testing). Reuses `src/io_utils.py`, `src/oct_analyzer.py`, `src/viz.py` from the existing pipeline.

**Reference design:** [`docs/plans/2026-05-09-hitl-design.md`](2026-05-09-hitl-design.md)

**Reference data:** `data/mouse_data_org/output/oct_results.xlsx` (96-image batch already produced)

---

## Conventions used throughout this plan

- All paths absolute relative to `D:\workspace\sumin_claude\`.
- Run pytest from the project root: `cd D:/workspace/sumin_claude && python -m pytest <path> -v`.
- Commits use Korean-ish-feature-prefix matching existing log style (`feat:`, `chore:`, `test:`).
- One feature per commit. Every TDD task has its own commit.
- Hard-coded test data uses the already-generated `21_OS_4H` artefacts so tests don't depend on running the analyzer.

---

## Task 1: Environment setup

**Files:**
- Modify: `requirements.txt`

**Step 1: Add `pyside6` and `pytest-qt` to requirements**

Edit `requirements.txt`, append:

```
pyside6>=6.6
pytest>=8.0
pytest-qt>=4.4
```

**Step 2: Install**

Run:
```
pip install -r requirements.txt
```

Expected: `Successfully installed pyside6-… pytest-qt-…` (or "already satisfied").

**Step 3: Verify**

Run:
```
python -c "import PySide6, pytestqt; print('ok')"
```

Expected output: `ok`.

**Step 4: Commit**

```
git add requirements.txt
git commit -m "chore: add pyside6 + pytest-qt for HITL editor"
```

---

## Task 2: Create `src/hitl/` package skeleton

**Files:**
- Create: `src/hitl/__init__.py`
- Create: `tests/hitl/__init__.py`
- Create: `tests/hitl/conftest.py`

**Step 1: Make package directories**

```
mkdir -p src/hitl tests/hitl
```

**Step 2: Write `src/hitl/__init__.py`**

```python
"""Human-in-the-loop boundary editor for OCT analysis.

Modules:
  - storage:        reads/writes oct_results.xlsx (auto + *_corrected cols)
  - boundary_model: per-image boundary state with undo/redo
  - overlay_render: renders corrected overlay PNGs
  - canvas:         PySide6 edit surface (drag points, erase regions)
  - sidebar:        QListWidget showing files + ✓ corrected marker
  - app:            QMainWindow that assembles canvas + sidebar
  - main:           entry point (`python -m src.hitl.main`)
"""
```

**Step 3: Write `tests/hitl/__init__.py`**

Empty file (package marker).

**Step 4: Write `tests/hitl/conftest.py`**

```python
"""Shared test fixtures for HITL tests."""
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "mouse_data_org"
OUTPUT_DIR = DATA_DIR / "output"


@pytest.fixture
def oct_results_xlsx() -> Path:
    """Path to the batch-produced workbook used as test fixture."""
    p = OUTPUT_DIR / "oct_results.xlsx"
    if not p.exists():
        pytest.skip(f"{p} not present — run batch_process.py first")
    return p


@pytest.fixture
def sample_image_path() -> Path:
    p = DATA_DIR / "21_OS_4H.tif"
    if not p.exists():
        pytest.skip(f"{p} not present")
    return p


@pytest.fixture
def sample_image_stem() -> str:
    return "21_OS_4H"
```

**Step 5: Verify pytest discovers it**

Run:
```
python -m pytest tests/hitl -v --collect-only
```

Expected: `no tests collected` (no test files yet) — confirming pytest finds the directory.

**Step 6: Commit**

```
git add src/hitl/__init__.py tests/hitl/__init__.py tests/hitl/conftest.py
git commit -m "feat: scaffold src/hitl/ package + test conftest"
```

---

## Task 3: `storage.py` — load workbook into memory

**Files:**
- Create: `tests/hitl/test_storage_load.py`
- Create: `src/hitl/storage.py`

**Step 1: Write the failing test**

```python
# tests/hitl/test_storage_load.py
"""storage.load_workbook() reads the batch xlsx into a typed dict."""
from src.hitl.storage import load_workbook, ImageRecord


def test_load_workbook_returns_one_record_per_image(oct_results_xlsx, sample_image_stem):
    wb = load_workbook(oct_results_xlsx)
    assert len(wb.images) >= 1
    assert sample_image_stem in wb.images
    rec = wb.images[sample_image_stem]
    assert isinstance(rec, ImageRecord)
    assert rec.filename.endswith(".tif")
    assert rec.width > 0
    # At minimum, the auto detection arrays exist:
    for name in ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
        arr = rec.auto[name]
        assert arr.shape == (rec.width,)


def test_load_workbook_loads_corrected_columns_when_present(oct_results_xlsx):
    wb = load_workbook(oct_results_xlsx)
    # Corrected columns may be absent in a fresh batch — that's fine.
    for rec in wb.images.values():
        for name in ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
            assert name in rec.corrected         # always populated key
            arr = rec.corrected[name]
            assert arr.shape == (rec.width,)
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_storage_load.py -v
```

Expected: `ImportError` (storage module not yet written).

**Step 3: Write minimal implementation**

```python
# src/hitl/storage.py
"""Read/write `oct_results.xlsx` for the HITL editor.

Layout:
  - The xlsx has one `summary` sheet plus one detail sheet per image.
  - Each detail sheet's columns are the per-x measurements produced by
    the batch pipeline. We treat the auto-detection columns as immutable
    and store user edits in parallel `<name>_corrected` columns.

Workbook → memory:
  load_workbook(path) -> Workbook
    .images: dict[stem, ImageRecord]

Memory → workbook (separate task)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


AUTO_COLS = ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y")


@dataclass
class ImageRecord:
    stem: str                  # e.g. "21_OS_4H"
    filename: str              # e.g. "21_OS_4H.tif"
    width: int                 # B-scan column count
    auto: dict[str, np.ndarray] = field(default_factory=dict)
    corrected: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class Workbook:
    path: Path
    summary: pd.DataFrame
    images: dict[str, ImageRecord] = field(default_factory=dict)


def load_workbook(path: str | Path) -> Workbook:
    p = Path(path)
    xls = pd.ExcelFile(p)
    summary = pd.read_excel(xls, sheet_name="summary")
    wb = Workbook(path=p, summary=summary)

    for sheet in xls.sheet_names:
        if sheet == "summary":
            continue
        if sheet == "corrected_summary":
            continue
        df = pd.read_excel(xls, sheet_name=sheet)
        if "x_local" not in df.columns:
            continue
        width = len(df)
        rec = ImageRecord(stem=sheet, filename=f"{sheet}.tif", width=width)
        for name in AUTO_COLS:
            rec.auto[name] = df[name].to_numpy(dtype=float) \
                if name in df.columns \
                else np.full(width, np.nan, dtype=float)
            corr_col = f"{name}_corrected"
            if corr_col in df.columns:
                rec.corrected[name] = df[corr_col].to_numpy(dtype=float)
            else:
                rec.corrected[name] = np.full(width, np.nan, dtype=float)
        wb.images[sheet] = rec
    return wb
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_storage_load.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```
git add src/hitl/storage.py tests/hitl/test_storage_load.py
git commit -m "feat(hitl): storage.load_workbook reads xlsx into ImageRecord dicts"
```

---

## Task 4: `boundary_model.py` — per-image edit state

**Files:**
- Create: `tests/hitl/test_boundary_model.py`
- Create: `src/hitl/boundary_model.py`

**Step 1: Write the failing test**

```python
# tests/hitl/test_boundary_model.py
"""BoundaryEditor holds the merged auto+corrected arrays and tracks edits."""
import numpy as np
import pytest

from src.hitl.boundary_model import BoundaryEditor


@pytest.fixture
def editor() -> BoundaryEditor:
    width = 100
    auto = {
        "TOP_y": np.linspace(50, 60, width).astype(float),
        "ONL_y": np.linspace(70, 80, width).astype(float),
        "BM_y": np.linspace(100, 110, width).astype(float),
        "DET_top_y": np.full(width, np.nan, dtype=float),
        "DET_bottom_y": np.full(width, np.nan, dtype=float),
    }
    corrected = {k: np.full(width, np.nan, dtype=float) for k in auto}
    return BoundaryEditor(width=width, auto=auto, corrected=corrected)


def test_effective_returns_auto_when_no_corrections(editor):
    eff = editor.effective("TOP_y")
    assert np.allclose(eff, editor.auto["TOP_y"])


def test_drag_overrides_effective_value_with_falloff(editor):
    target_x, target_y = 50, 40.0
    editor.apply_drag("TOP_y", target_x, target_y, sigma=5)
    eff = editor.effective("TOP_y")
    # The dragged column lands exactly on target_y …
    assert eff[target_x] == pytest.approx(target_y)
    # … neighbours move partially …
    assert eff[target_x - 3] != editor.auto["TOP_y"][target_x - 3]
    # … far columns are unchanged.
    assert eff[target_x + 30] == pytest.approx(editor.auto["TOP_y"][target_x + 30])


def test_apply_drag_with_ctrl_only_moves_single_column(editor):
    editor.apply_drag("TOP_y", 50, 40.0, sigma=5, single=True)
    eff = editor.effective("TOP_y")
    assert eff[50] == pytest.approx(40.0)
    assert eff[49] == pytest.approx(editor.auto["TOP_y"][49])
    assert eff[51] == pytest.approx(editor.auto["TOP_y"][51])


def test_erase_marks_range_nan(editor):
    editor.apply_erase("BM_y", 20, 30)
    eff = editor.effective("BM_y")
    assert np.all(np.isnan(eff[20:31]))
    assert not np.isnan(eff[19])
    assert not np.isnan(eff[31])


def test_undo_restores_previous_state(editor):
    before = editor.effective("TOP_y").copy()
    editor.apply_drag("TOP_y", 50, 40.0, sigma=5)
    editor.undo()
    assert np.allclose(editor.effective("TOP_y"), before)


def test_dirty_flag_true_after_edit(editor):
    assert not editor.dirty
    editor.apply_drag("TOP_y", 50, 40.0, sigma=5)
    assert editor.dirty
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_boundary_model.py -v
```

Expected: ImportError.

**Step 3: Write the implementation**

```python
# src/hitl/boundary_model.py
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
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_boundary_model.py -v
```

Expected: 6 passed.

**Step 5: Commit**

```
git add src/hitl/boundary_model.py tests/hitl/test_boundary_model.py
git commit -m "feat(hitl): boundary_model with drag/erase/undo + ERASED sentinel"
```

---

## Task 5: `storage.py` — save corrections back to xlsx

**Files:**
- Modify: `src/hitl/storage.py`
- Create: `tests/hitl/test_storage_save.py`

**Step 1: Write failing tests**

```python
# tests/hitl/test_storage_save.py
"""storage.save_corrections() writes user edits back into oct_results.xlsx."""
from datetime import datetime
import shutil

import numpy as np
import pandas as pd
import pytest

from src.hitl.storage import (load_workbook, save_corrections, ERASED_MARKER,
                              CorrectedSnapshot, AUTO_COLS)


@pytest.fixture
def temp_xlsx(tmp_path, oct_results_xlsx):
    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    return dst


def test_save_writes_corrected_columns_for_image(temp_xlsx, sample_image_stem):
    wb = load_workbook(temp_xlsx)
    rec = wb.images[sample_image_stem]
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in AUTO_COLS}
    # Edit two columns of TOP_y at indices 0 and 1.
    corrected["TOP_y"][0] = 123.0
    corrected["TOP_y"][1] = 124.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 9, 10, 30, 0),
    )

    save_corrections(temp_xlsx, [snap], scale_um_per_px_y=3.87)

    df = pd.read_excel(temp_xlsx, sheet_name=sample_image_stem)
    assert "TOP_y_corrected" in df.columns
    assert df["TOP_y_corrected"].iloc[0] == pytest.approx(123.0)
    assert df["TOP_y_corrected"].iloc[1] == pytest.approx(124.0)


def test_save_recomputes_thicknesses_corrected(temp_xlsx, sample_image_stem):
    wb = load_workbook(temp_xlsx)
    rec = wb.images[sample_image_stem]
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in AUTO_COLS}
    # Move BM down by 5 px at column 0; TOP and ONL untouched.
    corrected["BM_y"][0] = float(rec.auto["BM_y"][0]) + 5.0

    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 9, 10, 30, 0),
    )
    save_corrections(temp_xlsx, [snap], scale_um_per_px_y=3.87)

    df = pd.read_excel(temp_xlsx, sheet_name=sample_image_stem)
    auto_total = df["total_thickness_um"].iloc[0]
    corr_total = df["total_thickness_um_corrected"].iloc[0]
    if not np.isnan(auto_total):
        # Increased BM (lower in image) means total_thickness grew.
        assert corr_total > auto_total


def test_save_creates_corrected_summary_sheet(temp_xlsx, sample_image_stem):
    wb = load_workbook(temp_xlsx)
    rec = wb.images[sample_image_stem]
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in AUTO_COLS}
    corrected["TOP_y"][0] = 123.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 9, 10, 30, 0),
    )
    save_corrections(temp_xlsx, [snap], scale_um_per_px_y=3.87)
    summary = pd.read_excel(temp_xlsx, sheet_name="corrected_summary")
    row = summary.loc[summary["filename"] == f"{sample_image_stem}.tif"]
    assert len(row) == 1
    assert int(row["n_corrected_cols"].iloc[0]) >= 1
    assert bool(row["corrected_TOP"].iloc[0]) is True


def test_save_uses_ERASED_string_for_explicit_nan(temp_xlsx, sample_image_stem):
    wb = load_workbook(temp_xlsx)
    rec = wb.images[sample_image_stem]
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in AUTO_COLS}
    corrected["TOP_y"][5] = ERASED_MARKER
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 9, 10, 30, 0),
    )
    save_corrections(temp_xlsx, [snap], scale_um_per_px_y=3.87)
    df = pd.read_excel(temp_xlsx, sheet_name=sample_image_stem)
    assert df["TOP_y_corrected"].iloc[5] == "ERASED" \
        or df["TOP_y_corrected"].iloc[5] == ERASED_MARKER
```

**Step 2: Run, confirm failures**

```
python -m pytest tests/hitl/test_storage_save.py -v
```

Expected: ImportError or function-not-defined.

**Step 3: Add the implementation**

Edit `src/hitl/storage.py`. Add at top after existing imports:

```python
from datetime import datetime

from openpyxl import load_workbook as _openpyxl_load
```

Re-export the marker so callers can use one place:

```python
from src.hitl.boundary_model import ERASED_MARKER  # noqa: F401
```

Add new dataclass and function:

```python
@dataclass
class CorrectedSnapshot:
    stem: str
    corrected: dict[str, np.ndarray]
    timestamp: datetime


def save_corrections(path: str | Path,
                     snapshots: list[CorrectedSnapshot],
                     scale_um_per_px_y: float) -> None:
    """Write user corrections to the workbook.

    For each snapshot:
      - Update the per-image sheet with `<name>_corrected` columns and
        the recomputed thickness columns.
      - ERASED_MARKER in `corrected` is written as the literal string
        `"ERASED"` so spreadsheets stay human-readable.
      - Append/update a row in `corrected_summary`.
    """
    p = Path(path)

    # Read the whole workbook into memory so we can rewrite it.
    xls = pd.ExcelFile(p)
    sheets: dict[str, pd.DataFrame] = {
        name: pd.read_excel(xls, sheet_name=name)
        for name in xls.sheet_names
    }

    summary_rows: list[dict] = []

    for snap in snapshots:
        if snap.stem not in sheets:
            continue
        df = sheets[snap.stem]

        # Apply each boundary's edits.
        any_corrected: dict[str, bool] = {}
        for name, arr in snap.corrected.items():
            corr_col = f"{name}_corrected"
            # Build a list of cell values: ERASED_MARKER → "ERASED",
            # finite → number, NaN → empty.
            cells = []
            for v in arr.tolist():
                if v == ERASED_MARKER:
                    cells.append("ERASED")
                elif np.isnan(v):
                    cells.append(np.nan)
                else:
                    cells.append(float(v))
            df[corr_col] = cells
            any_corrected[name] = any(c == "ERASED" or
                                       (isinstance(c, float) and not np.isnan(c))
                                       for c in cells)

        # Recompute thicknesses using effective boundary values
        # (auto where no correction, corrected otherwise).
        eff: dict[str, np.ndarray] = {}
        for name in AUTO_COLS:
            auto = df[name].to_numpy(dtype=float)
            corr_col = f"{name}_corrected"
            corr_raw = df[corr_col].tolist() if corr_col in df.columns else []
            out = auto.copy()
            for i, v in enumerate(corr_raw):
                if v == "ERASED":
                    out[i] = np.nan
                elif isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
                    out[i] = float(v)
            eff[name] = out

        # total = (BM - TOP) * scale, outer = (BM - ONL) * scale, det = (DET_b - DET_t) * scale
        df["total_thickness_um_corrected"] = (eff["BM_y"] - eff["TOP_y"]) * scale_um_per_px_y
        df["outer_thickness_um_corrected"] = (eff["BM_y"] - eff["ONL_y"]) * scale_um_per_px_y
        df["detachment_thickness_um_corrected"] = (eff["DET_bottom_y"] - eff["DET_top_y"]) * scale_um_per_px_y

        # corrected_by_user flag for the row.
        any_per_col = np.zeros(len(df), dtype=bool)
        for name in AUTO_COLS:
            corr_col = f"{name}_corrected"
            for i, v in enumerate(df[corr_col].tolist()):
                if v == "ERASED" or (isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v))):
                    any_per_col[i] = True
        df["corrected_by_user"] = any_per_col

        sheets[snap.stem] = df

        # Build the summary row.
        n_corr = int(any_per_col.sum())
        mean_total = float(np.nanmean(df["total_thickness_um"])) \
            if "total_thickness_um" in df.columns else float("nan")
        mean_total_corr = float(np.nanmean(df["total_thickness_um_corrected"]))
        summary_rows.append({
            "filename": f"{snap.stem}.tif",
            "n_corrected_cols": n_corr,
            "corrected_TOP": bool(any_corrected.get("TOP_y", False)),
            "corrected_ONL": bool(any_corrected.get("ONL_y", False)),
            "corrected_BM": bool(any_corrected.get("BM_y", False)),
            "corrected_DET": bool(any_corrected.get("DET_top_y", False)
                                  or any_corrected.get("DET_bottom_y", False)),
            "mean_total_um": mean_total,
            "mean_total_um_corrected": mean_total_corr,
            "edit_timestamp": snap.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # Merge into / create corrected_summary.
    if "corrected_summary" in sheets:
        old = sheets["corrected_summary"]
        new = pd.DataFrame(summary_rows)
        # Replace rows for files we just edited, keep others.
        edited_files = set(r["filename"] for r in summary_rows)
        old = old[~old["filename"].isin(edited_files)]
        sheets["corrected_summary"] = pd.concat([old, new], ignore_index=True)
    else:
        sheets["corrected_summary"] = pd.DataFrame(summary_rows)

    # Write all sheets back. ExcelWriter with mode="w" recreates the file
    # without losing what we already loaded.
    with pd.ExcelWriter(p, engine="openpyxl", mode="w") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_storage_save.py -v
```

Expected: 4 passed.

**Step 5: Commit**

```
git add src/hitl/storage.py tests/hitl/test_storage_save.py
git commit -m "feat(hitl): storage.save_corrections writes corrected cols + summary sheet"
```

---

## Task 6: `overlay_render.py` — render corrected overlay PNG

**Files:**
- Create: `tests/hitl/test_overlay_render.py`
- Create: `src/hitl/overlay_render.py`

**Step 1: Write failing test**

```python
# tests/hitl/test_overlay_render.py
"""overlay_render writes <stem>_overlay_corrected.png."""
import numpy as np
from PIL import Image

from src.hitl.overlay_render import render_corrected_overlay


def test_render_writes_png(tmp_path, sample_image_path):
    boundaries = {
        "TOP_y": np.full(2032, 100.0),
        "ONL_y": np.full(2032, 130.0),
        "BM_y": np.full(2032, 160.0),
        "DET_top_y": np.full(2032, np.nan),
        "DET_bottom_y": np.full(2032, np.nan),
    }
    out = tmp_path / "test_overlay_corrected.png"
    render_corrected_overlay(sample_image_path, boundaries, out)
    assert out.exists()
    arr = np.array(Image.open(out))
    # Original image is RGB.
    assert arr.ndim == 3 and arr.shape[2] == 3
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_overlay_render.py -v
```

Expected: ImportError.

**Step 3: Write the implementation**

```python
# src/hitl/overlay_render.py
"""Render an overlay PNG using corrected boundary arrays.

Reuses the existing renderer (`src/viz.py`) plus the layout/scale
detection from `src/io_utils.py`. The boundary arrays passed in are
*B-scan-relative* coordinates (same convention the analyzer uses).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import sys

# Make the existing analyzer modules importable.
SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from io_utils import load_oct                     # noqa: E402
from oct_analyzer import BoundaryResult           # noqa: E402
from viz import save_overlay                       # noqa: E402


def render_corrected_overlay(image_path: str | Path,
                             boundaries: dict[str, np.ndarray],
                             out_path: str | Path) -> Path:
    """Render an overlay using the supplied (corrected) boundary arrays."""
    img = load_oct(image_path)
    has_det = bool(np.any(np.isfinite(boundaries["DET_top_y"])))

    # Build a BoundaryResult that the existing renderer accepts.
    b = BoundaryResult(
        TOP=boundaries["TOP_y"].astype(np.float32),
        ONL=boundaries["ONL_y"].astype(np.float32),
        BM=boundaries["BM_y"].astype(np.float32),
        DET_top=boundaries["DET_top_y"].astype(np.float32),
        DET_bottom=boundaries["DET_bottom_y"].astype(np.float32),
        has_detachment=has_det,
        center_x_local=img.layout.center_x - img.layout.left_x,
    )
    return save_overlay(img, b, out_path)
```

**Step 4: Run test**

```
python -m pytest tests/hitl/test_overlay_render.py -v
```

Expected: 1 passed.

**Step 5: Commit**

```
git add src/hitl/overlay_render.py tests/hitl/test_overlay_render.py
git commit -m "feat(hitl): overlay_render reuses viz.save_overlay for corrected PNG"
```

---

## Task 7: `canvas.py` — PySide6 edit surface

**Files:**
- Create: `tests/hitl/test_canvas.py`
- Create: `src/hitl/canvas.py`

**Step 1: Write failing test**

GUI tests use the `qtbot` fixture from `pytest-qt`.

```python
# tests/hitl/test_canvas.py
"""OverlayCanvas dispatches drag and erase events to the BoundaryEditor."""
import numpy as np
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QPointF, Qt

from src.hitl.boundary_model import BoundaryEditor
from src.hitl.canvas import OverlayCanvas, EditMode


@pytest.fixture
def editor() -> BoundaryEditor:
    width = 200
    auto = {
        "TOP_y": np.full(width, 80.0),
        "ONL_y": np.full(width, 110.0),
        "BM_y": np.full(width, 150.0),
        "DET_top_y": np.full(width, np.nan),
        "DET_bottom_y": np.full(width, np.nan),
    }
    corrected = {k: np.full(width, np.nan) for k in auto}
    return BoundaryEditor(width=width, auto=auto, corrected=corrected)


def test_canvas_constructs_with_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    assert canvas.editor is editor


def test_canvas_drag_delegates_to_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("TOP_y")
    canvas.set_mode(EditMode.DRAG)

    # Simulate a drag at column 100 to y=50.
    canvas.simulate_drag_to(x=100, y=50.0)
    eff = editor.effective("TOP_y")
    assert eff[100] == pytest.approx(50.0)


def test_canvas_erase_delegates_to_editor(qtbot, editor):
    img = np.zeros((300, 200, 3), dtype=np.uint8)
    canvas = OverlayCanvas()
    qtbot.addWidget(canvas)
    canvas.set_image(img)
    canvas.set_editor(editor)
    canvas.set_active_boundary("BM_y")
    canvas.set_mode(EditMode.ERASE)

    canvas.simulate_erase(x_start=10, x_end=20)
    eff = editor.effective("BM_y")
    assert np.all(np.isnan(eff[10:21]))
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_canvas.py -v
```

Expected: ImportError.

**Step 3: Write the implementation**

```python
# src/hitl/canvas.py
"""PySide6 graphics view that hosts an OCT image with editable boundary lines.

The canvas exposes:
  - set_image(numpy_rgb)
  - set_editor(BoundaryEditor)
  - set_active_boundary(name)
  - set_mode(EditMode.DRAG | EditMode.ERASE)
  - simulate_drag_to(x, y) and simulate_erase(x_start, x_end) for tests

Real interaction mapping:
  - Drag mode: left-click + drag → editor.apply_drag(active, x, y, sigma)
  - Erase mode: left-click + drag → editor.apply_erase(active, x1, x2)
  - Right-click + drag pans, Ctrl + wheel zooms.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPainterPath, QPen, QPixmap,
                            QWheelEvent)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem,
                                QGraphicsPixmapItem, QGraphicsRectItem,
                                QGraphicsScene, QGraphicsView)


from .boundary_model import BoundaryEditor, ERASED_MARKER


class EditMode(Enum):
    DRAG = "drag"
    ERASE = "erase"


# Colour scheme matches the existing overlay renderer.
COLORS = {
    "TOP_y": (0, 230, 0),
    "ONL_y": (0, 220, 220),
    "BM_y": (230, 50, 200),
    "DET_top_y": (255, 230, 0),
    "DET_bottom_y": (0, 0, 0),
}


@dataclass
class _Stroke:
    x_start: int = -1
    last_x: int = -1


class OverlayCanvas(QGraphicsView):
    DRAG_SIGMA = 5.0

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._line_items: dict[str, QGraphicsPathItem] = {}
        self._erase_rect: QGraphicsRectItem | None = None
        self._stroke = _Stroke()
        self.editor: BoundaryEditor | None = None
        self._active = "TOP_y"
        self._mode = EditMode.DRAG
        self._image_offset_x = 0  # B-scan left_x in image coordinates

        self.setRenderHint(self.renderHints())
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    # -------------------------------------------------------------- inputs

    def set_image(self, rgb: np.ndarray, offset_x: int = 0) -> None:
        h, w, _ = rgb.shape
        # Convert numpy RGB to QImage. Make a contiguous copy so the
        # underlying buffer stays alive.
        buf = np.ascontiguousarray(rgb).tobytes()
        qimg = QImage(buf, w, h, 3 * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        if self._pixmap_item is None:
            self._pixmap_item = self._scene.addPixmap(pix)
            self._pixmap_item.setZValue(0)
        else:
            self._pixmap_item.setPixmap(pix)
        self._scene.setSceneRect(QRectF(0, 0, w, h))
        self._image_offset_x = int(offset_x)

    def set_editor(self, editor: BoundaryEditor) -> None:
        self.editor = editor
        self._refresh_lines()

    def set_active_boundary(self, name: str) -> None:
        self._active = name

    def set_mode(self, mode: EditMode) -> None:
        self._mode = mode

    # ----------------------------------------------------- line rendering

    def _refresh_lines(self) -> None:
        for name in COLORS:
            if name in self._line_items:
                self._scene.removeItem(self._line_items[name])
                del self._line_items[name]
        if self.editor is None:
            return
        for name in COLORS:
            arr = self.editor.effective(name)
            path = self._array_to_path(arr)
            item = QGraphicsPathItem(path)
            r, g, b = COLORS[name]
            pen = QPen(QColor(r, g, b))
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(10)
            self._scene.addItem(item)
            self._line_items[name] = item

    def _array_to_path(self, arr: np.ndarray) -> QPainterPath:
        path = QPainterPath()
        prev_valid = False
        for x_local, y in enumerate(arr):
            x = x_local + self._image_offset_x
            if np.isnan(y):
                prev_valid = False
                continue
            if not prev_valid:
                path.moveTo(x, float(y))
                prev_valid = True
            else:
                path.lineTo(x, float(y))
        return path

    # ------------------------------------------------------- mouse events

    def mousePressEvent(self, event):  # noqa: D401
        if event.button() == Qt.LeftButton and self.editor is not None:
            sp = self.mapToScene(event.position().toPoint())
            self._stroke = _Stroke(
                x_start=int(sp.x()) - self._image_offset_x,
                last_x=int(sp.x()) - self._image_offset_x,
            )
            if self._mode == EditMode.ERASE:
                # Visualise the erase rectangle.
                rect = QRectF(sp.x(), 0, 1, self._scene.sceneRect().height())
                self._erase_rect = QGraphicsRectItem(rect)
                self._erase_rect.setPen(QPen(QColor(255, 0, 0)))
                self._erase_rect.setBrush(QBrush(QColor(255, 0, 0, 60)))
                self._erase_rect.setZValue(50)
                self._scene.addItem(self._erase_rect)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: D401
        if self.editor is None or self._stroke.x_start < 0:
            super().mouseMoveEvent(event)
            return
        sp = self.mapToScene(event.position().toPoint())
        x = int(sp.x()) - self._image_offset_x
        y = float(sp.y())
        if self._mode == EditMode.DRAG:
            self.editor.apply_drag(self._active, x, y,
                                   sigma=self.DRAG_SIGMA,
                                   single=event.modifiers() & Qt.ControlModifier)
            self._refresh_lines()
        elif self._mode == EditMode.ERASE and self._erase_rect is not None:
            x_start = self._stroke.x_start + self._image_offset_x
            x_now = int(sp.x())
            x_left = min(x_start, x_now)
            x_right = max(x_start, x_now)
            self._erase_rect.setRect(
                QRectF(x_left, 0, x_right - x_left + 1,
                       self._scene.sceneRect().height()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: D401
        if event.button() == Qt.LeftButton and self.editor is not None \
                and self._stroke.x_start >= 0:
            sp = self.mapToScene(event.position().toPoint())
            x_end = int(sp.x()) - self._image_offset_x
            if self._mode == EditMode.ERASE:
                self.editor.apply_erase(self._active,
                                        self._stroke.x_start, x_end)
                if self._erase_rect is not None:
                    self._scene.removeItem(self._erase_rect)
                    self._erase_rect = None
                self._refresh_lines()
            self._stroke = _Stroke()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.scale(factor, factor)
            return
        super().wheelEvent(event)

    # ------------------------------------------------------- test helpers

    def simulate_drag_to(self, x: int, y: float) -> None:
        """Headless equivalent of pressing, dragging, releasing a single point."""
        if self.editor is None:
            return
        self.editor.apply_drag(self._active, x, y, sigma=self.DRAG_SIGMA)
        self._refresh_lines()

    def simulate_erase(self, x_start: int, x_end: int) -> None:
        if self.editor is None:
            return
        self.editor.apply_erase(self._active, x_start, x_end)
        self._refresh_lines()
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_canvas.py -v
```

Expected: 3 passed (a Qt application is implicitly created by `qtbot`).

**Step 5: Commit**

```
git add src/hitl/canvas.py tests/hitl/test_canvas.py
git commit -m "feat(hitl): canvas with drag/erase + headless simulation hooks"
```

---

## Task 8: `sidebar.py` — file list with corrected indicator

**Files:**
- Create: `tests/hitl/test_sidebar.py`
- Create: `src/hitl/sidebar.py`

**Step 1: Write failing test**

```python
# tests/hitl/test_sidebar.py
"""FileListView shows ✓ for images that already have corrections."""
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from src.hitl.sidebar import FileListView, FileEntry


def test_sidebar_marks_corrected_files(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="21_OS_4H", filename="21_OS_4H.tif", has_corrections=True),
        FileEntry(stem="21_OS_4H(1)", filename="21_OS_4H(1).tif", has_corrections=False),
    ])
    item0 = sb.item(0)
    item1 = sb.item(1)
    assert "✓" in item0.text()
    assert "✓" not in item1.text()


def test_sidebar_emits_signal_on_selection(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="a", filename="a.tif", has_corrections=False),
        FileEntry(stem="b", filename="b.tif", has_corrections=False),
    ])
    with qtbot.waitSignal(sb.image_selected, timeout=500) as blocker:
        sb.setCurrentRow(1)
    assert blocker.args == ["b"]


def test_sidebar_update_marks_after_save(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="a", filename="a.tif", has_corrections=False),
    ])
    assert "✓" not in sb.item(0).text()
    sb.mark_corrected("a", True)
    assert "✓" in sb.item(0).text()
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_sidebar.py -v
```

Expected: ImportError.

**Step 3: Write the implementation**

```python
# src/hitl/sidebar.py
"""Left-side file list with a ✓ marker for images that have corrections."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget


@dataclass
class FileEntry:
    stem: str
    filename: str
    has_corrections: bool = False


class FileListView(QListWidget):
    image_selected = Signal(str)   # emits stem

    def __init__(self):
        super().__init__()
        self._stem_for_row: list[str] = []
        self.currentRowChanged.connect(self._on_row_changed)

    # ----------------------------------------------------------- mutators

    def set_entries(self, entries: list[FileEntry]) -> None:
        self.clear()
        self._stem_for_row = []
        for e in entries:
            self.addItem(self._format(e.has_corrections, e.filename))
            self._stem_for_row.append(e.stem)

    def mark_corrected(self, stem: str, has_corrections: bool) -> None:
        if stem not in self._stem_for_row:
            return
        row = self._stem_for_row.index(stem)
        item = self.item(row)
        # Strip any leading "✓ " then re-prefix if needed.
        text = item.text().lstrip("✓ ")
        item.setText(self._format(has_corrections, text))

    # ----------------------------------------------------------- internal

    @staticmethod
    def _format(has_corrections: bool, filename: str) -> str:
        return f"✓ {filename}" if has_corrections else f"  {filename}"

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._stem_for_row):
            self.image_selected.emit(self._stem_for_row[row])
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_sidebar.py -v
```

Expected: 3 passed.

**Step 5: Commit**

```
git add src/hitl/sidebar.py tests/hitl/test_sidebar.py
git commit -m "feat(hitl): sidebar file list with corrected ✓ marker + selection signal"
```

---

## Task 9: `app.py` — MainWindow assembly

**Files:**
- Create: `tests/hitl/test_app.py`
- Create: `src/hitl/app.py`

**Step 1: Write failing test**

```python
# tests/hitl/test_app.py
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
```

**Step 2: Run, confirm failure**

```
python -m pytest tests/hitl/test_app.py -v
```

Expected: ImportError.

**Step 3: Write the implementation**

```python
# src/hitl/app.py
"""Main window: sidebar + canvas + storage glue."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QMainWindow,
                                QMessageBox, QStatusBar, QToolBar)

# Make sibling analysis modules importable.
SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from io_utils import load_oct                                       # noqa: E402

from .boundary_model import BoundaryEditor                          # noqa: E402
from .canvas import EditMode, OverlayCanvas                         # noqa: E402
from .overlay_render import render_corrected_overlay                # noqa: E402
from .sidebar import FileEntry, FileListView                        # noqa: E402
from .storage import (CorrectedSnapshot, ERASED_MARKER, Workbook,
                      load_workbook, save_corrections, AUTO_COLS)  # noqa: E402


class MainWindow(QMainWindow):
    def __init__(self, workbook_path: str | Path,
                 image_dir: str | Path) -> None:
        super().__init__()
        self.workbook_path = Path(workbook_path)
        self.image_dir = Path(image_dir)
        self._editors: dict[str, BoundaryEditor] = {}
        self._wb: Workbook | None = None
        self._current_stem: str | None = None
        self._scale_y = 3.87  # default; overridden when summary sheet has it.

        self._build_ui()
        self._reload_workbook()

    # ----------------------------------------------------------- UI build

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

        # Boundary picker shortcuts.
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

    # --------------------------------------------------------- workbook

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

    # ------------------------------------------------------ image switching

    def select_image(self, stem: str) -> None:
        if self._wb is None:
            return
        if stem not in self._wb.images:
            return
        self._current_stem = stem
        rec = self._wb.images[stem]
        # Lazy-create the editor for this image.
        if stem not in self._editors:
            self._editors[stem] = BoundaryEditor(width=rec.width,
                                                  auto=rec.auto,
                                                  corrected={
                                                      k: v.copy()
                                                      for k, v in rec.corrected.items()
                                                  })
        # Load image and push to canvas.
        img_path = self.image_dir / rec.filename
        img = load_oct(img_path)
        self.canvas.set_image(img.rgb, offset_x=img.layout.left_x)
        self.canvas.set_editor(self._editors[stem])
        self.canvas.set_active_boundary("TOP_y")
        self.statusBar().showMessage(f"{rec.filename} | {rec.width} cols")

    # ---------------------------------------------------------- save / undo

    def save_current_image(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        snap = CorrectedSnapshot(
            stem=self._current_stem,
            corrected={k: editor.corrected[k].copy()
                       for k in editor.corrected},
            timestamp=datetime.now(),
        )
        # Replace NaNs with marker for ERASED, leave numbers as-is.
        # Actually our boundary_model already stores ERASED_MARKER
        # directly in the array, so no conversion needed.
        save_corrections(self.workbook_path, [snap],
                          scale_um_per_px_y=self._scale_y)
        # Render PNG.
        rec = self._wb.images[self._current_stem]
        img_path = self.image_dir / rec.filename
        out_path = self.workbook_path.parent / f"{self._current_stem}_overlay_corrected.png"
        boundaries = {k: editor.effective(k) for k in editor.auto}
        render_corrected_overlay(img_path, boundaries, out_path)
        self.sidebar.mark_corrected(self._current_stem, True)
        self.statusBar().showMessage(f"Saved {rec.filename}")

    def _undo(self) -> None:
        if self._current_stem is None:
            return
        editor = self._editors[self._current_stem]
        editor.undo()
        self.canvas._refresh_lines()


def run(workbook_path: str | Path, image_dir: str | Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(workbook_path=workbook_path, image_dir=image_dir)
    win.resize(1400, 800)
    win.show()
    app.exec()
```

**Step 4: Run tests**

```
python -m pytest tests/hitl/test_app.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```
git add src/hitl/app.py tests/hitl/test_app.py
git commit -m "feat(hitl): app MainWindow ties storage+sidebar+canvas+overlay-render"
```

---

## Task 10: `main.py` — entry point + run smoke test

**Files:**
- Create: `src/hitl/main.py`

**Step 1: Write the entry point**

```python
# src/hitl/main.py
"""Run as `python -m src.hitl.main` from the project root."""
from __future__ import annotations

import argparse
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="OCT HITL boundary editor")
    parser.add_argument("--workbook", type=Path,
                        default=Path("data/mouse_data_org/output/oct_results.xlsx"),
                        help="Path to oct_results.xlsx (default: project default)")
    parser.add_argument("--image-dir", type=Path,
                        default=Path("data/mouse_data_org"),
                        help="Folder holding the source TIFFs")
    args = parser.parse_args()

    if not args.workbook.exists():
        raise SystemExit(f"Workbook not found: {args.workbook}")
    if not args.image_dir.exists():
        raise SystemExit(f"Image dir not found: {args.image_dir}")
    run(args.workbook, args.image_dir)


if __name__ == "__main__":
    main()
```

**Step 2: Smoke test launch**

Run (this opens a window — close it to continue):
```
python -m src.hitl.main
```

Expected: window appears with the file list populated, first image rendered with boundary lines visible. Closing the window returns control to the shell.

If the window doesn't open, common fixes:
- `pip install pyside6` again, ensure version ≥ 6.6.
- Run from project root (so the `data/` paths resolve).

**Step 3: Commit**

```
git add src/hitl/main.py
git commit -m "feat(hitl): main.py entry point with --workbook/--image-dir args"
```

---

## Task 11: Manual verification checklist

This is not a code change but a hand-run regression list. Do not skip.

**Run:**
```
python -m src.hitl.main
```

**Verify each of:**

| # | Action | Expected |
|---|---|---|
| 1 | Window opens; sidebar shows ≥ 1 image | OK |
| 2 | Click first image | Canvas shows image + 3 lines (TOP/ONL/BM); status bar updates |
| 3 | Press `2` | Active boundary = ONL_y (no visible change yet) |
| 4 | Drag a point on the cyan ONL line | The line bends locally, neighbours follow with falloff |
| 5 | Ctrl + drag a point | Only that single column moves |
| 6 | Switch to Erase mode (toolbar) | Drag a rectangle on TOP — that x-range disappears |
| 7 | Press Ctrl+Z | Last edit reverts |
| 8 | Press Ctrl+S | Status bar shows "Saved …"; sidebar gains ✓ |
| 9 | Close + reopen the app | The ✓ persists; the lines reflect the saved corrections |
| 10 | Open `oct_results.xlsx` in Excel | The image's sheet has populated `*_corrected` columns and `corrected_summary` shows the row |
| 11 | Open `<stem>_overlay_corrected.png` | Lines reflect the corrections |

If any item fails, file the specific failure as a follow-up bug — do not patch ad-hoc.

**Commit (verification log):**

```
git add docs/plans/2026-05-09-hitl-implementation.md
git commit --allow-empty -m "chore: HITL manual verification checklist run"
```

---

## Appendix A: Running the tests

```
# All HITL tests:
python -m pytest tests/hitl -v

# Just the headless ones (no Qt display required):
python -m pytest tests/hitl/test_storage_load.py \
                tests/hitl/test_storage_save.py \
                tests/hitl/test_boundary_model.py \
                tests/hitl/test_overlay_render.py -v

# Qt tests (need a display; on headless CI, install xvfb / Qt offscreen):
QT_QPA_PLATFORM=offscreen python -m pytest tests/hitl/test_canvas.py \
                                            tests/hitl/test_sidebar.py \
                                            tests/hitl/test_app.py -v
```

## Appendix B: Things deliberately left out (YAGNI)

- **Redo stack.** Undo only. Add later if pain.
- **Multi-select bulk edits.** One image at a time.
- **Project config (`.hitl-rc.json` etc.).** Defaults are fine; CLI flags cover the rest.
- **Histogram / brightness panel.** The corrected overlay PNG already shows what's needed.
- **Auto-save.** Explicit Ctrl+S only — corrections are deliberate.
