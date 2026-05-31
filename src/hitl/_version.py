"""Single source of truth for the editor version string.

Used by:
  - MainWindow window title (so end users can confirm their build)
  - The PyInstaller build script when naming the distribution zip
"""
from __future__ import annotations

__version__ = "2026.05.11"
