# Быстрый старт

## 1. Установить зависимости

```bash
install.bat
python -m pip install -r requirements_ui.txt
```

## 2. Настроить `.env`

```env
BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/
BITRIX24_DOMAIN=online-kassa.bitrix24.ru
BITNEWTON_ASR_URL=https://bit-asr.1bitai.ru
BITNEWTON_TOKEN=your_bitnewton_token
```

Webhook должен иметь права на CRM, телефонию, диск и пользователей.

## 3. Запустить Bit.Newton-интерфейс

```bash
run_transcription.bat
```

Откроется Streamlit UI. В нем можно выбрать одну сделку или фильтр сделок, включить UI fallback для скачивания записи и выбрать KPI-профиль.

## 4. Где смотреть результат

Результаты сохраняются в `reports/`:

- `bitnewton_sync_report_*.json`
- `bitnewton_sync_report_*.xlsx`

## 5. CRM-отчеты без транскрипции

```bash
run_leads.bat
run_deals.bat
run_contacts.bat
run_full_report.bat
run_managers_stats.bat
```
