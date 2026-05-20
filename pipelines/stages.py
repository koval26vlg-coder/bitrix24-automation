from __future__ import annotations

from typing import Any

STAGE_STUCK_THRESHOLD_HOURS = 72.0
DEAL_TOTAL_WORK_WARNING_MINUTES = 10 * 24 * 60
DEAL_TOTAL_WORK_CRITICAL_MINUTES = 14 * 24 * 60
DEFAULT_STAGE_WARNING_MINUTES = 3 * 24 * 60
DEFAULT_STAGE_CRITICAL_MINUTES = 5 * 24 * 60

STAGE_DURATION_THRESHOLDS_MINUTES: dict[str, tuple[int, int]] = {
    "C1:NEW": (30, 3 * 24 * 60),
    "C1:PREPARATION": (24 * 60, 2 * 24 * 60),
    "C1:PREPAYMENT_INVOICE": (2 * 24 * 60, 4 * 24 * 60),
    "C1:FINAL_INVOICE": (5 * 24 * 60, 8 * 24 * 60),
    "C1:EXECUTING": (2 * 24 * 60, 3 * 24 * 60),
    "C1:UC_9NU15J": (3 * 24 * 60, 5 * 24 * 60),
    "C1:UC_50AD9V": (5 * 24 * 60, 7 * 24 * 60),
    "C1:UC_KLTOFA": (7 * 24 * 60, 10 * 24 * 60),
    "C1:UC_6SX2WL": (24 * 60, 2 * 24 * 60),
}

DEFAULT_STAGE_NAMES: dict[str, str] = {
    "C1:NEW": "Ответственный назначен",
    "C1:PREPARATION": "Потребность выявлена",
    "C1:PREPAYMENT_INVOICE": "Тех. пресейл назначен",
    "C1:FINAL_INVOICE": "Тех. пресейл проведен",
    "C1:EXECUTING": "Защита КП проведена",
    "C1:UC_9NU15J": "Счет отправлен",
    "C1:UC_50AD9V": "Оплата получена",
    "C1:UC_KLTOFA": "Передан в Тех деп.",
    "C1:UC_6SX2WL": "Возврат сделки в работу от РОП",
    "C1:WON": "Успешно завершена",
    "C1:UC_AHHIBG": "Сделка проиграна на проверке РОП",
    "C1:LOSE": "Сделка проиграна",
    "C1:UC_62ISSK": "ВОЗВРАТ",
    "C1:UC_2EN0IE": "ДУБЛЬ",
    "NEW": "Новая",
    "WON": "Сделка успешна",
    "LOSE": "Сделка проиграна",
}


def safe_int(x: Any) -> int | None:
    try:
        if x is None or x == "":
            return None
        return int(float(str(x).replace(",", ".")))
    except Exception:
        return None


def stage_display_name(stage_id: Any, stage_map: dict[str, str] | None = None) -> str:
    sid = str(stage_id or "").strip()
    if not sid:
        return ""
    return (stage_map or DEFAULT_STAGE_NAMES).get(sid, sid)


def stage_order_map(stage_map: dict[str, str] | None = None) -> dict[str, int]:
    ordered_ids = list(DEFAULT_STAGE_NAMES.keys())
    if stage_map:
        for stage_id in stage_map.keys():
            if stage_id not in ordered_ids:
                ordered_ids.append(stage_id)
    return {stage_id: index for index, stage_id in enumerate(ordered_ids, start=1)}


def stage_history_type_label(type_id: Any) -> str:
    labels = {
        1: "Создание/попадание на стадию",
        2: "Смена стадии",
        3: "Финальная стадия",
    }
    return labels.get(safe_int(type_id), str(type_id or ""))


def format_minutes_for_threshold(minutes: float | None) -> str:
    if minutes is None:
        return ""
    try:
        m = float(minutes)
    except Exception:
        return ""
    if m >= 24 * 60 and m % (24 * 60) == 0:
        return f"{int(m // (24 * 60))} д."
    if m >= 60 and m % 60 == 0:
        return f"{int(m // 60)} ч."
    return f"{int(round(m))} мин."


def stage_duration_thresholds(stage_id: Any) -> tuple[int, int]:
    sid = str(stage_id or "").strip()
    return STAGE_DURATION_THRESHOLDS_MINUTES.get(
        sid,
        (DEFAULT_STAGE_WARNING_MINUTES, DEFAULT_STAGE_CRITICAL_MINUTES),
    )


def threshold_status(
    value_minutes: float | None, warning_minutes: float | None, critical_minutes: float | None
) -> str:
    if value_minutes is None or warning_minutes is None or critical_minutes is None:
        return "Нет данных"
    value = float(value_minutes)
    if value >= float(critical_minutes):
        return "Тревога"
    if value >= float(warning_minutes):
        return "Предупреждение"
    return "OK"
