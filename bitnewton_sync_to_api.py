from __future__ import annotations

from pipelines.bitnewton_sync import build_parser, run_sync


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_sync(args)


if __name__ == "__main__":
    main()

