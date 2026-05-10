from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


class DealsManager:
    def __init__(self):
        self.api = Bitrix24API()

    def get_deals(self, filter_params: dict = None) -> list:
        """Получить список сделок с фильтрацией"""
        params = {
            'select': [
                'ID', 'TITLE', 'STAGE_ID', 'PROBABILITY',
                'OPPORTUNITY', 'CURRENCY_ID', 'TYPE_ID',
                'ASSIGNED_BY_ID', 'CREATED_BY_ID', 'DATE_CREATE',
                'DATE_MODIFY', 'BEGINDATE', 'CLOSEDATE',
                'CLOSED', 'COMMENTS', 'COMPANY_ID', 'CONTACT_ID'
            ],
            'order': {'DATE_CREATE': 'DESC'}
        }

        if filter_params:
            params['filter'] = filter_params

        deals = self.api.get_all('crm.deal.list', params)
        return deals

    def get_deals_by_date(self, days: int = 7) -> list:
        """Получить сделки за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        filter_params = {
            '>=DATE_CREATE': date_from
        }

        return self.get_deals(filter_params)

    def get_deals_by_stage(self, stage_id: str) -> list:
        """Получить сделки по стадии"""
        filter_params = {
            'STAGE_ID': stage_id
        }

        return self.get_deals(filter_params)

    def get_open_deals(self) -> list:
        """Получить открытые сделки"""
        filter_params = {
            'CLOSED': 'N'
        }

        return self.get_deals(filter_params)

    def get_won_deals(self, days: int = 30) -> list:
        """Получить выигранные сделки за период"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        filter_params = {
            'CLOSED': 'Y',
            'STAGE_ID': 'WON',
            '>=CLOSEDATE': date_from
        }

        return self.get_deals(filter_params)

    def export_to_excel(self, deals: list, filename: str = None):
        """Экспорт сделок в Excel"""
        if not filename:
            filename = f"{config.REPORTS_DIR}/deals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        df = pd.DataFrame(deals)

        if not df.empty:
            if 'DATE_CREATE' in df.columns:
                df['DATE_CREATE'] = pd.to_datetime(df['DATE_CREATE'], utc=True).dt.tz_localize(None)
            if 'DATE_MODIFY' in df.columns:
                df['DATE_MODIFY'] = pd.to_datetime(df['DATE_MODIFY'], utc=True).dt.tz_localize(None)
            if 'BEGINDATE' in df.columns:
                df['BEGINDATE'] = pd.to_datetime(df['BEGINDATE'], utc=True).dt.tz_localize(None)
            if 'CLOSEDATE' in df.columns:
                df['CLOSEDATE'] = pd.to_datetime(df['CLOSEDATE'], utc=True).dt.tz_localize(None)

        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"[OK] Otchet sohranen: {filename}")
        return filename

    def get_statistics(self, deals: list) -> dict:
        """Получить статистику по сделкам"""
        if not deals:
            return {}

        df = pd.DataFrame(deals)

        stats = {
            'total': len(deals),
            'by_stage': df['STAGE_ID'].value_counts().to_dict() if 'STAGE_ID' in df else {},
            'open_count': len(df[df['CLOSED'] == 'N']) if 'CLOSED' in df else 0,
            'closed_count': len(df[df['CLOSED'] == 'Y']) if 'CLOSED' in df else 0,
            'total_opportunity': df['OPPORTUNITY'].astype(float).sum() if 'OPPORTUNITY' in df else 0,
            'avg_opportunity': df['OPPORTUNITY'].astype(float).mean() if 'OPPORTUNITY' in df else 0,
            'avg_probability': df['PROBABILITY'].astype(float).mean() if 'PROBABILITY' in df else 0
        }

        return stats


def main():
    print("=== Отчет по сделкам Bitrix24 ===\n")

    manager = DealsManager()

    if not manager.api.test_connection():
        return

    print("\nВыберите действие:")
    print("1. Все сделки за последние 7 дней")
    print("2. Все сделки за последние 30 дней")
    print("3. Только открытые сделки")
    print("4. Выигранные сделки за месяц")
    print("5. Все сделки")

    choice = input("\nВаш выбор (1-5): ").strip()

    if choice == '1':
        deals = manager.get_deals_by_date(7)
        title = "Сделки за последние 7 дней"
    elif choice == '2':
        deals = manager.get_deals_by_date(30)
        title = "Сделки за последние 30 дней"
    elif choice == '3':
        deals = manager.get_open_deals()
        title = "Открытые сделки"
    elif choice == '4':
        deals = manager.get_won_deals(30)
        title = "Выигранные сделки за месяц"
    elif choice == '5':
        deals = manager.get_deals()
        title = "Все сделки"
    else:
        print("Неверный выбор")
        return

    print(f"\n{title}: найдено {len(deals)} записей")

    if deals:
        stats = manager.get_statistics(deals)
        print(f"\nСтатистика:")
        print(f"  Всего: {stats['total']}")
        print(f"  Открытых: {stats['open_count']}")
        print(f"  Закрытых: {stats['closed_count']}")
        print(f"  Общая сумма: {stats['total_opportunity']:.2f}")
        print(f"  Средняя сумма: {stats['avg_opportunity']:.2f}")
        print(f"  Средняя вероятность: {stats['avg_probability']:.0f}%")

        if stats['by_stage']:
            print(f"\n  По стадиям:")
            for stage, count in stats['by_stage'].items():
                print(f"    {stage}: {count}")

        filename = manager.export_to_excel(deals)
        print(f"\n✓ Готово! Файл: {filename}")
    else:
        print("Сделки не найдены")


if __name__ == '__main__':
    main()
