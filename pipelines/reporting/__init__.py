from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pipelines.reporting import core as _core
from pipelines.reporting import rows as _rows
from pipelines.reporting.ru_columns import RU_COLUMNS

LATEST_JSON_REPORT = _core.LATEST_JSON_REPORT
LATEST_XLSX_REPORT = _core.LATEST_XLSX_REPORT
REPORTS_DIR = _core.REPORTS_DIR

build_call_checklist_rows = _rows.build_call_checklist_rows
build_call_detail_rows = _rows.build_call_detail_rows
build_coaching_plan_rows = _rows.build_coaching_plan_rows
build_crm_checklist_rows = _rows.build_crm_checklist_rows
build_deal_conclusions = _rows.build_deal_conclusions
build_deal_report_rows = _rows.build_deal_report_rows
build_executive_summary_rows = _rows.build_executive_summary_rows
build_manager_criterion_gap_rows = _rows.build_manager_criterion_gap_rows
build_manager_crm_gap_rows = _rows.build_manager_crm_gap_rows
build_manager_scorecard_rows = _rows.build_manager_scorecard_rows
build_manager_stage_summary_rows = _rows.build_manager_stage_summary_rows
build_manager_summary = _rows.build_manager_summary
build_objection_rows = _rows.build_objection_rows
build_quality_control_rows = _rows.build_quality_control_rows
build_sales_stage_score_rows = _rows.build_sales_stage_score_rows
build_stage_history_rows = _rows.build_stage_history_rows
build_stage_movement_rows = _rows.build_stage_movement_rows
build_stage_sr_rows = _rows.build_stage_sr_rows
kpi_profile_display = _core.kpi_profile_display
prepare_report_rows = _core.prepare_report_rows


def _sync_paths() -> None:
    _core.REPORTS_DIR = REPORTS_DIR
    _core.LATEST_JSON_REPORT = LATEST_JSON_REPORT
    _core.LATEST_XLSX_REPORT = LATEST_XLSX_REPORT


def publish_latest_report(json_path: Path, xlsx_path: Path) -> None:
    _sync_paths()
    _core.publish_latest_report(json_path, xlsx_path)


def flatten_results(
    rows: List[Dict[str, Any]],
    manager_summary: List[Dict[str, Any]],
    manager_summary_cmp: Optional[List[Dict[str, Any]]] = None,
    stage_map: Optional[Dict[str, str]] = None,
    lost_deals_analysis: Optional[Dict[str, Any]] = None,
) -> Path:
    _sync_paths()
    return _core.flatten_results(
        rows,
        manager_summary,
        manager_summary_cmp=manager_summary_cmp,
        stage_map=stage_map,
        lost_deals_analysis=lost_deals_analysis,
    )


__all__ = [
    "LATEST_JSON_REPORT",
    "LATEST_XLSX_REPORT",
    "REPORTS_DIR",
    "RU_COLUMNS",
    "build_call_checklist_rows",
    "build_call_detail_rows",
    "build_coaching_plan_rows",
    "build_crm_checklist_rows",
    "build_deal_conclusions",
    "build_deal_report_rows",
    "build_executive_summary_rows",
    "build_manager_criterion_gap_rows",
    "build_manager_crm_gap_rows",
    "build_manager_scorecard_rows",
    "build_manager_stage_summary_rows",
    "build_manager_summary",
    "build_objection_rows",
    "build_quality_control_rows",
    "build_sales_stage_score_rows",
    "build_stage_history_rows",
    "build_stage_movement_rows",
    "build_stage_sr_rows",
    "flatten_results",
    "kpi_profile_display",
    "prepare_report_rows",
    "publish_latest_report",
]
