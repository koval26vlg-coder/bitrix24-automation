
from logging_setup import get_logger

logger = get_logger(__name__)
"""
Статистика звонков менеджеров с анализом эффективности (автоматический режим)
"""

from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config
import sys


class ManagersCallStats:
    """Анализ статистики звонков менеджеров"""

    def __init__(self):
        self.api = Bitrix24API()

    def get_managers_list(self) -> dict:
        """Получить список менеджеров"""
        result = self.api.call('user.get', {
            'FILTER': {'ACTIVE': True}
        })

        managers = {}
        for user in result.get('result', []):
            managers[user['ID']] = {
                'name': f"{user.get('NAME', '')} {user.get('LAST_NAME', '')}".strip(),
                'email': user.get('EMAIL', '')
            }

        return managers

    def get_calls_stats(self, days: int = 30) -> list:
        """Получить статистику звонков за период"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Получаем все звонки
        result = self.api.call('voximplant.statistic.get', {
            'FILTER': {
                '>=CALL_START_DATE': date_from
            }
        })

        calls = result.get('result', [])
        return calls

    def get_deals_stats(self, days: int = 30) -> list:
        """Получить статистику сделок за период"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        result = self.api.call('crm.deal.list', {
            'filter': {
                '>=DATE_CREATE': date_from
            },
            'select': ['ID', 'TITLE', 'STAGE_ID', 'ASSIGNED_BY_ID',
                      'OPPORTUNITY', 'DATE_CREATE', 'CLOSEDATE']
        })

        deals = result.get('result', [])
        return deals

    def analyze_manager_performance(self, calls: list, deals: list, managers: dict) -> pd.DataFrame:
        """Анализ эффективности менеджеров"""

        stats = {}

        # Анализ звонков
        for call in calls:
            manager_id = str(call.get('PORTAL_USER_ID', ''))

            if manager_id not in stats:
                stats[manager_id] = {
                    'manager_id': manager_id,
                    'manager_name': managers.get(manager_id, {}).get('name', f'ID {manager_id}'),
                    'total_calls': 0,
                    'outgoing_calls': 0,
                    'incoming_calls': 0,
                    'total_duration': 0,
                    'calls_with_records': 0,
                    'successful_calls': 0,
                    'failed_calls': 0
                }

            stats[manager_id]['total_calls'] += 1

            call_type = int(call.get('CALL_TYPE', 0))
            if call_type == 1:  # Входящий
                stats[manager_id]['incoming_calls'] += 1
            elif call_type == 2:  # Исходящий
                stats[manager_id]['outgoing_calls'] += 1

            duration = int(call.get('CALL_DURATION', 0))
            stats[manager_id]['total_duration'] += duration

            if call.get('RECORD_FILE_ID'):
                stats[manager_id]['calls_with_records'] += 1

            failed_code = int(call.get('CALL_FAILED_CODE', 200))
            if failed_code == 200:
                stats[manager_id]['successful_calls'] += 1
            else:
                stats[manager_id]['failed_calls'] += 1

        # Анализ сделок
        for deal in deals:
            manager_id = str(deal.get('ASSIGNED_BY_ID', ''))

            if manager_id in stats:
                if 'total_deals' not in stats[manager_id]:
                    stats[manager_id]['total_deals'] = 0
                    stats[manager_id]['deals_sum'] = 0
                    stats[manager_id]['won_deals'] = 0

                stats[manager_id]['total_deals'] += 1

                opportunity = float(deal.get('OPPORTUNITY', 0) or 0)
                stats[manager_id]['deals_sum'] += opportunity

                stage_id = deal.get('STAGE_ID', '')
                if 'WON' in stage_id or 'SUCCESS' in stage_id:
                    stats[manager_id]['won_deals'] += 1

        # Преобразуем в DataFrame
        df = pd.DataFrame(list(stats.values()))

        if not df.empty:
            # Добавляем расчётные метрики
            df['avg_call_duration'] = df['total_duration'] / df['total_calls']
            df['success_rate'] = (df['successful_calls'] / df['total_calls'] * 100).round(1)
            df['record_rate'] = (df['calls_with_records'] / df['total_calls'] * 100).round(1)

            if 'total_deals' in df.columns:
                df['avg_deal_sum'] = (df['deals_sum'] / df['total_deals']).fillna(0).round(2)
                df['conversion_rate'] = (df['won_deals'] / df['total_deals'] * 100).fillna(0).round(1)
            else:
                df['total_deals'] = 0
                df['deals_sum'] = 0
                df['won_deals'] = 0
                df['avg_deal_sum'] = 0
                df['conversion_rate'] = 0

            # Сортируем по количеству звонков
            df = df.sort_values('total_calls', ascending=False)

        return df

    def export_to_excel(self, df: pd.DataFrame, filename: str):
        """Экспорт в Excel с форматированием"""

        # Переименовываем колонки для читаемости
        columns_rename = {
            'manager_name': 'Менеджер',
            'total_calls': 'Всего звонков',
            'outgoing_calls': 'Исходящих',
            'incoming_calls': 'Входящих',
            'total_duration': 'Общая длительность (сек)',
            'avg_call_duration': 'Средняя длительность (сек)',
            'calls_with_records': 'Звонков с записью',
            'record_rate': 'Процент записей (%)',
            'successful_calls': 'Успешных звонков',
            'success_rate': 'Процент успеха (%)',
            'failed_calls': 'Неудачных звонков',
            'total_deals': 'Всего сделок',
            'deals_sum': 'Сумма сделок',
            'avg_deal_sum': 'Средняя сумма сделки',
            'won_deals': 'Выигранных сделок',
            'conversion_rate': 'Конверсия (%)'
        }

        df_export = df.copy()
        df_export = df_export[[col for col in columns_rename.keys() if col in df_export.columns]]
        df_export = df_export.rename(columns=columns_rename)

        # Округляем числа
        for col in df_export.columns:
            if df_export[col].dtype in ['float64', 'float32']:
                df_export[col] = df_export[col].round(2)

        df_export.to_excel(filename, index=False, engine='openpyxl')
        logger.info(f"[OK] Otchet sohranen: {filename}")


def main():
    logger.info("=== STATISTIKA ZVONKOV MENEDZHEROV ===\n")

    # Параметр из командной строки или по умолчанию 30 дней
    days = 30
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except:
            days = 30

    logger.info(f"Period: poslednie {days} dney\n")

    stats = ManagersCallStats()

    if not stats.api.test_connection():
        return

    logger.info(f"Poluchenie dannyh za poslednie {days} dney...")

    # Получаем данные
    managers = stats.get_managers_list()
    logger.info(f"Naydeno menedzherov: {len(managers)}")

    calls = stats.get_calls_stats(days)
    logger.info(f"Naydeno zvonkov: {len(calls)}")

    deals = stats.get_deals_stats(days)
    logger.info(f"Naydeno sdelok: {len(deals)}")

    # Анализируем
    logger.info("\nAnaliz effektivnosti...")
    df = stats.analyze_manager_performance(calls, deals, managers)

    if df.empty:
        logger.info("[INFO] Net dannyh dlya analiza")
        return

    # Выводим топ-5
    logger.info("\n=== TOP-5 MENEDZHEROV PO KOLICHESTVU ZVONKOV ===")
    logger.info(df[['manager_name', 'total_calls', 'avg_call_duration', 'success_rate']].head(5).to_string(index=False))

    if 'total_deals' in df.columns:
        logger.info("\n=== TOP-5 MENEDZHEROV PO SDELKAM ===")
        top_deals = df[df['total_deals'] > 0].sort_values('deals_sum', ascending=False)
        if not top_deals.empty:
            logger.info(top_deals[['manager_name', 'total_deals', 'deals_sum', 'conversion_rate']].head(5).to_string(index=False))

    # Экспорт
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{config.REPORTS_DIR}/managers_call_stats_{days}days_{timestamp}.xlsx"

    stats.export_to_excel(df, filename)
    logger.info(f"\n[OK] Polnyy otchet sohranen v: {filename}")


if __name__ == '__main__':
    main()
