from pipelines.bitnewton_sync import merge_retry_results


def test_merge_retry_results_replaces_only_failed_activity():
    original = [
        {"deal_id": "10", "activity_id": 100, "error": "download failed"},
        {"deal_id": "10", "activity_id": 101, "error": None, "transcript_text": "old ok"},
        {"deal_id": "20", "activity_id": 200, "error": None},
    ]
    retry_rows = [
        {"deal_id": "10", "activity_id": 100, "error": None, "transcript_text": "new ok"},
    ]
    scope = {
        "activity_ids_by_deal": {"10": {100}},
        "full_deals": set(),
    }

    merged = merge_retry_results(original, retry_rows, scope)

    assert len(merged) == 3
    assert merged[0]["transcript_text"] == "new ok"
    assert merged[0]["error"] is None
    assert merged[1]["transcript_text"] == "old ok"
    assert merged[2]["deal_id"] == "20"


def test_merge_retry_results_replaces_full_deal_when_deal_level_error():
    original = [
        {"deal_id": "10", "activity_id": None, "error": "no calls"},
        {"deal_id": "20", "activity_id": 200, "error": None},
    ]
    retry_rows = [
        {"deal_id": "10", "activity_id": 101, "error": None},
        {"deal_id": "10", "activity_id": 102, "error": None},
    ]
    scope = {
        "activity_ids_by_deal": {},
        "full_deals": {"10"},
    }

    merged = merge_retry_results(original, retry_rows, scope)

    assert [row["deal_id"] for row in merged] == ["10", "10", "20"]
    assert [row["activity_id"] for row in merged[:2]] == [101, 102]
    assert all(row["error"] is None for row in merged[:2])
