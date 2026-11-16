@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto environment_ready
where py >nul 2>&1
if errorlevel 1 goto need_python
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:environment_ready
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --distpath . --workpath build DungeonBot.spec
if errorlevel 1 goto failed
echo.
echo Build complete: %CD%\DungeonBot.exe
echo Keep .env.telegram next to the EXE for Telegram access.
if /I "%~1"=="--no-pause" exit /b 0
pause
exit /b 0
:need_python
echo Install Python 3.12 x64 with the Python Launcher, then run this file again.
goto failed
:failed
echo Build failed. Check the messages above. Close DungeonBot.exe before rebuilding.
if /I "%~1"=="--no-pause" exit /b 1
pause
exit /b 1
