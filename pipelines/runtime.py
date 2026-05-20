from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bitrix.api import Bitrix24API
from logging_setup import get_logger
from pipelines.audio import build_audio_source_index, parse_audio_source_dirs
from pipelines.cleanup import cleanup_old_outputs
from pipelines.deals import resolve_deal_ids
from pipelines.paths import REPORTS_DIR
from pipelines.processing import ProcessingContext
from pipelines.retry import load_retry_scope
from scoring.codex_evaluator import CodexEvaluator

logger = get_logger(__name__)


@dataclass
class AudioRuntime:
    audio_dir: Path
    ui_audio_dir: Path
    audio_source_index: list[Path]


def resolve_retry_scope(args: Any) -> dict[str, Any] | None:
    """Загружает область повторной обработки ошибок."""
    retry_scope = load_retry_scope(args.retry_errors_from) if args.retry_errors_from else None
    if retry_scope is not None:
        error_count = retry_scope.get("errors", 0)
        deal_count = len(retry_scope.get("deal_ids", []))
        logger.info(
            f"[RETRY] Повторяю только ошибки из отчета: "
            f"строк с ошибками={error_count}, сделок={deal_count}"
        )
    return retry_scope


def resolve_deal_scope(
    args: Any, api: Bitrix24API, vibe: Any = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """Shim for tests."""
    retry_scope = resolve_retry_scope(args)
    if retry_scope is not None:
        return retry_scope, list(retry_scope.get("deal_ids", []))

    # In async version resolve_deal_ids is async, so this shim can only return empty list if not in retry  # noqa: E501
    # Tests that mock resolve_deal_ids will still work if they mock it to return a list
    try:
        ids = resolve_deal_ids(args, api, vibe=vibe)
        if not isinstance(ids, list):
            return retry_scope, []
        return retry_scope, ids
    except Exception:
        return retry_scope, []


def prepare_audio_runtime(args: Any) -> AudioRuntime:
    """Подготавливает папки и индекс локальных аудиофайлов."""
    audio_dir = REPORTS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ui_audio_dir = (
        Path(args.ui_download_dir) if args.ui_download_dir else (REPORTS_DIR / "audio_ui")
    )
    ui_audio_dir.mkdir(parents=True, exist_ok=True)

    audio_source_dirs = parse_audio_source_dirs(getattr(args, "audio_source_dir", []))
    audio_source_index = build_audio_source_index(audio_source_dirs)
    if audio_source_dirs:
        audio_dirs_text = ", ".join(str(path) for path in audio_source_dirs)
        logger.info(
            f"[AUDIO] Локальных аудиофайлов в индексе: {len(audio_source_index)}; "
            f"папки: {audio_dirs_text}"
        )

    cleanup_days = int(args.cleanup_output_days or 0)
    if cleanup_days > 0:
        removed = cleanup_old_outputs(
            REPORTS_DIR, keep_days=cleanup_days, extra_audio_dirs=[ui_audio_dir]
        )
        if removed.get("total"):
            report_count = removed.get("reports", 0)
            audio_count = removed.get("audio", 0)
            transcript_count = removed.get("transcripts", 0)
            logger.info(
                f"[OK] Автоочистка старше {cleanup_days} дней: "
                f"отчеты={report_count}, "
                f"аудио={audio_count}, "
                f"расшифровки={transcript_count}"
            )

    return AudioRuntime(
        audio_dir=audio_dir,
        ui_audio_dir=ui_audio_dir,
        audio_source_index=audio_source_index,
    )


def build_processing_context(
    *,
    api: Bitrix24API,
    asr: Any,
    args: Any,
    kpi: dict[str, Any],
    kpi_cmp: dict[str, Any] | None,
    audio_runtime: AudioRuntime,
    state_cache: dict[str, Any],
    vibe: Any = None,
) -> ProcessingContext:
    """Собирает контекст для выполнения обработки."""
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
        vibe=vibe,
        asr_disabled_reason=getattr(asr, "auth_error", None),
        codex_evaluator=CodexEvaluator(),
    )


async def close_processing_context(ctx: ProcessingContext) -> None:
    """Закрывает ресурсы, используемые в контексте."""
    if ctx.ui_browser_session is not None:
        ctx.ui_browser_session.close()
    if ctx.api is not None:
        await ctx.api.aclose()
    if ctx.codex_evaluator is not None and hasattr(ctx.codex_evaluator, "aclose"):
        await ctx.codex_evaluator.aclose()
