@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ====================================
echo BIT.NEWTON TRANSKRIPCIYA ZVONKOV
echo ====================================
echo.

REM Detect Python command
set PYTHON_CMD=
set PYTHON_PATHS="C:\Program Files\Python313\python.exe" "C:\Program Files\Python312\python.exe" "C:\Python313\python.exe" "C:\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

where python >nul 2>&1
if %errorlevel% equ 0 (set PYTHON_CMD=python & goto :run)
where py >nul 2>&1
if %errorlevel% equ 0 (set PYTHON_CMD=py & goto :run)

for %%P in (%PYTHON_PATHS%) do (
    if exist %%P (set PYTHON_CMD=%%P & goto :run)
)

echo [ERROR] Python ne nayden!
echo Zapustite check_python.bat
pause
exit /b 1

:run
REM If Streamlit is already running, open it instead of failing on "Port 8501 is already in use".
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://localhost:8501 -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Web-interface uzhe zapushchen: http://localhost:8501
    start "" http://localhost:8501
    echo.
    pause
    exit /b 0
)

%PYTHON_CMD% -m streamlit run web_ui.py --server.port 8501

if errorlevel 1 (
    echo.
    echo [ERROR] Ne udalos vypolnit skript
    echo Esli v loge napisano "Port 8501 is already in use", otkroyte http://localhost:8501
    echo Inache prover'te BITRIX24_WEBHOOK i BITNEWTON_TOKEN v .env
)

echo.
pause
