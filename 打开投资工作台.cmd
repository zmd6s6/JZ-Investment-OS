@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
uv run python scripts/open_local_ui.py %*
if errorlevel 1 pause
