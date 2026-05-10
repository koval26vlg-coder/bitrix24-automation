@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo Проверка подключения к Bitrix24
echo ====================================
echo.

if not exist .env (
    echo [ОШИБКА] Файл .env не найден!
    echo.
    echo Создайте файл .env на основе .env.example
    echo и добавьте ваш webhook URL
    echo.
    pause
    exit /b 1
)

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
%PYTHON_CMD% -c "from bitrix24_api import Bitrix24API; api = Bitrix24API(); api.test_connection()"

echo.
pause
