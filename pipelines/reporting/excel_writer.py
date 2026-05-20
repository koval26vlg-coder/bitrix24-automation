from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.conversation_intelligence import (
    CI_OBJECTION_COLUMNS,
    CONVERSATION_MAP_COLUMNS,
    CONVERSION_FACTOR_COLUMNS,
    EMOTIONAL_RISK_COLUMNS,
    MANAGER_RECOMMENDATION_COLUMNS,
)
from pipelines.reporting.columns import (
    CALL_DETAIL_COLUMNS,
    CHECKLIST_COLUMNS,
    COACHING_PLAN_COLUMNS,
    CONVERSION_ACTION_COLUMNS,
    CRM_CHECKLIST_COLUMNS,
    DEAL_COLUMNS,
    EXECUTIVE_SUMMARY_COLUMNS,
    LOST_DEAL_COLUMNS,
    LOST_REASON_SUMMARY_COLUMNS,
    MANAGER_CRITERION_GAP_COLUMNS,
    MANAGER_CRM_GAP_COLUMNS,
    MANAGER_SCORECARD_COLUMNS,
    MANAGER_STAGE_COLUMNS,
    MANAGER_SUMMARY_COLUMNS,
    OBJECTION_COLUMNS,
    QUALITY_CONTROL_COLUMNS,
    SALES_STAGE_SCORE_COLUMNS,
    STAGE_HISTORY_COLUMNS,
    STAGE_MOVEMENT_COLUMNS,
    STAGE_SR_COLUMNS,
)
from pipelines.reporting.excel import _format_excel_writer, _ru_df
from pipelines.script_scoring import (
    SCRIPT_GAP_COLUMNS,
    SCRIPT_PROFILE_COLUMNS,
    SCRIPT_SCORE_COLUMNS,
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
            if not rows and sheet_name not in ["Итоги", "Карточки менеджеров", "Сделки", "Сводка менеджеров"]:
                return
            df = pd.DataFrame(rows)
            # Фильтруем колонки, которые реально есть в данных
            valid_cols = [c for c in columns if c in df.columns]
            _ru_df(df[valid_cols]).to_excel(writer, sheet_name=sheet_name, index=False)

        _write_sheet(executive_summary_rows, EXECUTIVE_SUMMARY_COLUMNS, "Итоги")
        _write_sheet(manager_scorecard_rows, MANAGER_SCORECARD_COLUMNS, "Карточки менеджеров")
        _write_sheet(deal_report_rows, DEAL_COLUMNS, "Сделки")
        _write_sheet(call_detail_rows, CALL_DETAIL_COLUMNS, "Звонки внутри сделок")
        _write_sheet(objection_rows, OBJECTION_COLUMNS, "Разбор возражений")
        _write_sheet(conversation_map_rows, CONVERSATION_MAP_COLUMNS, "Карта разговора")
        _write_sheet(ci_objection_rows, CI_OBJECTION_COLUMNS, "Возражения")
        _write_sheet(emotional_risk_rows, EMOTIONAL_RISK_COLUMNS, "Эмоциональные риски")
        _write_sheet(ci_conversion_factor_rows, CONVERSION_FACTOR_COLUMNS, "Факторы конверсии")
        _write_sheet(ci_manager_recommendation_rows, MANAGER_RECOMMENDATION_COLUMNS, "Рекомендации менеджерам")
        _write_sheet(script_profile_rows, SCRIPT_PROFILE_COLUMNS, "Соответствие скриптам")
        _write_sheet(script_score_rows, SCRIPT_SCORE_COLUMNS, "Оценка по скрипту")
        _write_sheet(script_gap_rows, SCRIPT_GAP_COLUMNS, "Провалы скрипта")
        _write_sheet(checklist_rows, CHECKLIST_COLUMNS, "Чек-лист звонков")
        _write_sheet(sales_stage_score_rows, SALES_STAGE_SCORE_COLUMNS, "Этапы продаж")
        _write_sheet(manager_stage_rows, MANAGER_STAGE_COLUMNS, "Слабые этапы")
        _write_sheet(manager_criterion_gap_rows, MANAGER_CRITERION_GAP_COLUMNS, "Проблемные критерии")
        _write_sheet(crm_checklist_rows, CRM_CHECKLIST_COLUMNS, "Чек-лист CRM")
        _write_sheet(manager_crm_gap_rows, MANAGER_CRM_GAP_COLUMNS, "Проблемы CRM")
        _write_sheet(quality_control_rows, QUALITY_CONTROL_COLUMNS, "Контроль качества")
        _write_sheet(coaching_plan_rows, COACHING_PLAN_COLUMNS, "План обучения")
        _write_sheet(stage_history_rows, STAGE_HISTORY_COLUMNS, "История стадий")
        _write_sheet(stage_sr_rows, STAGE_SR_COLUMNS, "SR по стадиям")
        _write_sheet(stage_movement_rows, STAGE_MOVEMENT_COLUMNS, "Риски движения")

        if lost_deal_rows or lost_reason_summary_rows or conversion_action_rows:
            _write_sheet(lost_deal_rows, LOST_DEAL_COLUMNS, "Проигранные сделки")
            _write_sheet(lost_reason_summary_rows, LOST_REASON_SUMMARY_COLUMNS, "Причины отказов")
            _write_sheet(conversion_action_rows, CONVERSION_ACTION_COLUMNS, "Рост конверсии")

        _write_sheet(manager_summary, MANAGER_SUMMARY_COLUMNS, "Сводка менеджеров")
        if manager_summary_cmp is not None:
            _write_sheet(manager_summary_cmp, MANAGER_SUMMARY_COLUMNS, "Сводка менеджеров cmp")

        _format_excel_writer(writer)
