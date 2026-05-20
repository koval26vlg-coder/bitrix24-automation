from __future__ import annotations

import argparse
import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off", "нет"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bit.Newton: звонок -> аудио -> ASR -> attachtranscription"
    )
    parser.add_argument("--mode", choices=["single", "filter"], default=None)
    parser.add_argument("--deal-id", default=None, help="ID сделки (для mode=single)")
    parser.add_argument(
        "--deal-url", default=None, help="URL сделки (для mode=single, если ID не задан)"
    )
    parser.add_argument(
        "--filter-json",
        default=None,
        help="Путь к JSON фильтру для crm.deal.list (для mode=filter)",
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--diarize", action="store_true", help="Bit.Newton diarize")
    parser.add_argument(
        "--use-bitnewton", action="store_true", help="Включить Bit.Newton (нужен BITNEWTON_TOKEN)"
    )
    parser.add_argument(
        "--bitnewton-flow", action="store_true", help="Идти строго: call->audio->bitnewton->attach"
    )
    parser.add_argument(
        "--download-audio", action="store_true", help="Сохранять аудио в reports/audio/"
    )
    parser.add_argument(
        "--audio-source-dir",
        action="append",
        default=[],
        help="Локальная папка с уже доступными аудиозаписями. Можно передать несколько раз или через ;",  # noqa: E501
    )
    parser.add_argument(
        "--ui-download",
        action="store_true",
        help="Если REST-скачивание недоступно - попытаться скачать через Chrome (нужен логин в профиле)",  # noqa: E501
    )
    parser.add_argument(
        "--ui-browser",
        choices=["chrome", "edge"],
        default="chrome",
        help="Какой браузер использовать для UI-fallback (edge безопаснее для рабочего Chrome)",
    )
    parser.add_argument(
        "--ui-download-mode",
        choices=["direct", "timeline", "auto"],
        default="auto",
        help="UI способ: direct=точная CRM-ссылка записи, timeline=кнопка Скачать в таймлайне, auto=direct->timeline",  # noqa: E501
    )
    parser.add_argument(
        "--ui-timeout-sec",
        type=int,
        default=20,
        help="Сколько ждать обычное UI-скачивание; ручной вход в Bitrix ждём отдельно минимум 120 секунд",  # noqa: E501
    )
    parser.add_argument(
        "--rest-timeout-sec",
        type=int,
        default=20,
        help="Сколько ждать REST-скачивание одного URL записи",
    )
    parser.add_argument(
        "--ui-download-dir",
        default=None,
        help="Куда скачивать через UI (по умолчанию reports/audio_ui)",
    )
    parser.add_argument(
        "--browser-profile-directory",
        default="Default",
        help="Имя профиля браузера внутри User Data, например Default или Profile 1",
    )
    parser.add_argument(
        "--chrome-profile-dir",
        default=None,
        help="Папка профиля Chrome для UI-скачивания. Можно указать 'system' чтобы использовать обычный профиль Chrome (LOCALAPPDATA/Google/Chrome/User Data).",  # noqa: E501
    )
    parser.add_argument(
        "--domain", default=os.getenv("BITRIX24_DOMAIN", "online-kassa.bitrix24.ru")
    )
    parser.add_argument(
        "--kpi-config", default=None, help="Путь к JSON с порогами/весами/паттернами оценки"
    )
    parser.add_argument(
        "--kpi-config-compare", default=None, help="Второй KPI JSON для сравнения в этом же отчёте"
    )
    parser.add_argument(
        "--force-attach",
        action="store_true",
        help="Всегда делать attachtranscription, игнорируя локальный state_cache",
    )
    parser.add_argument(
        "--no-reuse-transcripts",
        action="store_true",
        help="Не использовать ранее сохранённые расшифровки; заново скачивать аудио и отправлять в Bit.Newton",  # noqa: E501
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Безопасная репетиция боевого сценария: читать Bitrix/VibeCode и локальный кэш, "
            "но не запускать новую ASR и не писать обратно во внешние системы"
        ),
    )
    parser.add_argument(
        "--no-external-write",
        action="store_true",
        help="Не выполнять внешние write-действия: attachTranscription, VibeCode calls/transcription и timeline-logs",  # noqa: E501
    )
    parser.add_argument(
        "--retry-errors-from",
        default=None,
        help="JSON отчета, из которого нужно повторить только строки с ошибками",
    )
    parser.add_argument(
        "--reevaluate-from",
        default=None,
        help="JSON отчета, который нужно переоценить без скачивания аудио и Bit.Newton",
    )
    parser.add_argument(
        "--max-calls-per-deal",
        type=int,
        default=0,
        help="Ограничить количество звонков для анализа по каждой сделке; 0 = все",
    )
    parser.add_argument(
        "--min-call-duration-sec",
        type=int,
        default=15,
        help="Не отправлять в ASR технические звонки короче N секунд; 0 отключает",
    )
    parser.add_argument(
        "--include-call-center",
        action="store_true",
        help="Не исключать звонки операторов Call-центра из анализа",
    )
    parser.add_argument(
        "--fetch-bitrix-card-transcript",
        action="store_true",
        help="Пробовать читать расшифровку из карточки звонка Bitrix через UI и сопоставлять с Bit.Newton",  # noqa: E501
    )
    parser.add_argument(
        "--lost-deals-analysis",
        action="store_true",
        help="Добавить в Excel анализ проигранных сделок и типичных причин отказа",
    )
    parser.add_argument(
        "--lost-deals-limit",
        type=int,
        default=500,
        help="Лимит проигранных сделок для анализа причин отказа",
    )
    parser.add_argument(
        "--cleanup-output-days",
        type=int,
        default=30,
        help="Автоудаление отчетов, расшифровок и аудио старше N дней; 0 отключает",
    )
    parser.add_argument(
        "--cleanup-chrome-tmp-days",
        type=int,
        default=7,
        help="Удалять старые reports/chrome_profile_tmp_* (дней хранения)",
    )
    parser.add_argument(
        "--use-vibecode",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("USE_VIBECODE", True),
        help="Использовать VibeCode API при наличии VIBECODE_API_KEY",
    )
    parser.add_argument(
        "--vibecode-read",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("VIBECODE_READ", True),
        help="Читать сделки/активности/stage-history через VibeCode с fallback на Bitrix REST",
    )
    parser.add_argument(
        "--vibecode-audio-download",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("VIBECODE_AUDIO_DOWNLOAD", True),
        help="Пробовать скачать запись через /v1/files/:id/download до REST/UI fallback",
    )
    parser.add_argument(
        "--vibecode-asr-fallback",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("VIBECODE_ASR_FALLBACK", False),
        help="Если Bit.Newton недоступен, пробовать VibeCode /v1/audio/transcriptions",
    )
    parser.add_argument(
        "--vibecode-attach-transcription",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("VIBECODE_ATTACH_TRANSCRIPTION", False),
        help="Пробовать прикреплять расшифровку через VibeCode /v1/calls/transcription; по умолчанию выключено.",  # noqa: E501
    )
    parser.add_argument(
        "--vibecode-timeline-log",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("VIBECODE_TIMELINE_LOG", False),
        help="Писать краткий результат анализа в таймлайн сделки через /v1/timeline-logs",
    )
    return parser
