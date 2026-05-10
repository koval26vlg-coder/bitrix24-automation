from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


class LeadsManager:
    def __init__(self):
        self.api = Bitrix24API()

    def get_leads(self, filter_params: dict = None) -> list:
        """Получить список лидов с фильтрацией"""
        params = {
            'select': [
                'ID', 'TITLE', 'NAME', 'LAST_NAME', 'STATUS_ID',
                'SOURCE_ID', 'OPPORTUNITY', 'CURRENCY_ID',
                'ASSIGNED_BY_ID', 'CREATED_BY_ID', 'DATE_CREATE',
                'DATE_MODIFY', 'PHONE', 'EMAIL', 'COMMENTS'
            ],
            'order': {'DATE_CREATE': 'DESC'}
        }

        if filter_params:
            params['filter'] = filter_params

        leads = self.api.get_all('crm.lead.list', params)
        return leads

    def get_leads_by_date(self, days: int = 7) -> list:
        """Получить лиды за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        filter_params = {
            '>=DATE_CREATE': date_from
        }

        return self.get_leads(filter_params)

    def get_leads_by_status(self, status_id: str) -> list:
        """Получить лиды по статусу"""
        filter_params = {
            'STATUS_ID': status_id
        }

        return self.get_leads(filter_params)

    def get_new_leads(self) -> list:
        """Получить новые лиды (статус NEW)"""
        return self.get_leads_by_status('NEW')

    def export_to_excel(self, leads: list, filename: str = None):
        """Экспорт лидов в Excel"""
        if not filename:
            filename = f"{config.REPORTS_DIR}/leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        df = pd.DataFrame(leads)

        if not df.empty:
            if 'DATE_CREATE' in df.columns:
                df['DATE_CREATE'] = pd.to_datetime(df['DATE_CREATE'], utc=True).dt.tz_localize(None)
            if 'DATE_MODIFY' in df.columns:
                df['DATE_MODIFY'] = pd.to_datetime(df['DATE_MODIFY'], utc=True).dt.tz_localize(None)

        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"[OK] Otchet sohranen: {filename}")
        return filename

    def get_statistics(self, leads: list) -> dict:
        """Получить статистику по лидам"""
        if not leads:
            return {}

        df = pd.DataFrame(leads)

        stats = {
            'total': len(leads),
            'by_status': df['STATUS_ID'].value_counts().to_dict() if 'STATUS_ID' in df else {},
            'by_source': df['SOURCE_ID'].value_counts().to_dict() if 'SOURCE_ID' in df else {},
            'total_opportunity': df['OPPORTUNITY'].astype(float).sum() if 'OPPORTUNITY' in df else 0,
            'avg_opportunity': df['OPPORTUNITY'].astype(float).mean() if 'OPPORTUNITY' in df else 0
        }

        return stats


def main():
    print("=== Отчет по лидам Bitrix24 ===\n")

    manager = LeadsManager()

    if not manager.api.test_connection():
        return

    print("\nВыберите действие:")
    print("1. Все лиды за последние 7 дней")
    print("2. Все лиды за последние 30 дней")
    print("3. Только новые лиды")
    print("4. Все лиды")

    choice = input("\nВаш выбор (1-4): ").strip()

    if choice == '1':
        leads = manager.get_leads_by_date(7)
        title = "Лиды за последние 7 дней"
    elif choice == '2':
        leads = manager.get_leads_by_date(30)
        title = "Лиды за последние 30 дней"
    elif choice == '3':
        leads = manager.get_new_leads()
        title = "Новые лиды"
    elif choice == '4':
        leads = manager.get_leads()
        title = "Все лиды"
    else:
        print("Неверный выбор")
        return

    print(f"\n{title}: найдено {len(leads)} записей")

    if leads:
        stats = manager.get_statistics(leads)
        print(f"\nСтатистика:")
        print(f"  Всего: {stats['total']}")
        print(f"  Общая сумма: {stats['total_opportunity']:.2f}")
        print(f"  Средняя сумма: {stats['avg_opportunity']:.2f}")

        if stats['by_status']:
            print(f"\n  По статусам:")
            for status, count in stats['by_status'].items():
                print(f"    {status}: {count}")

        filename = manager.export_to_excel(leads)
        print(f"\n[OK] Gotovo! Fayl: {filename}")
    else:
        print("Lidy ne naydeny")


if __name__ == '__main__':
    main()
