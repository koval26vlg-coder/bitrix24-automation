from telegram_notify import build_summary


def _row(**overrides):
    row = {
        "deal_id": "100",
        "activity_id": "200",
        "manager_name": "Иван Иванов",
        "overall_score": 80,
        "call_quality_score": 70,
        "deal_quality_score": 60,
        "first_response_sla_ok": True,
        "error": None,
    }
    row.update(overrides)
    return row


def test_build_summary_counts_deals_and_calls():
    rows = [
        _row(),
        _row(deal_id="101", activity_id="201", overall_score=60),
    ]
    summary = build_summary(rows)
    assert "Сделок: 2, звонков: 2" in summary
    assert "Средний общий балл: 70.0" in summary


def test_build_summary_groups_by_manager():
    rows = [
        _row(),
        _row(activity_id="201", manager_name="Петр Петров", overall_score=50),
    ]
    summary = build_summary(rows)
    assert "Иван Иванов: 1 звонков" in summary
    assert "Петр Петров: 1 звонков" in summary


def test_build_summary_sla_percent():
    rows = [
        _row(),
        _row(activity_id="201", first_response_sla_ok=False),
    ]
    summary = build_summary(rows)
    assert "SLA первого ответа: 50% вовремя" in summary


def test_build_summary_reports_errors():
    rows = [_row(error="timeout")]
    summary = build_summary(rows)
    assert "Ошибок обработки: 1" in summary


def test_build_summary_skips_missing_scores():
    rows = [_row(overall_score=None, call_quality_score="")]
    summary = build_summary(rows)
    assert "Средний общий балл" not in summary
    assert "Качество звонков" not in summary
