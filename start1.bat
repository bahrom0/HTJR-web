@echo off
setlocal
chcp 65001 >nul
title Tajik HTR Studio (Lite)

set "WORKSPACE_ROOT=%~dp0"
set "ACTION=%~1"
if not defined ACTION set "ACTION=start"

set "HTR_OCR_PROVIDER=gemini"
set "HTR_GEMINI_MODE=page"
set "HTR_CRAFT_ENABLED=false"
set "HTR_CUDA=false"
set "HTR_ML_DEVICE=cpu"

if /I "%ACTION%"=="start" goto start_stack
if /I "%ACTION%"=="dev" goto start_dev
if /I "%ACTION%"=="status" goto status_stack
if /I "%ACTION%"=="stop" goto stop_stack
if /I "%ACTION%"=="build" goto build_web

echo Usage:
echo   start1.bat          Start lightweight production stack (Cloud Gemini, no TrOCR/CRAFT/CUDA)
echo   start1.bat dev      Start lightweight Vite dev stack
echo   start1.bat status   Check stack status
echo   start1.bat stop     Stop stack
echo   start1.bat build    Build the production web client
exit /b 2

:start_stack
echo.
echo ==================================================
echo   Tajik HTR Studio (Lite: Cloud Gemini, no TrOCR)
echo ==================================================
echo Starting lightweight web, API, and worker...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-production.ps1" -Action Start -ReadinessTimeoutSeconds 60
if errorlevel 1 goto failed

echo.
echo [OPEN] http://127.0.0.1:8000
echo [TIP]  Run "start1.bat status" to inspect status.
start "" "http://127.0.0.1:8000"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\wait-for-ctrl-h.ps1"
exit /b 0

:start_dev
echo.
echo ==================================================
echo   Tajik HTR Studio (Lite Dev: Vite + Cloud Gemini)
echo ==================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%ops\start-local.ps1" -ReadinessTimeoutSeconds 60
if errorlevel 1 goto failed_dev
start "" "http://127.0.0.1:5173"
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

:failed_dev
echo.
echo Development stack failed. Check api_server\data\.runtime\ and web_app\output\.runtime\ logs.
pause
exit /b 1

:failed
echo.
echo Failed to start Tajik HTR Studio in lightweight mode.
echo Check:
echo   api_server\data\.runtime\api.stderr.log
echo   api_server\data\.runtime\worker.stderr.log
echo.
pause
exit /b 1
