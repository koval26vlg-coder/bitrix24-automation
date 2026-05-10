@echo off
chcp 1251 >nul
cls

echo ====================================
echo NASTROYKA WEBHOOK DLYA BITRIX24
echo ====================================
echo.
echo Etot skript pomozhet vam nastroit webhook za 2 minuty!
echo.
echo ====================================
echo.
echo SHAG 1: Otkroyte Bitrix24 v brauzere
echo.
echo Nazhmite Enter, chtoby otkryt vash portal...
pause >nul
start https://online-kassa.bitrix24.ru
echo.
echo OK - Portal otkryt v brauzere
echo.
echo ====================================
echo.
echo SHAG 2: Sozdayte webhook
echo.
echo V Bitrix24 vypolnite:
echo   1. Naydite "Prilozheniya" ili "Razrabotchikam" v menyu sleva
echo   2. Vyberite "Vebhuki" - "Vhodyashchiy vebhuk"
echo   3. Nazhmite "Dobavit vebhuk"
echo   4. Otmette prava: CRM, Disk, Polzovateli, Telefonia/Voximplant
echo   5. Nazhmite "Sohranit"
echo   6. Skopiruyte poluchennyy URL
echo.
echo Nazhmite Enter, kogda skopiruete URL...
pause >nul
echo.
echo ====================================
echo.
echo SHAG 3: Vstavte webhook URL
echo.
echo Seychas otkroetsya fayl .env v Bloknote
echo.
echo V fayle naydite stroku:
echo   BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/VSTAVTE_SYUDA...
echo.
echo Zamenite "VSTAVTE_SYUDA_VASH_WEBHOOK_KOD" na vash URL
echo I dobavte BITNEWTON_TOKEN.
echo.
echo Primer pravilnogo URL:
echo   BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/123/abc123def456/
echo   BITNEWTON_TOKEN=your_bitnewton_token
echo.
echo Nazhmite Enter, chtoby otkryt fayl...
pause >nul
notepad .env
echo.
echo OK - Fayl .env otkryt
echo.
echo ====================================
echo.
echo SHAG 4: Proverka podklyucheniya
echo.
echo Posle togo kak vy:
echo   - Vstavili webhook URL v fayl .env
echo   - Vstavili BITNEWTON_TOKEN v fayl .env
echo   - Sohranili fayl (Ctrl+S)
echo   - Zakryli Bloknot
echo.
echo Nazhmite Enter dlya proverki podklyucheniya...
pause >nul
echo.
echo Proveryaem podklyuchenie...
echo.
call test_connection.bat
echo.
echo ====================================
echo.
echo Esli podklyuchenie uspeshno - vsyo gotovo!
echo Zapustite menu.bat dlya raboty s otchetami i Bit.Newton
echo.
echo Esli oshibka - proverte:
echo   1. Pravilno li skopirovan URL (dolzhen zakanchivatsya na /)
echo   2. Aktiven li webhook v Bitrix24
echo   3. Est li prava CRM, Disk, Polzovateli, Telefonia/Voximplant u webhook
echo.
pause
