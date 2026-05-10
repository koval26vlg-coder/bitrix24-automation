@echo off
chcp 65001 >nul
echo ====================================
echo Проверка Python
echo ====================================
echo.

REM Проверка Python
where python >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python найден:
    python --version
    echo.
    goto :check_pip
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python найден через py launcher:
    py --version
    echo.
    goto :check_pip
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python найден:
    python3 --version
    echo.
    goto :check_pip
)

echo [ОШИБКА] Python не найден!
echo.
echo Варианты решения:
echo.
echo 1. Установить Python:
echo    - Откройте: https://www.python.org/downloads/
echo    - Скачайте последнюю версию
echo    - При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
echo.
echo 2. Если Python уже установлен, добавьте его в PATH:
echo    - Найдите папку установки Python (обычно C:\Python3X или C:\Users\%USERNAME%\AppData\Local\Programs\Python)
echo    - Добавьте в переменную PATH
echo.
echo 3. Использовать альтернативную версию (PowerShell):
echo    - Запустите check_python_powershell.ps1
echo.
pause
exit /b 1

:check_pip
echo Проверка pip...
where pip >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] pip найден:
    pip --version
    echo.
    goto :success
)

python -m pip --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] pip найден через python -m pip:
    python -m pip --version
    echo.
    goto :success
)

py -m pip --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] pip найден через py -m pip:
    py -m pip --version
    echo.
    goto :success
)

echo [ПРЕДУПРЕЖДЕНИЕ] pip не найден
echo Установите pip: python -m ensurepip --upgrade
echo.

:success
echo ====================================
echo Проверка завершена
echo ====================================
echo.
echo Python готов к использованию!
echo Теперь можете запустить install.bat
echo.
pause
