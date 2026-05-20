# Полный аудит Bitrix24 Automation

Дата аудита: 2026-05-19  
Каноническая папка проекта: `C:\Users\koval\bat\bitrix24-automation`

## Назначение проекта

Проект автоматизирует контроль работы с клиентами в Bitrix24: получает сделки и звонки, берет или скачивает аудио, получает расшифровку через Bit.Newton/VibeCode/кэш, оценивает разговор и CRM-дисциплину, строит Excel/JSON-отчеты и при необходимости прикрепляет расшифровку/аналитику обратно в Bitrix24.

Основной запуск:

```powershell
cd C:\Users\koval\bat\bitrix24-automation
.\run_transcription.bat
```

Прямой CLI:

```powershell
cd C:\Users\koval\bat\bitrix24-automation
.\.venv-test\Scripts\python.exe bitnewton_sync_to_api.py --help
```

Веб-интерфейс:

```powershell
cd C:\Users\koval\bat\bitrix24-automation
.\.venv-test\Scripts\python.exe -m streamlit run web_ui.py --server.port 8501
```

## Что проверено

Проверены структура проекта, git-состояние, зависимости, `.gitignore`, отчеты, внешние папки с похожими артефактами, тесты, CLI, веб-интерфейс, read-only подключения к Bitrix24, Bit.Newton и VibeCode.

Безопасные live-проверки:

- Bitrix24 `profile`: успешно, пользователь `Дмитрий`, ID `15205`.
- Bitrix24 `crm.dealcategory.list`: успешно, найдено 15 воронок.
- Bitrix24 `crm.status.list`: успешно.
- Bit.Newton token check: успешно, токен активен до 2026-06-11.
- VibeCode `/v1/me`: успешно, портал `online-kassa.bitrix24.ru`, trial активен, осталось 9 дней.
- Streamlit UI smoke test: `http://localhost:8505/` вернул HTTP 200.
- Мини-боевой запуск на реальной сделке `130565` без ASR и без записи в Bitrix: успешно сформировал отчет.
- Мини-боевой запуск с VibeCode-read на сделке `130565`: успешно получил звонки и stage-history через VibeCode, сформировал отчет.
- Режим `--reevaluate-from reports\latest_bitnewton_report.json`: успешно пересобрал отчет без повторной расшифровки.

Проверки качества:

- `python -m pytest -q`: 59 passed.
- Компиляция Python-файлов: 85 файлов, 0 ошибок.
- `ruff check`: больше нет ошибок `invalid-syntax` для Python 3.10, но остаются 1840 замечаний форматирования/стиля.
- `black --check`: проект пока не отформатирован единым стилем, 77 файлов требуют форматирования.

## Исправлено во время аудита

1. Исправлен блокер запуска в `pipelines/scoring/crm.py`: f-string был несовместим с текущим парсером и ломал импорт.
2. Исправлена проверка токена Bit.Newton: код больше не делает `await` над синхронным `validate_token()`.
3. Исправлены Python 3.10-incompatible f-string выражения в ключевых файлах.
4. Исправлен режим переоценки без повторной расшифровки: `reevaluate_report` теперь ожидает async `recompute_existing_row`.
5. Исправлена финализация отчета: `user_name_map`, stage-history и lost-deals helpers переведены на корректный async-вызов.
6. Исправлен порядок закрытия Bitrix API-клиента: финальное обогащение отчета выполняется до `api.aclose()`.
7. Исправлен веб-интерфейс после async-рефакторинга: фильтры менеджеров, воронок, стадий и категории лида теперь выполняют async-запросы через синхронный bridge для Streamlit.
8. Установлены dev-зависимости в `.venv-test`: `ruff`, `black`.

## Текущее состояние проекта

Git-репозиторий есть, ветка `master`. Рабочее дерево грязное: много измененных и новых файлов после серии рефакторингов и текущих исправлений. Перед следующими крупными изменениями нужно сделать осознанный коммит.

Крупные модули по размеру:

- `pipelines/reporting.py` - 119 KB, главный новый монолит.
- `ui_audio_downloader.py` - 43 KB, Selenium/UI fallback.
- `web_ui.py` - 38 KB, Streamlit-интерфейс.
- `pipelines/script_scoring.py` - 33 KB.
- `pipelines/conversation_intelligence.py` - 30 KB.
- `pipelines/lost_deals.py` - 22 KB.
- `pipelines/scoring/checklist.py` - 20 KB.

`pipelines/bitnewton_sync.py` уже уменьшен до тонкого orchestration-слоя. Самый большой долг теперь не в нем, а в отчетности, веб-интерфейсе и UI-скачивании.

## Найденные внешние артефакты

Канонический проект: `C:\Users\koval\bat\bitrix24-automation`.

Связанные, но не канонические места:

- `C:\Users\koval\Documents\GitHub\bitrix24-automation` - почти пустой git-репозиторий, только `.git` и `.gitattributes`; не является рабочим проектом.
- `C:\Users\koval\Documents\Codex\2026-05-19\new-chat-2` - отдельная разовая выгрузка Bitrix24: `deals.json` около 97 MB, `deals.csv` около 15 MB, `tasks.json`, `users.json`, `crm_statuses.json`, `deal_fields.json`, `scripts\export_bitrix24.ps1`, `bitrix24.env`. Не переносить `.env` в проект из-за секретов.
- `D:\ОК` - старый отчет `bitnewton_sync_report_20260508_181510.*` и установщик Bitrix24 desktop. Можно оставить как архив или перенести только отчет без секретов.
- `C:\Users\koval\Desktop\Bitrix24 Аналитика.url` - ярлык на `http://localhost:8501/`.
- `C:\Users\koval\Desktop\...` - обучающие материалы по Bitrix24, не часть кода проекта.

Решение: все новые документы и решения по проекту вести в `C:\Users\koval\bat\bitrix24-automation\docs\`. Большие сырые выгрузки держать отдельно и подключать только как источник данных, не смешивать с кодом.

## Состояние reports

`reports/` игнорируется git, но накопил много рабочих артефактов:

- JSON: 68 файлов, около 281 MB.
- MP3: 232 файла, около 79.5 MB.
- XLSX: 66 файлов, около 39.8 MB.
- файлы без расширения: 218 файлов, около 22 MB.
- TXT: 438 файлов, около 1.5 MB.

TTL-очистка в проекте есть (`--cleanup-output-days`, по умолчанию 30), но исторический мусор уже накоплен. Безопасный следующий шаг: сделать отдельную команду `cleanup_reports.bat` с dry-run и подтверждением, чтобы удалять старое управляемо, а не руками.

## Слабые места

### P1. Грязное git-состояние

В проекте много несохраненных изменений и новых файлов. Это риск для любого следующего рефакторинга: сложно понять, что уже проверено, а что эксперимент.

Решение: после текущего аудита сделать коммит вида `fix: stabilize bitrix pipeline async runtime`.

### P1. Нет полноценного dry-run режима

Сейчас можно безопасно проверять read-only подключения и переоценку, но нет явного флага `--dry-run`, который гарантирует: не скачивать ASR, не attach в Bitrix, не писать timeline-log.

Решение: добавить `--dry-run` и централизованно блокировать все внешние write-действия.

### P1. Много legacy-скриптов не переведены на async API

Основной pipeline исправлен, но отдельные старые скрипты (`op_deals_analytics.py`, `op_lost_deals_analysis.py`, `detailed_*`, `yesterday_*`, `managers_call_stats_auto.py`, `pipelines/dump_one_call_debug.py`) вызывают `api.call()` как синхронную функцию. После перехода `Bitrix24API` на async эти скрипты потенциально нерабочие.

Решение: либо перевести их на async, либо пометить как deprecated и убрать из меню.

### P1. `pipelines/reporting.py` стал новым монолитом

После успешной декомпозиции `bitnewton_sync.py` большой объем логики переехал в reporting. Это рабочее, но поддерживать сложно.

Решение: разбить на `excel_writer.py`, `rows.py`, `manager_summary.py`, `sheets/*.py`, `formatting.py`.

### P1. UI fallback через браузер остается хрупким

Selenium/Edge fallback нужен только когда API не отдает файл. Он медленный и зависит от интерфейса Bitrix.

Решение: считать UI fallback аварийным точечным режимом. Массовый поток должен идти через VibeCode `/v1/files/:fileId/download`, Bitrix Disk/API или локальную папку аудио.

### P2. RUFF/Black еще не введены как обязательные проверки

`ruff` больше не показывает Python 3.10 syntax blockers, но все еще находит 1840 style/lint замечаний. `black --check` требует форматирования 77 файлов.

Решение: не форматировать всё вместе с функциональными изменениями. Сделать отдельный форматирующий коммит.

### P2. Дублирующие ASR-файлы

Есть `bit_newton_asr.py` и подозрительный новый `bit_new_ton_asr.py`. Нужно оставить один канонический клиент и убрать/заархивировать дубль.

### P2. Документация частично устарела

`README.md` ссылается на старые файлы, часть которых лежит в `docs/_archive`. Это создает путаницу при запуске.

Решение: обновить `README.md`, оставить одну точку входа и один runbook.

### P2. Домен завязан на `online-kassa.bitrix24.ru`

Для текущего клиента нормально, но для второго портала понадобится profile-based конфигурация.

Решение: `profiles/<name>.env` + `--profile`.

## Перспективы развития

1. Быстрый путь ускорения: использовать VibeCode как основной read/file-download слой, Bitrix REST как fallback, UI fallback только вручную.
2. Добавить режимы:
   - `--dry-run`
   - `--retry-errors-from`
   - `--reevaluate-from`
   - `--audio-source-dir`
   - `--no-external-write`
3. Сделать SQLite state-store вместо большого `state_cache.json`: звонок, hash аудио/текста, статус ASR, статус attach, timestamp.
4. Собирать аналитику не только в Excel, а в локальную БД: потом Streamlit будет дашбордом над данными, а не только запускателем.
5. Укрепить conversation intelligence:
   - карта разговора,
   - возражения,
   - неотработанные возражения,
   - эмоциональные риски,
   - факторы конверсии,
   - рекомендации менеджерам,
   - связь с проигранными сделками.
6. Для проигранных сделок строить причинную аналитику: причина отказа, стадия потери, менеджер, источник, длительность воронки, качество последнего контакта, наличие следующего шага.
7. Добавить weekly-manager report: кто теряет на цене, кто не фиксирует следующий шаг, кто долго держит сделки на стадиях, где нужны тренировки.

## Рекомендуемый порядок дальнейших работ

1. Сделать коммит текущей стабилизации.
2. Добавить `--dry-run` и тесты на запрет внешних write-действий.
3. Разобрать legacy-скрипты: рабочие перевести на async, ненужные убрать из меню.
4. Разбить `pipelines/reporting.py`.
5. Ввести `cleanup_reports.bat --dry-run`.
6. Свести README/QUICKSTART/runbook к одному актуальному сценарию запуска.
7. Сделать отдельный formatting-коммит `black`/`ruff --fix`.

