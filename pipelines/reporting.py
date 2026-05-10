from __future__ import annotations

import shutil
from pathlib import Path

from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR


def publish_latest_report(json_path: Path, xlsx_path: Path) -> None:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if json_path.exists():
            shutil.copy2(json_path, LATEST_JSON_REPORT)
        if xlsx_path.exists():
            shutil.copy2(xlsx_path, LATEST_XLSX_REPORT)
    except Exception as e:
        print(f"[WARN] Не удалось обновить latest-отчет: {e}", flush=True)
