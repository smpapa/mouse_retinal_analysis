"""Shared test fixtures for HITL tests."""
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "mouse_data_org"
OUTPUT_DIR = DATA_DIR / "output"


@pytest.fixture
def oct_results_xlsx() -> Path:
    """Path to the batch-produced workbook used as test fixture."""
    p = OUTPUT_DIR / "oct_results.xlsx"
    if not p.exists():
        pytest.skip(f"{p} not present — run batch_process.py first")
    return p


@pytest.fixture
def sample_image_path() -> Path:
    p = DATA_DIR / "21_OS_4H.tif"
    if not p.exists():
        pytest.skip(f"{p} not present")
    return p


@pytest.fixture
def sample_image_stem() -> str:
    return "21_OS_4H"
