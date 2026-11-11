@echo off
rem Double-click to start AnKar Video Editor. Keep this window open while editing; close it to stop.
rem It runs only on this PC (http://localhost:8765) - nothing is shared on the internet.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title AnKar Video Editor (close this window to stop)
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONPATH="
set "PYTHONHOME="
set "PY=%~dp0runtime\python.exe"
if exist "%PY%" goto :run
rem developer setup: a .venv made from requirements.txt
set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto :run
echo AnKar Video Editor is not set up yet. Double-click "Setup AnKar Video Editor.bat" first.
pause
exit /b 1
:run
echo AnKar Video Editor is starting at http://localhost:8765 ...
"%PY%" -m app.server
echo.
echo AnKar Video Editor stopped.
pause
