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


def test_undo_on_empty_stack_is_noop(editor):
    # No edits made, undo should not raise.
    editor.undo()
    assert np.allclose(editor.effective("TOP_y"), editor.auto["TOP_y"])


def test_apply_drag_when_current_value_is_nan(editor):
    # Set ONL to NaN at x=10 first via erase, then drag — should set the col directly.
    editor.apply_erase("ONL_y", 10, 10)
    editor.apply_drag("ONL_y", 10, 99.0, sigma=5)
    eff = editor.effective("ONL_y")
    assert eff[10] == pytest.approx(99.0)


def test_apply_drag_at_left_edge(editor):
    editor.apply_drag("BM_y", 0, 200.0, sigma=5)
    eff = editor.effective("BM_y")
    assert eff[0] == pytest.approx(200.0)


def test_apply_drag_at_right_edge(editor):
    editor.apply_drag("BM_y", editor.width - 1, 200.0, sigma=5)
    eff = editor.effective("BM_y")
    assert eff[editor.width - 1] == pytest.approx(200.0)


def test_multiple_edits_stack_then_undo_one(editor):
    editor.apply_drag("TOP_y", 30, 45.0, sigma=5, single=True)
    editor.apply_drag("TOP_y", 60, 55.0, sigma=5, single=True)
    eff_before = editor.effective("TOP_y").copy()
    editor.apply_drag("TOP_y", 80, 50.0, sigma=5, single=True)
    editor.undo()
    assert np.allclose(editor.effective("TOP_y"), eff_before)


def test_erase_persists_after_drag_on_different_column(editor):
    editor.apply_erase("BM_y", 50, 60)
    editor.apply_drag("BM_y", 10, 95.0, sigma=5, single=True)
    eff = editor.effective("BM_y")
    assert eff[10] == pytest.approx(95.0)
    assert np.all(np.isnan(eff[50:61]))


def test_apply_drag_session_does_not_compound(editor):
    # Simulating an interactive drag: same anchor, multiple update calls.
    editor.begin_drag("TOP_y", 50, sigma=5)
    editor.update_drag(45.0)
    after_first = editor.effective("TOP_y").copy()
    # Second update with the same y should produce the same result
    # (NOT compounded on top of the first).
    editor.update_drag(45.0)
    after_second = editor.effective("TOP_y").copy()
    editor.end_drag()
    assert np.allclose(after_first, after_second)


def test_apply_drag_session_pushes_only_one_undo(editor):
    editor.begin_drag("TOP_y", 50, sigma=5)
    editor.update_drag(45.0)
    editor.update_drag(46.0)
    editor.update_drag(47.0)
    editor.end_drag()
    editor.undo()
    assert np.allclose(editor.effective("TOP_y"), editor.auto["TOP_y"])


def test_unknown_boundary_raises(editor):
    with pytest.raises(KeyError):
        editor.apply_drag("NOT_A_BOUNDARY", 10, 50.0)


def test_mark_clean_resets_dirty(editor):
    editor.apply_drag("TOP_y", 50, 40.0)
    assert editor.dirty
    editor.mark_clean()
    assert not editor.dirty
    editor.apply_drag("TOP_y", 51, 41.0)
    assert editor.dirty
