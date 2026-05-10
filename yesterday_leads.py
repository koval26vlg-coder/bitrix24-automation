"""
Лиды за вчерашний день
"""

from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta

api = Bitrix24API()

if not api.test_connection():
    exit()

# Вчерашний день
yesterday = datetime.now() - timedelta(days=1)
date_from = yesterday.strftime('%Y-%m-%d')
date_to = yesterday.strftime('%Y-%m-%d') + ' 23:59:59'

print(f"=== LIDY ZA {date_from} ===\n")

# Получаем лиды
result = api.call('crm.lead.list', {
    'filter': {
        '>=DATE_CREATE': date_from,
        '<=DATE_CREATE': date_to
    },
    'select': ['ID', 'TITLE', 'NAME', 'LAST_NAME', 'STATUS_ID',
               'SOURCE_ID', 'DATE_CREATE', 'ASSIGNED_BY_ID']
})

leads = result.get('result', [])

print(f"Vsego lidov: {len(leads)}\n")

if leads:
    print("Spisok lidov:")
    for lead in leads:
        name = f"{lead.get('NAME', '')} {lead.get('LAST_NAME', '')}".strip()
        if not name:
            name = lead.get('TITLE', 'Bez imeni')

        print(f"  ID: {lead.get('ID')}")
        print(f"    Imya: {name}")
        print(f"    Status: {lead.get('STATUS_ID')}")
        print(f"    Istochnik: {lead.get('SOURCE_ID')}")
        print(f"    Sozdano: {lead.get('DATE_CREATE')}")
        print()
else:
    print("Lidov ne naydeno")
