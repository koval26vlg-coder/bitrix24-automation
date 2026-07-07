"""Отправка сводки отчета bitnewton_sync в Telegram.

Использование:
    python telegram_notify.py                # сводка + XLSX из latest-отчета
    python telegram_notify.py --no-file      # только текстовая сводка
    python telegram_notify.py --dry-run      # напечатать сводку без отправки

Требует TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPORTS_DIR = Path(__file__).parent / "reports"
DEFAULT_REPORT_JSON = REPORTS_DIR / "latest_bitnewton_report.json"
DEFAULT_REPORT_XLSX = REPORTS_DIR / "latest_bitnewton_report.xlsx"
TELEGRAM_API = "https://api.telegram.org"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _collect_scores(rows: list[dict[str, Any]], field: str) -> list[float]:
    scores: list[float] = []
    for row in rows:
        raw = row.get(field)
        if raw is None or raw == "":
            continue
        try:
            scores.append(float(raw))
        except (TypeError, ValueError):
            continue
    return scores


def build_summary(rows: list[dict[str, Any]]) -> str:
    deals = {str(r.get("deal_id")) for r in rows if r.get("deal_id")}
    calls = [r for r in rows if r.get("activity_id")]

    overall = _avg(_collect_scores(rows, "overall_score"))
    call_quality = _avg(_collect_scores(rows, "call_quality_score"))
    deal_quality = _avg(_collect_scores(rows, "deal_quality_score"))

    sla_flags = [
        bool(r.get("first_response_sla_ok"))
        for r in rows
        if r.get("first_response_sla_ok") is not None
    ]
    sla_percent = round(100 * sum(sla_flags) / len(sla_flags)) if sla_flags else None

    by_manager: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("manager_name") or "Без менеджера").strip()
        by_manager.setdefault(name, []).append(row)

    lines = [
        "Отчет Bitrix24 (bitnewton_sync)",
        f"Сделок: {len(deals)}, звонков: {len(calls)}",
    ]
    if overall is not None:
        lines.append(f"Средний общий балл: {overall}")
    if call_quality is not None:
        lines.append(f"Качество звонков: {call_quality}")
    if deal_quality is not None:
        lines.append(f"Качество ведения сделок: {deal_quality}")
    if sla_percent is not None:
        lines.append(f"SLA первого ответа: {sla_percent}% вовремя")

    if by_manager:
        lines.append("")
        lines.append("По менеджерам:")
        for name in sorted(by_manager):
            manager_rows = by_manager[name]
            manager_overall = _avg(_collect_scores(manager_rows, "overall_score"))
            score_text = f", общий балл {manager_overall}" if manager_overall is not None else ""
            lines.append(f"- {name}: {len(manager_rows)} звонков{score_text}")

    errors = [r for r in rows if r.get("error")]
    if errors:
        lines.append("")
        lines.append(f"Ошибок обработки: {len(errors)}")

    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    resp.raise_for_status()


def send_document(token: str, chat_id: str, path: Path) -> None:
    with path.open("rb") as fh:
        resp = requests.post(
            f"{TELEGRAM_API}/bot{token}/sendDocument",
            data={"chat_id": chat_id},
            files={"document": (path.name, fh)},
            timeout=120,
        )
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Отправка сводки отчета в Telegram")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_JSON), help="Путь к JSON-отчету")
    parser.add_argument("--xlsx", default=str(DEFAULT_REPORT_XLSX), help="Путь к XLSX-отчету")
    parser.add_argument("--no-file", action="store_true", help="Не прикреплять XLSX")
    parser.add_argument("--dry-run", action="store_true", help="Только напечатать сводку")
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[ERROR] Отчет не найден: {report_path}", file=sys.stderr)
        return 1

    rows = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        print("[ERROR] Ожидался JSON-массив строк отчета", file=sys.stderr)
        return 1

    summary = build_summary(rows)

    if args.dry_run:
        print(summary)
        return 0

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print(
            "[ERROR] TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть заданы в .env",
            file=sys.stderr,
        )
        return 1

    send_message(token, chat_id, summary)

    xlsx_path = Path(args.xlsx)
    if not args.no_file and xlsx_path.exists():
        send_document(token, chat_id, xlsx_path)

    print("[OK] Сводка отправлена в Telegram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
