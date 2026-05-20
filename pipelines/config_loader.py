from __future__ import annotations

from typing import Any

from pipelines.kpi import load_kpi_config
from pipelines.transcription import _load_state_cache, _save_state_cache


def load_kpi_pair(args: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Загружает основную и (опционально) сравнительную конфигурацию KPI."""
    kpi = load_kpi_config(args.kpi_config)
    kpi_cmp = load_kpi_config(args.kpi_config_compare) if args.kpi_config_compare else None
    return kpi, kpi_cmp


def load_state_cache() -> dict[str, Any]:
    """Загружает кэш состояний транскрипций."""
    return _load_state_cache()


def save_state_cache(state_cache: dict[str, Any]) -> None:
    """Сохраняет кэш состояний транскрипций."""
    _save_state_cache(state_cache)
