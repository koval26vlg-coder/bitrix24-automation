from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pipelines.paths import REPORTS_DIR

BITNEWTON_TOKEN_TTL_DAYS = 30
TOKEN_STATUS_PATH = REPORTS_DIR / "bitnewton_token_status.json"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _load_status(path: Path = TOKEN_STATUS_PATH) -> dict[str, Any]:
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
    return {}


def _save_status(status: dict[str, Any], path: Path = TOKEN_STATUS_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def update_bitnewton_token_status(
    token: str | None = None,
    *,
    issued_at: str | None = None,
    today: date | None = None,
    path: Path = TOKEN_STATUS_PATH,
) -> dict[str, Any]:
    token = (token if token is not None else os.getenv("BITNEWTON_TOKEN", "")).strip()
    today = today or date.today()
    if not token:
        return {
            "configured": False,
            "days_left": None,
            "message": "BITNEWTON_TOKEN не задан.",
        }

    current_hash = _token_hash(token)
    previous = _load_status(path)
    env_issued_at = (
        issued_at
        or os.getenv("BITNEWTON_TOKEN_ISSUED_AT")
        or os.getenv("BITNEWTON_TOKEN_CREATED_AT")
    )
    issued_date = _parse_date(env_issued_at)

    if previous.get("token_hash") == current_hash and not issued_date:
        issued_date = _parse_date(previous.get("issued_at"))
    if issued_date is None:
        issued_date = today

    expires_at = issued_date + timedelta(days=BITNEWTON_TOKEN_TTL_DAYS)
    days_left = (expires_at - today).days
    status = {
        "configured": True,
        "token_hash": current_hash,
        "token_hash_short": current_hash[:12],
        "issued_at": issued_date.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_days": BITNEWTON_TOKEN_TTL_DAYS,
        "days_left": days_left,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if previous.get("token_hash") == current_hash:
        for key in ["last_validation_ok", "last_validation_error", "last_validation_at"]:
            if key in previous:
                status[key] = previous[key]
    status["message"] = format_bitnewton_token_status(status)
    _save_status(status, path)
    return status


def record_bitnewton_token_validation(
    *,
    ok: bool,
    error: str | None = None,
    path: Path = TOKEN_STATUS_PATH,
) -> dict[str, Any]:
    status = _load_status(path)
    if not status:
        return status
    status["last_validation_ok"] = bool(ok)
    status["last_validation_error"] = (error or "")[:500] if not ok else ""
    status["last_validation_at"] = datetime.now().isoformat(timespec="seconds")
    status["message"] = format_bitnewton_token_status(status)
    _save_status(status, path)
    return status


def current_bitnewton_token_status() -> dict[str, Any]:
    token = os.getenv("BITNEWTON_TOKEN", "").strip()
    if token:
        return update_bitnewton_token_status(token)
    status = _load_status()
    if status:
        status["message"] = format_bitnewton_token_status(status)
        return status
    return {"configured": False, "days_left": None, "message": "BITNEWTON_TOKEN не задан."}


def format_bitnewton_token_status(status: dict[str, Any]) -> str:
    if not status.get("configured"):
        return "BITNEWTON_TOKEN не задан."
    days_left = status.get("days_left")
    expires_at = status.get("expires_at") or ""
    validation_ok = status.get("last_validation_ok")
    validation_error = str(status.get("last_validation_error") or "").strip()
    if days_left is None:
        return "Токен Bit.Newton активен. Дата окончания не рассчитана."
    try:
        days = int(days_left)
    except Exception:
        return f"Токен Bit.Newton активен. Дата окончания: {expires_at}."
    if validation_ok is False:
        local_ttl = (
            f"локально до {expires_at}, осталось {days} дн"
            if days >= 0
            else f"локально просрочен {expires_at}"
        )
        short_error = (
            validation_error.splitlines()[0][:180] if validation_error else "проверка не пройдена"
        )
        return f"Токен Bit.Newton не прошел проверку: {short_error}. Срок по локальному учету: {local_ttl}."  # noqa: E501
    if days < 0:
        return f"Токен Bit.Newton просрочен на {abs(days)} дн. Дата окончания: {expires_at}."
    if days == 0:
        return f"Токен Bit.Newton истекает сегодня ({expires_at})."
    if days <= 3:
        return f"Токен Bit.Newton скоро истечет: осталось {days} дн. до {expires_at}."
    return f"Токен Bit.Newton активен: осталось {days} дн. до {expires_at}."
