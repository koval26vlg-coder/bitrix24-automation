"""
Статистика лидов за вчерашний день
"""

from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
from collections import Counter

api = Bitrix24API()

if not api.test_connection():
    exit()

# Вчерашний день
yesterday = datetime.now() - timedelta(days=1)
date_from = yesterday.strftime('%Y-%m-%d')
date_to = yesterday.strftime('%Y-%m-%d') + ' 23:59:59'

print(f"=== STATISTIKA LIDOV ZA {date_from} ===\n")

# Получаем лиды
result = api.call('crm.lead.list', {
    'filter': {
        '>=DATE_CREATE': date_from,
        '<=DATE_CREATE': date_to
    },
    'select': ['ID', 'STATUS_ID', 'SOURCE_ID']
})

leads = result.get('result', [])

print(f"Vsego lidov: {len(leads)}\n")

# Статистика по статусам
statuses = Counter([l.get('STATUS_ID') for l in leads])
print("Po statusam:")
for status, count in statuses.most_common():
    print(f"  {status}: {count}")

# Статистика по источникам
sources = Counter([l.get('SOURCE_ID') for l in leads])
print("\nPo istochnikam:")
for source, count in sources.most_common():
    print(f"  {source}: {count}")
