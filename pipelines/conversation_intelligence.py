from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from pipelines.scoring import HANDLING_RE, OBJECTION_RULES
from pipelines.stages import stage_display_name


CONVERSATION_MAP_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "call_number",
    "subject",
    "duration_minutes",
    "ci_moment_type",
    "ci_moment_risk",
    "ci_moment_fragment",
    "ci_moment_recommendation",
    "ci_moment_source",
    "ci_confidence",
]

CI_OBJECTION_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "call_number",
    "subject",
    "objection_type",
    "objection_status",
    "objection_fragment",
    "objection_recommendations",
    "ci_next_manager_action",
    "ci_confidence",
]

EMOTIONAL_RISK_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "call_number",
    "subject",
    "duration_minutes",
    "ci_emotion_state",
    "ci_emotional_risk_level",
    "ci_emotional_risk_score",
    "ci_uncertainty_hits",
    "ci_negative_hits",
    "ci_manager_uncertainty_hits",
    "ci_unhandled_objections_count",
    "ci_questions_count",
    "ci_next_step_present",
    "ci_risk_evidence",
    "ci_recommendation",
    "ci_confidence",
]

CONVERSION_FACTOR_COLUMNS = [
    "ci_conversion_factor",
    "ci_factor_source",
    "ci_factor_priority",
    "ci_affected_deals",
    "ci_affected_calls",
    "ci_factor_share_percent",
    "ci_avg_overall_score",
    "ci_avg_call_quality_score",
    "ci_expected_effect",
    "ci_conversion_action",
]

MANAGER_RECOMMENDATION_COLUMNS = [
    "manager_name",
    "ci_manager_priority",
    "ci_manager_deals",
    "ci_manager_calls",
    "ci_high_risk_calls",
    "ci_unhandled_objections_count",
    "ci_no_next_step_count",
    "ci_low_crm_count",
    "ci_main_growth_area",
    "ci_manager_recommendation",
    "ci_manager_next_action",
]


TEXT_RISK_RULES = [
    (
        "Сомнение клиента",
        re.compile(
            r"\b(подумаю|подумаем|сомнева\w*|не уверен\w*|не уверена|не готовы?|"
            r"не готова|надо обсудить|нужно подумать|я не знаю|не знаю)\b",
            re.IGNORECASE,
        ),
        "Уточнить источник сомнения, вернуть клиента к ценности решения и закрепить следующий шаг.",
        "Высокий",
    ),
    (
        "Негатив или отказ",
        re.compile(
            r"\b(дорого|не подходит|не устраивает|не ?интересно|не нужно|отказ\w*|"
            r"не хочу|нет времени|проблем\w*|жалоб\w*|недовол\w*)\b",
            re.IGNORECASE,
        ),
        "Признать позицию клиента, уточнить причину отказа и дать короткий аргумент под его задачу.",
        "Высокий",
    ),
    (
        "Неуверенная формулировка в диалоге",
        re.compile(
            r"\b(наверное|возможно|как бы|постараюсь|попробуем|если получится|может быть)\b",
            re.IGNORECASE,
        ),
        "Заменить неуверенную формулировку на конкретное действие, срок и ответственного.",
        "Средний",
    ),
]

QUESTION_RE = re.compile(r"\b(что|как|когда|почему|зачем|сколько|какой|какая|какие|где)\b", re.IGNORECASE)
NEXT_STEP_RE = re.compile(
    r"\b(перезвон\w*|созвон\w*|встреч\w*|отправ\w*|вышл\w*|"
    r"согласу\w*|уточн\w*|договор\w*|следующ\w* шаг)\b",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _analysis_text(row: dict[str, Any]) -> str:
    for key in ("combined_transcript_text", "transcript_text", "bitrix_card_transcript"):
        text = _clean_text(row.get(key))
        if text:
            return text
    return ""


def _context(text: str, start: int, end: int, radius: int = 190) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    fragment = re.sub(r"\s+", " ", text[left:right]).strip()
    if left > 0:
        fragment = "..." + fragment
    if right < len(text):
        fragment += "..."
    return fragment


def _call_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("start_time") or ""), str(row.get("activity_id") or ""))


def _deal_group_key(row: dict[str, Any]) -> str:
    return str(row.get("deal_id") or row.get("deal_url") or "unknown")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _risk_priority(level: str) -> int:
    if level == "Критичный":
        return 0
    if level == "Высокий":
        return 1
    if level == "Средний":
        return 2
    return 3


def _risk_level(score: float) -> str:
    if score >= 70:
        return "Критичный"
    if score >= 45:
        return "Высокий"
    if score >= 25:
        return "Средний"
    return "Низкий"


def _stage_name(row: dict[str, Any]) -> str:
    return str(row.get("stage_name") or stage_display_name(row.get("stage_id")) or "")


def _base_row(row: dict[str, Any], call_number: int) -> dict[str, Any]:
    return {
        "deal_url": row.get("deal_url"),
        "stage_name": _stage_name(row),
        "manager_name": row.get("manager_name"),
        "call_number": call_number,
        "subject": row.get("subject"),
        "duration_minutes": row.get("duration_minutes"),
    }


def _normalize_existing_objection(objection: dict[str, Any]) -> dict[str, Any]:
    status = str(objection.get("objection_status") or "").strip()
    status_l = status.lower()
    handled = bool(objection.get("handled")) or ("отработано" in status_l and "не отработано" not in status_l)
    return {
        "objection_type": str(objection.get("objection_type") or "Возражение").strip(),
        "objection_fragment": _clean_text(objection.get("objection_fragment")),
        "objection_status": "отработано" if handled else "не отработано",
        "objection_recommendation": _clean_text(objection.get("objection_recommendation")),
        "handled": handled,
    }


def detect_objections(row: dict[str, Any], text: str) -> list[dict[str, Any]]:
    existing = row.get("objection_rows")
    if isinstance(existing, list) and existing:
        objections = [_normalize_existing_objection(item) for item in existing if isinstance(item, dict)]
        return [item for item in objections if item.get("objection_fragment")]

    lower = text.lower()
    objections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for label, pattern, suggestion in OBJECTION_RULES:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            fragment = _context(text, match.start(), match.end())
            key = (str(label), fragment[:160])
            if key in seen:
                continue
            seen.add(key)
            after = lower[match.end() : match.end() + 420]
            handled = bool(HANDLING_RE.search(after))
            objections.append(
                {
                    "objection_type": str(label),
                    "objection_fragment": fragment,
                    "objection_status": "отработано" if handled else "не отработано",
                    "objection_recommendation": str(suggestion),
                    "handled": handled,
                }
            )
    return objections


def detect_text_risks(text: str) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for label, pattern, recommendation, severity in TEXT_RISK_RULES:
        for match in pattern.finditer(text):
            fragment = _context(text, match.start(), match.end())
            key = (label, fragment[:160])
            if key in seen:
                continue
            seen.add(key)
            risks.append(
                {
                    "risk_type": label,
                    "risk_severity": severity,
                    "risk_fragment": fragment,
                    "risk_recommendation": recommendation,
                }
            )
    return risks


def _question_count(text: str) -> int:
    return text.count("?") + len(QUESTION_RE.findall(text))


def _evidence(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    return "\n".join(cleaned[:8])


def analyze_call(row: dict[str, Any], call_number: int) -> dict[str, Any] | None:
    text = _analysis_text(row)
    if not text:
        return None

    objections = detect_objections(row, text)
    text_risks = detect_text_risks(text)
    unhandled = [item for item in objections if not item.get("handled")]
    uncertainty_hits = [item for item in text_risks if item["risk_type"] == "Сомнение клиента"]
    negative_hits = [item for item in text_risks if item["risk_type"] == "Негатив или отказ"]
    manager_uncertainty_hits = [
        item for item in text_risks if item["risk_type"] == "Неуверенная формулировка в диалоге"
    ]
    questions_count = _question_count(text)
    next_step_present = bool(row.get("has_next_step_phrase")) or bool(NEXT_STEP_RE.search(text))
    needs_present = bool(row.get("has_needs_discovery"))
    crm_percent = _safe_float(row.get("crm_checklist_percent"))
    call_percent = _safe_float(row.get("call_checklist_percent"))

    score = 0.0
    score += min(40, len(unhandled) * 22)
    score += min(24, len(uncertainty_hits) * 8)
    score += min(24, len(negative_hits) * 10)
    score += min(14, len(manager_uncertainty_hits) * 5)
    if not next_step_present:
        score += 15
    if not needs_present:
        score += 12
    if crm_percent is not None and crm_percent < 70:
        score += 10
    if call_percent is not None and call_percent < 70:
        score += 10
    score = min(100.0, round(score, 2))
    level = _risk_level(score)

    if negative_hits:
        state = "Негатив/отказ"
    elif uncertainty_hits or unhandled:
        state = "Сомнение клиента"
    elif manager_uncertainty_hits:
        state = "Неуверенность в диалоге"
    else:
        state = "Нейтрально"

    evidence_parts = []
    evidence_parts.extend(item["objection_fragment"] for item in unhandled[:3])
    evidence_parts.extend(item["risk_fragment"] for item in text_risks[:5])
    if not next_step_present:
        evidence_parts.append("В разговоре не найден конкретный следующий шаг.")
    if not needs_present:
        evidence_parts.append("В разговоре слабо видно выявление потребности.")

    recommendations = []
    if unhandled:
        recommendations.append("Отработать возражение по схеме: признать, уточнить, аргументировать, закрепить следующий шаг.")
    if uncertainty_hits:
        recommendations.append("Уточнять причину сомнения и переводить ответ клиента в конкретное следующее действие.")
    if negative_hits:
        recommendations.append("Фиксировать причину негатива/отказа и подбирать аргумент под задачу клиента.")
    if not next_step_present:
        recommendations.append("В конце каждого звонка фиксировать дату, действие и ответственного.")
    if not recommendations:
        recommendations.append("Продолжать контроль структуры разговора и качества фиксации результата в CRM.")

    return {
        "row": row,
        "base": _base_row(row, call_number),
        "text": text,
        "objections": objections,
        "text_risks": text_risks,
        "unhandled": unhandled,
        "uncertainty_count": len(uncertainty_hits),
        "negative_count": len(negative_hits),
        "manager_uncertainty_count": len(manager_uncertainty_hits),
        "questions_count": questions_count,
        "next_step_present": next_step_present,
        "needs_present": needs_present,
        "crm_percent": crm_percent,
        "call_percent": call_percent,
        "risk_score": score,
        "risk_level": level,
        "emotion_state": state,
        "risk_evidence": _evidence(evidence_parts),
        "recommendation": "\n".join(dict.fromkeys(recommendations)),
        "confidence": "Средняя: вывод сделан по тексту расшифровки, без акустической модели интонаций.",
    }


def _build_conversation_map_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for analysis in analyses:
        base = analysis["base"]
        for objection in analysis["objections"]:
            handled = bool(objection.get("handled"))
            out.append(
                {
                    **base,
                    "ci_moment_type": "Возражение клиента",
                    "ci_moment_risk": "Средний" if handled else "Критичный",
                    "ci_moment_fragment": objection.get("objection_fragment"),
                    "ci_moment_recommendation": objection.get("objection_recommendation"),
                    "ci_moment_source": "Текст расшифровки",
                    "ci_confidence": analysis["confidence"],
                }
            )
        for risk in analysis["text_risks"][:8]:
            out.append(
                {
                    **base,
                    "ci_moment_type": risk.get("risk_type"),
                    "ci_moment_risk": risk.get("risk_severity"),
                    "ci_moment_fragment": risk.get("risk_fragment"),
                    "ci_moment_recommendation": risk.get("risk_recommendation"),
                    "ci_moment_source": "Текстовый индикатор",
                    "ci_confidence": analysis["confidence"],
                }
            )
        row = analysis["row"]
        for item in row.get("call_checklist_items") or []:
            if not isinstance(item, dict):
                continue
            score = _safe_float(item.get("checklist_score")) or 0.0
            max_score = _safe_float(item.get("checklist_max_score")) or 1.0
            if score >= max_score:
                continue
            fragment = _clean_text(item.get("checklist_evidence") or item.get("checklist_comment"))
            out.append(
                {
                    **base,
                    "ci_moment_type": f"Провал этапа: {item.get('checklist_criterion') or ''}".strip(),
                    "ci_moment_risk": "Высокий" if score == 0 else "Средний",
                    "ci_moment_fragment": fragment,
                    "ci_moment_recommendation": _clean_text(item.get("checklist_comment"))
                    or "Разобрать критерий чек-листа с менеджером.",
                    "ci_moment_source": "Чек-лист звонка",
                    "ci_confidence": "Высокая: критерий уже рассчитан по чек-листу звонка.",
                }
            )
    return sorted(out, key=lambda row: (_risk_priority(str(row.get("ci_moment_risk") or "")), str(row.get("manager_name") or "")))


def _build_objection_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for analysis in analyses:
        for objection in analysis["objections"]:
            handled = bool(objection.get("handled"))
            next_action = (
                "Разобрать с менеджером конкретную отработку возражения и закрепление следующего шага."
                if not handled
                else "Проверить, был ли после ответа зафиксирован следующий шаг в CRM."
            )
            out.append(
                {
                    **analysis["base"],
                    "objection_type": objection.get("objection_type"),
                    "objection_status": objection.get("objection_status"),
                    "objection_fragment": objection.get("objection_fragment"),
                    "objection_recommendations": objection.get("objection_recommendation"),
                    "ci_next_manager_action": next_action,
                    "ci_confidence": analysis["confidence"],
                }
            )
    return sorted(out, key=lambda row: (str(row.get("objection_status") or ""), str(row.get("manager_name") or "")))


def _build_emotional_risk_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for analysis in analyses:
        out.append(
            {
                **analysis["base"],
                "ci_emotion_state": analysis["emotion_state"],
                "ci_emotional_risk_level": analysis["risk_level"],
                "ci_emotional_risk_score": analysis["risk_score"],
                "ci_uncertainty_hits": analysis["uncertainty_count"],
                "ci_negative_hits": analysis["negative_count"],
                "ci_manager_uncertainty_hits": analysis["manager_uncertainty_count"],
                "ci_unhandled_objections_count": len(analysis["unhandled"]),
                "ci_questions_count": analysis["questions_count"],
                "ci_next_step_present": analysis["next_step_present"],
                "ci_risk_evidence": analysis["risk_evidence"],
                "ci_recommendation": analysis["recommendation"],
                "ci_confidence": analysis["confidence"],
            }
        )
    return sorted(
        out,
        key=lambda row: (
            _risk_priority(str(row.get("ci_emotional_risk_level") or "")),
            -float(row.get("ci_emotional_risk_score") or 0.0),
        ),
    )


def _add_factor(bucket: dict[str, Any], analysis: dict[str, Any], factor: str, priority: str, action: str, source: str) -> None:
    item = bucket.setdefault(
        factor,
        {
            "ci_conversion_factor": factor,
            "ci_factor_source": source,
            "ci_factor_priority": priority,
            "ci_affected_deals_set": set(),
            "ci_affected_calls": 0,
            "overall_scores": [],
            "call_scores": [],
            "ci_conversion_action": action,
        },
    )
    item["ci_affected_deals_set"].add(_deal_group_key(analysis["row"]))
    item["ci_affected_calls"] += 1
    overall = _safe_float(analysis["row"].get("overall_score"))
    call_score = _safe_float(analysis["row"].get("call_quality_score"))
    if overall is not None:
        item["overall_scores"].append(overall)
    if call_score is not None:
        item["call_scores"].append(call_score)


def _priority_for_factor(name: str, count: int) -> str:
    if "Неотработанные" in name or "Негатив" in name:
        return "Критичный" if count >= 3 else "Высокий"
    return "Высокий" if count >= 3 else "Средний"


def _build_conversion_factor_rows(
    analyses: list[dict[str, Any]],
    lost_reason_summary_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    total_deals = max(1, len({_deal_group_key(analysis["row"]) for analysis in analyses}))
    bucket: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        if analysis["unhandled"]:
            _add_factor(
                bucket,
                analysis,
                "Неотработанные возражения",
                "Высокий",
                "Ввести обязательный разбор возражений и библиотеку ответов по типовым причинам отказа.",
                "Расшифровки звонков",
            )
        if analysis["negative_count"]:
            _add_factor(
                bucket,
                analysis,
                "Негатив или отказ в разговоре",
                "Высокий",
                "Фиксировать причину негатива и проверять, предложил ли менеджер альтернативный вариант.",
                "Расшифровки звонков",
            )
        if analysis["uncertainty_count"]:
            _add_factor(
                bucket,
                analysis,
                "Сомнение клиента",
                "Средний",
                "Добавить сценарий уточнения сомнения: причина, критерий выбора, следующий шаг.",
                "Расшифровки звонков",
            )
        if not analysis["next_step_present"]:
            _add_factor(
                bucket,
                analysis,
                "Нет закрепленного следующего шага",
                "Высокий",
                "Сделать следующий шаг обязательным результатом звонка и контролировать его в CRM.",
                "Расшифровки + CRM",
            )
        if not analysis["needs_present"]:
            _add_factor(
                bucket,
                analysis,
                "Слабо выявлена потребность",
                "Средний",
                "Добавить 3-5 обязательных вопросов до презентации решения.",
                "Чек-лист звонка",
            )
        if analysis["crm_percent"] is not None and analysis["crm_percent"] < 70:
            _add_factor(
                bucket,
                analysis,
                "Слабое ведение CRM",
                "Высокий",
                "Контролировать обязательные поля, следующий шаг и соответствие стадии фактической ситуации.",
                "CRM-чек-лист",
            )

    out: list[dict[str, Any]] = []
    for factor, item in bucket.items():
        deals = len(item["ci_affected_deals_set"])
        calls = int(item["ci_affected_calls"])
        overall_scores = item["overall_scores"]
        call_scores = item["call_scores"]
        priority = _priority_for_factor(factor, calls)
        out.append(
            {
                "ci_conversion_factor": factor,
                "ci_factor_source": item["ci_factor_source"],
                "ci_factor_priority": priority,
                "ci_affected_deals": deals,
                "ci_affected_calls": calls,
                "ci_factor_share_percent": round(deals * 100.0 / total_deals, 2),
                "ci_avg_overall_score": round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else "",
                "ci_avg_call_quality_score": round(sum(call_scores) / len(call_scores), 2) if call_scores else "",
                "ci_expected_effect": "Рост конверсии за счет снижения повторяемой причины потерь.",
                "ci_conversion_action": item["ci_conversion_action"],
            }
        )

    for lost in lost_reason_summary_rows:
        category = _clean_text(lost.get("loss_reason_category"))
        if not category:
            continue
        out.append(
            {
                "ci_conversion_factor": f"Проигрыш: {category}",
                "ci_factor_source": "Проигранные сделки",
                "ci_factor_priority": "Высокий",
                "ci_affected_deals": lost.get("lost_deals_count"),
                "ci_affected_calls": "",
                "ci_factor_share_percent": lost.get("lost_deals_share"),
                "ci_avg_overall_score": "",
                "ci_avg_call_quality_score": "",
                "ci_expected_effect": lost.get("conversion_expected_effect")
                or "Снижение повторяемой причины отказа в проигранных сделках.",
                "ci_conversion_action": lost.get("conversion_next_action") or lost.get("conversion_tools"),
            }
        )

    return sorted(
        out,
        key=lambda row: (
            _risk_priority(str(row.get("ci_factor_priority") or "")),
            -float(row.get("ci_affected_deals") or 0),
        ),
    )


def _build_manager_recommendation_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "manager_name": "",
            "deal_ids": set(),
            "ci_manager_calls": 0,
            "ci_high_risk_calls": 0,
            "ci_unhandled_objections_count": 0,
            "ci_no_next_step_count": 0,
            "ci_low_crm_count": 0,
            "needs_gaps": 0,
        }
    )
    for analysis in analyses:
        manager = str(analysis["row"].get("manager_name") or "Без менеджера")
        item = grouped[manager]
        item["manager_name"] = manager
        item["deal_ids"].add(_deal_group_key(analysis["row"]))
        item["ci_manager_calls"] += 1
        if analysis["risk_level"] in {"Критичный", "Высокий"}:
            item["ci_high_risk_calls"] += 1
        item["ci_unhandled_objections_count"] += len(analysis["unhandled"])
        if not analysis["next_step_present"]:
            item["ci_no_next_step_count"] += 1
        if analysis["crm_percent"] is not None and analysis["crm_percent"] < 70:
            item["ci_low_crm_count"] += 1
        if not analysis["needs_present"]:
            item["needs_gaps"] += 1

    out: list[dict[str, Any]] = []
    for item in grouped.values():
        metrics = [
            ("Отработка возражений", int(item["ci_unhandled_objections_count"])),
            ("Фиксация следующего шага", int(item["ci_no_next_step_count"])),
            ("Ведение CRM", int(item["ci_low_crm_count"])),
            ("Выявление потребности", int(item["needs_gaps"])),
            ("Эмоциональный риск", int(item["ci_high_risk_calls"])),
        ]
        metrics = sorted(metrics, key=lambda pair: pair[1], reverse=True)
        main_area, main_count = metrics[0]
        if main_count >= 5:
            priority = "Критичный"
        elif main_count >= 2:
            priority = "Высокий"
        elif main_count == 1:
            priority = "Средний"
        else:
            priority = "Низкий"
        recommendations = {
            "Отработка возражений": "Провести разбор 3 звонков с неотработанными возражениями и закрепить готовые формулировки ответов.",
            "Фиксация следующего шага": "Проверять, что каждый звонок заканчивается конкретным действием, датой и ответственным.",
            "Ведение CRM": "Проверить заполнение карточек, стадию, следующий шаг и комментарии после звонка.",
            "Выявление потребности": "Отработать блок вопросов до презентации решения.",
            "Эмоциональный риск": "Прослушать звонки с высоким риском и найти моменты сомнения/негатива клиента.",
        }
        out.append(
            {
                "manager_name": item["manager_name"],
                "ci_manager_priority": priority,
                "ci_manager_deals": len(item["deal_ids"]),
                "ci_manager_calls": item["ci_manager_calls"],
                "ci_high_risk_calls": item["ci_high_risk_calls"],
                "ci_unhandled_objections_count": item["ci_unhandled_objections_count"],
                "ci_no_next_step_count": item["ci_no_next_step_count"],
                "ci_low_crm_count": item["ci_low_crm_count"],
                "ci_main_growth_area": main_area,
                "ci_manager_recommendation": recommendations.get(main_area, "Продолжать регулярный контроль звонков."),
                "ci_manager_next_action": "Назначить точечный разбор с руководителем и проверить следующие 5 звонков по этому же критерию.",
            }
        )
    return sorted(out, key=lambda row: (_risk_priority(str(row.get("ci_manager_priority") or "")), str(row.get("manager_name") or "")))


def build_conversation_intelligence(
    rows: list[dict[str, Any]],
    lost_reason_summary_rows: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    analyses: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("no_calls") or row.get("asr_skipped"):
            continue
        grouped[_deal_group_key(row)].append(row)

    for deal_rows in grouped.values():
        for call_number, row in enumerate(sorted(deal_rows, key=_call_sort_key), start=1):
            analysis = analyze_call(row, call_number)
            if analysis is not None:
                analyses.append(analysis)

    lost_reason_summary_rows = lost_reason_summary_rows or []
    return {
        "conversation_map_rows": _build_conversation_map_rows(analyses),
        "objection_rows": _build_objection_rows(analyses),
        "emotional_risk_rows": _build_emotional_risk_rows(analyses),
        "conversion_factor_rows": _build_conversion_factor_rows(analyses, lost_reason_summary_rows),
        "manager_recommendation_rows": _build_manager_recommendation_rows(analyses),
    }
