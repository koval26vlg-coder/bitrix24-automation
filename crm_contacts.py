import asyncio
from datetime import datetime, timedelta

import pandas as pd

import config
from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)


class ContactsManager:
    def __init__(self):
        self.api = Bitrix24API()

    async def get_contacts(self, filter_params: dict = None) -> list:
        """Получить список контактов с фильтрацией (асинхронно)"""
        params = {
            "select": [
                "ID",
                "NAME",
                "LAST_NAME",
                "SECOND_NAME",
                "POST",
                "COMPANY_ID",
                "ASSIGNED_BY_ID",
                "CREATED_BY_ID",
                "DATE_CREATE",
                "DATE_MODIFY",
                "PHONE",
                "EMAIL",
                "WEB",
                "IM",
                "COMMENTS",
            ],
            "order": {"DATE_CREATE": "DESC"},
        }

        if filter_params:
            params["filter"] = filter_params

        contacts = await self.api.get_all("crm.contact.list", params)
        return contacts

    async def get_contacts_by_date(self, days: int = 7) -> list:
        """Получить контакты за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        filter_params = {">=DATE_CREATE": date_from}

        return await self.get_contacts(filter_params)

    async def get_contact_by_id(self, contact_id: int) -> dict:
        """Получить контакт по ID"""
        result = await self.api.call("crm.contact.get", {"id": contact_id})
        return result.get("result", {})

    async def search_contacts(self, query: str) -> list:
        """Поиск контактов по имени, email или телефону"""
        filter_params = {"%NAME": query}

        return await self.get_contacts(filter_params)

    def export_to_excel(self, contacts: list, filename: str = None):
        """Экспорт контактов в Excel"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{config.REPORTS_DIR}/contacts_{timestamp}.xlsx"

        processed_contacts = []
        for contact in contacts:
            processed = contact.copy()

            if "PHONE" in processed and isinstance(processed["PHONE"], list):
                processed["PHONE"] = ", ".join([p.get("VALUE", "") for p in processed["PHONE"]])

            if "EMAIL" in processed and isinstance(processed["EMAIL"], list):
                processed["EMAIL"] = ", ".join([e.get("VALUE", "") for e in processed["EMAIL"]])

            processed_contacts.append(processed)

        df = pd.DataFrame(processed_contacts)

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

    def get_statistics(self, contacts: list) -> dict:
        """Получить статистику по контактам"""
        if not contacts:
            return {}

        stats = {
            "total": len(contacts),
            "with_phone": sum(1 for c in contacts if c.get("PHONE")),
            "with_email": sum(1 for c in contacts if c.get("EMAIL")),
            "with_company": sum(1 for c in contacts if c.get("COMPANY_ID")),
        }

        return stats


async def main():
    logger.info("=== Отчет по контактам Bitrix24 (Async) ===\n")

    manager = ContactsManager()

    async with manager.api as api:
        if not await api.test_connection():
            return

        logger.info("\nВыберите действие:")
        logger.info("1. Все контакты за последние 7 дней")
        logger.info("2. Все контакты за последние 30 дней")
        logger.info("3. Все контакты")
        logger.info("4. Поиск контакта")

        choice = input("\nВаш выбор (1-4): ").strip()

        if choice == "1":
            contacts = await manager.get_contacts_by_date(7)
            title = "Контакты за последние 7 дней"
        elif choice == "2":
            contacts = await manager.get_contacts_by_date(30)
            title = "Контакты за последние 30 дней"
        elif choice == "3":
            contacts = await manager.get_contacts()
            title = "Все контакты"
        elif choice == "4":
            query = input("Введите имя, email или телефон: ").strip()
            contacts = await manager.search_contacts(query)
            title = f"Результаты поиска: {query}"
        else:
            logger.info("Неверный выбор")
            return

        logger.info(f"\n{title}: найдено {len(contacts)} записей")

        if contacts:
            stats = manager.get_statistics(contacts)
            logger.info("\nСтатистика:")
            logger.info(f"  Всего: {stats['total']}")
            logger.info(f"  С телефоном: {stats['with_phone']}")
            logger.info(f"  С email: {stats['with_email']}")
            logger.info(f"  С компанией: {stats['with_company']}")

            filename = manager.export_to_excel(contacts)
            logger.info(f"\n✓ Готово! Файл: {filename}")
        else:
            logger.info("Контакты не найдены")


if __name__ == "__main__":
    asyncio.run(main())
