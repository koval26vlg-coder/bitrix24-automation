"""
Полная расширенная аналитика по воронке ОП
"""

import asyncio
from datetime import datetime, timedelta

import pandas as pd

import config
from bitrix24_api import Bitrix24API
from logging_setup import get_logger

logger = get_logger(__name__)


async def main():
    api = Bitrix24API()

    async with api:
        if not await api.test_connection():
            return

        logger.info("=== POLNAYA ANALITIKA VORONKI OP ===\n")

        # Находим воронку ОП и список пользователей параллельно
        logger.info("Получение начальных данных...")
        categories_task = asyncio.create_task(api.call("crm.category.list", {"entityTypeId": 2}))
        users_task = asyncio.create_task(api.call("user.get", {"FILTER": {"ACTIVE": True}}))

        categories_result, users_result = await asyncio.gather(categories_task, users_task)

        categories = categories_result.get("result", {}).get("categories", [])
        op_category_id = None
        for cat in categories:
            if "ОП" in cat.get("name", ""):
                op_category_id = cat.get("id")
                logger.info(f"Воронка: {cat.get('name')} (ID={op_category_id})\n")
                break

        # Получаем все сделки в воронке ОП
        logger.info("Получение сделок...")
        filter_params = {"CATEGORY_ID": op_category_id} if op_category_id else {}

        # Используем get_all для надежности, если сделок много
        deals = await api.get_all(
            "crm.deal.list",
            {
                "filter": filter_params,
                "select": [
                    "ID",
                    "TITLE",
                    "STAGE_ID",
                    "CATEGORY_ID",
                    "DATE_CREATE",
                    "DATE_MODIFY",
                    "CLOSEDATE",
                    "ASSIGNED_BY_ID",
                    "OPPORTUNITY",
                    "CURRENCY_ID",
                    "BEGINDATE",
                    "CLOSED",
                ],
            },
        )

        logger.info(f"Всего сделок: {len(deals)}\n")

        if not deals:
            logger.info("Сделок не найдено")
            return

        # Информация о менеджерах
        users = {
            str(u["ID"]): f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            for u in users_result.get("result", [])
        }

        # Преобразуем в DataFrame
        df = pd.DataFrame(deals)

        # Конвертируем типы данных
        df["OPPORTUNITY"] = pd.to_numeric(df["OPPORTUNITY"], errors="coerce").fillna(0)
        df["DATE_CREATE"] = pd.to_datetime(
            df["DATE_CREATE"], utc=True, errors="coerce"
        ).dt.tz_localize(None)
        df["DATE_MODIFY"] = pd.to_datetime(
            df["DATE_MODIFY"], utc=True, errors="coerce"
        ).dt.tz_localize(None)
        df["CLOSEDATE"] = pd.to_datetime(df["CLOSEDATE"], utc=True, errors="coerce").dt.tz_localize(
            None
        )

        # Добавляем имена менеджеров
        df["MANAGER_NAME"] = df["ASSIGNED_BY_ID"].apply(lambda x: users.get(str(x), f"ID {x}"))

        # Добавляем периоды
        df["CREATE_DATE"] = df["DATE_CREATE"].dt.date
        df["CREATE_WEEK"] = df["DATE_CREATE"].dt.isocalendar().week
        df["CREATE_MONTH"] = df["DATE_CREATE"].dt.to_period("M")

        logger.info("=" * 80)
        logger.info("1. DINAMIKA PO DNYAM")
        logger.info("=" * 80)

        # Группируем по дням за последние 30 дней
        date_30_days_ago = datetime.now() - timedelta(days=30)
        recent_deals = df[df["DATE_CREATE"] >= date_30_days_ago]

        if not recent_deals.empty:
            daily_stats = (
                recent_deals.groupby("CREATE_DATE")
                .agg({"ID": "count", "OPPORTUNITY": "sum"})
                .rename(columns={"ID": "Количество", "OPPORTUNITY": "Сумма"})
            )

            logger.info("\nСделки по дням (последние 30 дней):")
            logger.info(daily_stats.to_string())
        else:
            daily_stats = pd.DataFrame()
            logger.info("\nНет сделок за последние 30 дней")

        logger.info("\n" + "=" * 80)
        logger.info("2. DINAMIKA PO NEDELYAM")
        logger.info("=" * 80)

        if not recent_deals.empty:
            weekly_stats = (
                recent_deals.groupby("CREATE_WEEK")
                .agg({"ID": "count", "OPPORTUNITY": "sum"})
                .rename(columns={"ID": "Количество", "OPPORTUNITY": "Сумма"})
            )

            logger.info("\nСделки по неделям (последние 30 дней):")
            logger.info(weekly_stats.to_string())
        else:
            weekly_stats = pd.DataFrame()
            logger.info("\nНет сделок за последние 30 дней")

        logger.info("\n" + "=" * 80)
        logger.info("3. KONVERSIYA PO STADIYAM")
        logger.info("=" * 80)

        # Статистика по стадиям
        stage_stats = (
            df.groupby("STAGE_ID")
            .agg({"ID": "count", "OPPORTUNITY": "sum"})
            .rename(columns={"ID": "Количество", "OPPORTUNITY": "Сумма"})
        )

        stage_stats["Процент от общего"] = (stage_stats["Количество"] / len(df) * 100).round(1)
        stage_stats["Средний чек"] = (stage_stats["Сумма"] / stage_stats["Количество"]).round(2)

        logger.info("\nСтатистика по стадиям:")
        logger.info(stage_stats.to_string())

        # Воронка конверсии
        logger.info("\n\nВоронка конверсии:")
        total_deals = len(df)
        in_progress = len(df[df["STAGE_ID"].str.contains("EXECUTING", na=False)])
        final_invoice = len(df[df["STAGE_ID"].str.contains("FINAL_INVOICE", na=False)])
        closed_won = len(
            df[(df["CLOSED"] == "Y") & (~df["STAGE_ID"].str.contains("LOSE", na=False))]
        )
        closed_lost = len(df[df["STAGE_ID"].str.contains("LOSE", na=False)])

        logger.info(f"  Всего сделок: {total_deals} (100%)")
        logger.info(f"  В работе: {in_progress} ({in_progress/total_deals*100:.1f}%)")
        logger.info(f"  Финальный счет: {final_invoice} ({final_invoice/total_deals*100:.1f}%)")
        logger.info(f"  Выиграно: {closed_won} ({closed_won/total_deals*100:.1f}%)")
        logger.info(f"  Проиграно: {closed_lost} ({closed_lost/total_deals*100:.1f}%)")

        if in_progress > 0:
            logger.info(f"\n  Конверсия в финальный счет: {final_invoice/in_progress*100:.1f}%")
        if final_invoice > 0:
            logger.info(f"  Конверсия в выигрыш: {closed_won/final_invoice*100:.1f}%")

        logger.info("\n" + "=" * 80)
        logger.info("4. DETALNIY ANALIZ PO MENEDZHERAM")
        logger.info("=" * 80)

        manager_stats = (
            df.groupby("MANAGER_NAME")
            .agg({"ID": "count", "OPPORTUNITY": ["sum", "mean", "max"]})
            .round(2)
        )

        manager_stats.columns = ["Количество сделок", "Общая сумма", "Средний чек", "Макс сделка"]
        manager_stats = manager_stats.sort_values("Общая сумма", ascending=False)

        logger.info("\nСтатистика по менеджерам:")
        logger.info(manager_stats.to_string())

        # Детальная статистика по каждому менеджеру
        logger.info("\n\nДетальная статистика TOP-5 менеджеров:")
        for idx, (manager, row) in enumerate(manager_stats.head(5).iterrows(), 1):
            manager_deals = df[df["MANAGER_NAME"] == manager]

            won = len(
                manager_deals[
                    (manager_deals["CLOSED"] == "Y")
                    & (~manager_deals["STAGE_ID"].str.contains("LOSE", na=False))
                ]
            )
            lost = len(manager_deals[manager_deals["STAGE_ID"].str.contains("LOSE", na=False)])
            in_work = len(manager_deals) - won - lost

            logger.info(f"\n{idx}. {manager}")
            logger.info(f"   Сделок: {int(row['Количество сделок'])}")
            logger.info(f"   Сумма: {row['Общая сумма']:,.2f} руб")
            logger.info(f"   Средний чек: {row['Средний чек']:,.2f} руб")
            logger.info(f"   Выиграно: {won}, Проиграно: {lost}, В работе: {in_work}")
            if (won + lost) > 0:
                win_rate = won / (won + lost) * 100
                logger.info(f"   Win rate: {win_rate:.1f}%")

        logger.info("\n" + "=" * 80)
        logger.info("5. SRAVNENIE S PREDYDUSHCHIMI PERIODAMI")
        logger.info("=" * 80)

        current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_deals = df[df["DATE_CREATE"] >= current_month]

        prev_month = (current_month - timedelta(days=1)).replace(day=1)
        prev_month_end = current_month - timedelta(seconds=1)
        prev_month_deals = df[
            (df["DATE_CREATE"] >= prev_month) & (df["DATE_CREATE"] <= prev_month_end)
        ]

        current_month_label = current_month.strftime("%Y-%m")
        logger.info(f"\nТекущий месяц ({current_month_label}):")
        logger.info(f"  Сделок: {len(current_month_deals)}")
        logger.info(f"  Сумма: {current_month_deals['OPPORTUNITY'].sum():,.2f} руб")
        if not current_month_deals.empty:
            logger.info(f"  Средний чек: {current_month_deals['OPPORTUNITY'].mean():,.2f} руб")

        prev_month_label = prev_month.strftime("%Y-%m")
        logger.info(f"\nПредыдущий месяц ({prev_month_label}):")
        logger.info(f"  Сделок: {len(prev_month_deals)}")
        logger.info(f"  Сумма: {prev_month_deals['OPPORTUNITY'].sum():,.2f} руб")
        if not prev_month_deals.empty:
            logger.info(f"  Средний чек: {prev_month_deals['OPPORTUNITY'].mean():,.2f} руб")

        # Сравнение
        if len(prev_month_deals) > 0:
            deals_change = (
                (len(current_month_deals) - len(prev_month_deals)) / len(prev_month_deals) * 100
            )
            prev_sum = prev_month_deals["OPPORTUNITY"].sum()
            if prev_sum > 0:
                sum_change = (current_month_deals["OPPORTUNITY"].sum() - prev_sum) / prev_sum * 100
                logger.info("\nИзменение (текущий vs предыдущий):")
                logger.info(f"  Количество сделок: {deals_change:+.1f}%")
                logger.info(f"  Сумма: {sum_change:+.1f}%")

        # Экспорт
        logger.info("\n" + "=" * 80)
        logger.info("EKSPORT DANNYH")
        logger.info("=" * 80)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{config.REPORTS_DIR}/op_full_analytics_{timestamp}.xlsx"

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Vse sdelki", index=False)
            if not daily_stats.empty:
                daily_stats.to_excel(writer, sheet_name="Po dnyam")
            if not weekly_stats.empty:
                weekly_stats.to_excel(writer, sheet_name="Po nedelyam")
            stage_stats.to_excel(writer, sheet_name="Po stadiyam")
            manager_stats.to_excel(writer, sheet_name="Po menedzheram")

        logger.info(f"\n[OK] Полный отчет сохранен: {filename}")


if __name__ == "__main__":
    asyncio.run(main())
