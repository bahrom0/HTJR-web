@echo off
setlocal
chcp 65001 >nul
title Tajik HTR Studio

rem Compatibility launcher. There must be only one startup path so a second
rem double-click cannot create another Vite/API/worker process.
call "%~dp0start.bat" %*
exit /b %ERRORLEVEL%
