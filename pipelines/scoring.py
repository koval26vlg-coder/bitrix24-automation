from __future__ import annotations

from typing import Any, Dict


def recalculate_overall_score(row: Dict[str, Any], kpi: Dict[str, Any], suffix: str = "") -> None:
    w = kpi.get("weights", {})
    ow = w.get("overall", {})
    call_weight = float(ow.get("call_quality", 0.50))
    crm_weight = float(ow.get("crm_alignment", 0.50))
    total_weight = call_weight + crm_weight
    if total_weight <= 0:
        call_weight = crm_weight = 0.50
        total_weight = 1.0
    call_weight = call_weight / total_weight
    crm_weight = crm_weight / total_weight
    crm_work_score = float(row.get(f"crm_work_score{suffix}") or row.get("crm_work_score") or 0)
    row[f"overall_score{suffix}"] = round(
        call_weight * float(row.get(f"call_quality_score{suffix}") or 0)
        + crm_weight * crm_work_score,
        2,
    )
    row[f"overall_score_details{suffix}"] = (
        f"Итог = качество разговора {call_weight * 100:.0f}% "
        f"+ ведение CRM {crm_weight * 100:.0f}%. "
        "Ведение CRM считается по CRM-чек-листу: заполнение карточки, наличие звонка менеджера, "
        "синхронизация следующего шага, связь разговора с данными сделки и движение по воронке."
    )
