from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from bitrix.api import Bitrix24API


@dataclass
class ProcessingContext:
    api: Bitrix24API
    asr: Any
    args: Any
    kpi: Dict[str, Any]
    kpi_cmp: Optional[Dict[str, Any]]
    audio_source_index: List[Path]
    audio_dir: Path
    ui_audio_dir: Path
    state_cache: Dict[str, Any]
    ui_browser_session: Any = None


@dataclass
class DealProcessingResult:
    rows: List[Dict[str, Any]]
    ok: int
    err: int


@dataclass
class ProcessingRunResult:
    rows: List[Dict[str, Any]]
    ok: int
    err: int
