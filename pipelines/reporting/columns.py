from __future__ import annotations

# Колонки для вкладки "Сделки"
DEAL_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "calls_total",
    "calls_ok",
    "calls_failed",
    "ignored_call_center_calls",
    "skipped_short_calls",
    "no_calls",
    "transcripts_count",
    "avg_overall_score",
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
    "stage_current_age_days",
    "stage_warning_threshold",
    "stage_critical_threshold",
    "stage_current_age_status",
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
    "recommendations",
    "calls_breakdown",
    "improvement_moments_combined",
]

# Колонки для вкладки "Звонки внутри сделок"
CALL_DETAIL_COLUMNS = [
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
    "transcript_marked",
    "transcript_text",
    "bitrix_card_transcript_status",
    "transcript_match_score",
    "bitrix_card_transcript",
    "timeline_log_result",
    "timeline_log_error",
    "error",
]

# Колонки для вкладки "Разбор возражений"
OBJECTION_COLUMNS = [
    "deal_url",
    "stage_name",
    "manager_name",
    "subject",
    "objection_fragment",
    "objection_status",
    "objection_recommendations",
]

# Колонки для вкладки "Чек-лист звонков"
CHECKLIST_COLUMNS = [
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

# Колонки для вкладки "Этапы продаж"
SALES_STAGE_SCORE_COLUMNS = [
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

# Колонки для сводок по менеджерам
MANAGER_STAGE_COLUMNS = [
    "manager_name",
    "sales_stage_block_name",
    "manager_stage_calls",
    "manager_stage_deals",
    "manager_stage_avg_percent",
    "manager_stage_weak_calls",
    "manager_stage_weak_rate",
]

MANAGER_CRITERION_GAP_COLUMNS = [
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

# Колонки для CRM чек-листа
CRM_CHECKLIST_COLUMNS = [
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

MANAGER_CRM_GAP_COLUMNS = [
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

# Контроль качества и обучение
QUALITY_CONTROL_COLUMNS = [
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

COACHING_PLAN_COLUMNS = [
    "manager_name",
    "coaching_priority",
    "training_source",
    "training_topic",
    "coaching_metric",
    "coaching_affected_count",
    "training_recommendation",
]

# Итоги и карточки
EXECUTIVE_SUMMARY_COLUMNS = [
    "summary_section",
    "summary_metric",
    "summary_value",
    "summary_comment",
]

MANAGER_SCORECARD_COLUMNS = [
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
]

# История и движение стадий
STAGE_HISTORY_COLUMNS = [
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

STAGE_SR_COLUMNS = [
    "stage_order",
    "stage_id",
    "stage_name",
    "stage_deals_total",
    "stage_deals_passed",
    "stage_sr",
]

STAGE_MOVEMENT_COLUMNS = [
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

# Проигранные сделки и конверсия
LOST_DEAL_COLUMNS = [
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

LOST_REASON_SUMMARY_COLUMNS = [
    "loss_reason_category",
    "lost_deals_count",
    "lost_deals_share",
    "lost_amount",
    "lost_avg_lifetime_days",
    "lost_top_managers",
    "conversion_tools",
    "conversion_next_action",
]

CONVERSION_ACTION_COLUMNS = [
    "conversion_priority",
    "conversion_rank",
    "loss_reason_category",
    "lost_deals_count",
    "lost_deals_share",
    "conversion_tools",
    "conversion_next_action",
    "conversion_expected_effect",
]

# Сводка менеджеров
MANAGER_SUMMARY_COLUMNS = [
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
