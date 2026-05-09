"""Human-in-the-loop boundary editor for OCT analysis.

Modules:
  - storage:        reads/writes oct_results.xlsx (auto + *_corrected cols)
  - boundary_model: per-image boundary state with undo/redo
  - overlay_render: renders corrected overlay PNGs
  - canvas:         PySide6 edit surface (drag points, erase regions)
  - sidebar:        QListWidget showing files + ✓ corrected marker
  - app:            QMainWindow that assembles canvas + sidebar
  - main:           entry point (`python -m src.hitl.main`)
"""
