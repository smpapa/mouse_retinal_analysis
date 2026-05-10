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

# Two import paths:
# - Normal CLI (`python -m src.hitl.main`): main.py runs as a package
#   member, so the relative import works.
# - PyInstaller standalone exe: main.py is loaded as `__main__` with no
#   package context, so the relative import raises ImportError. Fall
#   back to the absolute path that OctHitlEditor.spec puts on sys.path.
try:
    from .app import run
except ImportError:
    from src.hitl.app import run  # type: ignore[no-redef]


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

    # Both paths are allowed to be missing — the editor opens with an
    # empty sidebar and the user picks a folder via File > Open Data
    # Folder. We just print a notice so the user knows what happened.
    if not args.workbook.exists():
        print(f"Notice: workbook not found at {args.workbook}; "
              "use File > Open Data Folder to load one.")
    if not args.image_dir.exists():
        print(f"Notice: image dir not found at {args.image_dir}; "
              "use File > Open Data Folder to load one.")
    run(args.workbook, args.image_dir)


if __name__ == "__main__":
    main()
