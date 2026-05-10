"""
Детальный анализ звонков с разбивкой по дням и клиентам
"""

from bitrix24_api import Bitrix24API
from datetime import datetime, timedelta
import pandas as pd
import config


def main():
    print("=== DETALNAYA STATISTIKA ZVONKOV ===\n")

    api = Bitrix24API()

    if not api.test_connection():
        return

    days = 30
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # Получаем звонки
    print(f"Poluchenie zvonkov za poslednie {days} dney...")
    calls_result = api.call('voximplant.statistic.get', {
        'FILTER': {'>=CALL_START_DATE': date_from}
    })
    calls = calls_result.get('result', [])
    print(f"Vsego zvonkov: {len(calls)}\n")

    if not calls:
        print("[INFO] Net zvonkov za period")
        return

    # Преобразуем в DataFrame
    df = pd.DataFrame(calls)

    # Преобразуем числовые поля
    df['CALL_DURATION'] = pd.to_numeric(df['CALL_DURATION'], errors='coerce').fillna(0)
    df['CALL_TYPE'] = pd.to_numeric(df['CALL_TYPE'], errors='coerce').fillna(0).astype(int)
    df['CALL_FAILED_CODE'] = pd.to_numeric(df['CALL_FAILED_CODE'], errors='coerce').fillna(0).astype(int)

    # Обработка дат
    df['CALL_START_DATE'] = pd.to_datetime(df['CALL_START_DATE'], utc=True).dt.tz_localize(None)
    df['date'] = df['CALL_START_DATE'].dt.date
    df['time'] = df['CALL_START_DATE'].dt.time

    # Типы звонков
    df['call_type_name'] = df['CALL_TYPE'].map({
        1: 'Vhodyashchiy',
        2: 'Ishodyashchiy',
        3: 'Vhodyashchiy (propushchennyy)',
        4: 'Obratnyy zvonok'
    })

    # Статус звонка
    df['status'] = df['CALL_FAILED_CODE'].apply(lambda x: 'Uspeshnyy' if x == 200 else 'Neudachnyy')

    # Длительность в минутах
    df['duration_min'] = (df['CALL_DURATION'] / 60).round(2)

    # Статистика по дням
    print("=== STATISTIKA PO DNYAM ===\n")
    daily_stats = df.groupby('date').agg({
        'ID': 'count',
        'CALL_DURATION': 'sum',
        'duration_min': 'sum'
    }).rename(columns={'ID': 'calls', 'CALL_DURATION': 'total_seconds'})
    daily_stats['avg_duration'] = (daily_stats['total_seconds'] / daily_stats['calls']).round(1)
    print(daily_stats.to_string())

    # Статистика по типам звонков
    print("\n\n=== STATISTIKA PO TIPAM ZVONKOV ===\n")
    type_stats = df.groupby('call_type_name').agg({
        'ID': 'count',
        'CALL_DURATION': 'sum',
        'duration_min': 'sum'
    }).rename(columns={'ID': 'calls', 'CALL_DURATION': 'total_seconds'})
    type_stats['avg_duration'] = (type_stats['total_seconds'] / type_stats['calls']).round(1)
    print(type_stats.to_string())

    # Статистика по клиентам (топ-10)
    print("\n\n=== TOP-10 KLIENTOV PO KOLICHESTVU ZVONKOV ===\n")
    client_stats = df.groupby('PHONE_NUMBER').agg({
        'ID': 'count',
        'CALL_DURATION': 'sum',
        'duration_min': 'sum'
    }).rename(columns={'ID': 'calls', 'CALL_DURATION': 'total_seconds'})
    client_stats = client_stats.sort_values('calls', ascending=False).head(10)
    print(client_stats.to_string())

    # Экспорт детального отчёта
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Основной отчёт
    df_export = df[[
        'CALL_START_DATE', 'PHONE_NUMBER', 'call_type_name',
        'CALL_DURATION', 'duration_min', 'status',
        'CRM_ENTITY_TYPE', 'CRM_ENTITY_ID'
    ]].copy()

    df_export = df_export.rename(columns={
        'CALL_START_DATE': 'Дата и время',
        'PHONE_NUMBER': 'Номер телефона',
        'call_type_name': 'Тип звонка',
        'CALL_DURATION': 'Длительность (сек)',
        'duration_min': 'Длительность (мин)',
        'status': 'Статус',
        'CRM_ENTITY_TYPE': 'Тип сущности CRM',
        'CRM_ENTITY_ID': 'ID сущности CRM'
    })

    filename = f"{config.REPORTS_DIR}/detailed_calls_report_{timestamp}.xlsx"

    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df_export.to_excel(writer, sheet_name='Vse zvonki', index=False)
        daily_stats.to_excel(writer, sheet_name='Po dnyam')
        type_stats.to_excel(writer, sheet_name='Po tipam')
        client_stats.to_excel(writer, sheet_name='Po klientam')

    print(f"\n[OK] Detalniy otchet sohranen: {filename}")

    # Общая статистика
    print("\n\n=== OBSHCHAYA STATISTIKA ===")
    print(f"Vsego zvonkov: {len(df)}")
    print(f"Obshchaya dlitelnost: {df['duration_min'].sum():.1f} min")
    print(f"Srednyaya dlitelnost: {df['CALL_DURATION'].mean():.1f} sek")
    print(f"Uspeshnyh zvonkov: {len(df[df['status'] == 'Uspeshnyy'])}")
    print(f"Zvonkov s zapisyu: {len(df[df['RECORD_FILE_ID'].notna()])}")
    print(f"Unikalnyh klientov: {df['PHONE_NUMBER'].nunique()}")


if __name__ == '__main__':
    main()
