from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asr.bitnewton import env_bitnewton_asr
from bitrix.api import Bitrix24API
from pipelines.audio import build_audio_source_index, parse_audio_source_dirs
from pipelines.cleanup import cleanup_old_outputs
from pipelines.deals import resolve_deal_ids
from pipelines.kpi import load_kpi_config
from pipelines.paths import REPORTS_DIR
from pipelines.processing import ProcessingContext
from pipelines.retry import load_retry_scope
from pipelines.transcription import _load_state_cache, _save_state_cache


@dataclass
class AudioRuntime:
    audio_dir: Path
    ui_audio_dir: Path
    audio_source_index: List[Path]


def load_kpi_pair(args: Any) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    kpi = load_kpi_config(args.kpi_config)
    kpi_cmp = load_kpi_config(args.kpi_config_compare) if args.kpi_config_compare else None
    return kpi, kpi_cmp


def create_bitrix_api() -> Bitrix24API:
    api = Bitrix24API()
    if not api.test_connection():
        raise SystemExit(1)
    return api


def create_bitnewton_asr(args: Any) -> Any:
    if not (args.use_bitnewton or args.bitnewton_flow):
        raise SystemExit("Нужен флаг --use-bitnewton (или --bitnewton-flow)")
    asr = env_bitnewton_asr()
    if not asr:
        raise SystemExit("Не задан BITNEWTON_TOKEN в .env")
    return asr


def resolve_deal_scope(args: Any, api: Bitrix24API) -> tuple[Optional[Dict[str, Any]], List[str]]:
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
        return retry_scope, deal_ids

    return None, resolve_deal_ids(args, api)


def prepare_audio_runtime(args: Any) -> AudioRuntime:
    audio_dir = REPORTS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ui_audio_dir = Path(args.ui_download_dir) if args.ui_download_dir else (REPORTS_DIR / "audio_ui")
    ui_audio_dir.mkdir(parents=True, exist_ok=True)

    audio_source_dirs = parse_audio_source_dirs(getattr(args, "audio_source_dir", []))
    audio_source_index = build_audio_source_index(audio_source_dirs)
    if audio_source_dirs:
        print(
            f"[AUDIO] Локальных аудиофайлов в индексе: {len(audio_source_index)}; "
            f"папки: {', '.join(str(path) for path in audio_source_dirs)}",
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

    return AudioRuntime(
        audio_dir=audio_dir,
        ui_audio_dir=ui_audio_dir,
        audio_source_index=audio_source_index,
    )


def load_state_cache() -> Dict[str, Any]:
    return _load_state_cache()


def save_state_cache(state_cache: Dict[str, Any]) -> None:
    _save_state_cache(state_cache)


def build_processing_context(
    *,
    api: Bitrix24API,
    asr: Any,
    args: Any,
    kpi: Dict[str, Any],
    kpi_cmp: Optional[Dict[str, Any]],
    audio_runtime: AudioRuntime,
    state_cache: Dict[str, Any],
) -> ProcessingContext:
    return ProcessingContext(
        api=api,
        asr=asr,
        args=args,
        kpi=kpi,
        kpi_cmp=kpi_cmp,
        audio_source_index=audio_runtime.audio_source_index,
        audio_dir=audio_runtime.audio_dir,
        ui_audio_dir=audio_runtime.ui_audio_dir,
        state_cache=state_cache,
    )


def close_processing_context(ctx: ProcessingContext) -> None:
    if ctx.ui_browser_session is not None:
        ctx.ui_browser_session.close()
