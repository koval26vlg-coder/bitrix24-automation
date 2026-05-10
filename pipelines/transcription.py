from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipelines.paths import REPORTS_DIR, TRANSCRIPTS_DIR


STATE_CACHE_PATH = REPORTS_DIR / "state_cache.json"


def _load_state_cache() -> Dict[str, Any]:
    try:
        if STATE_CACHE_PATH.exists():
            raw = json.loads(STATE_CACHE_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
    return {}


def _save_state_cache(cache: Dict[str, Any]) -> None:
    try:
        STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()


def save_transcript_file(deal_id: str, activity_id: Any, task_id: str, text: str) -> Path:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_task = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(task_id or ""))[:36] or "no_task"
    safe_deal = re.sub(r"\D+", "", str(deal_id or "")) or "unknown_deal"
    safe_activity = re.sub(r"\D+", "", str(activity_id or "")) or "unknown_activity"
    path = TRANSCRIPTS_DIR / f"deal{safe_deal}_activity{safe_activity}_{safe_task}.txt"
    path.write_text(text or "", encoding="utf-8")
    return path


def find_latest_transcript_file(deal_id: Any, activity_id: Any) -> Optional[Path]:
    safe_deal = re.sub(r"\D+", "", str(deal_id or ""))
    safe_activity = re.sub(r"\D+", "", str(activity_id or ""))
    if not safe_deal or not safe_activity or not TRANSCRIPTS_DIR.exists():
        return None
    pattern = f"deal{safe_deal}_activity{safe_activity}_*.txt"
    files = sorted(TRANSCRIPTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[0] if files else None


def load_cached_transcript(
    state_cache: Dict[str, Any],
    call_id: str,
    deal_id: Any,
    activity_id: Any,
) -> Tuple[Optional[str], Optional[Path]]:
    candidates: List[Path] = []
    cached = state_cache.get(call_id)
    if isinstance(cached, dict):
        cached_path = cached.get("transcript_path")
        if cached_path:
            candidates.append(Path(str(cached_path)))
    latest = find_latest_transcript_file(deal_id, activity_id)
    if latest:
        candidates.append(latest)

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.stat().st_size > 0:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
                if text:
                    return text, path
        except Exception:
            continue
    return None, None


def transcribe_with_bitnewton(
    *,
    asr: Any,
    audio_path: Path,
    deal_id: Any,
    activity_id: Any,
    diarize: bool,
) -> Tuple[str, str, Path]:
    task = asr.start_transcribing(str(audio_path), diarize=bool(diarize), remove_timestamps=True)
    text = asr.wait_and_get_text(task.task_id, timeout_sec=1800) or ""
    transcript_path = save_transcript_file(
        deal_id=str(deal_id),
        activity_id=activity_id,
        task_id=task.task_id,
        text=text,
    )
    return text, task.task_id, transcript_path
