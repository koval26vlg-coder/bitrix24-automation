import asyncio
from datetime import datetime, timedelta

import pandas as pd

import config
from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)


class DealsManager:
    def __init__(self):
        self.api = Bitrix24API()

    async def get_deals(self, filter_params: dict = None) -> list:
        """Получить список сделок с фильтрацией (асинхронно)"""
        params = {
            "select": [
                "ID",
                "TITLE",
                "STAGE_ID",
                "PROBABILITY",
                "OPPORTUNITY",
                "CURRENCY_ID",
                "TYPE_ID",
                "ASSIGNED_BY_ID",
                "CREATED_BY_ID",
                "DATE_CREATE",
                "DATE_MODIFY",
                "BEGINDATE",
                "CLOSEDATE",
                "CLOSED",
                "COMMENTS",
                "COMPANY_ID",
                "CONTACT_ID",
            ],
            "order": {"DATE_CREATE": "DESC"},
        }

        if filter_params:
            params["filter"] = filter_params

        deals = await self.api.get_all("crm.deal.list", params)
        return deals

    async def get_deals_by_date(self, days: int = 7) -> list:
        """Получить сделки за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        filter_params = {">=DATE_CREATE": date_from}

        return await self.get_deals(filter_params)

    async def get_deals_by_stage(self, stage_id: str) -> list:
        """Получить сделки по стадии"""
        filter_params = {"STAGE_ID": stage_id}

        return await self.get_deals(filter_params)

    async def get_open_deals(self) -> list:
        """Получить открытые сделки"""
        filter_params = {"CLOSED": "N"}

        return await self.get_deals(filter_params)

    async def get_won_deals(self, days: int = 30) -> list:
        """Получить выигранные сделки за период"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        filter_params = {"CLOSED": "Y", "STAGE_ID": "WON", ">=CLOSEDATE": date_from}

        return await self.get_deals(filter_params)

    def export_to_excel(self, deals: list, filename: str = None):
        """Экспорт сделок в Excel"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{config.REPORTS_DIR}/deals_{timestamp}.xlsx"

        df = pd.DataFrame(deals)

        if not df.empty:
            if "DATE_CREATE" in df.columns:
                df["DATE_CREATE"] = pd.to_datetime(
                    df["DATE_CREATE"], utc=True, errors="coerce"
                ).dt.tz_localize(None)
            if "DATE_MODIFY" in df.columns:
                df["DATE_MODIFY"] = pd.to_datetime(
                    df["DATE_MODIFY"], utc=True, errors="coerce"
                ).dt.tz_localize(None)
            if "BEGINDATE" in df.columns:
                df["BEGINDATE"] = pd.to_datetime(
                    df["BEGINDATE"], utc=True, errors="coerce"
                ).dt.tz_localize(None)
            if "CLOSEDATE" in df.columns:
                df["CLOSEDATE"] = pd.to_datetime(
                    df["CLOSEDATE"], utc=True, errors="coerce"
                ).dt.tz_localize(None)

        df.to_excel(filename, index=False, engine="openpyxl")
        logger.info(f"[OK] Отчет сохранен: {filename}")
        return filename

    def get_statistics(self, deals: list) -> dict:
        """Получить статистику по сделкам"""
        if not deals:
            return {}

        df = pd.DataFrame(deals)

        stats = {
            "total": len(deals),
            "by_stage": df["STAGE_ID"].value_counts().to_dict() if "STAGE_ID" in df else {},
            "open_count": len(df[df["CLOSED"] == "N"]) if "CLOSED" in df else 0,
            "closed_count": len(df[df["CLOSED"] == "Y"]) if "CLOSED" in df else 0,
            "total_opportunity": (
                df["OPPORTUNITY"].astype(float).sum() if "OPPORTUNITY" in df else 0
            ),
            "avg_opportunity": df["OPPORTUNITY"].astype(float).mean() if "OPPORTUNITY" in df else 0,
            "avg_probability": df["PROBABILITY"].astype(float).mean() if "PROBABILITY" in df else 0,
        }

        return stats


async def main():
    logger.info("=== Отчет по сделкам Bitrix24 (Async) ===\n")

    manager = DealsManager()

    async with manager.api as api:
        if not await api.test_connection():
            return

        logger.info("\nВыберите действие:")
        logger.info("1. Все сделки за последние 7 дней")
        logger.info("2. Все сделки за последние 30 дней")
        logger.info("3. Только открытые сделки")
        logger.info("4. Выигранные сделки за месяц")
        logger.info("5. Все сделки")

        choice = input("\nВаш выбор (1-5): ").strip()

        if choice == "1":
            deals = await manager.get_deals_by_date(7)
            title = "Сделки за последние 7 дней"
        elif choice == "2":
            deals = await manager.get_deals_by_date(30)
            title = "Сделки за последние 30 дней"
        elif choice == "3":
            deals = await manager.get_open_deals()
            title = "Открытые сделки"
        elif choice == "4":
            deals = await manager.get_won_deals(30)
            title = "Выигранные сделки за месяц"
        elif choice == "5":
            deals = await manager.get_deals()
            title = "Все сделки"
        else:
            logger.info("Неверный выбор")
            return

        logger.info(f"\n{title}: найдено {len(deals)} записей")

        if deals:
            stats = manager.get_statistics(deals)
            logger.info("\nСтатистика:")
            logger.info(f"  Всего: {stats['total']}")
            logger.info(f"  Открытых: {stats['open_count']}")
            logger.info(f"  Закрытых: {stats['closed_count']}")
            logger.info(f"  Общая сумма: {stats['total_opportunity']:.2f}")
            logger.info(f"  Средняя сумма: {stats['avg_opportunity']:.2f}")
            logger.info(f"  Средняя вероятность: {stats['avg_probability']:.0f}%")

            if stats["by_stage"]:
                logger.info("\n  По стадиям:")
                for stage, count in stats["by_stage"].items():
                    logger.info(f"    {stage}: {count}")

            filename = manager.export_to_excel(deals)
            logger.info(f"\n✓ Готово! Файл: {filename}")
        else:
            logger.info("Сделки не найдены")


if __name__ == "__main__":
    asyncio.run(main())
