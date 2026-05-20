from __future__ import annotations
from typing import Any, Dict, List, Tuple

def _crm_item(code: str, block: str, criterion: str, score: float, comment: str) -> Dict[str, Any]:
    score = max(0.0, min(1.0, float(score or 0.0)))
    return {
        "crm_checklist_block_name": block,
        "crm_checklist_code": code,
        "crm_checklist_criterion": criterion,
        "crm_checklist_score": score,
        "crm_checklist_max_score": 1,
        "crm_checklist_comment": comment,
    }

def _status_score(status: Any) -> Tuple[float, str]:
    text = str(status or "").strip()
    lowered = text.lower()
    if not text:
        return 0.5, "Нет данных о статусе срока, критерий учтен как частично выполненный."
    if "тревога" in lowered:
        return 0.0, f"Статус: {text}. Нужна управленческая реакция по сделке."
    if "предупреждение" in lowered:
        return 0.5, f"Статус: {text}. Сделка приближается к критическому сроку."
    return 1.0, f"Статус: {text}."

def evaluate_crm_checklist(row: Dict[str, Any], suffix: str = "", include_stage: bool = True) -> Dict[str, Any]:
    def get(key: str) -> Any:
        if suffix and f"{key}{suffix}" in row:
            return row.get(f"{key}{suffix}")
        return row.get(key)

    items: List[Dict[str, Any]] = []
    items.append(
        _crm_item(
            "crm_has_contact",
            "Заполнение сделки",
            "В сделке указан контакт или компания",
            1.0 if get("has_contact") else 0.0,
            "Контакт/компания есть." if get("has_contact") else "В сделке нет контакта или компании.",
        )
    )
    items.append(
        _crm_item(
            "crm_has_amount",
            "Заполнение сделки",
            "В сделке указана сумма",
            1.0 if get("has_amount") else 0.0,
            "Сумма заполнена." if get("has_amount") else "Сумма сделки не заполнена или равна нулю.",
        )
    )
    items.append(
        _crm_item(
            "crm_has_title",
            "Заполнение сделки",
            "Название сделки заполнено",
            1.0 if get("has_title") else 0.0,
            "Название заполнено." if get("has_title") else "Название сделки пустое.",
        )
    )
    items.append(
        _crm_item(
            "crm_has_comments",
            "Заполнение сделки",
            "В CRM есть комментарий или следующий шаг",
            1.0 if get("has_comments") else 0.0,
            "В таймлайне есть комментарии/следующие действия." if get("has_comments") else "В CRM не найден комментарий или следующий шаг.",
        )
    )

    has_call = not bool(row.get("no_calls")) and int(row.get("calls_count") or 0) > 0
    items.append(
        _crm_item(
            "crm_has_manager_call",
            "Активность по сделке",
            "Есть звонок менеджера после исключения Call-центра",
            1.0 if has_call else 0.0,
            "Звонок менеджера найден." if has_call else "Звонков менеджера не найдено.",
        )
    )

    next_step_synced = bool(get("next_step_synced"))
    next_step_in_call = bool(get("has_next_step_phrase"))
    items.append(
        _crm_item(
            "crm_next_step_synced",
            "Связь звонка с CRM",
            "Следующий шаг из разговора синхронизирован с CRM",
            1.0 if next_step_synced else (0.5 if next_step_in_call else 0.0),
            (
                "Следующий шаг прозвучал и зафиксирован в CRM."
                if next_step_synced
                else (
                    "Следующий шаг прозвучал, но не подтвержден в CRM."
                    if next_step_in_call
                    else "Следующий шаг не найден ни в разговоре, ни в CRM."
                )
            ),
        )
    )

    amount_mentioned = bool(get("amount_mentioned"))
    has_amount = bool(get("has_amount"))
    items.append(
        _crm_item(
            "crm_amount_aligned",
            "Связь звонка с CRM",
            "Сумма сделки подтверждается разговором",
            1.0 if amount_mentioned else (0.5 if has_amount else 0.0),
            (
                "Сумма из сделки встречается в разговоре."
                if amount_mentioned
                else (
                    "Сумма есть в CRM, но в разговоре явно не подтверждена."
                    if has_amount
                    else "Сумма не заполнена и не подтверждена разговором."
                )
            ),
        )
    )

    if include_stage:
        history_count = row.get("stage_history_count")
        if history_count is not None:
            history_ok = int(history_count or 0) > 0
            items.append(
                _crm_item(
                    "crm_stage_history",
                    "Движение по воронке",
                    "Есть история движения сделки по стадиям",
                    1.0 if history_ok else 0.0,
                    "История стадий найдена." if history_ok else "История движения по стадиям не найдена.",
                )
            )
            score, comment = _status_score(row.get("stage_current_age_status"))
            items.append(
                _crm_item(
                    "crm_stage_age_ok",
                    "Движение по воронке",
                    "Сделка не зависла на текущей стадии",
                    score,
                    comment,
                )
            )
            score, comment = _status_score(row.get("deal_total_work_status"))
            items.append(
                _crm_item(
                    "crm_total_work_ok",
                    "Движение по воронке",
                    "Общий срок сделки в работе без тревоги",
                    score,
                    comment,
                )
            )
            returns = int(row.get("stage_return_count") or 0)
            items.append(
                _crm_item(
                    "crm_no_stage_returns",
                    "Движение по воронке",
                    "Нет возвратов на предыдущие стадии",
                    1.0 if returns == 0 else (0.5 if returns == 1 else 0.0),
                    f"Возвратов на предыдущие стадии: {returns}.",
                )
            )
            risk = str(row.get("stage_movement_risk") or "").strip()
            risk_l = risk.lower()
            if not risk:
                risk_score = 0.5
                risk_comment = "Риск движения по воронке не рассчитан."
            elif risk in {"OK", "Финал"}:
                risk_score = 1.0
                risk_comment = f"Риск движения: {risk}."
            elif "тревога" in risk_l:
                risk_score = 0.0
                risk_comment = f"Риск движения: {risk}. Нужна корректировка работы со сделкой."
            else:
                risk_score = 0.5
                risk_comment = f"Риск движения: {risk}. Требуется проверка руководителем."
            items.append(
                _crm_item(
                    "crm_stage_movement_ok",
                    "Движение по воронке",
                    "Движение сделки по воронке без критических рисков",
                    risk_score,
                    risk_comment,
                )
            )

    total_score = round(sum(float(item.get("crm_checklist_score") or 0.0) for item in items), 2)
    total_max = len(items)
    percent = round(total_score * 100.0 / max(1, total_max), 2)
    blocks: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        blocks.setdefault(str(item.get("crm_checklist_block_name") or ""), []).append(item)
    details_parts = []
    for block, block_items in blocks.items():
        block_score = round(
            sum(float(item.get("crm_checklist_score") or 0.0) for item in block_items),
            2,
        )
        details_parts.append(f"{block}: {block_score}/{len(block_items)}")
    details = "; ".join(details_parts)
    return {
        "crm_checklist_total_score": total_score,
        "crm_checklist_max_score": total_max,
        "crm_checklist_percent": percent,
        "crm_checklist_details": details,
        "crm_checklist_items": items,
        "crm_work_score": percent,
    }

def recalculate_overall_score(row: Dict[str, Any], kpi: Dict[str, Any], suffix: str = "") -> None:
    w: Dict[str, Any] = kpi.get("weights", {})
    ow: Dict[str, Any] = w.get("overall", {})
    call_weight: float = float(ow.get("call_quality", 0.50))
    crm_weight: float = float(ow.get("crm_alignment", 0.50))
    total_weight = call_weight + crm_weight
    if total_weight <= 0:
        call_weight = crm_weight = 0.50
        total_weight = 1.0
    call_weight = call_weight / total_weight
    crm_weight = crm_weight / total_weight
    crm_work_score_val = row.get(f"crm_work_score{suffix}") or row.get("crm_work_score")
    crm_work_score: float = float(crm_work_score_val) if crm_work_score_val is not None else 0.0
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
