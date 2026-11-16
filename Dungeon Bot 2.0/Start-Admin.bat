@echo off
setlocal
cd /d "%~dp0"
set "DUNGEON_START_DIR=%CD%"
powershell.exe -NoProfile -Command "Start-Process -FilePath (Join-Path $env:DUNGEON_START_DIR 'DungeonBot.exe') -WorkingDirectory $env:DUNGEON_START_DIR -Verb RunAs -WindowStyle Normal"
if errorlevel 1 (
  echo Administrator launch was cancelled or failed.
  pause
  exit /b 1
)
