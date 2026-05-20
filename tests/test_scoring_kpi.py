from pathlib import Path

from pipelines.calls import compute_discipline_metrics
from pipelines.evaluation import compute_deal_quality, crm_call_alignment
from pipelines.scoring import _objection_matches, evaluate_call_checklist

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
        "CONTACT_ID": "1",
        "OPPORTUNITY": "5000",
        "TITLE": "Продажа кассы",
    }
    comments = ["Клиент ждет звонка"]
    kpi = {
        "deal_quality_weights": {
            "has_contact": 25,
            "has_amount": 25,
            "has_title": 25,
            "has_comments": 25,
        }
    }

    res = compute_deal_quality(deal, comments, kpi)
    assert res["deal_quality_score"] == 100
    assert res["has_contact"] is True


def test_crm_call_alignment():
    deal = {"TITLE": "Касса Эвотор", "OPPORTUNITY": "15000"}
    comments = ["Следующий шаг: перезвонить"]
    kpi = {"alignment_weights": {"amount_mentioned": 30, "next_step_synced": 40}}

    text_with_number = "Менеджер: Касса Эвотор стоит 15000 рублей."
    res = crm_call_alignment(deal, text_with_number, comments, kpi)
    assert res["amount_mentioned"] is True
    assert res["title_mentions"] > 0


def test_compute_discipline_metrics():
    deal = {"DATE_CREATE": "2026-05-01T10:00:00+03:00"}
    calls = [{"START_TIME": "2026-05-01T10:10:00+03:00"}]
    kpi = {"sla": {"first_response_hours": 0.5}}

    res = compute_discipline_metrics(deal, calls, kpi)
    assert res["first_response_minutes"] == 10.0
    assert res["first_response_sla_ok"] is True
