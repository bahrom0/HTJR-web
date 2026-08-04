@echo off
setlocal
chcp 65001 >nul
title Tajik HTR Studio - development

set "WORKSPACE_ROOT=%~dp0"
set "ACTION=%~1"
if not defined ACTION set "ACTION=start"

if /I "%ACTION%"=="start" goto start_stack
if /I "%ACTION%"=="status" goto status_stack
if /I "%ACTION%"=="stop" goto stop_stack

echo Usage:
echo   start-dev.bat          Start Vite, API and persistent ML worker
echo   start-dev.bat status   Check the development stack
echo   start-dev.bat stop     Stop the development stack
exit /b 2

:start_stack
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-local.ps1" -ReadinessTimeoutSeconds 60
if errorlevel 1 goto failed
start "" "http://127.0.0.1:5173"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\wait-for-ctrl-h.ps1"
exit /b 0

:status_stack
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\status-local.ps1"
exit /b %ERRORLEVEL%

:stop_stack
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\stop-local.ps1"
exit /b %ERRORLEVEL%

:failed
echo Development stack failed. Check api_server\data\.runtime\ and web_app\output\.runtime\ logs.
pause
exit /b 1
