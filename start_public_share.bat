@echo off
setlocal
cd /d "%~dp0"
python "%~dp0share_public.py" --copy
if errorlevel 1 pause
