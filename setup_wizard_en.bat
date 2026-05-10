@echo off
cls

echo ====================================
echo QUICK SETUP - BITRIX24 WEBHOOK
echo ====================================
echo.
echo This wizard will help you setup webhook in 2 minutes!
echo.
echo ====================================
echo.
echo STEP 1: Open Bitrix24 in browser
echo.
echo Press Enter to open your portal...
pause >nul
start https://online-kassa.bitrix24.ru
echo.
echo OK - Portal opened in browser
echo.
echo ====================================
echo.
echo STEP 2: Create webhook
echo.
echo In Bitrix24 do:
echo   1. Find "Applications" or "Developers" in left menu
echo   2. Select "Webhooks" - "Incoming webhook"
echo   3. Click "Add webhook"
echo   4. Check permissions: CRM, Disk, Users, Telephony/Voximplant
echo   5. Click "Save"
echo   6. Copy the URL you receive
echo.
echo Press Enter when you copied the URL...
pause >nul
echo.
echo ====================================
echo.
echo STEP 3: Paste webhook URL
echo.
echo Now .env file will open in Notepad
echo.
echo In the file find line:
echo   BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/PASTE_HERE...
echo.
echo Replace "PASTE_HERE_YOUR_WEBHOOK_CODE" with your URL
echo And add BITNEWTON_TOKEN.
echo.
echo Example of correct URL:
echo   BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/123/abc123def456/
echo   BITNEWTON_TOKEN=your_bitnewton_token
echo.
echo Press Enter to open file...
pause >nul
notepad .env
echo.
echo OK - File .env opened
echo.
echo ====================================
echo.
echo STEP 4: Test connection
echo.
echo After you:
echo   - Pasted webhook URL into .env file
echo   - Pasted BITNEWTON_TOKEN into .env file
echo   - Saved file (Ctrl+S)
echo   - Closed Notepad
echo.
echo Press Enter to test connection...
pause >nul
echo.
echo Testing connection...
echo.
call test_connection.bat
echo.
echo ====================================
echo.
echo If connection successful - all done!
echo Run menu.bat to work with reports and Bit.Newton
echo.
echo If error - check:
echo   1. URL copied correctly (must end with /)
echo   2. Webhook is active in Bitrix24
echo   3. Webhook has CRM, Disk, Users, Telephony/Voximplant permissions
echo.
pause
