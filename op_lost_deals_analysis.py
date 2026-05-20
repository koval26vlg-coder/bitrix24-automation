"""
Анализ проигранных сделок в воронке ОП
"""

import asyncio
from datetime import datetime

import pandas as pd

import config
from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)



async def fetch_lost_deals_data():
    api = Bitrix24API()
    try:
        if not await api.test_connection():
            return None, None

        logger.info("=== ANALIZ PROIGRANNYH SDELOK V VORONKE OP ===\n")

        # Находим воронку ОП
        categories_result = await api.call("crm.category.list", {"entityTypeId": 2})
        categories = categories_result.get("result", {}).get("categories", [])

        op_category_id = None
        for cat in categories:
            if "ОП" in cat.get("name", ""):
                op_category_id = cat.get("id")
                break

        # Получаем проигранные сделки
        logger.info("Poluchenie proigrannyh sdelok...")
        filter_params = {"STAGE_ID": "C1:LOSE"}
        if op_category_id:
            filter_params["CATEGORY_ID"] = op_category_id

        result = await api.call(
            "crm.deal.list",
            {
                "filter": filter_params,
                "select": [
                    "ID",
                    "TITLE",
                    "STAGE_ID",
                    "DATE_CREATE",
                    "DATE_MODIFY",
                    "CLOSEDATE",
                    "ASSIGNED_BY_ID",
                    "OPPORTUNITY",
                    "COMMENTS",
                    "SOURCE_ID",
                    "CONTACT_ID",
                    "COMPANY_ID",
                ],
            },
        )

        lost_deals = result.get("result", [])

        # Получаем информацию о менеджерах
        users_result = await api.call("user.get", {"FILTER": {"ACTIVE": True}})
        users = {
            u["ID"]: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            for u in users_result.get("result", [])
        }
        return lost_deals, users
    finally:
        await api.aclose()


lost_deals, users = asyncio.run(fetch_lost_deals_data())
if lost_deals is None:
    exit()
logger.info(f"Vsego proigrannyh sdelok: {len(lost_deals)}\n")

if not lost_deals:
    logger.info("Proigrannyh sdelok ne naydeno")
    exit()

# Преобразуем в DataFrame
df = pd.DataFrame(lost_deals)
df["OPPORTUNITY"] = pd.to_numeric(df["OPPORTUNITY"], errors="coerce").fillna(0)
df["DATE_CREATE"] = pd.to_datetime(df["DATE_CREATE"], utc=True, errors="coerce").dt.tz_localize(
    None
)
df["DATE_MODIFY"] = pd.to_datetime(df["DATE_MODIFY"], utc=True, errors="coerce").dt.tz_localize(
    None
)
df["CLOSEDATE"] = pd.to_datetime(df["CLOSEDATE"], utc=True, errors="coerce").dt.tz_localize(None)

# Добавляем имена менеджеров
df["MANAGER_NAME"] = df["ASSIGNED_BY_ID"].apply(lambda x: users.get(str(x), f"ID {x}"))

# Рассчитываем время жизни сделки
df["LIFETIME_DAYS"] = (df["DATE_MODIFY"] - df["DATE_CREATE"]).dt.days

logger.info("=" * 80)
logger.info("1. OBSHCHAYA STATISTIKA")
logger.info("=" * 80)

logger.info(f"\nVsego proigrannyh sdelok: {len(df)}")
logger.info(f"Obshchaya summa poter: {df['OPPORTUNITY'].sum():,.2f} rub")
logger.info(f"Srednyaya summa proigrannoy sdelki: {df['OPPORTUNITY'].mean():,.2f} rub")
logger.info(f"Maksimalnaya poterya: {df['OPPORTUNITY'].max():,.2f} rub")
logger.info(f"Srednee vremya zhizni sdelki: {df['LIFETIME_DAYS'].mean():.1f} dney")

logger.info("\n" + "=" * 80)
logger.info("2. RASPREDELENIE PO MENEDZHERAM")
logger.info("=" * 80)

manager_stats = (
    df.groupby("MANAGER_NAME")
    .agg({"ID": "count", "OPPORTUNITY": "sum", "LIFETIME_DAYS": "mean"})
    .round(2)
)

manager_stats.columns = ["Количество", "Сумма потерь", "Среднее время (дни)"]
manager_stats = manager_stats.sort_values("Количество", ascending=False)

logger.info("\nProigrannye sdelki po menedzheram:")
logger.info(manager_stats.to_string())

logger.info("\n" + "=" * 80)
logger.info("3. RASPREDELENIE PO ISTOCHNIKAM")
logger.info("=" * 80)

source_stats = df.groupby("SOURCE_ID").agg({"ID": "count", "OPPORTUNITY": "sum"}).round(2)

source_stats.columns = ["Количество", "Сумма потерь"]
source_stats = source_stats.sort_values("Количество", ascending=False)

logger.info("\nProigrannye sdelki po istochnikam:")
logger.info(source_stats.to_string())

logger.info("\n" + "=" * 80)
logger.info("4. DINAMIKA PROIGRYSHEY")
logger.info("=" * 80)

# По месяцам
df["CLOSE_MONTH"] = df["DATE_MODIFY"].dt.to_period("M")
monthly_stats = df.groupby("CLOSE_MONTH").agg({"ID": "count", "OPPORTUNITY": "sum"}).round(2)

monthly_stats.columns = ["Количество", "Сумма потерь"]

logger.info("\nProigryshi po mesyacam:")
logger.info(monthly_stats.to_string())

logger.info("\n" + "=" * 80)
logger.info("5. ANALIZ VREMENI ZHIZNI SDELOK")
logger.info("=" * 80)

# Группируем по времени жизни
logger.info("\nRaspredelenie po vremeni zhizni:")
logger.info(f"  0-7 dney: {len(df[df['LIFETIME_DAYS'] <= 7])} sdelok")
logger.info(
    f"  8-30 dney: {len(df[(df['LIFETIME_DAYS'] > 7) & (df['LIFETIME_DAYS'] <= 30)])} sdelok"
)
logger.info(
    f"  31-90 dney: {len(df[(df['LIFETIME_DAYS'] > 30) & (df['LIFETIME_DAYS'] <= 90)])} sdelok"
)
logger.info(f"  90+ dney: {len(df[df['LIFETIME_DAYS'] > 90])} sdelok")

logger.info("\n" + "=" * 80)
logger.info("6. DETALNIY SPISOK PROIGRANNYH SDELOK")
logger.info("=" * 80)

logger.info("\nPoslednie 14 proigrannyh sdelok:\n")

for _idx, deal in df.sort_values("DATE_MODIFY", ascending=False).iterrows():
    logger.info(f"ID: {deal['ID']}")
    logger.info(f"  Nazvanie: {deal.get('TITLE', 'Bez nazvaniya')}")
    logger.info(f"  Menedzher: {deal['MANAGER_NAME']}")
    logger.info(f"  Summa: {deal['OPPORTUNITY']:,.2f} rub")
    logger.info(
        f"  Sozdano: {deal['DATE_CREATE'].strftime('%Y-%m-%d') if pd.notna(deal['DATE_CREATE']) else 'N/A'}"  # noqa: E501
    )
    logger.info(
        f"  Zakryto: {deal['DATE_MODIFY'].strftime('%Y-%m-%d') if pd.notna(deal['DATE_MODIFY']) else 'N/A'}"  # noqa: E501
    )
    logger.info(f"  Vremya zhizni: {deal['LIFETIME_DAYS']} dney")
    logger.info(f"  Istochnik: {deal.get('SOURCE_ID', 'N/A')}")
    logger.info()

logger.info("=" * 80)
logger.info("7. REKOMENDACII")
logger.info("=" * 80)

# Анализируем паттерны
top_loser_manager = manager_stats.index[0] if len(manager_stats) > 0 else None
top_loser_source = source_stats.index[0] if len(source_stats) > 0 else None
avg_lifetime = df["LIFETIME_DAYS"].mean()

logger.info("\nNa osnove analiza:")

if top_loser_manager:
    manager_count = manager_stats.loc[top_loser_manager, "Количество"]
    logger.info(f"\n1. MENEDZHER: {top_loser_manager}")
    logger.info(f"   - Bolshe vsego proigrannyh sdelok: {int(manager_count)}")
    logger.info("   - Rekomendaciya: Provesti analiz prichin s menedzherom")
    logger.info("   - Vozmozhno nuzhno obuchenie ili izmenit podkhod")

if top_loser_source:
    source_count = source_stats.loc[top_loser_source, "Количество"]
    logger.info(f"\n2. ISTOCHNIK: {top_loser_source}")
    logger.info(f"   - Bolshe vsego proigryshey iz etogo istochnika: {int(source_count)}")
    logger.info("   - Rekomendaciya: Proverit kachestvo lidov iz etogo istochnika")
    logger.info("   - Vozmozhno nuzhna kvalifikaciya na ranney stadii")

logger.info("\n3. VREMYA ZHIZNI SDELOK:")
logger.info(f"   - Srednee vremya do proigrysha: {avg_lifetime:.1f} dney")
if avg_lifetime < 7:
    logger.info("   - Sdelki proigryvayutsya bystro - vozmozhno nekachestvennye lidy")
elif avg_lifetime > 90:
    logger.info("   - Sdelki dolgo visyat - nuzhno uluchshit rabotu s vozrazheniyami")
else:
    logger.info("   - Normalnoe vremya zhizni sdelok")

# Экспорт
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"{config.REPORTS_DIR}/op_lost_deals_analysis_{timestamp}.xlsx"

df_export = df.copy()
df_export.to_excel(filename, index=False, engine="openpyxl")

logger.info(f"\n[OK] Detalniy otchet sohranen: {filename}")
