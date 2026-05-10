from __future__ import annotations

from pipelines.bitnewton_sync import run_sync
from pipelines.cli import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_sync(args)


if __name__ == "__main__":
    main()

