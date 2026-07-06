from __future__ import annotations

from typing import Any

from pipelines.conversation_intelligence import (
    CI_OBJECTION_COLUMNS,
    CONVERSATION_MAP_COLUMNS,
    CONVERSION_FACTOR_COLUMNS,
    EMOTIONAL_RISK_COLUMNS,
    MANAGER_RECOMMENDATION_COLUMNS,
)
from pipelines.reporting.columns import (
    CALL_DETAIL_COLUMNS,
    COACHING_PLAN_COLUMNS,
    CONVERSION_ACTION_COLUMNS,
    DEAL_COLUMNS,
    EXECUTIVE_SUMMARY_COLUMNS,
    LOST_DEAL_COLUMNS,
    LOST_REASON_SUMMARY_COLUMNS,
    MANAGER_CRITERION_GAP_COLUMNS,
    MANAGER_CRM_GAP_COLUMNS,
    MANAGER_SCORECARD_COLUMNS,
    MANAGER_STAGE_COLUMNS,
    SALES_STAGE_SCORE_COLUMNS,
    STAGE_SR_COLUMNS,
)
from pipelines.script_scoring import (
    SCRIPT_GAP_COLUMNS,
    SCRIPT_PROFILE_COLUMNS,
    SCRIPT_SCORE_COLUMNS,
)


def _ordered_union(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for column in group:
            if column not in seen:
                out.append(column)
                seen.add(column)
    return out


DASHBOARD_COLUMNS = EXECUTIVE_SUMMARY_COLUMNS
FUNNEL_COLUMNS = STAGE_SR_COLUMNS

CONVERSION_OVERVIEW_COLUMNS = _ordered_union(
    ["conversion_report_section"],
    CONVERSION_FACTOR_COLUMNS,
    LOST_REASON_SUMMARY_COLUMNS,
    CONVERSION_ACTION_COLUMNS,
)

MANAGER_CARD_COLUMNS = _ordered_union(
    MANAGER_SCORECARD_COLUMNS,
    MANAGER_RECOMMENDATION_COLUMNS,
)

MANAGER_ERROR_COLUMNS = _ordered_union(
    ["manager_issue_type", "manager_issue_detail", "deal_url"],
    MANAGER_STAGE_COLUMNS,
    SCRIPT_GAP_COLUMNS,
    MANAGER_CRITERION_GAP_COLUMNS,
    MANAGER_CRM_GAP_COLUMNS,
    COACHING_PLAN_COLUMNS,
)

DEAL_REGISTRY_COLUMNS = _ordered_union(DEAL_COLUMNS, LOST_DEAL_COLUMNS)
CALL_BASE_COLUMNS = CALL_DETAIL_COLUMNS

CALL_EVENT_COLUMNS = _ordered_union(
    ["event_type", "event_detail"],
    CI_OBJECTION_COLUMNS,
    CONVERSATION_MAP_COLUMNS,
    EMOTIONAL_RISK_COLUMNS,
)

SCRIPT_PROFILE_OPTIMIZED_COLUMNS = SCRIPT_PROFILE_COLUMNS
SCRIPT_SCORE_OPTIMIZED_COLUMNS = SCRIPT_SCORE_COLUMNS
SALES_STAGE_OPTIMIZED_COLUMNS = SALES_STAGE_SCORE_COLUMNS


def build_conversion_overview_rows(
    conversion_factor_rows: list[dict[str, Any]],
    lost_reason_summary_rows: list[dict[str, Any]],
    conversion_action_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in conversion_factor_rows:
        rows.append({"conversion_report_section": "Фактор конверсии", **row})
    for row in lost_reason_summary_rows:
        rows.append({"conversion_report_section": "Причина отказа", **row})
    for row in conversion_action_rows:
        rows.append({"conversion_report_section": "План роста конверсии", **row})
    return rows


def build_manager_card_rows(
    manager_scorecard_rows: list[dict[str, Any]],
    manager_recommendation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendation_by_manager = {
        str(row.get("manager_name") or ""): row for row in manager_recommendation_rows
    }
    scorecard_managers = {str(row.get("manager_name") or "") for row in manager_scorecard_rows}

    rows: list[dict[str, Any]] = []
    for row in manager_scorecard_rows:
        manager_name = str(row.get("manager_name") or "")
        merged = dict(row)
        merged.update(recommendation_by_manager.get(manager_name, {}))
        rows.append(merged)

    for manager_name, row in recommendation_by_manager.items():
        if manager_name not in scorecard_managers:
            rows.append(dict(row))
    return rows


def build_manager_error_rows(
    manager_stage_rows: list[dict[str, Any]],
    script_gap_rows: list[dict[str, Any]],
    manager_criterion_gap_rows: list[dict[str, Any]],
    manager_crm_gap_rows: list[dict[str, Any]],
    coaching_plan_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in manager_stage_rows:
        rows.append(
            {
                "manager_issue_type": "Слабый этап продаж",
                "manager_issue_detail": row.get("sales_stage_block_name"),
                **row,
            }
        )
    for row in script_gap_rows:
        rows.append(
            {
                "manager_issue_type": "Провал шага скрипта",
                "manager_issue_detail": row.get("script_step"),
                **row,
            }
        )
    for row in manager_criterion_gap_rows:
        rows.append(
            {
                "manager_issue_type": "Проблемный критерий звонка",
                "manager_issue_detail": row.get("checklist_criterion"),
                **row,
            }
        )
    for row in manager_crm_gap_rows:
        rows.append(
            {
                "manager_issue_type": "Проблема ведения CRM",
                "manager_issue_detail": row.get("crm_checklist_criterion"),
                **row,
            }
        )
    for row in coaching_plan_rows:
        rows.append(
            {
                "manager_issue_type": "Рекомендация / обучение",
                "manager_issue_detail": row.get("training_topic"),
                **row,
            }
        )
    return rows


def build_deal_registry_rows(
    deal_report_rows: list[dict[str, Any]],
    lost_deal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lost_by_url = {str(row.get("lost_deal_url") or ""): row for row in lost_deal_rows}
    existing_urls = {str(row.get("deal_url") or "") for row in deal_report_rows}

    rows: list[dict[str, Any]] = []
    for row in deal_report_rows:
        deal_url = str(row.get("deal_url") or "")
        merged = dict(row)
        merged.update(lost_by_url.get(deal_url, {}))
        rows.append(merged)

    for lost_url, row in lost_by_url.items():
        if lost_url not in existing_urls:
            rows.append({"deal_url": lost_url, **row})
    return rows


def build_call_event_rows(
    objection_rows: list[dict[str, Any]],
    conversation_map_rows: list[dict[str, Any]],
    emotional_risk_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in objection_rows:
        event_detail = " | ".join(
            part
            for part in (
                str(row.get("objection_type") or "").strip(),
                str(row.get("objection_fragment") or "").strip(),
            )
            if part
        )
        rows.append(
            {
                "event_type": "Возражение",
                "event_detail": event_detail,
                **row,
            }
        )

    for row in conversation_map_rows:
        rows.append(
            {
                "event_type": row.get("ci_moment_type") or "Момент разговора",
                "event_detail": row.get("ci_moment_fragment"),
                **row,
            }
        )

    for row in emotional_risk_rows:
        rows.append(
            {
                "event_type": "Эмоциональный риск",
                "event_detail": row.get("ci_risk_evidence") or row.get("ci_emotion_state"),
                **row,
            }
        )
    return rows
