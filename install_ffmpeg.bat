@echo off
echo ====================================
echo USTANOVKA FFMPEG
echo ====================================
echo.

echo Popytka 1: Ustanovka cherez winget...
winget install ffmpeg --accept-package-agreements --accept-source-agreements
if %errorlevel% equ 0 (
    echo.
    echo [OK] ffmpeg ustanovlen cherez winget
    goto :verify
)

echo.
echo Popytka 2: Ustanovka cherez chocolatey...
where choco >nul 2>&1
if %errorlevel% equ 0 (
    choco install ffmpeg -y
    if %errorlevel% equ 0 (
        echo [OK] ffmpeg ustanovlen cherez chocolatey
        goto :verify
    )
)

echo.
echo [INFO] Avtomaticheskaya ustanovka ne udalas
echo.
echo Ruchnaya ustanovka:
echo 1. Otkroyte: https://github.com/BtbN/FFmpeg-Builds/releases
echo 2. Skachayte: ffmpeg-master-latest-win64-gpl.zip
echo 3. Raspakuyte v C:\ffmpeg
echo 4. Dobavte v PATH: C:\ffmpeg\bin
echo.
pause
exit /b 1

:verify
echo.
echo Proverka ustanovki...
ffmpeg -version
if %errorlevel% equ 0 (
    echo.
    echo [OK] ffmpeg uspeshno ustanovlen!
    echo Teper mozhno zapustit: run_transcription.bat
) else (
    echo.
    echo [WARNING] ffmpeg ustanovlen, no trebuetsya perezapusk terminala
    echo Zakroyte eto okno i otkroyte novoe
)

echo.
pause
