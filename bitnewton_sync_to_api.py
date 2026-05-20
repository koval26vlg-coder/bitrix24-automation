from __future__ import annotations

import asyncio

from logging_setup import get_logger
from pipelines.bitnewton_sync import run_sync
from pipelines.cli import build_parser
from pipelines.processing.context import FatalProcessingError

logger = get_logger(__name__)


async def main_async() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        # run_sync теперь асинхронный
        await run_sync(args)
    except FatalProcessingError as e:
        logger.error(str(e))
        raise SystemExit(2) from e


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
