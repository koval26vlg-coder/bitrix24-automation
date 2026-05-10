from __future__ import annotations

import os
import re
import time
import html
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class UiDownloadError(RuntimeError):
    pass


@dataclass
class UiDownloadResult:
    ok: bool
    path: Optional[Path]
    error: Optional[str] = None


@dataclass
class UiTranscriptResult:
    ok: bool
    text: str = ""
    error: Optional[str] = None


PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".download")
MIN_UI_LOGIN_WAIT_SEC = 120
DEFAULT_UI_TIMEOUT_SEC = 20


def _clean_url(url: Optional[str]) -> str:
    if not isinstance(url, str):
        return ""
    return html.unescape(url).strip()


def _import_selenium():
    try:
        from selenium import webdriver
        from selenium.common.exceptions import SessionNotCreatedException, TimeoutException, WebDriverException
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as e:  # pragma: no cover
        raise UiDownloadError(
            "Не установлены зависимости UI-скачивания. Установи: pip install -r requirements_ui.txt"
        ) from e
    return (
        webdriver,
        ChromeOptions,
        EdgeOptions,
        By,
        WebDriverWait,
        EC,
        TimeoutException,
        SessionNotCreatedException,
        WebDriverException,
    )


def _looks_like_html(data: bytes) -> bool:
    if not data:
        return False
    head = data.lstrip()[:512].lower()
    return (
        head.startswith(b"<!doctype")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
        or head.startswith(b"<body")
        or b"<title>" in head[:200]
    )


def _snapshot_downloads(downloads_dir: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for p in downloads_dir.glob("*"):
        try:
            if p.is_file():
                st = p.stat()
                out[p.name] = (int(st.st_size), int(st.st_mtime_ns))
        except OSError:
            continue
    return out


def _is_ready_file(path: Path) -> bool:
    return path.is_file() and not path.name.lower().endswith(PARTIAL_SUFFIXES)


def _is_new_or_changed(path: Path, before: dict[str, tuple[int, int]]) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    old = before.get(path.name)
    return old is None or old != (int(st.st_size), int(st.st_mtime_ns))


def _page_context(driver) -> str:
    try:
        cur = _clean_url(str(driver.current_url or ""))
    except Exception:
        cur = ""
    try:
        title = str(driver.title or "")
    except Exception:
        title = ""
    try:
        text = html.unescape(str(driver.execute_script("return document.body ? document.body.innerText : ''") or ""))
        text = re.sub(r"\s+", " ", text).strip()[:260]
    except Exception:
        text = ""
    parts = []
    if cur:
        parts.append(f"url={cur}")
    if title:
        parts.append(f"title={title}")
    if text:
        parts.append(f"text={text}")
    return "; ".join(parts)


def _is_contextless_disk_download_href(href: str) -> bool:
    low = _clean_url(href).lower()
    if "/disk/downloadfile/" not in low:
        return False
    return "ownertypeid=" not in low and "ownerid=" not in low


def _looks_like_invalid_owner_page(driver) -> bool:
    try:
        cur = _clean_url(str(driver.current_url or "")).lower()
    except Exception:
        cur = ""
    try:
        title = html.unescape(str(driver.title or "")).lower()
    except Exception:
        title = ""
    try:
        text = html.unescape(str(driver.execute_script("return document.body ? document.body.innerText : ''") or "")).lower()
    except Exception:
        text = ""

    context = " ".join([cur, title, text[:1200]])
    return "invalid data ownertypeid" in context or ("ownertypeid = 0" in context and "ownerid = 0" in context)


def _looks_like_login_page(driver) -> bool:
    try:
        cur = str(driver.current_url or "").lower()
    except Exception:
        cur = ""
    try:
        title = str(driver.title or "").lower()
    except Exception:
        title = ""
    try:
        text = str(driver.execute_script("return document.body ? document.body.innerText : ''") or "").lower()
    except Exception:
        text = ""

    auth_url_markers = ("/auth", "login", "oauth", "authorize", "bitrix24.net")
    if any(marker in cur for marker in auth_url_markers):
        return True

    auth_text = " ".join([title, text[:1200]])
    return (
        "qr" in auth_text
        and ("войти" in auth_text or "авторизац" in auth_text or "login" in auth_text)
    ) or "авторизация" in auth_text


def _wait_for_manual_login(driver, timeout_sec: int = MIN_UI_LOGIN_WAIT_SEC) -> tuple[bool, Optional[str]]:
    if not _looks_like_login_page(driver):
        return False, None

    wait_sec = max(MIN_UI_LOGIN_WAIT_SEC, int(timeout_sec or 0))
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not _looks_like_login_page(driver):
            return True, None
        time.sleep(1.0)

    return True, f"не дождался входа в Bitrix за {wait_sec} сек.; {_page_context(driver)}"


def _validate_download(path: Path, driver=None) -> Optional[str]:
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return "файл не создан или пустой"
        head = path.read_bytes()[:512]
        if _looks_like_html(head):
            ctx = _page_context(driver) if driver is not None else ""
            return "скачался HTML вместо аудио" + (f" ({ctx})" if ctx else "")
    except Exception as e:
        return f"не смог проверить файл: {e}"
    return None


def _wait_for_download(downloads_dir: Path, before: dict[str, tuple[int, int]], timeout_sec: int, driver=None) -> UiDownloadResult:
    deadline = time.time() + max(1, int(timeout_sec))
    while time.time() < deadline:
        files = []
        for p in downloads_dir.glob("*"):
            try:
                if _is_ready_file(p):
                    files.append(p)
            except OSError:
                continue
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for f in files:
            if not _is_new_or_changed(f, before):
                continue
            try:
                if f.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            bad = _validate_download(f, driver=driver)
            if bad:
                return UiDownloadResult(ok=False, path=f, error=bad)
            return UiDownloadResult(ok=True, path=f)
        time.sleep(0.5)

    ctx = _page_context(driver) if driver is not None else ""
    return UiDownloadResult(
        ok=False,
        path=None,
        error="UI download timeout: файл не появился в папке загрузок" + (f" ({ctx})" if ctx else ""),
    )


def _system_profile_dir(browser_name: str) -> str:
    local = os.getenv("LOCALAPPDATA") or ""
    if local:
        if browser_name == "edge":
            return str(Path(local) / "Microsoft" / "Edge" / "User Data")
        return str(Path(local) / "Google" / "Chrome" / "User Data")
    if browser_name == "edge":
        return str((Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data").resolve())
    return str((Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data").resolve())


def _resolve_profile_dir(browser_name: str, chrome_profile_dir: Optional[str]) -> str:
    if chrome_profile_dir and chrome_profile_dir.strip().lower() in {"system", "default", "user"}:
        return _system_profile_dir(browser_name)
    return chrome_profile_dir or os.getenv("CHROME_PROFILE_DIR") or str((Path("reports") / "chrome_profile").resolve())


def _options(
    browser_name: str,
    user_data_dir: str,
    downloads_dir: Path,
    ChromeOptions,
    EdgeOptions,
    profile_directory: Optional[str] = None,
):
    options = EdgeOptions() if browser_name == "edge" else ChromeOptions()
    try:
        options.page_load_strategy = "eager"
    except Exception:
        pass
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-quic")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-popup-blocking")
    options.add_argument(f"--user-data-dir={user_data_dir}")
    profile_directory = (profile_directory or os.getenv("BROWSER_PROFILE_DIRECTORY") or "Default").strip()
    if profile_directory:
        options.add_argument(f"--profile-directory={profile_directory}")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(downloads_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "download_restrictions": 0,
            "safebrowsing.enabled": True,
        },
    )
    return options


def _allow_downloads(driver, downloads_dir: Path) -> None:
    payload = {"behavior": "allow", "downloadPath": str(downloads_dir.resolve())}
    for command in ("Page.setDownloadBehavior", "Browser.setDownloadBehavior"):
        try:
            driver.execute_cdp_cmd(command, payload)
        except Exception:
            continue


def _create_driver(
    browser: str,
    downloads_dir: Path,
    chrome_profile_dir: Optional[str],
    browser_profile_directory: Optional[str] = None,
):
    (
        webdriver,
        ChromeOptions,
        EdgeOptions,
        By,
        WebDriverWait,
        EC,
        TimeoutException,
        SessionNotCreatedException,
        WebDriverException,
    ) = _import_selenium()

    browser = (browser or "chrome").strip().lower()
    if browser not in {"chrome", "edge"}:
        raise UiDownloadError(f"Unsupported browser='{browser}'. Use chrome|edge.")

    base_profile_dir = _resolve_profile_dir(browser, chrome_profile_dir)
    Path(base_profile_dir).mkdir(parents=True, exist_ok=True)

    def create(profile_dir: str):
        opts = _options(browser, profile_dir, downloads_dir, ChromeOptions, EdgeOptions, browser_profile_directory)
        if browser == "edge":
            return webdriver.Edge(options=opts)  # type: ignore[attr-defined]
        return webdriver.Chrome(options=opts)

    try:
        driver = create(base_profile_dir)
    except (SessionNotCreatedException, WebDriverException) as e:
        if chrome_profile_dir and chrome_profile_dir.strip().lower() in {"system", "default", "user"}:
            raise UiDownloadError(
                "Chrome/Edge system-профиль занят или заблокирован. "
                "Закрой все окна браузера и повтори, либо выбери custom-профиль. "
                f"Тех.деталь: {e}"
            ) from e
        fallback_dir = str((Path("reports") / f"chrome_profile_tmp_{int(time.time())}").resolve())
        Path(fallback_dir).mkdir(parents=True, exist_ok=True)
        driver = create(fallback_dir)

    try:
        driver.set_page_load_timeout(35)
        driver.set_script_timeout(20)
    except Exception:
        pass
    _allow_downloads(driver, downloads_dir)
    return driver, By, WebDriverWait, EC, TimeoutException, WebDriverException


def _safe_get(driver, url: str, TimeoutException, timeout_sec: int = 35) -> Optional[str]:
    url = _clean_url(url)
    if not url:
        return "empty url"
    try:
        driver.set_page_load_timeout(max(5, min(60, int(timeout_sec))))
    except Exception:
        pass
    try:
        driver.get(url)
        return None
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
        return f"page load timeout: {url}"


def _click_first_download_control(driver, By) -> Optional[str]:
    xpaths = [
        "//a[contains(., 'Скачать') or contains(., 'Download') or contains(., 'download')]",
        "//*[self::button or self::span or self::div][contains(., 'Скачать')]",
        "//a[contains(@href, 'download') or contains(@href, 'Download') or contains(@href, 'crm_show_file.php')]",
    ]
    last_error = None
    for xp in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xp)
        except Exception as e:
            last_error = str(e)
            continue
        for el in elements[:12]:
            try:
                href = _clean_url(el.get_attribute("href") or "")
                if _is_contextless_disk_download_href(href):
                    continue
                if not el.is_displayed() and not href:
                    continue
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.2)
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                return href or "clicked download control"
            except Exception as e:
                last_error = str(e)
                continue
    return f"download control not found: {last_error}" if last_error else None


def _visible_text_from_element(driver, element=None) -> str:
    try:
        if element is None:
            text = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        else:
            text = driver.execute_script("return arguments[0] ? arguments[0].innerText : ''", element) or ""
        return html.unescape(str(text))
    except Exception:
        return ""


def _meaningful_lines(text: str) -> list[str]:
    bad_markers = (
        "битрикс24",
        "crm",
        "календарь",
        "мессенджер",
        "пригласить",
        "мой тариф",
        "помощь",
        "позвонить",
        "заполнить поля",
        "оценить звонок",
        "программа для автоматической проверки",
    )
    lines: list[str] = []
    for raw in re.split(r"[\r\n]+", text or ""):
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 20:
            continue
        low = line.lower()
        if any(marker in low for marker in bad_markers):
            continue
        lines.append(line)
    return lines


def _extract_new_transcript_text(before_text: str, after_text: str) -> str:
    before_lines = set(_meaningful_lines(before_text))
    after_lines = _meaningful_lines(after_text)
    new_lines = [line for line in after_lines if line not in before_lines]
    text = "\n".join(new_lines).strip()
    if len(text) >= 120:
        return text[:20000]
    return ""


class UiBrowserSession:
    def __init__(
        self,
        downloads_dir: Path,
        chrome_profile_dir: Optional[str] = None,
        browser: str = "chrome",
        browser_profile_directory: Optional[str] = None,
    ):
        downloads_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir = downloads_dir
        (
            self.driver,
            self.By,
            self.WebDriverWait,
            self.EC,
            self.TimeoutException,
            self.WebDriverException,
        ) = _create_driver(
            browser=browser,
            downloads_dir=downloads_dir,
            chrome_profile_dir=chrome_profile_dir,
            browser_profile_directory=browser_profile_directory,
        )
        self._login_checked = False

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass

    def __enter__(self) -> "UiBrowserSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def download_url(self, url: str, timeout_sec: int = DEFAULT_UI_TIMEOUT_SEC, referer_url: Optional[str] = None) -> UiDownloadResult:
        url = _clean_url(url)
        referer_url = _clean_url(referer_url)
        if not isinstance(url, str) or not url.startswith("http"):
            return UiDownloadResult(ok=False, path=None, error=f"Некорректный URL для UI-скачивания: {url!r}")

        try:
            timeout_sec = max(5, int(timeout_sec or DEFAULT_UI_TIMEOUT_SEC))
            before = _snapshot_downloads(self.downloads_dir)
            if referer_url and not self._login_checked:
                _safe_get(self.driver, referer_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
                login_waited, login_error = _wait_for_manual_login(self.driver, timeout_sec=timeout_sec)
                if login_error:
                    return UiDownloadResult(ok=False, path=None, error=login_error)
                if login_waited:
                    _safe_get(self.driver, referer_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
                time.sleep(1.0)
                _allow_downloads(self.driver, self.downloads_dir)
                self._login_checked = True

            nav_warning = _safe_get(self.driver, url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
            login_waited, login_error = _wait_for_manual_login(self.driver, timeout_sec=timeout_sec)
            if login_error:
                return UiDownloadResult(ok=False, path=None, error=login_error)
            if login_waited:
                nav_warning = _safe_get(self.driver, url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
            self._login_checked = True
            _allow_downloads(self.driver, self.downloads_dir)
            if _looks_like_invalid_owner_page(self.driver):
                return UiDownloadResult(ok=False, path=None, error=f"Bitrix открыл ссылку без контекста ownerTypeId/ownerId: {_page_context(self.driver)}")

            quick = _wait_for_download(self.downloads_dir, before, timeout_sec=min(8, timeout_sec), driver=self.driver)
            if quick.ok or quick.path:
                return quick

            clicked = _click_first_download_control(self.driver, self.By)
            remaining = max(5, min(45, int(timeout_sec) - 8))
            final = _wait_for_download(self.downloads_dir, before, timeout_sec=remaining, driver=self.driver)
            if final.ok or final.path:
                return final

            details = []
            if nav_warning:
                details.append(nav_warning)
            if clicked:
                details.append(str(clicked))
            if final.error:
                details.append(final.error)
            return UiDownloadResult(ok=False, path=None, error="; ".join(details) or "UI download failed")
        except self.WebDriverException as e:
            return UiDownloadResult(ok=False, path=None, error=f"Selenium error: {e}")

    def download_call_from_deal_timeline(
        self,
        deal_url: str,
        activity_id: int,
        timeout_sec: int = DEFAULT_UI_TIMEOUT_SEC,
    ) -> UiDownloadResult:
        By = self.By
        EC = self.EC
        timeout_sec = max(5, int(timeout_sec or DEFAULT_UI_TIMEOUT_SEC))
        wait = self.WebDriverWait(self.driver, min(10, max(1, timeout_sec)))

        def wait_download(before, seconds: int) -> UiDownloadResult:
            return _wait_for_download(self.downloads_dir, before, timeout_sec=seconds, driver=self.driver)

        try:
            before = _snapshot_downloads(self.downloads_dir)
            nav_warning = _safe_get(self.driver, deal_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
            login_waited, login_error = _wait_for_manual_login(self.driver, timeout_sec=timeout_sec)
            if login_error:
                return UiDownloadResult(ok=False, path=None, error=login_error)
            if login_waited:
                nav_warning = _safe_get(self.driver, deal_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
            _allow_downloads(self.driver, self.downloads_dir)

            deadline = time.time() + max(5, min(30, timeout_sec))
            while time.time() < deadline:
                try:
                    if "/crm/deal/details/" in str(self.driver.current_url or ""):
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            for y in (0, 500, 1200, 2200):
                try:
                    self.driver.execute_script("window.scrollTo(0, arguments[0]);", y)
                    time.sleep(0.5)
                except Exception:
                    pass

            link_xpaths = [
                f"//a[contains(@href, 'crm_show_file.php') and contains(@href, 'ownerId={int(activity_id)}')]",
                f"//a[contains(@href, 'fileId=') and contains(@href, 'ownerId={int(activity_id)}')]",
                f"//a[contains(@href, '{int(activity_id)}') and (contains(@href, 'download') or contains(@href, 'crm_show_file.php'))]",
            ]
            for xp in link_xpaths:
                try:
                    links = self.driver.find_elements(By.XPATH, xp)
                except Exception:
                    links = []
                for link in links[:5]:
                    try:
                        href = _clean_url(link.get_attribute("href") or "")
                        if _is_contextless_disk_download_href(href):
                            continue
                        if href.startswith("http"):
                            _safe_get(self.driver, href, self.TimeoutException, timeout_sec=min(12, timeout_sec))
                            if _looks_like_invalid_owner_page(self.driver):
                                continue
                        else:
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                            self.driver.execute_script("arguments[0].click();", link)
                    except Exception:
                        continue
                    res = wait_download(before, seconds=min(8, timeout_sec))
                    if res.ok or res.path:
                        return res

            card = None
            card_locators = [
                (By.CSS_SELECTOR, f"[data-id='{int(activity_id)}']"),
                (By.CSS_SELECTOR, f"[data-entity-id='{int(activity_id)}']"),
                (By.XPATH, f"//*[contains(@data-id, '{int(activity_id)}')]"),
                (By.XPATH, f"//a[contains(@href, 'activity/view/{int(activity_id)}') or contains(@href, '{int(activity_id)}')]"),
                (By.XPATH, f"//a[contains(@href, 'crm_show_file.php') and contains(@href, 'ownerId={int(activity_id)}')]"),
            ]
            for by, sel in card_locators:
                try:
                    el = wait.until(EC.presence_of_element_located((by, sel)))
                    try:
                        card = el.find_element(
                            By.XPATH,
                            "ancestor-or-self::*[contains(@class,'crm-entity-stream-section') or contains(@class,'crm-timeline') or contains(@class,'crm-entity-stream-content')][1]",
                        )
                    except Exception:
                        card = el
                    if card:
                        break
                except Exception:
                    continue

            if not card:
                details = _page_context(self.driver)
                return UiDownloadResult(
                    ok=False,
                    path=None,
                    error=f"Не нашёл блок звонка в таймлайне по activity_id={activity_id}" + (f"; {details}" if details else ""),
                )

            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                time.sleep(0.5)
            except Exception:
                pass

            menu_btn = None
            menu_locators = [
                (By.XPATH, ".//button[contains(@aria-label,'Еще') or contains(@title,'Еще') or contains(@aria-label,'More') or contains(@title,'More')]"),
                (By.XPATH, ".//*[contains(@class,'ui-icon-set') and (contains(@class,'--more') or contains(@class,'more'))]"),
                (By.XPATH, ".//button[contains(., '…') or contains(., '...')]"),
                (By.XPATH, ".//*[contains(@class,'menu') or contains(@class,'more')]"),
            ]
            for by, sel in menu_locators:
                try:
                    menu_btn = card.find_element(by, sel)
                    if menu_btn:
                        break
                except Exception:
                    continue

            if not menu_btn:
                return UiDownloadResult(ok=False, path=None, error=f"Не нашёл кнопку меню у звонка; {_page_context(self.driver)}")

            try:
                menu_btn.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", menu_btn)
                except Exception as e:
                    return UiDownloadResult(ok=False, path=None, error=f"Не удалось кликнуть меню: {e}; {_page_context(self.driver)}")

            try:
                dl_item = wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//*[contains(@class,'menu-popup') or contains(@class,'ui-context-menu') or contains(@class,'popup-window')]//*[contains(., 'Скачать') or contains(., 'Download')]",
                        )
                    )
                )
                dl_item.click()
            except Exception:
                clicked = _click_first_download_control(self.driver, By)
                if not clicked:
                    return UiDownloadResult(ok=False, path=None, error=f"Не нашёл пункт 'Скачать'; {_page_context(self.driver)}")

            res = wait_download(before, seconds=timeout_sec)
            if res.ok or res.path:
                return res
            if nav_warning and res.error:
                res.error = f"{nav_warning}; {res.error}"
            return res
        except self.WebDriverException as e:
            return UiDownloadResult(ok=False, path=None, error=f"Selenium error: {e}")

    def fetch_transcript_from_deal_timeline(
        self,
        deal_url: str,
        activity_id: int,
        timeout_sec: int = DEFAULT_UI_TIMEOUT_SEC,
    ) -> UiTranscriptResult:
        By = self.By
        EC = self.EC
        timeout_sec = max(5, int(timeout_sec or DEFAULT_UI_TIMEOUT_SEC))
        wait = self.WebDriverWait(self.driver, min(10, max(1, timeout_sec)))

        try:
            nav_warning = _safe_get(self.driver, deal_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))
            login_waited, login_error = _wait_for_manual_login(self.driver, timeout_sec=timeout_sec)
            if login_error:
                return UiTranscriptResult(ok=False, error=login_error)
            if login_waited:
                nav_warning = _safe_get(self.driver, deal_url, self.TimeoutException, timeout_sec=min(30, timeout_sec))

            deadline = time.time() + max(5, min(20, timeout_sec))
            while time.time() < deadline:
                try:
                    if "/crm/deal/details/" in str(self.driver.current_url or ""):
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            for y in (0, 500, 1200, 2200):
                try:
                    self.driver.execute_script("window.scrollTo(0, arguments[0]);", y)
                    time.sleep(0.35)
                except Exception:
                    pass

            card = None
            card_locators = [
                (By.CSS_SELECTOR, f"[data-id='{int(activity_id)}']"),
                (By.CSS_SELECTOR, f"[data-entity-id='{int(activity_id)}']"),
                (By.XPATH, f"//*[contains(@data-id, '{int(activity_id)}')]"),
                (By.XPATH, f"//a[contains(@href, 'activity/view/{int(activity_id)}') or contains(@href, '{int(activity_id)}')]"),
            ]
            for by, sel in card_locators:
                try:
                    el = wait.until(EC.presence_of_element_located((by, sel)))
                    try:
                        card = el.find_element(
                            By.XPATH,
                            "ancestor-or-self::*[contains(@class,'crm-entity-stream-section') or contains(@class,'crm-timeline') or contains(@class,'crm-entity-stream-content')][1]",
                        )
                    except Exception:
                        card = el
                    if card:
                        break
                except Exception:
                    continue

            if not card:
                details = _page_context(self.driver)
                warning = f"; {nav_warning}" if nav_warning else ""
                return UiTranscriptResult(ok=False, error=f"Не нашёл блок звонка в таймлайне по activity_id={activity_id}{warning}" + (f"; {details}" if details else ""))

            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                time.sleep(0.5)
            except Exception:
                pass

            before_body = _visible_text_from_element(self.driver)
            before_card = _visible_text_from_element(self.driver, card)

            transcript_controls = []
            control_xpaths = [
                ".//*[self::button or self::a or self::div or self::span][contains(@title,'Расшиф') or contains(@aria-label,'Расшиф') or contains(., 'Расшифров')]",
                ".//*[self::button or self::a or self::div or self::span][normalize-space(.)='A' or normalize-space(.)='>A' or contains(normalize-space(.), '→A')]",
                ".//*[self::button or self::a][contains(@class,'transcript') or contains(@class,'ai') or contains(@class,'speech')]",
            ]
            for xp in control_xpaths:
                try:
                    for el in card.find_elements(By.XPATH, xp):
                        if el.is_displayed():
                            transcript_controls.append(el)
                except Exception:
                    continue

            last_error = None
            for control in transcript_controls[:8]:
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", control)
                    time.sleep(0.2)
                    try:
                        control.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", control)
                    time.sleep(2.0)
                    for _ in range(max(2, min(8, timeout_sec // 2))):
                        body_text = _visible_text_from_element(self.driver)
                        card_text = _visible_text_from_element(self.driver, card)
                        text = _extract_new_transcript_text(before_body, body_text) or _extract_new_transcript_text(before_card, card_text)
                        if text:
                            return UiTranscriptResult(ok=True, text=text)
                        time.sleep(1.0)
                except Exception as e:
                    last_error = str(e)
                    continue

            return UiTranscriptResult(ok=False, error=f"Не нашёл или не прочитал кнопку расшифровки в карточке звонка" + (f": {last_error}" if last_error else ""))
        except self.WebDriverException as e:
            return UiTranscriptResult(ok=False, error=f"Selenium error: {e}")


def download_url_via_ui(
    url: str,
    downloads_dir: Path,
    chrome_profile_dir: Optional[str] = None,
    browser: str = "chrome",
    timeout_sec: int = DEFAULT_UI_TIMEOUT_SEC,
    referer_url: Optional[str] = None,
    browser_profile_directory: Optional[str] = None,
) -> UiDownloadResult:
    """
    Открывает точную ссылку Bitrix через авторизованный браузер и ждёт реальный файл.
    Для записей звонков это обычно надёжнее, чем REST: cookies браузера дают доступ к crm_show_file.php.
    """
    url = _clean_url(url)
    referer_url = _clean_url(referer_url)
    if not isinstance(url, str) or not url.startswith("http"):
        return UiDownloadResult(ok=False, path=None, error=f"Некорректный URL для UI-скачивания: {url!r}")

    downloads_dir.mkdir(parents=True, exist_ok=True)
    try:
        driver, By, WebDriverWait, EC, TimeoutException, WebDriverException = _create_driver(
            browser=browser,
            downloads_dir=downloads_dir,
            chrome_profile_dir=chrome_profile_dir,
            browser_profile_directory=browser_profile_directory,
        )
    except Exception as e:
        return UiDownloadResult(ok=False, path=None, error=str(e))

    try:
        timeout_sec = max(5, int(timeout_sec or DEFAULT_UI_TIMEOUT_SEC))
        before = _snapshot_downloads(downloads_dir)
        if referer_url:
            _safe_get(driver, referer_url, TimeoutException, timeout_sec=min(30, timeout_sec))
            login_waited, login_error = _wait_for_manual_login(driver, timeout_sec=timeout_sec)
            if login_error:
                return UiDownloadResult(ok=False, path=None, error=login_error)
            if login_waited:
                _safe_get(driver, referer_url, TimeoutException, timeout_sec=min(30, timeout_sec))
            time.sleep(1.0)
            _allow_downloads(driver, downloads_dir)

        nav_warning = _safe_get(driver, url, TimeoutException, timeout_sec=min(30, timeout_sec))
        login_waited, login_error = _wait_for_manual_login(driver, timeout_sec=timeout_sec)
        if login_error:
            return UiDownloadResult(ok=False, path=None, error=login_error)
        if login_waited:
            nav_warning = _safe_get(driver, url, TimeoutException, timeout_sec=min(30, timeout_sec))
        _allow_downloads(driver, downloads_dir)
        if _looks_like_invalid_owner_page(driver):
            return UiDownloadResult(ok=False, path=None, error=f"Bitrix открыл ссылку без контекста ownerTypeId/ownerId: {_page_context(driver)}")

        quick = _wait_for_download(downloads_dir, before, timeout_sec=min(8, timeout_sec), driver=driver)
        if quick.ok or quick.path:
            return quick

        clicked = _click_first_download_control(driver, By)
        remaining = max(5, min(45, int(timeout_sec) - 8))
        final = _wait_for_download(downloads_dir, before, timeout_sec=remaining, driver=driver)
        if final.ok or final.path:
            return final

        details = []
        if nav_warning:
            details.append(nav_warning)
        if clicked:
            details.append(str(clicked))
        if final.error:
            details.append(final.error)
        return UiDownloadResult(ok=False, path=None, error="; ".join(details) or "UI download failed")
    except WebDriverException as e:
        return UiDownloadResult(ok=False, path=None, error=f"Selenium error: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def download_call_from_deal_timeline_via_ui(
    deal_url: str,
    activity_id: int,
    downloads_dir: Path,
    chrome_profile_dir: Optional[str] = None,
    browser: str = "chrome",
    timeout_sec: int = DEFAULT_UI_TIMEOUT_SEC,
    browser_profile_directory: Optional[str] = None,
) -> UiDownloadResult:
    """
    UI-скачивание через сделку: открыть таймлайн, найти ссылку файла или пункт "Скачать".
    """
    downloads_dir.mkdir(parents=True, exist_ok=True)
    try:
        driver, By, WebDriverWait, EC, TimeoutException, WebDriverException = _create_driver(
            browser=browser,
            downloads_dir=downloads_dir,
            chrome_profile_dir=chrome_profile_dir,
            browser_profile_directory=browser_profile_directory,
        )
    except Exception as e:
        return UiDownloadResult(ok=False, path=None, error=str(e))

    def wait_download(before, seconds: int) -> UiDownloadResult:
        return _wait_for_download(downloads_dir, before, timeout_sec=seconds, driver=driver)

    try:
        timeout_sec = max(5, int(timeout_sec or DEFAULT_UI_TIMEOUT_SEC))
        before = _snapshot_downloads(downloads_dir)
        nav_warning = _safe_get(driver, deal_url, TimeoutException, timeout_sec=min(30, timeout_sec))
        login_waited, login_error = _wait_for_manual_login(driver, timeout_sec=timeout_sec)
        if login_error:
            return UiDownloadResult(ok=False, path=None, error=login_error)
        if login_waited:
            nav_warning = _safe_get(driver, deal_url, TimeoutException, timeout_sec=min(30, timeout_sec))
        _allow_downloads(driver, downloads_dir)

        wait = WebDriverWait(driver, min(20, timeout_sec))
        deadline = time.time() + max(5, min(30, timeout_sec))
        while time.time() < deadline:
            try:
                if "/crm/deal/details/" in str(driver.current_url or ""):
                    break
            except Exception:
                pass
            time.sleep(0.5)

        # Timeline may lazy-load; scroll a bit to force rendering.
        for y in (0, 500, 1200, 2200):
            try:
                driver.execute_script("window.scrollTo(0, arguments[0]);", y)
                time.sleep(0.5)
            except Exception:
                pass

        link_xpaths = [
            f"//a[contains(@href, 'crm_show_file.php') and contains(@href, 'ownerId={int(activity_id)}')]",
            f"//a[contains(@href, 'fileId=') and contains(@href, 'ownerId={int(activity_id)}')]",
            f"//a[contains(@href, '{int(activity_id)}') and (contains(@href, 'download') or contains(@href, 'crm_show_file.php'))]",
        ]
        for xp in link_xpaths:
            try:
                links = driver.find_elements(By.XPATH, xp)
            except Exception:
                links = []
            for link in links[:5]:
                href = ""
                try:
                    href = _clean_url(link.get_attribute("href") or "")
                    if _is_contextless_disk_download_href(href):
                        continue
                    if href.startswith("http"):
                        _safe_get(driver, href, TimeoutException, timeout_sec=min(12, timeout_sec))
                        if _looks_like_invalid_owner_page(driver):
                            continue
                    else:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                        driver.execute_script("arguments[0].click();", link)
                except Exception:
                    continue
                res = wait_download(before, seconds=min(8, timeout_sec))
                if res.ok or res.path:
                    return res

        card = None
        card_locators = [
            (By.CSS_SELECTOR, f"[data-id='{int(activity_id)}']"),
            (By.CSS_SELECTOR, f"[data-entity-id='{int(activity_id)}']"),
            (By.XPATH, f"//*[contains(@data-id, '{int(activity_id)}')]"),
            (By.XPATH, f"//a[contains(@href, 'activity/view/{int(activity_id)}') or contains(@href, '{int(activity_id)}')]"),
            (By.XPATH, f"//a[contains(@href, 'crm_show_file.php') and contains(@href, 'ownerId={int(activity_id)}')]"),
        ]
        for by, sel in card_locators:
            try:
                el = wait.until(EC.presence_of_element_located((by, sel)))
                try:
                    card = el.find_element(
                        By.XPATH,
                        "ancestor-or-self::*[contains(@class,'crm-entity-stream-section') or contains(@class,'crm-timeline') or contains(@class,'crm-entity-stream-content')][1]",
                    )
                except Exception:
                    card = el
                if card:
                    break
            except Exception:
                continue

        if not card:
            details = _page_context(driver)
            return UiDownloadResult(
                ok=False,
                path=None,
                error=f"Не нашёл блок звонка в таймлайне по activity_id={activity_id}" + (f"; {details}" if details else ""),
            )

        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
            time.sleep(0.5)
        except Exception:
            pass

        menu_btn = None
        menu_locators = [
            (By.XPATH, ".//button[contains(@aria-label,'Еще') or contains(@title,'Еще') or contains(@aria-label,'More') or contains(@title,'More')]"),
            (By.XPATH, ".//*[contains(@class,'ui-icon-set') and (contains(@class,'--more') or contains(@class,'more'))]"),
            (By.XPATH, ".//button[contains(., '…') or contains(., '...')]"),
            (By.XPATH, ".//*[contains(@class,'menu') or contains(@class,'more')]"),
        ]
        for by, sel in menu_locators:
            try:
                menu_btn = card.find_element(by, sel)
                if menu_btn:
                    break
            except Exception:
                continue

        if not menu_btn:
            return UiDownloadResult(ok=False, path=None, error=f"Не нашёл кнопку меню у звонка; {_page_context(driver)}")

        try:
            menu_btn.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", menu_btn)
            except Exception as e:
                return UiDownloadResult(ok=False, path=None, error=f"Не удалось кликнуть меню: {e}; {_page_context(driver)}")

        try:
            dl_item = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//*[contains(@class,'menu-popup') or contains(@class,'ui-context-menu') or contains(@class,'popup-window')]//*[contains(., 'Скачать') or contains(., 'Download')]",
                    )
                )
            )
            dl_item.click()
        except Exception:
            clicked = _click_first_download_control(driver, By)
            if not clicked:
                return UiDownloadResult(ok=False, path=None, error=f"Не нашёл пункт 'Скачать'; {_page_context(driver)}")

        res = wait_download(before, seconds=timeout_sec)
        if res.ok or res.path:
            return res
        if nav_warning and res.error:
            res.error = f"{nav_warning}; {res.error}"
        return res
    except WebDriverException as e:
        return UiDownloadResult(ok=False, path=None, error=f"Selenium error: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
