@echo off
chcp 65001 >nul
title Tajik HTR Studio Launcher

echo ========================================================
echo         Tajik HTR Studio - Runner & Prompt Generator
echo ========================================================
echo.

:: 1. Запуск API сервера
echo [1/3] Запуск API сервера и ML worker...
start "Tajik HTR API Server" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-dev.ps1"
echo [OK] Запрос на запуск API отправлен.
echo.

:: 2. Выбор сессии для генерации промта
echo [2/3] Выберите номер сессии для генерации промта:
echo   1. Сессия 1: Git commit + /processing + /settings
echo   2. Сессия 2: /documents (список и карточки)
echo   3. Сессия 3: /editor (текстовая часть и автосохранение)
echo   4. Сессия 4: /editor (split view и связь с изображением)
echo   5. Сессия 5: /review + Таджикская панель символов
echo   6. Сессия 6: /export (экспорт и поделиться)
echo   7. Сессия 7: /organizer + /diagnostics
echo   8. Сессия 8: Финальная чистка и удаление заглушек
echo   9. Сессия 9: Проверка в браузере
echo.

set /p SESSION_NUM="Введите номер сессии (1-9) и нажмите Enter: "

set PROMPT_TEXT=

if "%SESSION_NUM%"=="1" (
    set PROMPT_TEXT=Ты работаешь над веб-приложением Tajik HTR Studio в c:\Users\bahro\OneDrive\Desktop\HTR App X Server\web_app. Прочитай docs/FLASH_INSTRUCTIONS.md. Выполни Сессию 1 (git commit + /processing + /settings). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="2" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 2 (/documents). Сначала git commit, потом работай над списком документов, табами и поиском. Используй субагентов.
)
if "%SESSION_NUM%"=="3" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 3 (/editor основа текста). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="4" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 4 (/editor split view и связь с изображением). Сначала git commit!
)
if "%SESSION_NUM%"=="5" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 5 (/review + Таджикская панель). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="6" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 6 (/export). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="7" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 7 (/organizer + /diagnostics). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="8" (
    set PROMPT_TEXT=Продолжай по docs/FLASH_INSTRUCTIONS.md — выполни Сессию 8 (удали WorkspaceRoute полностью, интеграция и чистка). Сначала сделай git commit!
)
if "%SESSION_NUM%"=="9" (
    set PROMPT_TEXT=Финальная проверка по docs/FLASH_INSTRUCTIONS.md — Сессия 9. Открой браузер, пройди по всем маршрутам, убедись что заглушек нет. Git commit "feat: all stubs replaced".
)

if defined PROMPT_TEXT (
    echo %PROMPT_TEXT% | clip
    echo.
    echo ========================================================
    echo Промт для Сессии %SESSION_NUM% скопирован в буфер обмена!
    echo ========================================================
    echo Сгенерированный промт:
    echo %PROMPT_TEXT%
    echo.
) else (
    echo [!] Неверный номер сессии. Промт не сгенерирован.
)

:: 3. Запуск веб-клиента
echo [3/3] Запуск React Web-клиента (Vite)...
echo.
cd /d "%~dp0web_app"
npm run dev

pause
