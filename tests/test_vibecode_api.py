from pathlib import Path

from vibecode_api import (
    VibeCodeClient,
    VibeCodeError,
    bitrix_filter_to_vibe,
    vibe_activity_to_bitrix,
    vibe_deal_to_bitrix,
    vibe_stage_history_to_bitrix,
)


def test_vibecode_filter_maps_common_bitrix_fields():
    out = bitrix_filter_to_vibe(
        {
            "CATEGORY_ID": 1,
            "STAGE_ID": ["C1:NEW"],
            ">=DATE_CREATE": "2026-05-01",
            "<DATE_CREATE": "2026-05-16",
            "=STAGE_SEMANTIC_ID": "F",
        }
    )

    assert out == {
        "categoryId": 1,
        "stageId": ["C1:NEW"],
        ">=createdAt": "2026-05-01",
        "<createdAt": "2026-05-16",
        "stageSemanticId": "F",
    }


def test_vibecode_deal_activity_and_stage_history_mapping():
    assert vibe_deal_to_bitrix(
        {
            "id": 10,
            "title": "Сделка",
            "assignedById": 5,
            "stageId": "C1:NEW",
            "createdAt": "2026-05-01",
        }
    ) == {
        "id": 10,
        "title": "Сделка",
        "assignedById": 5,
        "stageId": "C1:NEW",
        "createdAt": "2026-05-01",
        "ID": 10,
        "TITLE": "Сделка",
        "ASSIGNED_BY_ID": 5,
        "STAGE_ID": "C1:NEW",
        "DATE_CREATE": "2026-05-01",
    }
    assert (
        vibe_activity_to_bitrix({"id": 100, "originId": "VI_1", "startTime": "2026"})["ORIGIN_ID"]
        == "VI_1"
    )
    assert (
        vibe_stage_history_to_bitrix({"id": 1, "ownerId": 10, "stageId": "C1:NEW"})["OWNER_ID"]
        == 10
    )


def test_vibecode_download_contract_with_fake_client(tmp_path):
    class FakeVibe:
        def download_file(self, file_id, out_path):
            assert file_id == 123
            Path(out_path).write_bytes(b"ID3" + b"x" * 3000)
            return out_path

    out = tmp_path / "call.mp3"
    FakeVibe().download_file(123, out)

    assert out.exists()
    assert out.stat().st_size > 2048


def test_vibecode_search_deals_retries_without_auto_window(monkeypatch):
    client = VibeCodeClient(api_key="test-key")
    calls = []

    def fake_post(path, body):
        calls.append(body)
        if len(calls) == 1:
            raise VibeCodeError("WINDOWED_SEARCH_FAILED")
        return {"data": [{"id": 10, "title": "Сделка"}]}

    monkeypatch.setattr(client, "post", fake_post)

    rows = client.search_deals({"CATEGORY_ID": 1}, limit=10)

    assert rows[0]["ID"] == 10
    assert "autoWindow" not in calls[0]
    assert calls[1]["autoWindow"] is False
