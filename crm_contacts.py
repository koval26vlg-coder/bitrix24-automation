from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


class ContactsManager:
    def __init__(self):
        self.api = Bitrix24API()

    def get_contacts(self, filter_params: dict = None) -> list:
        """Получить список контактов с фильтрацией"""
        params = {
            'select': [
                'ID', 'NAME', 'LAST_NAME', 'SECOND_NAME',
                'POST', 'COMPANY_ID', 'ASSIGNED_BY_ID',
                'CREATED_BY_ID', 'DATE_CREATE', 'DATE_MODIFY',
                'PHONE', 'EMAIL', 'WEB', 'IM', 'COMMENTS'
            ],
            'order': {'DATE_CREATE': 'DESC'}
        }

        if filter_params:
            params['filter'] = filter_params

        contacts = self.api.get_all('crm.contact.list', params)
        return contacts

    def get_contacts_by_date(self, days: int = 7) -> list:
        """Получить контакты за последние N дней"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        filter_params = {
            '>=DATE_CREATE': date_from
        }

        return self.get_contacts(filter_params)

    def get_contact_by_id(self, contact_id: int) -> dict:
        """Получить контакт по ID"""
        result = self.api.call('crm.contact.get', {'id': contact_id})
        return result.get('result', {})

    def search_contacts(self, query: str) -> list:
        """Поиск контактов по имени, email или телефону"""
        filter_params = {
            '%NAME': query
        }

        return self.get_contacts(filter_params)

    def export_to_excel(self, contacts: list, filename: str = None):
        """Экспорт контактов в Excel"""
        if not filename:
            filename = f"{config.REPORTS_DIR}/contacts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        processed_contacts = []
        for contact in contacts:
            processed = contact.copy()

            if 'PHONE' in processed and isinstance(processed['PHONE'], list):
                processed['PHONE'] = ', '.join([p.get('VALUE', '') for p in processed['PHONE']])

            if 'EMAIL' in processed and isinstance(processed['EMAIL'], list):
                processed['EMAIL'] = ', '.join([e.get('VALUE', '') for e in processed['EMAIL']])

            processed_contacts.append(processed)

        df = pd.DataFrame(processed_contacts)

        if not df.empty:
            if 'DATE_CREATE' in df.columns:
                df['DATE_CREATE'] = pd.to_datetime(df['DATE_CREATE'], utc=True).dt.tz_localize(None)
            if 'DATE_MODIFY' in df.columns:
                df['DATE_MODIFY'] = pd.to_datetime(df['DATE_MODIFY'], utc=True).dt.tz_localize(None)

        df.to_excel(filename, index=False, engine='openpyxl')
        print(f"[OK] Otchet sohranen: {filename}")
        return filename

    def get_statistics(self, contacts: list) -> dict:
        """Получить статистику по контактам"""
        if not contacts:
            return {}

        df = pd.DataFrame(contacts)

        stats = {
            'total': len(contacts),
            'with_phone': sum(1 for c in contacts if c.get('PHONE')),
            'with_email': sum(1 for c in contacts if c.get('EMAIL')),
            'with_company': sum(1 for c in contacts if c.get('COMPANY_ID'))
        }

        return stats


def main():
    print("=== Отчет по контактам Bitrix24 ===\n")

    manager = ContactsManager()

    if not manager.api.test_connection():
        return

    print("\nВыберите действие:")
    print("1. Все контакты за последние 7 дней")
    print("2. Все контакты за последние 30 дней")
    print("3. Все контакты")
    print("4. Поиск контакта")

    choice = input("\nВаш выбор (1-4): ").strip()

    if choice == '1':
        contacts = manager.get_contacts_by_date(7)
        title = "Контакты за последние 7 дней"
    elif choice == '2':
        contacts = manager.get_contacts_by_date(30)
        title = "Контакты за последние 30 дней"
    elif choice == '3':
        contacts = manager.get_contacts()
        title = "Все контакты"
    elif choice == '4':
        query = input("Введите имя, email или телефон: ").strip()
        contacts = manager.search_contacts(query)
        title = f"Результаты поиска: {query}"
    else:
        print("Неверный выбор")
        return

    print(f"\n{title}: найдено {len(contacts)} записей")

    if contacts:
        stats = manager.get_statistics(contacts)
        print(f"\nСтатистика:")
        print(f"  Всего: {stats['total']}")
        print(f"  С телефоном: {stats['with_phone']}")
        print(f"  С email: {stats['with_email']}")
        print(f"  С компанией: {stats['with_company']}")

        filename = manager.export_to_excel(contacts)
        print(f"\n✓ Готово! Файл: {filename}")
    else:
        print("Контакты не найдены")


if __name__ == '__main__':
    main()
