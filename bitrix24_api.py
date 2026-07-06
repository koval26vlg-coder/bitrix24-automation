import asyncio
import os
import random
from typing import Any

import httpx

import config
from logging_setup import get_logger

logger = get_logger(__name__)


class Bitrix24API:
    def __init__(self, webhook_url: str | None = None, readonly: bool = False):
        self.webhook_url = webhook_url or config.BITRIX24_WEBHOOK
        if not self.webhook_url:
            raise ValueError("Webhook URL не настроен. Проверьте файл .env")

        self.readonly = readonly
        source_ip = (os.getenv("BITRIX24_SOURCE_IP", "") or "").strip()
        transport = None
        if source_ip:
            transport = httpx.AsyncHTTPTransport(local_address=source_ip)
            logger.info(f"[NET] Bitrix24API source IP bind enabled: {source_ip}")

        self.client = httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=float(getattr(config, "BITRIX24_TIMEOUT_SEC", 30) or 30),
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def aclose(self):
        """Закрыть клиент httpx"""
        await self.client.aclose()

    async def call(self, method: str, params: dict[str, Any] = None) -> dict[str, Any]:
        """Асинхронный вызов метода Bitrix24 REST API"""
        if self.readonly:
            # Разрешаем только безопасные методы чтения.
            # batch может содержать записи, но мы полагаемся на то, что вызывающий код
            # также учитывает флаг dry_run. Централизованно блокируем самые опасные.
            safe_methods = {
                "crm.activity.get",
                "crm.activity.list",
                "crm.category.list",
                "crm.company.get",
                "crm.company.list",
                "crm.contact.get",
                "crm.deal.fields",
                "crm.deal.get",
                "crm.deal.list",
                "crm.dealcategory.list",
                "crm.lead.list",
                "crm.stagehistory.list",
                "crm.status.list",
                "crm.timeline.comment.list",
                "department.get",
                "disk.file.get",
                "disk.file.getExternalLink",
                "disk.folder.getchildren",
                "profile",
                "user.get",
                "voximplant.statistic.get",
            }
            if method not in safe_methods and not method.startswith("batch"):
                logger.info(f"[DRY-RUN] Пропущен вызов записи Bitrix24: {method}")
                return {"result": True, "dry_run": True, "skipped": True}

        url = f"{self.webhook_url}{method}"

        max_attempts = int(getattr(config, "BITRIX24_MAX_ATTEMPTS", 5) or 5)
        base_backoff = float(getattr(config, "BITRIX24_BACKOFF_BASE_SEC", 0.6) or 0.6)
        max_backoff = float(getattr(config, "BITRIX24_BACKOFF_MAX_SEC", 20.0) or 20.0)

        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.client.post(url, json=params or {})
                request_id = (
                    response.headers.get("X-Request-Id")
                    or response.headers.get("X-Request-ID")
                    or response.headers.get("X-RequestID")
                    or response.headers.get("X-Bitrix-Request-Id")
                )
                try:
                    data = response.json()
                except ValueError:
                    data = {}

                if response.status_code in (429,) or 500 <= response.status_code <= 599:
                    details = None
                    if isinstance(data, dict):
                        details = data.get("error_description") or data.get("error")
                    details = details or response.text
                    last_error = f"HTTP {response.status_code} {method}: {details}"

                    retry_after = response.headers.get("Retry-After")
                    sleep_for = None
                    if retry_after:
                        try:
                            sleep_for = float(retry_after)
                        except Exception:
                            sleep_for = None

                    if sleep_for is None:
                        sleep_for = min(max_backoff, base_backoff * (2 ** (attempt - 1))) * (
                            0.7 + random.random() * 0.6
                        )

                    logger.warning(
                        f"[WARN] Retry {attempt}/{max_attempts} {method} (request_id={request_id}): {last_error}; sleep={sleep_for:.2f}s"  # noqa: E501
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(sleep_for)
                        continue

                if response.status_code >= 400:
                    error_description = (
                        data.get("error_description") if isinstance(data, dict) else None
                    )
                    details = error_description or response.text
                    raise Exception(
                        f"HTTP {response.status_code} при вызове {method} (request_id={request_id}): {details}"  # noqa: E501
                    )

                if isinstance(data, dict) and "error" in data:
                    error_code = data["error"]
                    error_description = data.get("error_description", "")
                    raise Exception(
                        f"Bitrix24 API Error: {error_code} - {error_description} "
                        f"(request_id={request_id})"
                    )

                return data

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                sleep_for = min(max_backoff, base_backoff * (2 ** (attempt - 1))) * (
                    0.7 + random.random() * 0.6
                )
                logger.warning(
                    f"[WARN] Retry {attempt}/{max_attempts} {method}: {last_error}; sleep={sleep_for:.2f}s"  # noqa: E501
                )
                if attempt < max_attempts:
                    await asyncio.sleep(sleep_for)
                    continue
                raise Exception(
                    f"Ошибка запроса к API после {max_attempts} попыток: {last_error}"
                ) from e
            except httpx.RequestError as e:
                raise Exception(f"Ошибка запроса к API: {str(e)}") from e

        error_text = last_error or "unknown error"
        raise Exception(f"Ошибка запроса к API: {error_text}")

    async def call_batch(self, calls: dict[str, dict]) -> dict[str, Any]:
        """Асинхронный пакетный вызов методов (до 50 за раз)"""
        cmd = {}
        for key, call_data in calls.items():
            method = call_data["method"]
            params = call_data.get("params", {})
            param_list = []
            for k, v in params.items():
                param_list.append(f"{k}={v}")
            param_str = "&".join(param_list)
            cmd[key] = f"{method}?{param_str}"

        return await self.call("batch", {"cmd": cmd})

    async def get_all(self, method: str, params: dict[str, Any] = None) -> list[dict]:
        """Получить все записи с автоматической пагинацией (асинхронно)"""
        all_items = []
        start = 0

        if params is None:
            params = {}

        while True:
            params["start"] = start
            result = await self.call(method, params)

            items = result.get("result", [])
            if not items:
                break

            all_items.extend(items)

            total = result.get("total", 0)
            if start + len(items) >= total:
                break

            start += 50
            await asyncio.sleep(0.5)

        return all_items

    async def test_connection(self) -> bool:
        """Проверка подключения к API (асинхронно)"""
        try:
            result = await self.call("profile")
            name = result.get("result", {}).get("NAME", "Unknown")
            logger.info(f"[OK] Подключение успешно! Пользователь: {name}")
            return True
        except Exception as e:
            logger.error(f"[ERROR] Ошибка подключения: {str(e)}")
            return False
