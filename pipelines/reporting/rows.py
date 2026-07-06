from __future__ import annotations

from typing import Any

from pipelines.scoring import _clean_text_for_report, evaluate_crm_checklist, quality_label
from pipelines.stages import safe_int, stage_display_name, stage_order_map


def build_deal_conclusions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("deal_id") or "unknown"), []).append(row)

    out: list[dict[str, Any]] = []
    for deal_rows in grouped.values():
        ok_rows = [r for r in deal_rows if not r.get("error")]
        scored = ok_rows or deal_rows
        calls_total = len(deal_rows)
        calls_ok = len(ok_rows)
        avg_overall = round(
            sum(float(r.get("overall_score") or 0.0) for r in scored) / max(1, len(scored)), 2
        )
        avg_call = round(
            sum(float(r.get("call_quality_score") or 0.0) for r in scored) / max(1, len(scored)), 2
        )
        deal_quality = (
            max(float(r.get("deal_quality_score") or 0.0) for r in scored) if scored else 0.0
        )
        needs_ratio = sum(1 for r in scored if r.get("has_needs_discovery")) / max(1, len(scored))
        next_step_ratio = sum(1 for r in scored if r.get("has_next_step_phrase")) / max(
            1, len(scored)
        )
        objection_ratio = sum(1 for r in scored if r.get("has_objection_work")) / max(
            1, len(scored)
        )
        synced_ratio = sum(1 for r in scored if r.get("next_step_synced")) / max(1, len(scored))
        avg_crm_work = round(
            sum(float(r.get("crm_work_score") or 0.0) for r in scored) / max(1, len(scored)), 2
        )

        client_work_score = round(
            avg_crm_work if avg_crm_work else (0.60 * deal_quality + 0.40 * synced_ratio * 100),
            2,
        )

        issues: list[str] = []
        if deal_quality < 100:
            issues.append("не выполнены критерии CRM-комментария и следующего дела")
        if needs_ratio < 0.5:
            issues.append("слабо выявлены потребности")
        if next_step_ratio < 0.5:
            issues.append("не фиксируется следующий шаг")
        if synced_ratio < 0.5:
            issues.append("следующий шаг плохо синхронизирован с CRM")
        if objection_ratio == 0 and calls_total > 0:
            issues.append("работа с возражениями не прослеживается")

        first = deal_rows[0]
        if client_work_score >= 80:
            client_conclusion = "Клиент проработан качественно: CRM и разговоры дают понятную картину дальнейших действий."  # noqa: E501
        elif client_work_score >= 60:
            client_conclusion = "Проработка клиента нормальная, но есть зоны для усиления."
        elif client_work_score >= 40:
            client_conclusion = "Проработка клиента слабая: часть важных элементов не закреплена в разговоре или CRM."  # noqa: E501
        else:
            client_conclusion = "Проработка клиента критически слабая: не хватает структуры, фиксации потребностей и следующего шага."  # noqa: E501

        if avg_call >= 80:
            conversation_conclusion = "Качество разговоров сильное."
        elif avg_call >= 60:
            conversation_conclusion = "Качество разговоров нормальное, но нестабильное."
        elif avg_call >= 40:
            conversation_conclusion = (
                "Качество разговоров слабое: менеджеру нужна более четкая структура диалога."
            )
        else:
            conversation_conclusion = "Качество разговоров критически слабое."

        recommendations = (
            "Усилить: " + ", ".join(issues) + "."
            if issues
            else "Сохранять текущий подход и фиксировать следующий шаг после каждого контакта."
        )
        transcript_paths = [
            str(r.get("transcript_path")) for r in deal_rows if r.get("transcript_path")
        ]

        out.append(
            {
                "deal_url": first.get("deal_url"),
                "stage_name": first.get("stage_name") or stage_display_name(first.get("stage_id")),
                "manager_name": first.get("manager_name"),
                "calls_total": calls_total,
                "calls_ok": calls_ok,
                "transcripts_count": len(transcript_paths),
                "avg_overall_score": avg_overall,
                "avg_call_quality_score": avg_call,
                "client_work_score": client_work_score,
                "client_work_quality": quality_label(client_work_score),
                "conversation_quality": quality_label(avg_call),
                "client_work_conclusion": client_conclusion,
                "call_quality_conclusion": conversation_conclusion,
                "recommendations": recommendations,
                "transcript_paths": "\n".join(transcript_paths),
            }
        )

    return sorted(out, key=lambda x: float(x.get("client_work_score") or 0.0))


def _deal_group_key(row: dict[str, Any]) -> str:
    return str(row.get("deal_id") or row.get("deal_url") or "unknown")


def _join_unique(values: list[Any], sep: str = "\n") -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return sep.join(out)


def _call_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("start_time") or ""), str(row.get("activity_id") or ""))


def _call_heading(row: dict[str, Any], number: int) -> str:
    subject = str(row.get("subject") or "Звонок").strip()
    duration = row.get("duration_minutes")
    duration_text = f"{duration:g} мин." if isinstance(duration, (int, float)) else ""
    if duration_text:
        return f"Звонок {number}: {subject} ({duration_text})"
    return f"Звонок {number}: {subject}"


def _short_error(text: Any, limit: int = 550) -> str:
    raw = _clean_text_for_report(str(text or ""))
    if not raw:
        return ""
    if "не дождался входа в Bitrix" in raw or "oauth/authorize" in raw:
        return "Не удалось открыть Bitrix через выбранный профиль браузера: требуется вход в Bitrix или выбран не тот профиль Edge/Chrome."  # noqa: E501
    if "UI download timeout" in raw:
        return (
            "Не удалось скачать запись через интерфейс Bitrix: файл не появился в папке загрузок."
        )
    if "download failed" in raw:
        return "Не удалось скачать запись звонка через REST/UI."
    return raw[:limit] + ("..." if len(raw) > limit else "")


def _build_bitrix_deal_summary(
    *,
    chat_summary: str,
    call_summary: str,
    stage_name: str,
    next_step_summary: str,
) -> tuple[str, str]:
    parts: list[str] = []
    if chat_summary:
        parts.append(f"Чат: {chat_summary}")
    if call_summary:
        parts.append(f"Звонок: {call_summary}")
    combined_summary = " ".join(parts).strip()

    stage_parts: list[str] = []
    if stage_name:
        stage_parts.append(f"Текущая стадия: {stage_name}.")
    if next_step_summary:
        stage_parts.append(f"Следующий шаг в CRM: {next_step_summary}.")
    stage_progress_summary = " ".join(stage_parts).strip()
    return combined_summary, stage_progress_summary


def build_deal_report_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for _, deal_rows in grouped.items():
        deal_rows = sorted(deal_rows, key=_call_sort_key)
        first = deal_rows[0]
        no_call_rows = [r for r in deal_rows if r.get("no_calls")]
        call_rows = [r for r in deal_rows if not r.get("no_calls")]
        ok_calls = [r for r in call_rows if not r.get("error") and not r.get("asr_skipped")]
        failed_calls = [r for r in call_rows if r.get("error")]
        asr_skipped_calls = len([r for r in call_rows if r.get("asr_skipped")])
        scored = ok_calls

        calls_total = len(call_rows)
        calls_ok = len(ok_calls)
        calls_failed = len(failed_calls)
        skipped_short_calls = (
            max(int(r.get("skipped_short_calls") or 0) for r in deal_rows) if deal_rows else 0
        )
        deal_quality = (
            max(float(r.get("deal_quality_score") or 0.0) for r in deal_rows) if deal_rows else 0.0
        )
        if scored:
            avg_overall = round(
                sum(float(r.get("overall_score") or 0.0) for r in scored) / len(scored), 2
            )
            avg_call = round(
                sum(float(r.get("call_quality_score") or 0.0) for r in scored) / len(scored), 2
            )
            avg_checklist = round(
                sum(
                    float(r.get("call_checklist_percent") or r.get("call_quality_score") or 0.0)
                    for r in scored
                )
                / len(scored),
                2,
            )
            avg_alignment = round(
                sum(float(r.get("alignment_score") or 0.0) for r in scored) / len(scored), 2
            )
            avg_crm_work = round(
                sum(float(r.get("crm_work_score") or 0.0) for r in scored) / len(scored), 2
            )
            avg_crm_checklist = round(
                sum(
                    float(r.get("crm_checklist_percent") or r.get("crm_work_score") or 0.0)
                    for r in scored
                )
                / len(scored),
                2,
            )
            needs_ratio = sum(1 for r in scored if r.get("has_needs_discovery")) / len(scored)
            next_step_ratio = sum(1 for r in scored if r.get("has_next_step_phrase")) / len(scored)
            objection_ratio = sum(1 for r in scored if r.get("has_objection_work")) / len(scored)
            synced_ratio = sum(1 for r in scored if r.get("next_step_synced")) / len(scored)
        else:
            avg_overall = 0.0
            avg_call = 0.0
            avg_checklist = 0.0
            avg_alignment = 0.0
            avg_crm_work = 0.0
            avg_crm_checklist = 0.0
            needs_ratio = 0.0
            next_step_ratio = 0.0
            objection_ratio = 0.0
            synced_ratio = 0.0

        client_work_score = (
            round(
                avg_crm_work if avg_crm_work else (0.60 * deal_quality + 0.40 * synced_ratio * 100),
                2,
            )
            if scored
            else 0.0
        )

        issues: list[str] = []
        if no_call_rows or calls_total == 0:
            if skipped_short_calls > 0:
                issues.append(f"только короткие звонки: {skipped_short_calls}")
            else:
                issues.append("по сделке не найдено звонков")
        if calls_failed:
            issues.append(f"не обработано звонков: {calls_failed}")
        if asr_skipped_calls:
            issues.append(f"без новой расшифровки Bit.Newton: {asr_skipped_calls}")
        if deal_quality < 100:
            issues.append("не выполнены критерии CRM-комментария и следующего дела")
        if scored and needs_ratio < 0.5:
            issues.append("слабо выявлены потребности")
        if scored and next_step_ratio < 0.5:
            issues.append("не фиксируется следующий шаг")
        if scored and synced_ratio < 0.5:
            issues.append("следующий шаг плохо синхронизирован с CRM")
        if scored and objection_ratio == 0:
            issues.append("работа с возражениями не прослеживается")

        if not scored:
            client_conclusion = "По сделке нет обработанных звонков: оценка клиента невозможна до появления записи или успешной расшифровки."  # noqa: E501
            conversation_conclusion = "Нет обработанных разговоров для оценки."
        elif client_work_score >= 80:
            client_conclusion = "Клиент проработан качественно: CRM и разговоры дают понятную картину дальнейших действий."  # noqa: E501
            conversation_conclusion = (
                "Качество разговоров сильное."
                if avg_call >= 80
                else "Разговоры в целом рабочие, но есть отдельные зоны для усиления."
            )
        elif client_work_score >= 60:
            client_conclusion = "Проработка клиента нормальная, но есть зоны для усиления."
            conversation_conclusion = (
                "Качество разговоров нормальное, но нестабильное."
                if avg_call >= 60
                else "Качество разговоров слабое: менеджеру нужна более четкая структура диалога."
            )
        elif client_work_score >= 40:
            client_conclusion = "Проработка клиента слабая: часть важных элементов не закреплена в разговоре или CRM."  # noqa: E501
            conversation_conclusion = (
                "Качество разговоров слабое: менеджеру нужна более четкая структура диалога."
            )
        else:
            client_conclusion = "Проработка клиента критически слабая: не хватает структуры, фиксации потребностей и следующего шага."  # noqa: E501
            conversation_conclusion = "Качество разговоров критически слабое."

        call_blocks: list[str] = []
        transcript_blocks: list[str] = []
        for index, row in enumerate(call_rows, start=1):
            heading = _call_heading(row, index)
            if row.get("error"):
                call_blocks.append(f"{heading}\nСтатус: ошибка обработки — {row.get('error')}")
                continue
            call_blocks.append(
                "\n".join(
                    [
                        heading,
                        f"Качество разговора: {row.get('call_quality_score') or 0}",
                        f"Потребности: {'да' if row.get('has_needs_discovery') else 'нет'}; "
                        f"возражения: {'да' if row.get('has_objection_work') else 'нет'}; "
                        f"следующий шаг: {'да' if row.get('has_next_step_phrase') else 'нет'}",
                        str(row.get("improvement_moments") or "").strip(),
                    ]
                ).strip()
            )
            transcript = str(
                row.get("transcript_marked") or row.get("transcript_text") or ""
            ).strip()
            if transcript:
                transcript_blocks.append(f"{heading}\n{transcript}")

        if no_call_rows and not call_blocks:
            message = first.get("error") or "Звонков по сделке не найдено."
            call_blocks.append(str(message))

        bitrix_chat_summary = _join_unique(
            [r.get("bitrix_chat_summary") for r in deal_rows if r.get("bitrix_chat_summary")],
            sep=" | ",
        )
        bitrix_call_summary = _join_unique(
            [r.get("bitrix_call_summary") for r in deal_rows if r.get("bitrix_call_summary")],
            sep=" | ",
        )
        bitrix_overall_meaning = _join_unique(
            [r.get("bitrix_overall_meaning") for r in deal_rows if r.get("bitrix_overall_meaning")],
            sep=" | ",
        )
        combined_bitrix_summary, stage_progress_summary = _build_bitrix_deal_summary(
            chat_summary=bitrix_chat_summary,
            call_summary=bitrix_call_summary,
            stage_name=str(first.get("stage_name") or stage_display_name(first.get("stage_id")) or ""),
            next_step_summary=str(first.get("next_step_activity_summary") or "").strip(),
        )
        if not combined_bitrix_summary and bitrix_overall_meaning:
            combined_bitrix_summary = bitrix_overall_meaning

        out.append(
            {
                "deal_url": first.get("deal_url"),
                "stage_name": first.get("stage_name") or stage_display_name(first.get("stage_id")),
                "manager_name": first.get("manager_name"),
                "kpi_profile_ru": first.get("kpi_profile_ru"),
                "kpi_explanation": first.get("kpi_explanation"),
                "calls_total": calls_total,
                "calls_ok": calls_ok,
                "calls_failed": calls_failed,
                "asr_skipped_calls": asr_skipped_calls,
                "ignored_call_center_calls": int(first.get("ignored_call_center_calls") or 0),
                "skipped_short_calls": skipped_short_calls,
                "no_calls": bool(no_call_rows or calls_total == 0),
                "transcripts_count": len([r for r in ok_calls if r.get("transcript_path")]),
                "avg_overall_score": avg_overall,
                "overall_score_details": _join_unique(
                    [r.get("overall_score_details") for r in ok_calls]
                )
                or first.get("overall_score_details"),
                "avg_call_quality_score": avg_call,
                "call_quality_details": _join_unique(
                    [r.get("call_quality_details") for r in ok_calls]
                ),
                "call_checklist_percent": avg_checklist,
                "call_checklist_block_details": _join_unique(
                    [r.get("call_checklist_block_details") for r in ok_calls]
                ),
                "deal_quality_score": deal_quality,
                "deal_quality_details": first.get("deal_quality_details"),
                "alignment_score": avg_alignment,
                "crm_work_score": client_work_score,
                "crm_checklist_percent": avg_crm_checklist,
                "crm_checklist_details": _join_unique(
                    [r.get("crm_checklist_details") for r in ok_calls]
                ),
                "alignment_details": _join_unique([r.get("alignment_details") for r in ok_calls]),
                "stage_history_count": first.get("stage_history_count"),
                "stage_history_path": first.get("stage_history_path"),
                "stage_last_change_at": first.get("stage_last_change_at"),
                "stage_current_age_minutes": first.get("stage_current_age_minutes"),
                "stage_current_age_days": first.get("stage_current_age_days"),
                "stage_warning_threshold": first.get("stage_warning_threshold"),
                "stage_critical_threshold": first.get("stage_critical_threshold"),
                "stage_current_age_status": first.get("stage_current_age_status"),
                "deal_total_work_minutes": first.get("deal_total_work_minutes"),
                "deal_total_work_days": first.get("deal_total_work_days"),
                "deal_total_work_warning_threshold": first.get("deal_total_work_warning_threshold"),
                "deal_total_work_critical_threshold": first.get(
                    "deal_total_work_critical_threshold"
                ),
                "deal_total_work_status": first.get("deal_total_work_status"),
                "stage_return_count": first.get("stage_return_count"),
                "stage_reached_final": first.get("stage_reached_final"),
                "stage_movement_risk": first.get("stage_movement_risk"),
                "stage_movement_recommendation": first.get("stage_movement_recommendation"),
                "client_work_score": client_work_score,
                "client_work_quality": quality_label(client_work_score) if scored else "Нет данных",
                "conversation_quality": quality_label(avg_call) if scored else "Нет данных",
                "client_work_conclusion": client_conclusion,
                "call_quality_conclusion": conversation_conclusion,
                "recommendations": (
                    "Усилить: " + ", ".join(issues) + "."
                    if issues
                    else "Сохранять текущий подход и фиксировать следующий шаг после каждого контакта."  # noqa: E501
                ),
                "bitrix_chat_summary": bitrix_chat_summary,
                "bitrix_call_summary": bitrix_call_summary,
                "bitrix_combined_summary": combined_bitrix_summary,
                "bitrix_overall_meaning": bitrix_overall_meaning,
                "deal_stage_progress_summary": stage_progress_summary,
                "bitrix_summary_sources": _join_unique(
                    [r.get("bitrix_summary_sources") for r in deal_rows if r.get("bitrix_summary_sources")],
                    sep=", ",
                ),
                "calls_breakdown": "\n\n".join(call_blocks),
                "transcripts_combined": "\n\n---\n\n".join(transcript_blocks),
                "conversation_meaning": (
                    _join_unique([r.get("conversation_meaning") for r in ok_calls], sep="\n\n")
                    or bitrix_overall_meaning
                ),
                "improvement_moments_combined": _join_unique(
                    [r.get("improvement_moments") for r in ok_calls]
                ),
                "objections_combined": _join_unique([r.get("objections_found") for r in ok_calls]),
                "unhandled_objections": _join_unique(
                    [r.get("unhandled_objections") for r in ok_calls]
                ),
                "objection_recommendations": _join_unique(
                    [r.get("objection_recommendations") for r in ok_calls]
                ),
                "transcript_paths": _join_unique([r.get("transcript_path") for r in ok_calls]),
                "error": _short_error(
                    _join_unique([r.get("error") for r in deal_rows if r.get("error")])
                ),
            }
        )

    return sorted(
        out, key=lambda x: (str(x.get("manager_name") or ""), str(x.get("deal_url") or ""))
    )


def build_call_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for _, deal_rows in grouped.items():
        deal_rows = sorted(deal_rows, key=_call_sort_key)
        call_rows = [r for r in deal_rows if not r.get("no_calls")]
        no_call_rows = [r for r in deal_rows if r.get("no_calls")]
        first = deal_rows[0]
        if not call_rows and no_call_rows:
            out.append(
                {
                    "deal_url": first.get("deal_url"),
                    "call_number": "",
                    "subject": first.get("subject") or "Звонков не найдено",
                    "duration_minutes": "",
                    "call_has_error": True,
                    "error": _short_error(first.get("error") or "По сделке не найдено звонков"),
                }
            )
            continue
        for index, row in enumerate(call_rows, start=1):
            out.append(
                {
                    "deal_url": row.get("deal_url"),
                    "call_number": index,
                    "subject": row.get("subject"),
                    "duration_minutes": row.get("duration_minutes"),
                    "call_quality_score": row.get("call_quality_score"),
                    "call_quality_details": row.get("call_quality_details"),
                    "call_checklist_total_score": row.get("call_checklist_total_score"),
                    "call_checklist_max_score": row.get("call_checklist_max_score"),
                    "call_checklist_percent": row.get("call_checklist_percent"),
                    "call_checklist_block_details": row.get("call_checklist_block_details"),
                    "has_greeting": row.get("has_greeting"),
                    "has_needs_discovery": row.get("has_needs_discovery"),
                    "has_objection_work": row.get("has_objection_work"),
                    "has_next_step_phrase": row.get("has_next_step_phrase"),
                    "alignment_score": row.get("alignment_score"),
                    "alignment_details": row.get("alignment_details"),
                    "next_step_synced": row.get("next_step_synced"),
                    "next_step_synced_details": row.get("next_step_synced_details"),
                    "call_quality_conclusion": row.get("call_quality_conclusion"),
                    "conversation_meaning": row.get("conversation_meaning"),
                    "bitrix_chat_summary": row.get("bitrix_chat_summary"),
                    "bitrix_call_summary": row.get("bitrix_call_summary"),
                    "bitrix_overall_meaning": row.get("bitrix_overall_meaning"),
                    "bitrix_combined_summary": row.get("bitrix_combined_summary"),
                    "bitrix_summary_sources": row.get("bitrix_summary_sources"),
                    "improvement_moments": row.get("improvement_moments"),
                    "unhandled_objections": row.get("unhandled_objections"),
                    "objection_recommendations": row.get("objection_recommendations"),
                    "transcript_path": row.get("transcript_path"),
                    "transcript_marked": row.get("transcript_marked"),
                    "transcript_text": row.get("transcript_text"),
                    "bitrix_card_transcript_status": row.get("bitrix_card_transcript_status"),
                    "transcript_match_score": row.get("transcript_match_score"),
                    "bitrix_card_transcript": row.get("bitrix_card_transcript"),
                    "call_has_error": bool(row.get("error")),
                    "error": _short_error(row.get("error")),
                }
            )
    return out


def build_objection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        for objection in row.get("objection_rows") or []:
            if not isinstance(objection, dict):
                continue
            out.append(
                {
                    "deal_url": row.get("deal_url"),
                    "stage_name": row.get("stage_name") or stage_display_name(row.get("stage_id")),
                    "manager_name": row.get("manager_name"),
                    "subject": row.get("subject"),
                    "objection_fragment": objection.get("objection_fragment"),
                    "objection_status": objection.get("objection_status"),
                    "objection_recommendations": objection.get("objection_recommendation"),
                }
            )
    return out


def build_call_checklist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for _, deal_rows in grouped.items():
        deal_rows = sorted(deal_rows, key=_call_sort_key)
        call_rows = [r for r in deal_rows if not r.get("no_calls")]
        for index, row in enumerate(call_rows, start=1):
            for item in row.get("call_checklist_items") or []:
                if not isinstance(item, dict):
                    continue
                out.append(
                    {
                        "deal_url": row.get("deal_url"),
                        "stage_name": row.get("stage_name")
                        or stage_display_name(row.get("stage_id")),
                        "manager_name": row.get("manager_name"),
                        "call_number": index,
                        "subject": row.get("subject"),
                        "duration_minutes": row.get("duration_minutes"),
                        "checklist_block_name": item.get("checklist_block_name"),
                        "checklist_criterion": item.get("checklist_criterion"),
                        "checklist_score": item.get("checklist_score"),
                        "checklist_max_score": item.get("checklist_max_score"),
                        "checklist_evidence": item.get("checklist_evidence"),
                        "checklist_comment": item.get("checklist_comment"),
                        "checklist_code": item.get("checklist_code"),
                    }
                )
    return out


def build_sales_stage_score_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for _, deal_rows in grouped.items():
        deal_rows = sorted(deal_rows, key=_call_sort_key)
        call_rows = [r for r in deal_rows if not r.get("no_calls")]
        for index, row in enumerate(call_rows, start=1):
            for block in row.get("call_checklist_blocks") or []:
                if not isinstance(block, dict):
                    continue
                out.append(
                    {
                        "deal_url": row.get("deal_url"),
                        "stage_name": row.get("stage_name")
                        or stage_display_name(row.get("stage_id")),
                        "manager_name": row.get("manager_name"),
                        "call_number": index,
                        "subject": row.get("subject"),
                        "duration_minutes": row.get("duration_minutes"),
                        "sales_stage_block_name": block.get("sales_stage_block_name"),
                        "sales_stage_score": block.get("sales_stage_score"),
                        "sales_stage_max_score": block.get("sales_stage_max_score"),
                        "sales_stage_percent": block.get("sales_stage_percent"),
                        "sales_stage_missing": block.get("sales_stage_missing"),
                    }
                )
    return out


def _training_recommendation(block_name: Any, criterion: Any) -> str:
    block = str(block_name or "").lower()
    crit = str(criterion or "").strip()
    if "контакт" in block:
        return f"Отработать старт звонка: {crit}. Сделать короткий обязательный скрипт первых 20 секунд."  # noqa: E501
    if "потребност" in block:
        return f"Отработать выявление потребности: {crit}. Добавить 3-5 обязательных уточняющих вопросов до презентации."  # noqa: E501
    if "презентац" in block:
        return f"Усилить презентацию: {crit}. Привязывать предложение к задаче клиента и говорить языком выгоды."  # noqa: E501
    if "возраж" in block:
        return f"Отработать возражения: {crit}. Использовать схему: признать, уточнить причину, дать аргумент, закрепить следующий шаг."  # noqa: E501
    if "закрытие" in block:
        return f"Усилить закрытие звонка: {crit}. Фиксировать договоренность, срок и следующий контакт в разговоре и CRM."  # noqa: E501
    if "заполнение" in block:
        return f"Навести порядок в карточке сделки: {crit}. Сделать поле обязательным или добавить контроль перед переводом стадии."  # noqa: E501
    if "активность" in block:
        return f"Проверить дисциплину касаний: {crit}. Звонок менеджера должен быть виден в CRM после исключения Call-центра."  # noqa: E501
    if "связь" in block:
        return f"Синхронизировать разговор и CRM: {crit}. После звонка фиксировать следующий шаг и ключевые договоренности в карточке."  # noqa: E501
    if "движение" in block:
        return f"Контролировать движение по воронке: {crit}. Проверить зависшие стадии, возвраты и актуальность текущей стадии."  # noqa: E501
    return f"Разобрать на обучении: {crit}. Проверить фрагменты звонков с низкой оценкой."


def build_manager_stage_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("no_calls") or row.get("error"):
            continue
        manager = str(row.get("manager_name") or row.get("manager_id") or "Без менеджера")
        deal_key = _deal_group_key(row)
        for block in row.get("call_checklist_blocks") or []:
            if not isinstance(block, dict):
                continue
            block_name = str(block.get("sales_stage_block_name") or "")
            if not block_name:
                continue
            key = (manager, block_name)
            item = agg.setdefault(
                key,
                {
                    "manager_name": manager,
                    "sales_stage_block_name": block_name,
                    "manager_stage_calls": 0,
                    "_deals": set(),
                    "_deal_urls": set(),
                    "_percent_sum": 0.0,
                    "manager_stage_weak_calls": 0,
                },
            )
            percent = float(block.get("sales_stage_percent") or 0.0)
            item["manager_stage_calls"] += 1
            item["_percent_sum"] += percent
            item["_deals"].add(deal_key)
            if percent < 70:
                item["manager_stage_weak_calls"] += 1
                if row.get("deal_url"):
                    item["_deal_urls"].add(str(row.get("deal_url")))

    out: list[dict[str, Any]] = []
    for item in agg.values():
        calls = max(1, int(item["manager_stage_calls"]))
        weak = int(item["manager_stage_weak_calls"])
        out.append(
            {
                "manager_name": item["manager_name"],
                "deal_url": "\n".join(sorted(item.get("_deal_urls") or [])),
                "sales_stage_block_name": item["sales_stage_block_name"],
                "manager_stage_calls": calls,
                "manager_stage_deals": len(item["_deals"]),
                "manager_stage_avg_percent": round(float(item["_percent_sum"]) / calls, 2),
                "manager_stage_weak_calls": weak,
                "manager_stage_weak_rate": round(weak * 100.0 / calls, 2),
            }
        )
    return sorted(
        out,
        key=lambda r: (
            float(r.get("manager_stage_avg_percent") or 0.0),
            str(r.get("manager_name") or ""),
        ),
    )


def build_manager_criterion_gap_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("no_calls") or row.get("error"):
            continue
        manager = str(row.get("manager_name") or row.get("manager_id") or "Без менеджера")
        for item in row.get("call_checklist_items") or []:
            if not isinstance(item, dict):
                continue
            block_name = str(item.get("checklist_block_name") or "")
            criterion = str(item.get("checklist_criterion") or "")
            if not criterion:
                continue
            key = (manager, block_name, criterion)
            bucket = agg.setdefault(
                key,
                {
                    "manager_name": manager,
                    "checklist_block_name": block_name,
                    "checklist_criterion": criterion,
                    "criterion_calls": 0,
                    "_deal_urls": set(),
                    "_score_sum": 0.0,
                    "criterion_failed_count": 0,
                    "criterion_partial_count": 0,
                    "training_recommendation": _training_recommendation(block_name, criterion),
                },
            )
            score = float(item.get("checklist_score") or 0.0)
            bucket["criterion_calls"] += 1
            bucket["_score_sum"] += score
            if score <= 0:
                bucket["criterion_failed_count"] += 1
                if row.get("deal_url"):
                    bucket["_deal_urls"].add(str(row.get("deal_url")))
            elif score < 1:
                bucket["criterion_partial_count"] += 1
                if row.get("deal_url"):
                    bucket["_deal_urls"].add(str(row.get("deal_url")))

    out: list[dict[str, Any]] = []
    for bucket in agg.values():
        calls = max(1, int(bucket["criterion_calls"]))
        avg_score = float(bucket["_score_sum"]) / calls
        failed = int(bucket["criterion_failed_count"])
        partial = int(bucket["criterion_partial_count"])
        out.append(
            {
                "manager_name": bucket["manager_name"],
                "deal_url": "\n".join(sorted(bucket.get("_deal_urls") or [])),
                "checklist_block_name": bucket["checklist_block_name"],
                "checklist_criterion": bucket["checklist_criterion"],
                "criterion_calls": calls,
                "criterion_avg_score": round(avg_score, 2),
                "criterion_completion_percent": round(avg_score * 100.0, 2),
                "criterion_failed_count": failed,
                "criterion_partial_count": partial,
                "criterion_fail_rate": round((failed + partial) * 100.0 / calls, 2),
                "training_recommendation": bucket["training_recommendation"],
            }
        )
    return sorted(
        out,
        key=lambda r: (
            float(r.get("criterion_completion_percent") or 0.0),
            -float(r.get("criterion_fail_rate") or 0.0),
            str(r.get("manager_name") or ""),
        ),
    )


def _aggregate_deal_crm_row(deal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_rows = sorted(deal_rows, key=_call_sort_key)
    first = dict(sorted_rows[0])
    call_rows = [r for r in sorted_rows if not r.get("no_calls")]
    ok_calls = [r for r in call_rows if not r.get("error")]
    first["no_calls"] = bool(not call_rows or any(r.get("no_calls") for r in sorted_rows))
    first["calls_count"] = max(int(first.get("calls_count") or 0), len(call_rows))
    first["has_next_step_phrase"] = any(r.get("has_next_step_phrase") for r in ok_calls)
    first["next_step_synced"] = any(r.get("next_step_synced") for r in ok_calls)
    first["amount_mentioned"] = any(r.get("amount_mentioned") for r in ok_calls)
    first["crm_checklist_items"] = (
        evaluate_crm_checklist(first, include_stage=True).get("crm_checklist_items") or []
    )
    return first


def build_crm_checklist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for _, deal_rows in grouped.items():
        deal_row = _aggregate_deal_crm_row(deal_rows)
        for item in deal_row.get("crm_checklist_items") or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "deal_url": deal_row.get("deal_url"),
                    "stage_name": deal_row.get("stage_name")
                    or stage_display_name(deal_row.get("stage_id")),
                    "manager_name": deal_row.get("manager_name"),
                    "crm_checklist_block_name": item.get("crm_checklist_block_name"),
                    "crm_checklist_criterion": item.get("crm_checklist_criterion"),
                    "crm_checklist_score": item.get("crm_checklist_score"),
                    "crm_checklist_max_score": item.get("crm_checklist_max_score"),
                    "crm_checklist_comment": item.get("crm_checklist_comment"),
                    "crm_checklist_code": item.get("crm_checklist_code"),
                }
            )
    return out


def build_manager_crm_gap_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    agg: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, deal_rows in grouped.items():
        deal_row = _aggregate_deal_crm_row(deal_rows)
        manager = str(deal_row.get("manager_name") or deal_row.get("manager_id") or "Без менеджера")
        for item in deal_row.get("crm_checklist_items") or []:
            if not isinstance(item, dict):
                continue
            block_name = str(item.get("crm_checklist_block_name") or "")
            criterion = str(item.get("crm_checklist_criterion") or "")
            if not criterion:
                continue
            key = (manager, block_name, criterion)
            bucket = agg.setdefault(
                key,
                {
                    "manager_name": manager,
                    "crm_checklist_block_name": block_name,
                    "crm_checklist_criterion": criterion,
                    "crm_criterion_deals": 0,
                    "_deal_urls": set(),
                    "_score_sum": 0.0,
                    "crm_criterion_failed_count": 0,
                    "crm_criterion_partial_count": 0,
                    "training_recommendation": _training_recommendation(block_name, criterion),
                },
            )
            score = float(item.get("crm_checklist_score") or 0.0)
            bucket["crm_criterion_deals"] += 1
            bucket["_score_sum"] += score
            if score <= 0:
                bucket["crm_criterion_failed_count"] += 1
                if deal_row.get("deal_url"):
                    bucket["_deal_urls"].add(str(deal_row.get("deal_url")))
            elif score < 1:
                bucket["crm_criterion_partial_count"] += 1
                if deal_row.get("deal_url"):
                    bucket["_deal_urls"].add(str(deal_row.get("deal_url")))

    out: list[dict[str, Any]] = []
    for bucket in agg.values():
        deals = max(1, int(bucket["crm_criterion_deals"]))
        avg_score = float(bucket["_score_sum"]) / deals
        failed = int(bucket["crm_criterion_failed_count"])
        partial = int(bucket["crm_criterion_partial_count"])
        out.append(
            {
                "manager_name": bucket["manager_name"],
                "deal_url": "\n".join(sorted(bucket.get("_deal_urls") or [])),
                "crm_checklist_block_name": bucket["crm_checklist_block_name"],
                "crm_checklist_criterion": bucket["crm_checklist_criterion"],
                "crm_criterion_deals": deals,
                "crm_criterion_avg_score": round(avg_score, 2),
                "crm_criterion_completion_percent": round(avg_score * 100.0, 2),
                "crm_criterion_failed_count": failed,
                "crm_criterion_partial_count": partial,
                "crm_criterion_fail_rate": round((failed + partial) * 100.0 / deals, 2),
                "training_recommendation": bucket["training_recommendation"],
            }
        )
    return sorted(
        out,
        key=lambda r: (
            float(r.get("crm_criterion_completion_percent") or 0.0),
            -float(r.get("crm_criterion_fail_rate") or 0.0),
            str(r.get("manager_name") or ""),
        ),
    )


def _control_priority(score: float, reasons: list[str]) -> tuple[int, str]:
    reason_text = " ".join(reasons).lower()
    if score >= 80 or "нет звонков" in reason_text or "тревога" in reason_text:
        return 1, "Критично"
    if score >= 55:
        return 2, "Высокий"
    if score >= 30:
        return 3, "Средний"
    return 4, "Наблюдать"


def _control_next_action(row: dict[str, Any], reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    if "нет звонков" in text:
        return "Проверить, почему по сделке нет звонка менеджера; назначить контакт с клиентом и зафиксировать следующий шаг в CRM."  # noqa: E501
    if "ошиб" in text:
        return "Запустить режим «Повторить только ошибки», затем проверить, доступна ли запись звонка и корректно ли работает источник аудио."  # noqa: E501
    if "crm" in text or "следующий шаг" in text:
        return "Открыть карточку сделки, заполнить недостающие поля, зафиксировать договоренности и следующий шаг после разговора."  # noqa: E501
    if "разговор" in text or "возраж" in text:
        return "Разобрать расшифровку звонка с менеджером и закрепить конкретный сценарий: потребность, аргумент, следующий шаг."  # noqa: E501
    if "стади" in text or "воронк" in text:
        return "Проверить актуальность стадии, причину зависания и необходимость возврата/перевода сделки."  # noqa: E501
    return "Проверить сделку выборочно и оставить в мониторинге до следующего запуска отчета."


def build_quality_control_rows(deal_report_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in deal_report_rows:
        overall = float(row.get("avg_overall_score") or 0.0)
        call_score = float(row.get("avg_call_quality_score") or 0.0)
        crm_score = float(row.get("crm_checklist_percent") or row.get("crm_work_score") or 0.0)
        calls_total = int(row.get("calls_total") or 0)
        calls_failed = int(row.get("calls_failed") or 0)
        no_calls = bool(row.get("no_calls"))
        risk = str(row.get("stage_movement_risk") or "").strip()
        unhandled = str(row.get("unhandled_objections") or "").strip()
        reasons: list[str] = []
        risk_score = 0.0
        if no_calls or calls_total == 0:
            reasons.append("нет звонков менеджера")
            risk_score += 35
        if calls_failed:
            reasons.append(f"ошибки обработки звонков: {calls_failed}")
            risk_score += min(25, 8 * calls_failed)
        if overall < 40:
            reasons.append(f"низкая итоговая оценка: {overall:g}")
            risk_score += 25
        elif overall < 60:
            reasons.append(f"итоговая оценка требует контроля: {overall:g}")
            risk_score += 12
        if call_score < 50:
            reasons.append(f"слабое качество разговора: {call_score:g}")
            risk_score += 18
        if crm_score < 50:
            reasons.append(f"слабое ведение CRM: {crm_score:g}")
            risk_score += 18
        if risk and risk not in {"OK", "Финал"}:
            reasons.append(f"риск движения по воронке: {risk}")
            risk_score += 20 if "Тревога" in risk else 10
        if unhandled:
            reasons.append("есть неотработанные возражения")
            risk_score += 10
        if not reasons:
            reasons.append("критичных отклонений не найдено")

        order, priority = _control_priority(risk_score, reasons)
        out.append(
            {
                "control_priority_order": order,
                "control_priority": priority,
                "quality_control_score": round(min(100.0, risk_score), 2),
                "deal_url": row.get("deal_url"),
                "stage_name": row.get("stage_name"),
                "manager_name": row.get("manager_name"),
                "avg_overall_score": overall,
                "avg_call_quality_score": call_score,
                "crm_checklist_percent": crm_score,
                "calls_total": calls_total,
                "calls_failed": calls_failed,
                "stage_movement_risk": risk,
                "control_reason": "; ".join(reasons),
                "control_next_action": _control_next_action(row, reasons),
                "recommendations": row.get("recommendations"),
            }
        )
    return sorted(
        out,
        key=lambda r: (
            int(r.get("control_priority_order") or 9),
            -float(r.get("quality_control_score") or 0),
            str(r.get("manager_name") or ""),
        ),
    )


def _coaching_priority(completion: float, fail_rate: float) -> str:
    if completion < 50 or fail_rate >= 60:
        return "Критично"
    if completion < 70 or fail_rate >= 35:
        return "Высокий"
    return "Средний"


def build_coaching_plan_rows(
    manager_criterion_gap_rows: list[dict[str, Any]],
    manager_crm_gap_rows: list[dict[str, Any]],
    manager_stage_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in manager_criterion_gap_rows:
        completion = float(row.get("criterion_completion_percent") or 0.0)
        fail_rate = float(row.get("criterion_fail_rate") or 0.0)
        if completion >= 75 and fail_rate < 30:
            continue
        out.append(
            {
                "manager_name": row.get("manager_name"),
                "training_source": "Звонки",
                "training_topic": f"{row.get('checklist_block_name')}: {row.get('checklist_criterion')}",  # noqa: E501
                "coaching_priority": _coaching_priority(completion, fail_rate),
                "coaching_metric": f"выполнение {completion:g}%, проблем {fail_rate:g}%",
                "coaching_affected_count": row.get("criterion_calls"),
                "training_recommendation": row.get("training_recommendation"),
            }
        )

    for row in manager_crm_gap_rows:
        completion = float(row.get("crm_criterion_completion_percent") or 0.0)
        fail_rate = float(row.get("crm_criterion_fail_rate") or 0.0)
        if completion >= 80 and fail_rate < 25:
            continue
        out.append(
            {
                "manager_name": row.get("manager_name"),
                "training_source": "CRM",
                "training_topic": f"{row.get('crm_checklist_block_name')}: {row.get('crm_checklist_criterion')}",  # noqa: E501
                "coaching_priority": _coaching_priority(completion, fail_rate),
                "coaching_metric": f"выполнение {completion:g}%, проблем {fail_rate:g}%",
                "coaching_affected_count": row.get("crm_criterion_deals"),
                "training_recommendation": row.get("training_recommendation"),
            }
        )

    for row in manager_stage_rows:
        completion = float(row.get("manager_stage_avg_percent") or 0.0)
        weak_rate = float(row.get("manager_stage_weak_rate") or 0.0)
        if completion >= 75 and weak_rate < 30:
            continue
        stage = row.get("sales_stage_block_name")
        out.append(
            {
                "manager_name": row.get("manager_name"),
                "training_source": "Этап продаж",
                "training_topic": f"Этап: {stage}",
                "coaching_priority": _coaching_priority(completion, weak_rate),
                "coaching_metric": f"среднее выполнение {completion:g}%, слабых звонков {weak_rate:g}%",  # noqa: E501
                "coaching_affected_count": row.get("manager_stage_calls"),
                "training_recommendation": f"Провести разбор этапа «{stage}» на примерах звонков менеджера и закрепить короткий рабочий сценарий.",  # noqa: E501
            }
        )

    priority_order = {"Критично": 1, "Высокий": 2, "Средний": 3}
    return sorted(
        out,
        key=lambda r: (
            priority_order.get(str(r.get("coaching_priority") or ""), 9),
            str(r.get("manager_name") or ""),
            str(r.get("training_source") or ""),
        ),
    )


def _avg_numeric(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row.get(key) or 0.0) for row in rows if row.get(key) is not None]
    return round(sum(values) / max(1, len(values)), 2)


def _count_by(rows: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for row in rows if str(row.get(key) or "") == value)


def build_executive_summary_rows(
    deal_report_rows: list[dict[str, Any]],
    manager_summary: list[dict[str, Any]],
    quality_control_rows: list[dict[str, Any]],
    manager_criterion_gap_rows: list[dict[str, Any]],
    manager_crm_gap_rows: list[dict[str, Any]],
    coaching_plan_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(section: str, metric: str, value: Any, comment: str = "") -> None:
        rows.append(
            {
                "summary_section": section,
                "summary_metric": metric,
                "summary_value": value,
                "summary_comment": comment,
            }
        )

    deals_total = len(deal_report_rows)
    calls_total = sum(int(row.get("calls_total") or 0) for row in deal_report_rows)
    calls_ok = sum(int(row.get("calls_ok") or 0) for row in deal_report_rows)
    calls_failed = sum(int(row.get("calls_failed") or 0) for row in deal_report_rows)
    asr_skipped_calls = sum(int(row.get("asr_skipped_calls") or 0) for row in deal_report_rows)
    skipped_short_calls = sum(int(row.get("skipped_short_calls") or 0) for row in deal_report_rows)
    deals_without_calls = sum(1 for row in deal_report_rows if row.get("no_calls"))
    add("Общее", "Сделок в отчете", deals_total)
    add("Общее", "Звонков в сделках", calls_total)
    add("Общее", "Успешно обработано звонков", calls_ok)
    add(
        "Общее",
        "Ошибок обработки звонков",
        calls_failed,
        "Используйте режим «Повторить только ошибки».",
    )
    add(
        "Общее",
        "Звонков без новой ASR",
        asr_skipped_calls,
        "Bit.Newton недоступен или токен не принят; кэш расшифровок используется, где он есть.",
    )
    add(
        "Общее",
        "Исключено коротких звонков",
        skipped_short_calls,
        "Технические дозвоны короче минимальной длительности не отправляются в Bit.Newton.",
    )
    add(
        "Общее",
        "Сделок без звонков менеджера",
        deals_without_calls,
        "Call-центр исключен из оценки менеджера.",
    )
    add("Оценки", "Средняя итоговая оценка", _avg_numeric(deal_report_rows, "avg_overall_score"))
    add(
        "Оценки",
        "Средняя оценка разговора",
        _avg_numeric(deal_report_rows, "avg_call_quality_score"),
    )
    add("Оценки", "Средняя оценка CRM", _avg_numeric(deal_report_rows, "crm_checklist_percent"))
    add(
        "Контроль",
        "Критичных сделок",
        _count_by(quality_control_rows, "control_priority", "Критично"),
    )
    add(
        "Контроль",
        "Сделок высокого приоритета",
        _count_by(quality_control_rows, "control_priority", "Высокий"),
    )
    add(
        "Контроль",
        "Сделок среднего приоритета",
        _count_by(quality_control_rows, "control_priority", "Средний"),
    )

    for index, row in enumerate(quality_control_rows[:5], start=1):
        add(
            "Топ контроля",
            f"{index}. {row.get('manager_name') or ''}",
            row.get("deal_url"),
            str(row.get("control_reason") or ""),
        )

    for index, row in enumerate(manager_criterion_gap_rows[:5], start=1):
        add(
            "Провалы звонков",
            f"{index}. {row.get('manager_name') or ''}",
            f"{row.get('criterion_completion_percent')}%",
            f"{row.get('checklist_block_name')}: {row.get('checklist_criterion')}",
        )

    for index, row in enumerate(manager_crm_gap_rows[:5], start=1):
        add(
            "Провалы CRM",
            f"{index}. {row.get('manager_name') or ''}",
            f"{row.get('crm_criterion_completion_percent')}%",
            f"{row.get('crm_checklist_block_name')}: {row.get('crm_checklist_criterion')}",
        )

    for index, row in enumerate(coaching_plan_rows[:5], start=1):
        add(
            "Обучение",
            f"{index}. {row.get('manager_name') or ''}",
            row.get("coaching_priority"),
            f"{row.get('training_source')}: {row.get('training_topic')}",
        )

    return rows


def build_manager_scorecard_rows(
    manager_summary: list[dict[str, Any]],
    quality_control_rows: list[dict[str, Any]],
    coaching_plan_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    control_by_manager: dict[str, list[dict[str, Any]]] = {}
    for row in quality_control_rows:
        control_by_manager.setdefault(str(row.get("manager_name") or "Без менеджера"), []).append(
            row
        )

    coaching_by_manager: dict[str, list[dict[str, Any]]] = {}
    for row in coaching_plan_rows:
        coaching_by_manager.setdefault(str(row.get("manager_name") or "Без менеджера"), []).append(
            row
        )

    out: list[dict[str, Any]] = []
    sorted_managers = sorted(
        manager_summary, key=lambda r: float(r.get("avg_overall_score") or 0.0)
    )
    for rank, row in enumerate(sorted_managers, start=1):
        manager = str(row.get("manager_name") or "Без менеджера")
        control = control_by_manager.get(manager, [])
        coaching = coaching_by_manager.get(manager, [])
        critical = _count_by(control, "control_priority", "Критично")
        high = _count_by(control, "control_priority", "Высокий")
        top_training = coaching[0] if coaching else {}
        score = float(row.get("avg_overall_score") or 0.0)
        if critical:
            focus = "Срочный контроль сделок"
            next_action = "Начать с критичных сделок из листа «Контроль качества», затем провести точечный разбор звонков."  # noqa: E501
        elif high:
            focus = "Плановый контроль сделок"
            next_action = (
                "Проверить сделки высокого приоритета и закрепить правила фиксации следующего шага."
            )
        elif coaching:
            focus = "Обучение по стабильности качества"
            next_action = "Провести короткое обучение по главной теме из плана обучения."
        elif score < 70:
            focus = "Наблюдение"
            next_action = (
                "Проверить несколько свежих сделок и сравнить динамику на следующем отчете."
            )
        else:
            focus = "Поддерживать уровень"
            next_action = "Использовать лучшие звонки менеджера как примеры для команды."
        out.append(
            {
                "manager_rank": rank,
                "manager_name": manager,
                "avg_overall_score": row.get("avg_overall_score"),
                "deals_total": row.get("deals_total"),
                "calls_total": row.get("calls_total"),
                "calls_ok": row.get("calls_ok"),
                "deals_without_calls": row.get("deals_without_calls"),
                "manager_critical_deals": critical,
                "manager_high_deals": high,
                "manager_training_topics": len(coaching),
                "manager_top_training_topic": top_training.get("training_topic") or "",
                "top_growth_zones": row.get("top_growth_zones"),
                "top_checklist_gaps": row.get("top_checklist_gaps"),
                "manager_focus": focus,
                "manager_next_action": next_action,
            }
        )
    return out


def _unique_deal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)
    return [sorted(deal_rows, key=_call_sort_key)[0] for deal_rows in grouped.values()]


def build_stage_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for deal_row in _unique_deal_rows(rows):
        for item in deal_row.get("stage_history_items") or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "deal_url": deal_row.get("deal_url"),
                    "manager_name": deal_row.get("manager_name"),
                    "stage_history_event_id": item.get("stage_history_event_id"),
                    "stage_history_event_type": item.get("stage_history_event_type"),
                    "stage_history_created_at": item.get("stage_history_created_at"),
                    "stage_id": item.get("stage_id"),
                    "stage_name": item.get("stage_name"),
                    "stage_order": item.get("stage_order"),
                    "stage_duration_minutes": item.get("stage_duration_minutes"),
                    "stage_duration_hours": item.get("stage_duration_hours"),
                    "stage_is_current": item.get("stage_is_current"),
                }
            )
    return sorted(
        out,
        key=lambda r: (str(r.get("deal_url") or ""), str(r.get("stage_history_created_at") or "")),
    )


def build_stage_sr_rows(
    rows: list[dict[str, Any]], stage_map: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    deal_rows = _unique_deal_rows(rows)
    deals_total = len(deal_rows)
    stage_deals: dict[str, set[str]] = {}
    ranks = stage_order_map(stage_map)

    for deal_row in deal_rows:
        deal_key = _deal_group_key(deal_row)
        seen_stages: set[str] = set()
        for item in deal_row.get("stage_history_items") or []:
            if not isinstance(item, dict):
                continue
            stage_id = str(item.get("stage_id") or "").strip()
            if stage_id:
                seen_stages.add(stage_id)
        if not seen_stages and deal_row.get("stage_id"):
            seen_stages.add(str(deal_row.get("stage_id")))
        for stage_id in seen_stages:
            stage_deals.setdefault(stage_id, set()).add(deal_key)

    out: list[dict[str, Any]] = []
    for stage_id, deal_keys in stage_deals.items():
        passed = len(deal_keys)
        out.append(
            {
                "stage_id": stage_id,
                "stage_name": stage_display_name(stage_id, stage_map=stage_map),
                "stage_order": ranks.get(stage_id),
                "stage_deals_total": deals_total,
                "stage_deals_passed": passed,
                "stage_sr": round((passed / max(1, deals_total)) * 100.0, 2),
            }
        )
    return sorted(
        out, key=lambda r: (safe_int(r.get("stage_order")) or 9999, str(r.get("stage_name") or ""))
    )


def build_stage_movement_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for deal_row in _unique_deal_rows(rows):
        out.append(
            {
                "deal_url": deal_row.get("deal_url"),
                "stage_name": deal_row.get("stage_name")
                or stage_display_name(deal_row.get("stage_id")),
                "manager_name": deal_row.get("manager_name"),
                "stage_history_count": deal_row.get("stage_history_count"),
                "stage_history_path": deal_row.get("stage_history_path"),
                "stage_last_change_at": deal_row.get("stage_last_change_at"),
                "stage_current_age_minutes": deal_row.get("stage_current_age_minutes"),
                "stage_current_age_days": deal_row.get("stage_current_age_days"),
                "stage_warning_threshold": deal_row.get("stage_warning_threshold"),
                "stage_critical_threshold": deal_row.get("stage_critical_threshold"),
                "stage_current_age_status": deal_row.get("stage_current_age_status"),
                "deal_total_work_minutes": deal_row.get("deal_total_work_minutes"),
                "deal_total_work_days": deal_row.get("deal_total_work_days"),
                "deal_total_work_warning_threshold": deal_row.get(
                    "deal_total_work_warning_threshold"
                ),
                "deal_total_work_critical_threshold": deal_row.get(
                    "deal_total_work_critical_threshold"
                ),
                "deal_total_work_status": deal_row.get("deal_total_work_status"),
                "stage_return_count": deal_row.get("stage_return_count"),
                "stage_reached_final": deal_row.get("stage_reached_final"),
                "stage_movement_risk": deal_row.get("stage_movement_risk"),
                "stage_movement_recommendation": deal_row.get("stage_movement_recommendation"),
            }
        )
    risk_order = {
        "Зависла": 0,
        "Нет продвижения": 1,
        "Возвраты": 2,
        "Нет истории": 3,
        "OK": 4,
        "Финал": 5,
    }
    return sorted(
        out,
        key=lambda r: (
            risk_order.get(str(r.get("stage_movement_risk") or ""), 9),
            str(r.get("manager_name") or ""),
        ),
    )


def build_manager_summary(
    rows: list[dict[str, Any]], score_key: str = "overall_score"
) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_deal_group_key(row), []).append(row)

    for _, deal_rows in grouped.items():
        first = deal_rows[0]
        mid = str(first.get("manager_id") or "unknown")
        call_rows = [r for r in deal_rows if not r.get("no_calls")]
        ok_calls = [r for r in call_rows if not r.get("error")]
        scored_calls = [r for r in ok_calls if r.get(score_key) is not None]
        deal_score = (
            sum(float(r.get(score_key) or 0.0) for r in scored_calls) / len(scored_calls)
            if scored_calls
            else 0.0
        )
        a = agg.setdefault(
            mid,
            {
                "manager_id": mid,
                "manager_name": first.get("manager_name") or mid,
                "deals_total": 0,
                "calls_total": 0,
                "calls_ok": 0,
                "deals_without_calls": 0,
                "scored_deals": 0,
                "overall_score_sum": 0.0,
                "growth_deal_data": 0,
                "growth_call_structure": 0,
                "growth_alignment": 0,
                "_checklist_gaps": {},
            },
        )
        a["deals_total"] += 1
        a["calls_total"] += len(call_rows)
        a["calls_ok"] += len(ok_calls)
        if any(r.get("no_calls") for r in deal_rows) or not call_rows:
            a["deals_without_calls"] += 1
        a["scored_deals"] += 1
        a["overall_score_sum"] += deal_score
        if any(
            not r.get("has_comments")
            or not r.get("has_next_step_activity")
            or not r.get("next_step_activity_has_comment")
            or not r.get("next_step_activity_not_overdue")
            for r in deal_rows
        ):
            a["growth_deal_data"] += 1
        if not ok_calls or any(
            float(r.get("call_checklist_percent") or r.get("call_quality_score") or 0.0) < 70
            for r in ok_calls
        ):
            a["growth_call_structure"] += 1
        if not ok_calls or not any(r.get("next_step_synced") for r in ok_calls):
            a["growth_alignment"] += 1
        gaps = a.setdefault("_checklist_gaps", {})
        if isinstance(gaps, dict):
            for call in ok_calls:
                for item in call.get("call_checklist_items") or []:
                    if not isinstance(item, dict):
                        continue
                    score = float(item.get("checklist_score") or 0.0)
                    if score >= 1:
                        continue
                    criterion = str(item.get("checklist_criterion") or "").strip()
                    if criterion:
                        gaps[criterion] = int(gaps.get(criterion, 0)) + 1

    out: list[dict[str, Any]] = []
    for _, a in agg.items():
        total = max(1, int(a["scored_deals"]))
        a["avg_overall_score"] = round(float(a["overall_score_sum"]) / total, 2)
        a.pop("scored_deals", None)
        gaps = a.pop("_checklist_gaps", {}) or {}
        if isinstance(gaps, dict):
            a["top_checklist_gaps"] = "; ".join(
                criterion
                for criterion, _ in sorted(gaps.items(), key=lambda x: int(x[1]), reverse=True)[:5]
            )
        else:
            a["top_checklist_gaps"] = ""
        zones = sorted(
            [
                ("Ведение CRM", a["growth_deal_data"]),
                ("Структура разговора", a["growth_call_structure"]),
                ("Синхронизация звонок↔CRM", a["growth_alignment"]),
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        a["top_growth_zones"] = ", ".join([z[0] for z in zones[:3]])
        out.append(a)
    return sorted(out, key=lambda x: x["avg_overall_score"])
