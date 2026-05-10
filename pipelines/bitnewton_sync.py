from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from asr.bitnewton import BitNewtonError, env_bitnewton_asr
from bitrix.api import Bitrix24API
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
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reporting import (
    build_manager_summary,
    flatten_results,
    kpi_profile_display,
    prepare_report_rows,
    publish_latest_report,
)
from pipelines.stages import safe_int
from pipelines.stage_history import (
    attach_stage_history_metrics,
    fetch_stage_history_by_deals,
    fetch_stage_name_map,
)
from pipelines.scoring import (
    HANDLING_RE,
    OBJECTION_RULES,
    _context,
    call_quality_conclusion,
    conversation_meaning,
    evaluate_call_checklist,
    evaluate_crm_checklist,
    evaluate_call_text,
    merged_transcript_text,
    recalculate_overall_score,
    transcript_match_score,
)
from pipelines.transcription import (
    _load_state_cache,
    _save_state_cache,
    _sha256_text,
    load_cached_transcript,
    transcribe_with_bitnewton,
)


FIRST_RESPONSE_SLA_HOURS = 0.5
MAX_GAP_BETWEEN_CALLS_HOURS = 72.0
DEFAULT_KPI_CONFIG: Dict[str, Any] = {
    "profile": {"name": "default", "version": "1"},
    "sla": {"first_response_hours": 0.5, "max_gap_between_calls_hours": 72.0},
    "weights": {
        "overall": {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50},
        "discipline_split": {"first_response": 1.0, "cadence": 0.0},
        "crm_alignment_split": {"deal_quality": 0.6, "alignment": 0.4},
    },
    "deal_quality_weights": {"has_contact": 25, "has_amount": 25, "has_title": 25, "has_comments": 25},
    "call_quality_weights": {"greeting": 25, "needs_discovery": 30, "objection_work": 20, "next_step": 25},
    "alignment_weights": {"title_hit": 10, "title_hit_cap": 40, "amount_mentioned": 30, "next_step_synced": 30},
    "patterns": {
        "greeting": [r"\b(добрый|здравств\w*|привет)\b"],
        "needs_discovery": [r"\b(потребност\w*|задач\w*|нужно|необходим\w*|интересу\w*|уточн\w*|подскаж\w*|что нужно|что необходимо)\b"],
        "objection_work": [r"\b(дорог\w*|возраж\w*|сомнен\w*|не подходит|не смож\w*|не получится|нет возможности|подума\w*)\b"],
        "next_step": [r"\b(договор\w*|следующ\w*|перезвон\w*|отправ\w*|вышл\w*|встреч\w*|созвон\w*|уточн\w*|согласу\w*)\b"],
    },
}

STATE_CACHE_PATH = REPORTS_DIR / "state_cache.json"








def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bit.Newton: звонок → аудио → ASR → attachtranscription")
    parser.add_argument("--mode", choices=["single", "filter"], default=None)
    parser.add_argument("--deal-id", default=None, help="ID сделки (для mode=single)")
    parser.add_argument("--deal-url", default=None, help="URL сделки (для mode=single, если ID не задан)")
    parser.add_argument("--filter-json", default=None, help="Путь к JSON фильтру для crm.deal.list (для mode=filter)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--diarize", action="store_true", help="Bit.Newton diarize")
    parser.add_argument("--use-bitnewton", action="store_true", help="Включить Bit.Newton (нужен BITNEWTON_TOKEN)")
    parser.add_argument("--bitnewton-flow", action="store_true", help="Идти строго: call→audio→bitnewton→attach")
    parser.add_argument("--download-audio", action="store_true", help="Сохранять аудио в reports/audio/")
    parser.add_argument(
        "--audio-source-dir",
        action="append",
        default=[],
        help="Локальная папка с уже доступными аудиозаписями. Можно передать несколько раз или через ;",
    )
    parser.add_argument("--ui-download", action="store_true", help="Если REST-скачивание недоступно — попытаться скачать через Chrome (нужен логин в профиле)")
    parser.add_argument("--ui-browser", choices=["chrome", "edge"], default="chrome", help="Какой браузер использовать для UI-fallback (edge безопаснее для рабочего Chrome)")
    parser.add_argument("--ui-download-mode", choices=["direct", "timeline", "auto"], default="auto", help="UI способ: direct=точная CRM-ссылка записи, timeline=кнопка Скачать в таймлайне, auto=direct->timeline")
    parser.add_argument("--ui-timeout-sec", type=int, default=20, help="Сколько ждать обычное UI-скачивание; ручной вход в Bitrix ждём отдельно минимум 120 секунд")
    parser.add_argument("--rest-timeout-sec", type=int, default=20, help="Сколько ждать REST-скачивание одного URL записи")
    parser.add_argument("--ui-download-dir", default=None, help="Куда скачивать через UI (по умолчанию reports/audio_ui)")
    parser.add_argument("--browser-profile-directory", default="Default", help="Имя профиля браузера внутри User Data, например Default или Profile 1")
    parser.add_argument(
        "--chrome-profile-dir",
        default=None,
        help="Папка профиля Chrome для UI-скачивания. Можно указать 'system' чтобы использовать обычный профиль Chrome (LOCALAPPDATA/Google/Chrome/User Data).",
    )
    parser.add_argument("--domain", default=os.getenv("BITRIX24_DOMAIN", "online-kassa.bitrix24.ru"))
    parser.add_argument("--kpi-config", default=None, help="Путь к JSON с порогами/весами/паттернами оценки")
    parser.add_argument("--kpi-config-compare", default=None, help="Второй KPI JSON для сравнения в этом же отчёте")
    parser.add_argument("--force-attach", action="store_true", help="Всегда делать attachtranscription, игнорируя локальный state_cache")
    parser.add_argument("--no-reuse-transcripts", action="store_true", help="Не использовать ранее сохранённые расшифровки; заново скачивать аудио и отправлять в Bit.Newton")
    parser.add_argument("--retry-errors-from", default=None, help="JSON отчета, из которого нужно повторить только строки с ошибками")
    parser.add_argument("--reevaluate-from", default=None, help="JSON отчета, который нужно переоценить без скачивания аудио и Bit.Newton")
    parser.add_argument("--max-calls-per-deal", type=int, default=0, help="Ограничить количество звонков для анализа по каждой сделке; 0 = все")
    parser.add_argument("--include-call-center", action="store_true", help="Не исключать звонки операторов Call-центра из анализа")
    parser.add_argument("--fetch-bitrix-card-transcript", action="store_true", help="Пробовать читать расшифровку из карточки звонка Bitrix через UI и сопоставлять с Bit.Newton")
    parser.add_argument("--cleanup-output-days", type=int, default=30, help="Автоудаление отчетов, расшифровок и аудио старше N дней; 0 отключает")
    parser.add_argument("--cleanup-chrome-tmp-days", type=int, default=7, help="Удалять старые reports/chrome_profile_tmp_* (дней хранения)")
    return parser


def compute_deal_quality(deal: Dict[str, Any], comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    w = kpi.get("deal_quality_weights", {})
    has_contact = bool(deal.get("CONTACT_ID") or deal.get("COMPANY_ID"))
    has_amount = bool(str(deal.get("OPPORTUNITY") or "").strip() not in {"", "0", "0.00"})
    has_title = bool(str(deal.get("TITLE") or "").strip())
    has_next_step = bool(comments)
    score = 0
    score += int(w.get("has_contact", 25)) if has_contact else 0
    score += int(w.get("has_amount", 25)) if has_amount else 0
    score += int(w.get("has_title", 25)) if has_title else 0
    score += int(w.get("has_comments", 25)) if has_next_step else 0
    details = (
        f"Контакт/компания: {'да' if has_contact else 'нет'} ({int(w.get('has_contact', 25))} баллов); "
        f"сумма: {'да' if has_amount else 'нет'} ({int(w.get('has_amount', 25))} баллов); "
        f"название сделки: {'да' if has_title else 'нет'} ({int(w.get('has_title', 25))} баллов); "
        f"комментарии или следующий шаг в CRM: {'да' if has_next_step else 'нет'} ({int(w.get('has_comments', 25))} баллов)."
    )
    return {
        "deal_quality_score": score,
        "deal_quality_details": details,
        "has_contact": has_contact,
        "has_amount": has_amount,
        "has_title": has_title,
        "has_comments": has_next_step,
    }


def _match_any(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        try:
            if re.search(p, text):
                return True
        except re.error:
            continue
    return False



def crm_call_alignment(deal: Dict[str, Any], text: str, comments: List[str], kpi: Dict[str, Any]) -> Dict[str, Any]:
    w = kpi.get("alignment_weights", {})
    t = (text or "").lower()
    title_words = [w for w in re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", str(deal.get("TITLE") or "").lower())[:6]]
    title_hits = sum(1 for w in title_words if w in t)
    amount = str(deal.get("OPPORTUNITY") or "").split(".")[0]
    amount_mentioned = bool(amount and amount != "0" and amount in t)
    comments_text = " ".join(comments).lower()
    next_step_re = r"\b(перезвон\w*|встреч\w*|созвон\w*|отправ\w*|вышл\w*|уточн\w*|согласу\w*|кп|договор\w*)\b"
    next_step_synced = bool(re.search(next_step_re, t) and re.search(next_step_re, comments_text))
    amount_weight = int(w.get("amount_mentioned", 30))
    next_step_weight = int(w.get("next_step_synced", 40))
    raw_score = (amount_weight if amount_mentioned else 0) + (next_step_weight if next_step_synced else 0)
    total_weight = max(1, amount_weight + next_step_weight)
    align_score = round(raw_score * 100.0 / total_weight, 2)
    next_step_details = (
        "Да: следующий шаг звучит в разговоре и зафиксирован в комментариях/таймлайне CRM."
        if next_step_synced
        else "Нет: следующий шаг либо не прозвучал в разговоре, либо не зафиксирован в CRM. Это мешает контролировать дальнейшее действие по клиенту."
    )
    details = (
        "Связь звонка с CRM показывает, совпадает ли содержание разговора с данными сделки: "
        f"сумма упомянута: {'да' if amount_mentioned else 'нет'}; "
        f"следующий шаг синхронизирован с CRM: {'да' if next_step_synced else 'нет'}. "
        "Совпадения с названием сделки больше не выводятся в отчет как отдельная метрика."
    )
    return {
        "alignment_score": align_score,
        "alignment_details": details,
        "title_mentions": title_hits,
        "amount_mentioned": amount_mentioned,
        "next_step_synced": next_step_synced,
        "next_step_synced_details": next_step_details,
    }



def analyze_transcript_improvements(text: str, row: Dict[str, Any]) -> Dict[str, Any]:
    raw = text or ""
    lower = raw.lower()
    objections: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    for label, pattern, suggestion in OBJECTION_RULES:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            fragment = _context(raw, match.start(), match.end())
            key = (label, fragment[:160])
            if key in seen:
                continue
            seen.add(key)
            after = lower[match.end() : match.end() + 420]
            handled = bool(HANDLING_RE.search(after))
            objections.append(
                {
                    "objection_type": label,
                    "objection_fragment": fragment,
                    "objection_status": "отработано" if handled else "не отработано",
                    "objection_recommendation": suggestion,
                    "handled": handled,
                }
            )

    improvement_items: List[str] = []
    if not row.get("has_greeting"):
        improvement_items.append("Нет явного приветствия и представления.")
    if not row.get("has_needs_discovery"):
        improvement_items.append("Слабо выявлены потребности: не видно уточняющих вопросов о задаче клиента.")
    if not row.get("has_next_step_phrase"):
        improvement_items.append("Не зафиксирован конкретный следующий шаг.")

    unhandled = [o for o in objections if not o["handled"]]
    if unhandled:
        improvement_items.append("Есть неотработанные возражения: " + "; ".join(o["objection_type"] for o in unhandled[:5]) + ".")
    elif objections:
        improvement_items.append("Возражения найдены и в целом отработаны, но стоит фиксировать следующий шаг после ответа.")

    marked_lines: List[str] = []
    for objection in objections:
        status = objection["objection_status"]
        marker = "ТРЕБУЕТ ОТРАБОТКИ" if status == "не отработано" else "ОТРАБОТАНО"
        marked_lines.append(
            f"[ВОЗРАЖЕНИЕ: {objection['objection_type']} | {marker}]\n"
            f"{objection['objection_fragment']}\n"
            f"[ВАРИАНТ ОТРАБОТКИ] {objection['objection_recommendation']}"
        )

    if not marked_lines and improvement_items:
        marked_lines.append("[МОМЕНТЫ ДЛЯ УЛУЧШЕНИЯ]\n" + "\n".join(f"- {x}" for x in improvement_items))

    transcript_marked = raw
    if marked_lines:
        transcript_marked = "\n\n".join(marked_lines) + "\n\n[ПОЛНАЯ РАСШИФРОВКА]\n" + raw

    recommendations = [o["objection_recommendation"] for o in unhandled]
    if not recommendations and objections:
        recommendations = ["После ответа на возражение обязательно закрепить следующий шаг: дата, действие, ответственный."]

    return {
        "objections_count": len(objections),
        "unhandled_objections_count": len(unhandled),
        "objections_handled": bool(objections and not unhandled),
        "objections_found": "\n".join(
            f"{o['objection_type']}: {o['objection_fragment']} ({o['objection_status']})" for o in objections
        ),
        "unhandled_objections": "\n".join(f"{o['objection_type']}: {o['objection_fragment']}" for o in unhandled),
        "objection_recommendations": "\n".join(dict.fromkeys(recommendations)),
        "improvement_moments": "\n".join(improvement_items),
        "transcript_marked": transcript_marked,
        "objection_rows": objections,
    }


def finalize_transcript_analysis(
    row: Dict[str, Any],
    deal: Dict[str, Any],
    comments: List[Dict[str, Any]],
    bitnewton_text: str,
    bitrix_text: str,
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
) -> None:
    analysis_text = merged_transcript_text(bitnewton_text or "", bitrix_text or "")
    row["combined_transcript_text"] = analysis_text
    apply_scores(row, deal, comments, analysis_text, kpi, suffix="")
    if kpi_cmp is not None:
        apply_scores(row, deal, comments, analysis_text, kpi_cmp, suffix="_cmp")
        row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)
    row.update(analyze_transcript_improvements(analysis_text, row))
    call_conclusion, call_recommendations = call_quality_conclusion(row)
    row["call_quality_conclusion"] = call_conclusion
    row["recommendations"] = call_recommendations
    row["conversation_meaning"] = conversation_meaning(analysis_text, row)





def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate_kpi_config(kpi: Dict[str, Any]) -> None:
    if not isinstance(kpi, dict):
        raise RuntimeError("KPI config: должен быть объектом")
    prof = kpi.get("profile")
    if not isinstance(prof, dict) or not str(prof.get("name") or "").strip():
        raise RuntimeError("KPI config: profile.name обязателен (строка)")
    sla = kpi.get("sla")
    if not isinstance(sla, dict):
        raise RuntimeError("KPI config: sla должен быть объектом")
    fr = float(sla.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    mg = float(sla.get("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS))
    if fr <= 0 or mg <= 0:
        raise RuntimeError("KPI config: sla значения должны быть > 0")
    w = kpi.get("weights")
    if not isinstance(w, dict):
        raise RuntimeError("KPI config: weights должен быть объектом")
    overall = w.get("overall")
    if not isinstance(overall, dict):
        raise RuntimeError("KPI config: weights.overall должен быть объектом")
    s = float(overall.get("call_quality", 0)) + float(overall.get("discipline", 0)) + float(overall.get("crm_alignment", 0))
    if not (0.95 <= s <= 1.05):
        raise RuntimeError(f"KPI config: weights.overall должны суммироваться примерно в 1.0 (сейчас {s})")
    patterns = kpi.get("patterns")
    if patterns is not None:
        if not isinstance(patterns, dict):
            raise RuntimeError("KPI config: patterns должен быть объектом")
        for key, arr in patterns.items():
            if not isinstance(arr, list):
                raise RuntimeError(f"KPI config: patterns.{key} должен быть списком regex-строк")
            for p in arr:
                if not isinstance(p, str):
                    raise RuntimeError(f"KPI config: patterns.{key} содержит не строку")


def enforce_reaction_kpi(kpi: Dict[str, Any]) -> Dict[str, Any]:
    """
    Единая итоговая оценка: разговор + ведение CRM. Скорость реакции не влияет на итог.
    """
    sla = kpi.setdefault("sla", {})
    if isinstance(sla, dict):
        sla["first_response_hours"] = FIRST_RESPONSE_SLA_HOURS
        sla.setdefault("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS)
    weights = kpi.setdefault("weights", {})
    if isinstance(weights, dict):
        weights["overall"] = {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50}
        weights["discipline_split"] = {"first_response": 1.0, "cadence": 0.0}
    return kpi


def load_kpi_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_KPI_CONFIG)
    if not path:
        cfg = enforce_reaction_kpi(cfg)
        validate_kpi_config(cfg)
        return cfg
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("--kpi-config должен содержать JSON-объект")
    merged = _deep_merge(cfg, raw)
    if isinstance(merged.get("profile"), dict):
        merged["profile"].setdefault("name", Path(path).name)
        merged["profile"].setdefault("version", "1")
    else:
        merged["profile"] = {"name": Path(path).name, "version": "1"}
    merged = enforce_reaction_kpi(merged)
    validate_kpi_config(merged)
    return merged


def load_report_json(path: str | Path) -> List[Dict[str, Any]]:
    report_path = Path(path)
    if not report_path.exists():
        raise SystemExit(f"Отчет не найден: {report_path}")
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"Ожидался JSON-список строк отчета: {report_path}")
    return [r for r in raw if isinstance(r, dict)]


def load_retry_scope(path: str | Path) -> Dict[str, Any]:
    rows = load_report_json(path)
    deal_ids: List[str] = []
    activity_ids_by_deal: Dict[str, set[int]] = {}
    full_deals: set[str] = set()
    errors = 0
    seen_deals: set[str] = set()

    for row in rows:
        if not row.get("error"):
            continue
        deal_id = deal_id_from_report_row(row)
        if not deal_id:
            continue
        errors += 1
        if deal_id not in seen_deals:
            seen_deals.add(deal_id)
            deal_ids.append(deal_id)
        activity_id = safe_int(row.get("activity_id"))
        if activity_id is None:
            full_deals.add(deal_id)
        else:
            activity_ids_by_deal.setdefault(deal_id, set()).add(activity_id)

    return {
        "deal_ids": deal_ids,
        "activity_ids_by_deal": activity_ids_by_deal,
        "full_deals": full_deals,
        "errors": errors,
        "source_rows": rows,
        "source_path": str(path),
    }


def _report_row_identity(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    return deal_id_from_report_row(row), safe_int(row.get("activity_id"))


def merge_retry_results(
    original_rows: List[Dict[str, Any]],
    retry_rows: List[Dict[str, Any]],
    retry_scope: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Повтор ошибок должен обновлять полный отчет, а не заменять его маленьким отчетом
    только по ошибочным строкам.
    """
    full_deals = set(str(x) for x in (retry_scope.get("full_deals") or set()))
    retry_activity_ids_by_deal = retry_scope.get("activity_ids_by_deal") or {}

    retry_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    retry_by_activity: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in retry_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            continue
        retry_by_deal.setdefault(deal_id, []).append(row)
        if activity_id is not None:
            retry_by_activity.setdefault((deal_id, activity_id), []).append(row)

    merged: List[Dict[str, Any]] = []
    inserted_full_deals: set[str] = set()
    inserted_activities: set[Tuple[str, int]] = set()
    inserted_fallback_deals: set[str] = set()

    for row in original_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue

        if deal_id in full_deals:
            if deal_id not in inserted_full_deals:
                replacements = retry_by_deal.get(deal_id)
                merged.extend(replacements if replacements else [row])
                inserted_full_deals.add(deal_id)
            continue

        target_activities = retry_activity_ids_by_deal.get(deal_id, set())
        if activity_id is not None and activity_id in target_activities:
            key = (deal_id, activity_id)
            if key not in inserted_activities:
                replacements = retry_by_activity.get(key)
                if replacements:
                    merged.extend(replacements)
                elif deal_id not in inserted_fallback_deals:
                    fallback = [r for r in retry_by_deal.get(deal_id, []) if safe_int(r.get("activity_id")) is None]
                    merged.extend(fallback if fallback else [row])
                    inserted_fallback_deals.add(deal_id)
                else:
                    merged.append(row)
                inserted_activities.add(key)
            continue

        merged.append(row)

    existing_object_ids = {id(row) for row in merged}
    for row in retry_rows:
        if id(row) in existing_object_ids:
            continue
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue
        if deal_id in full_deals and deal_id in inserted_full_deals:
            continue
        if activity_id is not None and (deal_id, activity_id) in inserted_activities:
            continue
        merged.append(row)

    return merged


def cleanup_old_chrome_tmp_profiles(base_dir: Path, keep_days: int = 7) -> int:
    try:
        if keep_days <= 0:
            return 0
        now = time.time()
        removed = 0
        for p in base_dir.glob("chrome_profile_tmp_*"):
            try:
                age_days = (now - p.stat().st_mtime) / (3600 * 24)
                if age_days < keep_days:
                    continue
                for sub in sorted(p.rglob("*"), reverse=True):
                    try:
                        if sub.is_file() or sub.is_symlink():
                            sub.unlink(missing_ok=True)  # type: ignore[call-arg]
                        else:
                            sub.rmdir()
                    except Exception:
                        pass
                try:
                    p.rmdir()
                except Exception:
                    pass
                removed += 1
            except Exception:
                continue
        return removed
    except Exception:
        return 0


def cleanup_old_outputs(base_dir: Path, keep_days: int = 30, extra_audio_dirs: Optional[List[Path]] = None) -> Dict[str, int]:
    counts = {"reports": 0, "audio": 0, "transcripts": 0, "total": 0}
    try:
        if keep_days <= 0:
            return counts
        base_dir = Path(base_dir)
        cutoff = time.time() - (float(keep_days) * 24 * 3600)

        def remove_file(path: Path, bucket: str) -> None:
            try:
                if not path.exists() or path.is_dir():
                    return
                if path.stat().st_mtime >= cutoff:
                    return
                path.unlink(missing_ok=True)  # type: ignore[call-arg]
                counts[bucket] = counts.get(bucket, 0) + 1
                counts["total"] += 1
            except Exception:
                return

        for pattern in ("bitnewton_sync_report_*.json", "bitnewton_sync_report_*.xlsx"):
            for path in base_dir.glob(pattern):
                remove_file(path, "reports")

        cleanup_dirs: List[Tuple[Path, str]] = [
            (base_dir / "audio", "audio"),
            (base_dir / "audio_ui", "audio"),
            (base_dir / "transcripts", "transcripts"),
        ]
        for extra in extra_audio_dirs or []:
            extra_path = Path(extra)
            if extra_path not in [p for p, _ in cleanup_dirs]:
                cleanup_dirs.append((extra_path, "audio"))

        for folder, bucket in cleanup_dirs:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                remove_file(path, bucket)
            for path in sorted(folder.rglob("*"), reverse=True):
                try:
                    if path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                except Exception:
                    continue
        return counts
    except Exception:
        return counts


def apply_scores(row: Dict[str, Any], deal: Dict[str, Any], comments: List[str], text: str, kpi: Dict[str, Any], suffix: str = "") -> None:
    first_h = row.get("first_response_hours")
    first_m = row.get("first_response_minutes")
    sla_cfg = kpi.get("sla", {})
    first_response_sla = float(sla_cfg.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    if first_h is None and first_m is not None:
        first_h = float(first_m) / 60.0
    row[f"first_response_sla_ok{suffix}"] = (first_h is not None and float(first_h) <= first_response_sla)

    deal_q = compute_deal_quality(deal, comments, kpi)
    call_q = evaluate_call_text(text, kpi)
    align = crm_call_alignment(deal, text, comments, kpi)
    for k, v in deal_q.items():
        row[f"{k}{suffix}"] = v
    for k, v in call_q.items():
        row[f"{k}{suffix}"] = v
    for k, v in align.items():
        row[f"{k}{suffix}"] = v

    crm_q = evaluate_crm_checklist(row, suffix=suffix, include_stage=False)
    for k, v in crm_q.items():
        if suffix and k in {"crm_checklist_items"}:
            continue
        row[f"{k}{suffix}"] = v

    recalculate_overall_score(row, kpi, suffix=suffix)


def refresh_crm_scores_after_stage_metrics(rows: List[Dict[str, Any]], kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]] = None) -> None:
    for row in rows:
        crm_q = evaluate_crm_checklist(row, include_stage=True)
        row.update(crm_q)
        recalculate_overall_score(row, kpi, suffix="")
        if kpi_cmp is not None:
            row["crm_work_score_cmp"] = crm_q.get("crm_work_score")
            row["crm_checklist_percent_cmp"] = crm_q.get("crm_checklist_percent")
            recalculate_overall_score(row, kpi_cmp, suffix="_cmp")
            row["overall_score_delta"] = round(float(row.get("overall_score_cmp") or 0) - float(row.get("overall_score") or 0), 2)


def recompute_existing_row(row: Dict[str, Any], kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = dict(row)
    r["kpi_profile"] = (kpi.get("profile") or {}).get("name")
    r["kpi_version"] = (kpi.get("profile") or {}).get("version")
    if kpi_cmp is not None:
        r["kpi_profile_cmp"] = (kpi_cmp.get("profile") or {}).get("name")
        r["kpi_version_cmp"] = (kpi_cmp.get("profile") or {}).get("version")

    text = str(r.get("combined_transcript_text") or r.get("transcript_text") or "").strip()
    if not text and r.get("transcript_path"):
        try:
            p = Path(str(r.get("transcript_path")))
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            text = ""
    bitrix_text = str(r.get("bitrix_card_transcript") or "").strip()
    analysis_text = merged_transcript_text(text, bitrix_text)
    r["combined_transcript_text"] = analysis_text
    if text and not r.get("transcript_text"):
        r["transcript_text"] = text

    if not analysis_text:
        r["call_quality_score"] = 0.0
        r["call_quality_details"] = "Качество разговора не рассчитано: нет сохраненной расшифровки."
        r.update(evaluate_crm_checklist(r, include_stage=True))
        recalculate_overall_score(r, kpi)
        return r

    for k, v in evaluate_call_text(analysis_text, kpi).items():
        r[k] = v

    r.update(evaluate_crm_checklist(r, include_stage=True))
    recalculate_overall_score(r, kpi)

    r.update(analyze_transcript_improvements(analysis_text, r))
    call_conclusion, call_recommendations = call_quality_conclusion(r)
    r["call_quality_conclusion"] = call_conclusion
    r["recommendations"] = call_recommendations
    r["conversation_meaning"] = conversation_meaning(analysis_text, r)

    if kpi_cmp is not None:
        tmp = recompute_existing_row({**r, "overall_score": None}, kpi_cmp, None)
        for key in ["call_quality_score", "deal_quality_score", "alignment_score", "crm_work_score", "overall_score"]:
            if key in tmp:
                r[f"{key}_cmp"] = tmp.get(key)
        r["overall_score_delta"] = round(float(r.get("overall_score_cmp") or 0.0) - float(r.get("overall_score") or 0.0), 2)

    return r


def reevaluate_report(args: argparse.Namespace, kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]]) -> Tuple[int, Path, Path]:
    rows = load_report_json(args.reevaluate_from)
    recalculated = [recompute_existing_row(row, kpi, kpi_cmp) for row in rows]
    manager_summary = build_manager_summary(recalculated)
    manager_summary_cmp = build_manager_summary(recalculated, score_key="overall_score_cmp") if kpi_cmp is not None else None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_out = REPORTS_DIR / f"bitnewton_reevaluated_report_{ts}.json"
    json_out.write_text(json.dumps(prepare_report_rows(recalculated), ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(recalculated, manager_summary, manager_summary_cmp=manager_summary_cmp)
    publish_latest_report(json_out, xlsx_out)
    print(f"[OK] Переоценено строк без повторной расшифровки: {len(recalculated)}")
    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    print(f"ИТОГО: OK={len(recalculated)} ERR=0")
    return len(recalculated), json_out, xlsx_out


def attach_transcription_to_bitrix(api: Bitrix24API, call_id: str, transcript_text: str, duration: int) -> Dict[str, Any]:
    text = (transcript_text or "").strip()
    if not text:
        raise RuntimeError("Пустая расшифровка (transcript_text)")
    duration = int(duration or 60)
    duration = max(1, duration)
    msg = {"SIDE": "User", "MESSAGE": text, "START_TIME": 0, "STOP_TIME": duration}

    variants = [str(call_id or "").strip()]
    if variants[0].startswith("VI_"):
        variants.append(variants[0][3:])

    seen = set()
    errors: List[str] = []
    for cid in variants:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            res = api.call("telephony.call.attachTranscription", {"CALL_ID": cid, "MESSAGES": [msg]}).get("result", {}) or {}
            return {"call_id_used": cid, "result": res}
        except Exception as e:
            errors.append(f"{cid}: {e}")

    raise RuntimeError("Не удалось прикрепить расшифровку в Bitrix: " + " | ".join(errors))


def run_sync(args: argparse.Namespace) -> Tuple[int, Path, Path]:
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
