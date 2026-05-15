from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from bitrix.api import Bitrix24API
from pipelines.stages import safe_int

from logging_setup import get_logger

logger = get_logger(__name__)


def deal_url_from_id(domain: str, deal_id: str) -> str:
    domain = (domain or "").strip().replace("https://", "").replace("http://", "").strip("/")
    return f"https://{domain}/crm/deal/details/{deal_id}/"


def fetch_deals_by_filter(api: Bitrix24API, flt: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
    deals: List[Dict[str, Any]] = []
    start: Optional[int] = 0
    page_size = 50
    max_items = max(0, int(limit or 0))
    if max_items <= 0:
        return deals

    while start is not None and len(deals) < max_items:
        res = api.call(
            "crm.deal.list",
            {
                "filter": flt,
                "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STAGE_ID", "DATE_CREATE"],
                "order": {"ID": "DESC"},
                "start": start,
            },
        )
        chunk = res.get("result", []) or []
        if not chunk:
            break

        remaining = max_items - len(deals)
        deals.extend(chunk[:remaining])
        if len(deals) >= max_items:
            break

        next_start = res.get("next")
        if next_start is not None:
            start = safe_int(next_start)
        else:
            total = safe_int(res.get("total"))
            start = start + page_size
            if total is None or start >= total:
                start = None

    return deals


def normalize_deal_filter_dates(flt: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(flt or {})
    date_to = out.pop("<=DATE_CREATE", None)
    if isinstance(date_to, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date_to.strip()):
        next_day = datetime.strptime(date_to.strip(), "%Y-%m-%d") + timedelta(days=1)
        out["<DATE_CREATE"] = next_day.date().isoformat()
    elif date_to is not None:
        out["<=DATE_CREATE"] = date_to
    return out


def deal_get(api: Bitrix24API, deal_id: str) -> Dict[str, Any]:
    return api.call("crm.deal.get", {"id": int(deal_id)}).get("result", {}) or {}


def deal_id_from_report_row(row: Dict[str, Any]) -> Optional[str]:
    deal_id = row.get("deal_id")
    if deal_id:
        deal_str = str(deal_id).strip()
        if deal_str.isdigit():
            return deal_str
    url = str(row.get("deal_url") or "").strip()
    match = re.search(r"/crm/deal/details/(\d+)/?", url)
    return match.group(1) if match else None


def resolve_deal_ids(args: Any, api: Bitrix24API) -> List[str]:
    if args.mode == "single":
        if args.deal_id:
            deal_id = str(args.deal_id).strip()
            if not deal_id.isdigit():
                raise SystemExit(f"--deal-id должен быть числом. Сейчас: {deal_id!r}")
            return [deal_id]
        if args.deal_url:
            url = str(args.deal_url).strip()
            match = re.search(r"/crm/deal/details/(\d+)/?", url)
            if match:
                return [match.group(1)]
            tail = url.rstrip("/").split("/")[-1]
            if tail.isdigit():
                return [tail]
            raise SystemExit(
                "Не смог распознать ID сделки из --deal-url. "
                "Ожидаю ссылку вида https://<domain>/crm/deal/details/12345/ "
                f"(получил: {url!r})."
            )
        raise SystemExit("Для --mode single нужен --deal-id или --deal-url")

    flt = normalize_deal_filter_dates(json.loads(Path(args.filter_json).read_text(encoding="utf-8")))
    deals = fetch_deals_by_filter(api, flt, limit=args.limit)
    logger.info(f"Найдено сделок: {len(deals)}")
    return [str(d.get("ID")) for d in deals if d.get("ID")]
