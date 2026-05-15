import requests
import random
import time
from typing import Dict, List, Any, Optional
import config

from logging_setup import get_logger

logger = get_logger(__name__)


class Bitrix24API:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or config.BITRIX24_WEBHOOK
        if not self.webhook_url:
            raise ValueError("Webhook URL не настроен. Проверьте файл .env")

        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })

    def call(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Вызов метода Bitrix24 REST API"""
        url = f"{self.webhook_url}{method}"

        max_attempts = int(getattr(config, "BITRIX24_MAX_ATTEMPTS", 5) or 5)
        timeout_sec = float(getattr(config, "BITRIX24_TIMEOUT_SEC", 30) or 30)
        base_backoff = float(getattr(config, "BITRIX24_BACKOFF_BASE_SEC", 0.6) or 0.6)
        max_backoff = float(getattr(config, "BITRIX24_BACKOFF_MAX_SEC", 20.0) or 20.0)

        last_error: Optional[str] = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.post(url, json=params or {}, timeout=timeout_sec)
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

                # Bitrix может возвращать 429/5xx — ретраим
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
                        # exp backoff + jitter
                        sleep_for = min(max_backoff, base_backoff * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                    logger.warning(f"[WARN] Retry {attempt}/{max_attempts} {method} (request_id={request_id}): {last_error}; sleep={sleep_for:.2f}s")
                    if attempt < max_attempts:
                        time.sleep(sleep_for)
                        continue

                if response.status_code >= 400:
                    error_description = data.get('error_description') if isinstance(data, dict) else None
                    details = error_description or response.text
                    raise Exception(
                        f"HTTP {response.status_code} при вызове {method} (request_id={request_id}): {details}"
                    )

                if isinstance(data, dict) and 'error' in data:
                    raise Exception(f"Bitrix24 API Error: {data['error']} - {data.get('error_description', '')} (request_id={request_id})")

                return data
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                sleep_for = min(max_backoff, base_backoff * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                logger.warning(f"[WARN] Retry {attempt}/{max_attempts} {method}: {last_error}; sleep={sleep_for:.2f}s")
                if attempt < max_attempts:
                    time.sleep(sleep_for)
                    continue
                raise Exception(f"Ошибка запроса к API после {max_attempts} попыток: {last_error}")
            except requests.exceptions.RequestException as e:
                # остальные ошибки requests обычно не ретраим
                raise Exception(f"Ошибка запроса к API: {str(e)}")

        raise Exception(f"Ошибка запроса к API: {last_error or 'unknown error'}")

    def call_batch(self, calls: Dict[str, Dict]) -> Dict[str, Any]:
        """Пакетный вызов методов (до 50 за раз)"""
        cmd = {}
        for key, call_data in calls.items():
            method = call_data['method']
            params = call_data.get('params', {})
            param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
            cmd[key] = f"{method}?{param_str}"

        return self.call('batch', {'cmd': cmd})

    def get_all(self, method: str, params: Dict[str, Any] = None) -> List[Dict]:
        """Получить все записи с автоматической пагинацией"""
        all_items = []
        start = 0

        if params is None:
            params = {}

        while True:
            params['start'] = start
            result = self.call(method, params)

            items = result.get('result', [])
            if not items:
                break

            all_items.extend(items)

            total = result.get('total', 0)
            if start + len(items) >= total:
                break

            start += 50
            time.sleep(0.5)

        return all_items

    def test_connection(self) -> bool:
        """Проверка подключения к API"""
        try:
            result = self.call('profile')
            logger.info(f"[OK] Podklyuchenie uspeshno! Polzovatel: {result['result'].get('NAME', 'Unknown')}")
            return True
        except Exception as e:
            logger.error(f"[ERROR] Oshibka podklyucheniya: {str(e)}")
            return False
