@echo off
setlocal
cd /d "%~dp0"
python "%~dp0run_fixed_public.py"
if errorlevel 1 pause
