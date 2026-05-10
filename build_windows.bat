@echo off
REM Build the standalone OCT HITL Editor for Windows (no Python required on
REM target PC). Run from the project root with .venv set up.
REM
REM Output:  dist\OctHitlEditor\OctHitlEditor.exe + bundled DLLs (onedir).
REM Distribute:  zip the entire dist\OctHitlEditor folder.

setlocal

if not exist .venv\Scripts\python.exe (
    echo [ERROR] .venv not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

echo [1/3] Installing PyInstaller into .venv (idempotent)...
.venv\Scripts\pip.exe install pyinstaller>=6.0 || exit /b 1

echo [2/3] Cleaning previous build...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo [3/3] Building OctHitlEditor.exe (this takes 1-3 minutes)...
.venv\Scripts\pyinstaller.exe OctHitlEditor.spec --clean --noconfirm || exit /b 1

echo.
echo [DONE] Output: dist\OctHitlEditor\OctHitlEditor.exe
echo Distribute:   zip the entire dist\OctHitlEditor folder.

endlocal
