"""Run as `python -m src.hitl.main` from the project root.

Examples:
  # Default workbook + image dir:
  python -m src.hitl.main

  # Custom paths:
  python -m src.hitl.main --workbook D:/path/to/oct_results.xlsx \\
                          --image-dir D:/path/to/tiffs/
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="OCT HITL boundary editor")
    parser.add_argument(
        "--workbook", type=Path,
        default=Path("data/mouse_data_org/output/oct_results.xlsx"),
        help="Path to oct_results.xlsx (default: project default)",
    )
    parser.add_argument(
        "--image-dir", type=Path,
        default=Path("data/mouse_data_org"),
        help="Folder holding the source TIFFs",
    )
    args = parser.parse_args()

    if not args.workbook.exists():
        raise SystemExit(f"Workbook not found: {args.workbook}")
    if not args.image_dir.exists():
        raise SystemExit(f"Image dir not found: {args.image_dir}")
    run(args.workbook, args.image_dir)


if __name__ == "__main__":
    main()
