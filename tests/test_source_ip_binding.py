from bit_new_ton_asr import env_bitnewton_asr as env_bitnewton_asr_async
from bit_newton_asr import env_bitnewton_asr as env_bitnewton_asr_sync
from download_resolver import _source_ip_from_env


def test_source_ip_from_env_prefers_argument_over_environment(monkeypatch):
    monkeypatch.setenv("BITRIX24_SOURCE_IP", "192.168.1.103")

    assert _source_ip_from_env("10.0.0.5") == "10.0.0.5"
    assert _source_ip_from_env(None) == "192.168.1.103"


def test_env_bitnewton_asr_sync_uses_fallback_source_ip(monkeypatch):
    monkeypatch.setenv("BITNEWTON_TOKEN", "token")
    monkeypatch.delenv("BITNEWTON_SOURCE_IP", raising=False)
    monkeypatch.setenv("BITRIX24_SOURCE_IP", "192.168.1.103")

    asr = env_bitnewton_asr_sync()

    assert asr is not None
    assert asr.source_ip == "192.168.1.103"


def test_env_bitnewton_asr_async_uses_fallback_source_ip(monkeypatch):
    monkeypatch.setenv("BITNEWTON_TOKEN", "token")
    monkeypatch.delenv("BITNEWTON_SOURCE_IP", raising=False)
    monkeypatch.setenv("BITRIX24_SOURCE_IP", "192.168.1.103")

    asr = env_bitnewton_asr_async()

    assert asr is not None
    assert asr.source_ip == "192.168.1.103"
