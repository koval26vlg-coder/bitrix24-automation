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


def test_process_call_without_cache_downloads_transcribes_and_attaches(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    audio_path = tmp_path / "call.mp3"
    transcript_path = tmp_path / "transcript.txt"
    captured_attach = {}
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=False,
        force_attach=False,
        download_audio=False,
        diarize=True,
        fetch_bitrix_card_transcript=False,
        ui_download=False,
    )
    state_cache = {}

    def fake_download_audio_for_call(**kwargs):
        audio_path.write_bytes(b"audio")
        kwargs["row"]["audio_path"] = str(audio_path)
        kwargs["row"]["disk_file_id"] = "disk-1"
        assert kwargs["call_id"] == "CALL-200"
        return audio_path, kwargs["ui_browser_session"]

    def fake_transcribe_with_bitnewton(**kwargs):
        assert kwargs["audio_path"] == audio_path
        assert kwargs["diarize"] is True
        transcript_path.write_text("Добрый день. Уточню потребность и отправлю КП.", encoding="utf-8")
        return transcript_path.read_text(encoding="utf-8"), "task-200", transcript_path

    def fake_attach_transcription_to_bitrix(api, call_id, transcript_text, duration):
        captured_attach.update(
            {
                "call_id": call_id,
                "transcript_text": transcript_text,
                "duration": duration,
            }
        )
        return {"ok": True, "call_id": call_id}

    monkeypatch.setattr("pipelines.processing.load_cached_transcript", lambda *args: (None, None))
    monkeypatch.setattr("pipelines.processing.download_audio_for_call", fake_download_audio_for_call)
    monkeypatch.setattr("pipelines.processing.transcribe_with_bitnewton", fake_transcribe_with_bitnewton)
    monkeypatch.setattr("pipelines.processing.attach_transcription_to_bitrix", fake_attach_transcription_to_bitrix)
    monkeypatch.setattr(
        "pipelines.processing.activity_get",
        lambda api, activity_id: {
            "ID": activity_id,
            "START_TIME": "2026-05-01T10:00:00+03:00",
            "END_TIME": "2026-05-01T10:03:00+03:00",
        },
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
        deal_id="20",
        deal={"ID": "20", "STAGE_ID": "NEW", "TITLE": "КП касса", "OPPORTUNITY": "10000"},
        comments=["Отправить КП клиенту"],
        discipline={"first_response_minutes": 10},
        deal_quality={"deal_quality_score": 50},
        manager_id=5,
        call_center_acts=[],
        activity={"ID": "200", "ORIGIN_ID": "CALL-200", "SUBJECT": "Исходящий звонок"},
    )

    assert success is True
    assert row["error"] is None
    assert row["bitnewton_task_id"] == "task-200"
    assert row["transcript_path"] == str(transcript_path)
    assert row["attach_result"] == {"ok": True, "call_id": "CALL-200"}
    assert row["audio_path"] is None
    assert not audio_path.exists()
    assert captured_attach["duration"] == 180
    assert state_cache["CALL-200"]["source"] == "bitnewton"


def test_process_call_returns_error_row_when_download_fails(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=True,
        force_attach=False,
        download_audio=False,
    )

    def fake_download_audio_for_call(**kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr("pipelines.processing.download_audio_for_call", fake_download_audio_for_call)
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
        state_cache={},
    )

    row, success = process_call(
        ctx=ctx,
        deal_id="30",
        deal={"ID": "30", "STAGE_ID": "NEW", "TITLE": "КП касса"},
        comments=[],
        discipline={"first_response_minutes": 10},
        deal_quality={"deal_quality_score": 25},
        manager_id=5,
        call_center_acts=[],
        activity={"ID": "300", "ORIGIN_ID": "CALL-300", "SUBJECT": "Исходящий звонок"},
    )

    assert success is False
    assert row["deal_id"] == "30"
    assert row["activity_id"] == "300"
    assert row["error"] == "download failed"
    assert row["attach_result"] is None
