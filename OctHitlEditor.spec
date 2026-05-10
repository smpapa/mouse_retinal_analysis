# PyInstaller spec for the OCT HITL Editor.
#
# Build:   .venv\Scripts\pyinstaller.exe OctHitlEditor.spec --clean --noconfirm
# Output:  dist/OctHitlEditor/OctHitlEditor.exe   (onedir; ship the whole folder)
#
# The exe is self-contained — no Python install needed on the target PC.
# Data folders are picked at runtime via "File > Open Data Folder...".

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
SRC = Path("src").resolve()

# `src/hitl/app.py` adds `src/` to sys.path at import time so that
# `from io_utils import ...` etc. resolve. PyInstaller's static analyser
# does not see those imports, so we list them explicitly.
hidden_imports = [
    # Analyzer pipeline (non-package imports inside src/).
    "io_utils",
    "oct_analyzer",
    "viz",
    "gt_guided",
    "batch_process",
    # HITL package modules (auto-discovered from main.py, listed for
    # belt-and-suspenders coverage).
    "src.hitl.app",
    "src.hitl.canvas",
    "src.hitl.sidebar",
    "src.hitl.boundary_model",
    "src.hitl.boundary_toggle",
    "src.hitl.storage",
    "src.hitl.overlay_render",
    "src.hitl.batch_runner",
    "src.hitl.db",
    "src.hitl.export_annotations",
]

# Skip large optional dependencies that the HITL editor never imports.
excludes = [
    "matplotlib",       # only used by analyze_single CLI, not by HITL
    "tkinter",          # not used; PySide6 owns the GUI
    "IPython",
    "jupyter",
]

a = Analysis(
    ["src/hitl/main.py"],
    pathex=[str(SRC), str(SRC / "hitl")],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="OctHitlEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                # GUI app; no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OctHitlEditor",
)
