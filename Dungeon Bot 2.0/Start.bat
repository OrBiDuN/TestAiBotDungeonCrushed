@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup first. See README.md.
  pause
  exit /b 1
)
start "Dungeon Bot 2.0" ".venv\Scripts\pythonw.exe" "launcher.py"
