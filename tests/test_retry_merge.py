import json

from pipelines.retry import load_retry_scope, merge_retry_results


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


def test_load_retry_scope_collects_activity_and_deal_errors(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            [
                {"deal_id": "10", "activity_id": 100, "error": "download failed"},
                {
                    "deal_url": "https://example.bitrix24.ru/crm/deal/details/20/",
                    "activity_id": None,
                    "error": "no calls",
                },
                {"deal_id": "30", "activity_id": 300, "error": None},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scope = load_retry_scope(report)

    assert scope["deal_ids"] == ["10", "20"]
    assert scope["activity_ids_by_deal"] == {"10": {100}}
    assert scope["full_deals"] == {"20"}
    assert scope["errors"] == 2
