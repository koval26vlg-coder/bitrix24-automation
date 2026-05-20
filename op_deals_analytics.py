"""
Аналитика по сделкам в воронке ОП.
"""

import asyncio
from collections import Counter
from datetime import datetime

import pandas as pd

from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)


async def main() -> None:
    api = Bitrix24API()
    try:
        if not await api.test_connection():
            return

        logger.info("=== ANALITIKA SDELOK V VORONKE OP ===\n")

        logger.info("Poluchenie spiska voronok...")
        categories_result = await api.call("crm.category.list", {"entityTypeId": 2})
        categories = categories_result.get("result", {}).get("categories", [])

        logger.info("\nDostupnye voronki:")
        for cat in categories:
            logger.info(f"  ID: {cat.get('id')}, Nazvanie: {cat.get('name')}")

        op_category_id = None
        for cat in categories:
            if "ОП" in cat.get("name", ""):
                op_category_id = cat.get("id")
                logger.info(
                    f"\n[OK] Naydena voronka OP: ID={op_category_id}, "
                    f"Nazvanie={cat.get('name')}"
                )
                break

        if not op_category_id:
            logger.info("\n[INFO] Voronka s nazvaniem 'OP' ne naydena")
            logger.info("Ispolzuem vse sdelki...")

        logger.info("\nPoluchenie sdelok...")
        filter_params = {}
        if op_category_id:
            filter_params["CATEGORY_ID"] = op_category_id

        result = await api.call(
            "crm.deal.list",
            {
                "filter": filter_params,
                "select": [
                    "ID",
                    "TITLE",
                    "STAGE_ID",
                    "CATEGORY_ID",
                    "DATE_CREATE",
                    "DATE_MODIFY",
                    "CLOSEDATE",
                    "ASSIGNED_BY_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "BEGINDATE",
                    "CLOSED",
                ],
            },
        )
        deals = result.get("result", [])
    finally:
        await api.aclose()

    logger.info(f"Vsego sdelok v voronke: {len(deals)}\n")
    if not deals:
        logger.info("Sdelok ne naydeno")
        return

    df = pd.DataFrame(deals)
    df["OPPORTUNITY"] = pd.to_numeric(df["OPPORTUNITY"], errors="coerce").fillna(0)

    logger.info("=== PO STADIYAM ===")
    stages = Counter(df["STAGE_ID"])
    for stage, count in stages.most_common():
        stage_sum = df[df["STAGE_ID"] == stage]["OPPORTUNITY"].sum()
        logger.info(f"  {stage}: {count} sdelok, summa: {stage_sum:,.2f}")

    logger.info("\n=== PO MENEDZHERAM ===")
    managers = Counter(df["ASSIGNED_BY_ID"])
    for manager_id, count in managers.most_common(10):
        manager_sum = df[df["ASSIGNED_BY_ID"] == manager_id]["OPPORTUNITY"].sum()
        logger.info(f"  Manager ID {manager_id}: {count} sdelok, summa: {manager_sum:,.2f}")

    logger.info("\n=== OBSHCHAYA STATISTIKA ===")
    logger.info(f"Vsego sdelok: {len(df)}")
    logger.info(f"Obshchaya summa: {df['OPPORTUNITY'].sum():,.2f}")
    logger.info(f"Srednyaya summa sdelki: {df['OPPORTUNITY'].mean():,.2f}")
    logger.info(f"Maksimalnaya sdelka: {df['OPPORTUNITY'].max():,.2f}")
    logger.info(f"Minimalnaya sdelka: {df['OPPORTUNITY'].min():,.2f}")

    closed = df[df["CLOSED"] == "Y"]
    if len(closed) > 0:
        logger.info(f"\nZakrytyh sdelok: {len(closed)}")
        logger.info(f"Summa zakrytyh: {closed['OPPORTUNITY'].sum():,.2f}")

    df["DATE_CREATE"] = pd.to_datetime(df["DATE_CREATE"], utc=True, errors="coerce")
    date_30_days_ago = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
    recent = df[df["DATE_CREATE"] >= date_30_days_ago]

    logger.info("\n=== ZA POSLEDNIE 30 DNEY ===")
    logger.info(f"Novyh sdelok: {len(recent)}")
    logger.info(f"Summa novyh: {recent['OPPORTUNITY'].sum():,.2f}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/op_deals_analytics_{timestamp}.xlsx"
    df_export = df.copy()

    for col in ["DATE_CREATE", "DATE_MODIFY", "CLOSEDATE", "BEGINDATE"]:
        if col in df_export.columns:
            df_export[col] = pd.to_datetime(
                df_export[col],
                utc=True,
                errors="coerce",
            ).dt.tz_localize(None)

    df_export.to_excel(filename, index=False, engine="openpyxl")
    logger.info(f"\n[OK] Dannye sohraneny: {filename}")


if __name__ == "__main__":
    asyncio.run(main())
