@echo off
setlocal
cd /d "%~dp0"
python "%~dp0setup_named_tunnel.py"
if errorlevel 1 pause
