import asyncio
from datetime import datetime, timedelta

import pandas as pd

import config
from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)


class LeadsManager:
    def __init__(self):
        self.api = Bitrix24API()

    async def get_leads(self, filter_params: dict = None) -> list:
        """Получить список лидов с фильтрацией (асинхронно)"""
        params = {
            "select": [
                "ID",
                "TITLE",
                "NAME",
                "LAST_NAME",
                "STATUS_ID",
                "SOURCE_ID",
                "OPPORTUNITY",
                "CURRENCY_ID",
                "ASSIGNED_BY_ID",
                "CREATED_BY_ID",
                "DATE_CREATE",
                "DATE_MODIFY",
                "PHONE",
                "EMAIL",
                "COMMENTS",
            ],
            "order": {"DATE_CREATE": "DESC"},
        }

        if filter_params:
            params["filter"] = filter_params

        leads = await self.api.get_all("crm.lead.list", params)
        return leads

    async def get_leads_by_date(self, days: int = 7) -> list:
        """Получить лиды за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        filter_params = {">=DATE_CREATE": date_from}

        return await self.get_leads(filter_params)

    async def get_leads_by_status(self, status_id: str) -> list:
        """Получить лиды по статусу"""
        filter_params = {"STATUS_ID": status_id}

        return await self.get_leads(filter_params)

    async def get_new_leads(self) -> list:
        """Получить новые лиды (статус NEW)"""
        return await self.get_leads_by_status("NEW")

    def export_to_excel(self, leads: list, filename: str = None):
        """Экспорт лидов в Excel"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{config.REPORTS_DIR}/leads_{timestamp}.xlsx"

        df = pd.DataFrame(leads)

        if not df.empty:
            if "DATE_CREATE" in df.columns:
                df["DATE_CREATE"] = pd.to_datetime(
                    df["DATE_CREATE"], utc=True, errors="coerce"
                ).dt.tz_localize(None)
            if "DATE_MODIFY" in df.columns:
                df["DATE_MODIFY"] = pd.to_datetime(
                    df["DATE_MODIFY"], utc=True, errors="coerce"
                ).dt.tz_localize(None)

        df.to_excel(filename, index=False, engine="openpyxl")
        logger.info(f"[OK] Отчет сохранен: {filename}")
        return filename

    def get_statistics(self, leads: list) -> dict:
        """Получить статистику по лидам"""
        if not leads:
            return {}

        df = pd.DataFrame(leads)

        stats = {
            "total": len(leads),
            "by_status": df["STATUS_ID"].value_counts().to_dict() if "STATUS_ID" in df else {},
            "by_source": df["SOURCE_ID"].value_counts().to_dict() if "SOURCE_ID" in df else {},
            "total_opportunity": (
                df["OPPORTUNITY"].astype(float).sum() if "OPPORTUNITY" in df else 0
            ),
            "avg_opportunity": df["OPPORTUNITY"].astype(float).mean() if "OPPORTUNITY" in df else 0,
        }

        return stats


async def main():
    logger.info("=== Отчет по лидам Bitrix24 (Async) ===\n")

    manager = LeadsManager()

    async with manager.api as api:
        if not await api.test_connection():
            return

        logger.info("\nВыберите действие:")
        logger.info("1. Все лиды за последние 7 дней")
        logger.info("2. Все лиды за последние 30 дней")
        logger.info("3. Только новые лиды")
        logger.info("4. Все лиды")

        choice = input("\nВаш выбор (1-4): ").strip()

        if choice == "1":
            leads = await manager.get_leads_by_date(7)
            title = "Лиды за последние 7 дней"
        elif choice == "2":
            leads = await manager.get_leads_by_date(30)
            title = "Лиды за последние 30 дней"
        elif choice == "3":
            leads = await manager.get_new_leads()
            title = "Новые лиды"
        elif choice == "4":
            leads = await manager.get_leads()
            title = "Все лиды"
        else:
            logger.info("Неверный выбор")
            return

        logger.info(f"\n{title}: найдено {len(leads)} записей")

        if leads:
            stats = manager.get_statistics(leads)
            logger.info("\nСтатистика:")
            logger.info(f"  Всего: {stats['total']}")
            logger.info(f"  Общая сумма: {stats['total_opportunity']:.2f}")
            logger.info(f"  Средняя сумма: {stats['avg_opportunity']:.2f}")

            if stats["by_status"]:
                logger.info("\n  По статусам:")
                for status, count in stats["by_status"].items():
                    logger.info(f"    {status}: {count}")

            filename = manager.export_to_excel(leads)
            logger.info(f"\n[OK] Готово! Файл: {filename}")
        else:
            logger.info("Лиды не найдены")


if __name__ == "__main__":
    asyncio.run(main())
