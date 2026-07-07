from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx


@dataclass
class DownloadAttempt:
    url: str
    status_code: int | None
    final_url: str | None
    history: list[int]
    content_type: str | None
    note: str = ""


@dataclass
class DownloadResult:
    ok: bool
    path: Path | None
    attempts: list[DownloadAttempt]
    error: str | None = None


def _source_ip_from_env(source_ip: str | None = None) -> str:
    return (source_ip if source_ip is not None else os.getenv("BITRIX24_SOURCE_IP", "")).strip()


def _looks_like_html_prefix(data: bytes) -> bool:
    if not data:
        return True
    head = data.lstrip()[:200].lower()
    return (
        head.startswith(b"<!doctype")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
        or head.startswith(b"<body")
    )


def _resolve_any_download_href(html: str, base_url: str) -> str | None:
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
    source_ip: str | None = None,
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

    async def _try_url(client: httpx.AsyncClient, u: str, referer: str | None) -> Path | None:
        nonlocal attempts
        h = dict(headers)
        if referer:
            h["Referer"] = referer

        try:
            async with client.stream(
                "GET", u, timeout=timeout_sec, follow_redirects=True, headers=h
            ) as r:
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

                byte_iter = r.aiter_bytes(chunk_size=1024 * 256)
                first_chunk = await anext(byte_iter, b"")
                if not first_chunk:
                    attempts[-1].note = "empty-body"
                    return None

                # если html — попробуем вытащить download href
                if ctype and "text/html" in ctype:
                    html_buf = bytearray(first_chunk)
                    if len(html_buf) < 200000:
                        async for chunk in byte_iter:
                            if not chunk:
                                continue
                            html_buf.extend(chunk)
                            if len(html_buf) >= 200000:
                                break
                    html_text = bytes(html_buf).decode("utf-8", errors="ignore")
                    direct = (
                        _resolve_any_download_href(html_text, base_url=base_url)
                        if base_url
                        else None
                    )
                    attempts[-1].note = "html"
                    if not direct:
                        return None
                    # второй шаг по извлеченной ссылке (рекурсивно, но в асинхронном клиенте это ок)
                    return await _try_url(client, direct, referer=u)

                # иначе считаем, что это файл; проверим первые байты
                if _looks_like_html_prefix(first_chunk):
                    html_text = first_chunk.decode("utf-8", errors="ignore")
                    direct = (
                        _resolve_any_download_href(html_text, base_url=base_url)
                        if base_url
                        else None
                    )
                    attempts[-1].note = "html-bytes"
                    if direct:
                        return await _try_url(client, direct, referer=u)
                    return None

                written = 0
                with out_path.open("wb") as f:
                    f.write(first_chunk)
                    written += len(first_chunk)
                    async for chunk in byte_iter:
                        if not chunk:
                            continue
                        f.write(chunk)
                        written += len(chunk)
                        if written > max_total_bytes:
                            raise RuntimeError(
                                f"Файл слишком большой (> {max_total_bytes} bytes), прервал скачивание."  # noqa: E501
                            )
                return out_path
        except Exception as e:
            msg = str(e) or repr(e)
            if not attempts or attempts[-1].url != u:
                attempts.append(
                    DownloadAttempt(
                        url=u,
                        status_code=None,
                        final_url=None,
                        history=[],
                        content_type=None,
                        note=f"error: {msg}",
                    )
                )
            else:
                attempts[-1].note += f" error: {msg}"
            return None

    clean_candidates = [
        html_lib.unescape(c).strip()
        for c in candidates
        if isinstance(c, str) and c.startswith("http")
    ]
    last_err = None

    client_kwargs = {}
    bind_ip = _source_ip_from_env(source_ip)
    if bind_ip:
        client_kwargs["transport"] = httpx.AsyncHTTPTransport(local_address=bind_ip)

    async with httpx.AsyncClient(**client_kwargs) as client:
        for _ in range(retries + 1):
            for i, u in enumerate(clean_candidates):
                try:
                    p = await _try_url(
                        client, u, referer=clean_candidates[i - 1] if i > 0 else None
                    )
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
    return DownloadResult(
        ok=False, path=None, attempts=attempts, error=last_err or "download failed"
    )
