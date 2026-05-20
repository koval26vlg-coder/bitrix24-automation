from types import SimpleNamespace

import pytest

from asr.bitnewton import BitNewtonAuthError
from pipelines.kpi import load_kpi_config
from pipelines.processing import (
    ProcessingContext,
    process_call,
    process_deal,
    process_deals,
    process_no_calls_deal,
)


@pytest.mark.asyncio
async def test_process_no_calls_deal_builds_scored_error_row():
    kpi = load_kpi_config(None)
    args = SimpleNamespace(domain="example.bitrix24.ru")
    ctx = ProcessingContext(
        api=object(),
        asr=object(),
        args=args,
        kpi=kpi,
        kpi_cmp=None,
        audio_source_index=[],
        audio_dir=None,
        ui_audio_dir=None,
        state_cache={},
    )
    deal = {"ID": "10", "STAGE_ID": "NEW", "TITLE": "Тестовая сделка", "ASSIGNED_BY_ID": "5"}

    row = await process_no_calls_deal(
        ctx=ctx,
        deal_id="10",
        deal=deal,
        comments=[],
        discipline={"first_response_minutes": None},
        deal_quality={"deal_quality_score": 25},
        manager_id=5,
        call_center_acts=[{"ID": "1"}],
    )

    assert row["deal_url"] == "https://example.bitrix24.ru/crm/deal/details/10/"
    assert row["no_calls"] is True
    assert row["ignored_call_center_calls"] == 1
    assert "Call-центра" in row["error"]
    assert row["overall_score"] >= 0
    assert row["recommendations"]


@pytest.mark.asyncio
async def test_process_call_reuses_cached_transcript(monkeypatch, tmp_path):
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
        "pipelines.processing.calls.load_cached_transcript",
        lambda state, call_id, deal_id, activity_id: (
            cached_path.read_text(encoding="utf-8"),
            cached_path,
        ),
    )
    monkeypatch.setattr("pipelines.processing.calls._save_state_cache", lambda state: None)

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

    row, success = await process_call(
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


@pytest.mark.asyncio
async def test_process_call_no_external_write_skips_cached_force_attach_and_timeline(
    monkeypatch, tmp_path
):
    kpi = load_kpi_config(None)
    cached_path = tmp_path / "cached.txt"
    cached_path.write_text("Добрый день. Уточню задачу и отправлю КП.", encoding="utf-8")
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=False,
        force_attach=True,
        download_audio=False,
        no_external_write=True,
        dry_run=False,
        vibecode_timeline_log=True,
    )

    class FakeVibe:
        def timeline_log(self, *_args, **_kwargs):
            raise AssertionError("timeline_log must be skipped when external writes are disabled")

    monkeypatch.setattr(
        "pipelines.processing.calls.load_cached_transcript",
        lambda state, call_id, deal_id, activity_id: (
            cached_path.read_text(encoding="utf-8"),
            cached_path,
        ),
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.attach_transcription_to_bitrix",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("attach must be skipped")),
    )

    async def fail_activity_get(*_args, **_kwargs):
        raise AssertionError("activity_get is not needed when attach is skipped")

    monkeypatch.setattr("pipelines.processing.calls.activity_get", fail_activity_get)
    monkeypatch.setattr("pipelines.processing.calls._save_state_cache", lambda state: None)

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
        vibe=FakeVibe(),
    )

    row, success = await process_call(
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
    assert row["attach_result"] == {"skipped": True, "reason": "no_external_write"}
    assert row["timeline_log_result"] == {"skipped": True, "reason": "no_external_write"}


@pytest.mark.asyncio
async def test_process_call_dry_run_without_cache_skips_download_and_asr(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=False,
        force_attach=False,
        download_audio=False,
        dry_run=True,
        no_external_write=False,
    )

    async def fail_download_audio_for_call(**_kwargs):
        raise AssertionError("dry-run must not download audio")

    async def fail_transcribe_with_bitnewton(**_kwargs):
        raise AssertionError("dry-run must not call Bit.Newton")

    monkeypatch.setattr(
        "pipelines.processing.calls.load_cached_transcript", lambda *args: (None, None)
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.download_audio_for_call", fail_download_audio_for_call
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.transcribe_with_bitnewton", fail_transcribe_with_bitnewton
    )

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

    row, success = await process_call(
        ctx=ctx,
        deal_id="11",
        deal={"ID": "11", "STAGE_ID": "NEW", "TITLE": "КП касса", "OPPORTUNITY": "10000"},
        comments=[],
        discipline={"first_response_minutes": 10},
        deal_quality={"deal_quality_score": 50},
        manager_id=5,
        call_center_acts=[],
        activity={"ID": "101", "ORIGIN_ID": "CALL-101", "SUBJECT": "Исходящий звонок"},
    )

    assert success is True
    assert row["asr_skipped"] is True
    assert row["bitnewton_task_id"] == "skipped_asr"
    assert "dry-run" in row["asr_status"]
    assert row["attach_result"] is None


@pytest.mark.asyncio
async def test_process_call_without_cache_downloads_transcribes_and_attaches(monkeypatch, tmp_path):
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

    async def fake_download_audio_for_call(**kwargs):
        audio_path.write_bytes(b"audio")
        kwargs["row"]["audio_path"] = str(audio_path)
        kwargs["row"]["disk_file_id"] = "disk-1"
        assert kwargs["call_id"] == "CALL-200"
        return audio_path, kwargs["ui_browser_session"]

    async def fake_transcribe_with_bitnewton(**kwargs):
        assert kwargs["audio_path"] == audio_path
        assert kwargs["diarize"] is True
        transcript_path.write_text(
            "Добрый день. Уточню потребность и отправлю КП.", encoding="utf-8"
        )
        return transcript_path.read_text(encoding="utf-8"), "task-200", transcript_path

    async def fake_attach_transcription_to_bitrix(api, call_id, transcript_text, duration):
        captured_attach.update(
            {
                "call_id": call_id,
                "transcript_text": transcript_text,
                "duration": duration,
            }
        )
        return {"ok": True, "call_id": call_id}

    monkeypatch.setattr(
        "pipelines.processing.calls.load_cached_transcript", lambda *args: (None, None)
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.download_audio_for_call", fake_download_audio_for_call
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.transcribe_with_bitnewton", fake_transcribe_with_bitnewton
    )
    monkeypatch.setattr(
        "pipelines.processing.calls.attach_transcription_to_bitrix",
        fake_attach_transcription_to_bitrix,
    )

    async def fake_activity_get(api, activity_id):
        return {
            "ID": activity_id,
            "START_TIME": "2026-05-01T10:00:00+03:00",
            "END_TIME": "2026-05-01T10:03:00+03:00",
        }

    monkeypatch.setattr("pipelines.processing.calls.activity_get", fake_activity_get)
    monkeypatch.setattr("pipelines.processing.calls._save_state_cache", lambda state: None)

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

    row, success = await process_call(
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


@pytest.mark.asyncio
async def test_process_call_returns_error_row_when_download_fails(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=True,
        force_attach=False,
        download_audio=False,
    )

    async def fake_download_audio_for_call(**kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(
        "pipelines.processing.calls.download_audio_for_call", fake_download_audio_for_call
    )
    monkeypatch.setattr("pipelines.processing.calls._save_state_cache", lambda state: None)

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

    row, success = await process_call(
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


@pytest.mark.asyncio
async def test_process_call_marks_asr_skipped_for_bitnewton_auth_error(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    audio_path = tmp_path / "call.mp3"
    audio_path.write_bytes(b"audio")
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        no_reuse_transcripts=True,
        force_attach=False,
        download_audio=False,
        diarize=False,
        fetch_bitrix_card_transcript=False,
        ui_download=False,
    )

    async def fake_download_audio_for_call(**kwargs):
        return audio_path, kwargs["ui_browser_session"]

    monkeypatch.setattr(
        "pipelines.processing.calls.download_audio_for_call", fake_download_audio_for_call
    )

    async def fake_transcribe_with_bitnewton(**kwargs):
        raise BitNewtonAuthError(
            "ASR start_transcribing: токен Bit.Newton истёк/неверный (HTTP 401)."
        )

    monkeypatch.setattr(
        "pipelines.processing.calls.transcribe_with_bitnewton", fake_transcribe_with_bitnewton
    )

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

    row, success = await process_call(
        ctx=ctx,
        deal_id="31",
        deal={"ID": "31", "STAGE_ID": "NEW", "TITLE": "КП касса"},
        comments=[],
        discipline={"first_response_minutes": 10},
        deal_quality={"deal_quality_score": 25},
        manager_id=5,
        call_center_acts=[],
        activity={"ID": "301", "ORIGIN_ID": "CALL-301", "SUBJECT": "Исходящий звонок"},
    )

    assert success is True
    assert row["error"] is None
    assert row["asr_skipped"] is True
    assert "ASR пропущена" in row["asr_status"]
    assert ctx.asr_disabled_reason


@pytest.mark.asyncio
async def test_process_deal_returns_no_call_result(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru", include_call_center=True, max_calls_per_deal=0
    )

    async def fake_list_activities(api, deal_id):
        return []

    async def fake_deal_get(api, deal_id):
        return {"ID": deal_id, "STAGE_ID": "NEW", "TITLE": "КП касса", "ASSIGNED_BY_ID": "5"}

    async def fake_fetch_comments(api, deal_id):
        return []

    monkeypatch.setattr(
        "pipelines.processing.deals.list_deal_call_activities", fake_list_activities
    )
    monkeypatch.setattr("pipelines.processing.deals.deal_get", fake_deal_get)
    monkeypatch.setattr("pipelines.processing.deals.fetch_timeline_comments", fake_fetch_comments)

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

    result = await process_deal(
        ctx=ctx,
        deal_id="40",
        deal_index=1,
        total_deals=1,
        retry_scope=None,
        user_cache={},
        department_cache={},
        base_ok=2,
        base_err=3,
    )

    assert result.ok == 0
    assert result.err == 1
    assert len(result.rows) == 1
    assert result.rows[0]["no_calls"] is True
    assert result.rows[0]["deal_id"] == "40"


@pytest.mark.asyncio
async def test_process_deal_keeps_running_when_deal_is_missing(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru", include_call_center=True, max_calls_per_deal=0
    )

    async def fake_list_activities(api, deal_id):
        return []

    async def fake_deal_get(api, deal_id):
        raise Exception("HTTP 400 при вызове crm.deal.get (request_id=None): Not found")

    monkeypatch.setattr(
        "pipelines.processing.deals.list_deal_call_activities", fake_list_activities
    )
    monkeypatch.setattr("pipelines.processing.deals.deal_get", fake_deal_get)

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

    result = await process_deal(
        ctx=ctx,
        deal_id="124573",
        deal_index=1,
        total_deals=1,
        retry_scope={"activity_ids_by_deal": {}, "full_deals": {"124573"}},
        user_cache={},
        department_cache={},
    )

    assert result.ok == 0
    assert result.err == 1
    assert len(result.rows) == 1
    assert result.rows[0]["deal_id"] == "124573"
    assert result.rows[0]["no_calls"] is True
    assert "Сделка не найдена" in result.rows[0]["error"]


@pytest.mark.asyncio
async def test_process_deal_filters_retry_scope_to_failed_activity(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru", include_call_center=True, max_calls_per_deal=0
    )
    processed_activity_ids = []

    async def fake_list_activities(api, deal_id):
        return [
            {"ID": "401", "ORIGIN_ID": "CALL-401", "SUBJECT": "failed call"},
            {"ID": "402", "ORIGIN_ID": "CALL-402", "SUBJECT": "ok call"},
        ]

    async def fake_deal_get(api, deal_id):
        return {
            "ID": deal_id,
            "STAGE_ID": "NEW",
            "TITLE": "КП касса",
            "ASSIGNED_BY_ID": "5",
            "DATE_CREATE": "2026-05-01T09:00:00+03:00",
        }

    async def fake_fetch_comments(api, deal_id):
        return []

    monkeypatch.setattr(
        "pipelines.processing.deals.list_deal_call_activities", fake_list_activities
    )
    monkeypatch.setattr("pipelines.processing.deals.deal_get", fake_deal_get)
    monkeypatch.setattr("pipelines.processing.deals.fetch_timeline_comments", fake_fetch_comments)

    async def fake_process_call(**kwargs):
        activity_id = kwargs["activity"]["ID"]
        processed_activity_ids.append(activity_id)
        return {"deal_id": kwargs["deal_id"], "activity_id": activity_id, "manager_id": 5}, True

    monkeypatch.setattr("pipelines.processing.deals.process_call", fake_process_call)

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

    result = await process_deal(
        ctx=ctx,
        deal_id="40",
        deal_index=1,
        total_deals=1,
        retry_scope={"activity_ids_by_deal": {"40": {401}}, "full_deals": set()},
        user_cache={},
        department_cache={},
    )

    assert result.ok == 1
    assert result.err == 0
    assert processed_activity_ids == [401]
    assert [row["activity_id"] for row in result.rows] == [401]


@pytest.mark.asyncio
async def test_process_deal_skips_short_calls_before_processing(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    args = SimpleNamespace(
        domain="example.bitrix24.ru",
        include_call_center=True,
        max_calls_per_deal=0,
        min_call_duration_sec=15,
    )
    processed_activity_ids = []

    async def fake_list_activities(api, deal_id):
        return [
            {
                "ID": "501",
                "ORIGIN_ID": "CALL-501",
                "SUBJECT": "короткий дозвон",
                "START_TIME": "2026-05-01T10:00:00+03:00",
                "END_TIME": "2026-05-01T10:00:04+03:00",
            },
            {
                "ID": "502",
                "ORIGIN_ID": "CALL-502",
                "SUBJECT": "нормальный звонок",
                "START_TIME": "2026-05-01T10:00:00+03:00",
                "END_TIME": "2026-05-01T10:01:00+03:00",
            },
        ]

    async def fake_deal_get(api, deal_id):
        return {
            "ID": deal_id,
            "STAGE_ID": "NEW",
            "TITLE": "КП касса",
            "ASSIGNED_BY_ID": "5",
            "DATE_CREATE": "2026-05-01T09:00:00+03:00",
        }

    async def fake_fetch_comments(api, deal_id):
        return []

    monkeypatch.setattr(
        "pipelines.processing.deals.list_deal_call_activities", fake_list_activities
    )
    monkeypatch.setattr("pipelines.processing.deals.deal_get", fake_deal_get)
    monkeypatch.setattr("pipelines.processing.deals.fetch_timeline_comments", fake_fetch_comments)

    async def fake_process_call(**kwargs):
        processed_activity_ids.append(kwargs["activity"]["ID"])
        return {
            "deal_id": kwargs["deal_id"],
            "activity_id": kwargs["activity"]["ID"],
            "manager_id": 5,
            "skipped_short_calls": kwargs["skipped_short_calls"],
        }, True

    monkeypatch.setattr("pipelines.processing.deals.process_call", fake_process_call)

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

    result = await process_deal(
        ctx=ctx,
        deal_id="50",
        deal_index=1,
        total_deals=1,
        retry_scope=None,
        user_cache={},
        department_cache={},
    )

    assert result.ok == 1
    assert processed_activity_ids == [502]
    assert result.rows[0]["skipped_short_calls"] == 1


@pytest.mark.asyncio
async def test_process_deals_aggregates_rows_and_counters(monkeypatch, tmp_path):
    kpi = load_kpi_config(None)
    calls = []

    async def fake_process_deal(**kwargs):
        deal_id = kwargs["deal_id"]
        calls.append((deal_id, kwargs["base_ok"], kwargs["base_err"]))
        from pipelines.processing.context import DealProcessingResult

        if deal_id == "10":
            return DealProcessingResult(rows=[{"deal_id": "10"}], ok=1, err=0)
        return DealProcessingResult(rows=[{"deal_id": "20"}], ok=0, err=2)

    monkeypatch.setattr("pipelines.processing.deals.process_deal", fake_process_deal)
    ctx = ProcessingContext(
        api=object(),
        asr=object(),
        args=SimpleNamespace(),
        kpi=kpi,
        kpi_cmp=None,
        audio_source_index=[],
        audio_dir=tmp_path,
        ui_audio_dir=tmp_path,
        state_cache={},
    )

    result = await process_deals(ctx=ctx, deal_ids=["10", "20"], retry_scope=None)

    assert result.rows == [{"deal_id": "10"}, {"deal_id": "20"}]
    assert result.ok == 1
    assert result.err == 2
    assert calls == [
        ("10", 0, 0),
        ("20", 0, 0),
    ]  # parallel execution means base_ok/base_err are same
