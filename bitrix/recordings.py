from __future__ import annotations
import re
import html
from dataclasses import dataclass
from typing import Any, Dict, Optional

from bitrix.api import Bitrix24API


def guess_recording_url(call_obj: Dict[str, Any]) -> Optional[str]:
    """
    Эвристика: ищем URL записи внутри объекта voximplant.statistic.get.
    """
    if not call_obj or not isinstance(call_obj, dict):
        return None
    for k in [
        "CALL_RECORD_URL",
        "RECORD_URL",
        "RECORDING_URL",
        "CALL_WEBDAV_LINK",
        "WEB_DAV_LINK",
        "FILE_URL",
        "DOWNLOAD_URL",
        "DOWNLOAD_LINK",
    ]:
        v = call_obj.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return html.unescape(v).strip()
    for v in call_obj.values():
        if not isinstance(v, str):
            continue
        vv = v.lower()
        if not vv.startswith("http"):
            continue
        if any(x in vv for x in [".mp3", ".wav", ".ogg", "download", "record", "voximplant", "webdav"]):
            return html.unescape(v).strip()
    return None


def safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


@dataclass
class RecordingResolution:
    call_id: str
    activity_id: Optional[int]
    disk_file_id: Optional[int]
    candidates: list[str]
    diagnostics: Dict[str, Any]


async def activity_get(api: Bitrix24API, activity_id: int) -> Dict[str, Any]:
    res = await api.call("crm.activity.get", {"id": int(activity_id)})
    return res.get("result", {}) or {}


async def disk_file_get(api: Bitrix24API, disk_file_id: int) -> Dict[str, Any]:
    res = await api.call("disk.file.get", {"id": int(disk_file_id)})
    return res.get("result", {}) or {}


async def disk_file_get_external_link(api: Bitrix24API, disk_file_id: int) -> Optional[str]:
    try:
        res = await api.call("disk.file.getExternalLink", {"id": int(disk_file_id)})
        link = res.get("result")
        return link if isinstance(link, str) and link.startswith("http") else None
    except Exception:
        return None


async def statistic_get_by_call_id(api: Bitrix24API, call_id: str) -> Optional[Dict[str, Any]]:
    if not call_id:
        return None
    # На части порталов crm.activity.ORIGIN_ID имеет префикс "VI_", а в статистике CALL_ID без него.
    call_ids = [call_id]
    if call_id.startswith("VI_"):
        call_ids.append(call_id[3:])
    for cid in call_ids:
        try:
            res = await api.call("voximplant.statistic.get", {"FILTER": {"CALL_ID": cid}})
            arr = res.get("result") or []
            if arr:
                for c in arr:
                    if str(c.get("CALL_ID") or "") == cid:
                        return c
                return arr[0]
        except Exception:
            continue
    return None


async def resolve_call_recording(api: Bitrix24API, call_id: str, activity_id: Optional[int]) -> RecordingResolution:
    """
    Единый resolver записи звонка:
    crm.activity.get -> voximplant.statistic.get -> disk.file.get / externalLink -> URL candidates.
    """
    diag: Dict[str, Any] = {"call_id": call_id, "activity_id": activity_id}
    candidates: list[str] = []
    activity_candidates: list[str] = []
    statistic_candidates: list[str] = []
    disk_download_candidates: list[str] = []
    disk_page_candidates: list[str] = []
    disk_id: Optional[int] = None

    # 1) crm.activity.get -> FILES[].id / FILES[].url
    if activity_id:
        try:
            act = await activity_get(api, int(activity_id))
            files = act.get("FILES") or []
            if files and isinstance(files[0], dict):
                disk_id = safe_int(files[0].get("id")) or disk_id
                u = files[0].get("url")
                if isinstance(u, str) and u.startswith("http"):
                    activity_candidates.append(html.unescape(u).strip())
        except Exception as e:
            diag["activity_get_error"] = str(e)

    # 2) voximplant.statistic.get -> RECORD_FILE_ID + possibly direct URL
    stat = await statistic_get_by_call_id(api, call_id)
    if stat:
        diag["statistic"] = {k: stat.get(k) for k in ["CALL_ID", "CRM_ACTIVITY_ID", "RECORD_FILE_ID", "CALL_START_DATE"]}
        disk_id = disk_id or safe_int(stat.get("RECORD_FILE_ID"))
        url = guess_recording_url(stat)
        if url:
            statistic_candidates.append(url)

    # 3) disk.file.get / external link -> download/detail/external
    if disk_id:
        diag["disk_file_id"] = disk_id
        disk_meta: Dict[str, Any] = {}
        disk_err = None
        try:
            disk_meta = await disk_file_get(api, disk_id)
        except Exception as e:
            disk_err = str(e)
        
        if disk_err:
            diag["disk_file_get_error"] = disk_err
        
        if isinstance(disk_meta, dict):
            u = disk_meta.get("DOWNLOAD_URL")
            if isinstance(u, str) and u.startswith("http"):
                disk_download_candidates.append(html.unescape(u).strip())
                diag["disk_download_url_ok"] = True
            u = disk_meta.get("DETAIL_URL")
            if isinstance(u, str) and u.startswith("http"):
                disk_page_candidates.append(html.unescape(u).strip())
            diag["disk_file_name"] = disk_meta.get("NAME")
            diag["disk_file_size"] = disk_meta.get("SIZE")

        ext = await disk_file_get_external_link(api, disk_id)
        if ext:
            disk_download_candidates.append(html.unescape(ext).strip())
            diag["external_link_ok"] = True
        else:
            diag["external_link_ok"] = False

    # Быстрый путь: прямые disk DOWNLOAD_URL идут первыми. UI/страницы Bitrix оставляем последним fallback.
    candidates.extend(disk_download_candidates)
    candidates.extend(statistic_candidates)
    candidates.extend(activity_candidates)
    candidates.extend(disk_page_candidates)

    # de-dupe keep order
    seen = set()
    out = []
    for u in candidates:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        u = html.unescape(u).strip()
        uu = re.sub(r"[?#].*$", "", u)
        if uu in seen:
            continue
        seen.add(uu)
        out.append(u)

    return RecordingResolution(call_id=call_id, activity_id=activity_id, disk_file_id=disk_id, candidates=out, diagnostics=diag)
