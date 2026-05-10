@echo off
chcp 65001 >nul
echo ====================================
echo Запуск проверки Python (PowerShell)
echo ====================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0check_python.ps1"

if errorlevel 1 (
    echo.
    echo Проверка не пройдена
    pause
    exit /b 1
)

echo.
pause
