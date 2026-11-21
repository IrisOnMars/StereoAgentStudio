@echo off
setlocal
cd /d "%~dp0"
py -3.11 scripts\setup_windows.py %*
if errorlevel 1 (
  echo See docs\INSTALL_WINDOWS.md for setup instructions.
  pause
  exit /b 1
)
if "%~1"=="" pause
