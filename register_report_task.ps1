# Регистрирует задачу Планировщика Windows для регулярного отчета bitnewton_sync
# и (опционально) отправки сводки в Telegram.
#
# Запускать вручную один раз от имени текущего пользователя:
#   pwsh -File register_report_task.ps1
#   pwsh -File register_report_task.ps1 -Time "08:30" -SendTelegram
#   pwsh -File register_report_task.ps1 -Arguments "--mode filter --limit 200 --use-bitnewton"
#
# Удалить задачу:
#   Unregister-ScheduledTask -TaskName "Bitrix24 Daily Report" -Confirm:$false
#
# ВНИМАНИЕ: подберите -Arguments под ваш регулярный сценарий (см. python bitnewton_sync_to_api.py --help).
# По умолчанию внешние записи в Bitrix24 выключены политикой no_external_write.

param(
    [string]$TaskName = "Bitrix24 Daily Report",
    [string]$Time = "08:00",
    [string]$Arguments = "--mode filter --limit 200 --use-bitnewton",
    [switch]$SendTelegram
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv-test\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
    Write-Warning "Локальный venv не найден, задача будет использовать python из PATH."
}

$commands = @("& `"$python`" bitnewton_sync_to_api.py $Arguments")
if ($SendTelegram) {
    $commands += "& `"$python`" telegram_notify.py"
}
$commandLine = $commands -join "; "

$action = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -Command `"Set-Location '$projectRoot'; $commandLine`"" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Ежедневный отчет bitrix24-automation (bitnewton_sync)" `
    -Force | Out-Null

Write-Host "Задача '$TaskName' зарегистрирована: ежедневно в $Time."
Write-Host "Команда: $commandLine"
if (-not $SendTelegram) {
    Write-Host "Отправка в Telegram выключена. Для включения перезапустите с -SendTelegram."
}
