@echo off
set TASK_NAME=GlobalNewsAgentDaily
set SCRIPT=%~dp0run_daily.bat
schtasks /create /tn "%TASK_NAME%" /tr "\"%SCRIPT%\"" /sc daily /st 08:00 /f
echo Task created: %TASK_NAME%
