from types import SimpleNamespace

import pytest

from pipelines.factories import create_bitnewton_asr
from pipelines.runtime import (
    AudioRuntime,
    build_processing_context,
    prepare_audio_runtime,
    resolve_deal_scope,
)


def test_create_bitnewton_asr_requires_enabled_flag():
    args = SimpleNamespace(use_bitnewton=False, bitnewton_flow=False)

    with pytest.raises(SystemExit, match="--use-bitnewton"):
        create_bitnewton_asr(args)


def test_create_bitnewton_asr_returns_disabled_asr_without_token(monkeypatch):
    args = SimpleNamespace(use_bitnewton=True, bitnewton_flow=False)
    monkeypatch.setattr("pipelines.factories.env_bitnewton_asr", lambda: None)

    asr = create_bitnewton_asr(args)

    assert "BITNEWTON_TOKEN" in asr.auth_error


def test_resolve_deal_scope_uses_retry_scope(monkeypatch):
    retry_scope = {"deal_ids": ["10", "20"], "errors": 2}
    args = SimpleNamespace(retry_errors_from="report.json")
    monkeypatch.setattr("pipelines.runtime.load_retry_scope", lambda path: retry_scope)

    scope, deal_ids = resolve_deal_scope(args, api=object())

    assert scope is retry_scope
    assert deal_ids == ["10", "20"]


def test_resolve_deal_scope_falls_back_to_filter(monkeypatch):
    args = SimpleNamespace(retry_errors_from=None)
    monkeypatch.setattr("pipelines.runtime.resolve_deal_ids", lambda args, api, vibe=None: ["30"])

    scope, deal_ids = resolve_deal_scope(args, api=object())

    assert scope is None
    assert deal_ids == ["30"]


def test_prepare_audio_runtime_creates_dirs_and_runs_cleanup(monkeypatch, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "call.mp3"
    source_file.write_bytes(b"audio")
    cleanup_calls = []
    args = SimpleNamespace(
        ui_download_dir=None,
        audio_source_dir=[str(source_dir)],
        cleanup_output_days=30,
    )

    def fake_cleanup_old_outputs(base_dir, keep_days, extra_audio_dirs=None):
        cleanup_calls.append((base_dir, keep_days, extra_audio_dirs))
        return {"reports": 1, "audio": 0, "transcripts": 0, "total": 1}

    monkeypatch.setattr("pipelines.runtime.REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("pipelines.runtime.cleanup_old_outputs", fake_cleanup_old_outputs)

    audio_runtime = prepare_audio_runtime(args)

    assert audio_runtime.audio_dir == tmp_path / "reports" / "audio"
    assert audio_runtime.ui_audio_dir == tmp_path / "reports" / "audio_ui"
    assert audio_runtime.audio_dir.exists()
    assert audio_runtime.ui_audio_dir.exists()
    assert audio_runtime.audio_source_index == [source_file]
    assert cleanup_calls == [(tmp_path / "reports", 30, [tmp_path / "reports" / "audio_ui"])]


def test_build_processing_context_uses_audio_runtime(tmp_path):
    args = SimpleNamespace()
    audio_runtime = AudioRuntime(
        audio_dir=tmp_path / "audio",
        ui_audio_dir=tmp_path / "audio_ui",
        audio_source_index=[tmp_path / "call.mp3"],
    )
    state_cache = {}

    ctx = build_processing_context(
        api=object(),
        asr=object(),
        args=args,
        kpi={"profile": {"name": "base"}},
        kpi_cmp=None,
        audio_runtime=audio_runtime,
        state_cache=state_cache,
    )

    assert ctx.audio_dir == audio_runtime.audio_dir
    assert ctx.ui_audio_dir == audio_runtime.ui_audio_dir
    assert ctx.audio_source_index == audio_runtime.audio_source_index
    assert ctx.state_cache is state_cache
