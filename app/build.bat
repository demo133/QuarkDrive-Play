@echo off
rem ============================================================
rem  QuarkPlay one-click build script
rem  Output: dist\QuarkPlay.exe  (single file, no console window)
rem  Requirement: Python 3.10+ with tkinter + pyinstaller + pillow
rem ============================================================
setlocal
cd /d "%~dp0"

rem Prefer a Python that has tkinter; adjust if needed.
set "PY=python"
where py >nul 2>nul && set "PY=py"

echo [1/3] generating icon ...
"%PY%" make_icon.py || goto :err

echo [2/3] running PyInstaller ...
"%PY%" -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name QuarkPlay --icon icon.ico ^
  --add-data "icon.ico;." ^
  app.py || goto :err

echo [3/3] done.
echo Output: %~dp0dist\QuarkPlay.exe
echo.
echo You can now double-click dist\QuarkPlay.exe
pause
exit /b 0

:err
echo.
echo BUILD FAILED - see messages above.
pause
exit /b 1
