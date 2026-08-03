@echo off
setlocal
chcp 65001 >nul
title Tajik HTR Studio

set "WORKSPACE_ROOT=%~dp0"
set "ACTION=%~1"
if not defined ACTION set "ACTION=start"

if /I "%ACTION%"=="start" goto start_stack
if /I "%ACTION%"=="status" goto status_stack
if /I "%ACTION%"=="stop" goto stop_stack

echo Usage:
echo   start.bat          Start frontend, API and ML worker
echo   start.bat status   Check the local stack
echo   start.bat stop     Stop the local stack
exit /b 2

:start_stack
echo.
echo ==================================================
echo   Tajik HTR Studio - local development launcher
echo ==================================================
echo Starting API, persistent ML worker, and frontend...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-local.ps1" -ReadinessTimeoutSeconds 60
if errorlevel 1 goto failed

echo.
echo [OPEN] http://127.0.0.1:5173
echo [TIP]  Run "start.bat status" to inspect API, CUDA and worker status.
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
echo.
echo Failed to start Tajik HTR Studio.
echo Check:
echo   api_server\data\.runtime\api.stderr.log
echo   api_server\data\.runtime\worker.stderr.log
echo.
pause
exit /b 1
