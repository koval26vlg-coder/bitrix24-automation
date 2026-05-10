from pipelines.bitnewton_sync import evaluate_call_checklist
from pipelines.scoring import recalculate_overall_score


def test_recalculate_overall_score_uses_call_and_crm_only():
    row = {
        "call_quality_score": 80.0,
        "crm_work_score": 60.0,
        "discipline_score": 0.0,
    }
    kpi = {
        "weights": {
            "overall": {
                "call_quality": 0.50,
                "discipline": 0.0,
                "crm_alignment": 0.50,
            }
        }
    }

    recalculate_overall_score(row, kpi)

    assert row["overall_score"] == 70.0
    assert "качество разговора 50%" in row["overall_score_details"]
    assert "ведение CRM 50%" in row["overall_score_details"]


def test_evaluate_call_checklist_returns_stable_structure():
    text = (
        "Здравствуйте, меня зовут Дмитрий. Подскажите, какая у вас задача? "
        "Правильно понимаю, что нужно подключить онлайн-кассу? "
        "Расскажу решение и согласуем следующий шаг: я пришлю КП сегодня."
    )

    result = evaluate_call_checklist(text)

    assert result["call_checklist_max_score"] > 0
    assert 0 <= result["call_quality_score"] <= 100
    assert isinstance(result["call_checklist_items"], list)
    assert isinstance(result["call_checklist_blocks"], list)
    assert result["call_checklist_items"]
    assert result["call_checklist_blocks"]
