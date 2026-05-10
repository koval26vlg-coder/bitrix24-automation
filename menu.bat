@echo off
chcp 65001 >nul
cd /d "%~dp0"

:menu
cls
echo ====================================
echo   АВТОМАТИЗАЦИЯ BITRIX24
echo ====================================
echo.
echo 1. Bit.Newton: транскрипция и KPI звонков
echo 2. Отчет по лидам
echo 3. Отчет по сделкам
echo 4. Отчет по контактам
echo 5. Полный отчет CRM
echo 6. Статистика звонков менеджеров
echo 7. Установить зависимости
echo 8. Открыть папку с отчетами
echo 0. Выход
echo.
echo ====================================

set /p choice="Выберите действие (0-8): "

if "%choice%"=="1" (
    call run_transcription.bat
    goto menu
)
if "%choice%"=="2" (
    call run_leads.bat
    goto menu
)
if "%choice%"=="3" (
    call run_deals.bat
    goto menu
)
if "%choice%"=="4" (
    call run_contacts.bat
    goto menu
)
if "%choice%"=="5" (
    call run_full_report.bat
    goto menu
)
if "%choice%"=="6" (
    call run_managers_stats.bat
    goto menu
)
if "%choice%"=="7" (
    call install.bat
    goto menu
)
if "%choice%"=="8" (
    if exist reports (
        start explorer reports
    ) else (
        echo Папка reports пока не создана
        pause
    )
    goto menu
)
if "%choice%"=="0" (
    exit
)

echo Неверный выбор!
timeout /t 2 >nul
goto menu
