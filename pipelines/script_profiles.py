from __future__ import annotations

from typing import Any

SCRIPT_PROFILES: dict[str, dict[str, Any]] = {
    "online_kassa_sales": {
        "name": "Продажи онлайн-касс",
        "purpose": "Полный продажный разговор по онлайн-кассам, ККТ, ОФД, маркировке и сопровождению.",  # noqa: E501
        "trigger_patterns": [
            r"\b(касс\w*|ккт|фискаль\w*|офд|маркировк\w*|эквайринг|онлайн-?касс\w*)\b",
        ],
        "steps": [
            {"code": "contact_greeting", "weight": 1.0, "critical": True},
            {"code": "contact_purpose", "weight": 1.0, "critical": True},
            {"code": "needs_question_variety", "weight": 1.4, "critical": True},
            {"code": "needs_before_offer", "weight": 1.3, "critical": True},
            {"code": "presentation_product_knowledge", "weight": 1.2, "critical": True},
            {"code": "presentation_benefits", "weight": 1.2, "critical": True},
            {"code": "presentation_company_advantages", "weight": 0.8, "critical": False},
            {"code": "objection_solution", "weight": 1.3, "critical": True, "when_objection": True},
            {"code": "closing_next_step", "weight": 1.4, "critical": True},
            {"code": "closing_next_comm_time", "weight": 1.2, "critical": True},
        ],
    },
    "first_contact": {
        "name": "Первичный звонок",
        "purpose": "Первый контакт: быстро объяснить причину звонка, выявить задачу и договориться о следующем шаге.",  # noqa: E501
        "trigger_patterns": [
            r"\b(заявк\w*|первичн\w*|первый раз|вы оставляли|интересовал\w*)\b",
        ],
        "steps": [
            {"code": "contact_greeting", "weight": 1.0, "critical": True},
            {"code": "contact_permission", "weight": 0.8, "critical": False},
            {"code": "contact_name", "weight": 0.7, "critical": False},
            {"code": "contact_purpose", "weight": 1.2, "critical": True},
            {"code": "needs_question_variety", "weight": 1.5, "critical": True},
            {"code": "needs_sequence", "weight": 1.1, "critical": True},
            {"code": "needs_active_listening", "weight": 1.0, "critical": False},
            {"code": "closing_next_step", "weight": 1.4, "critical": True},
            {"code": "closing_next_comm_time", "weight": 1.2, "critical": True},
        ],
    },
    "follow_up": {
        "name": "Дожим / повторный контакт",
        "purpose": "Повторный контакт после КП, счёта или паузы клиента: понять барьер и довести до решения.",  # noqa: E501
        "trigger_patterns": [
            r"\b(повторн\w*|возвраща\w*|ранее|прошлый раз|обсуждали|отправлял\w*|высылал\w*|получили|посмотрели|решение приняли)\b",  # noqa: E501
            r"\b(подума\w*|посмотрел\w*|обсудил\w*|согласовал\w*)\b",
        ],
        "steps": [
            {"code": "contact_greeting", "weight": 0.8, "critical": True},
            {"code": "followup_previous_context", "weight": 1.2, "critical": True},
            {"code": "followup_decision_status", "weight": 1.4, "critical": True},
            {"code": "followup_blocker", "weight": 1.4, "critical": True},
            {"code": "presentation_benefits", "weight": 1.0, "critical": False},
            {
                "code": "objection_true_reason",
                "weight": 1.2,
                "critical": True,
                "when_objection": True,
            },
            {"code": "objection_solution", "weight": 1.5, "critical": True, "when_objection": True},
            {"code": "closing_next_step", "weight": 1.5, "critical": True},
            {"code": "closing_next_comm_time", "weight": 1.3, "critical": True},
        ],
    },
    "objection_management": {
        "name": "Работа с отказом / Управление возражениями",
        "purpose": "Разговор с отказом, сомнением или ценовым возражением: понять причину, отработать и закрепить действие.",  # noqa: E501
        "trigger_patterns": [
            r"\b(дорог\w*|не интересно|неинтересно|не надо|не нужно|не подходит|подума\w*|нет бюджета|сомнева\w*|отказ\w*)\b",  # noqa: E501
        ],
        "steps": [
            {"code": "objection_calm", "weight": 1.1, "critical": True},
            {"code": "objection_true_reason", "weight": 1.5, "critical": True},
            {"code": "objection_solution", "weight": 1.8, "critical": True},
            {"code": "objection_closed_before_next", "weight": 1.4, "critical": True},
            {"code": "needs_active_listening", "weight": 1.0, "critical": False},
            {"code": "presentation_benefits", "weight": 1.2, "critical": True},
            {"code": "closing_questions", "weight": 0.8, "critical": False},
            {"code": "closing_next_step", "weight": 1.4, "critical": True},
            {"code": "closing_next_comm_time", "weight": 1.1, "critical": True},
        ],
    },
    "communication_etiquette": {
        "name": "Этикет общения",
        "purpose": "Культура делового разговора: вежливость, ясность, уважение к времени клиента и уверенность речи.",  # noqa: E501
        "trigger_patterns": [],
        "steps": [
            {"code": "contact_greeting", "weight": 1.0, "critical": True},
            {"code": "contact_permission", "weight": 0.9, "critical": False},
            {"code": "contact_name", "weight": 0.7, "critical": False},
            {"code": "needs_active_listening", "weight": 1.0, "critical": False},
            {"code": "impression_client_oriented", "weight": 1.2, "critical": True},
            {"code": "impression_proactive", "weight": 1.0, "critical": False},
            {"code": "impression_speech_clean", "weight": 1.0, "critical": True},
            {"code": "closing_questions", "weight": 0.8, "critical": False},
            {"code": "closing_goodbye", "weight": 0.8, "critical": False},
        ],
    },
}


PRIMARY_SCRIPT_PROFILE_IDS = [
    "objection_management",
    "follow_up",
    "online_kassa_sales",
    "first_contact",
]


DEFAULT_SCRIPT_PROFILE_ID = "first_contact"
ETIQUETTE_SCRIPT_PROFILE_ID = "communication_etiquette"
