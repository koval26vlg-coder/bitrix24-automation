@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo ПОЛНЫЙ ОТЧЕТ CRM Bitrix24
echo ====================================
echo.

REM Определение команды Python
set PYTHON_CMD=
set PYTHON_PATHS="C:\Program Files\Python313\python.exe" "C:\Program Files\Python312\python.exe" "C:\Python313\python.exe" "C:\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

where python >nul 2>&1
if %errorlevel% equ 0 (set PYTHON_CMD=python & goto :run)
where py >nul 2>&1
if %errorlevel% equ 0 (set PYTHON_CMD=py & goto :run)

for %%P in (%PYTHON_PATHS%) do (
    if exist %%P (set PYTHON_CMD=%%P & goto :run)
)

echo [ОШИБКА] Python не найден!
echo Запустите check_python.bat
pause
exit /b 1

:run
%PYTHON_CMD% crm_report.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось выполнить скрипт
    echo Проверьте настройки в .env файле
)

echo.
echo Отчеты сохранены в папке reports\
echo.
pause
