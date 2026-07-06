from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bitrix.api import Bitrix24API


class FatalProcessingError(RuntimeError):
    pass


@dataclass
class ProcessingContext:
    api: Bitrix24API
    asr: Any
    args: Any
    kpi: dict[str, Any]
    kpi_cmp: dict[str, Any] | None
    audio_source_index: list[Path]
    audio_dir: Path
    ui_audio_dir: Path
    state_cache: dict[str, Any]
    ui_browser_session: Any = None
    vibe: Any = None
    asr_disabled_reason: str | None = None
    codex_evaluator: Any = None  # Добавляем CodexEvaluator
    retry_queue: dict[str, dict[str, Any]] | None = None
    retry_queue_path: Path | None = None
    retry_queue_lock: Any = None
    retry_queue_added: int = 0
    retry_queue_resolved: int = 0


@dataclass
class DealProcessingResult:
    rows: list[dict[str, Any]]
    ok: int
    err: int


@dataclass
class ProcessingRunResult:
    rows: list[dict[str, Any]]
    ok: int
    err: int
