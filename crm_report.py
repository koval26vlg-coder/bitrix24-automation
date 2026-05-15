from crm_leads import LeadsManager
from crm_deals import DealsManager
from crm_contacts import ContactsManager
from datetime import datetime
import pandas as pd
import config

from logging_setup import get_logger

logger = get_logger(__name__)


class CRMReportGenerator:
    def __init__(self):
        self.leads_manager = LeadsManager()
        self.deals_manager = DealsManager()
        self.contacts_manager = ContactsManager()

    def generate_full_report(self, days: int = 30):
        """Генерация полного отчета по CRM"""
        logger.info(f"=== Полный отчет CRM за последние {days} дней ===\n")

        if not self.leads_manager.api.test_connection():
            return

        logger.info("\n1. Получение лидов...")
        leads = self.leads_manager.get_leads_by_date(days)
        leads_stats = self.leads_manager.get_statistics(leads)
        logger.info(f"   Найдено лидов: {len(leads)}")

        logger.info("\n2. Получение сделок...")
        deals = self.deals_manager.get_deals_by_date(days)
        deals_stats = self.deals_manager.get_statistics(deals)
        logger.info(f"   Найдено сделок: {len(deals)}")

        logger.info("\n3. Получение контактов...")
        contacts = self.contacts_manager.get_contacts_by_date(days)
        contacts_stats = self.contacts_manager.get_statistics(contacts)
        logger.info(f"   Найдено контактов: {len(contacts)}")

        logger.info("\n" + "="*50)
        logger.info("СВОДНАЯ СТАТИСТИКА")
        logger.info("="*50)

        logger.info(f"\n📊 ЛИДЫ:")
        logger.info(f"   Всего: {leads_stats.get('total', 0)}")
        logger.info(f"   Общая сумма: {leads_stats.get('total_opportunity', 0):.2f}")
        logger.info(f"   Средняя сумма: {leads_stats.get('avg_opportunity', 0):.2f}")
        if leads_stats.get('by_status'):
            logger.info(f"   По статусам:")
            for status, count in leads_stats['by_status'].items():
                logger.info(f"     • {status}: {count}")

        logger.info(f"\n💼 СДЕЛКИ:")
        logger.info(f"   Всего: {deals_stats.get('total', 0)}")
        logger.info(f"   Открытых: {deals_stats.get('open_count', 0)}")
        logger.info(f"   Закрытых: {deals_stats.get('closed_count', 0)}")
        logger.info(f"   Общая сумма: {deals_stats.get('total_opportunity', 0):.2f}")
        logger.info(f"   Средняя сумма: {deals_stats.get('avg_opportunity', 0):.2f}")
        logger.info(f"   Средняя вероятность: {deals_stats.get('avg_probability', 0):.0f}%")
        if deals_stats.get('by_stage'):
            logger.info(f"   По стадиям:")
            for stage, count in deals_stats['by_stage'].items():
                logger.info(f"     • {stage}: {count}")

        logger.info(f"\n👥 КОНТАКТЫ:")
        logger.info(f"   Всего: {contacts_stats.get('total', 0)}")
        logger.info(f"   С телефоном: {contacts_stats.get('with_phone', 0)}")
        logger.info(f"   С email: {contacts_stats.get('with_email', 0)}")
        logger.info(f"   С компанией: {contacts_stats.get('with_company', 0)}")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        logger.info("\n" + "="*50)
        logger.info("ЭКСПОРТ В EXCEL")
        logger.info("="*50)

        if leads:
            leads_file = self.leads_manager.export_to_excel(
                leads,
                f"{config.REPORTS_DIR}/report_leads_{timestamp}.xlsx"
            )

        if deals:
            deals_file = self.deals_manager.export_to_excel(
                deals,
                f"{config.REPORTS_DIR}/report_deals_{timestamp}.xlsx"
            )

        if contacts:
            contacts_file = self.contacts_manager.export_to_excel(
                contacts,
                f"{config.REPORTS_DIR}/report_contacts_{timestamp}.xlsx"
            )

        summary_file = self.create_summary_excel(
            leads_stats, deals_stats, contacts_stats, timestamp
        )

        logger.info(f"\n✓ Все отчеты сохранены в папке: {config.REPORTS_DIR}/")
        logger.info(f"✓ Сводный отчет: {summary_file}")

    def create_summary_excel(self, leads_stats, deals_stats, contacts_stats, timestamp):
        """Создание сводного Excel файла"""
        filename = f"{config.REPORTS_DIR}/report_summary_{timestamp}.xlsx"

        summary_data = {
            'Метрика': [
                'Лиды - Всего',
                'Лиды - Общая сумма',
                'Лиды - Средняя сумма',
                '',
                'Сделки - Всего',
                'Сделки - Открытых',
                'Сделки - Закрытых',
                'Сделки - Общая сумма',
                'Сделки - Средняя сумма',
                'Сделки - Средняя вероятность',
                '',
                'Контакты - Всего',
                'Контакты - С телефоном',
                'Контакты - С email',
                'Контакты - С компанией'
            ],
            'Значение': [
                leads_stats.get('total', 0),
                leads_stats.get('total_opportunity', 0),
                leads_stats.get('avg_opportunity', 0),
                '',
                deals_stats.get('total', 0),
                deals_stats.get('open_count', 0),
                deals_stats.get('closed_count', 0),
                deals_stats.get('total_opportunity', 0),
                deals_stats.get('avg_opportunity', 0),
                f"{deals_stats.get('avg_probability', 0):.0f}%",
                '',
                contacts_stats.get('total', 0),
                contacts_stats.get('with_phone', 0),
                contacts_stats.get('with_email', 0),
                contacts_stats.get('with_company', 0)
            ]
        }

        df = pd.DataFrame(summary_data)
        df.to_excel(filename, index=False, engine='openpyxl')

        return filename


def main():
    generator = CRMReportGenerator()

    logger.info("\nВыберите период отчета:")
    logger.info("1. За последние 7 дней")
    logger.info("2. За последние 30 дней")
    logger.info("3. За последние 90 дней")

    choice = input("\nВаш выбор (1-3): ").strip()

    if choice == '1':
        days = 7
    elif choice == '2':
        days = 30
    elif choice == '3':
        days = 90
    else:
        logger.info("Неверный выбор, используется 30 дней")
        days = 30

    generator.generate_full_report(days)


if __name__ == '__main__':
    main()
