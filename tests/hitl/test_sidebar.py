"""FileListView shows ✓ for images that already have corrections."""
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from src.hitl.sidebar import FileListView, FileEntry


def test_sidebar_marks_corrected_files(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="21_OS_4H", filename="21_OS_4H.tif", has_corrections=True),
        FileEntry(stem="21_OS_4H(1)", filename="21_OS_4H(1).tif", has_corrections=False),
    ])
    item0 = sb.item(0)
    item1 = sb.item(1)
    assert "✓" in item0.text()
    assert "✓" not in item1.text()


def test_sidebar_emits_signal_on_selection(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="a", filename="a.tif", has_corrections=False),
        FileEntry(stem="b", filename="b.tif", has_corrections=False),
    ])
    with qtbot.waitSignal(sb.image_selected, timeout=500) as blocker:
        sb.setCurrentRow(1)
    assert blocker.args == ["b"]


def test_sidebar_update_marks_after_save(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([
        FileEntry(stem="a", filename="a.tif", has_corrections=False),
    ])
    assert "✓" not in sb.item(0).text()
    sb.mark_corrected("a", True)
    assert "✓" in sb.item(0).text()


def test_sidebar_set_entries_does_not_emit_signal(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    received = []
    sb.image_selected.connect(received.append)
    sb.set_entries([
        FileEntry(stem="a", filename="a.tif", has_corrections=False),
        FileEntry(stem="b", filename="b.tif", has_corrections=False),
    ])
    # Population should not fire the selection signal.
    assert received == []
    # But subsequent setCurrentRow does fire.
    with qtbot.waitSignal(sb.image_selected, timeout=500) as blocker:
        sb.setCurrentRow(0)
    assert blocker.args == ["a"]


def test_sidebar_mark_corrected_round_trip(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([FileEntry(stem="a", filename="a.tif", has_corrections=False)])
    sb.mark_corrected("a", True)
    assert "✓" in sb.item(0).text()
    sb.mark_corrected("a", False)
    assert "✓" not in sb.item(0).text()
    assert "a.tif" in sb.item(0).text()


def test_sidebar_mark_corrected_unknown_stem_raises(qtbot):
    sb = FileListView()
    qtbot.addWidget(sb)
    sb.set_entries([FileEntry(stem="a", filename="a.tif", has_corrections=False)])
    with pytest.raises(KeyError):
        sb.mark_corrected("does-not-exist", True)
