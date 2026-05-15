from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple

from pipelines.finalization import finalize_sync_report
from pipelines.processing import process_deals
from pipelines.reevaluation import reevaluate_report
from pipelines.runtime import (
    build_processing_context,
    close_processing_context,
    create_bitnewton_asr,
    create_bitrix_api,
    load_kpi_pair,
    load_state_cache,
    prepare_audio_runtime,
    resolve_deal_scope,
    save_state_cache,
)


def run_sync(args: Any) -> Tuple[int, Path, Path]:
    kpi, kpi_cmp = load_kpi_pair(args)
    if args.reevaluate_from:
        return reevaluate_report(args, kpi, kpi_cmp)

    api = create_bitrix_api()
    asr = create_bitnewton_asr(args)
    retry_scope, deal_ids = resolve_deal_scope(args, api)
    audio_runtime = prepare_audio_runtime(args)
    state_cache = load_state_cache()
    processing_ctx = build_processing_context(
        api=api,
        asr=asr,
        args=args,
        kpi=kpi,
        kpi_cmp=kpi_cmp,
        audio_runtime=audio_runtime,
        state_cache=state_cache,
    )
    try:
        run_result = process_deals(ctx=processing_ctx, deal_ids=deal_ids, retry_scope=retry_scope)
    finally:
        close_processing_context(processing_ctx)
        save_state_cache(state_cache)

    report = finalize_sync_report(
        api=api,
        args=args,
        results=run_result.rows,
        kpi=kpi,
        kpi_cmp=kpi_cmp,
        retry_scope=retry_scope,
        ok=run_result.ok,
        err=run_result.err,
    )

    return run_result.ok, report.json_out, report.xlsx_out
