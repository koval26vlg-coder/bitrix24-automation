from __future__ import annotations
import re
from typing import Any, Dict, List, Pattern, cast
from pipelines.scoring.utils import _manager_lines, _first_match, _context

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
                "patterns": [r"\b(как\s+.*к\s+вам\s+обращаться|вас\s+зовут|имя\s+отчество|по\s+имени|[а-яё]{3,}\s+[а-яё]{5,}(?:вич|вна))\b"],
                "partial_patterns": [r"\b(наталья|дмитрий|павел|сергей|андрей|александр|елена|ольга|ирина|мария|клиент)\b"],
            },
            {
                "code": "contact_purpose",
                "criterion": "Обозначает цель звонка понятную для клиента",
                "patterns": [r"\b(звоню\s+по|по\s+поводу|цель\s+звонка|хотел[аи]?\s+обсудить|по\s+вашей\s+заявк\w*|вы\s+оставляли\s+заявку|интересовал[аи]сь)\b"],
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
                "patterns": [r"\b(правильно\s+понимаю|верно\s+понимаю|то\s+есть|если\s+я\s+правильно|резюмир\w*|подытож\w*|вы\s+говорите|получается)\b"],
                "partial_patterns": [r"\b(понял[аи]?|слыш[ау]|угу|ага)\b"],
            },
            {
                "code": "needs_dialog_control",
                "criterion": "Управляет диалогом, не передает инициативу клиенту",
                "patterns": [r"\b(давайте|сначала|уточню|перейдем|предлагаю|после\s+этого|следующим\s+шагом|тогда)\b"],
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
                "patterns": [r"\b(для\s+вас|вы\s+получите|сможете|позволит|выгод\w*|эконом\w*|удобн\w*|быстр\w*|снизит|решит|под\s+вашу\s+задач\w*)\b"],
            },
            {
                "code": "presentation_comparison",
                "criterion": "Сравнивает продукт с аналогами или конкурентами",
                "patterns": [r"\b(аналог\w*|конкурент\w*|в\s+отличие|сравн\w*|лучше|хуже|другой\s+вариант|альтернатив\w*)\b"],
            },
            {
                "code": "presentation_truthful",
                "criterion": "Отвечает на вопросы клиента правдиво и полно",
                "patterns": [r"\b(стоимост\w*|срок\w*|услов\w*|нюанс\w*|ограничен\w*|можно|нельзя|зависит|точн\w*|подробн\w*)\b"],
            },
            {
                "code": "presentation_examples",
                "criterion": "Приводит актуальные и референтные примеры",
                "patterns": [r"\b(например|пример|кейс|практик\w*|у\s+клиентов|обычно|как\s+правило|часто|в\s+похожей\s+ситуации)\b"],
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
                "patterns": [r"\b(вопрос\w*|сомнен\w*|что-то\s+уточнить|осталось|все\s+понятно|понятно\s+ли)\b"],
            },
            {
                "code": "closing_goodbye",
                "criterion": "Попрощался",
                "patterns": [r"\b(до\s+свидан\w*|всего\s+добр\w*|хорошего\s+дня|спасибо|до\s+встречи|до\s+связи)\b"],
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
                "patterns": [r"\b(для\s+вас|вам\s+удобно|под\s+вашу\s+задач\w*|вам\s+подойдет|исходя\s+из|с\s+учетом|как\s+вам\s+удобнее|ваш[еи]\s+интерес)\b"],
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
                "patterns": [r"\b(по\s+вашей\s+заявк\w*|вы\s+интересовал\w*|вижу|обращени\w*|у\s+вас|ваша\s+задач\w*|заявка|заказ|ранее\s+общал\w*)\b"],
            },
        ],
    },
]

QUESTION_SIGNAL_RE: Pattern[str] = re.compile(
    r"\b(что|как|когда|где|почему|зачем|сколько|какие|какая|какой|уточн\w*|подскаж\w*|"
    r"нужно|необходим\w*|планиру\w*|используете|есть\s+ли|правильно\s+ли|верно\s+ли|задач\w*|потребност\w*)\b|\?",
    re.IGNORECASE,
)
PRESENTATION_START_RE: Pattern[str] = re.compile(
    r"\b(предлож\w*|мы\s+можем|можем\s+сделать|стоимост\w*|тариф\w*|вариант\w*|решени\w*|услуг\w*|продукт\w*)\b",
    re.IGNORECASE,
)
FILLER_RE: Pattern[str] = re.compile(r"\b(ээ+|эм+|мм+|ну\s+типа|как\s+бы|короче)\b", re.IGNORECASE)

def _score_by_patterns(raw: str, item: Dict[str, Any]) -> Dict[str, Any]:
    m_text = _manager_lines(raw)
    match = _first_match(m_text, list(item.get("patterns") or []))
    if match:
        return {
            "score": 1.0,
            "evidence": _context(m_text, match.start(), match.end(), radius=120),
            "comment": "Критерий подтвержден фрагментом расшифровки.",
        }
    partial = _first_match(m_text, list(item.get("partial_patterns") or []))
    if partial:
        return {
            "score": 0.5,
            "evidence": _context(m_text, partial.start(), partial.end(), radius=120),
            "comment": "Есть косвенный признак, но критерий выражен недостаточно явно.",
        }
    return {"score": 0.0, "evidence": "", "comment": "В расшифровке нет надежного подтверждения критерия."}

def _score_special_checklist_item(raw: str, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    code = str(item.get("special") or "")
    m_text = _manager_lines(raw)
    questions: List[re.Match[str]] = list(QUESTION_SIGNAL_RE.finditer(m_text))
    objections: List[Dict[str, Any]] = list(ctx.get("objections") or [])
    
    presentation = PRESENTATION_START_RE.search(m_text)
    presentation_pos = presentation.start() if presentation else (len(m_text) + 1)

    if code == "question_variety":
        count = len(questions)
        if count >= 5:
            score = 1.0
        elif count >= 2:
            score = 0.5
        else:
            score = 0.0
        evidence = _context(m_text, questions[0].start(), questions[min(count - 1, 2)].end(), radius=160) if questions else ""
        return {
            "score": score,
            "evidence": evidence,
            "comment": f"Найдено признаков вопросов: {count}. Полный балл — когда менеджер явно задает серию уточняющих вопросов.",
        }

    if code in {"question_sequence", "needs_before_offer"}:
        before_offer = [q for q in questions if q.start() < presentation_pos]
        count = len(before_offer)
        if count >= 3:
            score = 1.0
        elif count >= 1:
            score = 0.5
        else:
            score = 0.0
        evidence = _context(m_text, before_offer[0].start(), before_offer[min(count - 1, 2)].end(), radius=160) if before_offer else ""
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
        
        # Mapping special codes to objection properties
        prop_map = {
            "objection_calm": "calm",
            "objection_true_reason": "reason",
            "objection_solution": "handled",
            "objection_closed_before_next": "handled"
        }
        prop = prop_map.get(code, "handled")
        
        passed = [o for o in objections if o.get(prop)]
        score = 1.0 if len(passed) == len(objections) else (0.5 if passed else 0.0)
        
        labels = {
            "objection_calm": "Конструктивная реакция",
            "objection_true_reason": "Уточнение причины",
            "objection_solution": "Решение/аргументация",
            "objection_closed_before_next": "Закрытие сомнений перед следующим шагом"
        }
        comment = f"{labels.get(code)} найдено по {len(passed)} из {len(objections)} возражений."
        first = objections[0]
        return {"score": score, "evidence": str(first.get("fragment") or ""), "comment": comment}

    if code == "speech_clean":
        fillers = FILLER_RE.findall(m_text)
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
    from pipelines.scoring.objections import _objection_matches
    raw = text or ""
    ctx = {
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
    objections_val = ctx.get("objections")
    objections = cast(List[Dict[str, Any]], objections_val) if objections_val is not None else []
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
