from pathlib import Path

from pipelines.calls import compute_discipline_metrics
from pipelines.evaluation import compute_deal_quality, crm_call_alignment
from pipelines.scoring import _objection_matches, evaluate_call_checklist, evaluate_crm_checklist

TRANSCRIPTS_DIR = Path(__file__).parent / "fixtures" / "transcripts"


def read_transcript(name):
    path = TRANSCRIPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def test_evaluate_call_checklist_good_call():
    text = read_transcript("good_call")
    res = evaluate_call_checklist(text)

    assert res["call_quality_score"] > 80
    assert res["has_greeting"] is True
    assert res["has_needs_discovery"] is True
    assert res["has_next_step_phrase"] is True

    # Проверка конкретных блоков
    blocks = {b["sales_stage_block_code"]: b for b in res["call_checklist_blocks"]}
    assert blocks["contact"]["sales_stage_percent"] >= 80
    assert blocks["closing"]["sales_stage_percent"] >= 80


def test_evaluate_call_checklist_bad_call():
    text = read_transcript("bad_call")
    res = evaluate_call_checklist(text)

    assert res["call_quality_score"] < 40
    assert res["has_greeting"] is False
    assert res["has_needs_discovery"] is False


def test_objection_matches_detection():
    text = read_transcript("objection_call")
    objections = _objection_matches(text)

    assert len(objections) >= 2
    # Проверка обнаружения возражения по цене
    price_objection = next((o for o in objections if o["label"] == "Цена / бюджет"), None)
    assert price_objection is not None
    assert price_objection["handled"] is True


def test_compute_deal_quality():
    deal = {
        "CONTACT_ID": "",
        "OPPORTUNITY": "0",
        "TITLE": "",
    }
    comments = ["Клиент ждет звонка по направленному предложению"]
    next_steps = [
        {
            "SUBJECT": "Перезвонить клиенту",
            "DESCRIPTION": "Обсудить направленное предложение",
            "DEADLINE": "2099-01-01T12:00:00+03:00",
        }
    ]
    kpi = {
        "deal_quality_weights": {
            "comment_matches_call": 40,
            "has_next_step_activity": 30,
            "next_step_has_comment": 20,
            "next_step_not_overdue": 10,
        }
    }

    res = compute_deal_quality(
        deal,
        comments,
        kpi,
        transcript_text="Договорились направить предложение и потом перезвонить клиенту.",
        next_steps=next_steps,
    )
    assert res["deal_quality_score"] == 100
    assert res["has_contact"] is False
    assert res["has_amount"] is False
    assert res["has_title"] is False
    assert res["has_relevant_crm_comment"] is True
    assert res["has_next_step_activity"] is True
    assert res["next_step_activity_has_comment"] is True
    assert res["next_step_activity_not_overdue"] is True
    assert "комментарий соответствует содержанию звонка" in res["deal_quality_details"]

    no_next_step = compute_deal_quality(
        {"CONTACT_ID": "1", "OPPORTUNITY": "5000", "TITLE": "Продажа кассы"},
        comments,
        kpi,
        transcript_text="Договорились направить предложение и потом перезвонить клиенту.",
        next_steps=[],
    )
    assert no_next_step["deal_quality_score"] < 100


def test_compute_deal_quality_short_call_requires_next_step_case():
    next_steps = [
        {
            "SUBJECT": "Перезвонить клиенту",
            "DESCRIPTION": "Клиент не ответил, связаться повторно",
            "DEADLINE": "2099-01-01T12:00:00+03:00",
        }
    ]

    res = compute_deal_quality(
        {},
        [],
        {},
        next_steps=next_steps,
        short_call_without_conversation=True,
    )

    assert res["deal_quality_score"] == 100
    assert res["deal_quality_short_call_mode"] is True


def test_crm_checklist_deal_filling_requires_comment_and_next_step_case():
    row = {
        "has_contact": False,
        "has_amount": False,
        "has_title": False,
        "has_comments": True,
        "crm_comment_matches_call": True,
        "has_next_step_activity": True,
        "next_step_activity_has_comment": True,
        "next_step_activity_not_overdue": True,
        "calls_count": 1,
        "next_step_synced": True,
        "has_next_step_phrase": True,
    }

    res = evaluate_crm_checklist(row, include_stage=False)
    codes = {item["crm_checklist_code"] for item in res["crm_checklist_items"]}

    assert "crm_comment_matches_call" in codes
    assert "crm_has_next_step_activity" in codes
    assert "crm_next_step_has_comment" in codes
    assert "crm_next_step_not_overdue" in codes
    assert "crm_has_comments" not in codes
    assert "crm_has_contact" not in codes
    assert "crm_has_amount" not in codes
    assert "crm_has_title" not in codes
    assert "crm_amount_aligned" not in codes
    assert res["crm_work_score"] == 100


def test_crm_call_alignment():
    deal = {"TITLE": "Касса Эвотор", "OPPORTUNITY": "15000"}
    comments = ["Следующий шаг: перезвонить"]
    kpi = {"alignment_weights": {"amount_mentioned": 30, "next_step_synced": 40}}

    text_with_number = "Менеджер: Касса Эвотор стоит 15000 рублей. Следующий шаг: перезвонить."
    res = crm_call_alignment(deal, text_with_number, comments, kpi)
    assert res["alignment_score"] == 100
    assert res["amount_mentioned"] is True
    assert res["title_mentions"] > 0


def test_compute_discipline_metrics():
    deal = {"DATE_CREATE": "2026-05-01T10:00:00+03:00"}
    calls = [{"START_TIME": "2026-05-01T10:10:00+03:00"}]
    kpi = {"sla": {"first_response_hours": 0.5}}

    res = compute_discipline_metrics(deal, calls, kpi)
    assert res["first_response_minutes"] == 10.0
    assert res["first_response_sla_ok"] is True
