from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from asr.bitnewton import env_bitnewton_asr
from bitrix.api import Bitrix24API
from pipelines.audio import build_audio_source_index, parse_audio_source_dirs
from pipelines.calls import user_name_map
from pipelines.deals import (
    deal_id_from_report_row,
    resolve_deal_ids,
)
from pipelines.cleanup import cleanup_old_chrome_tmp_profiles, cleanup_old_outputs
from pipelines.evaluation import refresh_crm_scores_after_stage_metrics
from pipelines.kpi import load_kpi_config
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.processing import ProcessingContext, process_deal
from pipelines.reevaluation import reevaluate_report
from pipelines.reporting import (
    build_manager_summary,
    flatten_results,
    prepare_report_rows,
    publish_latest_report,
)
from pipelines.retry import load_retry_scope, merge_retry_results
from pipelines.stage_history import (
    attach_stage_history_metrics,
    fetch_stage_history_by_deals,
    fetch_stage_name_map,
)
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

    manager_ids = [int(r["manager_id"]) for r in results if isinstance(r.get("manager_id"), int)]
    names = user_name_map(api, manager_ids) if manager_ids else {}
    for r in results:
        mid = r.get("manager_id")
        if isinstance(mid, int):
            r["manager_name"] = names.get(mid, str(mid))
        if r.get("overall_score") is None:
            r["overall_score"] = 0.0

    stage_ids_for_map = [str(r.get("stage_id") or "") for r in results]
    stage_history_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    try:
        unique_deal_ids = sorted({str(deal_id_from_report_row(r) or "") for r in results if deal_id_from_report_row(r)})
        if unique_deal_ids:
            print("[STAGE] Загружаю историю перемещений сделок по стадиям", flush=True)
            stage_history_by_deal = fetch_stage_history_by_deals(api, unique_deal_ids)
            for items in stage_history_by_deal.values():
                stage_ids_for_map.extend(str(item.get("STAGE_ID") or "") for item in items if isinstance(item, dict))
    except Exception as e:
        print(f"[WARN] Не удалось загрузить историю стадий: {e}", flush=True)

    stage_map = fetch_stage_name_map(api, stage_ids_for_map)
    if stage_history_by_deal:
        attach_stage_history_metrics(results, stage_history_by_deal, stage_map=stage_map)
    refresh_crm_scores_after_stage_metrics(results, kpi, kpi_cmp)

    final_results = results
    if retry_scope is not None:
        source_rows = list(retry_scope.get("source_rows") or [])
        final_results = merge_retry_results(source_rows, results, retry_scope)
        print(
            f"[RETRY] Пересобираю полный отчет: исходных строк={len(source_rows)}, "
            f"повторно обработано={len(results)}, итоговых строк={len(final_results)}",
            flush=True,
        )

    manager_summary = build_manager_summary(final_results)
    manager_summary_cmp = (
        build_manager_summary(final_results, score_key="overall_score_cmp") if kpi_cmp is not None else None
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_results = prepare_report_rows(final_results, stage_map=stage_map)
    json_out = REPORTS_DIR / f"bitnewton_sync_report_{ts}.json"
    json_out.write_text(json.dumps(report_results, ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(
        report_results,
        manager_summary,
        manager_summary_cmp=manager_summary_cmp,
        stage_map=stage_map,
    )
    publish_latest_report(json_out, xlsx_out)
    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    if kpi_cmp is not None:
        ranked = sorted(
            [r for r in final_results if r.get("overall_score_delta") is not None],
            key=lambda x: abs(float(x.get("overall_score_delta") or 0.0)),
            reverse=True,
        )[:5]
        if ranked:
            print("\nТоп-5 кейсов с максимальной разницей KPI:")
            for i, r in enumerate(ranked, 1):
                print(
                    f"{i}. deal={r.get('deal_id')} act={r.get('activity_id')} "
                    f"manager={r.get('manager_name') or r.get('manager_id')} "
                    f"base={r.get('overall_score')} cmp={r.get('overall_score_cmp')} "
                    f"delta={r.get('overall_score_delta')}"
                )
    print(f"ИТОГО: OK={ok} ERR={err}")

    if int(args.cleanup_chrome_tmp_days or 0) > 0:
        removed = cleanup_old_chrome_tmp_profiles(REPORTS_DIR, keep_days=int(args.cleanup_chrome_tmp_days))
        if removed:
            print(f"[OK] Удалено старых chrome_profile_tmp_*: {removed}")

    return ok, json_out, xlsx_out
