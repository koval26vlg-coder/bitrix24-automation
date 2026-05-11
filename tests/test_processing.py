from types import SimpleNamespace

from pipelines.kpi import load_kpi_config
from pipelines.processing import ProcessingContext, process_call, process_no_calls_deal


def test_process_no_calls_deal_builds_scored_error_row():
    kpi = load_kpi_config(None)
    args = SimpleNamespace(domain="example.bitrix24.ru")
    deal = {"ID": "10", "STAGE_ID": "NEW", "TITLE": "Тестовая сделка", "ASSIGNED_BY_ID": "5"}

    row = process_no_calls_deal(
        args=args,
        deal_id="10",
        deal=deal,
        comments=[],
        discipline={"first_response_minutes": None},
        deal_quality={"deal_quality_score": 25},
        manager_id=5,
        kpi=kpi,
        kpi_cmp=None,
        call_center_acts=[{"ID": "1"}],
    )

    assert row["deal_url"] == "https://example.bitrix24.ru/crm/deal/details/10/"
    assert row["no_calls"] is True
    assert row["ignored_call_center_calls"] == 1
    assert "Call-центра" in row["error"]
    assert row["overall_score"] >= 0
    assert row["recommendations"]


def test_process_call_reuses_cached_transcript(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    cached_path = tmp_path / "cached.txt"
    cached_path.write_text("Добрый день. Уточню задачу и отправлю КП.", encoding="utf-8")
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=False,
        force_attach=False,
        download_audio=False,
    )
    state_cache = {}
    monkeypatch.setattr(
        "pipelines.processing.load_cached_transcript",
        lambda state, call_id, deal_id, activity_id: (cached_path.read_text(encoding="utf-8"), cached_path),
    )
    monkeypatch.setattr("pipelines.processing._save_state_cache", lambda state: None)

    ctx = ProcessingContext(
        api=object(),
        asr=object(),
        args=args,
        kpi=kpi,
        kpi_cmp=None,
        audio_source_index=[],
        audio_dir=tmp_path,
        ui_audio_dir=tmp_path,
        state_cache=state_cache,
    )

    row, success = process_call(
        ctx=ctx,
        deal_id="10",
        deal={"ID": "10", "STAGE_ID": "NEW", "TITLE": "КП касса", "OPPORTUNITY": "10000"},
        comments=["Отправить КП клиенту"],
        discipline={"first_response_minutes": 10},
        deal_quality={"deal_quality_score": 50},
        manager_id=5,
        call_center_acts=[],
        activity={"ID": "100", "ORIGIN_ID": "CALL-100", "SUBJECT": "Исходящий звонок"},
    )

    assert success is True
    assert row["bitnewton_task_id"] == "cache"
    assert row["attach_result"] == {"skipped": True, "reason": "cached_transcript_reused"}
    assert row["transcript_text"] == cached_path.read_text(encoding="utf-8")
    assert state_cache["CALL-100"]["source"] == "cache"
