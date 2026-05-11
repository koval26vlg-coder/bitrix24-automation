from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bitrix.api import Bitrix24API
from pipelines.calls import user_name_map
from pipelines.cleanup import cleanup_old_chrome_tmp_profiles
from pipelines.deals import deal_id_from_report_row
from pipelines.evaluation import refresh_crm_scores_after_stage_metrics
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reporting import build_manager_summary, flatten_results, prepare_report_rows, publish_latest_report
from pipelines.retry import merge_retry_results
from pipelines.stage_history import (
    attach_stage_history_metrics,
    fetch_stage_history_by_deals,
    fetch_stage_name_map,
)


@dataclass
class SyncReportOutput:
    json_out: Path
    xlsx_out: Path
    final_results: List[Dict[str, Any]]
    stage_map: Dict[str, str]


def enrich_manager_names(api: Bitrix24API, results: List[Dict[str, Any]]) -> None:
    manager_ids = [int(row["manager_id"]) for row in results if isinstance(row.get("manager_id"), int)]
    names = user_name_map(api, manager_ids) if manager_ids else {}
    for row in results:
        manager_id = row.get("manager_id")
        if isinstance(manager_id, int):
            row["manager_name"] = names.get(manager_id, str(manager_id))
        if row.get("overall_score") is None:
            row["overall_score"] = 0.0


def load_stage_context(
    api: Bitrix24API,
    results: List[Dict[str, Any]],
) -> tuple[Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
    stage_ids_for_map = [str(row.get("stage_id") or "") for row in results]
    stage_history_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    try:
        unique_deal_ids = sorted(
            {str(deal_id_from_report_row(row) or "") for row in results if deal_id_from_report_row(row)}
        )
        if unique_deal_ids:
            print("[STAGE] Загружаю историю перемещений сделок по стадиям", flush=True)
            stage_history_by_deal = fetch_stage_history_by_deals(api, unique_deal_ids)
            for items in stage_history_by_deal.values():
                stage_ids_for_map.extend(str(item.get("STAGE_ID") or "") for item in items if isinstance(item, dict))
    except Exception as e:
        print(f"[WARN] Не удалось загрузить историю стадий: {e}", flush=True)

    stage_map = fetch_stage_name_map(api, stage_ids_for_map)
    return stage_map, stage_history_by_deal


def apply_stage_context(
    api: Bitrix24API,
    results: List[Dict[str, Any]],
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    stage_map, stage_history_by_deal = load_stage_context(api, results)
    if stage_history_by_deal:
        attach_stage_history_metrics(results, stage_history_by_deal, stage_map=stage_map)
    refresh_crm_scores_after_stage_metrics(results, kpi, kpi_cmp)
    return stage_map


def apply_retry_merge(
    results: List[Dict[str, Any]],
    retry_scope: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if retry_scope is None:
        return results

    source_rows = list(retry_scope.get("source_rows") or [])
    final_results = merge_retry_results(source_rows, results, retry_scope)
    print(
        f"[RETRY] Пересобираю полный отчет: исходных строк={len(source_rows)}, "
        f"повторно обработано={len(results)}, итоговых строк={len(final_results)}",
        flush=True,
    )
    return final_results


def write_sync_report(
    final_results: List[Dict[str, Any]],
    stage_map: Dict[str, str],
    kpi_cmp: Optional[Dict[str, Any]],
) -> tuple[Path, Path]:
    manager_summary = build_manager_summary(final_results)
    manager_summary_cmp = (
        build_manager_summary(final_results, score_key="overall_score_cmp") if kpi_cmp is not None else None
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_results = prepare_report_rows(final_results, stage_map=stage_map)
    json_out = REPORTS_DIR / f"bitnewton_sync_report_{timestamp}.json"
    json_out.write_text(json.dumps(report_results, ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(
        report_results,
        manager_summary,
        manager_summary_cmp=manager_summary_cmp,
        stage_map=stage_map,
    )
    publish_latest_report(json_out, xlsx_out)
    return json_out, xlsx_out


def print_kpi_comparison(final_results: List[Dict[str, Any]], kpi_cmp: Optional[Dict[str, Any]]) -> None:
    if kpi_cmp is None:
        return
    ranked = sorted(
        [row for row in final_results if row.get("overall_score_delta") is not None],
        key=lambda row: abs(float(row.get("overall_score_delta") or 0.0)),
        reverse=True,
    )[:5]
    if not ranked:
        return
    print("\nТоп-5 кейсов с максимальной разницей KPI:")
    for index, row in enumerate(ranked, 1):
        print(
            f"{index}. deal={row.get('deal_id')} act={row.get('activity_id')} "
            f"manager={row.get('manager_name') or row.get('manager_id')} "
            f"base={row.get('overall_score')} cmp={row.get('overall_score_cmp')} "
            f"delta={row.get('overall_score_delta')}"
        )


def cleanup_chrome_tmp_if_needed(args: Any) -> None:
    if int(args.cleanup_chrome_tmp_days or 0) <= 0:
        return
    removed = cleanup_old_chrome_tmp_profiles(REPORTS_DIR, keep_days=int(args.cleanup_chrome_tmp_days))
    if removed:
        print(f"[OK] Удалено старых chrome_profile_tmp_*: {removed}")


def finalize_sync_report(
    *,
    api: Bitrix24API,
    args: Any,
    results: List[Dict[str, Any]],
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
    retry_scope: Optional[Dict[str, Any]],
    ok: int,
    err: int,
) -> SyncReportOutput:
    enrich_manager_names(api, results)
    stage_map = apply_stage_context(api, results, kpi, kpi_cmp)
    final_results = apply_retry_merge(results, retry_scope)
    json_out, xlsx_out = write_sync_report(final_results, stage_map, kpi_cmp)

    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    print_kpi_comparison(final_results, kpi_cmp)
    print(f"ИТОГО: OK={ok} ERR={err}")
    cleanup_chrome_tmp_if_needed(args)

    return SyncReportOutput(
        json_out=json_out,
        xlsx_out=xlsx_out,
        final_results=final_results,
        stage_map=stage_map,
    )
