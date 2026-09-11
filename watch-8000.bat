@echo off
setlocal
chcp 65001 >nul
title Tajik HTR Studio - port 8000 logs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0api_server\ops\watch-8000.ps1" %*
exit /b %ERRORLEVEL%
