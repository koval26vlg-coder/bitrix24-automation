from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

from asr.bitnewton import BitNewtonAuthError, env_bitnewton_asr
from bitrix.api import Bitrix24API
from logging_setup import get_logger
from pipelines.token_status import (
    format_bitnewton_token_status,
    record_bitnewton_token_validation,
    update_bitnewton_token_status,
)
from vibecode_api import env_vibecode_client

logger = get_logger(__name__)


async def create_bitrix_api() -> Bitrix24API:
    """Создает и тестирует подключение к Bitrix24 API."""
    api = Bitrix24API()
    if not await api.test_connection():
        await api.aclose()
        raise SystemExit(1)
    return api


def create_vibecode_client(args: Any) -> Any:
    """Создает клиент VibeCode API, если это разрешено аргументами."""
    if not bool(getattr(args, "use_vibecode", True)):
        return None
    try:
        vibe = env_vibecode_client()
    except Exception as e:
        logger.warning(f"[WARN] VibeCode API недоступен: {e}")
        return None
    if vibe is None:
        logger.info("[VIBECODE] VIBECODE_API_KEY не задан, работаю через обычный Bitrix REST.")
        return None
    try:
        info = vibe.me()
        portal = info.get("portal") if isinstance(info, dict) else ""
        trial = info.get("trial") if isinstance(info, dict) else {}
        days = trial.get("daysRemaining") if isinstance(trial, dict) else None
        logger.info(f"[VIBECODE] Подключено: портал={portal or 'unknown'}, trial_days={days}")
    except Exception as e:
        logger.warning(
            f"[WARN] Не удалось проверить VibeCode /v1/me: {e}. Будет использован Bitrix REST."
        )
        return None
    return vibe


def create_bitnewton_asr(args: Any) -> Any:
    """Создает клиент Bit.Newton ASR и проверяет токен."""
    if bool(getattr(args, "dry_run", False)):
        reason = "dry-run: новая ASR отключена, Bit.Newton токен не требуется."
        logger.info(f"[DRY-RUN] {reason}")
        return SimpleNamespace(auth_error=reason)
    if not (args.use_bitnewton or args.bitnewton_flow):
        raise SystemExit("Нужен флаг --use-bitnewton (или --bitnewton-flow)")
    asr = env_bitnewton_asr()
    if not asr:
        reason = "Не задан BITNEWTON_TOKEN в .env. Новая расшифровка Bit.Newton будет пропущена."
        logger.warning(f"[WARN] {reason}")
        return SimpleNamespace(auth_error=reason)
    update_bitnewton_token_status(getattr(asr, "token", ""))
    return asr


async def validate_asr_token(asr: Any) -> None:
    """Асинхронная валидация токена ASR."""
    if hasattr(asr, "auth_error") or not hasattr(asr, "validate_token"):
        return
    try:
        validation_result = asr.validate_token()
        if inspect.isawaitable(validation_result):
            await validation_result
        token_status = record_bitnewton_token_validation(ok=True)
        logger.info(f"[TOKEN] {format_bitnewton_token_status(token_status)}")
    except BitNewtonAuthError as e:
        reason = str(e)
        token_status = record_bitnewton_token_validation(ok=False, error=reason)
        logger.info(f"[TOKEN] {format_bitnewton_token_status(token_status)}")
        logger.warning(f"[WARN] {reason}")
        logger.warning(
            "[WARN] Продолжаю отчет без новых запросов в Bit.Newton: использую кэш и CRM-аналитику."
        )
        asr.auth_error = reason
    except Exception as e:
        logger.warning(f"[WARN] Не удалось предварительно проверить токен Bit.Newton: {e}")
