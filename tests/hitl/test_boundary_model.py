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
