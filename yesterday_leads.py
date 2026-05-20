
from logging_setup import get_logger

logger = get_logger(__name__)
"""
Лиды за вчерашний день
"""

import asyncio
from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta


async def main() -> None:
    api = Bitrix24API()
    try:
        if not await api.test_connection():
            return

        # Вчерашний день
        yesterday = datetime.now() - timedelta(days=1)
        date_from = yesterday.strftime('%Y-%m-%d')
        date_to = yesterday.strftime('%Y-%m-%d') + ' 23:59:59'

        logger.info(f"=== LIDY ZA {date_from} ===\n")

        # Получаем лиды
        result = await api.call('crm.lead.list', {
            'filter': {
                '>=DATE_CREATE': date_from,
                '<=DATE_CREATE': date_to
            },
            'select': ['ID', 'TITLE', 'NAME', 'LAST_NAME', 'STATUS_ID',
                       'SOURCE_ID', 'DATE_CREATE', 'ASSIGNED_BY_ID']
        })
    finally:
        await api.aclose()

    leads = result.get('result', [])

    logger.info(f"Vsego lidov: {len(leads)}\n")

    if leads:
        logger.info("Spisok lidov:")
        for lead in leads:
            name = f"{lead.get('NAME', '')} {lead.get('LAST_NAME', '')}".strip()
            if not name:
                name = lead.get('TITLE', 'Bez imeni')

            logger.info(f"  ID: {lead.get('ID')}")
            logger.info(f"    Imya: {name}")
            logger.info(f"    Status: {lead.get('STATUS_ID')}")
            logger.info(f"    Istochnik: {lead.get('SOURCE_ID')}")
            logger.info(f"    Sozdano: {lead.get('DATE_CREATE')}")
            logger.info()
    else:
        logger.info("Lidov ne naydeno")


if __name__ == "__main__":
    asyncio.run(main())
