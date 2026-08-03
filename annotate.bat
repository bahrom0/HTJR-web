@echo off
setlocal
chcp 65001 >nul
set "WORKSPACE_ROOT=%~dp0"
set "ACTION=%~1"
if not defined ACTION set "ACTION=Start"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%annotation_app\start.ps1" -Action "%ACTION%"
exit /b %ERRORLEVEL%
