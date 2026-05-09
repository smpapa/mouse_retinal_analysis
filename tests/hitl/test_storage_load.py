"""storage.load_workbook() reads the batch xlsx into a typed dict."""
import numpy as np
import pandas as pd

from src.hitl.storage import load_workbook, ImageRecord


def test_load_workbook_returns_one_record_per_image(loaded_workbook, sample_image_stem):
    wb = loaded_workbook
    assert len(wb.images) >= 1
    assert sample_image_stem in wb.images
    rec = wb.images[sample_image_stem]
    assert isinstance(rec, ImageRecord)
    assert rec.filename.endswith(".tif")
    assert rec.width > 0
    for name in ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
        arr = rec.auto[name]
        assert arr.shape == (rec.width,)


def test_load_workbook_loads_corrected_columns_when_present(loaded_workbook):
    wb = loaded_workbook
    for rec in wb.images.values():
        for name in ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
            assert name in rec.corrected
            arr = rec.corrected[name]
            assert arr.shape == (rec.width,)


def test_load_workbook_preserves_ERASED_sentinel(tmp_path, oct_results_xlsx,
                                                  sample_image_stem):
    """Round-trip: save ERASED cells, reload, verify they come back as ERASED_MARKER."""
    import shutil
    from datetime import datetime
    from src.hitl.storage import (load_workbook, save_corrections,
                                  CorrectedSnapshot, AUTO_COLS, ERASED_MARKER)
    from src.hitl.boundary_model import ERASED_THRESHOLD
    import numpy as np

    dst = tmp_path / "oct_results.xlsx"
    shutil.copy(oct_results_xlsx, dst)
    wb = load_workbook(dst)
    rec = wb.images[sample_image_stem]
    width = rec.width
    corrected = {k: np.full(width, np.nan, dtype=float) for k in AUTO_COLS}
    # Erase TOP_y at columns 5..7 inclusive.
    corrected["TOP_y"][5] = ERASED_MARKER
    corrected["TOP_y"][6] = ERASED_MARKER
    corrected["TOP_y"][7] = ERASED_MARKER
    snap = CorrectedSnapshot(
        stem=sample_image_stem,
        corrected=corrected,
        timestamp=datetime(2026, 5, 9, 12, 0, 0),
    )
    save_corrections(dst, [snap], scale_um_per_px_y=3.87)
    # Reload and verify the sentinel survived.
    wb2 = load_workbook(dst)
    rec2 = wb2.images[sample_image_stem]
    reloaded = rec2.corrected["TOP_y"]
    for i in (5, 6, 7):
        assert reloaded[i] < ERASED_THRESHOLD, \
            f"Column {i} should be ERASED after round-trip; got {reloaded[i]}"
    # Untouched columns stay NaN.
    assert np.isnan(reloaded[0])


def test_load_workbook_missing_auto_columns_fall_back_to_nan(tmp_path):
    p = tmp_path / "tiny.xlsx"
    summary = pd.DataFrame({"filename": ["dummy.tif"]})
    detail = pd.DataFrame({
        "x_local": [0, 1, 2],
        "TOP_y": [10.0, 11.0, 12.0],
        # ONL_y, BM_y, DET_top_y, DET_bottom_y intentionally missing
    })
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="summary", index=False)
        detail.to_excel(w, sheet_name="dummy", index=False)
    wb = load_workbook(p)
    assert "dummy" in wb.images
    rec = wb.images["dummy"]
    assert rec.width == 3
    assert np.allclose(rec.auto["TOP_y"], [10.0, 11.0, 12.0])
    for missing in ("ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
        assert np.isnan(rec.auto[missing]).all()
        assert rec.auto[missing].shape == (3,)
