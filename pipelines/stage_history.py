from __future__ import annotations

import re
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from bitrix.api import Bitrix24API
from pipelines.deals import deal_id_from_report_row
from pipelines.stages import (
    DEAL_TOTAL_WORK_CRITICAL_MINUTES,
    DEAL_TOTAL_WORK_WARNING_MINUTES,
    DEFAULT_STAGE_NAMES,
    format_minutes_for_threshold as _format_minutes_for_threshold,
    safe_int,
    stage_display_name,
    stage_duration_thresholds,
    stage_history_type_label,
    stage_order_map,
    threshold_status,
)


def stage_entity_id_from_stage(stage_id: str) -> str:
    stage_id = str(stage_id or "")
    match = re.match(r"^C(\d+):", stage_id)
    if match:
        return f"DEAL_STAGE_{match.group(1)}"
    return "DEAL_STAGE"


async def fetch_stage_name_map(api: Bitrix24API, stage_ids: List[str]) -> Dict[str, str]:
    out = dict(DEFAULT_STAGE_NAMES)
    entities = sorted({stage_entity_id_from_stage(stage_id) for stage_id in stage_ids if stage_id})
    for entity in entities:
        try:
            res = await api.call(
                "crm.status.list", {"filter": {"ENTITY_ID": entity}, "order": {"SORT": "ASC"}}
            )
            for row in res.get("result") or []:
                sid = str(row.get("STATUS_ID") or "").strip()
                name = str(row.get("NAME") or "").strip()
                if sid and name:
                    out[sid] = name
        except Exception:
            continue
    return out


def parse_dt(raw: Any) -> Optional[datetime]:
    try:
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


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


async def fetch_stage_history_by_deals(
    api: Bitrix24API, deal_ids: List[str], chunk_size: int = 50
) -> Dict[str, List[Dict[str, Any]]]:
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
            data = await api.call("crm.stagehistory.list", params)
            items = _stage_history_items_from_response(data)
            for item in items:
                owner_id = str(item.get("OWNER_ID") or "").strip()
                if owner_id:
                    out.setdefault(owner_id, []).append(item)
            start = _stage_history_next_start(data, int(start or 0), len(items))
            if start is not None:
                await asyncio.sleep(0.1)
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
