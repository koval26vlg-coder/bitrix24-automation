from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asr.bitnewton import BitNewtonAuthError
from bitrix.transcriptions import attach_transcription_to_bitrix
from pipelines.audio import download_audio_for_call
from pipelines.calls import activity_get, guess_duration_minutes, guess_duration_sec
from pipelines.deals import deal_url_from_id
from pipelines.evaluation import apply_scores, finalize_transcript_analysis
from pipelines.processing.context import ProcessingContext
from pipelines.scoring import transcript_match_score
from pipelines.transcription import (
    _save_state_cache,
    _sha256_text,
    load_cached_transcript,
    transcribe_with_bitnewton,
)


def process_no_calls_deal(
    *,
    args: Any,
    deal_id: str,
    deal: Dict[str, Any],
    comments: List[str],
    discipline: Dict[str, Any],
    deal_quality: Dict[str, Any],
    manager_id: Optional[int],
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
    call_center_acts: List[Dict[str, Any]],
    skipped_short_calls: int = 0,
) -> Dict[str, Any]:
    error = (
        "По сделке не найдено звонков менеджера после исключения Call-центра"
        if call_center_acts
        else "По сделке не найдено звонков"
    )
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
        "error": error,
        "no_calls": True,
        "ignored_call_center_calls": len(call_center_acts),
        "skipped_short_calls": int(skipped_short_calls or 0),
    }
    row.update(discipline)
    row.update(deal_quality)
    apply_scores(row, deal, comments, "", kpi, suffix="")
    if kpi_cmp is not None:
        apply_scores(row, deal, comments, "", kpi_cmp, suffix="_cmp")
        row["overall_score_delta"] = round(
            float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0),
            2,
        )
    row["call_quality_conclusion"] = "Оценить разговор невозможно: по сделке не найдено звонков."
    row["recommendations"] = (
        "Проверить, был ли контакт с клиентом вне телефонии Bitrix. "
        "Если звонка не было — запланировать касание и зафиксировать следующий шаг в CRM."
    )
    return row


def _build_call_row(
    *,
    args: Any,
    deal_id: str,
    deal: Dict[str, Any],
    activity: Dict[str, Any],
    discipline: Dict[str, Any],
    deal_quality: Dict[str, Any],
    manager_id: Optional[int],
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
    call_center_acts: List[Dict[str, Any]],
    skipped_short_calls: int = 0,
) -> Dict[str, Any]:
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
        "activity_id": activity.get("ID"),
        "origin_id": activity.get("ORIGIN_ID"),
        "subject": activity.get("SUBJECT"),
        "start_time": activity.get("START_TIME"),
        "end_time": activity.get("END_TIME"),
        "duration_minutes": guess_duration_minutes(activity),
        "disk_file_id": None,
        "download_url": None,
        "audio_path": None,
        "bitnewton_task_id": None,
        "attach_result": None,
        "error": None,
        "ignored_call_center_calls": len(call_center_acts),
        "skipped_short_calls": int(skipped_short_calls or 0),
    }
    row.update(discipline)
    row.update(deal_quality)
    return row


def _fetch_bitrix_card_transcript(ctx: ProcessingContext, row: Dict[str, Any], text: str) -> str:
    args = ctx.args
    bitrix_text = ""
    if args.fetch_bitrix_card_transcript and args.ui_download:
        try:
            from ui_audio_downloader import UiBrowserSession

            browser = str(getattr(args, "ui_browser", "chrome"))
            ui_timeout_sec = max(5, int(getattr(args, "ui_timeout_sec", 20) or 20))
            browser_profile_directory = str(getattr(args, "browser_profile_directory", "Default") or "Default")
            if ctx.ui_browser_session is None:
                ctx.ui_browser_session = UiBrowserSession(
                    downloads_dir=ctx.ui_audio_dir,
                    chrome_profile_dir=args.chrome_profile_dir,
                    browser=browser,
                    browser_profile_directory=browser_profile_directory,
                )
            print(
                f"[UI] Пробую прочитать расшифровку из карточки Bitrix: activity_id={row.get('activity_id')}",
                flush=True,
            )
            tr_res = ctx.ui_browser_session.fetch_transcript_from_deal_timeline(
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
    return bitrix_text


def _mark_asr_skipped(
    *,
    ctx: ProcessingContext,
    row: Dict[str, Any],
    deal: Dict[str, Any],
    comments: List[str],
    reason: str,
) -> Tuple[Dict[str, Any], bool]:
    row["asr_skipped"] = True
    row["asr_status"] = f"ASR пропущена: {reason}"
    row["bitnewton_task_id"] = "skipped_asr"
    row["transcript_text"] = ""
    row["transcript_excerpt"] = ""
    row["bitrix_card_transcript_status"] = "Не запрашивалась: ASR пропущена"
    row["combined_transcript_text"] = ""
    apply_scores(row, deal, comments, "", ctx.kpi, suffix="")
    if ctx.kpi_cmp is not None:
        apply_scores(row, deal, comments, "", ctx.kpi_cmp, suffix="_cmp")
        row["overall_score_delta"] = round(
            float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0),
            2,
        )
    row["call_quality_score"] = 0.0
    row["call_quality_details"] = "Качество разговора не рассчитано: Bit.Newton недоступен, расшифровки нет."
    row["call_quality_conclusion"] = "Разговор не оценен: новая ASR-расшифровка пропущена из-за проблемы с Bit.Newton."
    row["conversation_meaning"] = "Нет расшифровки: можно оценить только CRM-часть и движение сделки."
    row["recommendations"] = "Обновить BITNEWTON_TOKEN и запустить режим «Повторить только ошибки» или обычную обработку с кэшем."
    return row, True


def process_call(
    *,
    ctx: ProcessingContext,
    deal_id: str,
    deal: Dict[str, Any],
    comments: List[str],
    discipline: Dict[str, Any],
    deal_quality: Dict[str, Any],
    manager_id: Optional[int],
    call_center_acts: List[Dict[str, Any]],
    activity: Dict[str, Any],
    skipped_short_calls: int = 0,
) -> Tuple[Dict[str, Any], bool]:
    row = _build_call_row(
        args=ctx.args,
        deal_id=deal_id,
        deal=deal,
        activity=activity,
        discipline=discipline,
        deal_quality=deal_quality,
        manager_id=manager_id,
        kpi=ctx.kpi,
        kpi_cmp=ctx.kpi_cmp,
        call_center_acts=call_center_acts,
        skipped_short_calls=skipped_short_calls,
    )

    try:
        call_id = str(row["origin_id"] or "")
        if not call_id:
            raise RuntimeError("Нет ORIGIN_ID (CALL_ID) для резолва записи")

        if not bool(getattr(ctx.args, "no_reuse_transcripts", False)):
            cached_text, cached_path = load_cached_transcript(ctx.state_cache, call_id, deal_id, row.get("activity_id"))
            if cached_text and cached_path:
                row["bitnewton_task_id"] = "cache"
                row["transcript_path"] = str(cached_path)
                row["transcript_text"] = cached_text
                row["transcript_excerpt"] = cached_text[:1200]
                row["transcript_hash"] = _sha256_text(cached_text)
                row["bitrix_card_transcript_status"] = "Не запрашивалась: использована сохранённая расшифровка"
                finalize_transcript_analysis(row, deal, comments, cached_text, "", ctx.kpi, ctx.kpi_cmp)
                if ctx.args.force_attach:
                    act_full = activity_get(ctx.api, int(activity.get("ID"))) if activity.get("ID") else activity
                    attach = attach_transcription_to_bitrix(
                        ctx.api,
                        call_id=call_id,
                        transcript_text=cached_text,
                        duration=guess_duration_sec(act_full),
                    )
                    row["attach_result"] = attach
                else:
                    row["attach_result"] = {"skipped": True, "reason": "cached_transcript_reused"}
                ctx.state_cache[call_id] = {
                    "hash": row["transcript_hash"],
                    "transcript_path": str(cached_path),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "deal_id": deal_id,
                    "activity_id": row.get("activity_id"),
                    "source": "cache",
                }
                _save_state_cache(ctx.state_cache)
                print(f"[CACHE] Использую сохранённую расшифровку: activity_id={row.get('activity_id')}", flush=True)
                return row, True

        if ctx.asr_disabled_reason:
            return _mark_asr_skipped(
                ctx=ctx,
                row=row,
                deal=deal,
                comments=comments,
                reason=str(ctx.asr_disabled_reason),
            )

        out_path, ctx.ui_browser_session = download_audio_for_call(
            api=ctx.api,
            args=ctx.args,
            row=row,
            deal_id=deal_id,
            activity=activity,
            call_id=call_id,
            audio_source_index=ctx.audio_source_index,
            audio_dir=ctx.audio_dir,
            ui_audio_dir=ctx.ui_audio_dir,
            ui_browser_session=ctx.ui_browser_session,
        )

        text, task_id, transcript_path = transcribe_with_bitnewton(
            asr=ctx.asr,
            audio_path=out_path,
            deal_id=deal_id,
            activity_id=row.get("activity_id"),
            diarize=bool(ctx.args.diarize),
        )
        row["bitnewton_task_id"] = task_id
        row["transcript_path"] = str(transcript_path)
        row["transcript_text"] = text or ""
        row["transcript_excerpt"] = (text or "")[:1200]
        bitrix_text = _fetch_bitrix_card_transcript(ctx, row, text)

        finalize_transcript_analysis(row, deal, comments, text or "", bitrix_text, ctx.kpi, ctx.kpi_cmp)

        txt_hash = _sha256_text(text or "")
        row["transcript_hash"] = txt_hash
        cached = (ctx.state_cache.get(call_id) or {}) if isinstance(ctx.state_cache.get(call_id), dict) else None
        if (not ctx.args.force_attach) and cached and cached.get("hash") == txt_hash:
            row["attach_result"] = {"skipped": True, "reason": "state_cache_same_hash"}
        else:
            act_full = activity_get(ctx.api, int(activity.get("ID"))) if activity.get("ID") else activity
            attach = attach_transcription_to_bitrix(
                ctx.api,
                call_id=call_id,
                transcript_text=text,
                duration=guess_duration_sec(act_full),
            )
            row["attach_result"] = attach
        ctx.state_cache[call_id] = {
            "hash": txt_hash,
            "transcript_path": str(transcript_path),
            "bitnewton_task_id": task_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "deal_id": deal_id,
            "activity_id": row.get("activity_id"),
            "source": "bitnewton",
        }
        _save_state_cache(ctx.state_cache)
        return row, True
    except BitNewtonAuthError as e:
        ctx.asr_disabled_reason = str(e)
        return _mark_asr_skipped(ctx=ctx, row=row, deal=deal, comments=comments, reason=str(e))
    except Exception as e:
        row["error"] = str(e)
        return row, False
    finally:
        if row.get("audio_path") and not ctx.args.download_audio:
            try:
                Path(str(row["audio_path"])).unlink(missing_ok=True)  # type: ignore[call-arg]
                row["audio_path"] = None
            except Exception:
                pass
