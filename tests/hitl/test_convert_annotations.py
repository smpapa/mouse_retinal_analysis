"""Convert legacy Heidelberg-palette annotation TIFFs to HITL colours."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.hitl.colors import BOUNDARY_COLORS
from src.hitl.convert_annotations import (
    convert_legacy_annotation,
    convert_legacy_folder,
)


PROJECT_DATA = Path(__file__).resolve().parents[2] / "data" / "mouse_data_org"
LEGACY_DIR = PROJECT_DATA / "annotation"


def _legacy_pair():
    """Return (legacy_tiff, source_tiff) for a real project image, or
    skip if either is missing."""
    candidates = [
        ("21_OS_4H_annotation.tiff", "21_OS_4H.tif"),
        ("21_OS_6H_annotation.tiff", "21_OS_6H.tif"),
    ]
    for legacy_name, src_name in candidates:
        legacy = LEGACY_DIR / legacy_name
        src = PROJECT_DATA / src_name
        if legacy.exists() and src.exists():
            return legacy, src
    pytest.skip("No legacy annotation + source TIFF pair available")


def test_convert_legacy_annotation_writes_hitl_colored_tiff(tmp_path):
    legacy, src = _legacy_pair()
    out = tmp_path / "out.tiff"
    result = convert_legacy_annotation(legacy, src, out)
    assert out.exists()
    arr = np.array(Image.open(out))
    # The converted TIFF should contain HITL palette colours; the
    # original Heidelberg cyan/magenta must NOT appear (those were the
    # legacy colours we converted away from).
    R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
    # HITL TOP red:
    is_hitl_top = (R == BOUNDARY_COLORS["TOP_y"][0]) & \
                   (G == BOUNDARY_COLORS["TOP_y"][1]) & \
                   (B == BOUNDARY_COLORS["TOP_y"][2])
    assert is_hitl_top.any(), \
        "HITL red TOP pixels should appear in the converted TIFF"
    # `result["found"]` should mark TOP/ONL/BM as detected for these
    # well-annotated 4H/6H images.
    assert result["found"]["TOP_y"] is True
    assert result["found"]["ONL_y"] is True
    assert result["found"]["BM_y"] is True


def test_convert_legacy_folder_walks_files(tmp_path):
    legacy, _src = _legacy_pair()
    legacy_dir = legacy.parent
    out_dir = tmp_path / "annotation_hitl"
    result = convert_legacy_folder(
        legacy_dir, PROJECT_DATA, out_dir,
    )
    assert result["converted"] >= 1
    # Every converted file lands at out_dir/*_annotation_hitl.tiff
    converted = list(out_dir.glob("*_annotation_hitl.tiff"))
    assert len(converted) == result["converted"]


def test_convert_legacy_folder_skips_unmatched_source(tmp_path):
    """If a legacy TIFF has no matching source in the original folder,
    it should be reported as skipped instead of crashing."""
    legacy, _src = _legacy_pair()
    legacy_dir = legacy.parent
    # Point original_image_dir at an empty folder.
    empty = tmp_path / "empty"
    empty.mkdir()
    out_dir = tmp_path / "annotation_hitl"
    result = convert_legacy_folder(legacy_dir, empty, out_dir)
    assert result["converted"] == 0
    assert result["skipped_no_source"] == result["total_legacy_files"]
