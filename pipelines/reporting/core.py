from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from logging_setup import get_logger
from pipelines.conversation_intelligence import build_conversation_intelligence
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reporting.excel_writer import write_excel_report
from pipelines.reporting.profile_descriptions import KPI_PROFILE_DESCRIPTIONS
from pipelines.reporting.rows import (
    build_call_checklist_rows,
    build_call_detail_rows,
    build_coaching_plan_rows,
    build_crm_checklist_rows,
    build_deal_report_rows,
    build_executive_summary_rows,
    build_manager_criterion_gap_rows,
    build_manager_crm_gap_rows,
    build_manager_scorecard_rows,
    build_manager_stage_summary_rows,
    build_objection_rows,
    build_quality_control_rows,
    build_sales_stage_score_rows,
    build_stage_history_rows,
    build_stage_movement_rows,
    build_stage_sr_rows,
)
from pipelines.script_scoring import (
    build_script_gap_rows,
    build_script_profile_rows,
    build_script_score_rows,
)
from pipelines.stages import stage_display_name

logger = get_logger(__name__)


def publish_latest_report(json_path: Path, xlsx_path: Path) -> None:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if json_path.exists():
            shutil.copy2(json_path, LATEST_JSON_REPORT)
        if xlsx_path.exists():
            shutil.copy2(xlsx_path, LATEST_XLSX_REPORT)
    except Exception as e:
        logger.warning(f"[WARN] Не удалось обновить latest-отчет: {e}")


def kpi_profile_display(profile: Any) -> tuple[str, str]:
    key = str(profile or "").strip()
    if not key:
        return "", ""
    title, explanation = KPI_PROFILE_DESCRIPTIONS.get(key, (key, "Пользовательский профиль KPI."))
    return title, explanation


def prepare_report_rows(
    rows: list[dict[str, Any]], stage_map: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        r["stage_name"] = stage_display_name(r.get("stage_id"), stage_map=stage_map) or r.get(
            "stage_name"
        )
        profile_title, profile_explanation = kpi_profile_display(r.get("kpi_profile"))
        r["kpi_profile_ru"] = profile_title
        r["kpi_explanation"] = profile_explanation
        if r.get("kpi_profile_cmp"):
            cmp_title, cmp_explanation = kpi_profile_display(r.get("kpi_profile_cmp"))
            r["kpi_profile_cmp_ru"] = cmp_title
            r["kpi_explanation_cmp"] = cmp_explanation
        out.append(r)
    return out


def flatten_results(
    rows: list[dict[str, Any]],
    manager_summary: list[dict[str, Any]],
    manager_summary_cmp: list[dict[str, Any]] | None = None,
    stage_map: dict[str, str] | None = None,
    lost_deals_analysis: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"bitnewton_sync_report_{ts}.xlsx"
    report_rows = prepare_report_rows(rows, stage_map=stage_map)

    # 1. Сбор данных для вкладок
    deal_report_rows = build_deal_report_rows(report_rows)
    call_detail_rows = build_call_detail_rows(report_rows)
    objection_rows = build_objection_rows(report_rows)
    checklist_rows = build_call_checklist_rows(report_rows)
    sales_stage_score_rows = build_sales_stage_score_rows(report_rows)
    manager_stage_rows = build_manager_stage_summary_rows(report_rows)
    manager_criterion_gap_rows = build_manager_criterion_gap_rows(report_rows)
    crm_checklist_rows = build_crm_checklist_rows(report_rows)
    manager_crm_gap_rows = build_manager_crm_gap_rows(report_rows)
    quality_control_rows = build_quality_control_rows(deal_report_rows)
    coaching_plan_rows = build_coaching_plan_rows(
        manager_criterion_gap_rows, manager_crm_gap_rows, manager_stage_rows
    )
    executive_summary_rows = build_executive_summary_rows(
        deal_report_rows,
        manager_summary,
        quality_control_rows,
        manager_criterion_gap_rows,
        manager_crm_gap_rows,
        coaching_plan_rows,
    )
    manager_scorecard_rows = build_manager_scorecard_rows(
        manager_summary, quality_control_rows, coaching_plan_rows
    )
    stage_history_rows = build_stage_history_rows(report_rows)
    stage_sr_rows = build_stage_sr_rows(report_rows, stage_map=stage_map)
    stage_movement_rows = build_stage_movement_rows(report_rows)

    lost_deal_rows = (lost_deals_analysis or {}).get("rows") or []
    lost_reason_summary_rows = (lost_deals_analysis or {}).get("summary_rows") or []
    conversion_action_rows = (lost_deals_analysis or {}).get("action_rows") or []

    conversation_intelligence = build_conversation_intelligence(
        report_rows, lost_reason_summary_rows
    )
    script_score_rows = build_script_score_rows(report_rows)

    # 2. Вызов специализированного модуля для записи Excel
    write_excel_report(
        out,
        executive_summary_rows=executive_summary_rows,
        manager_scorecard_rows=manager_scorecard_rows,
        deal_report_rows=deal_report_rows,
        call_detail_rows=call_detail_rows,
        objection_rows=objection_rows,
        conversation_map_rows=conversation_intelligence["conversation_map_rows"],
        ci_objection_rows=conversation_intelligence["objection_rows"],
        emotional_risk_rows=conversation_intelligence["emotional_risk_rows"],
        ci_conversion_factor_rows=conversation_intelligence["conversion_factor_rows"],
        ci_manager_recommendation_rows=conversation_intelligence["manager_recommendation_rows"],
        script_profile_rows=build_script_profile_rows(script_score_rows),
        script_score_rows=script_score_rows,
        script_gap_rows=build_script_gap_rows(script_score_rows),
        checklist_rows=checklist_rows,
        sales_stage_score_rows=sales_stage_score_rows,
        manager_stage_rows=manager_stage_rows,
        manager_criterion_gap_rows=manager_criterion_gap_rows,
        crm_checklist_rows=crm_checklist_rows,
        manager_crm_gap_rows=manager_crm_gap_rows,
        quality_control_rows=quality_control_rows,
        coaching_plan_rows=coaching_plan_rows,
        stage_history_rows=stage_history_rows,
        stage_sr_rows=stage_sr_rows,
        stage_movement_rows=stage_movement_rows,
        lost_deal_rows=lost_deal_rows,
        lost_reason_summary_rows=lost_reason_summary_rows,
        conversion_action_rows=conversion_action_rows,
        manager_summary=manager_summary,
        manager_summary_cmp=manager_summary_cmp,
    )

    return out
