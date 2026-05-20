"""
Статистика лидов за вчерашний день
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta

from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)



async def main() -> None:
    api = Bitrix24API()
    try:
        if not await api.test_connection():
            return

        # Вчерашний день
        yesterday = datetime.now() - timedelta(days=1)
        date_from = yesterday.strftime("%Y-%m-%d")
        date_to = yesterday.strftime("%Y-%m-%d") + " 23:59:59"

        logger.info(f"=== STATISTIKA LIDOV ZA {date_from} ===\n")

        # Получаем лиды
        result = await api.call(
            "crm.lead.list",
            {
                "filter": {">=DATE_CREATE": date_from, "<=DATE_CREATE": date_to},
                "select": ["ID", "STATUS_ID", "SOURCE_ID"],
            },
        )
    finally:
        await api.aclose()

    leads = result.get("result", [])

    logger.info(f"Vsego lidov: {len(leads)}\n")

    # Статистика по статусам
    statuses = Counter([lead.get("STATUS_ID") for lead in leads])
    logger.info("Po statusam:")
    for status, count in statuses.most_common():
        logger.info(f"  {status}: {count}")

    # Статистика по источникам
    sources = Counter([lead.get("SOURCE_ID") for lead in leads])
    logger.info("\nPo istochnikam:")
    for source, count in sources.most_common():
        logger.info(f"  {source}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
