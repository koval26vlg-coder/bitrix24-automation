from __future__ import annotations

from typing import Any

from pipelines.scoring.utils import _clean_text_for_report


def quality_label(score: float) -> str:
    if score >= 80:
        return "сильное"
    if score >= 60:
        return "нормальное"
    if score >= 40:
        return "слабое"
    return "критически слабое"


def call_quality_conclusion(row: dict[str, Any]) -> tuple[str, str]:
    score = float(row.get("call_quality_score") or 0.0)
    missing: list[str] = []
    blocks = row.get("call_checklist_blocks") or []
    if isinstance(blocks, list) and blocks:
        weak_blocks = [
            str(block.get("sales_stage_block_name") or "")
            for block in blocks
            if isinstance(block, dict) and float(block.get("sales_stage_percent") or 0.0) < 70
        ]
        missing.extend([x for x in weak_blocks if x])
    else:
        if not row.get("has_greeting"):
            missing.append("приветствие")
        if not row.get("has_needs_discovery"):
            missing.append("выявление потребностей")
        if int(row.get("objections_count") or 0) > 0 and not row.get("has_objection_work"):
            missing.append("работа с возражениями")
        if not row.get("has_next_step_phrase"):
            missing.append("фиксированный следующий шаг")

    if score >= 80:
        conclusion = "Разговор структурный: есть основные элементы продажного диалога."
    elif score >= 60:
        conclusion = "Разговор рабочий, но часть обязательных элементов требует усиления."
    elif score >= 40:
        conclusion = (
            "Разговор частично проработан: клиенту не хватает ясной структуры и завершения."
        )
    else:
        conclusion = "Разговор слабый: ключевые элементы проработки клиента почти не зафиксированы."

    recs = []
    if missing:
        recs.append("Усилить: " + ", ".join(missing) + ".")
    if int(row.get("unhandled_objections_count") or 0) > 0:
        recs.append(
            "Вернуться к неотработанным возражениям и дать клиенту альтернативу/ценность/следующий шаг."  # noqa: E501
        )
    if not row.get("next_step_synced"):
        recs.append("Зафиксировать следующий шаг в разговоре и в CRM.")
    objection_recs = str(row.get("objection_recommendations") or "").strip()
    if objection_recs:
        recs.append(objection_recs)
    if not recs:
        recs.append("Поддерживать текущую структуру разговора.")
    return conclusion, " ".join(recs)


def conversation_meaning(text: str, row: dict[str, Any]) -> str:
    import re

    t = (text or "").lower()
    topics: list[str] = []
    topic_rules = [
        ("цена/стоимость", r"\b(цен\w*|стоимост\w*|дорог\w*|бюджет)\b"),
        ("счет/оплата", r"\b(счет|оплат\w*|предоплат\w*|платеж)\b"),
        ("КП/договор", r"\b(кп|коммерческ\w*|договор\w*)\b"),
        ("технические условия", r"\b(тех\w*|интеграц\w*|настройк\w*|касс\w*|оборудован\w*)\b"),
        (
            "сроки/следующий контакт",
            r"\b(срок\w*|перезвон\w*|созвон\w*|встреч\w*|завтра|сегодня)\b",
        ),
    ]
    for label, pattern in topic_rules:
        if re.search(pattern, t):
            topics.append(label)
    if not topics:
        topics.append("общая консультация по сделке")

    unique_topics = ", ".join(dict.fromkeys(topics))
    parts = [f"Смысл разговора: обсуждались {unique_topics}."]
    if row.get("has_needs_discovery"):
        parts.append("Потребности клиента в разговоре частично выявлены.")
    else:
        parts.append("Потребности клиента выражены слабо: нужно больше уточняющих вопросов.")
    if row.get("has_objection_work"):
        parts.append("Возражения или сомнения клиента в разговоре затронуты.")
    if row.get("has_next_step_phrase"):
        parts.append("Следующий шаг в разговоре прозвучал.")
    else:
        parts.append("Следующий шаг не закреплен явно.")
    if row.get("next_step_synced"):
        parts.append("Следующий шаг совпадает с фиксацией в CRM.")
    else:
        parts.append("Следующий шаг нужно отдельно зафиксировать в CRM.")
    unhandled = str(row.get("unhandled_objections") or "").strip()
    if unhandled:
        parts.append("Есть неотработанные возражения: " + _clean_text_for_report(unhandled)[:220])
    return " ".join(parts)


def transcript_match_score(bitnewton_text: str, bitrix_text: str) -> float | None:
    import re

    a = set(re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", (bitnewton_text or "").lower()))
    b = set(re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", (bitrix_text or "").lower()))
    if not a or not b:
        return None
    return round((len(a & b) / max(1, len(a | b))) * 100.0, 1)


def merged_transcript_text(bitnewton_text: str, bitrix_text: str) -> str:
    bn = (bitnewton_text or "").strip()
    bx = (bitrix_text or "").strip()
    if not bx:
        return bn
    score = transcript_match_score(bn, bx)
    if not bn:
        return bx
    if score is not None and score >= 85:
        return bn
    return f"[Bit.Newton]\n{bn}\n\n[Bitrix карточка]\n{bx}"
