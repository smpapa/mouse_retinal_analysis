"""HitlDb — SQLite-backed canonical store + xlsx import/export."""
from __future__ import annotations

import shutil
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.hitl.boundary_model import BOUNDARY_NAMES, ERASED_MARKER
from src.hitl.db import HitlDb
from src.hitl.storage import CorrectedSnapshot


@pytest.fixture
def fresh_db(tmp_path):
    db = HitlDb(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def db_imported(tmp_path, oct_results_xlsx):
    """A DB populated from the project's batch-produced xlsx."""
    src = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, src)
    db = HitlDb(tmp_path / "db" / "oct_results.db")
    n = db.import_from_xlsx(src)
    assert n > 0
    yield db, src
    db.close()


def test_db_init_creates_schema(fresh_db):
    cur = fresh_db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cur.fetchall()}
    assert {"images", "meta", "per_column"}.issubset(tables)
    assert fresh_db.is_empty()


def test_import_populates_images_and_per_column(db_imported, sample_image_stem):
    db, _src = db_imported
    images = db.list_images()
    assert any(stem == sample_image_stem for stem, _, _ in images)
    rec = db.load_image(sample_image_stem)
    assert rec is not None
    assert rec.width > 0
    for name in BOUNDARY_NAMES:
        assert rec.auto[name].shape == (rec.width,)
        assert rec.corrected[name].shape == (rec.width,)


def test_save_corrections_round_trip(db_imported, sample_image_stem):
    db, _src = db_imported
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["TOP_y"][10] = 88.5
    corrected["BM_y"][20] = ERASED_MARKER
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)

    rec2 = db.load_image(sample_image_stem)
    assert rec2.corrected["TOP_y"][10] == pytest.approx(88.5)
    # ERASED sentinel must come back below threshold (it's a finite -1e9).
    assert rec2.corrected["BM_y"][20] < -1.0e8
    # Untouched columns stay NaN.
    assert np.isnan(rec2.corrected["TOP_y"][0])


def test_list_images_marks_corrections(db_imported, sample_image_stem):
    db, _src = db_imported
    # Initially, even imported corrected columns may show as has_corr=True
    # if the source xlsx already had them. Save explicitly to force True.
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["TOP_y"][0] = 99.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)
    found = [(s, has) for s, _, has in db.list_images() if s == sample_image_stem]
    assert found and found[0][1] is True


def test_export_to_xlsx_writes_corrected_columns(db_imported,
                                                  sample_image_stem,
                                                  tmp_path):
    db, _src = db_imported
    # First inject a correction so export has something to write.
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["TOP_y"][0] = 77.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)

    out = tmp_path / "exported.xlsx"
    db.export_to_xlsx(out)
    assert out.exists()

    df = pd.read_excel(out, sheet_name=sample_image_stem)
    assert "TOP_y_corrected" in df.columns
    assert df["TOP_y_corrected"].iloc[0] == pytest.approx(77.0)


def test_reimport_preserves_corrected_in_db(db_imported, sample_image_stem):
    """Re-importing the same xlsx should NOT clobber DB corrections."""
    db, src = db_imported
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["TOP_y"][5] = 123.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)

    # Re-import (e.g. after batch_process re-runs).
    db.import_from_xlsx(src, preserve_corrected_in_db=True)

    rec2 = db.load_image(sample_image_stem)
    assert rec2.corrected["TOP_y"][5] == pytest.approx(123.0)


def test_has_corrections_flag(db_imported, sample_image_stem):
    db, _src = db_imported
    # Whether or not the imported xlsx already had corrections, after
    # adding one we definitely expect has_corrections=True.
    rec = db.load_image(sample_image_stem)
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in BOUNDARY_NAMES}
    corrected["ONL_y"][0] = 111.0
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 10, 9, 0, 0),
    )
    db.save_corrections(snap)
    assert db.has_corrections() is True
