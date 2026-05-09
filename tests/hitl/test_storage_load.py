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
