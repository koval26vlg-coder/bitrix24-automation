from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.reporting.columns import BITRIXGPT_DEAL_SUMMARY_COLUMNS
from pipelines.reporting.excel import _format_excel_writer, _ru_df
from pipelines.reporting.optimized import (
    CALL_BASE_COLUMNS,
    CALL_EVENT_COLUMNS,
    CONVERSION_OVERVIEW_COLUMNS,
    DASHBOARD_COLUMNS,
    DEAL_REGISTRY_COLUMNS,
    FUNNEL_COLUMNS,
    MANAGER_CARD_COLUMNS,
    MANAGER_ERROR_COLUMNS,
    SALES_STAGE_OPTIMIZED_COLUMNS,
    SCRIPT_PROFILE_OPTIMIZED_COLUMNS,
    SCRIPT_SCORE_OPTIMIZED_COLUMNS,
    build_call_event_rows,
    build_conversion_overview_rows,
    build_deal_registry_rows,
    build_manager_card_rows,
    build_manager_error_rows,
)


def write_excel_report(
    output_path: Path,
    *,
    executive_summary_rows: list[dict[str, Any]],
    manager_scorecard_rows: list[dict[str, Any]],
    deal_report_rows: list[dict[str, Any]],
    call_detail_rows: list[dict[str, Any]],
    objection_rows: list[dict[str, Any]],
    conversation_map_rows: list[dict[str, Any]],
    ci_objection_rows: list[dict[str, Any]],
    emotional_risk_rows: list[dict[str, Any]],
    ci_conversion_factor_rows: list[dict[str, Any]],
    ci_manager_recommendation_rows: list[dict[str, Any]],
    script_profile_rows: list[dict[str, Any]],
    script_score_rows: list[dict[str, Any]],
    script_gap_rows: list[dict[str, Any]],
    checklist_rows: list[dict[str, Any]],
    sales_stage_score_rows: list[dict[str, Any]],
    manager_stage_rows: list[dict[str, Any]],
    manager_criterion_gap_rows: list[dict[str, Any]],
    crm_checklist_rows: list[dict[str, Any]],
    manager_crm_gap_rows: list[dict[str, Any]],
    quality_control_rows: list[dict[str, Any]],
    coaching_plan_rows: list[dict[str, Any]],
    stage_history_rows: list[dict[str, Any]],
    stage_sr_rows: list[dict[str, Any]],
    stage_movement_rows: list[dict[str, Any]],
    lost_deal_rows: list[dict[str, Any]],
    lost_reason_summary_rows: list[dict[str, Any]],
    conversion_action_rows: list[dict[str, Any]],
    manager_summary: list[dict[str, Any]],
    manager_summary_cmp: list[dict[str, Any]] | None = None,
) -> None:
    """Записывает все данные в Excel файл с разделением по вкладкам."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        def _write_sheet(rows: list[dict[str, Any]], columns: list[str], sheet_name: str) -> None:
            required_empty_sheets = {
                "Дашборд",
                "Воронка",
                "Менеджеры",
                "Сделки",
                "Звонки",
            }
            if not rows and sheet_name not in required_empty_sheets:
                return
            df = pd.DataFrame(rows)
            # Фильтруем колонки, которые реально есть в данных
            valid_cols = [c for c in columns if c in df.columns]
            _ru_df(df[valid_cols]).to_excel(writer, sheet_name=sheet_name, index=False)

        _write_sheet(executive_summary_rows, DASHBOARD_COLUMNS, "Дашборд")
        _write_sheet(stage_sr_rows, FUNNEL_COLUMNS, "Воронка")
        _write_sheet(
            build_conversion_overview_rows(
                ci_conversion_factor_rows,
                lost_reason_summary_rows,
                conversion_action_rows,
            ),
            CONVERSION_OVERVIEW_COLUMNS,
            "Факторы_и_отказы",
        )
        _write_sheet(
            build_manager_card_rows(manager_scorecard_rows, ci_manager_recommendation_rows),
            MANAGER_CARD_COLUMNS,
            "Менеджеры",
        )
        _write_sheet(
            build_manager_error_rows(
                manager_stage_rows,
                script_gap_rows,
                manager_criterion_gap_rows,
                manager_crm_gap_rows,
                coaching_plan_rows,
            ),
            MANAGER_ERROR_COLUMNS,
            "Ошибки_менеджеров",
        )
        _write_sheet(
            build_deal_registry_rows(deal_report_rows, lost_deal_rows),
            DEAL_REGISTRY_COLUMNS,
            "Сделки",
        )
        _write_sheet(
            deal_report_rows,
            BITRIXGPT_DEAL_SUMMARY_COLUMNS,
            "Сводка_BitrixGPT",
        )
        _write_sheet(call_detail_rows, CALL_BASE_COLUMNS, "Звонки")
        _write_sheet(
            build_call_event_rows(
                ci_objection_rows,
                conversation_map_rows,
                emotional_risk_rows,
            ),
            CALL_EVENT_COLUMNS,
            "События_звонков",
        )
        _write_sheet(
            script_profile_rows,
            SCRIPT_PROFILE_OPTIMIZED_COLUMNS,
            "Скрипты_итоги",
        )
        _write_sheet(script_score_rows, SCRIPT_SCORE_OPTIMIZED_COLUMNS, "Скрипты_шаги")
        _write_sheet(sales_stage_score_rows, SALES_STAGE_OPTIMIZED_COLUMNS, "Этапы_продаж")

        _format_excel_writer(writer)
