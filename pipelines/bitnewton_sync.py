from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from asr.bitnewton import BitNewtonError, env_bitnewton_asr
from bitrix.api import Bitrix24API
from bitrix.transcriptions import attach_transcription_to_bitrix
from pipelines.audio import (
    build_audio_source_index,
    download_audio_for_call,
    parse_audio_source_dirs,
)
from pipelines.calls import (
    activity_get,
    compute_discipline_metrics,
    fetch_timeline_comments,
    guess_duration_minutes,
    guess_duration_sec,
    list_deal_call_activities,
    split_call_center_operator_activities,
    user_name_map,
)
from pipelines.deals import (
    deal_get,
    deal_id_from_report_row,
    deal_url_from_id,
    resolve_deal_ids,
)
from pipelines.cleanup import cleanup_old_chrome_tmp_profiles, cleanup_old_outputs
from pipelines.evaluation import (
    apply_scores,
    compute_deal_quality,
    finalize_transcript_analysis,
    refresh_crm_scores_after_stage_metrics,
)
from pipelines.kpi import load_kpi_config
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reevaluation import reevaluate_report
from pipelines.reporting import (
    build_manager_summary,
    flatten_results,
    kpi_profile_display,
    prepare_report_rows,
    publish_latest_report,
)
from pipelines.retry import load_retry_scope, merge_retry_results
from pipelines.stages import safe_int
from pipelines.stage_history import (
    attach_stage_history_metrics,
    fetch_stage_history_by_deals,
    fetch_stage_name_map,
)
from pipelines.scoring import transcript_match_score
from pipelines.transcription import (
    _load_state_cache,
    _save_state_cache,
    _sha256_text,
    load_cached_transcript,
    transcribe_with_bitnewton,
)


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

    ok = 0
    err = 0
    ui_browser_session = None
    user_cache: Dict[int, Dict[str, Any]] = {}
    department_cache: Dict[int, Dict[str, Any]] = {}
    for di, deal_id in enumerate(deal_ids, 1):
        print(f"\nDEAL {di}/{len(deal_ids)}: {deal_url_from_id(args.domain, deal_id)}")
        acts_raw = list_deal_call_activities(api, deal_id)
        if args.include_call_center:
            acts = acts_raw
            call_center_acts: List[Dict[str, Any]] = []
        else:
            acts, call_center_acts = split_call_center_operator_activities(api, acts_raw, user_cache, department_cache)
        print(f"Звонков (crm.activity): {len(acts_raw)}")
        if call_center_acts:
            print(f"[SKIP] Звонков операторов Call-центра: {len(call_center_acts)}; к анализу: {len(acts)}", flush=True)

        if retry_scope is not None:
            retry_ids = retry_scope.get("activity_ids_by_deal", {}).get(str(deal_id), set())
            full_deal_retry = str(deal_id) in retry_scope.get("full_deals", set())
            if full_deal_retry:
                print("[RETRY] Ошибка была на уровне сделки, перепроверяю все звонки этой сделки", flush=True)
            else:
                before_retry = len(acts)
                acts = [a for a in acts if safe_int(a.get("ID")) in retry_ids]
                print(f"[RETRY] К повторной обработке звонков: {len(acts)} из {before_retry}", flush=True)

        max_calls_per_deal = max(0, int(getattr(args, "max_calls_per_deal", 0) or 0))
        if max_calls_per_deal and len(acts) > max_calls_per_deal:
            skipped_by_limit = len(acts) - max_calls_per_deal
            acts = acts[-max_calls_per_deal:]
            print(f"[FAST] Ограничение звонков по сделке: анализирую последние {len(acts)}, пропущено {skipped_by_limit}", flush=True)
        deal = deal_get(api, deal_id)
        comments = fetch_timeline_comments(api, deal_id)
        discipline = compute_discipline_metrics(deal, acts, kpi)
        deal_quality = compute_deal_quality(deal, comments, kpi)
        manager_id = safe_int(deal.get("ASSIGNED_BY_ID"))

        if not acts:
            row: Dict[str, Any] = {
                "deal_id": deal_id,
                "deal_url": deal_url_from_id(args.domain, deal_id),
                "stage_id": deal.get("STAGE_ID"),
                "manager_id": manager_id,
                "manager_name": None,
                "kpi_profile": (kpi.get("profile") or {}).get("name"),
                "kpi_version": (kpi.get("profile") or {}).get("version"),
                "kpi_profile_cmp": (kpi_cmp.get("profile") or {}).get("name") if kpi_cmp else None,
                "kpi_version_cmp": (kpi_cmp.get("profile") or {}).get("version") if kpi_cmp else None,
                "activity_id": None,
                "origin_id": None,
                "subject": "Звонков не найдено",
                "start_time": None,
                "end_time": None,
                "duration_minutes": None,
                "disk_file_id": None,
                "download_url": None,
                "audio_path": None,
                "bitnewton_task_id": None,
                "attach_result": None,
                "error": "По сделке не найдено звонков менеджера после исключения Call-центра" if call_center_acts else "По сделке не найдено звонков",
                "no_calls": True,
                "ignored_call_center_calls": len(call_center_acts),
            }
            row.update(discipline)
            row.update(deal_quality)
            apply_scores(row, deal, comments, "", kpi, suffix="")
            if kpi_cmp is not None:
                apply_scores(row, deal, comments, "", kpi_cmp, suffix="_cmp")
                row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)
            row["call_quality_conclusion"] = "Оценить разговор невозможно: по сделке не найдено звонков."
            row["recommendations"] = "Проверить, был ли контакт с клиентом вне телефонии Bitrix. Если звонка не было — запланировать касание и зафиксировать следующий шаг в CRM."
            results.append(row)
            err += 1
            print(f"[NO CALLS] OK={ok} ERR={err}", flush=True)
            continue

        for ai, act in enumerate(acts, 1):
            row: Dict[str, Any] = {
                "deal_id": deal_id,
                "deal_url": deal_url_from_id(args.domain, deal_id),
                "stage_id": deal.get("STAGE_ID"),
                "manager_id": manager_id,
                "manager_name": None,
                "kpi_profile": (kpi.get("profile") or {}).get("name"),
                "kpi_version": (kpi.get("profile") or {}).get("version"),
                "kpi_profile_cmp": (kpi_cmp.get("profile") or {}).get("name") if kpi_cmp else None,
                "kpi_version_cmp": (kpi_cmp.get("profile") or {}).get("version") if kpi_cmp else None,
                "activity_id": act.get("ID"),
                "origin_id": act.get("ORIGIN_ID"),
                "subject": act.get("SUBJECT"),
                "start_time": act.get("START_TIME"),
                "end_time": act.get("END_TIME"),
                "duration_minutes": guess_duration_minutes(act),
                "disk_file_id": None,
                "download_url": None,
                "audio_path": None,
                "bitnewton_task_id": None,
                "attach_result": None,
                "error": None,
                "ignored_call_center_calls": len(call_center_acts),
            }
            row.update(discipline)
            row.update(deal_quality)

            try:
                call_id = str(row["origin_id"] or "")
                if not call_id:
                    raise RuntimeError("Нет ORIGIN_ID (CALL_ID) для резолва записи")

                if not bool(getattr(args, "no_reuse_transcripts", False)):
                    cached_text, cached_path = load_cached_transcript(state_cache, call_id, deal_id, row.get("activity_id"))
                    if cached_text and cached_path:
                        row["bitnewton_task_id"] = "cache"
                        row["transcript_path"] = str(cached_path)
                        row["transcript_text"] = cached_text
                        row["transcript_excerpt"] = cached_text[:1200]
                        row["transcript_hash"] = _sha256_text(cached_text)
                        row["bitrix_card_transcript_status"] = "Не запрашивалась: использована сохранённая расшифровка"
                        finalize_transcript_analysis(row, deal, comments, cached_text, "", kpi, kpi_cmp)
                        if args.force_attach:
                            act_full = activity_get(api, int(act.get("ID"))) if act.get("ID") else act
                            attach = attach_transcription_to_bitrix(api, call_id=call_id, transcript_text=cached_text, duration=guess_duration_sec(act_full))
                            row["attach_result"] = attach
                        else:
                            row["attach_result"] = {"skipped": True, "reason": "cached_transcript_reused"}
                        state_cache[call_id] = {
                            "hash": row["transcript_hash"],
                            "transcript_path": str(cached_path),
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "deal_id": deal_id,
                            "activity_id": row.get("activity_id"),
                            "source": "cache",
                        }
                        _save_state_cache(state_cache)
                        ok += 1
                        print(f"[CACHE] Использую сохранённую расшифровку: activity_id={row.get('activity_id')}", flush=True)
                        continue

                out_path, ui_browser_session = download_audio_for_call(
                    api=api,
                    args=args,
                    row=row,
                    deal_id=deal_id,
                    activity=act,
                    call_id=call_id,
                    audio_source_index=audio_source_index,
                    audio_dir=audio_dir,
                    ui_audio_dir=ui_audio_dir,
                    ui_browser_session=ui_browser_session,
                )

                # ASR
                text, task_id, transcript_path = transcribe_with_bitnewton(
                    asr=asr,
                    audio_path=out_path,
                    deal_id=deal_id,
                    activity_id=row.get("activity_id"),
                    diarize=bool(args.diarize),
                )
                row["bitnewton_task_id"] = task_id
                row["transcript_path"] = str(transcript_path)
                row["transcript_text"] = text or ""
                row["transcript_excerpt"] = (text or "")[:1200]
                bitrix_text = ""
                if args.fetch_bitrix_card_transcript and args.ui_download:
                    try:
                        from ui_audio_downloader import UiBrowserSession

                        browser = str(getattr(args, "ui_browser", "chrome"))
                        ui_timeout_sec = max(5, int(getattr(args, "ui_timeout_sec", 20) or 20))
                        browser_profile_directory = str(getattr(args, "browser_profile_directory", "Default") or "Default")
                        if ui_browser_session is None:
                            ui_browser_session = UiBrowserSession(
                                downloads_dir=ui_audio_dir,
                                chrome_profile_dir=args.chrome_profile_dir,
                                browser=browser,
                                browser_profile_directory=browser_profile_directory,
                            )
                        print(f"[UI] Пробую прочитать расшифровку из карточки Bitrix: activity_id={row.get('activity_id')}", flush=True)
                        tr_res = ui_browser_session.fetch_transcript_from_deal_timeline(
                            row["deal_url"],
                            int(row.get("activity_id") or 0),
                            timeout_sec=ui_timeout_sec,
                        )
                        if tr_res.ok and tr_res.text:
                            bitrix_text = tr_res.text
                            row["bitrix_card_transcript"] = bitrix_text
                            row["bitrix_card_transcript_status"] = "Получена"
                            row["transcript_match_score"] = transcript_match_score(text or "", bitrix_text)
                        else:
                            row["bitrix_card_transcript_status"] = tr_res.error or "Расшифровка Bitrix не найдена"
                    except Exception as e:
                        row["bitrix_card_transcript_status"] = f"Не удалось прочитать расшифровку Bitrix: {e}"
                else:
                    row["bitrix_card_transcript_status"] = "Не запрашивалась"

                finalize_transcript_analysis(row, deal, comments, text or "", bitrix_text, kpi, kpi_cmp)

                # attach (idempotent via cache)
                txt_hash = _sha256_text(text or "")
                row["transcript_hash"] = txt_hash
                cached = (state_cache.get(call_id) or {}) if isinstance(state_cache.get(call_id), dict) else None
                if (not args.force_attach) and cached and cached.get("hash") == txt_hash:
                    row["attach_result"] = {"skipped": True, "reason": "state_cache_same_hash"}
                else:
                    act_full = activity_get(api, int(act.get("ID"))) if act.get("ID") else act
                    attach = attach_transcription_to_bitrix(api, call_id=call_id, transcript_text=text, duration=guess_duration_sec(act_full))
                    row["attach_result"] = attach
                state_cache[call_id] = {
                    "hash": txt_hash,
                    "transcript_path": str(transcript_path),
                    "bitnewton_task_id": task_id,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "deal_id": deal_id,
                    "activity_id": row.get("activity_id"),
                    "source": "bitnewton",
                }
                _save_state_cache(state_cache)
                ok += 1
            except (BitNewtonError, requests.RequestException, Exception) as e:
                row["error"] = str(e)
                err += 1
            finally:
                if row.get("audio_path") and not args.download_audio:
                    try:
                        Path(str(row["audio_path"])).unlink(missing_ok=True)  # type: ignore[call-arg]
                        row["audio_path"] = None
                    except Exception:
                        pass
                results.append(row)
                print(f"[{ai}/{len(acts)}] OK={ok} ERR={err}", flush=True)

    if ui_browser_session is not None:
        ui_browser_session.close()

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
    manager_summary_cmp = build_manager_summary(final_results, score_key="overall_score_cmp") if kpi_cmp is not None else None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_results = prepare_report_rows(final_results, stage_map=stage_map)
    json_out = REPORTS_DIR / f"bitnewton_sync_report_{ts}.json"
    json_out.write_text(json.dumps(report_results, ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(report_results, manager_summary, manager_summary_cmp=manager_summary_cmp, stage_map=stage_map)
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
