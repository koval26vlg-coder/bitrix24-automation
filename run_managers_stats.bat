@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo STATISTIKA ZVONKOV MENEDZHEROV
echo ====================================
echo.

set PYTHON_CMD=
set PYTHON_PATHS="C:\Program Files\Python313\python.exe" "C:\Program Files\Python312\python.exe"

where python >nul 2>&1
if %errorlevel% equ 0 (set PYTHON_CMD=python & goto :run)

for %%P in (%PYTHON_PATHS%) do (
    if exist %%P (set PYTHON_CMD=%%P & goto :run)
)

echo [ERROR] Python ne nayden!
pause
exit /b 1

:run
%PYTHON_CMD% managers_call_stats.py

echo.
pause
