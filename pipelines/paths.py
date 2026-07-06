from __future__ import annotations

from pathlib import Path

REPORTS_DIR = Path("reports")
TRANSCRIPTS_DIR = REPORTS_DIR / "transcripts"
LATEST_JSON_REPORT = REPORTS_DIR / "latest_bitnewton_report.json"
LATEST_XLSX_REPORT = REPORTS_DIR / "latest_bitnewton_report.xlsx"
BITNEWTON_RETRY_QUEUE_PATH = REPORTS_DIR / "bitnewton_retry_queue.json"
