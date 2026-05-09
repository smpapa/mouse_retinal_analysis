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
            rec.auto[name] = (
                df[name].to_numpy(dtype=float)
                if name in df.columns
                else np.full(width, np.nan, dtype=float)
            )
            corr_col = f"{name}_corrected"
            if corr_col in df.columns:
                rec.corrected[name] = df[corr_col].to_numpy(dtype=float)
            else:
                rec.corrected[name] = np.full(width, np.nan, dtype=float)
        wb.images[sheet] = rec
    return wb
