from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from asr.bitnewton import BitNewtonError, env_bitnewton_asr
from bitrix.api import Bitrix24API
from bitrix.recordings import resolve_call_recording
from download_resolver import download_best_effort
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR, TRANSCRIPTS_DIR
from pipelines.reporting import (
    build_manager_summary,
    flatten_results,
    kpi_profile_display,
    prepare_report_rows,
    publish_latest_report,
)
from pipelines.stages import (
    DEAL_TOTAL_WORK_CRITICAL_MINUTES,
    DEAL_TOTAL_WORK_WARNING_MINUTES,
    DEFAULT_STAGE_NAMES,
    STAGE_STUCK_THRESHOLD_HOURS,
    format_minutes_for_threshold as _format_minutes_for_threshold,
    stage_display_name,
    stage_duration_thresholds,
    stage_history_type_label,
    stage_order_map,
    threshold_status,
)
from pipelines.scoring import (
    HANDLING_RE,
    OBJECTION_RULES,
    _context,
    call_quality_conclusion,
    conversation_meaning,
    evaluate_call_checklist,
    evaluate_crm_checklist,
    evaluate_call_text,
    merged_transcript_text,
    recalculate_overall_score,
    transcript_match_score,
)


AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".webm", ".aac", ".opus", ".flac", ".wma"}
FIRST_RESPONSE_SLA_HOURS = 0.5
MAX_GAP_BETWEEN_CALLS_HOURS = 72.0
DEFAULT_KPI_CONFIG: Dict[str, Any] = {
    "profile": {"name": "default", "version": "1"},
    "sla": {"first_response_hours": 0.5, "max_gap_between_calls_hours": 72.0},
    "weights": {
        "overall": {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50},
        "discipline_split": {"first_response": 1.0, "cadence": 0.0},
        "crm_alignment_split": {"deal_quality": 0.6, "alignment": 0.4},
    },
    "deal_quality_weights": {"has_contact": 25, "has_amount": 25, "has_title": 25, "has_comments": 25},
    "call_quality_weights": {"greeting": 25, "needs_discovery": 30, "objection_work": 20, "next_step": 25},
    "alignment_weights": {"title_hit": 10, "title_hit_cap": 40, "amount_mentioned": 30, "next_step_synced": 30},
    "patterns": {
        "greeting": [r"\b(добрый|здравств\w*|привет)\b"],
        "needs_discovery": [r"\b(потребност\w*|задач\w*|нужно|необходим\w*|интересу\w*|уточн\w*|подскаж\w*|что нужно|что необходимо)\b"],
        "objection_work": [r"\b(дорог\w*|возраж\w*|сомнен\w*|не подходит|не смож\w*|не получится|нет возможности|подума\w*)\b"],
        "next_step": [r"\b(договор\w*|следующ\w*|перезвон\w*|отправ\w*|вышл\w*|встреч\w*|созвон\w*|уточн\w*|согласу\w*)\b"],
    },
}

STATE_CACHE_PATH = REPORTS_DIR / "state_cache.json"








def _looks_like_html_prefix(data: bytes) -> bool:
    if not data:
        return True
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<head") or head.startswith(b"<body")


def validate_audio_file(path: Path) -> Optional[str]:
    """
    Быстрая валидация, чтобы не отправлять в ASR HTML/пустышки.
    """
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return "файл не создан или пустой"
        if path.stat().st_size < 2048:
            return f"файл слишком маленький ({path.stat().st_size} bytes)"
        head = path.read_bytes()[:512]
        if _looks_like_html_prefix(head):
            return "вместо аудио скачался HTML (логин/нет прав)"
    except Exception:
        return None
    return None


def parse_audio_source_dirs(values: Any) -> List[Path]:
    out: List[Path] = []
    raw_values = values if isinstance(values, list) else ([values] if values else [])
    for raw in raw_values:
        for part in str(raw or "").split(";"):
            text = part.strip().strip('"')
            if text:
                out.append(Path(text))
    return out


def build_audio_source_index(source_dirs: List[Path]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for source_dir in source_dirs:
        try:
            base = Path(source_dir)
            if not base.exists() or not base.is_dir():
                print(f"[WARN] Локальная папка аудио не найдена: {base}", flush=True)
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                key = str(path.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        except Exception as e:
            print(f"[WARN] Не удалось просканировать папку аудио {source_dir}: {e}", flush=True)
    return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def find_local_audio_source(
    audio_index: List[Path],
    deal_id: Any,
    activity_id: Any,
    disk_file_id: Any,
    call_id: Any,
    disk_file_name: Any = None,
) -> Optional[Path]:
    if not audio_index:
        return None

    disk_name = str(disk_file_name or "").strip().lower()
    strong_tokens = [
        str(disk_file_id or "").strip(),
        str(activity_id or "").strip(),
        str(call_id or "").strip(),
        str(call_id or "").replace("VI_", "").strip(),
    ]
    weak_tokens = [str(deal_id or "").strip()]
    strong_tokens = [t.lower() for t in strong_tokens if len(t.strip()) >= 3]
    weak_tokens = [t.lower() for t in weak_tokens if len(t.strip()) >= 4]

    ranked: List[Tuple[int, float, Path]] = []
    for path in audio_index:
        try:
            name = path.name.lower()
            stem = path.stem.lower()
            score = 0
            if disk_name and name == disk_name:
                score += 120
            elif disk_name and (disk_name in name or name in disk_name):
                score += 90
            if any(token and token in name for token in strong_tokens):
                score += 80
            if any(token and token in stem for token in strong_tokens):
                score += 40
            if any(token and token in name for token in weak_tokens):
                score += 20
            if score >= 80:
                ranked.append((score, path.stat().st_mtime if path.exists() else 0, path))
        except Exception:
            continue

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bit.Newton: звонок → аудио → ASR → attachtranscription")
    parser.add_argument("--mode", choices=["single", "filter"], default=None)
    parser.add_argument("--deal-id", default=None, help="ID сделки (для mode=single)")
    parser.add_argument("--deal-url", default=None, help="URL сделки (для mode=single, если ID не задан)")
    parser.add_argument("--filter-json", default=None, help="Путь к JSON фильтру для crm.deal.list (для mode=filter)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--diarize", action="store_true", help="Bit.Newton diarize")
    parser.add_argument("--use-bitnewton", action="store_true", help="Включить Bit.Newton (нужен BITNEWTON_TOKEN)")
    parser.add_argument("--bitnewton-flow", action="store_true", help="Идти строго: call→audio→bitnewton→attach")
    parser.add_argument("--download-audio", action="store_true", help="Сохранять аудио в reports/audio/")
    parser.add_argument(
        "--audio-source-dir",
        action="append",
        default=[],
        help="Локальная папка с уже доступными аудиозаписями. Можно передать несколько раз или через ;",
    )
    parser.add_argument("--ui-download", action="store_true", help="Если REST-скачивание недоступно — попытаться скачать через Chrome (нужен логин в профиле)")
    parser.add_argument("--ui-browser", choices=["chrome", "edge"], default="chrome", help="Какой браузер использовать для UI-fallback (edge безопаснее для рабочего Chrome)")
    parser.add_argument("--ui-download-mode", choices=["direct", "timeline", "auto"], default="auto", help="UI способ: direct=точная CRM-ссылка записи, timeline=кнопка Скачать в таймлайне, auto=direct->timeline")
    parser.add_argument("--ui-timeout-sec", type=int, default=20, help="Сколько ждать обычное UI-скачивание; ручной вход в Bitrix ждём отдельно минимум 120 секунд")
    parser.add_argument("--rest-timeout-sec", type=int, default=20, help="Сколько ждать REST-скачивание одного URL записи")
    parser.add_argument("--ui-download-dir", default=None, help="Куда скачивать через UI (по умолчанию reports/audio_ui)")
    parser.add_argument("--browser-profile-directory", default="Default", help="Имя профиля браузера внутри User Data, например Default или Profile 1")
    parser.add_argument(
        "--chrome-profile-dir",
        default=None,
        help="Папка профиля Chrome для UI-скачивания. Можно указать 'system' чтобы использовать обычный профиль Chrome (LOCALAPPDATA/Google/Chrome/User Data).",
    )
    parser.add_argument("--domain", default=os.getenv("BITRIX24_DOMAIN", "online-kassa.bitrix24.ru"))
    parser.add_argument("--kpi-config", default=None, help="Путь к JSON с порогами/весами/паттернами оценки")
    parser.add_argument("--kpi-config-compare", default=None, help="Второй KPI JSON для сравнения в этом же отчёте")
    parser.add_argument("--force-attach", action="store_true", help="Всегда делать attachtranscription, игнорируя локальный state_cache")
    parser.add_argument("--no-reuse-transcripts", action="store_true", help="Не использовать ранее сохранённые расшифровки; заново скачивать аудио и отправлять в Bit.Newton")
    parser.add_argument("--retry-errors-from", default=None, help="JSON отчета, из которого нужно повторить только строки с ошибками")
    parser.add_argument("--reevaluate-from", default=None, help="JSON отчета, который нужно переоценить без скачивания аудио и Bit.Newton")
    parser.add_argument("--max-calls-per-deal", type=int, default=0, help="Ограничить количество звонков для анализа по каждой сделке; 0 = все")
    parser.add_argument("--include-call-center", action="store_true", help="Не исключать звонки операторов Call-центра из анализа")
    parser.add_argument("--fetch-bitrix-card-transcript", action="store_true", help="Пробовать читать расшифровку из карточки звонка Bitrix через UI и сопоставлять с Bit.Newton")
    parser.add_argument("--cleanup-output-days", type=int, default=30, help="Автоудаление отчетов, расшифровок и аудио старше N дней; 0 отключает")
    parser.add_argument("--cleanup-chrome-tmp-days", type=int, default=7, help="Удалять старые reports/chrome_profile_tmp_* (дней хранения)")
    return parser


def deal_url_from_id(domain: str, deal_id: str) -> str:
    domain = (domain or "").strip().replace("https://", "").replace("http://", "").strip("/")
    return f"https://{domain}/crm/deal/details/{deal_id}/"


def safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def fetch_deals_by_filter(api: Bitrix24API, flt: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
    deals: List[Dict[str, Any]] = []
    start: Optional[int] = 0
    page_size = 50
    max_items = max(0, int(limit or 0))
    if max_items <= 0:
        return deals

    while start is not None and len(deals) < max_items:
        res = api.call(
            "crm.deal.list",
            {
                "filter": flt,
                "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STAGE_ID", "DATE_CREATE"],
                "order": {"ID": "DESC"},
                "start": start,
            },
        )
        chunk = res.get("result", []) or []
        if not chunk:
            break

        remaining = max_items - len(deals)
        deals.extend(chunk[:remaining])
        if len(deals) >= max_items:
            break

        next_start = res.get("next")
        if next_start is not None:
            start = safe_int(next_start)
        else:
            total = safe_int(res.get("total"))
            start = start + page_size
            if total is None or start >= total:
                start = None

    return deals


def normalize_deal_filter_dates(flt: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(flt or {})
    date_to = out.pop("<=DATE_CREATE", None)
    if isinstance(date_to, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date_to.strip()):
        next_day = datetime.strptime(date_to.strip(), "%Y-%m-%d") + timedelta(days=1)
        out["<DATE_CREATE"] = next_day.date().isoformat()
    elif date_to is not None:
        out["<=DATE_CREATE"] = date_to
    return out


def deal_get(api: Bitrix24API, deal_id: str) -> Dict[str, Any]:
    return api.call("crm.deal.get", {"id": int(deal_id)}).get("result", {}) or {}


def stage_entity_id_from_stage(stage_id: str) -> str:
    stage_id = str(stage_id or "")
    m = re.match(r"^C(\d+):", stage_id)
    if m:
        return f"DEAL_STAGE_{m.group(1)}"
    return "DEAL_STAGE"


def fetch_stage_name_map(api: Bitrix24API, stage_ids: List[str]) -> Dict[str, str]:
    out = dict(DEFAULT_STAGE_NAMES)
    entities = sorted({stage_entity_id_from_stage(s) for s in stage_ids if s})
    for entity in entities:
        try:
            res = api.call("crm.status.list", {"filter": {"ENTITY_ID": entity}, "order": {"SORT": "ASC"}})
            for row in res.get("result") or []:
                sid = str(row.get("STATUS_ID") or "").strip()
                name = str(row.get("NAME") or "").strip()
                if sid and name:
                    out[sid] = name
        except Exception:
            continue
    return out



def _minutes_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if not a or not b:
        return None
    try:
        return round(max(0.0, (b - a).total_seconds() / 60.0), 2)
    except Exception:
        return None


def _minutes_since(dt: Optional[datetime]) -> Optional[float]:
    if not dt:
        return None
    try:
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return round(max(0.0, (now - dt).total_seconds() / 60.0), 2)
    except Exception:
        return None



def _stage_history_items_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = data.get("result")
    if isinstance(result, dict):
        items = result.get("items") or []
    else:
        items = result or []
    return [item for item in items if isinstance(item, dict)]


def _stage_history_next_start(data: Dict[str, Any], current_start: int, items_count: int) -> Optional[int]:
    result = data.get("result")
    next_value = data.get("next")
    if next_value is None and isinstance(result, dict):
        next_value = result.get("next")
    if next_value is not None:
        return safe_int(next_value)

    total = safe_int(data.get("total") or (result.get("total") if isinstance(result, dict) else None))
    if total is not None and current_start + items_count < total:
        return current_start + max(1, items_count)
    return None


def fetch_stage_history_by_deals(api: Bitrix24API, deal_ids: List[str], chunk_size: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {str(deal_id): [] for deal_id in deal_ids if deal_id}
    clean_ids = [int(d) for d in dict.fromkeys(str(deal_id) for deal_id in deal_ids if str(deal_id).isdigit())]
    for chunk_start in range(0, len(clean_ids), max(1, chunk_size)):
        chunk = clean_ids[chunk_start : chunk_start + max(1, chunk_size)]
        start: Optional[int] = 0
        while start is not None:
            params: Dict[str, Any] = {
                "entityTypeId": 2,
                "filter": {"OWNER_ID": chunk},
                "order": {"OWNER_ID": "ASC", "ID": "ASC"},
                "start": start,
            }
            data = api.call("crm.stagehistory.list", params)
            items = _stage_history_items_from_response(data)
            for item in items:
                owner_id = str(item.get("OWNER_ID") or "").strip()
                if owner_id:
                    out.setdefault(owner_id, []).append(item)
            start = _stage_history_next_start(data, int(start or 0), len(items))
            if start is not None:
                time.sleep(0.1)
    return out


def summarize_stage_history(
    items: List[Dict[str, Any]],
    stage_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    ranks = stage_order_map(stage_map)
    sorted_items = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda item: (str(item.get("CREATED_TIME") or ""), safe_int(item.get("ID")) or 0),
    )
    normalized: List[Dict[str, Any]] = []
    return_count = 0
    reached_final = False
    previous_rank: Optional[int] = None

    for index, item in enumerate(sorted_items):
        stage_id = str(item.get("STAGE_ID") or "").strip()
        created_at = parse_dt(item.get("CREATED_TIME"))
        next_dt = parse_dt(sorted_items[index + 1].get("CREATED_TIME")) if index + 1 < len(sorted_items) else None
        duration_minutes = _minutes_between(created_at, next_dt)
        rank = ranks.get(stage_id)
        if previous_rank is not None and rank is not None and rank < previous_rank:
            return_count += 1
        if rank is not None:
            previous_rank = rank
        semantic = str(item.get("STAGE_SEMANTIC_ID") or "").upper()
        if semantic in {"S", "F"} or stage_id.endswith(":WON") or stage_id.endswith(":LOSE") or stage_id in {"WON", "LOSE"}:
            reached_final = True
        normalized.append(
            {
                "stage_history_event_id": item.get("ID"),
                "stage_history_event_type": stage_history_type_label(item.get("TYPE_ID")),
                "stage_history_created_at": item.get("CREATED_TIME"),
                "stage_id": stage_id,
                "stage_name": stage_display_name(stage_id, stage_map=stage_map),
                "stage_order": rank,
                "stage_duration_minutes": duration_minutes,
                "stage_duration_hours": round(duration_minutes / 60.0, 2) if duration_minutes is not None else None,
                "stage_is_current": index == len(sorted_items) - 1,
            }
        )

    current = normalized[-1] if normalized else {}
    current_stage_id = current.get("stage_id") if current else None
    stage_warning_minutes, stage_critical_minutes = stage_duration_thresholds(current_stage_id)
    current_age_minutes = _minutes_since(parse_dt(current.get("stage_history_created_at"))) if current else None
    current_age_status = threshold_status(current_age_minutes, stage_warning_minutes, stage_critical_minutes)
    first_dt = parse_dt(normalized[0].get("stage_history_created_at")) if normalized else None
    last_dt = parse_dt(normalized[-1].get("stage_history_created_at")) if normalized else None
    if reached_final:
        total_work_minutes = _minutes_between(first_dt, last_dt)
    else:
        total_work_minutes = _minutes_since(first_dt)
    total_work_status = threshold_status(
        total_work_minutes,
        DEAL_TOTAL_WORK_WARNING_MINUTES,
        DEAL_TOTAL_WORK_CRITICAL_MINUTES,
    )
    if reached_final:
        current_age_status = "Финал"
    path_names = [str(item.get("stage_name") or item.get("stage_id") or "").strip() for item in normalized]
    compact_path: List[str] = []
    for name in path_names:
        if name and (not compact_path or compact_path[-1] != name):
            compact_path.append(name)

    if not normalized:
        risk = "Нет истории"
        recommendation = "История перемещения по стадиям не найдена. Проверьте права вебхука и корректность выборки."
    elif reached_final:
        risk = "Финал"
        recommendation = "Сделка достигла финальной стадии. Для анализа важно сопоставить итог со звонками и причиной результата."
    elif current_age_status == "Тревога":
        risk = "Тревога"
        recommendation = (
            f"Сделка находится на текущей стадии дольше критического порога "
            f"({_format_minutes_for_threshold(stage_critical_minutes)}). Нужен следующий шаг или актуализация стадии."
        )
    elif total_work_status == "Тревога":
        risk = "Тревога по сроку сделки"
        recommendation = (
            f"Общее время сделки в работе выше критического порога "
            f"({_format_minutes_for_threshold(DEAL_TOTAL_WORK_CRITICAL_MINUTES)}). Проверьте причину задержки по воронке."
        )
    elif current_age_status == "Предупреждение":
        risk = "Предупреждение"
        recommendation = (
            f"Сделка приближается к критическому сроку на текущей стадии. "
            f"Предупреждение после {_format_minutes_for_threshold(stage_warning_minutes)}, "
            f"тревога после {_format_minutes_for_threshold(stage_critical_minutes)}."
        )
    elif return_count > 0:
        risk = "Возвраты"
        recommendation = "Есть возвраты на предыдущие стадии. Проверьте, не переводится ли сделка вперед без готовности клиента."
    elif len(normalized) <= 1:
        risk = "Нет продвижения"
        recommendation = "Сделка пока не двигалась по воронке. Проверьте, есть ли звонок, выявленная потребность и запланированный следующий шаг."
    else:
        risk = "OK"
        recommendation = "Движение по стадиям выглядит рабочим. Сопоставьте переходы с качеством звонков и фиксацией следующего шага."

    return {
        "stage_history_items": normalized,
        "stage_history_count": len(normalized),
        "stage_history_path": " → ".join(compact_path),
        "stage_last_change_at": current.get("stage_history_created_at"),
        "stage_current_age_minutes": current_age_minutes,
        "stage_current_age_days": round(current_age_minutes / 1440.0, 2) if current_age_minutes is not None else None,
        "stage_warning_threshold": _format_minutes_for_threshold(stage_warning_minutes),
        "stage_critical_threshold": _format_minutes_for_threshold(stage_critical_minutes),
        "stage_current_age_status": current_age_status,
        "deal_total_work_minutes": total_work_minutes,
        "deal_total_work_days": round(total_work_minutes / 1440.0, 2) if total_work_minutes is not None else None,
        "deal_total_work_warning_threshold": _format_minutes_for_threshold(DEAL_TOTAL_WORK_WARNING_MINUTES),
        "deal_total_work_critical_threshold": _format_minutes_for_threshold(DEAL_TOTAL_WORK_CRITICAL_MINUTES),
        "deal_total_work_status": total_work_status,
        "stage_return_count": return_count,
        "stage_reached_final": reached_final,
        "stage_movement_risk": risk,
        "stage_movement_recommendation": recommendation,
    }


def attach_stage_history_metrics(
    rows: List[Dict[str, Any]],
    stage_history_by_deal: Dict[str, List[Dict[str, Any]]],
    stage_map: Optional[Dict[str, str]] = None,
) -> None:
    for row in rows:
        deal_id = deal_id_from_report_row(row)
        if not deal_id:
            continue
        row.update(summarize_stage_history(stage_history_by_deal.get(str(deal_id), []), stage_map=stage_map))


def activity_get(api: Bitrix24API, activity_id: int) -> Dict[str, Any]:
    return api.call("crm.activity.get", {"id": int(activity_id)}).get("result", {}) or {}


def list_deal_call_activities(api: Bitrix24API, deal_id: str) -> List[Dict[str, Any]]:
    res = api.call(
        "crm.activity.list",
        {
            "filter": {"OWNER_TYPE_ID": 2, "OWNER_ID": str(deal_id), "TYPE_ID": 2, "PROVIDER_ID": "VOXIMPLANT_CALL"},
            "select": ["ID", "CREATED", "START_TIME", "END_TIME", "SUBJECT", "ORIGIN_ID", "DIRECTION", "PROVIDER_ID", "PROVIDER_TYPE_ID", "AUTHOR_ID", "RESPONSIBLE_ID"],
            "order": {"START_TIME": "ASC"},
            "start": 0,
        },
    )
    return res.get("result", []) or []


def user_profile(api: Bitrix24API, user_id: Any, cache: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    uid = safe_int(user_id)
    if uid is None:
        return {}
    if uid in cache:
        return cache[uid]
    try:
        arr = api.call("user.get", {"ID": int(uid)}).get("result") or []
        cache[uid] = arr[0] if arr and isinstance(arr[0], dict) else {}
    except Exception:
        cache[uid] = {}
    return cache[uid]


def load_department_chain(api: Bitrix24API, department_ids: List[Any], cache: Dict[int, Dict[str, Any]]) -> None:
    pending = {int(x) for x in [safe_int(v) for v in department_ids] if x is not None and int(x) > 0 and int(x) not in cache}
    while pending:
        current = sorted(pending)
        pending.clear()
        try:
            rows = api.call("department.get", {"ID": current}).get("result") or []
        except Exception:
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            did = safe_int(row.get("ID"))
            if did is None:
                continue
            cache[did] = row
            parent = safe_int(row.get("PARENT"))
            if parent is not None and parent > 0 and parent not in cache:
                pending.add(parent)


def department_is_call_center(department_id: Any, cache: Dict[int, Dict[str, Any]]) -> bool:
    did = safe_int(department_id)
    seen: set[int] = set()
    while did is not None and did > 0 and did not in seen:
        seen.add(did)
        row = cache.get(did) or {}
        name = str(row.get("NAME") or "").lower()
        if "call центр" in name or "call center" in name or "колл" in name or "контакт центр" in name:
            return True
        did = safe_int(row.get("PARENT"))
    return False


def is_call_center_operator(
    api: Bitrix24API,
    user_id: Any,
    user_cache: Dict[int, Dict[str, Any]],
    department_cache: Dict[int, Dict[str, Any]],
) -> bool:
    user = user_profile(api, user_id, user_cache)
    if not user:
        return False
    position = str(user.get("WORK_POSITION") or "").lower()
    if "оператор" not in position and "operator" not in position:
        return False
    departments = user.get("UF_DEPARTMENT") or []
    if not isinstance(departments, list):
        departments = [departments]
    load_department_chain(api, departments, department_cache)
    return any(department_is_call_center(dept_id, department_cache) for dept_id in departments)


def split_call_center_operator_activities(
    api: Bitrix24API,
    activities: List[Dict[str, Any]],
    user_cache: Dict[int, Dict[str, Any]],
    department_cache: Dict[int, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for act in activities:
        responsible_id = act.get("RESPONSIBLE_ID") or act.get("AUTHOR_ID")
        if is_call_center_operator(api, responsible_id, user_cache, department_cache):
            skipped.append(act)
        else:
            kept.append(act)
    return kept, skipped


def user_name_map(api: Bitrix24API, user_ids: List[int]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for uid in sorted(set(user_ids)):
        try:
            arr = api.call("user.get", {"ID": int(uid)}).get("result") or []
            if arr and isinstance(arr[0], dict):
                u = arr[0]
                out[int(uid)] = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip() or str(uid)
        except Exception:
            out[int(uid)] = str(uid)
    return out


def fetch_timeline_comments(api: Bitrix24API, deal_id: str) -> List[str]:
    try:
        res = api.call("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": int(deal_id)}})
        rows = res.get("result", []) or []
        comments: List[str] = []
        for r in rows:
            txt = str((r or {}).get("COMMENT") or "").strip()
            if txt:
                comments.append(txt)
        return comments
    except Exception:
        return []


def parse_dt(raw: Any) -> Optional[datetime]:
    try:
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def guess_duration_sec(act: Dict[str, Any]) -> int:
    try:
        st = act.get("START_TIME")
        en = act.get("END_TIME")
        if st and en:
            dt1 = datetime.fromisoformat(str(st).replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(str(en).replace("Z", "+00:00"))
            sec = int(max(1.0, (dt2 - dt1).total_seconds()))
            return sec
    except Exception:
        pass
    return 60


def guess_duration_minutes(act: Dict[str, Any]) -> float:
    return round(guess_duration_sec(act) / 60.0, 2)


def reaction_speed_label(first_delay_min: Optional[float]) -> str:
    if first_delay_min is None:
        return "Нет звонка менеджера"
    if first_delay_min <= 15:
        return "Быстрая реакция"
    if first_delay_min <= 30:
        return "В срок"
    if first_delay_min <= 60:
        return "Поздно"
    return "Критически поздно"


def compute_discipline_metrics(deal: Dict[str, Any], calls: List[Dict[str, Any]], kpi: Dict[str, Any]) -> Dict[str, Any]:
    sla_cfg = kpi.get("sla", {})
    first_response_sla = float(sla_cfg.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    created = parse_dt(deal.get("DATE_CREATE"))
    call_times = [parse_dt(c.get("START_TIME")) for c in calls]
    call_times = [t for t in call_times if t is not None]
    call_times.sort()

    first_delay_h = None
    first_delay_min = None
    if created and call_times:
        first_delay_h = round(max(0.0, (call_times[0] - created).total_seconds() / 3600.0), 2)
        first_delay_min = round(max(0.0, (call_times[0] - created).total_seconds() / 60.0), 1)

    first_sla_min = round(first_response_sla * 60.0, 1)
    first_ok = first_delay_h is not None and first_delay_h <= first_response_sla

    return {
        "calls_count": len(call_times),
        "first_response_hours": first_delay_h,
        "first_response_minutes": first_delay_min,
        "first_response_sla_minutes": first_sla_min,
        "first_response_sla_ok": first_ok,
        "reaction_speed_label": reaction_speed_label(first_delay_min),
        "first_response_explanation": (
            f"Скорость реакции — сколько минут прошло от создания сделки до первого звонка менеджера. "
            f"Единая норма KPI: до 30 мин.; факт: {first_delay_min:g} мин."
            if first_delay_min is not None
            else "Скорость реакции — время от создания сделки до первого звонка менеджера. Единая норма KPI: до 30 мин.; звонков менеджера нет."
        ),
    }


def compute_deal_quality(deal: Dict[str, Any], comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    w = kpi.get("deal_quality_weights", {})
    has_contact = bool(deal.get("CONTACT_ID") or deal.get("COMPANY_ID"))
    has_amount = bool(str(deal.get("OPPORTUNITY") or "").strip() not in {"", "0", "0.00"})
    has_title = bool(str(deal.get("TITLE") or "").strip())
    has_next_step = bool(comments)
    score = 0
    score += int(w.get("has_contact", 25)) if has_contact else 0
    score += int(w.get("has_amount", 25)) if has_amount else 0
    score += int(w.get("has_title", 25)) if has_title else 0
    score += int(w.get("has_comments", 25)) if has_next_step else 0
    details = (
        f"Контакт/компания: {'да' if has_contact else 'нет'} ({int(w.get('has_contact', 25))} баллов); "
        f"сумма: {'да' if has_amount else 'нет'} ({int(w.get('has_amount', 25))} баллов); "
        f"название сделки: {'да' if has_title else 'нет'} ({int(w.get('has_title', 25))} баллов); "
        f"комментарии или следующий шаг в CRM: {'да' if has_next_step else 'нет'} ({int(w.get('has_comments', 25))} баллов)."
    )
    return {
        "deal_quality_score": score,
        "deal_quality_details": details,
        "has_contact": has_contact,
        "has_amount": has_amount,
        "has_title": has_title,
        "has_comments": has_next_step,
    }


def _match_any(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        try:
            if re.search(p, text):
                return True
        except re.error:
            continue
    return False



def crm_call_alignment(deal: Dict[str, Any], text: str, comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    w = kpi.get("alignment_weights", {})
    t = (text or "").lower()
    title_words = [w for w in re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", str(deal.get("TITLE") or "").lower())[:6]]
    title_hits = sum(1 for w in title_words if w in t)
    amount = str(deal.get("OPPORTUNITY") or "").split(".")[0]
    amount_mentioned = bool(amount and amount != "0" and amount in t)
    comments_text = " ".join(comments).lower()
    next_step_re = r"\b(перезвон\w*|встреч\w*|созвон\w*|отправ\w*|вышл\w*|уточн\w*|согласу\w*|кп|договор\w*)\b"
    next_step_synced = bool(re.search(next_step_re, t) and re.search(next_step_re, comments_text))
    amount_weight = int(w.get("amount_mentioned", 30))
    next_step_weight = int(w.get("next_step_synced", 40))
    raw_score = (amount_weight if amount_mentioned else 0) + (next_step_weight if next_step_synced else 0)
    total_weight = max(1, amount_weight + next_step_weight)
    align_score = round(raw_score * 100.0 / total_weight, 2)
    next_step_details = (
        "Да: следующий шаг звучит в разговоре и зафиксирован в комментариях/таймлайне CRM."
        if next_step_synced
        else "Нет: следующий шаг либо не прозвучал в разговоре, либо не зафиксирован в CRM. Это мешает контролировать дальнейшее действие по клиенту."
    )
    details = (
        "Связь звонка с CRM показывает, совпадает ли содержание разговора с данными сделки: "
        f"сумма упомянута: {'да' if amount_mentioned else 'нет'}; "
        f"следующий шаг синхронизирован с CRM: {'да' if next_step_synced else 'нет'}. "
        "Совпадения с названием сделки больше не выводятся в отчет как отдельная метрика."
    )
    return {
        "alignment_score": align_score,
        "alignment_details": details,
        "title_mentions": title_hits,
        "amount_mentioned": amount_mentioned,
        "next_step_synced": next_step_synced,
        "next_step_synced_details": next_step_details,
    }



def analyze_transcript_improvements(text: str, row: Dict[str, Any]) -> Dict[str, Any]:
    raw = text or ""
    lower = raw.lower()
    objections: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    for label, pattern, suggestion in OBJECTION_RULES:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            fragment = _context(raw, match.start(), match.end())
            key = (label, fragment[:160])
            if key in seen:
                continue
            seen.add(key)
            after = lower[match.end() : match.end() + 420]
            handled = bool(HANDLING_RE.search(after))
            objections.append(
                {
                    "objection_type": label,
                    "objection_fragment": fragment,
                    "objection_status": "отработано" if handled else "не отработано",
                    "objection_recommendation": suggestion,
                    "handled": handled,
                }
            )

    improvement_items: List[str] = []
    if not row.get("has_greeting"):
        improvement_items.append("Нет явного приветствия и представления.")
    if not row.get("has_needs_discovery"):
        improvement_items.append("Слабо выявлены потребности: не видно уточняющих вопросов о задаче клиента.")
    if not row.get("has_next_step_phrase"):
        improvement_items.append("Не зафиксирован конкретный следующий шаг.")

    unhandled = [o for o in objections if not o["handled"]]
    if unhandled:
        improvement_items.append("Есть неотработанные возражения: " + "; ".join(o["objection_type"] for o in unhandled[:5]) + ".")
    elif objections:
        improvement_items.append("Возражения найдены и в целом отработаны, но стоит фиксировать следующий шаг после ответа.")

    marked_lines: List[str] = []
    for objection in objections:
        status = objection["objection_status"]
        marker = "ТРЕБУЕТ ОТРАБОТКИ" if status == "не отработано" else "ОТРАБОТАНО"
        marked_lines.append(
            f"[ВОЗРАЖЕНИЕ: {objection['objection_type']} | {marker}]\n"
            f"{objection['objection_fragment']}\n"
            f"[ВАРИАНТ ОТРАБОТКИ] {objection['objection_recommendation']}"
        )

    if not marked_lines and improvement_items:
        marked_lines.append("[МОМЕНТЫ ДЛЯ УЛУЧШЕНИЯ]\n" + "\n".join(f"- {x}" for x in improvement_items))

    transcript_marked = raw
    if marked_lines:
        transcript_marked = "\n\n".join(marked_lines) + "\n\n[ПОЛНАЯ РАСШИФРОВКА]\n" + raw

    recommendations = [o["objection_recommendation"] for o in unhandled]
    if not recommendations and objections:
        recommendations = ["После ответа на возражение обязательно закрепить следующий шаг: дата, действие, ответственный."]

    return {
        "objections_count": len(objections),
        "unhandled_objections_count": len(unhandled),
        "objections_handled": bool(objections and not unhandled),
        "objections_found": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']} ({o['objection_status']})" for o in objections
        ),
        "unhandled_objections": "\n".join(f"{o['objection_type']}: {o['objection_fragment']}" for o in unhandled),
        "objection_recommendations": "\n".join(dict.fromkeys(recommendations)),
        "improvement_moments": "\n".join(improvement_items),
        "transcript_marked": transcript_marked,
        "objection_rows": objections,
    }


def save_transcript_file(deal_id: str, activity_id: Any, task_id: str, text: str) -> Path:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_task = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(task_id or ""))[:36] or "no_task"
    safe_deal = re.sub(r"\D+", "", str(deal_id or "")) or "unknown_deal"
    safe_activity = re.sub(r"\D+", "", str(activity_id or "")) or "unknown_activity"
    path = TRANSCRIPTS_DIR / f"deal{safe_deal}_activity{safe_activity}_{safe_task}.txt"
    path.write_text(text or "", encoding="utf-8")
    return path


def find_latest_transcript_file(deal_id: Any, activity_id: Any) -> Optional[Path]:
    safe_deal = re.sub(r"\D+", "", str(deal_id or ""))
    safe_activity = re.sub(r"\D+", "", str(activity_id or ""))
    if not safe_deal or not safe_activity or not TRANSCRIPTS_DIR.exists():
        return None
    pattern = f"deal{safe_deal}_activity{safe_activity}_*.txt"
    files = sorted(TRANSCRIPTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[0] if files else None


def load_cached_transcript(
    state_cache: Dict[str, Any],
    call_id: str,
    deal_id: Any,
    activity_id: Any,
) -> Tuple[Optional[str], Optional[Path]]:
    candidates: List[Path] = []
    cached = state_cache.get(call_id)
    if isinstance(cached, dict):
        cached_path = cached.get("transcript_path")
        if cached_path:
            candidates.append(Path(str(cached_path)))
    latest = find_latest_transcript_file(deal_id, activity_id)
    if latest:
        candidates.append(latest)

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.stat().st_size > 0:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
                if text:
                    return text, path
        except Exception:
            continue
    return None, None


def finalize_transcript_analysis(
    row: Dict[str, Any],
    deal: Dict[str, Any],
    comments: List[Dict[str, Any]],
    bitnewton_text: str,
    bitrix_text: str,
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
) -> None:
    analysis_text = merged_transcript_text(bitnewton_text or "", bitrix_text or "")
    row["combined_transcript_text"] = analysis_text
    apply_scores(row, deal, comments, analysis_text, kpi, suffix="")
    if kpi_cmp is not None:
        apply_scores(row, deal, comments, analysis_text, kpi_cmp, suffix="_cmp")
        row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)
    row.update(analyze_transcript_improvements(analysis_text, row))
    call_conclusion, call_recommendations = call_quality_conclusion(row)
    row["call_quality_conclusion"] = call_conclusion
    row["recommendations"] = call_recommendations
    row["conversation_meaning"] = conversation_meaning(analysis_text, row)





def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate_kpi_config(kpi: Dict[str, Any]) -> None:
    if not isinstance(kpi, dict):
        raise RuntimeError("KPI config: должен быть объектом")
    prof = kpi.get("profile")
    if not isinstance(prof, dict) or not str(prof.get("name") or "").strip():
        raise RuntimeError("KPI config: profile.name обязателен (строка)")
    sla = kpi.get("sla")
    if not isinstance(sla, dict):
        raise RuntimeError("KPI config: sla должен быть объектом")
    fr = float(sla.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    mg = float(sla.get("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS))
    if fr <= 0 or mg <= 0:
        raise RuntimeError("KPI config: sla значения должны быть > 0")
    w = kpi.get("weights")
    if not isinstance(w, dict):
        raise RuntimeError("KPI config: weights должен быть объектом")
    overall = w.get("overall")
    if not isinstance(overall, dict):
        raise RuntimeError("KPI config: weights.overall должен быть объектом")
    s = float(overall.get("call_quality", 0)) + float(overall.get("discipline", 0)) + float(overall.get("crm_alignment", 0))
    if not (0.95 <= s <= 1.05):
        raise RuntimeError(f"KPI config: weights.overall должны суммироваться примерно в 1.0 (сейчас {s})")
    patterns = kpi.get("patterns")
    if patterns is not None:
        if not isinstance(patterns, dict):
            raise RuntimeError("KPI config: patterns должен быть объектом")
        for key, arr in patterns.items():
            if not isinstance(arr, list):
                raise RuntimeError(f"KPI config: patterns.{key} должен быть списком regex-строк")
            for p in arr:
                if not isinstance(p, str):
                    raise RuntimeError(f"KPI config: patterns.{key} содержит не строку")


def enforce_reaction_kpi(kpi: Dict[str, Any]) -> Dict[str, Any]:
    """
    Единая итоговая оценка: разговор + ведение CRM. Скорость реакции не влияет на итог.
    """
    sla = kpi.setdefault("sla", {})
    if isinstance(sla, dict):
        sla["first_response_hours"] = FIRST_RESPONSE_SLA_HOURS
        sla.setdefault("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS)
    weights = kpi.setdefault("weights", {})
    if isinstance(weights, dict):
        weights["overall"] = {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50}
        weights["discipline_split"] = {"first_response": 1.0, "cadence": 0.0}
    return kpi


def load_kpi_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_KPI_CONFIG)
    if not path:
        cfg = enforce_reaction_kpi(cfg)
        validate_kpi_config(cfg)
        return cfg
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("--kpi-config должен содержать JSON-объект")
    merged = _deep_merge(cfg, raw)
    if isinstance(merged.get("profile"), dict):
        merged["profile"].setdefault("name", Path(path).name)
        merged["profile"].setdefault("version", "1")
    else:
        merged["profile"] = {"name": Path(path).name, "version": "1"}
    merged = enforce_reaction_kpi(merged)
    validate_kpi_config(merged)
    return merged


def _load_state_cache() -> Dict[str, Any]:
    try:
        if STATE_CACHE_PATH.exists():
            raw = json.loads(STATE_CACHE_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
    return {}


def _save_state_cache(cache: Dict[str, Any]) -> None:
    try:
        STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_report_json(path: str | Path) -> List[Dict[str, Any]]:
    report_path = Path(path)
    if not report_path.exists():
        raise SystemExit(f"Отчет не найден: {report_path}")
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"Ожидался JSON-список строк отчета: {report_path}")
    return [r for r in raw if isinstance(r, dict)]


def deal_id_from_report_row(row: Dict[str, Any]) -> Optional[str]:
    deal_id = row.get("deal_id")
    if deal_id:
        deal_str = str(deal_id).strip()
        if deal_str.isdigit():
            return deal_str
    url = str(row.get("deal_url") or "").strip()
    m = re.search(r"/crm/deal/details/(\d+)/?", url)
    return m.group(1) if m else None


def load_retry_scope(path: str | Path) -> Dict[str, Any]:
    rows = load_report_json(path)
    deal_ids: List[str] = []
    activity_ids_by_deal: Dict[str, set[int]] = {}
    full_deals: set[str] = set()
    errors = 0
    seen_deals: set[str] = set()

    for row in rows:
        if not row.get("error"):
            continue
        deal_id = deal_id_from_report_row(row)
        if not deal_id:
            continue
        errors += 1
        if deal_id not in seen_deals:
            seen_deals.add(deal_id)
            deal_ids.append(deal_id)
        activity_id = safe_int(row.get("activity_id"))
        if activity_id is None:
            full_deals.add(deal_id)
        else:
            activity_ids_by_deal.setdefault(deal_id, set()).add(activity_id)

    return {
        "deal_ids": deal_ids,
        "activity_ids_by_deal": activity_ids_by_deal,
        "full_deals": full_deals,
        "errors": errors,
        "source_rows": rows,
        "source_path": str(path),
    }


def _report_row_identity(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    return deal_id_from_report_row(row), safe_int(row.get("activity_id"))


def merge_retry_results(
    original_rows: List[Dict[str, Any]],
    retry_rows: List[Dict[str, Any]],
    retry_scope: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Повтор ошибок должен обновлять полный отчет, а не заменять его маленьким отчетом
    только по ошибочным строкам.
    """
    full_deals = set(str(x) for x in (retry_scope.get("full_deals") or set()))
    retry_activity_ids_by_deal = retry_scope.get("activity_ids_by_deal") or {}

    retry_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    retry_by_activity: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in retry_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            continue
        retry_by_deal.setdefault(deal_id, []).append(row)
        if activity_id is not None:
            retry_by_activity.setdefault((deal_id, activity_id), []).append(row)

    merged: List[Dict[str, Any]] = []
    inserted_full_deals: set[str] = set()
    inserted_activities: set[Tuple[str, int]] = set()
    inserted_fallback_deals: set[str] = set()

    for row in original_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue

        if deal_id in full_deals:
            if deal_id not in inserted_full_deals:
                replacements = retry_by_deal.get(deal_id)
                merged.extend(replacements if replacements else [row])
                inserted_full_deals.add(deal_id)
            continue

        target_activities = retry_activity_ids_by_deal.get(deal_id, set())
        if activity_id is not None and activity_id in target_activities:
            key = (deal_id, activity_id)
            if key not in inserted_activities:
                replacements = retry_by_activity.get(key)
                if replacements:
                    merged.extend(replacements)
                elif deal_id not in inserted_fallback_deals:
                    fallback = [r for r in retry_by_deal.get(deal_id, []) if safe_int(r.get("activity_id")) is None]
                    merged.extend(fallback if fallback else [row])
                    inserted_fallback_deals.add(deal_id)
                else:
                    merged.append(row)
                inserted_activities.add(key)
            continue

        merged.append(row)

    existing_object_ids = {id(row) for row in merged}
    for row in retry_rows:
        if id(row) in existing_object_ids:
            continue
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue
        if deal_id in full_deals and deal_id in inserted_full_deals:
            continue
        if activity_id is not None and (deal_id, activity_id) in inserted_activities:
            continue
        merged.append(row)

    return merged


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()


def cleanup_old_chrome_tmp_profiles(base_dir: Path, keep_days: int = 7) -> int:
    try:
        if keep_days <= 0:
            return 0
        now = time.time()
        removed = 0
        for p in base_dir.glob("chrome_profile_tmp_*"):
            try:
                age_days = (now - p.stat().st_mtime) / (3600 * 24)
                if age_days < keep_days:
                    continue
                for sub in sorted(p.rglob("*"), reverse=True):
                    try:
                        if sub.is_file() or sub.is_symlink():
                            sub.unlink(missing_ok=True)  # type: ignore[call-arg]
                        else:
                            sub.rmdir()
                    except Exception:
                        pass
                try:
                    p.rmdir()
                except Exception:
                    pass
                removed += 1
            except Exception:
                continue
        return removed
    except Exception:
        return 0


def cleanup_old_outputs(base_dir: Path, keep_days: int = 30, extra_audio_dirs: Optional[List[Path]] = None) -> Dict[str, int]:
    counts = {"reports": 0, "audio": 0, "transcripts": 0, "total": 0}
    try:
        if keep_days <= 0:
            return counts
        base_dir = Path(base_dir)
        cutoff = time.time() - (float(keep_days) * 24 * 3600)

        def remove_file(path: Path, bucket: str) -> None:
            try:
                if not path.exists() or path.is_dir():
                    return
                if path.stat().st_mtime >= cutoff:
                    return
                path.unlink(missing_ok=True)  # type: ignore[call-arg]
                counts[bucket] = counts.get(bucket, 0) + 1
                counts["total"] += 1
            except Exception:
                return

        for pattern in ("bitnewton_sync_report_*.json", "bitnewton_sync_report_*.xlsx"):
            for path in base_dir.glob(pattern):
                remove_file(path, "reports")

        cleanup_dirs: List[Tuple[Path, str]] = [
            (base_dir / "audio", "audio"),
            (base_dir / "audio_ui", "audio"),
            (base_dir / "transcripts", "transcripts"),
        ]
        for extra in extra_audio_dirs or []:
            extra_path = Path(extra)
            if extra_path not in [p for p, _ in cleanup_dirs]:
                cleanup_dirs.append((extra_path, "audio"))

        for folder, bucket in cleanup_dirs:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                remove_file(path, bucket)
            for path in sorted(folder.rglob("*"), reverse=True):
                try:
                    if path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                except Exception:
                    continue
        return counts
    except Exception:
        return counts


def apply_scores(row: Dict[str, Any], deal: Dict[str, Any], comments: List[str], text: str, kpi: Dict[str, Any], suffix: str = "") -> None:
    first_h = row.get("first_response_hours")
    first_m = row.get("first_response_minutes")
    sla_cfg = kpi.get("sla", {})
    first_response_sla = float(sla_cfg.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    if first_h is None and first_m is not None:
        first_h = float(first_m) / 60.0
    row[f"first_response_sla_ok{suffix}"] = (first_h is not None and float(first_h) <= first_response_sla)

    deal_q = compute_deal_quality(deal, comments, kpi)
    call_q = evaluate_call_text(text, kpi)
    align = crm_call_alignment(deal, text, comments, kpi)
    for k, v in deal_q.items():
        row[f"{k}{suffix}"] = v
    for k, v in call_q.items():
        row[f"{k}{suffix}"] = v
    for k, v in align.items():
        row[f"{k}{suffix}"] = v

    crm_q = evaluate_crm_checklist(row, suffix=suffix, include_stage=False)
    for k, v in crm_q.items():
        if suffix and k in {"crm_checklist_items"}:
            continue
        row[f"{k}{suffix}"] = v

    recalculate_overall_score(row, kpi, suffix=suffix)


def refresh_crm_scores_after_stage_metrics(rows: List[Dict[str, Any]], kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]] = None) -> None:
    for row in rows:
        crm_q = evaluate_crm_checklist(row, include_stage=True)
        row.update(crm_q)
        recalculate_overall_score(row, kpi, suffix="")
        if kpi_cmp is not None:
            row["crm_work_score_cmp"] = crm_q.get("crm_work_score")
            row["crm_checklist_percent_cmp"] = crm_q.get("crm_checklist_percent")
            recalculate_overall_score(row, kpi_cmp, suffix="_cmp")
            row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)


def recompute_existing_row(row: Dict[str, Any], kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = dict(row)
    r["kpi_profile"] = (kpi.get("profile") or {}).get("name")
    r["kpi_version"] = (kpi.get("profile") or {}).get("version")
    if kpi_cmp is not None:
        r["kpi_profile_cmp"] = (kpi_cmp.get("profile") or {}).get("name")
        r["kpi_version_cmp"] = (kpi_cmp.get("profile") or {}).get("version")

    text = str(r.get("combined_transcript_text") or r.get("transcript_text") or "").strip()
    if not text and r.get("transcript_path"):
        try:
            p = Path(str(r.get("transcript_path")))
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            text = ""
    bitrix_text = str(r.get("bitrix_card_transcript") or "").strip()
    analysis_text = merged_transcript_text(text, bitrix_text)
    r["combined_transcript_text"] = analysis_text
    if text and not r.get("transcript_text"):
        r["transcript_text"] = text

    if not analysis_text:
        r["call_quality_score"] = 0.0
        r["call_quality_details"] = "Качество разговора не рассчитано: нет сохраненной расшифровки."
        r.update(evaluate_crm_checklist(r, include_stage=True))
        recalculate_overall_score(r, kpi)
        return r

    for k, v in evaluate_call_text(analysis_text, kpi).items():
        r[k] = v

    r.update(evaluate_crm_checklist(r, include_stage=True))
    recalculate_overall_score(r, kpi)

    r.update(analyze_transcript_improvements(analysis_text, r))
    call_conclusion, call_recommendations = call_quality_conclusion(r)
    r["call_quality_conclusion"] = call_conclusion
    r["recommendations"] = call_recommendations
    r["conversation_meaning"] = conversation_meaning(analysis_text, r)

    if kpi_cmp is not None:
        tmp = recompute_existing_row({**r, "overall_score": None}, kpi_cmp, None)
        for key in ["call_quality_score", "deal_quality_score", "alignment_score", "crm_work_score", "overall_score"]:
            if key in tmp:
                r[f"{key}_cmp"] = tmp.get(key)
        r["overall_score_delta"] = round(float(r.get("overall_score_cmp") or 0.0) - float(r.get("overall_score") or 0.0), 2)

    return r


def reevaluate_report(args: argparse.Namespace, kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]]) -> Tuple[int, Path, Path]:
    rows = load_report_json(args.reevaluate_from)
    recalculated = [recompute_existing_row(row, kpi, kpi_cmp) for row in rows]
    manager_summary = build_manager_summary(recalculated)
    manager_summary_cmp = build_manager_summary(recalculated, score_key="overall_score_cmp") if kpi_cmp is not None else None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_out = REPORTS_DIR / f"bitnewton_reevaluated_report_{ts}.json"
    json_out.write_text(json.dumps(prepare_report_rows(recalculated), ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(recalculated, manager_summary, manager_summary_cmp=manager_summary_cmp)
    publish_latest_report(json_out, xlsx_out)
    print(f"[OK] Переоценено строк без повторной расшифровки: {len(recalculated)}")
    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    print(f"ИТОГО: OK={len(recalculated)} ERR=0")
    return len(recalculated), json_out, xlsx_out


def attach_transcription_to_bitrix(api: Bitrix24API, call_id: str, transcript_text: str, duration: int) -> Dict[str, Any]:
    text = (transcript_text or "").strip()
    if not text:
        raise RuntimeError("Пустая расшифровка (transcript_text)")
    duration = int(duration or 60)
    duration = max(1, duration)
    msg = {"SIDE": "User", "MESSAGE": text, "START_TIME": 0, "STOP_TIME": duration}

    variants = [str(call_id or "").strip()]
    if variants[0].startswith("VI_"):
        variants.append(variants[0][3:])

    seen = set()
    errors: List[str] = []
    for cid in variants:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            res = api.call("telephony.call.attachTranscription", {"CALL_ID": cid, "MESSAGES": [msg]}).get("result", {}) or {}
            return {"call_id_used": cid, "result": res}
        except Exception as e:
            errors.append(f"{cid}: {e}")

    raise RuntimeError("Не удалось прикрепить расшифровку в Bitrix: " + " | ".join(errors))


def resolve_deal_ids(args: argparse.Namespace, api: Bitrix24API) -> List[str]:
    if args.mode == "single":
        if args.deal_id:
            deal_id = str(args.deal_id).strip()
            if not deal_id.isdigit():
                raise SystemExit(f"--deal-id должен быть числом. Сейчас: {deal_id!r}")
            return [deal_id]
        if args.deal_url:
            u = str(args.deal_url).strip()
            # Пытаемся вытащить числовой ID из URL вида .../crm/deal/details/83735/
            m = re.search(r"/crm/deal/details/(\d+)/?", u)
            if m:
                return [m.group(1)]
            # fallback: последний сегмент
            tail = u.rstrip("/").split("/")[-1]
            if tail.isdigit():
                return [tail]
            raise SystemExit(
                "Не смог распознать ID сделки из --deal-url. "
                "Ожидаю ссылку вида https://<domain>/crm/deal/details/12345/ "
                f"(получил: {u!r})."
            )
        raise SystemExit("Для --mode single нужен --deal-id или --deal-url")

    if not args.mode:
        raise SystemExit("Нужен --mode single/filter, --retry-errors-from или --reevaluate-from")

    if not args.filter_json:
        raise SystemExit("Для --mode filter нужен --filter-json")
    flt = normalize_deal_filter_dates(json.loads(Path(args.filter_json).read_text(encoding="utf-8")))
    deals = fetch_deals_by_filter(api, flt, limit=args.limit)
    print(f"Найдено сделок: {len(deals)}")
    return [str(d.get("ID")) for d in deals if d.get("ID")]


def run_sync(args: argparse.Namespace) -> Tuple[int, Path, Path]:
    kpi = load_kpi_config(args.kpi_config)
    kpi_cmp = load_kpi_config(args.kpi_config_compare) if args.kpi_config_compare else None

    if args.reevaluate_from:
        return reevaluate_report(args, kpi, kpi_cmp)

    api = Bitrix24API()
    if not api.test_connection():
        raise SystemExit(1)

    if args.use_bitnewton or args.bitnewton_flow:
        asr = env_bitnewton_asr()
        if not asr:
            raise SystemExit("Не задан BITNEWTON_TOKEN в .env")
    else:
        raise SystemExit("Нужен флаг --use-bitnewton (или --bitnewton-flow)")

    retry_scope = load_retry_scope(args.retry_errors_from) if args.retry_errors_from else None
    if retry_scope is not None:
        deal_ids = list(retry_scope.get("deal_ids") or [])
        if not deal_ids:
            raise SystemExit("В выбранном отчете нет строк с ошибками для повторного запуска")
        print(
            f"[RETRY] Повторяю только ошибки из отчета: "
            f"строк с ошибками={retry_scope.get('errors', 0)}, сделок={len(deal_ids)}",
            flush=True,
        )
    else:
        deal_ids = resolve_deal_ids(args, api)
    results: List[Dict[str, Any]] = []
    state_cache = _load_state_cache()

    audio_dir = REPORTS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ui_audio_dir = Path(args.ui_download_dir) if args.ui_download_dir else (REPORTS_DIR / "audio_ui")
    ui_audio_dir.mkdir(parents=True, exist_ok=True)
    audio_source_dirs = parse_audio_source_dirs(getattr(args, "audio_source_dir", []))
    audio_source_index = build_audio_source_index(audio_source_dirs)
    if audio_source_dirs:
        print(
            f"[AUDIO] Локальных аудиофайлов в индексе: {len(audio_source_index)}; "
            f"папки: {', '.join(str(p) for p in audio_source_dirs)}",
            flush=True,
        )
    cleanup_days = int(args.cleanup_output_days or 0)
    if cleanup_days > 0:
        removed = cleanup_old_outputs(REPORTS_DIR, keep_days=cleanup_days, extra_audio_dirs=[ui_audio_dir])
        if removed.get("total"):
            print(
                f"[OK] Автоочистка старше {cleanup_days} дней: "
                f"отчеты={removed.get('reports', 0)}, "
                f"аудио={removed.get('audio', 0)}, "
                f"расшифровки={removed.get('transcripts', 0)}",
                flush=True,
            )

    ok = 0
    err = 0
    ui_browser_session = None
    user_cache: Dict[int, Dict[str, Any]] = {}
    department_cache: Dict[int, Dict[str, Any]] = {}
    for di, deal_id in enumerate(deal_ids, 1):
        print(f"\nDEAL {di}/{len(deal_ids)}: {deal_url_from_id(args.domain, deal_id)}")
        acts_raw = list_deal_call_activities(api, deal_id)
        if args.include_call_center:
            acts = acts_raw
            call_center_acts: List[Dict[str, Any]] = []
        else:
            acts, call_center_acts = split_call_center_operator_activities(api, acts_raw, user_cache, department_cache)
        print(f"Звонков (crm.activity): {len(acts_raw)}")
        if call_center_acts:
            print(f"[SKIP] Звонков операторов Call-центра: {len(call_center_acts)}; к анализу: {len(acts)}", flush=True)

        if retry_scope is not None:
            retry_ids = retry_scope.get("activity_ids_by_deal", {}).get(str(deal_id), set())
            full_deal_retry = str(deal_id) in retry_scope.get("full_deals", set())
            if full_deal_retry:
                print("[RETRY] Ошибка была на уровне сделки, перепроверяю все звонки этой сделки", flush=True)
            else:
                before_retry = len(acts)
                acts = [a for a in acts if safe_int(a.get("ID")) in retry_ids]
                print(f"[RETRY] К повторной обработке звонков: {len(acts)} из {before_retry}", flush=True)

        max_calls_per_deal = max(0, int(getattr(args, "max_calls_per_deal", 0) or 0))
        if max_calls_per_deal and len(acts) > max_calls_per_deal:
            skipped_by_limit = len(acts) - max_calls_per_deal
            acts = acts[-max_calls_per_deal:]
            print(f"[FAST] Ограничение звонков по сделке: анализирую последние {len(acts)}, пропущено {skipped_by_limit}", flush=True)
        deal = deal_get(api, deal_id)
        comments = fetch_timeline_comments(api, deal_id)
        discipline = compute_discipline_metrics(deal, acts, kpi)
        deal_quality = compute_deal_quality(deal, comments, kpi)
        manager_id = safe_int(deal.get("ASSIGNED_BY_ID"))

        if not acts:
            row: Dict[str, Any] = {
                "deal_id": deal_id,
                "deal_url": deal_url_from_id(args.domain, deal_id),
                "stage_id": deal.get("STAGE_ID"),
                "manager_id": manager_id,
                "manager_name": None,
                "kpi_profile": (kpi.get("profile") or {}).get("name"),
                "kpi_version": (kpi.get("profile") or {}).get("version"),
                "kpi_profile_cmp": (kpi_cmp.get("profile") or {}).get("name") if kpi_cmp else None,
                "kpi_version_cmp": (kpi_cmp.get("profile") or {}).get("version") if kpi_cmp else None,
                "activity_id": None,
                "origin_id": None,
                "subject": "Звонков не найдено",
                "start_time": None,
                "end_time": None,
                "duration_minutes": None,
                "disk_file_id": None,
                "download_url": None,
                "audio_path": None,
                "bitnewton_task_id": None,
                "attach_result": None,
                "error": "По сделке не найдено звонков менеджера после исключения Call-центра" if call_center_acts else "По сделке не найдено звонков",
                "no_calls": True,
                "ignored_call_center_calls": len(call_center_acts),
            }
            row.update(discipline)
            row.update(deal_quality)
            apply_scores(row, deal, comments, "", kpi, suffix="")
            if kpi_cmp is not None:
                apply_scores(row, deal, comments, "", kpi_cmp, suffix="_cmp")
                row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)
            row["call_quality_conclusion"] = "Оценить разговор невозможно: по сделке не найдено звонков."
            row["recommendations"] = "Проверить, был ли контакт с клиентом вне телефонии Bitrix. Если звонка не было — запланировать касание и зафиксировать следующий шаг в CRM."
            results.append(row)
            err += 1
            print(f"[NO CALLS] OK={ok} ERR={err}", flush=True)
            continue

        for ai, act in enumerate(acts, 1):
            row: Dict[str, Any] = {
                "deal_id": deal_id,
                "deal_url": deal_url_from_id(args.domain, deal_id),
                "stage_id": deal.get("STAGE_ID"),
                "manager_id": manager_id,
                "manager_name": None,
                "kpi_profile": (kpi.get("profile") or {}).get("name"),
                "kpi_version": (kpi.get("profile") or {}).get("version"),
                "kpi_profile_cmp": (kpi_cmp.get("profile") or {}).get("name") if kpi_cmp else None,
                "kpi_version_cmp": (kpi_cmp.get("profile") or {}).get("version") if kpi_cmp else None,
                "activity_id": act.get("ID"),
                "origin_id": act.get("ORIGIN_ID"),
                "subject": act.get("SUBJECT"),
                "start_time": act.get("START_TIME"),
                "end_time": act.get("END_TIME"),
                "duration_minutes": guess_duration_minutes(act),
                "disk_file_id": None,
                "download_url": None,
                "audio_path": None,
                "bitnewton_task_id": None,
                "attach_result": None,
                "error": None,
                "ignored_call_center_calls": len(call_center_acts),
            }
            row.update(discipline)
            row.update(deal_quality)

            try:
                call_id = str(row["origin_id"] or "")
                if not call_id:
                    raise RuntimeError("Нет ORIGIN_ID (CALL_ID) для резолва записи")

                if not bool(getattr(args, "no_reuse_transcripts", False)):
                    cached_text, cached_path = load_cached_transcript(state_cache, call_id, deal_id, row.get("activity_id"))
                    if cached_text and cached_path:
                        row["bitnewton_task_id"] = "cache"
                        row["transcript_path"] = str(cached_path)
                        row["transcript_text"] = cached_text
                        row["transcript_excerpt"] = cached_text[:1200]
                        row["transcript_hash"] = _sha256_text(cached_text)
                        row["bitrix_card_transcript_status"] = "Не запрашивалась: использована сохранённая расшифровка"
                        finalize_transcript_analysis(row, deal, comments, cached_text, "", kpi, kpi_cmp)
                        if args.force_attach:
                            act_full = activity_get(api, int(act.get("ID"))) if act.get("ID") else act
                            attach = attach_transcription_to_bitrix(api, call_id=call_id, transcript_text=cached_text, duration=guess_duration_sec(act_full))
                            row["attach_result"] = attach
                        else:
                            row["attach_result"] = {"skipped": True, "reason": "cached_transcript_reused"}
                        state_cache[call_id] = {
                            "hash": row["transcript_hash"],
                            "transcript_path": str(cached_path),
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "deal_id": deal_id,
                            "activity_id": row.get("activity_id"),
                            "source": "cache",
                        }
                        _save_state_cache(state_cache)
                        ok += 1
                        print(f"[CACHE] Использую сохранённую расшифровку: activity_id={row.get('activity_id')}", flush=True)
                        continue

                rr = resolve_call_recording(api, call_id=call_id, activity_id=safe_int(act.get("ID")))
                row["disk_file_id"] = rr.disk_file_id
                row["recording_diagnostics"] = rr.diagnostics
                candidates = rr.candidates
                row["download_url"] = candidates[0] if candidates else None

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                local_source = find_local_audio_source(
                    audio_source_index,
                    deal_id=deal_id,
                    activity_id=act.get("ID"),
                    disk_file_id=row.get("disk_file_id"),
                    call_id=call_id,
                    disk_file_name=(rr.diagnostics or {}).get("disk_file_name"),
                )
                out_suffix = local_source.suffix if local_source else ".mp3"
                out_path = audio_dir / f"deal{deal_id}_act{act.get('ID')}_{row.get('disk_file_id')}_{ts}{out_suffix}"
                if local_source:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(local_source, out_path)
                    row["local_audio_source_used"] = True
                    row["local_audio_source_path"] = str(local_source)
                    print(f"[AUDIO] Использую локальный файл: activity_id={row.get('activity_id')} file={local_source}", flush=True)
                else:
                    row["local_audio_source_used"] = False
                    if not candidates:
                        raise RuntimeError("Не нашёл URL кандидаты для скачивания (resolver не смог), и локальный аудиофайл тоже не найден.")
                    rest_timeout_sec = max(5, int(getattr(args, "rest_timeout_sec", 20) or 20))
                    dl = download_best_effort(candidates=candidates, out_path=out_path, timeout_sec=rest_timeout_sec, retries=0)
                    if not dl.ok or not dl.path:
                        row["download_attempts"] = [a.__dict__ for a in dl.attempts]
                        if args.ui_download:
                            try:
                                from ui_audio_downloader import (
                                    UiBrowserSession,
                                )

                                ui_res = None
                                ui_errors: List[str] = []
                                mode = str(getattr(args, "ui_download_mode", "auto") or "auto")
                                browser = str(getattr(args, "ui_browser", "chrome"))
                                ui_timeout_sec = max(5, int(getattr(args, "ui_timeout_sec", 20) or 20))
                                browser_profile_directory = str(getattr(args, "browser_profile_directory", "Default") or "Default")
                                if ui_browser_session is None:
                                    ui_browser_session = UiBrowserSession(
                                        downloads_dir=ui_audio_dir,
                                        chrome_profile_dir=args.chrome_profile_dir,
                                        browser=browser,
                                        browser_profile_directory=browser_profile_directory,
                                    )

                                if mode in {"direct", "auto"}:
                                    for candidate in [html.unescape(c).strip() for c in candidates if isinstance(c, str) and c.startswith("http")]:
                                        print(f"[UI] Пробую ссылку активности через {browser}, таймаут {ui_timeout_sec} сек.: {candidate}", flush=True)
                                        ui_res = ui_browser_session.download_url(
                                            candidate,
                                            timeout_sec=ui_timeout_sec,
                                            referer_url=row["deal_url"],
                                        )
                                        if ui_res.ok and ui_res.path:
                                            break
                                        ui_errors.append(f"url={candidate}: {ui_res.error if ui_res else 'no result'}")

                                if (ui_res is None or not ui_res.ok) and mode in {"timeline", "auto"}:
                                    print(f"[UI] Пробую таймлайн сделки через {browser}, таймаут {ui_timeout_sec} сек.: activity_id={row.get('activity_id')}", flush=True)
                                    ui_res = ui_browser_session.download_call_from_deal_timeline(
                                        row["deal_url"],
                                        int(row.get("activity_id") or 0),
                                        timeout_sec=ui_timeout_sec,
                                    )
                                    if not ui_res.ok:
                                        ui_errors.append(f"timeline activity_id={row.get('activity_id')}: {ui_res.error}")

                                row["ui_download_errors"] = ui_errors
                                if ui_res is None or not ui_res.ok or not ui_res.path:
                                    raise RuntimeError("; ".join(ui_errors) or (ui_res.error if ui_res else "UI download failed"))
                                out_path.parent.mkdir(parents=True, exist_ok=True)
                                out_path.write_bytes(Path(ui_res.path).read_bytes())
                                row["ui_download_used"] = True
                                row["ui_download_path"] = str(ui_res.path)
                            except Exception as e:
                                raise RuntimeError(f"Не удалось скачать аудио (REST+UI): {dl.error}; UI: {e}")
                        else:
                            raise RuntimeError(f"Не удалось скачать аудио: {dl.error}")
                row["audio_path"] = str(out_path)
                row["audio_size_bytes"] = int(out_path.stat().st_size) if out_path.exists() else None
                bad = validate_audio_file(out_path)
                if bad:
                    raise RuntimeError(f"Скачанный файл не похож на аудио: {bad}")

                # ASR
                task = asr.start_transcribing(str(out_path), diarize=bool(args.diarize), remove_timestamps=True)
                row["bitnewton_task_id"] = task.task_id
                text = asr.wait_and_get_text(task.task_id, timeout_sec=1800)
                transcript_path = save_transcript_file(
                    deal_id=str(deal_id),
                    activity_id=row.get("activity_id"),
                    task_id=task.task_id,
                    text=text or "",
                )
                row["transcript_path"] = str(transcript_path)
                row["transcript_text"] = text or ""
                row["transcript_excerpt"] = (text or "")[:1200]

                bitrix_text = ""
                if args.fetch_bitrix_card_transcript and args.ui_download:
                    try:
                        from ui_audio_downloader import UiBrowserSession

                        browser = str(getattr(args, "ui_browser", "chrome"))
                        ui_timeout_sec = max(5, int(getattr(args, "ui_timeout_sec", 20) or 20))
                        browser_profile_directory = str(getattr(args, "browser_profile_directory", "Default") or "Default")
                        if ui_browser_session is None:
                            ui_browser_session = UiBrowserSession(
                                downloads_dir=ui_audio_dir,
                                chrome_profile_dir=args.chrome_profile_dir,
                                browser=browser,
                                browser_profile_directory=browser_profile_directory,
                            )
                        print(f"[UI] Пробую прочитать расшифровку из карточки Bitrix: activity_id={row.get('activity_id')}", flush=True)
                        tr_res = ui_browser_session.fetch_transcript_from_deal_timeline(
                            row["deal_url"],
                            int(row.get("activity_id") or 0),
                            timeout_sec=ui_timeout_sec,
                        )
                        if tr_res.ok and tr_res.text:
                            bitrix_text = tr_res.text
                            row["bitrix_card_transcript"] = bitrix_text
                            row["bitrix_card_transcript_status"] = "Получена"
                            row["transcript_match_score"] = transcript_match_score(text or "", bitrix_text)
                        else:
                            row["bitrix_card_transcript_status"] = tr_res.error or "Расшифровка Bitrix не найдена"
                    except Exception as e:
                        row["bitrix_card_transcript_status"] = f"Не удалось прочитать расшифровку Bitrix: {e}"
                else:
                    row["bitrix_card_transcript_status"] = "Не запрашивалась"

                finalize_transcript_analysis(row, deal, comments, text or "", bitrix_text, kpi, kpi_cmp)

                # attach (idempotent via cache)
                txt_hash = _sha256_text(text or "")
                row["transcript_hash"] = txt_hash
                cached = (state_cache.get(call_id) or {}) if isinstance(state_cache.get(call_id), dict) else None
                if (not args.force_attach) and cached and cached.get("hash") == txt_hash:
                    row["attach_result"] = {"skipped": True, "reason": "state_cache_same_hash"}
                else:
                    act_full = activity_get(api, int(act.get("ID"))) if act.get("ID") else act
                    attach = attach_transcription_to_bitrix(api, call_id=call_id, transcript_text=text, duration=guess_duration_sec(act_full))
                    row["attach_result"] = attach
                state_cache[call_id] = {
                    "hash": txt_hash,
                    "transcript_path": str(transcript_path),
                    "bitnewton_task_id": task.task_id,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "deal_id": deal_id,
                    "activity_id": row.get("activity_id"),
                    "source": "bitnewton",
                }
                _save_state_cache(state_cache)
                ok += 1
            except (BitNewtonError, requests.RequestException, Exception) as e:
                row["error"] = str(e)
                err += 1
            finally:
                if row.get("audio_path") and not args.download_audio:
                    try:
                        Path(str(row["audio_path"])).unlink(missing_ok=True)  # type: ignore[call-arg]
                        row["audio_path"] = None
                    except Exception:
                        pass
                results.append(row)
                print(f"[{ai}/{len(acts)}] OK={ok} ERR={err}", flush=True)

    if ui_browser_session is not None:
        ui_browser_session.close()

    _save_state_cache(state_cache)

    manager_ids = [int(r["manager_id"]) for r in results if isinstance(r.get("manager_id"), int)]
    names = user_name_map(api, manager_ids) if manager_ids else {}
    for r in results:
        mid = r.get("manager_id")
        if isinstance(mid, int):
            r["manager_name"] = names.get(mid, str(mid))
        if r.get("overall_score") is None:
            r["overall_score"] = 0.0

    stage_ids_for_map = [str(r.get("stage_id") or "") for r in results]
    stage_history_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    try:
        unique_deal_ids = sorted({str(deal_id_from_report_row(r) or "") for r in results if deal_id_from_report_row(r)})
        if unique_deal_ids:
            print("[STAGE] Загружаю историю перемещений сделок по стадиям", flush=True)
            stage_history_by_deal = fetch_stage_history_by_deals(api, unique_deal_ids)
            for items in stage_history_by_deal.values():
                stage_ids_for_map.extend(str(item.get("STAGE_ID") or "") for item in items if isinstance(item, dict))
    except Exception as e:
        print(f"[WARN] Не удалось загрузить историю стадий: {e}", flush=True)

    stage_map = fetch_stage_name_map(api, stage_ids_for_map)
    if stage_history_by_deal:
        attach_stage_history_metrics(results, stage_history_by_deal, stage_map=stage_map)
    refresh_crm_scores_after_stage_metrics(results, kpi, kpi_cmp)

    final_results = results
    if retry_scope is not None:
        source_rows = list(retry_scope.get("source_rows") or [])
        final_results = merge_retry_results(source_rows, results, retry_scope)
        print(
            f"[RETRY] Пересобираю полный отчет: исходных строк={len(source_rows)}, "
            f"повторно обработано={len(results)}, итоговых строк={len(final_results)}",
            flush=True,
        )

    manager_summary = build_manager_summary(final_results)
    manager_summary_cmp = build_manager_summary(final_results, score_key="overall_score_cmp") if kpi_cmp is not None else None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_results = prepare_report_rows(final_results, stage_map=stage_map)
    json_out = REPORTS_DIR / f"bitnewton_sync_report_{ts}.json"
    json_out.write_text(json.dumps(report_results, ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(report_results, manager_summary, manager_summary_cmp=manager_summary_cmp, stage_map=stage_map)
    publish_latest_report(json_out, xlsx_out)
    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    if kpi_cmp is not None:
        ranked = sorted(
            [r for r in final_results if r.get("overall_score_delta") is not None],
            key=lambda x: abs(float(x.get("overall_score_delta") or 0.0)),
            reverse=True,
        )[:5]
        if ranked:
            print("\nТоп-5 кейсов с максимальной разницей KPI:")
            for i, r in enumerate(ranked, 1):
                print(
                    f"{i}. deal={r.get('deal_id')} act={r.get('activity_id')} "
                    f"manager={r.get('manager_name') or r.get('manager_id')} "
                    f"base={r.get('overall_score')} cmp={r.get('overall_score_cmp')} "
                    f"delta={r.get('overall_score_delta')}"
                )
    print(f"ИТОГО: OK={ok} ERR={err}")

    if int(args.cleanup_chrome_tmp_days or 0) > 0:
        removed = cleanup_old_chrome_tmp_profiles(REPORTS_DIR, keep_days=int(args.cleanup_chrome_tmp_days))
        if removed:
            print(f"[OK] Удалено старых chrome_profile_tmp_*: {removed}")

    return ok, json_out, xlsx_out
