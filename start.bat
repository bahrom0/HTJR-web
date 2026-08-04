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
if /I "%ACTION%"=="build" goto build_web

echo Usage:
echo   start.bat          Start production web, API and ML worker
echo   start.bat build    Build the production web client
echo   start.bat status   Check the production stack
echo   start.bat stop     Stop the production stack
echo   start-dev.bat      Start the Vite development stack
exit /b 2

:start_stack
echo.
echo ==================================================
echo   Tajik HTR Studio - production launcher
echo ==================================================
echo Starting production web, API, and persistent ML worker...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-production.ps1" -Action Start -ReadinessTimeoutSeconds 60
if errorlevel 1 goto failed

echo.
echo [OPEN] http://127.0.0.1:8000
echo [TIP]  Run "start.bat status" to inspect API, CUDA, VRAM, and worker status.
start "" "http://127.0.0.1:8000"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\wait-for-ctrl-h.ps1"
exit /b 0

:status_stack
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-production.ps1" -Action Status
exit /b %ERRORLEVEL%

:stop_stack
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-production.ps1" -Action Stop
exit /b %ERRORLEVEL%

:build_web
pushd "%WORKSPACE_ROOT%web_app"
call npm.cmd run build
set "BUILD_EXIT=%ERRORLEVEL%"
popd
exit /b %BUILD_EXIT%

:failed
echo.
echo Failed to start Tajik HTR Studio production mode.
echo Check:
echo   api_server\data\.runtime\api.stderr.log
echo   api_server\data\.runtime\worker.stderr.log
echo.
pause
exit /b 1
