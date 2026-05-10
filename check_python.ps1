# Проверка и установка Python
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Проверка Python" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Проверка Python
$pythonFound = $false
$pythonCmd = ""

$commands = @("python", "py", "python3")
foreach ($cmd in $commands) {
    try {
        $version = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Python найден: $version" -ForegroundColor Green
            $pythonCmd = $cmd
            $pythonFound = $true
            break
        }
    } catch {
        continue
    }
}

if (-not $pythonFound) {
    Write-Host "[ОШИБКА] Python не найден!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Хотите установить Python автоматически? (Y/N)" -ForegroundColor Yellow
    $response = Read-Host

    if ($response -eq "Y" -or $response -eq "y") {
        Write-Host ""
        Write-Host "Скачивание Python..." -ForegroundColor Yellow

        # Скачивание установщика Python
        $pythonUrl = "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"
        $installerPath = "$env:TEMP\python-installer.exe"

        try {
            Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath
            Write-Host "Запуск установщика..." -ForegroundColor Yellow
            Write-Host "ВАЖНО: Отметьте 'Add Python to PATH' при установке!" -ForegroundColor Red
            Start-Process -FilePath $installerPath -ArgumentList "/passive", "InstallAllUsers=0", "PrependPath=1" -Wait
            Write-Host "Установка завершена!" -ForegroundColor Green
            Write-Host "Перезапустите скрипт для проверки" -ForegroundColor Yellow
        } catch {
            Write-Host "Ошибка скачивания. Установите вручную:" -ForegroundColor Red
            Write-Host "https://www.python.org/downloads/" -ForegroundColor Cyan
        }
    } else {
        Write-Host ""
        Write-Host "Установите Python вручную:" -ForegroundColor Yellow
        Write-Host "1. Откройте: https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "2. Скачайте последнюю версию" -ForegroundColor Cyan
        Write-Host "3. При установке отметьте 'Add Python to PATH'" -ForegroundColor Red
    }

    Write-Host ""
    pause
    exit 1
}

# Проверка pip
Write-Host ""
Write-Host "Проверка pip..." -ForegroundColor Cyan
try {
    $pipVersion = & $pythonCmd -m pip --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] pip найден: $pipVersion" -ForegroundColor Green
    } else {
        Write-Host "[ПРЕДУПРЕЖДЕНИЕ] pip не найден" -ForegroundColor Yellow
        Write-Host "Установка pip..." -ForegroundColor Yellow
        & $pythonCmd -m ensurepip --upgrade
    }
} catch {
    Write-Host "[ПРЕДУПРЕЖДЕНИЕ] Ошибка проверки pip" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Проверка завершена" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Python готов к использованию!" -ForegroundColor Green
Write-Host "Команда Python: $pythonCmd" -ForegroundColor Cyan
Write-Host ""
Write-Host "Теперь можете запустить install.bat" -ForegroundColor Yellow
Write-Host ""
pause
