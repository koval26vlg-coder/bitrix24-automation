# Автоматизация Bitrix24

Проект выгружает CRM-данные из Bitrix24, формирует Excel-отчеты и обрабатывает записи звонков через Bit.Newton ASR.

## Основной сценарий

1. Bitrix24 отдает сделки и активности звонков через REST API.
2. Скрипт находит запись звонка, скачивает аудио через REST или UI fallback.
3. Bit.Newton расшифровывает аудио.
4. Готовая расшифровка прикрепляется обратно в Bitrix24 через `telephony.call.attachtranscription`.
5. В `reports/` создаются JSON/XLSX отчеты с KPI по звонкам и менеджерам.

## Настройка

Создайте `.env` по примеру `.env.example`:

```env
BITRIX24_WEBHOOK=https://online-kassa.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/
BITRIX24_DOMAIN=online-kassa.bitrix24.ru
BITNEWTON_ASR_URL=https://bit-asr.1bitai.ru
BITNEWTON_TOKEN=your_bitnewton_token
BITRIX24_SOURCE_IP=
VIBECODE_SOURCE_IP=
```

Права входящего webhook: CRM, телефония, диск, пользователи.

Если работаете через full-tunnel VPN (VanyaVPN/Outline), задайте `BITRIX24_SOURCE_IP` и `VIBECODE_SOURCE_IP` в локальный Wi-Fi IP, чтобы избежать TLS timeout на Bitrix/VibeCode.

## Установка

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements_ui.txt
```

## Запуск

```bash
menu.bat
```

или напрямую:

```bash
run_transcription.bat
```

Для CLI-запуска одной сделки:

```bash
python bitnewton_sync_to_api.py --mode single --deal-url https://online-kassa.bitrix24.ru/crm/deal/details/123/ --use-bitnewton --bitnewton-flow --ui-download
```

## Основные файлы

- `web_ui.py` - Streamlit-интерфейс для выбора сделок и запуска Bit.Newton-пайплайна.
- `bitnewton_sync_to_api.py` - CLI-точка входа.
- `pipelines/bitnewton_sync.py` - основной пайплайн звонок -> аудио -> Bit.Newton -> Bitrix24.
- `bit_newton_asr.py` - клиент Bit.Newton ASR.
- `bitrix24_api.py` - клиент Bitrix24 REST API.
- `bitrix/recordings.py` - поиск записи звонка и URL-кандидатов.
- `download_resolver.py` и `ui_audio_downloader.py` - скачивание записей.
- `kpi_config*.json` - профили оценки звонков.

## Документация

- `docs/TROUBLESHOOTING.txt` - диагностика типовых проблем запуска.
- `docs/INSTALL_FFMPEG.txt` - установка FFmpeg.
- `docs/kriterii_ocenki.txt` - исходные критерии оценки звонков.
- `docs/_archive/` - старые служебные заметки, сохраненные только для истории.

`reports/`, `.env`, аудио, временные профили браузера и локальные кэши исключены из git через `.gitignore`.
