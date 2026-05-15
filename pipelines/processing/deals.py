from __future__ import annotations

from typing import Any, Dict, List, Optional

from pipelines.calls import (
    compute_discipline_metrics,
    fetch_timeline_comments,
    guess_duration_sec,
    list_deal_call_activities,
    split_call_center_operator_activities,
)
from pipelines.deals import deal_get, deal_url_from_id
from pipelines.evaluation import compute_deal_quality
from pipelines.processing.calls import process_call, process_no_calls_deal
from pipelines.processing.context import DealProcessingResult, ProcessingContext, ProcessingRunResult
from pipelines.stages import safe_int


def _is_missing_bitrix_deal_error(error: Exception) -> bool:
    text = str(error).lower()
    return "crm.deal.get" in text and "not found" in text


def _build_missing_deal_row(
    *,
    ctx: ProcessingContext,
    deal_id: str,
    error: Exception,
    call_center_acts: List[Dict[str, Any]],
    skipped_short_calls: int,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "deal_id": deal_id,
        "deal_url": deal_url_from_id(ctx.args.domain, deal_id),
        "stage_id": None,
        "manager_id": None,
        "manager_name": None,
        "kpi_profile": (ctx.kpi.get("profile") or {}).get("name"),
        "kpi_version": (ctx.kpi.get("profile") or {}).get("version"),
        "kpi_profile_cmp": (ctx.kpi_cmp.get("profile") or {}).get("name") if ctx.kpi_cmp else None,
        "kpi_version_cmp": (ctx.kpi_cmp.get("profile") or {}).get("version") if ctx.kpi_cmp else None,
        "activity_id": None,
        "origin_id": None,
        "subject": "Сделка не найдена",
        "start_time": None,
        "end_time": None,
        "duration_minutes": None,
        "disk_file_id": None,
        "download_url": None,
        "audio_path": None,
        "bitnewton_task_id": None,
        "attach_result": None,
        "error": f"Сделка не найдена или недоступна в Bitrix24: {error}",
        "no_calls": True,
        "ignored_call_center_calls": len(call_center_acts),
        "skipped_short_calls": int(skipped_short_calls or 0),
        "overall_score": 0.0,
        "call_quality_score": 0.0,
        "deal_quality_score": 0.0,
        "crm_work_score": 0.0,
        "call_quality_conclusion": "Оценить разговор невозможно: сделка не найдена или недоступна.",
        "conversation_meaning": "Нет данных: карточка сделки недоступна через Bitrix24 API.",
        "recommendations": "Проверить, удалена ли сделка, перемещена ли она в другую воронку, и есть ли доступ у webhook.",
    }
    if ctx.kpi_cmp is not None:
        row["overall_score_cmp"] = 0.0
        row["overall_score_delta"] = 0.0
    return row


def process_deal(
    *,
    ctx: ProcessingContext,
    deal_id: str,
    deal_index: int,
    total_deals: int,
    retry_scope: Optional[Dict[str, Any]],
    user_cache: Dict[int, Dict[str, Any]],
    department_cache: Dict[int, Dict[str, Any]],
    base_ok: int = 0,
    base_err: int = 0,
) -> DealProcessingResult:
    print(f"\nDEAL {deal_index}/{total_deals}: {deal_url_from_id(ctx.args.domain, deal_id)}")
    acts_raw = list_deal_call_activities(ctx.api, deal_id)
    if ctx.args.include_call_center:
        acts = acts_raw
        call_center_acts: List[Dict[str, Any]] = []
    else:
        acts, call_center_acts = split_call_center_operator_activities(
            ctx.api,
            acts_raw,
            user_cache,
            department_cache,
        )
    print(f"Звонков (crm.activity): {len(acts_raw)}")
    if call_center_acts:
        print(
            f"[SKIP] Звонков операторов Call-центра: {len(call_center_acts)}; к анализу: {len(acts)}",
            flush=True,
        )

    min_call_duration_sec = max(0, int(getattr(ctx.args, "min_call_duration_sec", 15) or 0))
    skipped_short_acts: List[Dict[str, Any]] = []
    if min_call_duration_sec > 0:
        long_acts: List[Dict[str, Any]] = []
        for act in acts:
            if guess_duration_sec(act) < min_call_duration_sec:
                skipped_short_acts.append(act)
            else:
                long_acts.append(act)
        if skipped_short_acts:
            print(
                f"[SKIP] Коротких звонков без полноценного разговора: {len(skipped_short_acts)} "
                f"(меньше {min_call_duration_sec} сек.); к анализу: {len(long_acts)}",
                flush=True,
            )
        acts = long_acts

    if retry_scope is not None:
        retry_ids = retry_scope.get("activity_ids_by_deal", {}).get(str(deal_id), set())
        full_deal_retry = str(deal_id) in retry_scope.get("full_deals", set())
        if full_deal_retry:
            print("[RETRY] Ошибка была на уровне сделки, перепроверяю все звонки этой сделки", flush=True)
        else:
            before_retry = len(acts)
            acts = [activity for activity in acts if safe_int(activity.get("ID")) in retry_ids]
            print(f"[RETRY] К повторной обработке звонков: {len(acts)} из {before_retry}", flush=True)

    max_calls_per_deal = max(0, int(getattr(ctx.args, "max_calls_per_deal", 0) or 0))
    if max_calls_per_deal and len(acts) > max_calls_per_deal:
        skipped_by_limit = len(acts) - max_calls_per_deal
        acts = acts[-max_calls_per_deal:]
        print(
            f"[FAST] Ограничение звонков по сделке: анализирую последние {len(acts)}, "
            f"пропущено {skipped_by_limit}",
            flush=True,
        )

    rows: List[Dict[str, Any]] = []
    ok = 0
    err = 0
    try:
        deal = deal_get(ctx.api, deal_id)
    except Exception as e:
        if not _is_missing_bitrix_deal_error(e):
            raise
        row = _build_missing_deal_row(
            ctx=ctx,
            deal_id=deal_id,
            error=e,
            call_center_acts=call_center_acts,
            skipped_short_calls=len(skipped_short_acts),
        )
        rows.append(row)
        err += 1
        print(f"[DEAL NOT FOUND] OK={base_ok + ok} ERR={base_err + err}: {e}", flush=True)
        return DealProcessingResult(rows=rows, ok=ok, err=err)

    comments = fetch_timeline_comments(ctx.api, deal_id)
    discipline = compute_discipline_metrics(deal, acts, ctx.kpi)
    deal_quality = compute_deal_quality(deal, comments, ctx.kpi)
    manager_id = safe_int(deal.get("ASSIGNED_BY_ID"))

    if not acts:
        row = process_no_calls_deal(
            args=ctx.args,
            deal_id=deal_id,
            deal=deal,
            comments=comments,
            discipline=discipline,
            deal_quality=deal_quality,
            manager_id=manager_id,
            kpi=ctx.kpi,
            kpi_cmp=ctx.kpi_cmp,
            call_center_acts=call_center_acts,
            skipped_short_calls=len(skipped_short_acts),
        )
        rows.append(row)
        err += 1
        print(f"[NO CALLS] OK={base_ok + ok} ERR={base_err + err}", flush=True)
        return DealProcessingResult(rows=rows, ok=ok, err=err)

    for activity_index, activity in enumerate(acts, 1):
        row, success = process_call(
            ctx=ctx,
            deal_id=deal_id,
            deal=deal,
            comments=comments,
            discipline=discipline,
            deal_quality=deal_quality,
            manager_id=manager_id,
            call_center_acts=call_center_acts,
            activity=activity,
            skipped_short_calls=len(skipped_short_acts),
        )
        if success:
            ok += 1
        else:
            err += 1
        rows.append(row)
        print(f"[{activity_index}/{len(acts)}] OK={base_ok + ok} ERR={base_err + err}", flush=True)

    return DealProcessingResult(rows=rows, ok=ok, err=err)


def process_deals(
    *,
    ctx: ProcessingContext,
    deal_ids: List[str],
    retry_scope: Optional[Dict[str, Any]],
) -> ProcessingRunResult:
    rows: List[Dict[str, Any]] = []
    ok = 0
    err = 0
    user_cache: Dict[int, Dict[str, Any]] = {}
    department_cache: Dict[int, Dict[str, Any]] = {}

    for deal_index, deal_id in enumerate(deal_ids, 1):
        deal_result = process_deal(
            ctx=ctx,
            deal_id=deal_id,
            deal_index=deal_index,
            total_deals=len(deal_ids),
            retry_scope=retry_scope,
            user_cache=user_cache,
            department_cache=department_cache,
            base_ok=ok,
            base_err=err,
        )
        rows.extend(deal_result.rows)
        ok += deal_result.ok
        err += deal_result.err

    return ProcessingRunResult(rows=rows, ok=ok, err=err)
