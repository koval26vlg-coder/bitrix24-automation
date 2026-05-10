@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo Установка зависимостей Bitrix24
echo ====================================
echo.

REM Определение команды Python
set PYTHON_CMD=
set PYTHON_PATHS="C:\Program Files\Python313\python.exe" "C:\Program Files\Python312\python.exe" "C:\Program Files\Python311\python.exe" "C:\Python313\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

REM Проверка стандартных команд
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :found_python
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :found_python
)

where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto :found_python
)

REM Поиск по полным путям
for %%P in (%PYTHON_PATHS%) do (
    if exist %%P (
        set PYTHON_CMD=%%P
        goto :found_python
    )
)

echo [ОШИБКА] Python не найден!
echo.
echo Запустите check_python.bat для проверки и установки Python
pause
exit /b 1

:found_python
echo [OK] Используется Python:
%PYTHON_CMD% --version
echo.

echo Установка библиотек...
%PYTHON_CMD% -m pip install -r requirements.txt
%PYTHON_CMD% -m pip install -r requirements_ui.txt

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось установить зависимости
    echo Попробуйте: %PYTHON_CMD% -m pip install --upgrade pip
    pause
    exit /b 1
)

echo.
echo ====================================
echo Установка завершена успешно!
echo ====================================
echo.
echo Следующий шаг:
echo 1. Откройте файл setup_webhook.md
echo 2. Следуйте инструкциям для создания webhook
echo 3. Скопируйте .env.example в .env
echo 4. Вставьте webhook URL и BITNEWTON_TOKEN в .env
echo.
pause
