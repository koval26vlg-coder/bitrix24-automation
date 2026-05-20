from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from pipelines.scoring import CALL_CHECKLIST_BLOCKS, OBJECTION_RULES, evaluate_call_checklist
from pipelines.script_profiles import (
    DEFAULT_SCRIPT_PROFILE_ID,
    ETIQUETTE_SCRIPT_PROFILE_ID,
    PRIMARY_SCRIPT_PROFILE_IDS,
    SCRIPT_PROFILES,
)
from pipelines.stages import stage_display_name


SCRIPT_SCORE_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "call_number",
    "subject",
    "duration_minutes",
    "script_profile_id",
    "script_profile_name",
    "script_block",
    "script_step",
    "script_required_action",
    "script_score",
    "script_max_score",
    "script_score_percent",
    "script_status",
    "script_critical_step",
    "script_critical_error",
    "script_evidence",
    "script_recommendation",
    "script_weight",
]

SCRIPT_PROFILE_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "call_number",
    "subject",
    "duration_minutes",
    "script_profile_id",
    "script_profile_name",
    "script_profile_purpose",
    "script_profile_selected",
    "script_profile_score",
    "script_profile_max_score",
    "script_profile_match_percent",
    "script_profile_status",
    "script_critical_errors_count",
    "script_critical_errors",
    "script_failed_steps",
    "script_profile_recommendation",
]

SCRIPT_GAP_COLUMNS = [
    "manager_name",
    "script_profile_name",
    "script_block",
    "script_step",
    "script_gap_count",
    "script_partial_count",
    "script_calls",
    "script_gap_rate",
    "script_priority",
    "script_training_recommendation",
]


SCRIPT_STEP_METADATA: dict[str, dict[str, Any]] = {
    "contact_greeting": {
        "required_action": "Поприветствовать клиента и представиться в начале разговора.",
        "recommendation": "Сделать обязательную первую фразу: приветствие, имя менеджера, компания.",
        "weight": 1.0,
    },
    "contact_permission": {
        "required_action": "Уточнить, удобно ли клиенту сейчас говорить.",
        "recommendation": "Перед переходом к сути спрашивать разрешение на короткий диалог.",
        "weight": 0.8,
    },
    "contact_name": {
        "required_action": "Обращаться к клиенту по имени или уточнить, как к нему обращаться.",
        "recommendation": "Проверять имя в карточке и использовать его в начале разговора.",
        "weight": 0.7,
    },
    "contact_purpose": {
        "required_action": "Коротко объяснить цель звонка понятным для клиента языком.",
        "recommendation": "Связывать цель звонка с заявкой, задачей или текущей стадией сделки.",
        "weight": 1.0,
    },
    "needs_question_variety": {
        "required_action": "Задать серию уточняющих вопросов разных типов.",
        "recommendation": "До презентации задать минимум 3 вопроса: задача, срок, текущий способ, критерии выбора.",
        "weight": 1.4,
    },
    "needs_sequence": {
        "required_action": "Выявлять потребность последовательно, не перескакивая между темами.",
        "recommendation": "Держать порядок: задача клиента, текущая ситуация, ограничения, критерии решения.",
        "weight": 1.1,
    },
    "needs_active_listening": {
        "required_action": "Подтверждать понимание через парафраз, эхо или краткое резюме.",
        "recommendation": "После ответа клиента проговаривать: 'правильно понимаю, что...' и фиксировать вывод.",
        "weight": 1.0,
    },
    "needs_dialog_control": {
        "required_action": "Управлять ходом диалога и мягко вести клиента к следующему этапу.",
        "recommendation": "Использовать связки: 'давайте уточню', 'после этого предложу вариант', 'следующий шаг'.",
        "weight": 0.9,
    },
    "needs_before_offer": {
        "required_action": "Не презентовать решение до формирования понятной потребности.",
        "recommendation": "Сначала подтвердить задачу клиента, затем давать предложение под эту задачу.",
        "weight": 1.3,
    },
    "presentation_product_knowledge": {
        "required_action": "Показать знание продукта, услуги и применимых условий.",
        "recommendation": "Говорить конкретно: продукт, условия, сроки, ограничения, что входит в услугу.",
        "weight": 1.0,
    },
    "presentation_benefits": {
        "required_action": "Связать презентацию с выгодой и задачей клиента.",
        "recommendation": "Переводить свойства продукта в пользу для клиента: экономия, скорость, снижение риска.",
        "weight": 1.2,
    },
    "presentation_comparison": {
        "required_action": "При необходимости сравнить решение с альтернативами или конкурентами.",
        "recommendation": "Подготовить 2-3 честных отличия компании и продукта от типичных альтернатив.",
        "weight": 0.7,
    },
    "presentation_truthful": {
        "required_action": "Отвечать на вопросы клиента полно, честно и без размытых обещаний.",
        "recommendation": "Если точного ответа нет, фиксировать, что менеджер уточнит срок/условия и вернётся.",
        "weight": 1.0,
    },
    "presentation_examples": {
        "required_action": "Подкреплять предложение примерами, кейсами или похожими ситуациями.",
        "recommendation": "Добавить в скрипт короткие примеры по типовым сегментам клиентов.",
        "weight": 0.7,
    },
    "presentation_company_advantages": {
        "required_action": "Обозначить преимущества работы с компанией.",
        "recommendation": "Говорить не только о продукте, но и о сопровождении, поддержке, опыте, гарантии.",
        "weight": 0.8,
    },
    "objection_calm": {
        "required_action": "Спокойно принять возражение и не спорить с клиентом.",
        "recommendation": "Начинать ответ с признания позиции клиента: 'понимаю', 'логичный вопрос'.",
        "weight": 1.0,
        "objection_only": True,
    },
    "objection_true_reason": {
        "required_action": "Выяснить истинную причину возражения.",
        "recommendation": "После возражения задавать уточнение: 'что именно смущает?', 'с чем сравниваете?'.",
        "weight": 1.2,
        "objection_only": True,
    },
    "objection_solution": {
        "required_action": "Дать решение или аргумент с учётом сомнений клиента.",
        "recommendation": "Отрабатывать по схеме: признать, уточнить, аргументировать, закрепить действие.",
        "weight": 1.5,
        "objection_only": True,
    },
    "objection_closed_before_next": {
        "required_action": "Закрыть сомнение до перехода к следующему этапу.",
        "recommendation": "Проверять после аргумента: 'такой вариант вам подходит?', затем фиксировать следующий шаг.",
        "weight": 1.2,
        "objection_only": True,
    },
    "closing_summary": {
        "required_action": "Кратко резюмировать договорённости по итогам разговора.",
        "recommendation": "В конце звонка проговаривать: что решили, что отправляем, кто и когда делает следующий шаг.",
        "weight": 1.0,
    },
    "closing_next_step": {
        "required_action": "Обозначить дальнейшие шаги.",
        "recommendation": "Каждый разговор завершать конкретным действием: отправить КП, счёт, перезвонить, согласовать.",
        "weight": 1.4,
    },
    "closing_next_comm_time": {
        "required_action": "Определить тип и срок следующей коммуникации.",
        "recommendation": "Фиксировать не просто 'созвонимся', а дату/время или понятный срок возврата.",
        "weight": 1.2,
    },
    "closing_questions": {
        "required_action": "Уточнить, остались ли вопросы или сомнения.",
        "recommendation": "Перед завершением спрашивать: 'остались вопросы?', 'что ещё нужно уточнить?'.",
        "weight": 0.8,
    },
    "closing_goodbye": {
        "required_action": "Корректно завершить разговор и попрощаться.",
        "recommendation": "Завершать звонок вежливой финальной фразой и подтверждением следующего контакта.",
        "weight": 0.6,
    },
    "impression_client_oriented": {
        "required_action": "Показывать ориентацию на задачу и интерес клиента.",
        "recommendation": "Чаще связывать предложения с формулировками клиента: 'для вашей задачи'.",
        "weight": 1.0,
    },
    "impression_proactive": {
        "required_action": "Брать инициативу в свои руки и предлагать конкретные действия.",
        "recommendation": "Менеджер должен сам предлагать действие, срок и формат продолжения.",
        "weight": 1.0,
    },
    "impression_speech_clean": {
        "required_action": "Говорить ясно, без заметных речевых паразитов и хаотичных пауз.",
        "recommendation": "Разбирать записи с большим количеством запинок и заменять неуверенные формулировки.",
        "weight": 0.8,
    },
    "impression_preparation": {
        "required_action": "Показать подготовку: понимать, кому и зачем звонит менеджер.",
        "recommendation": "Перед звонком смотреть карточку, источник обращения, предыдущие касания и текущую стадию.",
        "weight": 1.0,
    },
    "followup_previous_context": {
        "required_action": "Напомнить контекст предыдущего касания: КП, счёт, договорённость или вопрос клиента.",
        "recommendation": "Начинать повторный контакт с конкретного контекста: что отправляли, что клиент обещал посмотреть, к чему возвращаемся.",
        "weight": 1.2,
    },
    "followup_decision_status": {
        "required_action": "Уточнить текущий статус решения клиента.",
        "recommendation": "Спрашивать прямо: посмотрели ли КП/счёт, приняли ли решение, кто ещё участвует в согласовании.",
        "weight": 1.4,
    },
    "followup_blocker": {
        "required_action": "Выяснить, что мешает перейти к следующему шагу или оплате.",
        "recommendation": "Не завершать повторный контакт без причины паузы: цена, сроки, согласование, конкурент, отсутствие потребности.",
        "weight": 1.4,
    },
}


CUSTOM_STEP_PATTERNS: dict[str, dict[str, Any]] = {
    "followup_previous_context": {
        "block": "Дожим / повторный контакт",
        "criterion": "Напомнил контекст предыдущего касания",
        "patterns": [
            r"\b(возвраща\w*|ранее|прошлый раз|обсуждали|отправлял\w*|высылал\w*|кп|коммерческ\w*|счет|счёт|договоренн\w*)\b",
        ],
        "partial_patterns": [r"\b(смотрел\w*|посмотрел\w*|получил\w*|письм\w*|сообщени\w*)\b"],
    },
    "followup_decision_status": {
        "block": "Дожим / повторный контакт",
        "criterion": "Уточнил статус решения клиента",
        "patterns": [
            r"\b(решение|решили|приняли|согласовал\w*|обсудил\w*|посмотрел\w*|готовы|когда планируете|какой статус)\b",
        ],
        "partial_patterns": [r"\b(получилось|успели|что скажете|как вам)\b"],
    },
    "followup_blocker": {
        "block": "Дожим / повторный контакт",
        "criterion": "Выяснил барьер к покупке или следующему шагу",
        "patterns": [
            r"\b(что смущает|что мешает|какая причина|почему|из-за чего|дорого|бюджет|сроки|согласован\w*|конкурент\w*)\b",
        ],
        "partial_patterns": [r"\b(вопрос|сомнен\w*|не подходит|подума\w*)\b"],
    },
}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _context(text: str, start: int, end: int, radius: int = 160) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    fragment = _clean_text(text[left:right])
    if left > 0:
        fragment = "..." + fragment
    if right < len(text):
        fragment += "..."
    return fragment[:700]


def _analysis_text(row: dict[str, Any]) -> str:
    for key in ("combined_transcript_text", "transcript_text", "bitrix_card_transcript"):
        text = _clean_text(row.get(key))
        if text:
            return text
    return ""


def _call_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("start_time") or ""), str(row.get("activity_id") or ""))


def _deal_group_key(row: dict[str, Any]) -> str:
    return str(row.get("deal_id") or row.get("deal_url") or "unknown")


def _stage_name(row: dict[str, Any]) -> str:
    return str(row.get("stage_name") or stage_display_name(row.get("stage_id")) or "")


def _has_objections(row: dict[str, Any], text: str) -> bool:
    try:
        if int(row.get("objections_count") or 0) > 0:
            return True
    except Exception:
        pass
    if row.get("objections_found") or row.get("unhandled_objections") or row.get("objection_rows"):
        return True
    lower = text.lower()
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for _, pattern, _ in OBJECTION_RULES)


def _match_any(text: str, patterns: list[str]) -> re.Match[str] | None:
    for pattern in patterns:
        try:
            match = re.search(pattern, text, flags=re.IGNORECASE)
        except re.error:
            continue
        if match:
            return match
    return None


def _custom_step_result(code: str, text: str) -> dict[str, Any] | None:
    cfg = CUSTOM_STEP_PATTERNS.get(code)
    if not cfg:
        return None
    match = _match_any(text, list(cfg.get("patterns") or []))
    if match:
        return {
            "checklist_block_name": cfg.get("block"),
            "checklist_code": code,
            "checklist_criterion": cfg.get("criterion"),
            "checklist_score": 1.0,
            "checklist_max_score": 1,
            "checklist_evidence": _context(text, match.start(), match.end()),
            "checklist_comment": "Критерий подтвержден фрагментом расшифровки.",
        }
    partial = _match_any(text, list(cfg.get("partial_patterns") or []))
    if partial:
        return {
            "checklist_block_name": cfg.get("block"),
            "checklist_code": code,
            "checklist_criterion": cfg.get("criterion"),
            "checklist_score": 0.5,
            "checklist_max_score": 1,
            "checklist_evidence": _context(text, partial.start(), partial.end()),
            "checklist_comment": "Есть косвенный признак, но шаг дожима выражен недостаточно явно.",
        }
    return {
        "checklist_block_name": cfg.get("block"),
        "checklist_code": code,
        "checklist_criterion": cfg.get("criterion"),
        "checklist_score": 0.0,
        "checklist_max_score": 1,
        "checklist_evidence": "",
        "checklist_comment": "В расшифровке нет подтверждения этого шага скрипта.",
    }


def _default_checklist_index(text: str) -> dict[str, dict[str, Any]]:
    if not text:
        return {}
    evaluated = evaluate_call_checklist(text)
    return {
        str(item.get("checklist_code")): item
        for item in evaluated.get("call_checklist_items", [])
        if isinstance(item, dict)
    }


def _checklist_index(row: dict[str, Any], text: str) -> dict[str, dict[str, Any]]:
    items = row.get("call_checklist_items")
    if isinstance(items, list) and items:
        index = {
            str(item.get("checklist_code")): item
            for item in items
            if isinstance(item, dict) and item.get("checklist_code")
        }
    else:
        index = _default_checklist_index(text)
    for code in CUSTOM_STEP_PATTERNS:
        result = _custom_step_result(code, text)
        if result:
            index[code] = result
    return index


def _script_step_info(code: str) -> tuple[str, str]:
    custom = CUSTOM_STEP_PATTERNS.get(code)
    if custom:
        return str(custom.get("block") or ""), str(custom.get("criterion") or code)
    for block in CALL_CHECKLIST_BLOCKS:
        block_name = str(block.get("name") or "")
        for item in block.get("items") or []:
            if isinstance(item, dict) and str(item.get("code") or "") == code:
                return block_name, str(item.get("criterion") or code)
    return "", code


def _script_status(score: float, max_score: float) -> str:
    if max_score <= 0:
        return "Не применимо"
    ratio = score / max_score
    if ratio >= 0.95:
        return "Выполнено"
    if ratio > 0:
        return "Частично"
    return "Провал"


def _profile_trigger_matches(profile: dict[str, Any], text: str) -> bool:
    return bool(_match_any(text, list(profile.get("trigger_patterns") or [])))


def select_script_profile_ids(row: dict[str, Any], text: str) -> list[str]:
    explicit = str(row.get("script_profile_id") or "").strip()
    if explicit and explicit in SCRIPT_PROFILES:
        primary = explicit
    else:
        primary = DEFAULT_SCRIPT_PROFILE_ID
        for profile_id in PRIMARY_SCRIPT_PROFILE_IDS:
            profile = SCRIPT_PROFILES.get(profile_id) or {}
            if _profile_trigger_matches(profile, text):
                primary = profile_id
                break

    selected = [primary]
    if ETIQUETTE_SCRIPT_PROFILE_ID not in selected:
        selected.append(ETIQUETTE_SCRIPT_PROFILE_ID)
    return selected


def _step_row(
    row: dict[str, Any],
    call_number: int,
    profile_id: str,
    profile: dict[str, Any],
    step: dict[str, Any],
    checklist: dict[str, dict[str, Any]],
    has_objections: bool,
) -> dict[str, Any]:
    code = str(step.get("code") or "")
    meta = {**SCRIPT_STEP_METADATA.get(code, {}), **step}
    block_name, criterion = _script_step_info(code)
    checklist_item = checklist.get(code, {})
    raw_score = float(checklist_item.get("checklist_score") or 0.0)
    raw_max = float(checklist_item.get("checklist_max_score") or 1.0)
    weight = float(meta.get("weight") or 1.0)
    critical = bool(meta.get("critical"))

    if (meta.get("when_objection") or meta.get("objection_only")) and not has_objections:
        score = None
        max_score = None
        percent = None
        status = "Не применимо"
        evidence = "Возражений в расшифровке не найдено, шаг не влияет на оценку этого профиля."
    else:
        score = round(raw_score, 2)
        max_score = round(raw_max, 2)
        percent = round((raw_score * 100.0 / max(1.0, raw_max)), 2)
        status = _script_status(raw_score, raw_max)
        evidence = checklist_item.get("checklist_evidence") or checklist_item.get("checklist_comment") or ""

    critical_error = ""
    if critical and status == "Провал":
        critical_error = f"Критичный шаг не выполнен: {criterion}"
    elif critical and status == "Частично":
        critical_error = f"Критичный шаг выполнен частично: {criterion}"

    return {
        "deal_url": row.get("deal_url"),
        "stage_name": _stage_name(row),
        "manager_name": row.get("manager_name"),
        "call_number": call_number,
        "subject": row.get("subject"),
        "duration_minutes": row.get("duration_minutes"),
        "script_profile_id": profile_id,
        "script_profile_name": profile.get("name") or profile_id,
        "script_profile_purpose": profile.get("purpose") or "",
        "script_profile_selected": "Да",
        "script_block": block_name,
        "script_step": criterion,
        "script_required_action": meta.get("required_action") or criterion,
        "script_score": score,
        "script_max_score": max_score,
        "script_score_percent": percent,
        "script_status": status,
        "script_critical_step": critical,
        "script_critical_error": critical_error,
        "script_evidence": evidence,
        "script_recommendation": meta.get("recommendation") or "Разобрать этот шаг на обучении.",
        "script_weight": weight,
    }


def evaluate_script_for_call(row: dict[str, Any], call_number: int) -> list[dict[str, Any]]:
    text = _analysis_text(row)
    checklist = _checklist_index(row, text)
    has_objections = _has_objections(row, text)
    out: list[dict[str, Any]] = []

    for profile_id in select_script_profile_ids(row, text):
        profile = SCRIPT_PROFILES.get(profile_id) or {}
        for step in profile.get("steps") or []:
            if isinstance(step, dict):
                out.append(_step_row(row, call_number, profile_id, profile, step, checklist, has_objections))

    return out


def build_script_score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for deal_rows in grouped.values():
        call_rows = [
            row
            for row in sorted(deal_rows, key=_call_sort_key)
            if not row.get("no_calls") and not row.get("asr_skipped")
        ]
        for index, row in enumerate(call_rows, start=1):
            if not _analysis_text(row):
                continue
            out.extend(evaluate_script_for_call(row, index))
    return out


def _profile_status(match_percent: float, critical_errors_count: int) -> str:
    if critical_errors_count > 0 and match_percent < 85:
        return "Не соответствует"
    if critical_errors_count > 0:
        return "Соответствует с критичными замечаниями"
    if match_percent >= 85:
        return "Соответствует"
    if match_percent >= 65:
        return "Частично соответствует"
    return "Не соответствует"


def _profile_recommendation(failed_steps: list[str], critical_errors: list[str]) -> str:
    if critical_errors:
        return "Сначала устранить критичные ошибки: " + "; ".join(critical_errors[:5]) + "."
    if failed_steps:
        return "Доработать шаги скрипта: " + "; ".join(failed_steps[:5]) + "."
    return "Скрипт в целом соблюден. Поддерживать структуру и фиксировать следующий шаг."


def build_script_profile_rows(script_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in script_rows:
        key = (
            row.get("deal_url"),
            row.get("call_number"),
            row.get("script_profile_id"),
        )
        bucket = grouped.setdefault(
            key,
            {
                "deal_url": row.get("deal_url"),
                "stage_name": row.get("stage_name"),
                "manager_name": row.get("manager_name"),
                "call_number": row.get("call_number"),
                "subject": row.get("subject"),
                "duration_minutes": row.get("duration_minutes"),
                "script_profile_id": row.get("script_profile_id"),
                "script_profile_name": row.get("script_profile_name"),
                "script_profile_purpose": row.get("script_profile_purpose"),
                "script_profile_selected": row.get("script_profile_selected") or "Да",
                "_score_sum": 0.0,
                "_max_sum": 0.0,
                "_critical_errors": [],
                "_failed_steps": [],
            },
        )
        if row.get("script_status") != "Не применимо":
            weight = float(row.get("script_weight") or 1.0)
            bucket["_score_sum"] += float(row.get("script_score") or 0.0) * weight
            bucket["_max_sum"] += float(row.get("script_max_score") or 1.0) * weight
        if row.get("script_critical_error"):
            bucket["_critical_errors"].append(str(row.get("script_critical_error")))
        if row.get("script_status") in {"Провал", "Частично"}:
            bucket["_failed_steps"].append(str(row.get("script_step") or ""))

    out: list[dict[str, Any]] = []
    for bucket in grouped.values():
        score = round(float(bucket["_score_sum"]), 2)
        max_score = round(float(bucket["_max_sum"]), 2)
        match_percent = round(score * 100.0 / max(1.0, max_score), 2)
        critical_errors = list(dict.fromkeys(bucket["_critical_errors"]))
        failed_steps = list(dict.fromkeys([x for x in bucket["_failed_steps"] if x]))
        out.append(
            {
                "deal_url": bucket["deal_url"],
                "stage_name": bucket["stage_name"],
                "manager_name": bucket["manager_name"],
                "call_number": bucket["call_number"],
                "subject": bucket["subject"],
                "duration_minutes": bucket["duration_minutes"],
                "script_profile_id": bucket["script_profile_id"],
                "script_profile_name": bucket["script_profile_name"],
                "script_profile_purpose": bucket["script_profile_purpose"],
                "script_profile_selected": bucket["script_profile_selected"],
                "script_profile_score": score,
                "script_profile_max_score": max_score,
                "script_profile_match_percent": match_percent,
                "script_profile_status": _profile_status(match_percent, len(critical_errors)),
                "script_critical_errors_count": len(critical_errors),
                "script_critical_errors": "\n".join(critical_errors),
                "script_failed_steps": "\n".join(failed_steps),
                "script_profile_recommendation": _profile_recommendation(failed_steps, critical_errors),
            }
        )
    return sorted(out, key=lambda r: (str(r.get("deal_url") or ""), int(r.get("call_number") or 0), str(r.get("script_profile_name") or "")))


def _script_priority(gap_count: int, gap_rate: float, weighted_gap: float) -> str:
    if gap_count >= 5 or gap_rate >= 50 or weighted_gap >= 5:
        return "Критичный"
    if gap_count >= 2 or gap_rate >= 25 or weighted_gap >= 2:
        return "Высокий"
    return "Средний"


def build_script_gap_rows(script_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "manager_name": "",
            "script_profile_name": "",
            "script_block": "",
            "script_step": "",
            "script_gap_count": 0,
            "script_partial_count": 0,
            "script_calls": 0,
            "_weighted_gap": 0.0,
            "script_training_recommendation": "",
        }
    )

    for row in script_rows:
        status = str(row.get("script_status") or "")
        if status == "Не применимо":
            continue
        manager = str(row.get("manager_name") or "Без менеджера")
        profile_name = str(row.get("script_profile_name") or "")
        block = str(row.get("script_block") or "")
        step = str(row.get("script_step") or "")
        key = (manager, profile_name, block, step)
        bucket = buckets[key]
        bucket["manager_name"] = manager
        bucket["script_profile_name"] = profile_name
        bucket["script_block"] = block
        bucket["script_step"] = step
        bucket["script_calls"] += 1
        bucket["script_training_recommendation"] = row.get("script_recommendation") or ""
        weight = float(row.get("script_weight") or 1.0)
        if status == "Провал":
            bucket["script_gap_count"] += 1
            bucket["_weighted_gap"] += weight
        elif status == "Частично":
            bucket["script_partial_count"] += 1
            bucket["_weighted_gap"] += weight * 0.5

    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        gap_count = int(bucket["script_gap_count"])
        partial_count = int(bucket["script_partial_count"])
        if gap_count == 0 and partial_count == 0:
            continue
        calls = max(1, int(bucket["script_calls"]))
        gap_rate = round((gap_count + partial_count) * 100.0 / calls, 2)
        out.append(
            {
                "manager_name": bucket["manager_name"],
                "script_profile_name": bucket["script_profile_name"],
                "script_block": bucket["script_block"],
                "script_step": bucket["script_step"],
                "script_gap_count": gap_count,
                "script_partial_count": partial_count,
                "script_calls": calls,
                "script_gap_rate": gap_rate,
                "script_priority": _script_priority(gap_count, gap_rate, float(bucket["_weighted_gap"])),
                "script_training_recommendation": bucket["script_training_recommendation"],
            }
        )

    priority_order = {"Критичный": 0, "Высокий": 1, "Средний": 2}
    return sorted(
        out,
        key=lambda row: (
            priority_order.get(str(row.get("script_priority")), 9),
            -float(row.get("script_gap_rate") or 0.0),
            str(row.get("manager_name") or ""),
            str(row.get("script_profile_name") or ""),
            str(row.get("script_block") or ""),
        ),
    )
