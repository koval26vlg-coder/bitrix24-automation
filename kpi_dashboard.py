"""KPI-дашборд: динамика оценок менеджеров по накопленным отчетам bitnewton_sync.

Запуск:
    streamlit run kpi_dashboard.py

Читает reports/bitnewton_sync_report_*.json, дедуплицирует звонки по activity_id
(побеждает более свежий отчет) и показывает динамику KPI по неделям и менеджерам.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPORTS_DIR = Path(__file__).parent / "reports"

SCORE_COLUMNS = [
    "overall_score",
    "call_quality_score",
    "deal_quality_score",
    "crm_work_score",
    "call_checklist_percent",
]

SCORE_LABELS = {
    "overall_score": "Общий балл",
    "call_quality_score": "Качество звонка",
    "deal_quality_score": "Качество сделки",
    "crm_work_score": "Работа в CRM",
    "call_checklist_percent": "Чек-лист звонка, %",
}


@st.cache_data(ttl=300)
def load_calls() -> pd.DataFrame:
    files = sorted(REPORTS_DIR.glob("bitnewton_sync_report_*.json"))
    records: dict[str, dict] = {}

    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            activity_id = str(row.get("activity_id") or "")
            if not activity_id:
                continue
            # файлы отсортированы по имени (= по времени), поздний отчет побеждает
            records[activity_id] = {
                "activity_id": activity_id,
                "deal_id": str(row.get("deal_id") or ""),
                "manager_name": str(row.get("manager_name") or "Без менеджера").strip(),
                "start_time": row.get("start_time"),
                "duration_minutes": row.get("duration_minutes"),
                "first_response_sla_ok": row.get("first_response_sla_ok"),
                "asr_status": row.get("asr_status"),
                "error": row.get("error"),
                **{col: row.get(col) for col in SCORE_COLUMNS},
            }

    df = pd.DataFrame(records.values())
    if df.empty:
        return df

    # в отчетах встречаются времена и с таймзоной, и без — приводим к Москве
    df["start_time"] = (
        pd.to_datetime(df["start_time"], errors="coerce", utc=True)
        .dt.tz_convert("Europe/Moscow")
        .dt.tz_localize(None)
    )
    df = df.dropna(subset=["start_time"])
    for col in SCORE_COLUMNS + ["duration_minutes"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["week"] = df["start_time"].dt.to_period("W").dt.start_time
    return df


def main() -> None:
    st.set_page_config(page_title="KPI менеджеров", layout="wide")
    st.title("KPI менеджеров по звонкам")

    df = load_calls()
    if df.empty:
        st.warning(
            "Нет данных: в reports/ не найдено файлов bitnewton_sync_report_*.json "
            "с заполненными звонками."
        )
        return

    min_date = df["start_time"].min().date()
    max_date = df["start_time"].max().date()

    with st.sidebar:
        st.header("Фильтры")
        date_range = st.date_input(
            "Период",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        managers = sorted(df["manager_name"].unique())
        selected_managers = st.multiselect("Менеджеры", managers, default=managers)
        metric = st.selectbox(
            "Метрика динамики",
            SCORE_COLUMNS,
            format_func=lambda c: SCORE_LABELS[c],
        )

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        df = df[(df["start_time"].dt.date >= start) & (df["start_time"].dt.date <= end)]
    df = df[df["manager_name"].isin(selected_managers)]

    if df.empty:
        st.info("По выбранным фильтрам данных нет.")
        return

    sla_series = df["first_response_sla_ok"].dropna().astype(bool)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Звонков", len(df))
    col2.metric("Сделок", df["deal_id"].nunique())
    overall_avg = df["overall_score"].mean()
    col3.metric("Средний общий балл", f"{overall_avg:.1f}" if pd.notna(overall_avg) else "—")
    col4.metric(
        "SLA первого ответа",
        f"{100 * sla_series.mean():.0f}%" if not sla_series.empty else "—",
    )

    st.subheader(f"Динамика по неделям: {SCORE_LABELS[metric]}")
    weekly = (
        df.dropna(subset=[metric])
        .groupby(["week", "manager_name"])[metric]
        .mean()
        .reset_index()
        .pivot(index="week", columns="manager_name", values=metric)
    )
    if weekly.empty:
        st.info("Для выбранной метрики нет заполненных значений.")
    else:
        st.line_chart(weekly)

    st.subheader("Средние баллы по менеджерам")
    per_manager = (
        df.groupby("manager_name")[SCORE_COLUMNS]
        .mean()
        .round(1)
        .rename(columns=SCORE_LABELS)
        .sort_values("Общий балл", ascending=False)
    )
    per_manager["Звонков"] = df.groupby("manager_name").size()
    st.dataframe(per_manager, use_container_width=True)

    st.subheader("Последние звонки")
    latest = df.sort_values("start_time", ascending=False).head(50)
    display_columns = {
        "start_time": "Время",
        "manager_name": "Менеджер",
        "deal_id": "Сделка",
        "duration_minutes": "Длительность, мин",
        "overall_score": "Общий балл",
        "call_quality_score": "Качество звонка",
        "asr_status": "ASR",
        "error": "Ошибка",
    }
    st.dataframe(
        latest[list(display_columns)].rename(columns=display_columns),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
