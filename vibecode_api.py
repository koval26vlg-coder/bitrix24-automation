from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from logging_setup import get_logger

logger = get_logger(__name__)


VIBECODE_BASE_URL = "https://vibecode.bitrix24.tech"

DEAL_FIELD_MAP = {
    "id": "ID",
    "title": "TITLE",
    "assignedById": "ASSIGNED_BY_ID",
    "stageId": "STAGE_ID",
    "createdAt": "DATE_CREATE",
    "updatedAt": "DATE_MODIFY",
    "closedAt": "CLOSEDATE",
    "contactId": "CONTACT_ID",
    "companyId": "COMPANY_ID",
    "comments": "COMMENTS",
    "amount": "OPPORTUNITY",
    "opportunity": "OPPORTUNITY",
    "currency": "CURRENCY_ID",
    "sourceId": "SOURCE_ID",
    "sourceDescription": "SOURCE_DESCRIPTION",
    "categoryId": "CATEGORY_ID",
    "stageSemanticId": "STAGE_SEMANTIC_ID",
}

ACTIVITY_FIELD_MAP = {
    "id": "ID",
    "createdAt": "CREATED",
    "startTime": "START_TIME",
    "endTime": "END_TIME",
    "subject": "SUBJECT",
    "originId": "ORIGIN_ID",
    "direction": "DIRECTION",
    "providerId": "PROVIDER_ID",
    "providerTypeId": "PROVIDER_TYPE_ID",
    "authorId": "AUTHOR_ID",
    "responsibleId": "RESPONSIBLE_ID",
    "ownerTypeId": "OWNER_TYPE_ID",
    "ownerId": "OWNER_ID",
    "typeId": "TYPE_ID",
}

STAGE_HISTORY_FIELD_MAP = {
    "id": "ID",
    "typeId": "TYPE_ID",
    "ownerId": "OWNER_ID",
    "createdAt": "CREATED_TIME",
    "categoryId": "CATEGORY_ID",
    "stageSemanticId": "STAGE_SEMANTIC_ID",
    "stageId": "STAGE_ID",
}

STATUS_FIELD_MAP = {
    "id": "ID",
    "entityId": "ENTITY_ID",
    "statusId": "STATUS_ID",
    "name": "NAME",
    "sort": "SORT",
}

FILTER_FIELD_MAP = {
    "ID": "id",
    "TITLE": "title",
    "ASSIGNED_BY_ID": "assignedById",
    "STAGE_ID": "stageId",
    "DATE_CREATE": "createdAt",
    "CATEGORY_ID": "categoryId",
    "STAGE_SEMANTIC_ID": "stageSemanticId",
    "OPPORTUNITY": "amount",
    "SOURCE_ID": "sourceId",
}


class VibeCodeError(RuntimeError):
    pass


def _map_keys(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    out = dict(row)
    for src, dst in mapping.items():
        if src in row and dst not in out:
            out[dst] = row.get(src)
    return out


def vibe_deal_to_bitrix(row: dict[str, Any]) -> dict[str, Any]:
    return _map_keys(row, DEAL_FIELD_MAP)


def vibe_activity_to_bitrix(row: dict[str, Any]) -> dict[str, Any]:
    return _map_keys(row, ACTIVITY_FIELD_MAP)


def vibe_stage_history_to_bitrix(row: dict[str, Any]) -> dict[str, Any]:
    return _map_keys(row, STAGE_HISTORY_FIELD_MAP)


def vibe_status_to_bitrix(row: dict[str, Any]) -> dict[str, Any]:
    return _map_keys(row, STATUS_FIELD_MAP)


def _split_operator_key(key: str) -> tuple[str, str]:
    text = str(key or "")
    for op in (">=", "<=", ">", "<", "!", "%", "="):
        if text.startswith(op):
            return op, text[len(op) :]
    return "", text


def _vibe_operator(op: str) -> str:
    if op == "=":
        return ""
    return op


def bitrix_filter_to_vibe(flt: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, value in (flt or {}).items():
        op, bare_key = _split_operator_key(str(raw_key))
        mapped = FILTER_FIELD_MAP.get(bare_key, bare_key)
        out[f"{_vibe_operator(op)}{mapped}"] = value
    return out


class VibeCodeClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = VIBECODE_BASE_URL,
        timeout_sec: float = 30.0,
        max_attempts: int = 3,
    ):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("VIBECODE_API_KEY не задан")
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = float(timeout_sec or 30.0)
        self.max_attempts = max(1, int(max_attempts or 3))
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": self.api_key})

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout_sec, **kwargs)
                if response.status_code in (429,) or 500 <= response.status_code <= 599:
                    last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                    if attempt < self.max_attempts:
                        sleep_for = min(10.0, 0.5 * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                        logger.warning(
                            f"[WARN] Retry {attempt}/{self.max_attempts} VibeCode {method} {path}: "
                            f"{last_error}; sleep={sleep_for:.2f}s"
                        )
                        time.sleep(sleep_for)
                        continue
                if response.status_code >= 400:
                    raise VibeCodeError(f"VibeCode {method} {path} HTTP {response.status_code}: {response.text[:1000]}")

                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type:
                    return response
                data = response.json()
                if isinstance(data, dict) and data.get("success") is False:
                    raise VibeCodeError(f"VibeCode {method} {path}: {data.get('error') or data}")
                return data
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < self.max_attempts:
                    sleep_for = min(10.0, 0.5 * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
                    logger.warning(
                        f"[WARN] Retry {attempt}/{self.max_attempts} VibeCode {method} {path}: "
                        f"{last_error}; sleep={sleep_for:.2f}s"
                    )
                    time.sleep(sleep_for)
                    continue
                raise VibeCodeError(f"VibeCode request failed after {self.max_attempts} attempts: {last_error}")
        raise VibeCodeError(last_error or f"VibeCode {method} {path} failed")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=body or {})

    def me(self) -> dict[str, Any]:
        data = self.get("/v1/me")
        return data.get("data") if isinstance(data, dict) else {}

    def get_deal(self, deal_id: str) -> dict[str, Any]:
        data = self.get(f"/v1/deals/{int(deal_id)}")
        row = data.get("data") if isinstance(data, dict) else {}
        return vibe_deal_to_bitrix(row or {})

    def search_deals(self, flt: dict[str, Any], limit: int = 200, sort: dict[str, str] | None = None) -> list[dict[str, Any]]:
        data = self.post(
            "/v1/deals/search",
            {
                "filter": bitrix_filter_to_vibe(flt),
                "sort": sort or {"id": "desc"},
                "limit": max(1, min(5000, int(limit or 200))),
            },
        )
        rows = data.get("data") if isinstance(data, dict) else []
        return [vibe_deal_to_bitrix(row) for row in rows if isinstance(row, dict)]

    def list_deal_call_activities(self, deal_id: str, limit: int = 500) -> list[dict[str, Any]]:
        data = self.post(
            "/v1/activities/search",
            {
                "filter": {
                    "ownerTypeId": 2,
                    "ownerId": int(deal_id),
                    "typeId": 2,
                    "providerId": "VOXIMPLANT_CALL",
                },
                "sort": {"startTime": "asc"},
                "limit": max(1, min(5000, int(limit or 500))),
            },
        )
        rows = data.get("data") if isinstance(data, dict) else []
        return [vibe_activity_to_bitrix(row) for row in rows if isinstance(row, dict)]

    def fetch_stage_history(self, deal_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {str(deal_id): [] for deal_id in deal_ids if deal_id}
        for deal_id in dict.fromkeys(str(deal_id) for deal_id in deal_ids if str(deal_id).isdigit()):
            data = self.get("/v1/stage-history", params={"entityType": "deal", "ownerId": int(deal_id), "limit": 5000})
            rows = data.get("data") if isinstance(data, dict) else []
            out[str(deal_id)] = [vibe_stage_history_to_bitrix(row) for row in rows if isinstance(row, dict)]
        return out

    def fetch_stage_name_map(self, entity_ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for entity_id in sorted(set(entity_ids)):
            data = self.post("/v1/statuses/search", {"filter": {"entityId": entity_id}, "limit": 5000})
            rows = data.get("data") if isinstance(data, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                status = vibe_status_to_bitrix(row)
                sid = str(status.get("STATUS_ID") or "").strip()
                name = str(status.get("NAME") or "").strip()
                if sid and name:
                    out[sid] = name
        return out

    def download_file(self, file_id: int, out_path: Path) -> Path:
        response = self._request("GET", f"/v1/files/{int(file_id)}/download", stream=True)
        if not isinstance(response, requests.Response):
            raise VibeCodeError(f"VibeCode file download returned JSON for file {file_id}: {response}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
        return out_path

    def transcribe_audio(self, audio_path: Path, language: str = "ru") -> str:
        with Path(audio_path).open("rb") as handle:
            files = {"file": (Path(audio_path).name, handle)}
            data = {"language": language, "response_format": "text"}
            response = self.session.post(
                f"{self.base_url}/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=900,
            )
        if response.status_code >= 400:
            raise VibeCodeError(f"VibeCode ASR HTTP {response.status_code}: {response.text[:1000]}")
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("text") or payload.get("data") or "").strip()
        return response.text.strip()

    def attach_transcription(self, call_id: str, transcript_text: str) -> dict[str, Any]:
        variants = [str(call_id or "").strip()]
        if variants[0].startswith("VI_"):
            variants.append(variants[0][3:])
        errors: list[str] = []
        for cid in dict.fromkeys(v for v in variants if v):
            try:
                data = self.post(
                    "/v1/calls/transcription",
                    {"callId": cid, "messages": [{"side": "user", "text": transcript_text or ""}]},
                )
                return {"call_id_used": cid, "result": data.get("data") if isinstance(data, dict) else data, "source": "vibecode"}
            except Exception as e:
                errors.append(f"{cid}: {e}")
        raise VibeCodeError("Не удалось прикрепить расшифровку через VibeCode: " + " | ".join(errors))

    def timeline_log(self, deal_id: str, title: str, text: str) -> dict[str, Any]:
        data = self.post(
            "/v1/timeline-logs",
            {
                "entityTypeId": 2,
                "entityId": int(deal_id),
                "title": title,
                "text": text,
                "iconCode": "",
            },
        )
        return data.get("data") if isinstance(data, dict) else data


def env_vibecode_client() -> VibeCodeClient | None:
    load_dotenv()
    api_key = os.getenv("VIBECODE_API_KEY", "").strip()
    if not api_key:
        return None
    timeout_sec = float(os.getenv("VIBECODE_TIMEOUT_SEC", "30") or 30)
    max_attempts = int(os.getenv("VIBECODE_MAX_ATTEMPTS", "3") or 3)
    return VibeCodeClient(api_key=api_key, timeout_sec=timeout_sec, max_attempts=max_attempts)
