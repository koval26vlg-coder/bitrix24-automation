from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipelines.deals import deal_id_from_report_row
from pipelines.paths import BITNEWTON_RETRY_QUEUE_PATH
from pipelines.stages import safe_int


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_retry_key(
    *, call_id: str | None, deal_id: str | None, activity_id: int | None
) -> str | None:
    call = str(call_id or "").strip()
    if call:
        return f"call:{call}"
    deal = str(deal_id or "").strip()
    if not deal:
        return None
    aid = activity_id if activity_id is not None else 0
    return f"deal:{deal}:activity:{aid}"


def _normalize_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    deal_id = deal_id_from_report_row(raw) or str(raw.get("deal_id") or "").strip()
    if not deal_id:
        return None
    activity_id = safe_int(raw.get("activity_id"))
    origin_id = str(raw.get("origin_id") or raw.get("call_id") or "").strip()
    return {
        "deal_id": deal_id,
        "deal_url": raw.get("deal_url"),
        "activity_id": activity_id,
        "origin_id": origin_id,
        "subject": raw.get("subject"),
        "error": str(raw.get("error") or "").strip(),
        "retry_reason": str(raw.get("retry_reason") or "bitnewton_unavailable"),
        "retry_attempts": max(1, int(raw.get("retry_attempts") or 1)),
        "queued_at": str(raw.get("queued_at") or _now_iso()),
        "last_error_at": str(raw.get("last_error_at") or _now_iso()),
    }


def load_bitnewton_retry_queue(
    path: Path | str = BITNEWTON_RETRY_QUEUE_PATH,
) -> dict[str, dict[str, Any]]:
    queue_path = Path(path)
    if not queue_path.exists():
        return {}

    try:
        raw = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(raw, dict):
        items = raw.get("items")
        rows: list[dict[str, Any]] = items if isinstance(items, list) else []
    elif isinstance(raw, list):
        rows = [x for x in raw if isinstance(x, dict)]
    else:
        rows = []

    queue: dict[str, dict[str, Any]] = {}
    for item in rows:
        normalized = _normalize_entry(item)
        if normalized is None:
            continue
        key = build_retry_key(
            call_id=normalized.get("origin_id"),
            deal_id=normalized.get("deal_id"),
            activity_id=safe_int(normalized.get("activity_id")),
        )
        if not key:
            continue
        queue[key] = normalized
    return queue


def save_bitnewton_retry_queue(
    queue: dict[str, dict[str, Any]], path: Path | str = BITNEWTON_RETRY_QUEUE_PATH
) -> None:
    queue_path = Path(path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(queue.values())
    rows.sort(
        key=lambda r: (
            str(r.get("last_error_at") or ""),
            str(r.get("deal_id") or ""),
            int(safe_int(r.get("activity_id")) or 0),
        )
    )
    queue_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def enqueue_bitnewton_retry(
    queue: dict[str, dict[str, Any]],
    *,
    row: dict[str, Any],
    error: Exception | str,
    retry_reason: str = "bitnewton_unavailable",
) -> bool:
    deal_id = deal_id_from_report_row(row) or str(row.get("deal_id") or "").strip()
    if not deal_id:
        return False

    activity_id = safe_int(row.get("activity_id"))
    call_id = str(row.get("origin_id") or "").strip()
    key = build_retry_key(call_id=call_id, deal_id=deal_id, activity_id=activity_id)
    if not key:
        return False

    now = _now_iso()
    existing = queue.get(key)
    if existing:
        attempts = int(existing.get("retry_attempts") or 1) + 1
        existing.update(
            {
                "error": str(error),
                "retry_reason": retry_reason,
                "retry_attempts": attempts,
                "last_error_at": now,
                "deal_url": row.get("deal_url") or existing.get("deal_url"),
                "subject": row.get("subject") or existing.get("subject"),
            }
        )
        return False

    queue[key] = {
        "deal_id": deal_id,
        "deal_url": row.get("deal_url"),
        "activity_id": activity_id,
        "origin_id": call_id,
        "subject": row.get("subject"),
        "error": str(error),
        "retry_reason": retry_reason,
        "retry_attempts": 1,
        "queued_at": now,
        "last_error_at": now,
    }
    return True


def resolve_bitnewton_retry(
    queue: dict[str, dict[str, Any]],
    *,
    call_id: str | None,
    deal_id: str | None,
    activity_id: int | None,
) -> bool:
    key = build_retry_key(call_id=call_id, deal_id=deal_id, activity_id=activity_id)
    if not key:
        return False
    if key in queue:
        queue.pop(key, None)
        return True
    return False
