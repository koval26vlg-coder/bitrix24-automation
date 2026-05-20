
from logging_setup import get_logger

logger = get_logger(__name__)
"""
Детальный анализ эффективности менеджеров
"""

import asyncio
from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


async def main():
    logger.info("=== DETALNAYA STATISTIKA MENEDZHEROV ===\n")

    api = Bitrix24API()
    try:
        if not await api.test_connection():
            return

        days = 30
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Получаем менеджеров
        logger.info("Poluchenie spiska menedzherov...")
        users_result = await api.call('user.get', {'FILTER': {'ACTIVE': True}})
        users = {u['ID']: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip() for u in users_result.get('result', [])}
        logger.info(f"Vsego aktivnyh polzovateley: {len(users)}\n")

        # Получаем звонки
        logger.info("Poluchenie zvonkov...")
        calls_result = await api.call('voximplant.statistic.get', {
            'FILTER': {'>=CALL_START_DATE': date_from}
        })
        calls = calls_result.get('result', [])
        logger.info(f"Vsego zvonkov: {len(calls)}\n")

        # Получаем сделки
        logger.info("Poluchenie sdelok...")
        deals_result = await api.call('crm.deal.list', {
            'filter': {'>=DATE_CREATE': date_from},
            'select': ['ID', 'TITLE', 'STAGE_ID', 'ASSIGNED_BY_ID', 'OPPORTUNITY']
        })
        deals = deals_result.get('result', [])
        logger.info(f"Vsego sdelok: {len(deals)}\n")

        # Получаем лиды
        logger.info("Poluchenie lidov...")
        leads_result = await api.call('crm.lead.list', {
            'filter': {'>=DATE_CREATE': date_from},
            'select': ['ID', 'TITLE', 'STATUS_ID', 'ASSIGNED_BY_ID', 'OPPORTUNITY']
        })
        leads = leads_result.get('result', [])
        logger.info(f"Vsego lidov: {len(leads)}\n")
    finally:
        await api.aclose()

    # Анализ по менеджерам
    manager_stats = {}

    # Статистика звонков
    for call in calls:
        user_id = str(call.get('PORTAL_USER_ID', ''))
        if user_id not in manager_stats:
            manager_stats[user_id] = {
                'name': users.get(user_id, f'ID {user_id}'),
                'calls': 0,
                'call_duration': 0,
                'deals': 0,
                'deals_sum': 0,
                'leads': 0,
                'leads_sum': 0
            }

        manager_stats[user_id]['calls'] += 1
        manager_stats[user_id]['call_duration'] += int(call.get('CALL_DURATION', 0))

    # Статистика сделок
    for deal in deals:
        user_id = str(deal.get('ASSIGNED_BY_ID', ''))
        if user_id not in manager_stats:
            manager_stats[user_id] = {
                'name': users.get(user_id, f'ID {user_id}'),
                'calls': 0,
                'call_duration': 0,
                'deals': 0,
                'deals_sum': 0,
                'leads': 0,
                'leads_sum': 0
            }

        manager_stats[user_id]['deals'] += 1
        manager_stats[user_id]['deals_sum'] += float(deal.get('OPPORTUNITY', 0) or 0)

    # Статистика лидов
    for lead in leads:
        user_id = str(lead.get('ASSIGNED_BY_ID', ''))
        if user_id not in manager_stats:
            manager_stats[user_id] = {
                'name': users.get(user_id, f'ID {user_id}'),
                'calls': 0,
                'call_duration': 0,
                'deals': 0,
                'deals_sum': 0,
                'leads': 0,
                'leads_sum': 0
            }

        manager_stats[user_id]['leads'] += 1
        manager_stats[user_id]['leads_sum'] += float(lead.get('OPPORTUNITY', 0) or 0)

    # Создаём DataFrame
    df = pd.DataFrame.from_dict(manager_stats, orient='index')
    df = df[df['calls'] > 0]  # Только те, у кого есть звонки

    if not df.empty:
        df['avg_call_duration'] = (df['call_duration'] / df['calls']).round(1)
        df['avg_deal_sum'] = (df['deals_sum'] / df['deals'].replace(0, 1)).round(2)
        df = df.sort_values('calls', ascending=False)

        logger.info("=== STATISTIKA MENEDZHEROV (za poslednie 30 dney) ===\n")
        logger.info(df[['name', 'calls', 'avg_call_duration', 'deals', 'deals_sum', 'leads']].to_string())

        # Экспорт
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{config.REPORTS_DIR}/detailed_managers_stats_{timestamp}.xlsx"

        df_export = df.copy()
        df_export = df_export.rename(columns={
            'name': 'Менеджер',
            'calls': 'Звонков',
            'call_duration': 'Общая длительность (сек)',
            'avg_call_duration': 'Средняя длительность',
            'deals': 'Сделок',
            'deals_sum': 'Сумма сделок',
            'avg_deal_sum': 'Средняя сумма сделки',
            'leads': 'Лидов',
            'leads_sum': 'Сумма лидов'
        })

        df_export.to_excel(filename, index=False, engine='openpyxl')
        logger.info(f"\n[OK] Otchet sohranen: {filename}")
    else:
        logger.info("[INFO] Net dannyh")


if __name__ == '__main__':
    asyncio.run(main())
