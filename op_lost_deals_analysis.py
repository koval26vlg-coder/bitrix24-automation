"""
Анализ проигранных сделок в воронке ОП
"""

from bitrix24_api import Bitrix24API
from datetime import datetime
import pandas as pd
from collections import Counter
import config

api = Bitrix24API()

if not api.test_connection():
    exit()

print("=== ANALIZ PROIGRANNYH SDELOK V VORONKE OP ===\n")

# Находим воронку ОП
categories_result = api.call('crm.category.list', {'entityTypeId': 2})
categories = categories_result.get('result', {}).get('categories', [])

op_category_id = None
for cat in categories:
    if 'ОП' in cat.get('name', ''):
        op_category_id = cat.get('id')
        break

# Получаем проигранные сделки
print("Poluchenie proigrannyh sdelok...")
filter_params = {
    'STAGE_ID': 'C1:LOSE'
}
if op_category_id:
    filter_params['CATEGORY_ID'] = op_category_id

result = api.call('crm.deal.list', {
    'filter': filter_params,
    'select': ['ID', 'TITLE', 'STAGE_ID', 'DATE_CREATE', 'DATE_MODIFY',
               'CLOSEDATE', 'ASSIGNED_BY_ID', 'OPPORTUNITY', 'COMMENTS',
               'SOURCE_ID', 'CONTACT_ID', 'COMPANY_ID']
})

lost_deals = result.get('result', [])
print(f"Vsego proigrannyh sdelok: {len(lost_deals)}\n")

if not lost_deals:
    print("Proigrannyh sdelok ne naydeno")
    exit()

# Получаем информацию о менеджерах
users_result = api.call('user.get', {'FILTER': {'ACTIVE': True}})
users = {u['ID']: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip() for u in users_result.get('result', [])}

# Преобразуем в DataFrame
df = pd.DataFrame(lost_deals)
df['OPPORTUNITY'] = pd.to_numeric(df['OPPORTUNITY'], errors='coerce').fillna(0)
df['DATE_CREATE'] = pd.to_datetime(df['DATE_CREATE'], utc=True, errors='coerce').dt.tz_localize(None)
df['DATE_MODIFY'] = pd.to_datetime(df['DATE_MODIFY'], utc=True, errors='coerce').dt.tz_localize(None)
df['CLOSEDATE'] = pd.to_datetime(df['CLOSEDATE'], utc=True, errors='coerce').dt.tz_localize(None)

# Добавляем имена менеджеров
df['MANAGER_NAME'] = df['ASSIGNED_BY_ID'].apply(lambda x: users.get(str(x), f'ID {x}'))

# Рассчитываем время жизни сделки
df['LIFETIME_DAYS'] = (df['DATE_MODIFY'] - df['DATE_CREATE']).dt.days

print("="*80)
print("1. OBSHCHAYA STATISTIKA")
print("="*80)

print(f"\nVsego proigrannyh sdelok: {len(df)}")
print(f"Obshchaya summa poter: {df['OPPORTUNITY'].sum():,.2f} rub")
print(f"Srednyaya summa proigrannoy sdelki: {df['OPPORTUNITY'].mean():,.2f} rub")
print(f"Maksimalnaya poterya: {df['OPPORTUNITY'].max():,.2f} rub")
print(f"Srednee vremya zhizni sdelki: {df['LIFETIME_DAYS'].mean():.1f} dney")

print("\n" + "="*80)
print("2. RASPREDELENIE PO MENEDZHERAM")
print("="*80)

manager_stats = df.groupby('MANAGER_NAME').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum',
    'LIFETIME_DAYS': 'mean'
}).round(2)

manager_stats.columns = ['Количество', 'Сумма потерь', 'Среднее время (дни)']
manager_stats = manager_stats.sort_values('Количество', ascending=False)

print("\nProigrannye sdelki po menedzheram:")
print(manager_stats.to_string())

print("\n" + "="*80)
print("3. RASPREDELENIE PO ISTOCHNIKAM")
print("="*80)

source_stats = df.groupby('SOURCE_ID').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum'
}).round(2)

source_stats.columns = ['Количество', 'Сумма потерь']
source_stats = source_stats.sort_values('Количество', ascending=False)

print("\nProigrannye sdelki po istochnikam:")
print(source_stats.to_string())

print("\n" + "="*80)
print("4. DINAMIKA PROIGRYSHEY")
print("="*80)

# По месяцам
df['CLOSE_MONTH'] = df['DATE_MODIFY'].dt.to_period('M')
monthly_stats = df.groupby('CLOSE_MONTH').agg({
    'ID': 'count',
    'OPPORTUNITY': 'sum'
}).round(2)

monthly_stats.columns = ['Количество', 'Сумма потерь']

print("\nProigryshi po mesyacam:")
print(monthly_stats.to_string())

print("\n" + "="*80)
print("5. ANALIZ VREMENI ZHIZNI SDELOK")
print("="*80)

# Группируем по времени жизни
print("\nRaspredelenie po vremeni zhizni:")
print(f"  0-7 dney: {len(df[df['LIFETIME_DAYS'] <= 7])} sdelok")
print(f"  8-30 dney: {len(df[(df['LIFETIME_DAYS'] > 7) & (df['LIFETIME_DAYS'] <= 30)])} sdelok")
print(f"  31-90 dney: {len(df[(df['LIFETIME_DAYS'] > 30) & (df['LIFETIME_DAYS'] <= 90)])} sdelok")
print(f"  90+ dney: {len(df[df['LIFETIME_DAYS'] > 90])} sdelok")

print("\n" + "="*80)
print("6. DETALNIY SPISOK PROIGRANNYH SDELOK")
print("="*80)

print("\nPoslednie 14 proigrannyh sdelok:\n")

for idx, deal in df.sort_values('DATE_MODIFY', ascending=False).iterrows():
    print(f"ID: {deal['ID']}")
    print(f"  Nazvanie: {deal.get('TITLE', 'Bez nazvaniya')}")
    print(f"  Menedzher: {deal['MANAGER_NAME']}")
    print(f"  Summa: {deal['OPPORTUNITY']:,.2f} rub")
    print(f"  Sozdano: {deal['DATE_CREATE'].strftime('%Y-%m-%d') if pd.notna(deal['DATE_CREATE']) else 'N/A'}")
    print(f"  Zakryto: {deal['DATE_MODIFY'].strftime('%Y-%m-%d') if pd.notna(deal['DATE_MODIFY']) else 'N/A'}")
    print(f"  Vremya zhizni: {deal['LIFETIME_DAYS']} dney")
    print(f"  Istochnik: {deal.get('SOURCE_ID', 'N/A')}")
    print()

print("="*80)
print("7. REKOMENDACII")
print("="*80)

# Анализируем паттерны
top_loser_manager = manager_stats.index[0] if len(manager_stats) > 0 else None
top_loser_source = source_stats.index[0] if len(source_stats) > 0 else None
avg_lifetime = df['LIFETIME_DAYS'].mean()

print("\nNa osnove analiza:")

if top_loser_manager:
    manager_count = manager_stats.loc[top_loser_manager, 'Количество']
    print(f"\n1. MENEDZHER: {top_loser_manager}")
    print(f"   - Bolshe vsego proigrannyh sdelok: {int(manager_count)}")
    print(f"   - Rekomendaciya: Provesti analiz prichin s menedzherom")
    print(f"   - Vozmozhno nuzhno obuchenie ili izmenit podkhod")

if top_loser_source:
    source_count = source_stats.loc[top_loser_source, 'Количество']
    print(f"\n2. ISTOCHNIK: {top_loser_source}")
    print(f"   - Bolshe vsego proigryshey iz etogo istochnika: {int(source_count)}")
    print(f"   - Rekomendaciya: Proverit kachestvo lidov iz etogo istochnika")
    print(f"   - Vozmozhno nuzhna kvalifikaciya na ranney stadii")

print(f"\n3. VREMYA ZHIZNI SDELOK:")
print(f"   - Srednee vremya do proigrysha: {avg_lifetime:.1f} dney")
if avg_lifetime < 7:
    print(f"   - Sdelki proigryvayutsya bystro - vozmozhno nekachestvennye lidy")
elif avg_lifetime > 90:
    print(f"   - Sdelki dolgo visyat - nuzhno uluchshit rabotu s vozrazheniyami")
else:
    print(f"   - Normalnoe vremya zhizni sdelok")

# Экспорт
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
filename = f"{config.REPORTS_DIR}/op_lost_deals_analysis_{timestamp}.xlsx"

df_export = df.copy()
df_export.to_excel(filename, index=False, engine='openpyxl')

print(f"\n[OK] Detalniy otchet sohranen: {filename}")
