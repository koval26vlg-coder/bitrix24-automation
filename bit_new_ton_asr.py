from __future__ import annotations
import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv


load_dotenv(override=True)


class BitNewtonError(RuntimeError):
    pass


class BitNewtonAuthError(BitNewtonError):
    pass


@dataclass
class BitNewtonTask:
    task_id: str
    message: str = ""


class BitNewtonASR:
    """
    Асинхронный клиент Bit.Newton ASR.
    """

    def __init__(self, base_url: str, token: str, timeout_sec: int = 120):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self.timeout_sec = float(timeout_sec)
        self.client = httpx.AsyncClient(timeout=self.timeout_sec)

    async def aclose(self):
        await self.client.aclose()

    @staticmethod
    def _raise_for_auth_if_needed(status_code: int, body: str, where: str) -> None:
        if status_code in (401, 403):
            raise BitNewtonAuthError(
                f"{where}: токен Bit.Newton истёк/неверный (HTTP {status_code}). "
                f"Обнови BITNEWTON_TOKEN в .env и повтори. Ответ: {body[:300]}"
            )

    async def start_transcribing(
        self,
        file_path: str,
        diarize: bool = False,
        remove_timestamps: bool = True,
    ) -> BitNewtonTask:
        if not self.base_url:
            raise BitNewtonError("BitNewton base_url пустой")
        if not self.token:
            raise BitNewtonError("BitNewton token пустой")

        url = f"{self.base_url}/start_transcribing"
        headers = {"token": self.token}
        params = {"diarize": str(diarize).lower(), "remove_timestamps": str(remove_timestamps).lower()}

        p = Path(file_path)
        if not p.exists():
            raise BitNewtonError(f"Файл не найден: {file_path}")

        files = {"file": (p.name, p.open("rb"))}
        try:
            r = await self.client.post(url, headers=headers, params=params, files=files)
            if r.status_code >= 400:
                self._raise_for_auth_if_needed(r.status_code, r.text, "ASR start_transcribing")
                raise BitNewtonError(f"ASR start_transcribing HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            return BitNewtonTask(task_id=str(data.get("task_id")), message=str(data.get("message") or ""))
        finally:
            files["file"][1].close()

    async def get_status(self, task_id: str) -> dict:
        url = f"{self.base_url}/get_status"
        headers = {"token": self.token}
        r = await self.client.get(url, headers=headers, params={"task_id": task_id})
        if r.status_code >= 400:
            self._raise_for_auth_if_needed(r.status_code, r.text, "ASR get_status")
            raise BitNewtonError(f"ASR get_status HTTP {r.status_code}: {r.text[:500]}")
        return r.json()

    async def validate_token(self) -> bool:
        url = f"{self.base_url}/get_status"
        headers = {"token": self.token}
        try:
            r = await self.client.get(
                url,
                headers=headers,
                params={"task_id": "__token_check__"},
                timeout=min(self.timeout_sec, 30.0),
            )
            self._raise_for_auth_if_needed(r.status_code, r.text, "ASR token_check")
            return True
        except Exception as e:
            if isinstance(e, BitNewtonAuthError):
                raise
            return False

    async def get_file(self, task_id: str, file_type: Optional[str] = None) -> bytes:
        url = f"{self.base_url}/get_file"
        headers = {"token": self.token}
        params = {"task_id": task_id}
        if file_type:
            params["type"] = file_type
        r = await self.client.get(url, headers=headers, params=params)
        if r.status_code >= 400:
            self._raise_for_auth_if_needed(r.status_code, r.text, "ASR get_file")
            raise BitNewtonError(f"ASR get_file HTTP {r.status_code}: {r.text[:500]}")
        return r.content

    async def wait_and_get_text(
        self,
        task_id: str,
        poll_interval_sec: float = 2.0,
        timeout_sec: int = 600,
    ) -> str:
        start = time.time()
        last_status = None
        while True:
            st = await self.get_status(task_id)
            last_status = st
            status = str(st.get("status") or "").lower()
            progress = st.get("progress")

            if status in {"done", "success", "completed", "finished"} or (isinstance(progress, int) and progress >= 100):
                break
            if status in {"error", "failed"}:
                raise BitNewtonError(f"ASR task failed: {st}")
            if time.time() - start > timeout_sec:
                raise BitNewtonError(f"ASR timeout waiting task {task_id}. last_status={last_status}")
            await asyncio.sleep(poll_interval_sec)

        content = await self.get_file(task_id, file_type="txt")
        try:
            return content.decode("utf-8", errors="replace").strip()
        except Exception:
            return content.decode(errors="replace").strip()


def env_bitnewton_asr() -> Optional[BitNewtonASR]:
    base_url = os.getenv("BITNEWTON_ASR_URL", "https://bit-asr.1bitai.ru").strip()
    token = os.getenv("BITNEWTON_TOKEN", "").strip()
    if not token:
        return None
    timeout_sec = int(os.getenv("BITNEWTON_HTTP_TIMEOUT_SEC", "300") or 300)
    return BitNewtonASR(base_url=base_url, token=token, timeout_sec=timeout_sec)
