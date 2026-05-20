from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipelines.kpi import FIRST_RESPONSE_SLA_HOURS
from pipelines.scoring import (
    HANDLING_RE,
    OBJECTION_RULES,
    _context,
    call_quality_conclusion,
    conversation_meaning,
    evaluate_call_text,
    evaluate_crm_checklist,
    merged_transcript_text,
    recalculate_overall_score,
)


def compute_deal_quality(deal: Dict[str, Any], comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    weights: Dict[str, Any] = kpi.get("deal_quality_weights", {})
    has_contact = bool(deal.get("CONTACT_ID") or deal.get("COMPANY_ID"))
    has_amount = bool(str(deal.get("OPPORTUNITY") or "").strip() not in {"", "0", "0.00"})
    has_title = bool(str(deal.get("TITLE") or "").strip())
    has_next_step = bool(comments)
    score = 0
    score += int(weights.get("has_contact", 25)) if has_contact else 0
    score += int(weights.get("has_amount", 25)) if has_amount else 0
    score += int(weights.get("has_title", 25)) if has_title else 0
    score += int(weights.get("has_comments", 25)) if has_next_step else 0
    contact_text = "да" if has_contact else "нет"
    amount_text = "да" if has_amount else "нет"
    title_text = "да" if has_title else "нет"
    next_step_text = "да" if has_next_step else "нет"
    details = (
        f"Контакт/компания: {contact_text} ({int(weights.get('has_contact', 25))} баллов); "
        f"сумма: {amount_text} ({int(weights.get('has_amount', 25))} баллов); "
        f"название сделки: {title_text} ({int(weights.get('has_title', 25))} баллов); "
        f"комментарии или следующий шаг в CRM: {next_step_text} "
        f"({int(weights.get('has_comments', 25))} баллов)."
    )
    return {
        "deal_quality_score": float(score),
        "deal_quality_details": details,
        "has_contact": has_contact,
        "has_amount": has_amount,
        "has_title": has_title,
        "has_comments": has_next_step,
    }


def crm_call_alignment(deal: Dict[str, Any], text: str, comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    weights: Dict[str, Any] = kpi.get("alignment_weights", {})
    transcript = (text or "").lower()
    title_words = [word for word in re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", str(deal.get("TITLE") or "").lower())[:6]]
    title_hits = sum(1 for word in title_words if word in transcript)
    amount = str(deal.get("OPPORTUNITY") or "").split(".")[0]
    amount_mentioned = bool(amount and amount != "0" and amount in transcript)
    comments_text = " ".join(comments).lower()
    next_step_re = r"\b(перезвон\w*|встреч\w*|созвон\w*|отправ\w*|вышл\w*|уточн\w*|согласу\w*|кп|договор\w*)\b"
    next_step_synced = bool(re.search(next_step_re, transcript) and re.search(next_step_re, comments_text))
    amount_weight = int(weights.get("amount_mentioned", 30))
    next_step_weight = int(weights.get("next_step_synced", 40))
    raw_score = (amount_weight if amount_mentioned else 0) + (next_step_weight if next_step_synced else 0)
    total_weight = max(1, amount_weight + next_step_weight)
    align_score = round(raw_score * 100.0 / total_weight, 2)
    next_step_details = (
        "Да: следующий шаг звучит в разговоре и зафиксирован в комментариях/таймлайне CRM."
        if next_step_synced
        else "Нет: следующий шаг либо не прозвучал в разговоре, либо не зафиксирован в CRM. Это мешает контролировать дальнейшее действие по клиенту."
    )
    amount_text = "да" if amount_mentioned else "нет"
    next_step_text = "да" if next_step_synced else "нет"
    details = (
        "Связь звонка с CRM показывает, совпадает ли содержание разговора с данными сделки: "
        f"сумма упомянута: {amount_text}; "
        f"следующий шаг синхронизирован с CRM: {next_step_text}. "
        "Совпадения с названием сделки больше не выводятся в отчет как отдельная метрика."
    )
    return {
        "alignment_score": float(align_score),
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

    unhandled = [objection for objection in objections if not objection["handled"]]
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
        marked_lines.append("[МОМЕНТЫ ДЛЯ УЛУЧШЕНИЯ]\n" + "\n".join(f"- {item}" for item in improvement_items))

    transcript_marked = raw
    if marked_lines:
        transcript_marked = "\n\n".join(marked_lines) + "\n\n[ПОЛНАЯ РАСШИФРОВКА]\n" + raw

    recommendations = [objection["objection_recommendation"] for objection in unhandled]
    if not recommendations and objections:
        recommendations = ["После ответа на возражение обязательно закрепить следующий шаг: дата, действие, ответственный."]

    return {
        "objections_count": len(objections),
        "unhandled_objections_count": len(unhandled),
        "objections_handled": bool(objections and not unhandled),
        "objections_found": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']} ({o['objection_status']})" for o in objections
        ),
        "unhandled_objections": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']}" for o in unhandled
        ),
        "objection_recommendations": "\n".join(dict.fromkeys(recommendations)),
        "improvement_moments": "\n".join(improvement_items),
        "transcript_marked": transcript_marked,
        "objection_rows": objections,
    }


async def apply_scores(row: Dict[str, Any], deal: Dict[str, Any], comments: List[str], text: str, kpi: Dict[str, Any], suffix: str = "", codex_evaluator: Any = None) -> None:
    first_h = row.get("first_response_hours")
    first_m = row.get("first_response_minutes")
    sla_cfg = kpi.get("sla", {})
    first_response_sla = float(sla_cfg.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    if first_h is None and first_m is not None:
        first_h = float(first_m) / 60.0
    row[f"first_response_sla_ok{suffix}"] = first_h is not None and float(first_h) <= first_response_sla

    deal_q = compute_deal_quality(deal, comments, kpi)
    call_q = evaluate_call_text(text, kpi)
    align = crm_call_alignment(deal, text, comments, kpi)
    for key, value in deal_q.items():
        row[f"{key}{suffix}"] = value
    for key, value in call_q.items():
        row[f"{key}{suffix}"] = value
    for key, value in align.items():
        row[f"{key}{suffix}"] = value

    crm_q = evaluate_crm_checklist(row, suffix=suffix, include_stage=False)
    for key, value in crm_q.items():
        if suffix and key in {"crm_checklist_items"}:
            continue
        row[f"{key}{suffix}"] = value

    # Интеграция Codex
    if codex_evaluator is not None and text and not suffix:
        codex_res = await codex_evaluator.evaluate_transcript(text, {"deal_id": row.get("deal_id")})
        row.update(codex_res)

    recalculate_overall_score(row, kpi, suffix=suffix)


async def finalize_transcript_analysis(
    row: Dict[str, Any],
    deal: Dict[str, Any],
    comments: List[str],
    bitnewton_text: str,
    bitrix_text: str,
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
    codex_evaluator: Any = None,
) -> None:
    analysis_text = merged_transcript_text(bitnewton_text or "", bitrix_text or "")
    row["combined_transcript_text"] = analysis_text
    await apply_scores(row, deal, comments, analysis_text, kpi, suffix="", codex_evaluator=codex_evaluator)
    if kpi_cmp is not None:
        await apply_scores(row, deal, comments, analysis_text, kpi_cmp, suffix="_cmp", codex_evaluator=None)
        row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)
    row.update(analyze_transcript_improvements(analysis_text, row))
    call_conclusion, call_recommendations = call_quality_conclusion(row)
    row["call_quality_conclusion"] = call_conclusion
    row["recommendations"] = call_recommendations
    row["conversation_meaning"] = conversation_meaning(analysis_text, row)


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


async def recompute_existing_row(row: Dict[str, Any], kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]] = None, codex_evaluator: Any = None) -> Dict[str, Any]:
    recalculated = dict(row)
    recalculated["kpi_profile"] = (kpi.get("profile") or {}).get("name")
    recalculated["kpi_version"] = (kpi.get("profile") or {}).get("version")
    if kpi_cmp is not None:
        recalculated["kpi_profile_cmp"] = (kpi_cmp.get("profile") or {}).get("name")
        recalculated["kpi_version_cmp"] = (kpi_cmp.get("profile") or {}).get("version")

    text = str(recalculated.get("combined_transcript_text") or recalculated.get("transcript_text") or "").strip()
    if not text and recalculated.get("transcript_path"):
        try:
            path = Path(str(recalculated.get("transcript_path")))
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            text = ""
    bitrix_text = str(recalculated.get("bitrix_card_transcript") or "").strip()
    analysis_text = merged_transcript_text(text, bitrix_text)
    recalculated["combined_transcript_text"] = analysis_text
    if text and not recalculated.get("transcript_text"):
        recalculated["transcript_text"] = text

    if not analysis_text:
        recalculated["call_quality_score"] = 0.0
        recalculated["call_quality_details"] = "Качество разговора не рассчитано: нет сохраненной расшифровки."
        recalculated.update(evaluate_crm_checklist(recalculated, include_stage=True))
        recalculate_overall_score(recalculated, kpi)
        return recalculated

    for key, value in evaluate_call_text(analysis_text, kpi).items():
        recalculated[key] = value

    if codex_evaluator is not None:
        codex_res = await codex_evaluator.evaluate_transcript(analysis_text, {"deal_id": recalculated.get("deal_id")})
        recalculated.update(codex_res)

    recalculated.update(evaluate_crm_checklist(recalculated, include_stage=True))
    recalculate_overall_score(recalculated, kpi)

    recalculated.update(analyze_transcript_improvements(analysis_text, recalculated))
    call_conclusion, call_recommendations = call_quality_conclusion(recalculated)
    recalculated["call_quality_conclusion"] = call_conclusion
    recalculated["recommendations"] = call_recommendations
    recalculated["conversation_meaning"] = conversation_meaning(analysis_text, recalculated)

    if kpi_cmp is not None:
        tmp = await recompute_existing_row({**recalculated, "overall_score": None}, kpi_cmp, None, None)
        for key in ["call_quality_score", "deal_quality_score", "alignment_score", "crm_work_score", "overall_score"]:
            if key in tmp:
                recalculated[f"{key}_cmp"] = tmp.get(key)
        recalculated["overall_score_delta"] = round(
            float(recalculated.get("overall_score_cmp") or 0.0) - float(recalculated.get("overall_score") or 0.0),
            2,
        )

    return recalculated
