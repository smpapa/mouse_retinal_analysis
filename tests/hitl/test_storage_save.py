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
