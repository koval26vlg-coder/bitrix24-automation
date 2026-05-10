from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


class CustomPeriodReport:
    """Отчеты за произвольный период"""

    def __init__(self):
        self.api = Bitrix24API()

    def get_data_for_period(self, entity_type: str, date_from: str, date_to: str, manager_id: str = None):
        """
        Получить данные за период

        entity_type: 'leads', 'deals', 'contacts'
        date_from: 'YYYY-MM-DD'
        date_to: 'YYYY-MM-DD'
        manager_id: ID менеджера (опционально)
        """

        filter_params = {
            '>=DATE_CREATE': date_from,
            '<=DATE_CREATE': date_to
        }

        if manager_id:
            filter_params['ASSIGNED_BY_ID'] = manager_id

        if entity_type == 'leads':
            method = 'crm.lead.list'
            select = ['ID', 'TITLE', 'NAME', 'LAST_NAME', 'STATUS_ID',
                     'SOURCE_ID', 'DATE_CREATE', 'DATE_MODIFY', 'ASSIGNED_BY_ID',
                     'PHONE', 'EMAIL', 'OPPORTUNITY', 'CURRENCY_ID']
        elif entity_type == 'deals':
            method = 'crm.deal.list'
            select = ['ID', 'TITLE', 'STAGE_ID', 'CATEGORY_ID', 'DATE_CREATE',
                     'DATE_MODIFY', 'ASSIGNED_BY_ID', 'OPPORTUNITY', 'CURRENCY_ID',
                     'BEGINDATE', 'CLOSEDATE']
        elif entity_type == 'contacts':
            method = 'crm.contact.list'
            select = ['ID', 'NAME', 'LAST_NAME', 'DATE_CREATE', 'DATE_MODIFY',
                     'ASSIGNED_BY_ID', 'PHONE', 'EMAIL', 'TYPE_ID']
        else:
            return []

        params = {
            'select': select,
            'filter': filter_params,
            'order': {'DATE_CREATE': 'DESC'}
        }

        return self.api.get_all(method, params)

    def export_to_excel(self, data: list, filename: str, entity_type: str):
        """Экспорт в Excel"""
        if not data:
            print("[INFO] Net dannyh dlya eksporta")
            return None

        df = pd.DataFrame(data)

        # Обработка дат
        date_columns = ['DATE_CREATE', 'DATE_MODIFY', 'BEGINDATE', 'CLOSEDATE']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors='ignore').dt.tz_localize(None)

        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"[OK] Otchet sohranen: {filename}")
        return filename


def main():
    print("=== OTCHETY ZA PROIZVOLNYY PERIOD ===\n")

    reporter = CustomPeriodReport()

    if not reporter.api.test_connection():
        return

    # Выбор типа данных
    print("Vyberte tip dannyh:")
    print("1. Lidy")
    print("2. Sdelki")
    print("3. Kontakty")

    choice = input("\nVash vybor (1-3): ").strip()

    entity_map = {'1': 'leads', '2': 'deals', '3': 'contacts'}
    entity_type = entity_map.get(choice, 'leads')
    entity_name = {'leads': 'Lidy', 'deals': 'Sdelki', 'contacts': 'Kontakty'}[entity_type]

    print(f"\nVybrano: {entity_name}")
    print("")

    # Выбор периода
    print("Vyberte period:")
    print("1. Poslednie 7 dney")
    print("2. Poslednie 30 dney")
    print("3. Tekushchiy mesyac")
    print("4. Predydushchiy mesyac")
    print("5. Proizvolnyy period (vvesti daty)")

    period_choice = input("\nVash vybor (1-5): ").strip()

    today = datetime.now()

    if period_choice == '1':
        date_from = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
        period_name = "7_dney"
    elif period_choice == '2':
        date_from = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
        period_name = "30_dney"
    elif period_choice == '3':
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
        period_name = "tekushchiy_mesyac"
    elif period_choice == '4':
        last_month = today.replace(day=1) - timedelta(days=1)
        date_from = last_month.replace(day=1).strftime('%Y-%m-%d')
        date_to = last_month.strftime('%Y-%m-%d')
        period_name = "predydushchiy_mesyac"
    elif period_choice == '5':
        print("\nVvedite daty v formate YYYY-MM-DD")
        date_from = input("Data nachala (naprimer 2026-04-01): ").strip()
        date_to = input("Data kontsa (naprimer 2026-04-27): ").strip()
        period_name = f"{date_from}_to_{date_to}"
    else:
        print("Nevernyy vybor")
        return

    print(f"\nPeriod: {date_from} - {date_to}")
    print("")

    # Выбор менеджера
    print("Filtrovat po menedzheru?")
    print("1. Vse menedzhery")
    print("2. Konkretnyy menedzher")

    manager_choice = input("\nVash vybor (1-2): ").strip()
    manager_id = None
    manager_name = "vse"

    if manager_choice == '2':
        manager_id = input("Vvedite ID menedzhera: ").strip()
        manager_name = f"manager_{manager_id}"

    print(f"\nPoluchenie dannyh...")

    # Получаем данные
    data = reporter.get_data_for_period(entity_type, date_from, date_to, manager_id)

    print(f"Naydeno: {len(data)} zapisey")

    if data:
        # Статистика
        print("\nStatistika:")
        print(f"  Vsego: {len(data)}")

        if entity_type in ['leads', 'deals']:
            total_sum = sum(float(item.get('OPPORTUNITY', 0) or 0) for item in data)
            avg_sum = total_sum / len(data) if data else 0
            print(f"  Summa: {total_sum:.2f}")
            print(f"  Srednyaya: {avg_sum:.2f}")

        # Экспорт
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{config.REPORTS_DIR}/{entity_type}_{period_name}_{manager_name}_{timestamp}.xlsx"

        reporter.export_to_excel(data, filename, entity_type)
        print(f"\n[OK] Gotovo! Fayl: {filename}")
    else:
        print("\n[INFO] Dannye ne naydeny za ukazannyy period")


if __name__ == '__main__':
    main()
