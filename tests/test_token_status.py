from datetime import date

from pipelines.token_status import (
    format_bitnewton_token_status,
    record_bitnewton_token_validation,
    update_bitnewton_token_status,
)


def test_token_status_records_new_token_and_days_left(tmp_path):
    path = tmp_path / "token_status.json"

    status = update_bitnewton_token_status(
        "token-1",
        today=date(2026, 5, 12),
        path=path,
    )

    assert status["configured"] is True
    assert status["issued_at"] == "2026-05-12"
    assert status["expires_at"] == "2026-06-11"
    assert status["days_left"] == 30
    assert "осталось 30 дн." in status["message"]
    assert "token-1" not in path.read_text(encoding="utf-8")


def test_token_status_keeps_issue_date_for_same_token(tmp_path):
    path = tmp_path / "token_status.json"
    update_bitnewton_token_status("token-1", today=date(2026, 5, 12), path=path)

    status = update_bitnewton_token_status("token-1", today=date(2026, 5, 20), path=path)

    assert status["issued_at"] == "2026-05-12"
    assert status["days_left"] == 22


def test_token_status_resets_issue_date_for_changed_token(tmp_path):
    path = tmp_path / "token_status.json"
    update_bitnewton_token_status("token-1", today=date(2026, 5, 12), path=path)

    status = update_bitnewton_token_status("token-2", today=date(2026, 5, 20), path=path)

    assert status["issued_at"] == "2026-05-20"
    assert status["days_left"] == 30


def test_token_status_can_use_explicit_issue_date(tmp_path):
    path = tmp_path / "token_status.json"

    status = update_bitnewton_token_status(
        "token-1",
        issued_at="2026-05-01",
        today=date(2026, 5, 12),
        path=path,
    )

    assert status["issued_at"] == "2026-05-01"
    assert status["days_left"] == 19


def test_token_status_expired_message():
    message = format_bitnewton_token_status(
        {
            "configured": True,
            "days_left": -2,
            "expires_at": "2026-05-10",
        }
    )

    assert "просрочен" in message


def test_token_status_validation_error_overrides_active_message(tmp_path):
    path = tmp_path / "token_status.json"
    update_bitnewton_token_status("token-1", today=date(2026, 5, 12), path=path)

    status = record_bitnewton_token_validation(ok=False, error="Invalid token", path=path)

    assert status["last_validation_ok"] is False
    assert "не прошел проверку" in status["message"]
    assert "Invalid token" in status["message"]
