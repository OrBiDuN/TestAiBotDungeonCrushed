@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); $opts = @{ FilePath = 'powershell.exe'; ArgumentList = '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0Rebuild-Restart.ps1""'; WorkingDirectory = '%~dp0'; WindowStyle = 'Hidden'; ErrorAction = 'Stop' }; if (-not $admin) { $opts.Verb = 'RunAs' }; try { Start-Process @opts } catch { Write-Error $_; exit 1 }"
exit /b %errorlevel%
