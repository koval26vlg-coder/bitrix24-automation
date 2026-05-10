import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
from bitrix24_api import Bitrix24API
from pipelines.bitnewton_sync import cleanup_old_outputs
from pipelines.reporting import kpi_profile_display
from pipelines.stages import DEFAULT_STAGE_NAMES


ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LATEST_JSON_REPORT = REPORTS_DIR / "latest_bitnewton_report.json"
LATEST_XLSX_REPORT = REPORTS_DIR / "latest_bitnewton_report.xlsx"
KPI_FILES = sorted([p.name for p in ROOT.glob("kpi_config*.json")])
LEAD_CATEGORY_NEW_FIELD = "UF_CRM_66571549AF539"
LEAD_CATEGORY_NEW_IBLOCK_ID = 61


def kpi_file_profile_name(filename: str) -> str:
    path = ROOT / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = data.get("profile") if isinstance(data, dict) else None
        if isinstance(profile, dict) and profile.get("name"):
            return str(profile.get("name"))
    except Exception:
        pass
    return Path(filename).stem.replace("kpi_config.", "").replace("kpi_config", "default")


def kpi_file_label(filename: str) -> str:
    title, _ = kpi_profile_display(kpi_file_profile_name(filename))
    return title or filename


def kpi_file_description(filename: str) -> str:
    _, explanation = kpi_profile_display(kpi_file_profile_name(filename))
    return explanation


def browser_user_data_dir(browser_name: str) -> Path:
    local = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    if browser_name == "edge":
        return local / "Microsoft" / "Edge" / "User Data"
    return local / "Google" / "Chrome" / "User Data"


@st.cache_data(ttl=300)
def list_browser_profiles(browser_name: str) -> list[dict]:
    user_data = browser_user_data_dir(browser_name)
    local_state = user_data / "Local State"
    profiles: list[dict] = []
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        cache = ((data.get("profile") or {}).get("info_cache") or {}) if isinstance(data, dict) else {}
        if isinstance(cache, dict):
            for directory, meta in cache.items():
                if not (user_data / directory).exists():
                    continue
                meta = meta if isinstance(meta, dict) else {}
                name = str(meta.get("name") or directory)
                email = str(meta.get("user_name") or "").strip()
                gaia = str(meta.get("gaia_name") or "").strip()
                details = ", ".join([x for x in [directory, email or gaia] if x])
                label = f"{name} ({details})" if details else name
                profiles.append({"directory": directory, "label": label})
    except Exception:
        pass

    if not profiles and (user_data / "Default").exists():
        profiles.append({"directory": "Default", "label": "Default"})
    if not profiles:
        profiles.append({"directory": "Default", "label": "Default"})

    profiles.sort(key=lambda p: (0 if p.get("directory") == "Default" else 1, str(p.get("label") or "")))
    return profiles


@st.cache_data(ttl=300)
def fetch_active_users() -> list[dict]:
    api = Bitrix24API()
    users: list[dict] = []
    start = 0
    while True:
        res = api.call("user.get", {"FILTER": {"ACTIVE": True}, "start": start})
        chunk = res.get("result", []) or []
        users.extend(chunk)
        next_start = res.get("next")
        if next_start is None:
            break
        try:
            start = int(next_start)
        except Exception:
            break
    users.sort(key=lambda u: ((u.get("LAST_NAME") or "").lower(), (u.get("NAME") or "").lower()))
    return users


def user_fio(u: dict) -> str:
    parts = [u.get("LAST_NAME"), u.get("NAME"), u.get("SECOND_NAME")]
    return " ".join([p for p in parts if p]).strip()


@st.cache_data(ttl=300)
def fetch_deal_categories() -> list[dict]:
    api = Bitrix24API()
    return api.call("crm.dealcategory.list", {}).get("result", []) or []


def stage_entity_id(category_id: Optional[int]) -> str:
    if category_id is None:
        return "DEAL_STAGE"
    try:
        cid = int(category_id)
    except Exception:
        cid = 0
    return "DEAL_STAGE" if cid == 0 else f"DEAL_STAGE_{cid}"


def fallback_stage_rows(category_ids: tuple[Optional[int], ...]) -> list[dict]:
    allowed_prefixes: set[str] = set()
    include_plain = False
    for category_id in category_ids:
        if category_id is None:
            include_plain = True
            continue
        try:
            cid = int(category_id)
        except Exception:
            cid = 0
        if cid == 0:
            include_plain = True
        else:
            allowed_prefixes.add(f"C{cid}:")

    rows: list[dict] = []
    for sort, (stage_id, name) in enumerate(DEFAULT_STAGE_NAMES.items(), start=1):
        sid = str(stage_id)
        is_plain = ":" not in sid
        if include_plain and is_plain:
            rows.append({"id": sid, "name": name, "sort": sort})
        elif any(sid.startswith(prefix) for prefix in allowed_prefixes):
            rows.append({"id": sid, "name": name, "sort": sort})
    return rows


@st.cache_data(ttl=300)
def fetch_deal_stages(category_ids: tuple[Optional[int], ...]) -> list[dict]:
    api = Bitrix24API()
    rows: list[dict] = []
    seen: set[str] = set()
    for category_id in category_ids:
        entity_id = stage_entity_id(category_id)
        res = api.call("crm.status.list", {"filter": {"ENTITY_ID": entity_id}, "order": {"SORT": "ASC"}})
        for row in res.get("result") or []:
            stage_id = str(row.get("STATUS_ID") or "").strip()
            name = str(row.get("NAME") or stage_id).strip()
            if not stage_id or stage_id in seen:
                continue
            seen.add(stage_id)
            try:
                sort = int(row.get("SORT") or 0)
            except Exception:
                sort = 0
            rows.append({"id": stage_id, "name": name, "sort": sort})

    if not rows:
        rows = fallback_stage_rows(category_ids)
    return sorted(rows, key=lambda r: (int(r.get("sort") or 0), str(r.get("name") or "")))


@st.cache_data(ttl=300)
def fetch_lead_categories_new() -> list[dict]:
    api = Bitrix24API()
    rows = api.get_all(
        "lists.element.get",
        {
            "IBLOCK_TYPE_ID": "lists",
            "IBLOCK_ID": LEAD_CATEGORY_NEW_IBLOCK_ID,
        },
    )
    out: list[dict] = []
    for row in rows:
        category_id = str((row or {}).get("ID") or "").strip()
        name = str((row or {}).get("NAME") or category_id).strip()
        if category_id and name:
            out.append({"id": category_id, "name": name})
    return sorted(out, key=lambda r: str(r.get("name") or ""))


def latest_report_file(pattern: str) -> Optional[Path]:
    files = sorted(REPORTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def available_report_json_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("latest_bitnewton_report.json", "bitnewton_sync_report_*.json", "bitnewton_reevaluated_report_*.json"):
        files.extend(REPORTS_DIR.glob(pattern))
    unique = {str(p.resolve()): p for p in files}
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def report_file_label(path: Path) -> str:
    modified = date.fromtimestamp(path.stat().st_mtime).isoformat()
    return f"{path.name} ({modified})"


def extract_top_delta(json_path: Path, limit: int = 5) -> list[dict]:
    try:
        rows = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return []
        ranked = sorted(
            [r for r in rows if isinstance(r, dict) and r.get("overall_score_delta") is not None],
            key=lambda x: abs(float(x.get("overall_score_delta") or 0.0)),
            reverse=True,
        )
        return ranked[:limit]
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def read_report_sheet(path_str: str, modified_ts: float, sheet_name: str, nrows: int = 30) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, nrows=nrows)
        return df.fillna("")
    except Exception:
        return pd.DataFrame()


def summary_value(summary_df: pd.DataFrame, metric: str) -> str:
    if summary_df.empty or "Показатель" not in summary_df.columns or "Значение" not in summary_df.columns:
        return ""
    rows = summary_df[summary_df["Показатель"].astype(str) == metric]
    if rows.empty:
        return ""
    return str(rows.iloc[0]["Значение"])


def run_pipeline(args: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "bitnewton_sync_to_api.py"), *args],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output.append(line)
        st.write(line.rstrip("\n"))
    return proc.wait()


@st.cache_data(ttl=3600, show_spinner=False)
def run_retention_cleanup() -> dict:
    return cleanup_old_outputs(REPORTS_DIR, keep_days=30)


st.set_page_config(page_title="Bitrix24 Call Automation", layout="wide")
retention_cleanup = run_retention_cleanup()
st.title("Bitrix24 — расшифровка звонков по выборке сделок")

st.caption(
    "Интерфейс управляет пайплайном: звонок → аудио → Bit.Newton → запись в Bitrix через telephony.call.attachtranscription → отчеты (JSON/Excel)."
)

with st.sidebar:
    removed_total = int(retention_cleanup.get("total") or 0) if isinstance(retention_cleanup, dict) else 0
    if removed_total:
        st.caption(
            "Автоочистка 30 дней: "
            f"удалено файлов {removed_total} "
            f"(отчеты {retention_cleanup.get('reports', 0)}, "
            f"аудио {retention_cleanup.get('audio', 0)}, "
            f"расшифровки {retention_cleanup.get('transcripts', 0)})."
        )
    else:
        st.caption("Автоочистка: отчеты, аудио и расшифровки старше 30 дней удаляются автоматически.")

    st.header("Фильтр сделок")
    mode = st.radio("Режим", ["Выборка сделок", "Одна сделка по URL"], index=0)
    selected_stage_ids: list[str] = []

    if mode == "Одна сделка по URL":
        deal_url = st.text_input("URL сделки", value="https://online-kassa.bitrix24.ru/crm/deal/details/104291/")
    else:
        st.subheader("Основные")
        title_like = st.text_input("Название (содержит)", value="")
        selected_lead_category_ids: list[str] = []

        lead_categories = []
        try:
            lead_categories = fetch_lead_categories_new()
        except Exception as e:
            st.warning(f"Не удалось загрузить категории лида (NEW): {e}")

        if lead_categories:
            lead_category_names = {str(c["id"]): str(c.get("name") or c["id"]) for c in lead_categories}
            selected_lead_category_ids = st.multiselect(
                "Категория лида (NEW)",
                options=[str(c["id"]) for c in lead_categories],
                default=[],
                format_func=lambda category_id: lead_category_names.get(str(category_id), str(category_id)),
                help="Если ничего не выбрано, категория лида не ограничивает выборку.",
            )

        cats = []
        try:
            cats = fetch_deal_categories()
        except Exception as e:
            st.warning(f"Не удалось загрузить воронки: {e}")
        cat_options = {c.get("NAME", str(c.get("ID"))): int(c.get("ID")) for c in cats if c.get("ID")}
        selected_cat_name = st.selectbox("Воронка (CATEGORY_ID)", options=["(любая)"] + list(cat_options.keys()), index=0)
        selected_cat_id = cat_options.get(selected_cat_name) if selected_cat_name != "(любая)" else None

        stage_category_ids: tuple[Optional[int], ...]
        if selected_cat_id is not None:
            stage_category_ids = (selected_cat_id,)
        else:
            all_category_ids = [int(c.get("ID")) for c in cats if c.get("ID")]
            stage_category_ids = tuple([0, *all_category_ids]) if all_category_ids else (0, 1)

        stages = []
        try:
            stages = fetch_deal_stages(stage_category_ids)
        except Exception as e:
            st.warning(f"Не удалось загрузить стадии сделок: {e}")
            stages = fallback_stage_rows(stage_category_ids)

        if stages:
            stage_names = {str(s["id"]): str(s.get("name") or s["id"]) for s in stages}
            selected_stage_ids = st.multiselect(
                "Стадия сделки",
                options=[str(s["id"]) for s in stages],
                default=[],
                format_func=lambda stage_id: stage_names.get(str(stage_id), str(stage_id)),
                help="Если ничего не выбрано, стадия не ограничивает выборку.",
            )

        col1, col2 = st.columns(2)
        with col1:
            date_preset = st.selectbox(
                "Дата создания",
                ["Не учитывать дату", "Произвольно", "Сегодня", "Вчера", "Последние 7 дней", "Последние 30 дней"],
                index=0,
            )
        with col2:
            if date_preset == "Произвольно":
                date_from = st.date_input("ОТ", value=date.today().replace(day=1))
                date_to = st.date_input("ДО", value=date.today())
            else:
                date_from = None
                date_to = None

        users = []
        try:
            users = fetch_active_users()
        except Exception as e:
            st.warning(f"Не удалось загрузить сотрудников из Bitrix24: {e}")

        if users:
            fio_to_id = {user_fio(u): str(u.get("ID")) for u in users if u.get("ID")}
            selected = st.multiselect("Ответственный (по ФИО)", options=list(fio_to_id.keys()), default=[])
            assigned_by = ",".join([fio_to_id[name] for name in selected])
        else:
            assigned_by = st.text_input("ID менеджеров (через запятую)", value="")

    st.divider()
    st.header("Опции")
    limit = st.number_input("Лимит сделок (max)", min_value=1, max_value=2000, value=200, step=10)
    max_calls_per_deal = st.number_input("Макс. звонков на сделку (0 = все)", min_value=0, max_value=50, value=0, step=1)
    exclude_call_center = st.checkbox("Не учитывать звонки операторов Call-центра", value=True)
    st.caption("Для Bit.Newton нужен `BITNEWTON_TOKEN` в `.env`.")

    st.divider()
    st.subheader("Bit.Newton (опционально)")
    use_bitnewton = st.checkbox("Использовать Bit.Newton для расшифровки", value=True)
    diarize = st.checkbox("Разделение по спикерам (diarize)", value=False, disabled=not use_bitnewton)
    reuse_transcripts = st.checkbox(
        "Использовать уже сохранённые расшифровки",
        value=True,
        disabled=not use_bitnewton,
        help="Если звонок уже расшифровывался, отчет пересобирается из сохраненного текста без повторного скачивания аудио и отправки в Bit.Newton.",
    )
    rest_timeout_sec = st.number_input("Таймаут REST-скачивания, сек.", min_value=5, max_value=120, value=20, step=5, disabled=not use_bitnewton)
    download_audio = st.checkbox("Сохранять аудио в reports/audio/ (если получится скачать)", value=False, disabled=not use_bitnewton)
    audio_source_dir = st.text_input(
        "Локальная папка с аудиозаписями",
        value="",
        disabled=not use_bitnewton,
        help="Если записи уже доступны на диске, укажи папку. Система сначала ищет аудио там по ID файла/активности/звонка, а REST/UI использует только если файл не найден.",
    )
    bitnewton_flow = st.checkbox("Только Bit.Newton: call → audio → ASR → attach", value=True, disabled=not use_bitnewton)
    ui_download = st.checkbox(
        "UI fallback: скачивать через браузер, если REST не смог",
        value=False,
        disabled=not use_bitnewton,
        help="После выдачи доступа к папке записей обычный режим должен работать через Bitrix Disk/API. Включай браузерный fallback только для отдельных проблемных звонков.",
    )
    ui_timeout_sec = st.number_input("Таймаут UI fallback, сек.", min_value=5, max_value=120, value=20, step=5, disabled=not use_bitnewton or not ui_download)
    fetch_bitrix_card_transcript = st.checkbox(
        "Глубокая проверка: читать расшифровку из карточки Bitrix",
        value=False,
        disabled=not use_bitnewton or not ui_download,
        help="Медленный режим: открывает карточку звонка через браузер и пробует нажать кнопку расшифровки. Включать точечно для аудита, не для массового запуска.",
    )
    ui_browser = st.selectbox("Браузер для UI fallback", options=["edge", "chrome"], index=0, disabled=not use_bitnewton or not ui_download)
    ui_download_dir = st.text_input("Папка UI-скачивания", value="reports/audio_ui", disabled=not use_bitnewton)
    chrome_profile_mode = st.selectbox(
        "Профиль браузера для UI-скачивания",
        options=["system", "custom"],
        index=0,
        disabled=not use_bitnewton or not ui_download,
        help="system = обычные профили выбранного Edge/Chrome пользователя",
    )
    chrome_profile_dir = ""
    browser_profile_directory = "Default"
    if chrome_profile_mode == "system":
        browser_profiles = list_browser_profiles(ui_browser)
        profile_labels = {p["directory"]: p["label"] for p in browser_profiles}
        browser_profile_directory = st.selectbox(
            "Какой профиль открыть",
            options=[p["directory"] for p in browser_profiles],
            index=0,
            format_func=lambda value: profile_labels.get(value, value),
            disabled=not use_bitnewton or not ui_download,
            help="Выбери тот профиль, где Bitrix уже открыт под нужным пользователем.",
        )
    if chrome_profile_mode == "custom":
        chrome_profile_dir = st.text_input("Путь к custom Chrome profile", value="", disabled=not use_bitnewton or not ui_download)
        browser_profile_directory = st.text_input(
            "Папка профиля внутри custom profile",
            value="Default",
            disabled=not use_bitnewton or not ui_download,
            help="Обычно Default, Profile 1 или Profile 2.",
        )

    st.divider()
    st.subheader("KPI профили")
    if KPI_FILES:
        base_kpi = st.selectbox(
            "Основной KPI профиль",
            options=KPI_FILES,
            index=0,
            format_func=kpi_file_label,
            help="Профиль определяет веса оценки звонка, CRM-дисциплины, SLA и качества проработки клиента.",
        )
        st.caption(kpi_file_description(base_kpi))
        use_compare_kpi = st.checkbox("Сравнить со вторым KPI профилем", value=False)
        compare_kpi = None
        if use_compare_kpi:
            compare_options = [k for k in KPI_FILES if k != base_kpi] or KPI_FILES
            compare_kpi = st.selectbox(
                "Сравнительный KPI профиль",
                options=compare_options,
                index=0,
                format_func=kpi_file_label,
            )
            st.caption(kpi_file_description(compare_kpi))
    else:
        st.warning("KPI профили не найдены (ожидались файлы kpi_config*.json в корне проекта).")
        base_kpi = None
        use_compare_kpi = False
        compare_kpi = None

st.subheader("Запуск")
run_mode = st.radio(
    "Режим запуска",
    [
        "Обычная обработка",
        "Повторить только ошибки из отчета",
        "Переоценить отчет без повторной расшифровки",
    ],
    index=0,
)
report_files = available_report_json_files()
selected_report: Optional[Path] = None
if run_mode != "Обычная обработка":
    if report_files:
        selected_report = st.selectbox(
            "JSON отчет",
            options=report_files,
            index=0,
            format_func=report_file_label,
            help="Берется старый JSON из reports/. Excel для этих режимов не подходит, нужен именно JSON.",
        )
    else:
        st.warning("В reports/ не найдено JSON-отчетов для повторного режима.")
    if run_mode == "Повторить только ошибки из отчета":
        st.caption("Будут заново обработаны только строки с `Ошибка`; после этого пересоберется полный отчет со всеми исходными строками.")
    else:
        st.caption("Аудио не скачивается и Bit.Newton не вызывается: пересчитывается аналитика по сохраненным расшифровкам.")

run = st.button("Старт", type="primary")

if run:
    args: list[str] = []
    if run_mode == "Переоценить отчет без повторной расшифровки":
        if selected_report is None:
            st.error("Выбери JSON-отчет для переоценки.")
            st.stop()
        args += ["--reevaluate-from", str(selected_report)]
    elif run_mode == "Повторить только ошибки из отчета":
        if selected_report is None:
            st.error("Выбери JSON-отчет, из которого нужно повторить ошибки.")
            st.stop()
        args += ["--retry-errors-from", str(selected_report)]
    elif mode == "Одна сделка по URL":
        args += ["--mode", "single", "--deal-url", deal_url]
    else:
        flt: dict = {}

        if title_like.strip():
            flt["%TITLE"] = title_like.strip()

        if selected_cat_id is not None:
            flt["CATEGORY_ID"] = selected_cat_id

        if selected_stage_ids:
            flt["STAGE_ID"] = selected_stage_ids[0] if len(selected_stage_ids) == 1 else selected_stage_ids

        if selected_lead_category_ids:
            flt[LEAD_CATEGORY_NEW_FIELD] = (
                selected_lead_category_ids[0]
                if len(selected_lead_category_ids) == 1
                else selected_lead_category_ids
            )

        if date_preset == "Не учитывать дату":
            pass
        elif date_preset != "Произвольно":
            today = date.today()
            if date_preset == "Сегодня":
                flt[">=DATE_CREATE"] = str(today)
            elif date_preset == "Вчера":
                flt[">=DATE_CREATE"] = str(today - timedelta(days=1))
                flt["<DATE_CREATE"] = str(today)
            elif date_preset == "Последние 7 дней":
                flt[">=DATE_CREATE"] = str(today - timedelta(days=7))
            elif date_preset == "Последние 30 дней":
                flt[">=DATE_CREATE"] = str(today - timedelta(days=30))
        else:
            flt[">=DATE_CREATE"] = str(date_from)
            flt["<DATE_CREATE"] = str(date_to + timedelta(days=1))

        if assigned_by.strip():
            ids = [x.strip() for x in assigned_by.split(",") if x.strip()]
            flt["ASSIGNED_BY_ID"] = ids[0] if len(ids) == 1 else ids

        filter_path = REPORTS_DIR / "deal_filter.json"
        filter_path.write_text(json.dumps(flt, ensure_ascii=False, indent=2), encoding="utf-8")
        args += ["--mode", "filter", "--filter-json", str(filter_path), "--limit", str(int(limit))]

    if run_mode != "Переоценить отчет без повторной расшифровки":
        if not use_bitnewton:
            st.error("Для обычной обработки и повтора ошибок нужен Bit.Newton. Для работы без Bit.Newton выбери режим переоценки.")
            st.stop()
        args += ["--use-bitnewton"]
        args += ["--rest-timeout-sec", str(int(rest_timeout_sec))]
        if int(max_calls_per_deal) > 0:
            args += ["--max-calls-per-deal", str(int(max_calls_per_deal))]
        if not reuse_transcripts:
            args += ["--no-reuse-transcripts"]
        if not exclude_call_center:
            args += ["--include-call-center"]
        if diarize:
            args += ["--diarize"]
        if download_audio:
            args += ["--download-audio"]
        if audio_source_dir.strip():
            args += ["--audio-source-dir", audio_source_dir.strip()]
        if bitnewton_flow:
            args += ["--bitnewton-flow"]
        if ui_download:
            args += ["--ui-download"]
            args += ["--ui-timeout-sec", str(int(ui_timeout_sec))]
            if fetch_bitrix_card_transcript:
                args += ["--fetch-bitrix-card-transcript"]
            args += ["--ui-browser", ui_browser]
            if ui_download_dir.strip():
                args += ["--ui-download-dir", ui_download_dir.strip()]
            if chrome_profile_mode == "system":
                args += ["--chrome-profile-dir", "system"]
            elif chrome_profile_mode == "custom" and chrome_profile_dir.strip():
                args += ["--chrome-profile-dir", chrome_profile_dir.strip()]
            if browser_profile_directory.strip():
                args += ["--browser-profile-directory", browser_profile_directory.strip()]

    if base_kpi:
        args += ["--kpi-config", base_kpi]
    if use_compare_kpi and compare_kpi:
        args += ["--kpi-config-compare", compare_kpi]

    st.divider()
    st.subheader("Логи выполнения")
    exit_code = run_pipeline(args)
    st.divider()
    if exit_code == 0:
        st.success("Готово. Проверь папку `reports/` — там JSON и Excel отчеты.")
    else:
        st.error(f"Завершилось с ошибкой (exit code={exit_code}). Проверь лог выше.")

st.divider()
st.subheader("Последний отчёт")
json_reports = available_report_json_files()
last_json = LATEST_JSON_REPORT if LATEST_JSON_REPORT.exists() else (json_reports[0] if json_reports else None)
last_xlsx = LATEST_XLSX_REPORT if LATEST_XLSX_REPORT.exists() else latest_report_file("bitnewton_sync_report_*.xlsx")

if not last_json and not last_xlsx:
    st.info("Отчёты пока не найдены. Запусти пайплайн, и здесь появится быстрый доступ.")
else:
    st.caption(f"Постоянные файлы: `{LATEST_JSON_REPORT}` и `{LATEST_XLSX_REPORT}`")
    c1, c2 = st.columns(2)
    with c1:
        if last_json:
            st.caption(f"JSON: `{last_json.name}`")
            st.download_button(
                "Скачать последний JSON",
                data=last_json.read_bytes(),
                file_name=last_json.name,
                mime="application/json",
                use_container_width=True,
            )
    with c2:
        if last_xlsx:
            st.caption(f"Excel: `{last_xlsx.name}`")
            st.download_button(
                "Скачать последний Excel",
                data=last_xlsx.read_bytes(),
                file_name=last_xlsx.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    if last_xlsx:
        st.divider()
        st.markdown("**Быстрый просмотр последнего Excel**")
        modified_ts = last_xlsx.stat().st_mtime
        summary_df = read_report_sheet(str(last_xlsx), modified_ts, "Итоги", nrows=60)
        control_df = read_report_sheet(str(last_xlsx), modified_ts, "Контроль качества", nrows=25)
        coaching_df = read_report_sheet(str(last_xlsx), modified_ts, "План обучения", nrows=25)
        manager_cards_df = read_report_sheet(str(last_xlsx), modified_ts, "Карточки менеджеров", nrows=50)

        if summary_df.empty and control_df.empty and coaching_df.empty:
            st.info("Не удалось прочитать быстрый просмотр. Excel можно скачать кнопкой выше.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Сделок", summary_value(summary_df, "Сделок в отчете") or "—")
            with m2:
                st.metric("Ошибок звонков", summary_value(summary_df, "Ошибок обработки звонков") or "—")
            with m3:
                st.metric("Средняя оценка", summary_value(summary_df, "Средняя итоговая оценка") or "—")
            with m4:
                st.metric("Критичных сделок", summary_value(summary_df, "Критичных сделок") or "—")

            tab_summary, tab_control, tab_coaching, tab_managers = st.tabs(
                ["Итоги", "Контроль качества", "План обучения", "Карточки менеджеров"]
            )
            with tab_summary:
                if summary_df.empty:
                    st.info("Лист `Итоги` не найден в последнем Excel.")
                else:
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)
            with tab_control:
                if control_df.empty:
                    st.info("Лист `Контроль качества` не найден в последнем Excel.")
                else:
                    st.dataframe(control_df, use_container_width=True, hide_index=True)
            with tab_coaching:
                if coaching_df.empty:
                    st.info("Лист `План обучения` не найден в последнем Excel.")
                else:
                    st.dataframe(coaching_df, use_container_width=True, hide_index=True)
            with tab_managers:
                if manager_cards_df.empty:
                    st.info("Лист `Карточки менеджеров` не найден в последнем Excel.")
                else:
                    st.dataframe(manager_cards_df, use_container_width=True, hide_index=True)

    if last_json:
        top_delta = extract_top_delta(last_json, limit=5)
        if top_delta:
            st.markdown("**Top-5 delta между KPI профилями (последний JSON):**")
            for i, row in enumerate(top_delta, 1):
                st.write(
                    f"{i}. deal={row.get('deal_id')} act={row.get('activity_id')} "
                    f"manager={row.get('manager_name') or row.get('manager_id')} "
                    f"base={row.get('overall_score')} cmp={row.get('overall_score_cmp')} "
                    f"delta={row.get('overall_score_delta')}"
                )

