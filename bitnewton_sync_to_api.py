from __future__ import annotations

from pipelines.bitnewton_sync import run_sync
from pipelines.cli import build_parser
from pipelines.processing.context import FatalProcessingError

from logging_setup import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run_sync(args)
    except FatalProcessingError as e:
        logger.error(str(e))
        raise SystemExit(2) from e


if __name__ == "__main__":
    main()

