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
                rec.corrected[name] = pd.to_numeric(
                    df[corr_col], errors="coerce"
                ).to_numpy(dtype=float)
            else:
                rec.corrected[name] = np.full(width, np.nan, dtype=float)
        wb.images[stem] = rec
    return wb
