from __future__ import annotations

from pathlib import Path
from typing import Any

from pipelines.config_loader import load_kpi_pair, load_state_cache, save_state_cache
from pipelines.deals import resolve_deal_ids
from pipelines.factories import (
    create_bitnewton_asr,
    create_bitrix_api,
    create_vibecode_client,
    validate_asr_token,
)
from pipelines.finalization import finalize_sync_report
from pipelines.processing import process_deals
from pipelines.reevaluation import reevaluate_report
from pipelines.runtime import (
    build_processing_context,
    close_processing_context,
    prepare_audio_runtime,
    resolve_retry_scope,
)


async def run_sync(args: Any) -> tuple[int, Path, Path]:
    # 1. Загрузка конфигурации
    kpi, kpi_cmp = load_kpi_pair(args)

    # 2. Переоценка (если требуется)
    if args.reevaluate_from:
        return await reevaluate_report(args, kpi, kpi_cmp)

    # 3. Инициализация внешних сервисов
    api = await create_bitrix_api()
    vibe = create_vibecode_client(args)
    asr = create_bitnewton_asr(args)

    # Асинхронная валидация токена ASR
    await validate_asr_token(asr)

    # 4. Определение списка сделок
    retry_scope = resolve_retry_scope(args)
    if retry_scope is not None:
        deal_ids = list(retry_scope.get("deal_ids") or [])
    else:
        deal_ids = await resolve_deal_ids(args, api, vibe=vibe)

    # 5. Подготовка окружения для обработки
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
        vibe=vibe,
    )

    # 6. Основной цикл обработки
    try:
        run_result = await process_deals(
            ctx=processing_ctx, deal_ids=deal_ids, retry_scope=retry_scope
        )

        # 7. Финализация и генерация отчета
        report = await finalize_sync_report(
            api=api,
            args=args,
            results=run_result.rows,
            kpi=kpi,
            kpi_cmp=kpi_cmp,
            retry_scope=retry_scope,
            ok=run_result.ok,
            err=run_result.err,
            vibe=vibe,
        )
    finally:
        await close_processing_context(processing_ctx)
        save_state_cache(state_cache)

    return run_result.ok, report.json_out, report.xlsx_out
