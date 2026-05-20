from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipelines.deals import deal_id_from_report_row
from pipelines.stages import safe_int


def load_report_json(path: str | Path) -> list[dict[str, Any]]:
    report_path = Path(path)
    if not report_path.exists():
        raise SystemExit(f"Отчет не найден: {report_path}")
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"Ожидался JSON-список строк отчета: {report_path}")
    return [row for row in raw if isinstance(row, dict)]


def load_retry_scope(path: str | Path) -> dict[str, Any]:
    rows = load_report_json(path)
    deal_ids: list[str] = []
    activity_ids_by_deal: dict[str, set[int]] = {}
    full_deals: set[str] = set()
    errors = 0
    seen_deals: set[str] = set()

    for row in rows:
        if not row.get("error"):
            continue
        deal_id = deal_id_from_report_row(row)
        if not deal_id:
            continue
        errors += 1
        if deal_id not in seen_deals:
            seen_deals.add(deal_id)
            deal_ids.append(deal_id)
        activity_id = safe_int(row.get("activity_id"))
        if activity_id is None:
            full_deals.add(deal_id)
        else:
            activity_ids_by_deal.setdefault(deal_id, set()).add(activity_id)

    return {
        "deal_ids": deal_ids,
        "activity_ids_by_deal": activity_ids_by_deal,
        "full_deals": full_deals,
        "errors": errors,
        "source_rows": rows,
        "source_path": str(path),
    }


def _report_row_identity(row: dict[str, Any]) -> tuple[str | None, int | None]:
    return deal_id_from_report_row(row), safe_int(row.get("activity_id"))


def merge_retry_results(
    original_rows: list[dict[str, Any]],
    retry_rows: list[dict[str, Any]],
    retry_scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Повтор ошибок должен обновлять полный отчет, а не заменять его маленьким отчетом
    только по ошибочным строкам.
    """
    full_deals = set(str(x) for x in (retry_scope.get("full_deals") or set()))
    retry_activity_ids_by_deal = retry_scope.get("activity_ids_by_deal") or {}

    retry_by_deal: dict[str, list[dict[str, Any]]] = {}
    retry_by_activity: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in retry_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            continue
        retry_by_deal.setdefault(deal_id, []).append(row)
        if activity_id is not None:
            retry_by_activity.setdefault((deal_id, activity_id), []).append(row)

    merged: list[dict[str, Any]] = []
    inserted_full_deals: set[str] = set()
    inserted_activities: set[tuple[str, int]] = set()
    inserted_fallback_deals: set[str] = set()

    for row in original_rows:
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue

        if deal_id in full_deals:
            if deal_id not in inserted_full_deals:
                replacements = retry_by_deal.get(deal_id)
                merged.extend(replacements if replacements else [row])
                inserted_full_deals.add(deal_id)
            continue

        target_activities = retry_activity_ids_by_deal.get(deal_id, set())
        if activity_id is not None and activity_id in target_activities:
            key = (deal_id, activity_id)
            if key not in inserted_activities:
                replacements = retry_by_activity.get(key)
                if replacements:
                    merged.extend(replacements)
                elif deal_id not in inserted_fallback_deals:
                    fallback = [
                        r
                        for r in retry_by_deal.get(deal_id, [])
                        if safe_int(r.get("activity_id")) is None
                    ]
                    merged.extend(fallback if fallback else [row])
                    inserted_fallback_deals.add(deal_id)
                else:
                    merged.append(row)
                inserted_activities.add(key)
            continue

        merged.append(row)

    existing_object_ids = {id(row) for row in merged}
    for row in retry_rows:
        if id(row) in existing_object_ids:
            continue
        deal_id, activity_id = _report_row_identity(row)
        if not deal_id:
            merged.append(row)
            continue
        if deal_id in full_deals and deal_id in inserted_full_deals:
            continue
        if activity_id is not None and (deal_id, activity_id) in inserted_activities:
            continue
        merged.append(row)

    return merged
