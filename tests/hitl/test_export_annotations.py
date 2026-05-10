"""Export HITL corrections as CSV + annotation TIFF."""
from __future__ import annotations

import shutil
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from src.hitl.boundary_model import BOUNDARY_NAMES, ERASED_MARKER
from src.hitl.db import HitlDb
from src.hitl.export_annotations import (
    _compute_effective,
    export_annotations,
)
from src.hitl.storage import CorrectedSnapshot


@pytest.fixture
def db_with_one_correction(tmp_path, oct_results_xlsx, sample_image_stem):
    src = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, src)
    db = HitlDb(tmp_path / "db" / "oct_results.db")
    db.import_from_xlsx(src)
    # Force ONE image to have an explicit correction so list_images()
    # reports has_corrections=True for exactly that one stem.
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["TOP_y"][0] = 88.0
    corrected["BM_y"][1] = ERASED_MARKER
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)
    yield db, src
    db.close()


def test_compute_effective_overrides_auto_with_corrected():
    auto = {n: np.array([10.0, 20.0, 30.0]) for n in BOUNDARY_NAMES}
    corrected = {n: np.full(3, np.nan, dtype=float) for n in BOUNDARY_NAMES}
    corrected["TOP_y"][1] = 99.0
    corrected["BM_y"][2] = ERASED_MARKER  # erase
    eff = _compute_effective(auto, corrected)
    # Override
    assert eff["TOP_y"][1] == pytest.approx(99.0)
    # Auto preserved where corrected is NaN
    assert eff["TOP_y"][0] == pytest.approx(10.0)
    # Erased -> NaN
    assert np.isnan(eff["BM_y"][2])
    # Untouched in BM
    assert eff["BM_y"][0] == pytest.approx(10.0)


def test_export_annotations_writes_csv_and_tiff(db_with_one_correction,
                                                 sample_image_stem,
                                                 tmp_path):
    db, _src = db_with_one_correction
    image_dir = (tmp_path.parent
                  if False else _src.parent.parent)  # not used in this test
    # Use the project's data dir for source TIFFs.
    from pathlib import Path as _P
    project_data = _P(__file__).resolve().parents[2] / "data" / "mouse_data_org"
    if not (project_data / f"{sample_image_stem}.tif").exists():
        pytest.skip("Source TIFF not available")

    out_dir = tmp_path / "annotations"
    result = export_annotations(
        db, project_data, out_dir,
        only_corrected=True,
    )
    # Only the corrected image is exported.
    assert result["csv_count"] >= 1
    assert result["tiff_count"] >= 1
    # CSV
    csv_path = out_dir / "csv" / f"{sample_image_stem}.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert set(df.columns) >= {
        "x_local", "TOP_y", "ONL_y", "BM_y",
        "DET_top_y", "DET_bottom_y",
        "total_um", "outer_um", "det_um",
    }
    # TOP_y at column 0 should be the override value 88.0
    assert df.loc[df["x_local"] == 0, "TOP_y"].iloc[0] == pytest.approx(88.0)
    # BM_y at column 1 is erased -> NaN
    assert np.isnan(df.loc[df["x_local"] == 1, "BM_y"].iloc[0])
    # TIFF
    tiff_path = out_dir / "tiff" / f"{sample_image_stem}_annotation_hitl.tiff"
    assert tiff_path.exists()
    arr = np.array(Image.open(tiff_path))
    # Sanity: a TOP red pixel should appear (HITL palette: TOP_y = (255,64,64)).
    from src.hitl.colors import BOUNDARY_COLORS
    r, g, b = BOUNDARY_COLORS["TOP_y"]
    is_top = ((arr[..., 0] == r) & (arr[..., 1] == g) & (arr[..., 2] == b))
    assert is_top.any()


def test_export_annotations_only_corrected_skips_untouched(
        db_with_one_correction, sample_image_stem, tmp_path):
    db, _src = db_with_one_correction
    n_with_corr = sum(1 for _, _, has in db.list_images() if has)
    out_dir = tmp_path / "annotations"
    project_data = (_src.parent.parent
                     if False
                     else __import__("pathlib").Path(__file__).resolve()
                          .parents[2] / "data" / "mouse_data_org")
    result = export_annotations(
        db, project_data, out_dir,
        formats={"csv"},  # csv only — doesn't depend on TIFFs
        only_corrected=True,
    )
    assert result["csv_count"] == n_with_corr


def test_export_annotations_progress_callback(db_with_one_correction,
                                                tmp_path):
    db, _src = db_with_one_correction
    project_data = (__import__("pathlib").Path(__file__)
                     .resolve().parents[2] / "data" / "mouse_data_org")
    calls: list[tuple] = []
    out_dir = tmp_path / "annotations"
    export_annotations(
        db, project_data, out_dir,
        formats={"csv"},
        only_corrected=True,
        progress_callback=lambda i, n, name: calls.append((i, n, name)),
    )
    assert calls, "progress_callback should fire at least once"
    assert calls[0][0] == 1
    assert calls[-1][0] == calls[-1][1]  # last i == n
