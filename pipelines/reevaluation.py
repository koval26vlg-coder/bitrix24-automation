from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pipelines.evaluation import recompute_existing_row
from pipelines.paths import LATEST_JSON_REPORT, LATEST_XLSX_REPORT, REPORTS_DIR
from pipelines.reporting import build_manager_summary, flatten_results, prepare_report_rows, publish_latest_report
from pipelines.retry import load_report_json


def reevaluate_report(args: Any, kpi: Dict[str, Any], kpi_cmp: Optional[Dict[str, Any]]) -> Tuple[int, Path, Path]:
    rows = load_report_json(args.reevaluate_from)
    recalculated = [recompute_existing_row(row, kpi, kpi_cmp) for row in rows]
    manager_summary = build_manager_summary(recalculated)
    manager_summary_cmp = build_manager_summary(recalculated, score_key="overall_score_cmp") if kpi_cmp is not None else None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_out = REPORTS_DIR / f"bitnewton_reevaluated_report_{ts}.json"
    json_out.write_text(json.dumps(prepare_report_rows(recalculated), ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = flatten_results(recalculated, manager_summary, manager_summary_cmp=manager_summary_cmp)
    publish_latest_report(json_out, xlsx_out)
    print(f"[OK] Переоценено строк без повторной расшифровки: {len(recalculated)}")
    print(f"\nОтчет JSON: {json_out}")
    print(f"Отчет Excel: {xlsx_out}")
    print(f"Последний JSON: {LATEST_JSON_REPORT}")
    print(f"Последний Excel: {LATEST_XLSX_REPORT}")
    print(f"ИТОГО: OK={len(recalculated)} ERR=0")
    return len(recalculated), json_out, xlsx_out
