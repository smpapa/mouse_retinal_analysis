"""BoundaryToggleBar emits visibility changes per checkbox toggle."""
import pytest

pytest.importorskip("pytestqt")

from src.hitl.boundary_toggle import BoundaryToggleBar


def test_initial_state_all_checked(qtbot):
    bar = BoundaryToggleBar()
    qtbot.addWidget(bar)
    for name in ("TOP_y", "ONL_y", "BM_y", "DET_top_y", "DET_bottom_y"):
        assert bar.is_visible(name) is True


def test_user_toggle_emits_signal(qtbot):
    bar = BoundaryToggleBar()
    qtbot.addWidget(bar)
    received = []
    bar.visibility_changed.connect(lambda n, v: received.append((n, v)))
    # Programmatically click the TOP checkbox by accessing the private box dict
    # (acceptable for test introspection).
    bar._boxes["TOP_y"].setChecked(False)
    assert received == [("TOP_y", False)]


def test_set_visible_does_not_emit_signal(qtbot):
    bar = BoundaryToggleBar()
    qtbot.addWidget(bar)
    received = []
    bar.visibility_changed.connect(lambda n, v: received.append((n, v)))
    bar.set_visible("TOP_y", False)
    assert received == []
    assert bar.is_visible("TOP_y") is False


def test_unknown_boundary_set_visible_is_noop(qtbot):
    bar = BoundaryToggleBar()
    qtbot.addWidget(bar)
    bar.set_visible("not_a_boundary", False)  # no exception
    assert bar.is_visible("TOP_y") is True
