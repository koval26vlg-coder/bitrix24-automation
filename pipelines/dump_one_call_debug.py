from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asr.bitnewton import BitNewtonError, env_bitnewton_asr  # noqa: E402
from bitrix.api import Bitrix24API  # noqa: E402
from bitrix.recordings import guess_recording_url  # noqa: E402
from logging_setup import get_logger  # noqa: E402

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Вывести пример ответа voximplant.statistic.get (1 звонок)."
    )
    p.add_argument(
        "--days", type=int, default=3, help="За сколько последних дней искать звонок (по дате)."
    )
    p.add_argument("--limit", type=int, default=10, help="Сколько звонков запросить у API.")
    p.add_argument("--pretty", action="store_true", help="Красивый JSON (indent=2).")
    p.add_argument(
        "--transcribe",
        action="store_true",
        help="Скачать запись и транскрибировать через Bit.Newton (нужен BITNEWTON_TOKEN).",
    )
    p.add_argument(
        "--diarize",
        action="store_true",
        help="Включить диаризацию (разделение на спикеров), если поддерживается.",
    )
    p.add_argument(
        "--selenium-fallback",
        action="store_true",
        help="Если прямое скачивание не удалось — скачать через Chrome (UI).",
    )
    p.add_argument(
        "--audio-file",
        type=str,
        default="",
        help="Путь к локальному mp3/wav. Если указан — скачивание из Bitrix пропускается.",
    )
    return p


def _import_selenium():
    from selenium import webdriver
    from selenium.common.exceptions import (
        SessionNotCreatedException,
        TimeoutException,
        WebDriverException,
    )
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    return (
        webdriver,
        Options,
        By,
        WebDriverWait,
        EC,
        WebDriverException,
        TimeoutException,
        SessionNotCreatedException,
    )


def extract_any_url(obj: Any) -> str | None:
    if isinstance(obj, str) and obj.startswith("http"):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            u = extract_any_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for it in obj:
            u = extract_any_url(it)
            if u:
                return u
    return None


def resolve_any_download_href(html: str, base_url: str) -> str | None:
    if not html:
        return None
    patterns = [
        r'href="([^"]+/docs/pub/[^"]+/download\?token=[^"]+)"',
        r'href="([^"]+/docs/pub/[^"]+/download[^"]+)"',
        r'href="([^"]+/docs/pub/[^"]+)"',
        r'href="([^"]+/bitrix/[^"]*download[^"]+)"',
        r'href="([^"]+/bitrix/tools/[^"]+)"',
        r'href="([^"]+/download\?token=[^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            href = m.group(1)
            href = re.sub(r"^/[^/]+\.bitrix24\.ru/", "/", href)
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return base_url.rstrip("/") + href
            return base_url.rstrip("/") + "/" + href
    return None


def looks_like_html_prefix(data: bytes) -> bool:
    if not data:
        return True
    head = data.lstrip()[:200].lower()
    return (
        head.startswith(b"<!doctype")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
        or head.startswith(b"<body")
    )


async def _run_with_api(args: argparse.Namespace, api: Bitrix24API) -> None:
    date_to = datetime.now()
    date_from = date_to - timedelta(days=max(1, args.days))
    flt = {
        ">=CALL_START_DATE": date_from.strftime("%Y-%m-%d"),
        "<=CALL_START_DATE": date_to.strftime("%Y-%m-%d"),
    }

    data = await api.call(
        "voximplant.statistic.get",
        {"FILTER": flt, "SORT": "CALL_START_DATE", "ORDER": "DESC", "LIMIT": args.limit},
    )
    calls = data.get("result") or []
    if not calls:
        logger.info("Звонков не найдено. Попробуй увеличить --days.")
        return

    call0 = calls[0]
    url = guess_recording_url(call0)
    record_file_id = call0.get("RECORD_FILE_ID")
    activity_id = call0.get("CRM_ACTIVITY_ID")
    detail_url = None
    activity_file_url = None
    external_link = None

    logger.info("\n=== Пример 1 звонка из voximplant.statistic.get ===\n")
    logger.info(
        json.dumps(call0, ensure_ascii=False, indent=2)
        if args.pretty
        else json.dumps(call0, ensure_ascii=False)
    )

    logger.info("\n=== Кандидат на ссылку записи (если найден) ===\n")
    if url:
        logger.info(url)
    else:
        logger.info("Не нашёл явную ссылку на запись в этом объекте.")
        logger.info(
            "\nПробую достать ссылку через Disk/Activity API (RECORD_FILE_ID / CRM_ACTIVITY_ID)...\n"  # noqa: E501
        )

        if record_file_id:
            try:
                disk_get = await api.call("disk.file.get", {"id": int(record_file_id)})
            except Exception as e:
                disk_get = {"error": str(e)}

            try:
                disk_link = await api.call("disk.file.getExternalLink", {"id": int(record_file_id)})
            except Exception as e:
                disk_link = {"error": str(e)}

            logger.info("=== disk.file.get ===")
            logger.info(json.dumps(disk_get, ensure_ascii=False, indent=2)[:4000])
            logger.info("\n=== disk.file.getExternalLink ===")
            logger.info(json.dumps(disk_link, ensure_ascii=False, indent=2)[:4000])

            try:
                if isinstance(disk_get, dict):
                    detail_url = (disk_get.get("result") or {}).get("DETAIL_URL")
            except Exception:
                detail_url = None

            if isinstance(disk_link, dict):
                external_link = disk_link.get("result")

            u = extract_any_url(disk_get) or extract_any_url(disk_link)
            if u:
                logger.info("\n>>> НАЙДЕН URL (из Disk):")
                logger.info(u)
                url = url or u

        if activity_id:
            try:
                act = await api.call("crm.activity.get", {"id": int(activity_id)})
            except Exception as e:
                act = {"error": str(e)}

            logger.info("\n=== crm.activity.get ===")
            logger.info(json.dumps(act, ensure_ascii=False, indent=2)[:4000])

            u2 = extract_any_url(act)
            if u2:
                logger.info("\n>>> НАЙДЕН URL (из Activity):")
                logger.info(u2)
                url = url or u2
            try:
                files = (act.get("result") or {}).get("FILES") or []
                if files and isinstance(files[0], dict) and isinstance(files[0].get("url"), str):
                    activity_file_url = files[0]["url"]
            except Exception:
                activity_file_url = None

        logger.info(
            "\nЕсли URL всё ещё не найден — просто скинь сюда вывод disk.file.get / crm.activity.get (можно замаскировать телефоны)."  # noqa: E501
        )

    if not args.transcribe:
        return

    asr = env_bitnewton_asr()
    if not asr:
        logger.error("\n[ERROR] Не найден BITNEWTON_TOKEN в .env / переменных окружения.")
        logger.info("Добавь в .env:")
        logger.info("BITNEWTON_TOKEN=...токен...")
        return

    logger.info("\n=== ТРАНСКРИБАЦИЯ через Bit.Newton ===\n")
    tmp_dir = Path("reports")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = tmp_dir / f"dump_call_{ts}.mp3"

    try:
        if args.audio_file:
            audio_path = Path(args.audio_file).expanduser().resolve()
            if not audio_path.exists():
                logger.error(f"[ERROR] Файл не найден: {audio_path}")
                return
            logger.info(
                f"[OK] Беру локальный файл: {audio_path} ({audio_path.stat().st_size} bytes)"
            )
        else:
            if not url and not external_link and not detail_url and not activity_file_url:
                logger.error(
                    "\n[ERROR] Не удалось определить URL записи. Сначала добудь URL через Disk/Activity."  # noqa: E501
                )
                return

            sess = requests.Session()
            download_candidates = []
            for u in [url, external_link]:
                if not (isinstance(u, str) and u.startswith("http")):
                    continue
                download_candidates.append(u)
                if "/~" in u:
                    sep = "&" if "?" in u else "?"
                    download_candidates.append(f"{u}{sep}download=1")
                    download_candidates.append(f"{u}{sep}export=1")

            last_status = None
            for cand in download_candidates:
                headers = {"User-Agent": "Mozilla/5.0"}
                logger.info(f"[DL] пробую: {cand}")
                r = sess.get(cand, timeout=120, allow_redirects=True, stream=True, headers=headers)
                last_status = r.status_code
                ctype = (r.headers.get("Content-Type") or "").lower()
                logger.info(f"[DL] http={r.status_code} content-type={ctype or '<none>'}")
                if r.status_code >= 400:
                    continue
                if "text/html" in ctype:
                    try:
                        debug_html = tmp_dir / f"debug_download_{ts}.html"
                        chunk = next(r.iter_content(chunk_size=20000), b"")
                        debug_html.write_bytes(chunk)
                        logger.warning(
                            f"[WARN] Вместо файла пришёл HTML ({cand}). Сохранил: {debug_html}"
                        )
                        html = chunk.decode("utf-8", errors="ignore")
                        base = "https://online-kassa.bitrix24.ru"
                        direct = resolve_any_download_href(html, base_url=base)
                        if direct:
                            logger.info(f"[DL] нашёл прямую ссылку Скачать: {direct}")
                            headers2 = dict(headers)
                            headers2["Referer"] = cand
                            rr = sess.get(
                                direct,
                                timeout=120,
                                allow_redirects=True,
                                stream=True,
                                headers=headers2,
                            )
                            last_status = rr.status_code
                            rr_ctype = (rr.headers.get("Content-Type") or "").lower()
                            hist = (
                                ",".join([str(h.status_code) for h in rr.history])
                                if rr.history
                                else "-"
                            )
                            logger.info(
                                f"[DL] download-link http={rr.status_code} hist={hist} final={rr.url} content-type={rr_ctype or '<none>'}"  # noqa: E501
                            )
                            if rr.status_code < 400:
                                first = next(rr.iter_content(chunk_size=4096), b"")
                                if looks_like_html_prefix(first):
                                    # fallback for additional link resolution
                                    buf = bytearray(first)
                                    for _ in range(0, 512000 // 20000):
                                        try:
                                            part = next(rr.iter_content(chunk_size=20000), b"")
                                        except Exception:
                                            part = b""
                                        if not part:
                                            break
                                        buf.extend(part)
                                        if len(buf) >= 512000:
                                            break
                                    html2 = bytes(buf).decode("utf-8", errors="ignore")
                                    dbg = tmp_dir / f"debug_download_link_{ts}.html"
                                    dbg.write_text(html2, encoding="utf-8", errors="ignore")
                                    logger.warning(
                                        f"[WARN] download-link тоже вернул HTML. Сохранил: {dbg}"
                                    )
                                    direct2 = resolve_any_download_href(html2, base_url=base)
                                    if not direct2:
                                        sep2 = "&" if "?" in direct else "?"
                                        direct2 = f"{direct}{sep2}download=1"
                                    if direct2 and direct2 != direct:
                                        logger.info(f"[DL] нашёл вторую ссылку Скачать: {direct2}")
                                        headers3 = dict(headers)
                                        headers3["Referer"] = rr.url
                                        rrr = sess.get(
                                            direct2,
                                            timeout=120,
                                            allow_redirects=True,
                                            stream=True,
                                            headers=headers3,
                                        )
                                        last_status = rrr.status_code
                                        rrr_ctype = (rrr.headers.get("Content-Type") or "").lower()
                                        hist2 = (
                                            ",".join([str(h.status_code) for h in rrr.history])
                                            if rrr.history
                                            else "-"
                                        )
                                        logger.info(
                                            f"[DL] download-link2 http={rrr.status_code} hist={hist2} final={rrr.url} content-type={rrr_ctype or '<none>'}"  # noqa: E501
                                        )
                                        if rrr.status_code < 400:
                                            first3 = next(rrr.iter_content(chunk_size=4096), b"")
                                            if not looks_like_html_prefix(first3):
                                                with audio_path.open("wb") as f:
                                                    f.write(first3)
                                                    for c3 in rrr.iter_content(
                                                        chunk_size=1024 * 256
                                                    ):
                                                        if c3:
                                                            f.write(c3)
                                                break
                                else:
                                    with audio_path.open("wb") as f:
                                        f.write(first)
                                        for c2 in rr.iter_content(chunk_size=1024 * 256):
                                            if c2:
                                                f.write(c2)
                                    break
                    except Exception:
                        pass
                    continue

                with audio_path.open("wb") as f:
                    first = next(r.iter_content(chunk_size=4096), b"")
                    if looks_like_html_prefix(first):
                        raise RuntimeError("Похоже, вместо файла пришёл HTML (по содержимому).")
                    f.write(first)
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                break

            if not audio_path.exists() or audio_path.stat().st_size == 0:
                logger.error(f"[ERROR] Не удалось скачать запись. Последний HTTP={last_status}.")
                logger.info(
                    "Подсказка: иногда external link надо скачивать с параметром ?download=1."
                )
                if not args.selenium_fallback:
                    return

                logger.info("\n[INFO] Пробую скачать через Chrome (selenium fallback)...")
                (
                    webdriver,
                    Options,
                    By,
                    WebDriverWait,
                    EC,
                    WebDriverException,
                    TimeoutException,
                    SessionNotCreatedException,
                ) = _import_selenium()
                dl_dir = tmp_dir / f"selenium_download_{ts}"
                dl_dir.mkdir(parents=True, exist_ok=True)

                def build_driver():
                    def _opts(user_data_dir: str):
                        options = Options()
                        options.add_argument("--start-maximized")
                        options.add_argument("--disable-blink-features=AutomationControlled")
                        options.add_argument("--disable-quic")
                        options.add_argument("--no-first-run")
                        options.add_argument("--no-default-browser-check")
                        options.add_argument("--disable-background-networking")
                        options.add_argument("--disable-sync")
                        options.add_argument("--disable-extensions")
                        options.add_argument("--disable-gpu")
                        options.add_argument(f"--user-data-dir={user_data_dir}")
                        options.add_argument("--profile-directory=Default")
                        options.add_experimental_option(
                            "prefs",
                            {
                                "download.default_directory": str(dl_dir.resolve()),
                                "download.prompt_for_download": False,
                                "download.directory_upgrade": True,
                                "safebrowsing.enabled": True,
                            },
                        )
                        return options

                    base_profile_dir = os.getenv("CHROME_PROFILE_DIR") or str(
                        (Path("reports") / "chrome_profile").resolve()
                    )
                    Path(base_profile_dir).mkdir(parents=True, exist_ok=True)
                    try:
                        return webdriver.Chrome(options=_opts(base_profile_dir))
                    except SessionNotCreatedException:
                        fallback_dir = str(
                            (Path("reports") / f"chrome_profile_tmp_{int(time.time())}").resolve()
                        )
                        Path(fallback_dir).mkdir(parents=True, exist_ok=True)
                        return webdriver.Chrome(options=_opts(fallback_dir))

                driver = build_driver()
                try:
                    targets = []
                    if external_link:
                        targets.append(str(external_link))
                    if detail_url:
                        try:
                            if "://" in detail_url:
                                proto, rest = detail_url.split("://", 1)
                                host, path = rest.split("/", 1)
                                targets.append(f"{proto}://{host}/{quote(path)}")
                            else:
                                targets.append(str(detail_url))
                        except Exception:
                            targets.append(str(detail_url))
                    if activity_file_url:
                        targets.append(str(activity_file_url))

                    if not targets:
                        logger.error(
                            "[ERROR] Нет ссылки для открытия в браузере (external_link/detail_url)."
                        )
                        return

                    def try_click_download() -> None:
                        locators = [
                            (By.XPATH, "//a[contains(., 'Скачать')]"),
                            (By.XPATH, "//button[contains(., 'Скачать')]"),
                            (By.CSS_SELECTOR, "a.bx-disk-btn"),
                        ]
                        for by, sel in locators:
                            try:
                                btn = WebDriverWait(driver, 8).until(
                                    EC.element_to_be_clickable((by, sel))
                                )
                                btn.click()
                                return
                            except TimeoutException:
                                continue
                            except WebDriverException:
                                continue

                    downloaded = False
                    for target in targets:
                        logger.info(f"[SEL] Открываю в Chrome: {target}")
                        driver.get(target)
                        try_click_download()

                        start_wait = time.time()
                        while time.time() - start_wait < 60:
                            files = sorted(
                                dl_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True
                            )
                            ready = [
                                f
                                for f in files
                                if f.is_file() and not f.name.endswith(".crdownload")
                            ]
                            if ready:
                                audio_path = ready[0]
                                downloaded = True
                                break
                            time.sleep(1.0)
                        if downloaded:
                            break

                    if not downloaded or not audio_path.exists() or audio_path.stat().st_size == 0:
                        logger.info(
                            "[ERROR] Selenium скачивание не дало файл. Возможные причины: не выполнен логин, нет прав, или сетевой блок.",  # noqa: E501
                            flush=True,
                        )
                        return
                    logger.info(
                        f"[OK] Selenium скачал: {audio_path} ({audio_path.stat().st_size} bytes)"
                    )
                except WebDriverException as e:
                    logger.error(f"[ERROR] Selenium: {e}")
                    return
                finally:
                    try:
                        driver.quit()
                    except Exception:
                        pass

        if not args.audio_file:
            logger.info(f"[OK] Запись скачана: {audio_path} ({audio_path.stat().st_size} bytes)")

        task = asr.start_transcribing(
            str(audio_path), diarize=bool(args.diarize), remove_timestamps=True
        )
        logger.info(f"[OK] Задача создана: task_id={task.task_id}")

        start = time.time()
        last_print = 0.0
        while True:
            st = asr.get_status(task.task_id)
            status = str(st.get("status") or "")
            progress = st.get("progress")
            upload = st.get("upload_progress")
            trans = st.get("transcribe_progress")
            qpos = st.get("queue_position")
            err = st.get("error")

            now = time.time()
            if now - last_print >= 2.5:
                logger.info(
                    f"[ASR] status={status} progress={progress} upload={upload} transcribe={trans} queue={qpos}"  # noqa: E501
                )
                last_print = now

            st_l = status.lower()
            if st_l in {"done", "success", "completed", "finished"} or (
                isinstance(progress, int) and progress >= 100
            ):
                break
            if st_l in {"error", "failed"}:
                raise BitNewtonError(f"ASR task failed: {err or st}")
            if now - start > 900:
                raise BitNewtonError(f"ASR timeout waiting task {task.task_id}. last_status={st}")
            time.sleep(2.0)

        content = asr.get_file(task.task_id, file_type="txt")
        try:
            text = content.decode("utf-8", errors="replace").strip()
        except Exception:
            text = content.decode(errors="replace").strip()
        logger.info("\n=== РЕЗУЛЬТАТ (первые 4000 символов) ===\n")
        logger.info(text[:4000])
    except BitNewtonError as e:
        logger.error(f"[ERROR] Bit.Newton: {e}")
    except Exception as e:
        logger.error(f"[ERROR] Ошибка: {e}")
    finally:
        try:
            if not args.audio_file:
                audio_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            pass


async def run(args: argparse.Namespace) -> None:
    api = Bitrix24API()
    try:
        await _run_with_api(args, api)
    finally:
        await api.aclose()


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
