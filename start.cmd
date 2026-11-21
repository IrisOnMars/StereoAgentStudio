@echo off
setlocal
cd /d "%~dp0"
set ELECTRON_RUN_AS_NODE=
if not exist "%~dp0node_modules\electron\dist\electron.exe" goto setup
if not exist "%~dp0config.json" goto setup
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
exit /b
:setup
echo Run setup.cmd first. See docs\INSTALL_WINDOWS.md.
pause
