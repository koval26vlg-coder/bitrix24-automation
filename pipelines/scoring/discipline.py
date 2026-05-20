from __future__ import annotations

from datetime import datetime
from typing import Any

FIRST_RESPONSE_SLA_HOURS = 0.5


def parse_dt(raw: Any) -> datetime | None:
    try:
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


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
