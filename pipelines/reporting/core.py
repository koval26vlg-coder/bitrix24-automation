from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pipelines.conversation_intelligence import (
    CI_OBJECTION_COLUMNS,
    CONVERSATION_MAP_COLUMNS,
    CONVERSION_FACTOR_COLUMNS,
    EMOTIONAL_RISK_COLUMNS,
    MANAGER_RECOMMENDATION_COLUMNS,
    build_conversation_intelligence,
)
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reporting.profile_descriptions import KPI_PROFILE_DESCRIPTIONS
from pipelines.reporting.excel import _format_excel_writer, _ru_df
from pipelines.script_scoring import (
    SCRIPT_GAP_COLUMNS,
    SCRIPT_PROFILE_COLUMNS,
    SCRIPT_SCORE_COLUMNS,
    build_script_gap_rows,
    build_script_profile_rows,
    build_script_score_rows,
)
from pipelines.stages import stage_display_name

from logging_setup import get_logger

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

def kpi_profile_display(profile: Any) -> Tuple[str, str]:
    key = str(profile or "").strip()
    if not key:
        return "", ""
    title, explanation = KPI_PROFILE_DESCRIPTIONS.get(key, (key, "Пользовательский профиль KPI."))
    return title, explanation


def prepare_report_rows(rows: List[Dict[str, Any]], stage_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        r["stage_name"] = stage_display_name(r.get("stage_id"), stage_map=stage_map) or r.get("stage_name")
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
    rows: List[Dict[str, Any]],
    manager_summary: List[Dict[str, Any]],
    manager_summary_cmp: Optional[List[Dict[str, Any]]] = None,
    stage_map: Optional[Dict[str, str]] = None,
    lost_deals_analysis: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"bitnewton_sync_report_{ts}.xlsx"
    report_rows = prepare_report_rows(rows, stage_map=stage_map)
    df = pd.DataFrame(report_rows)
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
    coaching_plan_rows = build_coaching_plan_rows(manager_criterion_gap_rows, manager_crm_gap_rows, manager_stage_rows)
    executive_summary_rows = build_executive_summary_rows(
        deal_report_rows,
        manager_summary,
        quality_control_rows,
        manager_criterion_gap_rows,
        manager_crm_gap_rows,
        coaching_plan_rows,
    )
    manager_scorecard_rows = build_manager_scorecard_rows(manager_summary, quality_control_rows, coaching_plan_rows)
    stage_history_rows = build_stage_history_rows(report_rows)
    stage_sr_rows = build_stage_sr_rows(report_rows, stage_map=stage_map)
    stage_movement_rows = build_stage_movement_rows(report_rows)
    lost_deal_rows = (lost_deals_analysis or {}).get("rows") or []
    lost_reason_summary_rows = (lost_deals_analysis or {}).get("summary_rows") or []
    conversion_action_rows = (lost_deals_analysis or {}).get("action_rows") or []
    conversation_intelligence = build_conversation_intelligence(report_rows, lost_reason_summary_rows)
    conversation_map_rows = conversation_intelligence["conversation_map_rows"]
    ci_objection_rows = conversation_intelligence["objection_rows"]
    emotional_risk_rows = conversation_intelligence["emotional_risk_rows"]
    ci_conversion_factor_rows = conversation_intelligence["conversion_factor_rows"]
    ci_manager_recommendation_rows = conversation_intelligence["manager_recommendation_rows"]
    script_score_rows = build_script_score_rows(report_rows)
    script_profile_rows = build_script_profile_rows(script_score_rows)
    script_gap_rows = build_script_gap_rows(script_score_rows)
    deal_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "kpi_profile_ru",
        "kpi_explanation",
        "calls_total",
        "calls_ok",
        "calls_failed",
        "asr_skipped_calls",
        "ignored_call_center_calls",
        "skipped_short_calls",
        "no_calls",
        "transcripts_count",
        "avg_overall_score",
        "overall_score_details",
        "avg_call_quality_score",
        "call_quality_details",
        "call_checklist_percent",
        "call_checklist_block_details",
        "deal_quality_score",
        "deal_quality_details",
        "alignment_score",
        "crm_work_score",
        "crm_checklist_percent",
        "crm_checklist_details",
        "alignment_details",
        "stage_history_count",
        "stage_history_path",
        "stage_last_change_at",
        "stage_current_age_minutes",
        "stage_current_age_days",
        "stage_warning_threshold",
        "stage_critical_threshold",
        "stage_current_age_status",
        "deal_total_work_minutes",
        "deal_total_work_days",
        "deal_total_work_warning_threshold",
        "deal_total_work_critical_threshold",
        "deal_total_work_status",
        "stage_return_count",
        "stage_reached_final",
        "stage_movement_risk",
        "stage_movement_recommendation",
        "client_work_score",
        "client_work_quality",
        "conversation_quality",
        "client_work_conclusion",
        "call_quality_conclusion",
        "conversation_meaning",
        "recommendations",
        "calls_breakdown",
        "improvement_moments_combined",
        "objections_combined",
        "unhandled_objections",
        "objection_recommendations",
        "transcript_paths",
        "error",
    ]
    call_detail_cols = [
        "deal_url",
        "call_number",
        "subject",
        "duration_minutes",
        "call_has_error",
        "asr_status",
        "skipped_short_calls",
        "vibecode_download_used",
        "vibecode_download_error",
        "call_quality_score",
        "call_quality_details",
        "call_checklist_total_score",
        "call_checklist_max_score",
        "call_checklist_percent",
        "call_checklist_block_details",
        "has_greeting",
        "has_needs_discovery",
        "has_objection_work",
        "has_next_step_phrase",
        "alignment_score",
        "crm_work_score",
        "crm_checklist_percent",
        "crm_checklist_details",
        "alignment_details",
        "next_step_synced",
        "next_step_synced_details",
        "call_quality_conclusion",
        "conversation_meaning",
        "improvement_moments",
        "unhandled_objections",
        "objection_recommendations",
        "transcript_path",
        "transcript_marked",
        "transcript_text",
        "bitrix_card_transcript_status",
        "transcript_match_score",
        "bitrix_card_transcript",
        "timeline_log_result",
        "timeline_log_error",
        "error",
    ]
    objection_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "subject",
        "objection_fragment",
        "objection_status",
        "objection_recommendations",
    ]
    checklist_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "call_number",
        "subject",
        "duration_minutes",
        "checklist_block_name",
        "checklist_criterion",
        "checklist_score",
        "checklist_max_score",
        "checklist_evidence",
        "checklist_comment",
        "checklist_code",
    ]
    sales_stage_score_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "call_number",
        "subject",
        "duration_minutes",
        "sales_stage_block_name",
        "sales_stage_score",
        "sales_stage_max_score",
        "sales_stage_percent",
        "sales_stage_missing",
    ]
    manager_stage_cols = [
        "manager_name",
        "sales_stage_block_name",
        "manager_stage_calls",
        "manager_stage_deals",
        "manager_stage_avg_percent",
        "manager_stage_weak_calls",
        "manager_stage_weak_rate",
    ]
    manager_criterion_gap_cols = [
        "manager_name",
        "checklist_block_name",
        "checklist_criterion",
        "criterion_calls",
        "criterion_avg_score",
        "criterion_completion_percent",
        "criterion_failed_count",
        "criterion_partial_count",
        "criterion_fail_rate",
        "training_recommendation",
    ]
    crm_checklist_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "crm_checklist_block_name",
        "crm_checklist_criterion",
        "crm_checklist_score",
        "crm_checklist_max_score",
        "crm_checklist_comment",
        "crm_checklist_code",
    ]
    manager_crm_gap_cols = [
        "manager_name",
        "crm_checklist_block_name",
        "crm_checklist_criterion",
        "crm_criterion_deals",
        "crm_criterion_avg_score",
        "crm_criterion_completion_percent",
        "crm_criterion_failed_count",
        "crm_criterion_partial_count",
        "crm_criterion_fail_rate",
        "training_recommendation",
    ]
    quality_control_cols = [
        "control_priority",
        "quality_control_score",
        "deal_url",
        "stage_name",
        "manager_name",
        "avg_overall_score",
        "avg_call_quality_score",
        "crm_checklist_percent",
        "calls_total",
        "calls_failed",
        "stage_movement_risk",
        "control_reason",
        "control_next_action",
        "recommendations",
    ]
    coaching_plan_cols = [
        "manager_name",
        "coaching_priority",
        "training_source",
        "training_topic",
        "coaching_metric",
        "coaching_affected_count",
        "training_recommendation",
    ]
    executive_summary_cols = [
        "summary_section",
        "summary_metric",
        "summary_value",
        "summary_comment",
    ]
    manager_scorecard_cols = [
        "manager_rank",
        "manager_name",
        "avg_overall_score",
        "deals_total",
        "calls_total",
        "calls_ok",
        "deals_without_calls",
        "manager_critical_deals",
        "manager_high_deals",
        "manager_training_topics",
        "manager_top_training_topic",
        "top_growth_zones",
        "top_checklist_gaps",
        "manager_focus",
        "manager_next_action",
    ]
    stage_history_cols = [
        "deal_url",
        "manager_name",
        "stage_history_event_id",
        "stage_history_event_type",
        "stage_history_created_at",
        "stage_id",
        "stage_name",
        "stage_order",
        "stage_duration_minutes",
        "stage_duration_hours",
        "stage_is_current",
    ]
    stage_sr_cols = [
        "stage_order",
        "stage_id",
        "stage_name",
        "stage_deals_total",
        "stage_deals_passed",
        "stage_sr",
    ]
    stage_movement_cols = [
        "deal_url",
        "stage_name",
        "manager_name",
        "stage_history_count",
        "stage_history_path",
        "stage_last_change_at",
        "stage_current_age_minutes",
        "stage_current_age_days",
        "stage_warning_threshold",
        "stage_critical_threshold",
        "stage_current_age_status",
        "deal_total_work_minutes",
        "deal_total_work_days",
        "deal_total_work_warning_threshold",
        "deal_total_work_critical_threshold",
        "deal_total_work_status",
        "stage_return_count",
        "stage_reached_final",
        "stage_movement_risk",
        "stage_movement_recommendation",
    ]
    lost_deal_cols = [
        "lost_deal_url",
        "lost_deal_title",
        "lost_stage_name",
        "lost_manager_name",
        "lost_amount",
        "lost_date_create",
        "lost_close_date",
        "lost_lifetime_days",
        "lost_source",
        "loss_reason_category",
        "loss_reason_confidence",
        "loss_reason_evidence",
        "conversion_tools",
        "conversion_next_action",
        "lost_analysis_basis",
    ]
    lost_reason_summary_cols = [
        "loss_reason_category",
        "lost_deals_count",
        "lost_deals_share",
        "lost_amount",
        "lost_avg_lifetime_days",
        "lost_top_managers",
        "conversion_tools",
        "conversion_next_action",
    ]
    conversion_action_cols = [
        "conversion_priority",
        "conversion_rank",
        "loss_reason_category",
        "lost_deals_count",
        "lost_deals_share",
        "conversion_tools",
        "conversion_next_action",
        "conversion_expected_effect",
    ]
    manager_cols = [
        "manager_name",
        "deals_total",
        "calls_total",
        "calls_ok",
        "deals_without_calls",
        "growth_deal_data",
        "growth_call_structure",
        "growth_alignment",
        "avg_overall_score",
        "top_growth_zones",
        "top_checklist_gaps",
    ]
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        executive_summary_df = pd.DataFrame(executive_summary_rows, columns=executive_summary_cols)
        _ru_df(executive_summary_df).to_excel(writer, sheet_name="Итоги", index=False)
        manager_scorecard_df = pd.DataFrame(manager_scorecard_rows, columns=manager_scorecard_cols)
        _ru_df(manager_scorecard_df).to_excel(writer, sheet_name="Карточки менеджеров", index=False)
        deal_df = pd.DataFrame(deal_report_rows)
        _ru_df(deal_df[[c for c in deal_cols if c in deal_df.columns]]).to_excel(writer, sheet_name="Сделки", index=False)
        if not df.empty:
            call_df = pd.DataFrame(call_detail_rows)
            _ru_df(call_df[[c for c in call_detail_cols if c in call_df.columns]]).to_excel(writer, sheet_name="Звонки внутри сделок", index=False)
            objection_df = pd.DataFrame(objection_rows, columns=objection_cols)
            _ru_df(objection_df).to_excel(writer, sheet_name="Разбор возражений", index=False)
            conversation_map_df = pd.DataFrame(conversation_map_rows, columns=CONVERSATION_MAP_COLUMNS)
            _ru_df(conversation_map_df).to_excel(writer, sheet_name="Карта разговора", index=False)
            ci_objection_df = pd.DataFrame(ci_objection_rows, columns=CI_OBJECTION_COLUMNS)
            _ru_df(ci_objection_df).to_excel(writer, sheet_name="Возражения", index=False)
            emotional_risk_df = pd.DataFrame(emotional_risk_rows, columns=EMOTIONAL_RISK_COLUMNS)
            _ru_df(emotional_risk_df).to_excel(writer, sheet_name="Эмоциональные риски", index=False)
            ci_conversion_factor_df = pd.DataFrame(ci_conversion_factor_rows, columns=CONVERSION_FACTOR_COLUMNS)
            _ru_df(ci_conversion_factor_df).to_excel(writer, sheet_name="Факторы конверсии", index=False)
            ci_manager_recommendation_df = pd.DataFrame(
                ci_manager_recommendation_rows,
                columns=MANAGER_RECOMMENDATION_COLUMNS,
            )
            _ru_df(ci_manager_recommendation_df).to_excel(
                writer,
                sheet_name="Рекомендации менеджерам",
                index=False,
            )
            script_profile_df = pd.DataFrame(script_profile_rows, columns=SCRIPT_PROFILE_COLUMNS)
            _ru_df(script_profile_df).to_excel(writer, sheet_name="Соответствие скриптам", index=False)
            script_score_df = pd.DataFrame(script_score_rows, columns=SCRIPT_SCORE_COLUMNS)
            _ru_df(script_score_df).to_excel(writer, sheet_name="Оценка по скрипту", index=False)
            script_gap_df = pd.DataFrame(script_gap_rows, columns=SCRIPT_GAP_COLUMNS)
            _ru_df(script_gap_df).to_excel(writer, sheet_name="Провалы скрипта", index=False)
            checklist_df = pd.DataFrame(checklist_rows, columns=checklist_cols)
            _ru_df(checklist_df).to_excel(writer, sheet_name="Чек-лист звонков", index=False)
            sales_stage_score_df = pd.DataFrame(sales_stage_score_rows, columns=sales_stage_score_cols)
            _ru_df(sales_stage_score_df).to_excel(writer, sheet_name="Этапы продаж", index=False)
            manager_stage_df = pd.DataFrame(manager_stage_rows, columns=manager_stage_cols)
            _ru_df(manager_stage_df).to_excel(writer, sheet_name="Слабые этапы", index=False)
            manager_criterion_gap_df = pd.DataFrame(manager_criterion_gap_rows, columns=manager_criterion_gap_cols)
            _ru_df(manager_criterion_gap_df).to_excel(writer, sheet_name="Проблемные критерии", index=False)
            crm_checklist_df = pd.DataFrame(crm_checklist_rows, columns=crm_checklist_cols)
            _ru_df(crm_checklist_df).to_excel(writer, sheet_name="Чек-лист CRM", index=False)
            manager_crm_gap_df = pd.DataFrame(manager_crm_gap_rows, columns=manager_crm_gap_cols)
            _ru_df(manager_crm_gap_df).to_excel(writer, sheet_name="Проблемы CRM", index=False)
            quality_control_df = pd.DataFrame(quality_control_rows, columns=quality_control_cols)
            _ru_df(quality_control_df).to_excel(writer, sheet_name="Контроль качества", index=False)
            coaching_plan_df = pd.DataFrame(coaching_plan_rows, columns=coaching_plan_cols)
            _ru_df(coaching_plan_df).to_excel(writer, sheet_name="План обучения", index=False)
            stage_history_df = pd.DataFrame(stage_history_rows, columns=stage_history_cols)
            _ru_df(stage_history_df).to_excel(writer, sheet_name="История стадий", index=False)
            stage_sr_df = pd.DataFrame(stage_sr_rows, columns=stage_sr_cols)
            _ru_df(stage_sr_df).to_excel(writer, sheet_name="SR по стадиям", index=False)
            stage_movement_df = pd.DataFrame(stage_movement_rows, columns=stage_movement_cols)
            _ru_df(stage_movement_df).to_excel(writer, sheet_name="Риски движения", index=False)
        if lost_deal_rows or lost_reason_summary_rows or conversion_action_rows:
            lost_df = pd.DataFrame(lost_deal_rows, columns=lost_deal_cols)
            _ru_df(lost_df).to_excel(writer, sheet_name="Проигранные сделки", index=False)
            lost_summary_df = pd.DataFrame(lost_reason_summary_rows, columns=lost_reason_summary_cols)
            _ru_df(lost_summary_df).to_excel(writer, sheet_name="Причины отказов", index=False)
            conversion_df = pd.DataFrame(conversion_action_rows, columns=conversion_action_cols)
            _ru_df(conversion_df).to_excel(writer, sheet_name="Рост конверсии", index=False)
        manager_df = pd.DataFrame(manager_summary)
        _ru_df(manager_df[[c for c in manager_cols if c in manager_df.columns]]).to_excel(writer, sheet_name="Сводка менеджеров", index=False)
        if manager_summary_cmp is not None:
            manager_cmp_df = pd.DataFrame(manager_summary_cmp)
            _ru_df(manager_cmp_df[[c for c in manager_cols if c in manager_cmp_df.columns]]).to_excel(writer, sheet_name="Сводка менеджеров cmp", index=False)
        _format_excel_writer(writer)
    return out
