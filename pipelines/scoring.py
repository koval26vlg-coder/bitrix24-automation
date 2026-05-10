from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


CALL_CHECKLIST_BLOCKS: List[Dict[str, Any]] = [
    {
        "code": "contact",
        "name": "Установление контакта",
        "items": [
            {
                "code": "contact_greeting",
                "criterion": "Поздоровался, представился",
                "patterns": [r"\b(добрый|здравств\w*|привет)\b", r"\b(меня зовут|это\s+[а-яё]+|компани[яи])\b"],
            },
            {
                "code": "contact_permission",
                "criterion": "Уточнил возможность провести диалог",
                "patterns": [r"\b(удобно|можете говорить|есть\s+\w*\s*минут|уделить\s+\w*\s*минут|сможете\s+поговорить)\b"],
                "partial_patterns": [r"\b(не отвлекаю|можно|разговор)\b"],
            },
            {
                "code": "contact_name",
                "criterion": "Обращается к клиенту по имени/имени отчеству",
                "patterns": [r"\b(как к вам обращаться|вас зовут|имя отчество|по имени|[а-яё]{3,}\s+[а-яё]{5,}(?:вич|вна))\b"],
                "partial_patterns": [r"\b(наталья|дмитрий|павел|сергей|андрей|александр|елена|ольга|ирина|мария|клиент)\b"],
            },
            {
                "code": "contact_purpose",
                "criterion": "Обозначает цель звонка понятную для клиента",
                "patterns": [r"\b(звоню по|по поводу|цель звонка|хотел[аи]?\s+обсудить|по вашей заявк\w*|вы оставляли заявку|интересовал[аи]сь)\b"],
            },
        ],
    },
    {
        "code": "needs",
        "name": "Выявление потребности",
        "items": [
            {
                "code": "needs_question_variety",
                "criterion": "Задает вопросы разных типов",
                "special": "question_variety",
            },
            {
                "code": "needs_sequence",
                "criterion": "Вопросы задаются последовательно, менеджер не перескакивает с темы на тему",
                "special": "question_sequence",
            },
            {
                "code": "needs_active_listening",
                "criterion": "Использует активное слушание: парафраз, эхо, резюме",
                "patterns": [r"\b(правильно понимаю|верно понимаю|то есть|если я правильно|резюмир\w*|подытож\w*|вы говорите|получается)\b"],
                "partial_patterns": [r"\b(понял[аи]?|слыш[ау]|угу|ага)\b"],
            },
            {
                "code": "needs_dialog_control",
                "criterion": "Управляет диалогом, не передает инициативу клиенту",
                "patterns": [r"\b(давайте|сначала|уточню|перейдем|предлагаю|после этого|следующим шагом|тогда)\b"],
            },
            {
                "code": "needs_before_offer",
                "criterion": "Не переходит к предложению, пока не сформирована потребность клиента",
                "special": "needs_before_offer",
            },
        ],
    },
    {
        "code": "presentation",
        "name": "Презентация",
        "items": [
            {
                "code": "presentation_product_knowledge",
                "criterion": "Владеет информацией о продукте или услуге",
                "patterns": [r"\b(касс\w*|ккт|фискаль\w*|офд|маркировк\w*|эквайринг|битрикс|1с|тариф\w*|интеграц\w*|настройк\w*|обслуживан\w*)\b"],
            },
            {
                "code": "presentation_benefits",
                "criterion": "Презентует продукт на языке выгоды исходя из потребности",
                "patterns": [r"\b(для вас|вы получите|сможете|позволит|выгод\w*|эконом\w*|удобн\w*|быстр\w*|снизит|решит|под вашу задач\w*)\b"],
            },
            {
                "code": "presentation_comparison",
                "criterion": "Сравнивает продукт с аналогами или конкурентами",
                "patterns": [r"\b(аналог\w*|конкурент\w*|в отличие|сравн\w*|лучше|хуже|другой вариант|альтернатив\w*)\b"],
            },
            {
                "code": "presentation_truthful",
                "criterion": "Отвечает на вопросы клиента правдиво и полно",
                "patterns": [r"\b(стоимост\w*|срок\w*|услов\w*|нюанс\w*|ограничен\w*|можно|нельзя|зависит|точн\w*|подробн\w*)\b"],
            },
            {
                "code": "presentation_examples",
                "criterion": "Приводит актуальные и референтные примеры",
                "patterns": [r"\b(например|пример|кейс|практик\w*|у клиентов|обычно|как правило|часто|в похожей ситуации)\b"],
            },
            {
                "code": "presentation_company_advantages",
                "criterion": "Презентует преимущества работы с компанией",
                "patterns": [r"\b(поддержк\w*|гаранти\w*|сервис\w*|опыт|специалист\w*|команд\w*|работаем|партнер\w*|сопровожд\w*)\b"],
            },
        ],
    },
    {
        "code": "objections",
        "name": "Работа с возражениями",
        "items": [
            {
                "code": "objection_calm",
                "criterion": "Сохраняет спокойный конструктивный подход при возражениях",
                "special": "objection_calm",
            },
            {
                "code": "objection_true_reason",
                "criterion": "Выясняет истинную причину возражения",
                "special": "objection_true_reason",
            },
            {
                "code": "objection_solution",
                "criterion": "Предлагает решения и убедительные аргументы",
                "special": "objection_solution",
            },
            {
                "code": "objection_closed_before_next",
                "criterion": "Не переходит дальше, пока не закроет сомнения клиента",
                "special": "objection_closed_before_next",
            },
        ],
    },
    {
        "code": "closing",
        "name": "Закрытие звонка",
        "items": [
            {
                "code": "closing_summary",
                "criterion": "Резюмирует договоренности",
                "patterns": [r"\b(резюм\w*|подытож\w*|итак|договорил\w*|получается|фиксируем)\b"],
            },
            {
                "code": "closing_next_step",
                "criterion": "Обозначил дальнейшие шаги",
                "patterns": [r"\b(следующ\w*|дальше|отправ\w*|вышл\w*|перезвон\w*|созвон\w*|встреч\w*|согласу\w*|подготовлю|проверю)\b"],
            },
            {
                "code": "closing_next_comm_time",
                "criterion": "Определил тип и срок следующей коммуникации",
                "patterns": [r"\b(сегодня|завтра|послезавтра|понедельник|вторник|сред[ау]|четверг|пятниц\w*|час\w*|минут\w*|до\s+\d|после\s+\d|срок|дата)\b"],
            },
            {
                "code": "closing_questions",
                "criterion": "Уточнил наличие вопросов или сомнений у клиента",
                "patterns": [r"\b(вопрос\w*|сомнен\w*|что-то уточнить|осталось|все понятно|понятно ли)\b"],
            },
            {
                "code": "closing_goodbye",
                "criterion": "Попрощался",
                "patterns": [r"\b(до свидан\w*|всего добр\w*|хорошего дня|спасибо|до встречи|до связи)\b"],
            },
        ],
    },
    {
        "code": "impression",
        "name": "Общее впечатление по звонку",
        "items": [
            {
                "code": "impression_client_oriented",
                "criterion": "Клиентоориентированность: действует исходя из интересов клиента",
                "patterns": [r"\b(для вас|вам удобно|под вашу задач\w*|вам подойдет|исходя из|с учетом|как вам удобнее|ваш[еи]\s+интерес)\b"],
            },
            {
                "code": "impression_proactive",
                "criterion": "Инициативен и проактивен",
                "patterns": [r"\b(предлагаю|могу|давайте|подготовлю|отправлю|возьму|сделаю|проверю|уточню|согласую)\b"],
            },
            {
                "code": "impression_speech_clean",
                "criterion": "Чистая грамотная речь, нет долгих пауз",
                "special": "speech_clean",
            },
            {
                "code": "impression_preparation",
                "criterion": "Провел предварительную подготовку к звонку",
                "patterns": [r"\b(по вашей заявк\w*|вы интересовал\w*|вижу|обращени\w*|у вас|ваша задач\w*|заявка|заказ|ранее общал\w*)\b"],
            },
        ],
    },
]


QUESTION_SIGNAL_RE = re.compile(
    r"\b(что|как|когда|где|почему|зачем|сколько|какие|какая|какой|уточн\w*|подскаж\w*|"
    r"нужно|необходим\w*|планиру\w*|используете|есть ли|правильно ли|верно ли|задач\w*|потребност\w*)\b|\?",
    re.IGNORECASE,
)
PRESENTATION_START_RE = re.compile(
    r"\b(предлож\w*|мы можем|можем сделать|стоимост\w*|тариф\w*|вариант\w*|решени\w*|услуг\w*|продукт\w*)\b",
    re.IGNORECASE,
)
CALM_RESPONSE_RE = re.compile(r"\b(понима\w*|соглас\w*|да,|конечно|верно|логично|слышу|это нормально)\b", re.IGNORECASE)
REASON_QUESTION_RE = re.compile(r"\b(почему|что именно|с чем связан\w*|какая причин\w*|что смущает|из-за чего|расскажите)\b", re.IGNORECASE)
FILLER_RE = re.compile(r"\b(ээ+|эм+|мм+|ну типа|как бы|короче)\b", re.IGNORECASE)


def _first_match(text: str, patterns: List[str]) -> Optional[Any]:
    for pattern in patterns:
        try:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match
        except re.error:
            continue
    return None


def _score_by_patterns(raw: str, item: Dict[str, Any]) -> Dict[str, Any]:
    match = _first_match(raw, list(item.get("patterns") or []))
    if match:
        return {
            "score": 1.0,
            "evidence": _context(raw, match.start(), match.end(), radius=120),
            "comment": "Критерий подтвержден фрагментом расшифровки.",
        }
    partial = _first_match(raw, list(item.get("partial_patterns") or []))
    if partial:
        return {
            "score": 0.5,
            "evidence": _context(raw, partial.start(), partial.end(), radius=120),
            "comment": "Есть косвенный признак, но критерий выражен недостаточно явно.",
        }
    return {"score": 0.0, "evidence": "", "comment": "В расшифровке нет надежного подтверждения критерия."}


def _objection_matches(raw: str) -> List[Dict[str, Any]]:
    lower = raw.lower()
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int]] = set()
    for label, pattern, suggestion in OBJECTION_RULES:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            key = (label, match.start())
            if key in seen:
                continue
            seen.add(key)
            after = raw[match.end() : match.end() + 420]
            out.append(
                {
                    "label": label,
                    "start": match.start(),
                    "end": match.end(),
                    "fragment": _context(raw, match.start(), match.end(), radius=140),
                    "handled": bool(HANDLING_RE.search(after)),
                    "calm": bool(CALM_RESPONSE_RE.search(after)),
                    "reason": bool(REASON_QUESTION_RE.search(after)),
                    "suggestion": suggestion,
                }
            )
    return sorted(out, key=lambda x: int(x.get("start") or 0))


def _score_special_checklist_item(raw: str, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    code = str(item.get("special") or "")
    questions = list(ctx.get("questions") or [])
    objections = list(ctx.get("objections") or [])
    presentation_pos = ctx.get("presentation_pos")
    if presentation_pos is None:
        presentation_pos = len(raw) + 1

    if code == "question_variety":
        count = len(questions)
        if count >= 5:
            score = 1.0
        elif count >= 2:
            score = 0.5
        else:
            score = 0.0
        evidence = _context(raw, questions[0].start(), questions[min(count - 1, 2)].end(), radius=160) if questions else ""
        return {
            "score": score,
            "evidence": evidence,
            "comment": f"Найдено признаков вопросов: {count}. Полный балл — когда менеджер явно задает серию уточняющих вопросов.",
        }

    if code in {"question_sequence", "needs_before_offer"}:
        before_offer = [q for q in questions if q.start() < int(presentation_pos)]
        count = len(before_offer)
        if count >= 3:
            score = 1.0
        elif count >= 1:
            score = 0.5
        else:
            score = 0.0
        evidence = _context(raw, before_offer[0].start(), before_offer[min(count - 1, 2)].end(), radius=160) if before_offer else ""
        if code == "question_sequence":
            comment = f"До презентации найдено вопросов: {count}. Это показывает последовательность выявления потребности."
        else:
            comment = f"До предложения найдено вопросов: {count}. Полный балл — когда предложение идет после выявления задачи клиента."
        return {"score": score, "evidence": evidence, "comment": comment}

    if code.startswith("objection_"):
        if not objections:
            return {
                "score": 1.0,
                "evidence": "",
                "comment": "Возражений в расшифровке не найдено, поэтому пункт не снижает оценку.",
            }
        if code == "objection_calm":
            passed = [o for o in objections if o.get("calm")]
            score = 1.0 if len(passed) == len(objections) else (0.5 if passed else 0.0)
            comment = f"Конструктивная реакция найдена по {len(passed)} из {len(objections)} возражений."
        elif code == "objection_true_reason":
            passed = [o for o in objections if o.get("reason")]
            score = 1.0 if len(passed) == len(objections) else (0.5 if passed else 0.0)
            comment = f"Уточнение причины найдено по {len(passed)} из {len(objections)} возражений."
        elif code == "objection_solution":
            passed = [o for o in objections if o.get("handled")]
            score = 1.0 if len(passed) == len(objections) else (0.5 if passed else 0.0)
            comment = f"Решение/аргументация найдены по {len(passed)} из {len(objections)} возражений."
        else:
            passed = [o for o in objections if o.get("handled")]
            score = 1.0 if len(passed) == len(objections) else (0.5 if passed else 0.0)
            comment = f"Закрытие сомнений перед следующим шагом найдено по {len(passed)} из {len(objections)} возражений."
        first = objections[0]
        return {"score": score, "evidence": str(first.get("fragment") or ""), "comment": comment}

    if code == "speech_clean":
        fillers = FILLER_RE.findall(raw)
        if len(fillers) <= 2:
            score = 1.0
        elif len(fillers) <= 6:
            score = 0.5
        else:
            score = 0.0
        return {
            "score": score,
            "evidence": "",
            "comment": f"Найдено явных речевых паразитов/запинок: {len(fillers)}. Долгие паузы лучше подтверждать аудио-метаданными.",
        }

    return _score_by_patterns(raw, item)


def evaluate_call_checklist(text: str) -> Dict[str, Any]:
    raw = text or ""
    questions = list(QUESTION_SIGNAL_RE.finditer(raw))
    presentation = PRESENTATION_START_RE.search(raw)
    ctx = {
        "questions": questions,
        "presentation_pos": presentation.start() if presentation else None,
        "objections": _objection_matches(raw),
    }

    item_rows: List[Dict[str, Any]] = []
    block_rows: List[Dict[str, Any]] = []
    total_score = 0.0
    total_max = 0.0
    for block in CALL_CHECKLIST_BLOCKS:
        block_score = 0.0
        block_max = 0.0
        weak: List[str] = []
        for item in block.get("items") or []:
            result = (
                _score_special_checklist_item(raw, item, ctx)
                if item.get("special")
                else _score_by_patterns(raw, item)
            )
            score = float(result.get("score") or 0.0)
            block_score += score
            block_max += 1.0
            if score < 1:
                weak.append(str(item.get("criterion") or ""))
            item_rows.append(
                {
                    "checklist_block_code": block.get("code"),
                    "checklist_block_name": block.get("name"),
                    "checklist_code": item.get("code"),
                    "checklist_criterion": item.get("criterion"),
                    "checklist_score": score,
                    "checklist_max_score": 1,
                    "checklist_evidence": result.get("evidence") or "",
                    "checklist_comment": result.get("comment") or "",
                }
            )
        total_score += block_score
        total_max += block_max
        block_rows.append(
            {
                "sales_stage_block_code": block.get("code"),
                "sales_stage_block_name": block.get("name"),
                "sales_stage_score": round(block_score, 2),
                "sales_stage_max_score": int(block_max),
                "sales_stage_percent": round(block_score * 100.0 / max(1.0, block_max), 2),
                "sales_stage_missing": "; ".join([x for x in weak if x]),
            }
        )

    percent = round(total_score * 100.0 / max(1.0, total_max), 2)
    details = "; ".join(
        f"{b['sales_stage_block_name']}: {b['sales_stage_score']}/{b['sales_stage_max_score']} ({b['sales_stage_percent']}%)"
        for b in block_rows
    )
    scores_by_code = {str(x.get("checklist_code")): float(x.get("checklist_score") or 0.0) for x in item_rows}
    objections = list(ctx.get("objections") or [])
    return {
        "call_quality_score": percent,
        "call_quality_details": details,
        "call_checklist_total_score": round(total_score, 2),
        "call_checklist_max_score": int(total_max),
        "call_checklist_percent": percent,
        "call_checklist_block_details": details,
        "call_checklist_items": item_rows,
        "call_checklist_blocks": block_rows,
        "has_greeting": scores_by_code.get("contact_greeting", 0.0) > 0,
        "has_needs_discovery": any(
            scores_by_code.get(code, 0.0) > 0
            for code in ["needs_question_variety", "needs_sequence", "needs_active_listening", "needs_before_offer"]
        ),
        "has_objection_work": bool(objections) and any(
            scores_by_code.get(code, 0.0) > 0
            for code in ["objection_calm", "objection_true_reason", "objection_solution", "objection_closed_before_next"]
        ),
        "has_next_step_phrase": scores_by_code.get("closing_next_step", 0.0) > 0,
    }


def evaluate_call_text(text: str, kpi: Dict[str, Any]) -> Dict[str, Any]:
    return evaluate_call_checklist(text)




OBJECTION_RULES: List[Tuple[str, str, str]] = [
    (
        "Цена / бюджет",
        r"\b(дорог\w*|цена|стоимост\w*|сколько стоит|нет бюджета|дороже|дешевле)\b",
        "Признать вопрос цены, разложить стоимость на состав услуги, показать выгоду/риск бездействия и предложить следующий шаг.",
    ),
    (
        "Нет потребности / не актуально",
        r"\b(не надо|не нужно|не актуаль\w*|не интерес\w*|не подходит|не требуется)\b",
        "Уточнить контекст клиента, почему сейчас не актуально, и предложить минимальный следующий шаг или полезную альтернативу.",
    ),
    (
        "Ограничение / отказ",
        r"\b(не смож\w*|не можем|не получится|нет возможности|невозможно|такого нет)\b",
        "Не оставлять клиента с отказом: объяснить ограничение, предложить близкий рабочий вариант и согласовать дальнейшее действие.",
    ),
    (
        "Пауза на решение",
        r"\b(подума\w*|посмотр\w*|обсуд\w*|решим|перезвоните позже|не сейчас)\b",
        "Согласовать конкретный срок возврата, критерии решения и что клиенту нужно прислать до следующего контакта.",
    ),
    (
        "Непонимание / сомнение",
        r"\b(не понимаю|непонятн\w*|сомнева\w*|что это|как это работает|зачем)\b",
        "Переформулировать простыми словами, задать уточняющий вопрос и проверить, стало ли клиенту понятно.",
    ),
]

HANDLING_RE = re.compile(
    r"\b(понима\w*|давайте|уточн\w*|предлож\w*|вариант\w*|альтернатив\w*|в таком случае|тогда|можем|"
    r"входит|стоимост\w*|выгод\w*|риск\w*|сравн\w*|перезвон\w*|отправ\w*|согласу\w*)\b",
    re.IGNORECASE,
)


def _clean_text_for_report(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _context(text: str, start: int, end: int, radius: int = 180) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = _clean_text_for_report(text[left:right])
    return snippet[:700]


def quality_label(score: float) -> str:
    if score >= 80:
        return "сильное"
    if score >= 60:
        return "нормальное"
    if score >= 40:
        return "слабое"
    return "критически слабое"


def call_quality_conclusion(row: Dict[str, Any]) -> Tuple[str, str]:
    score = float(row.get("call_quality_score") or 0.0)
    missing: List[str] = []
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
        conclusion = "Разговор частично проработан: клиенту не хватает ясной структуры и завершения."
    else:
        conclusion = "Разговор слабый: ключевые элементы проработки клиента почти не зафиксированы."

    recs = []
    if missing:
        recs.append("Усилить: " + ", ".join(missing) + ".")
    if int(row.get("unhandled_objections_count") or 0) > 0:
        recs.append("Вернуться к неотработанным возражениям и дать клиенту альтернативу/ценность/следующий шаг.")
    if not row.get("next_step_synced"):
        recs.append("Зафиксировать следующий шаг в разговоре и в CRM.")
    objection_recs = str(row.get("objection_recommendations") or "").strip()
    if objection_recs:
        recs.append(objection_recs)
    if not recs:
        recs.append("Поддерживать текущую структуру разговора.")
    return conclusion, " ".join(recs)



def transcript_match_score(bitnewton_text: str, bitrix_text: str) -> Optional[float]:
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


def conversation_meaning(text: str, row: Dict[str, Any]) -> str:
    t = (text or "").lower()
    topics: List[str] = []
    topic_rules = [
        ("цена/стоимость", r"\b(цен\w*|стоимост\w*|дорог\w*|бюджет)\b"),
        ("счет/оплата", r"\b(счет|оплат\w*|предоплат\w*|платеж)\b"),
        ("КП/договор", r"\b(кп|коммерческ\w*|договор\w*)\b"),
        ("технические условия", r"\b(тех\w*|интеграц\w*|настройк\w*|касс\w*|оборудован\w*)\b"),
        ("сроки/следующий контакт", r"\b(срок\w*|перезвон\w*|созвон\w*|встреч\w*|завтра|сегодня)\b"),
    ]
    for label, pattern in topic_rules:
        if re.search(pattern, t):
            topics.append(label)
    if not topics:
        topics.append("общая консультация по сделке")

    parts = [f"Смысл разговора: обсуждались {', '.join(dict.fromkeys(topics))}."]
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
    details = "; ".join(
        f"{block}: {round(sum(float(x.get('crm_checklist_score') or 0.0) for x in block_items), 2)}/{len(block_items)}"
        for block, block_items in blocks.items()
    )
    return {
        "crm_checklist_total_score": total_score,
        "crm_checklist_max_score": total_max,
        "crm_checklist_percent": percent,
        "crm_checklist_details": details,
        "crm_checklist_items": items,
        "crm_work_score": percent,
    }

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
