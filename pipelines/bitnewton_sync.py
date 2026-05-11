from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from asr.bitnewton import env_bitnewton_asr
from bitrix.api import Bitrix24API
from pipelines.audio import build_audio_source_index, parse_audio_source_dirs
from pipelines.cleanup import cleanup_old_outputs
from pipelines.deals import resolve_deal_ids
from pipelines.finalization import finalize_sync_report
from pipelines.kpi import load_kpi_config
from pipelines.paths import REPORTS_DIR
from pipelines.processing import ProcessingContext, process_deal
from pipelines.reevaluation import reevaluate_report
from pipelines.retry import load_retry_scope
from pipelines.transcription import _load_state_cache, _save_state_cache


def run_sync(args: Any) -> Tuple[int, Path, Path]:
    kpi = load_kpi_config(args.kpi_config)
    kpi_cmp = load_kpi_config(args.kpi_config_compare) if args.kpi_config_compare else None

    if args.reevaluate_from:
        return reevaluate_report(args, kpi, kpi_cmp)

    api = Bitrix24API()
    if not api.test_connection():
        raise SystemExit(1)

    if args.use_bitnewton or args.bitnewton_flow:
        asr = env_bitnewton_asr()
        if not asr:
            raise SystemExit("Не задан BITNEWTON_TOKEN в .env")
    else:
        raise SystemExit("Нужен флаг --use-bitnewton (или --bitnewton-flow)")

    retry_scope = load_retry_scope(args.retry_errors_from) if args.retry_errors_from else None
    if retry_scope is not None:
        deal_ids = list(retry_scope.get("deal_ids") or [])
        if not deal_ids:
            raise SystemExit("В выбранном отчете нет строк с ошибками для повторного запуска")
        print(
            f"[RETRY] Повторяю только ошибки из отчета: "
            f"строк с ошибками={retry_scope.get('errors', 0)}, сделок={len(deal_ids)}",
            flush=True,
        )
    else:
        deal_ids = resolve_deal_ids(args, api)
    results: List[Dict[str, Any]] = []
    state_cache = _load_state_cache()

    audio_dir = REPORTS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ui_audio_dir = Path(args.ui_download_dir) if args.ui_download_dir else (REPORTS_DIR / "audio_ui")
    ui_audio_dir.mkdir(parents=True, exist_ok=True)
    audio_source_dirs = parse_audio_source_dirs(getattr(args, "audio_source_dir", []))
    audio_source_index = build_audio_source_index(audio_source_dirs)
    if audio_source_dirs:
        print(
            f"[AUDIO] Локальных аудиофайлов в индексе: {len(audio_source_index)}; "
            f"папки: {', '.join(str(p) for p in audio_source_dirs)}",
            flush=True,
        )
    cleanup_days = int(args.cleanup_output_days or 0)
    if cleanup_days > 0:
        removed = cleanup_old_outputs(REPORTS_DIR, keep_days=cleanup_days, extra_audio_dirs=[ui_audio_dir])
        if removed.get("total"):
            print(
                f"[OK] Автоочистка старше {cleanup_days} дней: "
                f"отчеты={removed.get('reports', 0)}, "
                f"аудио={removed.get('audio', 0)}, "
                f"расшифровки={removed.get('transcripts', 0)}",
                flush=True,
            )

    processing_ctx = ProcessingContext(
        api=api,
        asr=asr,
        args=args,
        kpi=kpi,
        kpi_cmp=kpi_cmp,
        audio_source_index=audio_source_index,
        audio_dir=audio_dir,
        ui_audio_dir=ui_audio_dir,
        state_cache=state_cache,
    )
    ok = 0
    err = 0
    user_cache: Dict[int, Dict[str, Any]] = {}
    department_cache: Dict[int, Dict[str, Any]] = {}
    for di, deal_id in enumerate(deal_ids, 1):
        deal_result = process_deal(
            ctx=processing_ctx,
            deal_id=deal_id,
            deal_index=di,
            total_deals=len(deal_ids),
            retry_scope=retry_scope,
            user_cache=user_cache,
            department_cache=department_cache,
            base_ok=ok,
            base_err=err,
        )
        results.extend(deal_result.rows)
        ok += deal_result.ok
        err += deal_result.err

    if processing_ctx.ui_browser_session is not None:
        processing_ctx.ui_browser_session.close()

    _save_state_cache(state_cache)

    report = finalize_sync_report(
        api=api,
        args=args,
        results=results,
        kpi=kpi,
        kpi_cmp=kpi_cmp,
        retry_scope=retry_scope,
        ok=ok,
        err=err,
    )

    return ok, report.json_out, report.xlsx_out
