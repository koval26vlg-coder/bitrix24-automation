from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

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

_COMMENT_STOPWORDS = {
    "если",
    "или",
    "для",
    "что",
    "как",
    "это",
    "его",
    "она",
    "они",
    "мы",
    "вы",
    "нам",
    "вам",
    "будет",
    "быть",
    "клиент",
    "клиента",
    "менеджер",
    "звонок",
    "сделка",
    "сделки",
}


def _text_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", (text or "").lower())
        if token not in _COMMENT_STOPWORDS
    }


def _next_step_text(step: dict[str, Any]) -> str:
    return " ".join(
        str(step.get(key) or "").strip()
        for key in ("SUBJECT", "DESCRIPTION", "COMMENTS", "COMMENT")
        if str(step.get(key) or "").strip()
    ).strip()


def _next_step_comment_text(step: dict[str, Any]) -> str:
    comment = " ".join(
        str(step.get(key) or "").strip()
        for key in ("DESCRIPTION", "COMMENTS", "COMMENT")
        if str(step.get(key) or "").strip()
    ).strip()
    if comment:
        return comment
    return str(step.get("SUBJECT") or "").strip()


def _parse_deadline(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _deadline_not_overdue(raw: Any) -> bool:
    deadline = _parse_deadline(raw)
    if deadline is None:
        return False
    now = datetime.now(deadline.tzinfo) if deadline.tzinfo else datetime.now()
    return deadline >= now


def _comment_matches_call(comment: str, transcript: str) -> bool:
    comment_tokens = _text_tokens(comment)
    transcript_tokens = _text_tokens(transcript)
    if not comment_tokens or not transcript_tokens:
        return False
    common = comment_tokens & transcript_tokens
    if len(common) >= 2:
        return True
    if len(common) >= 1 and len(comment_tokens) <= 4:
        return True

    semantic_pairs = [
        r"(кп|предлож\w*|коммерческ\w*|отправ\w*|направ\w*|вышл\w*)",
        r"(перезвон\w*|созвон\w*|связ\w*|контакт\w*)",
        r"(счет|сч[её]т|оплат\w*|платеж\w*)",
        r"(договор\w*|документ\w*)",
        r"(уточн\w*|соглас\w*|провер\w*)",
    ]
    comment_l = comment.lower()
    transcript_l = transcript.lower()
    return any(re.search(pattern, comment_l) and re.search(pattern, transcript_l) for pattern in semantic_pairs)


def _best_matching_comment(comments: list[str], next_steps: list[dict[str, Any]], text: str) -> str:
    crm_texts = [str(comment or "").strip() for comment in comments if str(comment or "").strip()]
    crm_texts.extend(
        _next_step_text(step) for step in next_steps if _next_step_text(step)
    )
    for comment in crm_texts:
        if _comment_matches_call(comment, text):
            return comment
    return ""


def _next_step_summary(next_steps: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for step in next_steps[:3]:
        subject = str(step.get("SUBJECT") or "").strip()
        deadline = str(step.get("DEADLINE") or step.get("END_TIME") or "").strip()
        comment = _next_step_comment_text(step)
        item = subject or comment or f"ID {step.get('ID')}"
        if deadline:
            item = f"{item}; срок: {deadline}"
        parts.append(item)
    return " | ".join(parts)


def compute_deal_quality(
    deal: dict[str, Any],
    comments: list[str],
    kpi: dict[str, Any],
    *,
    transcript_text: str = "",
    next_steps: list[dict[str, Any]] | None = None,
    short_call_without_conversation: bool = False,
) -> dict[str, Any]:
    has_contact = bool(deal.get("CONTACT_ID") or deal.get("COMPANY_ID"))
    has_amount = bool(str(deal.get("OPPORTUNITY") or "").strip() not in {"", "0", "0.00"})
    has_title = bool(str(deal.get("TITLE") or "").strip())
    weights: dict[str, Any] = kpi.get("deal_quality_weights", {})
    comment_weight = float(weights.get("comment_matches_call", 40))
    next_step_weight = float(weights.get("has_next_step_activity", 30))
    next_step_comment_weight = float(weights.get("next_step_has_comment", 20))
    next_step_deadline_weight = float(weights.get("next_step_not_overdue", 10))
    next_steps = next_steps or []
    active_next_steps = [step for step in next_steps if isinstance(step, dict)]
    has_next_step_activity = bool(active_next_steps)
    next_step_has_comment = any(bool(_next_step_comment_text(step)) for step in active_next_steps)
    next_step_not_overdue = any(
        _deadline_not_overdue(step.get("DEADLINE") or step.get("END_TIME"))
        for step in active_next_steps
    )
    matching_comment = _best_matching_comment(comments, active_next_steps, transcript_text)
    has_relevant_comment = bool(matching_comment)

    if short_call_without_conversation:
        score = 0.0
        short_next_step_weight = 40.0
        short_comment_weight = 30.0
        short_deadline_weight = 30.0
        score += short_next_step_weight if has_next_step_activity else 0.0
        score += short_comment_weight if next_step_has_comment else 0.0
        score += short_deadline_weight if next_step_not_overdue else 0.0
        details = (
            "Короткий звонок без полноценного разговора: оценивается не содержание звонка, "
            "а контроль следующего касания. "
            f"Создано дело/следующий шаг: {'да' if has_next_step_activity else 'нет'} "
            f"({short_next_step_weight:g} баллов); "
            f"в деле есть комментарий/описание: {'да' if next_step_has_comment else 'нет'} "
            f"({short_comment_weight:g} баллов); "
            f"срок дела не просрочен: {'да' if next_step_not_overdue else 'нет'} "
            f"({short_deadline_weight:g} баллов)."
        )
        has_comments = next_step_has_comment
    else:
        score = 0.0
        score += comment_weight if has_relevant_comment else 0.0
        score += next_step_weight if has_next_step_activity else 0.0
        score += next_step_comment_weight if next_step_has_comment else 0.0
        score += next_step_deadline_weight if next_step_not_overdue else 0.0
        details = (
            "Критерии заполнения сделки: "
            f"комментарий соответствует содержанию звонка: {'да' if has_relevant_comment else 'нет'} "
            f"({comment_weight:g} баллов); "
            f"создано дело/следующий шаг: {'да' if has_next_step_activity else 'нет'} "
            f"({next_step_weight:g} баллов); "
            f"в деле есть комментарий/описание: {'да' if next_step_has_comment else 'нет'} "
            f"({next_step_comment_weight:g} баллов); "
            f"срок дела не просрочен: {'да' if next_step_not_overdue else 'нет'} "
            f"({next_step_deadline_weight:g} баллов). "
            "Контакт/компания, сумма и название сделки не учитываются."
        )
        has_comments = has_relevant_comment

    score = round(score, 2)
    details = (
        details
        + (
            f" Следующее дело: {_next_step_summary(active_next_steps)}."
            if active_next_steps
            else " Следующее дело не найдено."
        )
    )
    return {
        "deal_quality_score": score,
        "deal_quality_details": details,
        "has_contact": has_contact,
        "has_amount": has_amount,
        "has_title": has_title,
        "has_comments": has_comments,
        "has_relevant_crm_comment": has_relevant_comment,
        "crm_comment_matches_call": has_relevant_comment,
        "crm_comment_match_text": matching_comment,
        "has_next_step_activity": has_next_step_activity,
        "next_step_activity_has_comment": next_step_has_comment,
        "next_step_activity_not_overdue": next_step_not_overdue,
        "next_step_activity_summary": _next_step_summary(active_next_steps),
        "deal_quality_short_call_mode": bool(short_call_without_conversation),
    }


def crm_call_alignment(
    deal: dict[str, Any],
    text: str,
    comments: list[str],
    kpi: dict[str, Any],
    *,
    next_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    transcript = (text or "").lower()
    title_words = [
        word
        for word in re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", str(deal.get("TITLE") or "").lower())[:6]
    ]
    title_hits = sum(1 for word in title_words if word in transcript)
    amount = str(deal.get("OPPORTUNITY") or "").split(".")[0]
    amount_mentioned = bool(amount and amount != "0" and amount in transcript)
    next_steps = next_steps or []
    crm_notes = list(comments)
    crm_notes.extend(_next_step_text(step) for step in next_steps if _next_step_text(step))
    comments_text = " ".join(crm_notes).lower()
    next_step_re = (
        r"\b(перезвон\w*|встреч\w*|созвон\w*|отправ\w*|вышл\w*|уточн\w*|согласу\w*|кп|договор\w*)\b"
    )
    next_step_synced = bool(
        re.search(next_step_re, transcript) and re.search(next_step_re, comments_text)
    )
    align_score = 100.0 if next_step_synced else 0.0
    next_step_details = (
        "Да: следующий шаг звучит в разговоре и зафиксирован в комментариях/таймлайне CRM."
        if next_step_synced
        else "Нет: следующий шаг либо не прозвучал в разговоре, либо не зафиксирован в CRM. Это мешает контролировать дальнейшее действие по клиенту."  # noqa: E501
    )
    next_step_text = "да" if next_step_synced else "нет"
    details = (
        "Связь звонка с CRM показывает, зафиксирован ли следующий шаг из разговора в CRM: "
        f"следующий шаг синхронизирован с CRM: {next_step_text}. "
        "Сумма и название сделки не снижают эту оценку."
    )
    return {
        "alignment_score": float(align_score),
        "alignment_details": details,
        "title_mentions": title_hits,
        "amount_mentioned": amount_mentioned,
        "next_step_synced": next_step_synced,
        "next_step_synced_details": next_step_details,
    }


def analyze_transcript_improvements(text: str, row: dict[str, Any]) -> dict[str, Any]:
    raw = text or ""
    lower = raw.lower()
    objections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

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

    improvement_items: list[str] = []
    if not row.get("has_greeting"):
        improvement_items.append("Нет явного приветствия и представления.")
    if not row.get("has_needs_discovery"):
        improvement_items.append(
            "Слабо выявлены потребности: не видно уточняющих вопросов о задаче клиента."
        )
    if not row.get("has_next_step_phrase"):
        improvement_items.append("Не зафиксирован конкретный следующий шаг.")

    unhandled = [objection for objection in objections if not objection["handled"]]
    if unhandled:
        improvement_items.append(
            "Есть неотработанные возражения: "
            + "; ".join(o["objection_type"] for o in unhandled[:5])
            + "."
        )
    elif objections:
        improvement_items.append(
            "Возражения найдены и в целом отработаны, но стоит фиксировать следующий шаг после ответа."  # noqa: E501
        )

    marked_lines: list[str] = []
    for objection in objections:
        status = objection["objection_status"]
        marker = "ТРЕБУЕТ ОТРАБОТКИ" if status == "не отработано" else "ОТРАБОТАНО"
        marked_lines.append(
            f"[ВОЗРАЖЕНИЕ: {objection['objection_type']} | {marker}]\n"
            f"{objection['objection_fragment']}\n"
            f"[ВАРИАНТ ОТРАБОТКИ] {objection['objection_recommendation']}"
        )

    if not marked_lines and improvement_items:
        marked_lines.append(
            "[МОМЕНТЫ ДЛЯ УЛУЧШЕНИЯ]\n" + "\n".join(f"- {item}" for item in improvement_items)
        )

    transcript_marked = raw
    if marked_lines:
        transcript_marked = "\n\n".join(marked_lines) + "\n\n[ПОЛНАЯ РАСШИФРОВКА]\n" + raw

    recommendations = [objection["objection_recommendation"] for objection in unhandled]
    if not recommendations and objections:
        recommendations = [
            "После ответа на возражение обязательно закрепить следующий шаг: дата, действие, ответственный."  # noqa: E501
        ]

    return {
        "objections_count": len(objections),
        "unhandled_objections_count": len(unhandled),
        "objections_handled": bool(objections and not unhandled),
        "objections_found": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']} ({o['objection_status']})"
            for o in objections
        ),
        "unhandled_objections": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']}" for o in unhandled
        ),
        "objection_recommendations": "\n".join(dict.fromkeys(recommendations)),
        "improvement_moments": "\n".join(improvement_items),
        "transcript_marked": transcript_marked,
        "objection_rows": objections,
    }


async def apply_scores(
    row: dict[str, Any],
    deal: dict[str, Any],
    comments: list[str],
    text: str,
    kpi: dict[str, Any],
    suffix: str = "",
    codex_evaluator: Any = None,
    next_steps: list[dict[str, Any]] | None = None,
    short_call_without_conversation: bool = False,
) -> None:
    first_h = row.get("first_response_hours")
    first_m = row.get("first_response_minutes")
    sla_cfg = kpi.get("sla", {})
    first_response_sla = float(sla_cfg.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    if first_h is None and first_m is not None:
        first_h = float(first_m) / 60.0
    row[f"first_response_sla_ok{suffix}"] = (
        first_h is not None and float(first_h) <= first_response_sla
    )

    deal_q = compute_deal_quality(
        deal,
        comments,
        kpi,
        transcript_text=text,
        next_steps=next_steps,
        short_call_without_conversation=short_call_without_conversation,
    )
    call_q = evaluate_call_text(text, kpi)
    align = crm_call_alignment(deal, text, comments, kpi, next_steps=next_steps)
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
    row: dict[str, Any],
    deal: dict[str, Any],
    comments: list[str],
    bitnewton_text: str,
    bitrix_text: str,
    kpi: dict[str, Any],
    kpi_cmp: dict[str, Any] | None,
    codex_evaluator: Any = None,
    next_steps: list[dict[str, Any]] | None = None,
) -> None:
    analysis_text = merged_transcript_text(bitnewton_text or "", bitrix_text or "")
    row["combined_transcript_text"] = analysis_text
    await apply_scores(
        row,
        deal,
        comments,
        analysis_text,
        kpi,
        suffix="",
        codex_evaluator=codex_evaluator,
        next_steps=next_steps,
    )
    if kpi_cmp is not None:
        await apply_scores(
            row,
            deal,
            comments,
            analysis_text,
            kpi_cmp,
            suffix="_cmp",
            codex_evaluator=None,
            next_steps=next_steps,
        )
        row["overall_score_delta"] = round(
            float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2
        )
    row.update(analyze_transcript_improvements(analysis_text, row))
    call_conclusion, call_recommendations = call_quality_conclusion(row)
    row["call_quality_conclusion"] = call_conclusion
    row["recommendations"] = call_recommendations
    row["conversation_meaning"] = conversation_meaning(analysis_text, row)


def refresh_crm_scores_after_stage_metrics(
    rows: list[dict[str, Any]], kpi: dict[str, Any], kpi_cmp: dict[str, Any] | None = None
) -> None:
    for row in rows:
        crm_q = evaluate_crm_checklist(row, include_stage=True)
        row.update(crm_q)
        recalculate_overall_score(row, kpi, suffix="")
        if kpi_cmp is not None:
            row["crm_work_score_cmp"] = crm_q.get("crm_work_score")
            row["crm_checklist_percent_cmp"] = crm_q.get("crm_checklist_percent")
            recalculate_overall_score(row, kpi_cmp, suffix="_cmp")
            row["overall_score_delta"] = round(
                float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2
            )


async def recompute_existing_row(
    row: dict[str, Any],
    kpi: dict[str, Any],
    kpi_cmp: dict[str, Any] | None = None,
    codex_evaluator: Any = None,
) -> dict[str, Any]:
    recalculated = dict(row)
    recalculated["kpi_profile"] = (kpi.get("profile") or {}).get("name")
    recalculated["kpi_version"] = (kpi.get("profile") or {}).get("version")
    if kpi_cmp is not None:
        recalculated["kpi_profile_cmp"] = (kpi_cmp.get("profile") or {}).get("name")
        recalculated["kpi_version_cmp"] = (kpi_cmp.get("profile") or {}).get("version")

    text = str(
        recalculated.get("combined_transcript_text") or recalculated.get("transcript_text") or ""
    ).strip()
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
        recalculated["call_quality_details"] = (
            "Качество разговора не рассчитано: нет сохраненной расшифровки."
        )
        recalculated.update(evaluate_crm_checklist(recalculated, include_stage=True))
        recalculate_overall_score(recalculated, kpi)
        return recalculated

    for key, value in evaluate_call_text(analysis_text, kpi).items():
        recalculated[key] = value

    if codex_evaluator is not None:
        codex_res = await codex_evaluator.evaluate_transcript(
            analysis_text, {"deal_id": recalculated.get("deal_id")}
        )
        recalculated.update(codex_res)

    recalculated.update(evaluate_crm_checklist(recalculated, include_stage=True))
    recalculate_overall_score(recalculated, kpi)

    recalculated.update(analyze_transcript_improvements(analysis_text, recalculated))
    call_conclusion, call_recommendations = call_quality_conclusion(recalculated)
    recalculated["call_quality_conclusion"] = call_conclusion
    recalculated["recommendations"] = call_recommendations
    recalculated["conversation_meaning"] = conversation_meaning(analysis_text, recalculated)

    if kpi_cmp is not None:
        tmp = await recompute_existing_row(
            {**recalculated, "overall_score": None}, kpi_cmp, None, None
        )
        for key in [
            "call_quality_score",
            "deal_quality_score",
            "alignment_score",
            "crm_work_score",
            "overall_score",
        ]:
            if key in tmp:
                recalculated[f"{key}_cmp"] = tmp.get(key)
        recalculated["overall_score_delta"] = round(
            float(recalculated.get("overall_score_cmp") or 0.0)
            - float(recalculated.get("overall_score") or 0.0),
            2,
        )

    return recalculated
