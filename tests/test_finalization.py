from types import SimpleNamespace

from pipelines.finalization import enrich_manager_names, finalize_sync_report, write_sync_report


def test_enrich_manager_names_fills_names_and_default_score(monkeypatch):
    rows = [
        {"deal_id": "10", "manager_id": 5, "overall_score": None},
        {"deal_id": "20", "manager_id": "not-int", "overall_score": 70},
    ]
    monkeypatch.setattr("pipelines.finalization.user_name_map", lambda api, user_ids: {5: "Иван Иванов"})

    enrich_manager_names(api=object(), results=rows)

    assert rows[0]["manager_name"] == "Иван Иванов"
    assert rows[0]["overall_score"] == 0.0
    assert "manager_name" not in rows[1]
    assert rows[1]["overall_score"] == 70


def test_write_sync_report_writes_json_and_returns_xlsx(monkeypatch, tmp_path):
    xlsx_path = tmp_path / "report.xlsx"
    published = {}

    def fake_flatten_results(report_results, manager_summary, manager_summary_cmp=None, stage_map=None):
        xlsx_path.write_bytes(b"xlsx")
        return xlsx_path

    def fake_publish_latest_report(json_path, xlsx_out):
        published["json"] = json_path
        published["xlsx"] = xlsx_out

    monkeypatch.setattr("pipelines.finalization.REPORTS_DIR", tmp_path)
    monkeypatch.setattr("pipelines.finalization.flatten_results", fake_flatten_results)
    monkeypatch.setattr("pipelines.finalization.publish_latest_report", fake_publish_latest_report)

    json_path, returned_xlsx = write_sync_report(
        final_results=[{"deal_id": "10", "manager_id": 5, "overall_score": 80}],
        stage_map={"NEW": "Новая"},
        kpi_cmp=None,
    )

    assert json_path.exists()
    assert returned_xlsx == xlsx_path
    assert published == {"json": json_path, "xlsx": xlsx_path}
    assert '"deal_id": "10"' in json_path.read_text(encoding="utf-8")


def test_finalize_sync_report_orchestrates_final_steps(monkeypatch, tmp_path):
    rows = [{"deal_id": "10", "manager_id": 5, "overall_score": 80}]
    json_path = tmp_path / "out.json"
    xlsx_path = tmp_path / "out.xlsx"
    calls = []

    def fake_enrich_manager_names(api, results):
        calls.append("names")
        results[0]["manager_name"] = "Иван Иванов"

    def fake_apply_stage_context(api, results, kpi, kpi_cmp):
        calls.append("stage")
        return {"NEW": "Новая"}

    def fake_apply_retry_merge(results, retry_scope):
        calls.append("retry")
        return list(results) + [{"deal_id": "source"}]

    def fake_write_sync_report(final_results, stage_map, kpi_cmp):
        calls.append(("write", len(final_results), stage_map))
        json_path.write_text("[]", encoding="utf-8")
        xlsx_path.write_bytes(b"xlsx")
        return json_path, xlsx_path

    monkeypatch.setattr("pipelines.finalization.enrich_manager_names", fake_enrich_manager_names)
    monkeypatch.setattr("pipelines.finalization.apply_stage_context", fake_apply_stage_context)
    monkeypatch.setattr("pipelines.finalization.apply_retry_merge", fake_apply_retry_merge)
    monkeypatch.setattr("pipelines.finalization.write_sync_report", fake_write_sync_report)
    monkeypatch.setattr(
        "pipelines.finalization.print_kpi_comparison",
        lambda final_results, kpi_cmp: calls.append("kpi"),
    )
    monkeypatch.setattr("pipelines.finalization.cleanup_chrome_tmp_if_needed", lambda args: calls.append("cleanup"))

    output = finalize_sync_report(
        api=object(),
        args=SimpleNamespace(cleanup_chrome_tmp_days=0),
        results=rows,
        kpi={},
        kpi_cmp=None,
        retry_scope={"source_rows": [{"deal_id": "source"}]},
        ok=1,
        err=0,
    )

    assert output.json_out == json_path
    assert output.xlsx_out == xlsx_path
    assert output.stage_map == {"NEW": "Новая"}
    assert output.final_results == [
        {"deal_id": "10", "manager_id": 5, "overall_score": 80, "manager_name": "Иван Иванов"},
        {"deal_id": "source"},
    ]
    assert calls == ["names", "stage", "retry", ("write", 2, {"NEW": "Новая"}), "kpi", "cleanup"]
