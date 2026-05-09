"""Read/write `oct_results.xlsx` for the HITL editor.

Layout:
  - The xlsx has one `summary` sheet plus one detail sheet per image.
  - Each detail sheet's columns are the per-x measurements produced by
    the batch pipeline. We treat the auto-detection columns as immutable
    and store user edits in parallel `<name>_corrected` columns.

Workbook -> memory:
  load_workbook(path) -> Workbook
    .images: dict[stem, ImageRecord]

Memory -> workbook (separate task)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.hitl.boundary_model import (BOUNDARY_NAMES, ERASED_MARKER,
                                       ERASED_THRESHOLD)


# Re-exported for backwards compatibility — older callers import AUTO_COLS
# directly from `storage`. Both names refer to the same canonical tuple.
AUTO_COLS = BOUNDARY_NAMES

# String literal written to xlsx to represent an erased (explicit-NaN) cell.
ERASED_CELL_TEXT = "ERASED"


def _is_set_cell(v) -> bool:
    """True if a corrected-column cell holds a user edit (number or ERASED)."""
    if isinstance(v, str):
        return v == ERASED_CELL_TEXT
    try:
        return not np.isnan(float(v))
    except (TypeError, ValueError):
        return False


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

    # Sheet names may be truncated to 28 chars (with `_2`, `_3` for duplicates),
    # so we cannot derive the original filename/stem from the sheet name.
    # The batch writes summary rows and detail sheets in matching order, so we
    # zip the detail sheets against the `filename` column from the summary.
    if "filename" in summary.columns:
        summary_filenames = summary["filename"].tolist()
    else:
        summary_filenames = []
    fn_iter = iter(summary_filenames)

    for sheet in xls.sheet_names:
        if sheet == "summary":
            continue
        if sheet == "corrected_summary":
            continue
        df = pd.read_excel(xls, sheet_name=sheet)
        if "x_local" not in df.columns:
            continue
        try:
            filename = next(fn_iter)
        except StopIteration:
            # No corresponding summary row (e.g. unrelated future sheet).
            continue
        width = len(df)
        stem = Path(str(filename)).stem
        rec = ImageRecord(stem=stem, filename=str(filename), width=width)
        for name in AUTO_COLS:
            if name in df.columns:
                rec.auto[name] = pd.to_numeric(
                    df[name], errors="coerce"
                ).to_numpy(dtype=float)
            else:
                rec.auto[name] = np.full(width, np.nan, dtype=float)
            corr_col = f"{name}_corrected"
            if corr_col in df.columns:
                # Map literal "ERASED" cells back to ERASED_MARKER so the
                # sentinel survives save->reload (pd.to_numeric would
                # otherwise silently coerce it to NaN, indistinguishable
                # from "untouched").
                raw = df[corr_col]
                out = np.full(width, np.nan, dtype=float)
                nums = pd.to_numeric(raw, errors="coerce").to_numpy(dtype=float)
                is_erased = raw.astype(str).str.upper() == ERASED_CELL_TEXT
                out[:] = nums
                out[is_erased.to_numpy()] = ERASED_MARKER
                rec.corrected[name] = out
            else:
                rec.corrected[name] = np.full(width, np.nan, dtype=float)
        wb.images[stem] = rec
    return wb


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

    The write is atomic: we serialize to a sibling `.tmp` file and then
    `os.replace()` it over the target so a crash mid-write cannot leave
    the user with a corrupted workbook.
    """
    p = Path(path)

    # Read the whole workbook into memory so we can rewrite it. Use a
    # context manager so the underlying file handle is released before
    # we open the path for writing (Windows would otherwise raise a
    # sharing violation).
    with pd.ExcelFile(p) as xls:
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
            # Build a list of cell values: erased -> "ERASED",
            # finite -> number, NaN -> empty.
            cells = []
            for v in arr.tolist():
                if v < ERASED_THRESHOLD:
                    cells.append(ERASED_CELL_TEXT)
                elif np.isnan(v):
                    cells.append(np.nan)
                else:
                    cells.append(float(v))
            df[corr_col] = cells
            any_corrected[name] = any(_is_set_cell(c) for c in cells)

        # Recompute thicknesses using effective boundary values
        # (auto where no correction, corrected otherwise).
        eff: dict[str, np.ndarray] = {}
        for name in AUTO_COLS:
            auto = df[name].to_numpy(dtype=float) if name in df.columns \
                else np.full(len(df), np.nan, dtype=float)
            corr_col = f"{name}_corrected"
            corr_raw = df[corr_col].tolist() if corr_col in df.columns else []
            out = auto.copy()
            for i, v in enumerate(corr_raw):
                if v == ERASED_CELL_TEXT:
                    out[i] = np.nan
                elif isinstance(v, (int, float, np.integer, np.floating)) \
                        and not (isinstance(v, float) and np.isnan(v)):
                    out[i] = float(v)
            eff[name] = out

        # total = (BM - TOP) * scale, outer = (BM - ONL) * scale,
        # det = (DET_b - DET_t) * scale
        df["total_thickness_um_corrected"] = \
            (eff["BM_y"] - eff["TOP_y"]) * scale_um_per_px_y
        df["outer_thickness_um_corrected"] = \
            (eff["BM_y"] - eff["ONL_y"]) * scale_um_per_px_y
        df["detachment_thickness_um_corrected"] = \
            (eff["DET_bottom_y"] - eff["DET_top_y"]) * scale_um_per_px_y

        # corrected_by_user flag for the row.
        any_per_col = np.zeros(len(df), dtype=bool)
        for name in AUTO_COLS:
            corr_col = f"{name}_corrected"
            if corr_col not in df.columns:
                continue
            for i, v in enumerate(df[corr_col].tolist()):
                if _is_set_cell(v):
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
    if summary_rows:
        if "corrected_summary" in sheets:
            old = sheets["corrected_summary"]
            new = pd.DataFrame(summary_rows)
            # Replace rows for files we just edited, keep others.
            edited_files = set(r["filename"] for r in summary_rows)
            if "filename" in old.columns:
                old = old[~old["filename"].isin(edited_files)]
            sheets["corrected_summary"] = pd.concat(
                [old, new], ignore_index=True
            )
        else:
            sheets["corrected_summary"] = pd.DataFrame(summary_rows)
    # If summary_rows is empty: leave any existing corrected_summary
    # untouched, and don't create a new (empty) one either.

    # Write all sheets to a temp sibling and atomically replace, so a
    # crash mid-write cannot corrupt the user's only workbook.
    tmp = p.with_suffix(p.suffix + ".tmp")
    with pd.ExcelWriter(tmp, engine="openpyxl", mode="w") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    os.replace(tmp, p)
