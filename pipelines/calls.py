from __future__ import annotations

import asyncio
import json
import html
import re
from datetime import datetime
from typing import Any

from bitrix.api import Bitrix24API
from logging_setup import get_logger
from pipelines.models import BitrixActivity
from pipelines.stages import safe_int

FIRST_RESPONSE_SLA_HOURS = 0.5
logger = get_logger(__name__)

_BITRIX_CHAT_MARKERS = (
    "bitrixgpt составил резюме чата",
    "резюме чата",
    "чат с клиентом",
    "диалог чат",
    "telegram",
    "whatsapp",
    "мессенджер",
    "открытая линия",
)

_BITRIX_CALL_MARKERS = (
    "bitrixgpt составил резюме звонка",
    "резюме звонка",
    "итог звонка",
    "по звонку",
)

_BITRIX_SYSTEM_COMMENT_MARKERS = (
    "изменён ответственный за сделку",
    "ответственный синхронизирован",
    "изменен ответственный за сделку",
)

_BITRIX_NOISE_MARKERS = (
    "ответственный синхронизирован",
    "изменен ответственный за сделку",
    "изменён ответственный за сделку",
    "в контактах",
    "company/personal/user",
)


def _normalize_bitrix_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\[URL=[^\]]+\](.*?)\[/URL\]", r"\1", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[(?:/?B|/?I|/?U|/?S|/?P|BR)\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _short(text: str, limit: int) -> str:
    normalized = _normalize_bitrix_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _strip_bbcode_tags(text: str) -> str:
    cleaned = re.sub(r"\[/?URL(?:=[^\]]*)?\]", " ", str(text or ""), flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\[/?(?:B|I|U|S|QUOTE|CODE|COLOR|SIZE|LEFT|RIGHT|CENTER|LIST|\*)[^\]]*\]",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"https?://\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\d+\]", " ", cleaned)
    return _normalize_bitrix_text(cleaned)


def _is_noise_fragment(text: str) -> bool:
    normalized = _normalize_bitrix_text(text)
    if not normalized:
        return True
    lowered = normalized.lower().replace("ё", "е")
    if re.fullmatch(r"[\W_]+", normalized):
        return True
    return any(marker in lowered for marker in _BITRIX_NOISE_MARKERS)


def _extract_activity_fragments(activity: dict[str, Any], max_chars: int) -> list[str]:
    fragments: list[str] = []
    for key in ("SUBJECT", "DESCRIPTION", "PROVIDER_TYPE_NAME", "RESULT_SUMMARY"):
        text = _strip_bbcode_tags(activity.get(key))
        if text and not _is_noise_fragment(text):
            fragments.append(_short(text, max_chars))

    settings = activity.get("SETTINGS")
    if isinstance(settings, str):
        trimmed = settings.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                settings = json.loads(trimmed)
            except json.JSONDecodeError:
                settings = None
    if isinstance(settings, dict):
        for key, value in settings.items():
            key_norm = str(key or "").lower().replace("ё", "е")
            if any(
                token in key_norm
                for token in ("summary", "resume", "transcript", "расшифр", "резюме", "итог")
            ):
                text = _strip_bbcode_tags(value)
                if text and not _is_noise_fragment(text):
                    fragments.append(_short(text, max_chars))
    return fragments


def _extract_bitrix_summary_fragments(comment_texts: list[str], max_chars: int) -> list[str]:
    out: list[str] = []
    for comment in comment_texts:
        lowered = comment.lower().replace("ё", "е")
        if not any(marker in lowered for marker in _BITRIX_CHAT_MARKERS + _BITRIX_CALL_MARKERS):
            continue
        payload = _summary_payload(comment)
        if len(payload) < 20:
            continue
        out.append(_short(payload, max_chars))
    return out[:4]


def _build_overall_meaning(fragments: list[str], max_chars: int) -> str:
    seen: set[str] = set()
    unique: list[str] = []
    for fragment in fragments:
        cleaned = _strip_bbcode_tags(fragment)
        if not cleaned or _is_noise_fragment(cleaned):
            continue
        key = cleaned.lower().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    if not unique:
        return ""
    return _short(" | ".join(unique[:6]), max_chars)


def _looks_like_system_comment(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _BITRIX_SYSTEM_COMMENT_MARKERS)


def _summary_payload(text: str) -> str:
    cleaned = text
    cleaned = re.sub(
        r"(?i)bitrixgpt\s*составил\s*резюме\s*(чата|звонка)\s*[:\-]?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\bрезюме\s*(чата|звонка)\b\s*[:\-]?", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\n\t")
    return cleaned


def _pick_neighbor_comment(comments: list[str], index: int) -> str:
    for offset in (1, -1, 2, -2):
        target = index + offset
        if target < 0 or target >= len(comments):
            continue
        candidate = comments[target]
        if len(candidate) < 40:
            continue
        if _looks_like_system_comment(candidate):
            continue
        return candidate
    return ""


def _unique_ordered(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_bitrix_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _compact_summary(value: str, max_chars: int = 1200) -> str:
    text = _normalize_bitrix_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def extract_bitrix_gpt_summaries(
    comments: list[str],
    activities: list[dict[str, Any]] | None = None,
    *,
    max_fragments: int = 12,
    max_chars_per_fragment: int = 700,
    max_result_chars: int = 1200,
) -> dict[str, Any]:
    normalized: list[str] = []
    for comment in comments:
        text = _strip_bbcode_tags(comment)
        if text and not _is_noise_fragment(text):
            normalized.append(text)

    chat_candidates: list[str] = []
    call_candidates: list[str] = []

    for index, comment in enumerate(normalized):
        lowered = comment.lower()
        is_chat = any(marker in lowered for marker in _BITRIX_CHAT_MARKERS)
        is_call = any(marker in lowered for marker in _BITRIX_CALL_MARKERS)
        if not (is_chat or is_call):
            continue

        payload = _summary_payload(comment)
        if len(payload) < 30:
            payload = _pick_neighbor_comment(normalized, index) or payload
        if len(payload) < 20:
            continue

        if is_chat:
            chat_candidates.append(payload)
        if is_call:
            call_candidates.append(payload)

    if not chat_candidates:
        chat_candidates = [
            comment
            for comment in normalized
            if len(comment) >= 50
            and any(marker in comment.lower() for marker in ("чат", "telegram", "whatsapp", "мессендж"))
            and not _looks_like_system_comment(comment)
        ][:2]

    if not call_candidates:
        call_candidates = [
            comment
            for comment in normalized
            if len(comment) >= 50
            and any(marker in comment.lower() for marker in ("звон", "созвон", "перезвон"))
            and not _looks_like_system_comment(comment)
        ][:2]

    chat_items = _unique_ordered(chat_candidates)
    call_items = _unique_ordered(call_candidates)

    chat_summary = _compact_summary(" ".join(chat_items[:2]))
    call_summary = _compact_summary(" ".join(call_items[:2]))

    fragments: list[str] = _extract_bitrix_summary_fragments(normalized, max_chars_per_fragment)
    for comment in normalized:
        fragments.append(_short(comment, max_chars_per_fragment))
        if len(fragments) >= max_fragments:
            break

    if len(fragments) < max_fragments:
        for activity in activities or []:
            if not isinstance(activity, dict):
                continue
            for fragment in _extract_activity_fragments(activity, max_chars_per_fragment):
                fragments.append(fragment)
                if len(fragments) >= max_fragments:
                    break
            if len(fragments) >= max_fragments:
                break

    overall_meaning = _build_overall_meaning(fragments, max_result_chars)
    combined = " ".join(x for x in [f"Чат: {chat_summary}" if chat_summary else "", f"Звонок: {call_summary}" if call_summary else ""] if x).strip()
    if not combined and overall_meaning:
        combined = overall_meaning

    sources: list[str] = []
    if chat_summary:
        sources.append("чат")
    if call_summary:
        sources.append("звонок")
    if overall_meaning:
        sources.append("контекст")

    return {
        "bitrix_chat_summary": chat_summary,
        "bitrix_call_summary": call_summary,
        "bitrix_combined_summary": combined,
        "bitrix_overall_meaning": overall_meaning,
        "bitrix_summary_sources": ", ".join(sources),
        "bitrix_summary_found": bool(sources),
    }


async def activity_get(api: Bitrix24API, activity_id: int) -> dict[str, Any]:
    res = await api.call("crm.activity.get", {"id": int(activity_id)})
    raw = res.get("result", {}) or {}
    try:
        return BitrixActivity.model_validate(raw).model_dump(by_alias=True, mode="json")
    except Exception as e:
        logger.error(f"[ERROR] Ошибка валидации активности {activity_id}: {e}")
        return raw


async def list_deal_call_activities(api: Bitrix24API, deal_id: str) -> list[dict[str, Any]]:
    res = await api.call(
        "crm.activity.list",
        {
            "filter": {
                "OWNER_TYPE_ID": 2,
                "OWNER_ID": str(deal_id),
                "TYPE_ID": 2,
                "PROVIDER_ID": "VOXIMPLANT_CALL",
            },
            "select": [
                "ID",
                "CREATED",
                "START_TIME",
                "END_TIME",
                "SUBJECT",
                "ORIGIN_ID",
                "DIRECTION",
                "PROVIDER_ID",
                "PROVIDER_TYPE_ID",
                "AUTHOR_ID",
                "RESPONSIBLE_ID",
            ],
            "order": {"START_TIME": "ASC"},
            "start": 0,
        },
    )
    raw_list = res.get("result", []) or []
    out = []
    for r in raw_list:
        try:
            validated = BitrixActivity.model_validate(r).model_dump(by_alias=True, mode="json")
            out.append(validated)
        except Exception as e:
            logger.error(
                f"[ERROR] Ошибка валидации активности {r.get('ID')} "
                f"в сделке {deal_id}: {e}"
            )
    return out


async def user_profile(
    api: Bitrix24API, user_id: Any, cache: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    uid = safe_int(user_id)
    if uid is None:
        return {}
    if uid in cache:
        return cache[uid]
    try:
        res = await api.call("user.get", {"ID": int(uid)})
        arr = res.get("result") or []
        cache[uid] = arr[0] if arr and isinstance(arr[0], dict) else {}
    except Exception:
        cache[uid] = {}
    return cache[uid]


async def load_department_chain(
    api: Bitrix24API, department_ids: list[Any], cache: dict[int, dict[str, Any]]
) -> None:
    pending = {
        int(x)
        for x in [safe_int(v) for v in department_ids]
        if x is not None and int(x) > 0 and int(x) not in cache
    }
    while pending:
        current = sorted(pending)
        pending.clear()
        try:
            res = await api.call("department.get", {"ID": current})
            rows = res.get("result") or []
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


def department_is_call_center(department_id: Any, cache: dict[int, dict[str, Any]]) -> bool:
    did = safe_int(department_id)
    seen: set[int] = set()
    while did is not None and did > 0 and did not in seen:
        seen.add(did)
        row = cache.get(did) or {}
        name = str(row.get("NAME") or "").lower()
        if (
            "call центр" in name
            or "call center" in name
            or "колл" in name
            or "контакт центр" in name
        ):
            return True
        did = safe_int(row.get("PARENT"))
    return False


async def is_call_center_operator(
    api: Bitrix24API,
    user_id: Any,
    user_cache: dict[int, dict[str, Any]],
    department_cache: dict[int, dict[str, Any]],
) -> bool:
    user = await user_profile(api, user_id, user_cache)
    if not user:
        return False
    position = str(user.get("WORK_POSITION") or "").lower()
    if "оператор" not in position and "operator" not in position:
        return False
    departments = user.get("UF_DEPARTMENT") or []
    if not isinstance(departments, list):
        departments = [departments]
    await load_department_chain(api, departments, department_cache)
    return any(department_is_call_center(dept_id, department_cache) for dept_id in departments)


async def split_call_center_operator_activities(
    api: Bitrix24API,
    activities: list[dict[str, Any]],
    user_cache: dict[int, dict[str, Any]],
    department_cache: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # Мы можем распараллелить проверку операторов
    tasks = []
    for act in activities:
        responsible_id = act.get("RESPONSIBLE_ID") or act.get("AUTHOR_ID")
        tasks.append(is_call_center_operator(api, responsible_id, user_cache, department_cache))

    results = await asyncio.gather(*tasks)

    for act, is_cc in zip(activities, results, strict=True):
        if is_cc:
            skipped.append(act)
        else:
            kept.append(act)

    return kept, skipped


async def user_name_map(api: Bitrix24API, user_ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    tasks = []
    sorted_uids = sorted(set(user_ids))
    for uid in sorted_uids:
        tasks.append(api.call("user.get", {"ID": int(uid)}))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for uid, res in zip(sorted_uids, results, strict=True):
        if isinstance(res, Exception):
            out[int(uid)] = str(uid)
            continue
        arr = res.get("result") or []
        if arr and isinstance(arr[0], dict):
            u = arr[0]
            out[int(uid)] = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip() or str(uid)
        else:
            out[int(uid)] = str(uid)
    return out


async def fetch_timeline_comments(api: Bitrix24API, deal_id: str) -> list[str]:
    try:
        res = await api.call(
            "crm.timeline.comment.list",
            {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": int(deal_id)}},
        )
        rows = res.get("result", []) or []
        comments: list[str] = []
        for r in rows:
            txt = str((r or {}).get("COMMENT") or "").strip()
            if txt:
                comments.append(txt)
        return comments
    except Exception:
        return []


async def fetch_deal_activities(api: Bitrix24API, deal_id: str, limit: int = 120) -> list[dict[str, Any]]:
    try:
        res = await api.call(
            "crm.activity.list",
            {
                "filter": {"OWNER_TYPE_ID": 2, "OWNER_ID": int(deal_id)},
                "select": [
                    "ID",
                    "TYPE_ID",
                    "PROVIDER_ID",
                    "PROVIDER_TYPE_ID",
                    "SUBJECT",
                    "DESCRIPTION",
                    "SETTINGS",
                    "RESULT_SUMMARY",
                    "COMMENTS",
                    "CREATED",
                ],
                "order": {"ID": "DESC"},
                "start": 0,
            },
        )
        rows = res.get("result", []) or []
        if not isinstance(rows, list):
            return []
        return [row for row in rows[: max(1, int(limit or 120))] if isinstance(row, dict)]
    except Exception:
        return []


async def fetch_open_next_step_activities(api: Bitrix24API, deal_id: str) -> list[dict[str, Any]]:
    try:
        res = await api.call(
            "crm.activity.list",
            {
                "filter": {
                    "OWNER_TYPE_ID": 2,
                    "OWNER_ID": int(deal_id),
                    "COMPLETED": "N",
                },
                "select": [
                    "ID",
                    "TYPE_ID",
                    "ORIGIN_ID",
                    "SUBJECT",
                    "DESCRIPTION",
                    "COMMENTS",
                    "START_TIME",
                    "END_TIME",
                    "DEADLINE",
                    "COMPLETED",
                    "STATUS",
                    "PROVIDER_ID",
                    "PROVIDER_TYPE_ID",
                    "RESPONSIBLE_ID",
                    "AUTHOR_ID",
                ],
                "order": {"DEADLINE": "ASC"},
                "start": 0,
            },
        )
        rows = res.get("result", []) or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            provider = str(row.get("PROVIDER_ID") or "").upper()
            type_id = str(row.get("TYPE_ID") or "").strip()
            if provider == "VOXIMPLANT_CALL" or (type_id == "2" and row.get("ORIGIN_ID")):
                continue
            out.append(row)
        return out
    except Exception:
        return []


def parse_dt(raw: Any) -> datetime | None:
    try:
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def guess_duration_sec(act: dict[str, Any]) -> int:
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


def guess_duration_minutes(act: dict[str, Any]) -> float:
    return round(guess_duration_sec(act) / 60.0, 2)


def reaction_speed_label(first_delay_min: float | None) -> str:
    if first_delay_min is None:
        return "Нет звонка менеджера"
    if first_delay_min <= 15:
        return "Быстрая реакция"
    if first_delay_min <= 30:
        return "В срок"
    if first_delay_min <= 60:
        return "Поздно"
    return "Критически поздно"


def compute_discipline_metrics(
    deal: dict[str, Any], calls: list[dict[str, Any]], kpi: dict[str, Any]
) -> dict[str, Any]:
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
            f"Скорость реакции — сколько минут прошло от создания сделки до первого звонка менеджера. "  # noqa: E501
            f"Единая норма KPI: до 30 мин.; факт: {first_delay_min:g} мин."
            if first_delay_min is not None
            else "Скорость реакции — время от создания сделки до первого звонка менеджера. Единая норма KPI: до 30 мин.; звонков менеджера нет."  # noqa: E501
        ),
    }
