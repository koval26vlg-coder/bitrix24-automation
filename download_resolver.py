from __future__ import annotations
import asyncio
import re
import html as html_lib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx


@dataclass
class DownloadAttempt:
    url: str
    status_code: Optional[int]
    final_url: Optional[str]
    history: list[int]
    content_type: Optional[str]
    note: str = ""


@dataclass
class DownloadResult:
    ok: bool
    path: Optional[Path]
    attempts: list[DownloadAttempt]
    error: Optional[str] = None


def _looks_like_html_prefix(data: bytes) -> bool:
    if not data:
        return True
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<head") or head.startswith(b"<body")


def _resolve_any_download_href(html: str, base_url: str) -> Optional[str]:
    if not html:
        return None
    patterns = [
        r"href=\"([^\"]+/docs/pub/[^\"]+/download\?token=[^\"]+)\"",
        r"href=\"([^\"]+/docs/pub/[^\"]+/download[^\"]+)\"",
        r"href=\"([^\"]+/docs/pub/[^\"]+)\"",
        r"href=\"([^\"]+/bitrix/tools/[^\"]+)\"",
        r"href=\"([^\"]+/bitrix/[^\"]*download[^\"]+)\"",
        r"href=\"([^\"]+/download\?token=[^\"]+)\"",
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if not m:
            continue
        href = html_lib.unescape(m.group(1)).strip()
        href = re.sub(r"^/[^/]+\.bitrix24\.ru/", "/", href)
        if href.startswith("http"):
            return href
        return urljoin(base_url.rstrip("/") + "/", href)
    return None


async def download_best_effort(
    candidates: list[str],
    out_path: Path,
    timeout_sec: int = 180,
    max_total_bytes: int = 250 * 1024 * 1024,
    retries: int = 1,
) -> DownloadResult:
    """
    Пытается скачать файл по цепочке URL-кандидатов (асинхронно через httpx).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    attempts: list[DownloadAttempt] = []

    headers = {"User-Agent": "Mozilla/5.0"}
    base_url = None
    for u in candidates:
        u = html_lib.unescape(str(u)).strip()
        if u.startswith("http"):
            base_url = "https://" + u.split("://", 1)[1].split("/", 1)[0]
            break
    base_url = base_url or ""

    async def _try_url(client: httpx.AsyncClient, u: str, referer: Optional[str]) -> Optional[Path]:
        nonlocal attempts
        h = dict(headers)
        if referer:
            h["Referer"] = referer

        try:
            async with client.stream("GET", u, timeout=timeout_sec, follow_redirects=True, headers=h) as r:
                hist = [resp.status_code for resp in r.history]
                ctype = (r.headers.get("Content-Type") or "").lower() or None
                attempts.append(
                    DownloadAttempt(
                        url=u,
                        status_code=r.status_code,
                        final_url=str(r.url),
                        history=hist,
                        content_type=ctype,
                    )
                )
                if r.status_code >= 400:
                    return None

                # если html — попробуем вытащить download href
                if ctype and "text/html" in ctype:
                    first = await r.aiter_bytes(chunk_size=40000).__anext__()
                    html = first.decode("utf-8", errors="ignore")
                    direct = _resolve_any_download_href(html, base_url=base_url) if base_url else None
                    attempts[-1].note = "html"
                    if not direct:
                        return None
                    # второй шаг по извлеченной ссылке (рекурсивно, но в асинхронном клиенте это ок)
                    return await _try_url(client, direct, referer=u)

                # иначе считаем, что это файл; проверим первые байты
                first_chunk = await r.aiter_bytes(chunk_size=4096).__anext__()
                if _looks_like_html_prefix(first_chunk):
                    attempts[-1].note = "html-bytes"
                    return None

                written = 0
                with out_path.open("wb") as f:
                    f.write(first_chunk)
                    written += len(first_chunk)
                    async for chunk in r.aiter_bytes(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        written += len(chunk)
                        if written > max_total_bytes:
                            raise RuntimeError(f"Файл слишком большой (> {max_total_bytes} bytes), прервал скачивание.")
                return out_path
        except Exception as e:
            if not attempts or attempts[-1].url != u:
                attempts.append(DownloadAttempt(url=u, status_code=None, final_url=None, history=[], content_type=None, note=f"error: {e}"))
            else:
                attempts[-1].note += f" error: {e}"
            return None

    clean_candidates = [html_lib.unescape(c).strip() for c in candidates if isinstance(c, str) and c.startswith("http")]
    last_err = None
    
    async with httpx.AsyncClient() as client:
        for _ in range(retries + 1):
            for i, u in enumerate(clean_candidates):
                try:
                    p = await _try_url(client, u, referer=clean_candidates[i - 1] if i > 0 else None)
                    if p and p.exists() and p.stat().st_size > 0:
                        return DownloadResult(ok=True, path=p, attempts=attempts)
                except Exception as e:
                    last_err = str(e)
            await asyncio.sleep(0.5)

    # cleanup partial
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception:
        pass
    return DownloadResult(ok=False, path=None, attempts=attempts, error=last_err or "download failed")
