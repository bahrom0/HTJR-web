@echo off
setlocal
chcp 65001 >nul
title Stop Tajik HTR Studio

call "%~dp0start.bat" stop
if errorlevel 1 pause
exit /b %ERRORLEVEL%
