
from logging_setup import get_logger

logger = get_logger(__name__)
"""
Полная расширенная аналитика по воронке ОП
"""

from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
from collections import Counter
import config

api = Bitrix24API()

if not api.test_connection():
    exit()

logger.info("=== POLNAYA ANALITIKA VORONKI OP ===\n")

# Находим воронку ОП
categories_result = api.call('crm.category.list', {'entityTypeId': 2})
categories = categories_result.get('result', {}).get('categories', [])

op_category_id = None
for cat in categories:
    if 'ОП' in cat.get('name', ''):
        op_category_id = cat.get('id')
        logger.info(f"Voronka: {cat.get('name')} (ID={op_category_id})\n")
        break

# Получаем все сделки в воронке ОП
logger.info("Poluchenie sdelok...")
filter_params = {'CATEGORY_ID': op_category_id} if op_category_id else {}

result = api.call('crm.deal.list', {
    'filter': filter_params,
    'select': ['ID', 'TITLE', 'STAGE_ID', 'CATEGORY_ID', 'DATE_CREATE',
               'DATE_MODIFY', 'CLOSEDATE', 'ASSIGNED_BY_ID', 'OPPORTUNITY',
               'CURRENCY_ID', 'BEGINDATE', 'CLOSED']
})

deals = result.get('result', [])
logger.info(f"Vsego sdelok: {len(deals)}\n")

if not deals:
    logger.info("Sdelok ne naydeno")
    exit()

# Получаем информацию о менеджерах
logger.info("Poluchenie informacii o menedzherah...")
users_result = api.call('user.get', {'FILTER': {'ACTIVE': True}})
users = {u['ID']: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip() for u in users_result.get('result', [])}

# Преобразуем в DataFrame
df = pd.DataFrame(deals)

# Конвертируем типы данных
df['OPPORTUNITY'] = pd.to_numeric(df['OPPORTUNITY'], errors='coerce').fillna(0)
df['DATE_CREATE'] = pd.to_datetime(df['DATE_CREATE'], utc=True, errors='coerce').dt.tz_localize(None)
df['DATE_MODIFY'] = pd.to_datetime(df['DATE_MODIFY'], utc=True, errors='coerce').dt.tz_localize(None)
df['CLOSEDATE'] = pd.to_datetime(df['CLOSEDATE'], utc=True, errors='coerce').dt.tz_localize(None)

# Добавляем имена менеджеров
df['MANAGER_NAME'] = df['ASSIGNED_BY_ID'].apply(lambda x: users.get(str(x), f'ID {x}'))

# Добавляем периоды
df['CREATE_DATE'] = df['DATE_CREATE'].dt.date
df['CREATE_WEEK'] = df['DATE_CREATE'].dt.isocalendar().week
df['CREATE_MONTH'] = df['DATE_CREATE'].dt.to_period('M')

logger.info("="*80)
logger.info("1. DINAMIKA PO DNYAM")
logger.info("="*80)

# Группируем по дням за последние 30 дней
date_30_days_ago = datetime.now() - timedelta(days=30)
recent_deals = df[df['DATE_CREATE'] >= date_30_days_ago]

daily_stats = recent_deals.groupby('CREATE_DATE').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum'
}).rename(columns={'ID': 'Количество', 'OPPORTUNITY': 'Сумма'})

logger.info("\nSdelki po dnyam (poslednie 30 dney):")
logger.info(daily_stats.to_string())

logger.info("\n" + "="*80)
logger.info("2. DINAMIKA PO NEDELYAM")
logger.info("="*80)

weekly_stats = recent_deals.groupby('CREATE_WEEK').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum'
}).rename(columns={'ID': 'Количество', 'OPPORTUNITY': 'Сумма'})

logger.info("\nSdelki po nedelyam (poslednie 30 dney):")
logger.info(weekly_stats.to_string())

logger.info("\n" + "="*80)
logger.info("3. KONVERSIYA PO STADIYAM")
logger.info("="*80)

# Статистика по стадиям
stage_stats = df.groupby('STAGE_ID').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum'
}).rename(columns={'ID': 'Количество', 'OPPORTUNITY': 'Сумма'})

stage_stats['Процент от общего'] = (stage_stats['Количество'] / len(df) * 100).round(1)
stage_stats['Средний чек'] = (stage_stats['Сумма'] / stage_stats['Количество']).round(2)

logger.info("\nStatistika po stadiyam:")
logger.info(stage_stats.to_string())

# Воронка конверсии (упрощённая)
logger.info("\n\nVoronka konversii:")
total_deals = len(df)
in_progress = len(df[df['STAGE_ID'].str.contains('EXECUTING', na=False)])
final_invoice = len(df[df['STAGE_ID'].str.contains('FINAL_INVOICE', na=False)])
closed_won = len(df[(df['CLOSED'] == 'Y') & (~df['STAGE_ID'].str.contains('LOSE', na=False))])
closed_lost = len(df[df['STAGE_ID'].str.contains('LOSE', na=False)])

logger.info(f"  Vsego sdelok: {total_deals} (100%)")
logger.info(f"  V rabote: {in_progress} ({in_progress/total_deals*100:.1f}%)")
logger.info(f"  Finalnyy schet: {final_invoice} ({final_invoice/total_deals*100:.1f}%)")
logger.info(f"  Vyigrano: {closed_won} ({closed_won/total_deals*100:.1f}%)")
logger.info(f"  Proigrano: {closed_lost} ({closed_lost/total_deals*100:.1f}%)")

if in_progress > 0:
    logger.info(f"\n  Konversiya v finalnyy schet: {final_invoice/in_progress*100:.1f}%")
if final_invoice > 0:
    logger.info(f"  Konversiya v vyigrysh: {closed_won/final_invoice*100:.1f}%")

logger.info("\n" + "="*80)
logger.info("4. DETALNIY ANALIZ PO MENEDZHERAM")
logger.info("="*80)

manager_stats = df.groupby('MANAGER_NAME').agg({
    'ID': 'count',
    'OPPORTUNITY': ['sum', 'mean', 'max']
}).round(2)

manager_stats.columns = ['Количество сделок', 'Общая сумма', 'Средний чек', 'Макс сделка']
manager_stats = manager_stats.sort_values('Общая сумма', ascending=False)

logger.info("\nStatistika po menedzheram:")
logger.info(manager_stats.to_string())

# Детальная статистика по каждому менеджеру
logger.info("\n\nDetalnaya statistika TOP-5 menedzherov:")
for idx, (manager, row) in enumerate(manager_stats.head(5).iterrows(), 1):
    manager_deals = df[df['MANAGER_NAME'] == manager]

    won = len(manager_deals[(manager_deals['CLOSED'] == 'Y') & (~manager_deals['STAGE_ID'].str.contains('LOSE', na=False))])
    lost = len(manager_deals[manager_deals['STAGE_ID'].str.contains('LOSE', na=False)])
    in_work = len(manager_deals) - won - lost

    logger.info(f"\n{idx}. {manager}")
    logger.info(f"   Sdelok: {int(row['Количество сделок'])}")
    logger.info(f"   Summa: {row['Общая сумма']:,.2f} rub")
    logger.info(f"   Sredniy chek: {row['Средний чек']:,.2f} rub")
    logger.info(f"   Vyigrano: {won}, Proigrano: {lost}, V rabote: {in_work}")
    if (won + lost) > 0:
        win_rate = won / (won + lost) * 100
        logger.info(f"   Win rate: {win_rate:.1f}%")

logger.info("\n" + "="*80)
logger.info("5. SRAVNENIE S PREDYDUSHCHIMI PERIODAMI")
logger.info("="*80)

# Текущий месяц
current_month = datetime.now().replace(day=1)
current_month_deals = df[df['DATE_CREATE'] >= current_month]

# Предыдущий месяц
prev_month = (current_month - timedelta(days=1)).replace(day=1)
prev_month_end = current_month - timedelta(days=1)
prev_month_deals = df[(df['DATE_CREATE'] >= prev_month) & (df['DATE_CREATE'] <= prev_month_end)]

# Позапрошлый месяц
prev_prev_month = (prev_month - timedelta(days=1)).replace(day=1)
prev_prev_month_end = prev_month - timedelta(days=1)
prev_prev_month_deals = df[(df['DATE_CREATE'] >= prev_prev_month) & (df['DATE_CREATE'] <= prev_prev_month_end)]

logger.info(f"\nTekushchiy mesyac ({current_month.strftime('%Y-%m')}):")
logger.info(f"  Sdelok: {len(current_month_deals)}")
logger.info(f"  Summa: {current_month_deals['OPPORTUNITY'].sum():,.2f} rub")
logger.info(f"  Sredniy chek: {current_month_deals['OPPORTUNITY'].mean():,.2f} rub")

logger.info(f"\nPredydushchiy mesyac ({prev_month.strftime('%Y-%m')}):")
logger.info(f"  Sdelok: {len(prev_month_deals)}")
logger.info(f"  Summa: {prev_month_deals['OPPORTUNITY'].sum():,.2f} rub")
logger.info(f"  Sredniy chek: {prev_month_deals['OPPORTUNITY'].mean():,.2f} rub")

logger.info(f"\nPozaproshlyy mesyac ({prev_prev_month.strftime('%Y-%m')}):")
logger.info(f"  Sdelok: {len(prev_prev_month_deals)}")
logger.info(f"  Summa: {prev_prev_month_deals['OPPORTUNITY'].sum():,.2f} rub")
logger.info(f"  Sredniy chek: {prev_prev_month_deals['OPPORTUNITY'].mean():,.2f} rub")

# Сравнение
if len(prev_month_deals) > 0:
    deals_change = ((len(current_month_deals) - len(prev_month_deals)) / len(prev_month_deals) * 100)
    sum_change = ((current_month_deals['OPPORTUNITY'].sum() - prev_month_deals['OPPORTUNITY'].sum()) / prev_month_deals['OPPORTUNITY'].sum() * 100)

    logger.info(f"\nIzmenenie (tekushchiy vs predydushchiy):")
    logger.info(f"  Kolichestvo sdelok: {deals_change:+.1f}%")
    logger.info(f"  Summa: {sum_change:+.1f}%")

# Последние 7 дней vs предыдущие 7 дней
last_7_days = datetime.now() - timedelta(days=7)
prev_7_days = datetime.now() - timedelta(days=14)

last_week_deals = df[df['DATE_CREATE'] >= last_7_days]
prev_week_deals = df[(df['DATE_CREATE'] >= prev_7_days) & (df['DATE_CREATE'] < last_7_days)]

logger.info(f"\n\nPoslednie 7 dney:")
logger.info(f"  Sdelok: {len(last_week_deals)}")
logger.info(f"  Summa: {last_week_deals['OPPORTUNITY'].sum():,.2f} rub")

logger.info(f"\nPredydushchie 7 dney:")
logger.info(f"  Sdelok: {len(prev_week_deals)}")
logger.info(f"  Summa: {prev_week_deals['OPPORTUNITY'].sum():,.2f} rub")

if len(prev_week_deals) > 0:
    week_deals_change = ((len(last_week_deals) - len(prev_week_deals)) / len(prev_week_deals) * 100)
    week_sum_change = ((last_week_deals['OPPORTUNITY'].sum() - prev_week_deals['OPPORTUNITY'].sum()) / prev_week_deals['OPPORTUNITY'].sum() * 100)

    logger.info(f"\nIzmenenie:")
    logger.info(f"  Kolichestvo sdelok: {week_deals_change:+.1f}%")
    logger.info(f"  Summa: {week_sum_change:+.1f}%")

# Экспорт в Excel с несколькими листами
logger.info("\n" + "="*80)
logger.info("EKSPORT DANNYH")
logger.info("="*80)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
filename = f"{config.REPORTS_DIR}/op_full_analytics_{timestamp}.xlsx"

with pd.ExcelWriter(filename, engine='openpyxl') as writer:
    # Лист 1: Все сделки
    df_export = df.copy()
    df_export.to_excel(writer, sheet_name='Vse sdelki', index=False)

    # Лист 2: По дням
    daily_stats.to_excel(writer, sheet_name='Po dnyam')

    # Лист 3: По неделям
    weekly_stats.to_excel(writer, sheet_name='Po nedelyam')

    # Лист 4: По стадиям
    stage_stats.to_excel(writer, sheet_name='Po stadiyam')

    # Лист 5: По менеджерам
    manager_stats.to_excel(writer, sheet_name='Po menedzheram')

logger.info(f"\n[OK] Polnyy otchet sohranen: {filename}")
logger.info("\nOtchet soderzhit 5 listov:")
logger.info("  1. Vse sdelki - polnye dannye")
logger.info("  2. Po dnyam - dinamika po dnyam")
logger.info("  3. Po nedelyam - dinamika po nedelyam")
logger.info("  4. Po stadiyam - konversiya")
logger.info("  5. Po menedzheram - effektivnost")
