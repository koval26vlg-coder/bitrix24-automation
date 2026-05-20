from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from bitrix.api import Bitrix24API
from pipelines.stages import safe_int

FIRST_RESPONSE_SLA_HOURS = 0.5


async def activity_get(api: Bitrix24API, activity_id: int) -> dict[str, Any]:
    res = await api.call("crm.activity.get", {"id": int(activity_id)})
    return res.get("result", {}) or {}


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
    return res.get("result", []) or []


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
