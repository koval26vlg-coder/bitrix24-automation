from __future__ import annotations

import html
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bitrix.api import Bitrix24API
from bitrix.recordings import resolve_call_recording
from download_resolver import download_best_effort
from pipelines.stages import safe_int


AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".webm", ".aac", ".opus", ".flac", ".wma"}


def _looks_like_html_prefix(data: bytes) -> bool:
    if not data:
        return True
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<head") or head.startswith(b"<body")


def validate_audio_file(path: Path) -> Optional[str]:
    """
    Быстрая валидация, чтобы не отправлять в ASR HTML/пустышки.
    """
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return "файл не создан или пустой"
        if path.stat().st_size < 2048:
            return f"файл слишком маленький ({path.stat().st_size} bytes)"
        head = path.read_bytes()[:512]
        if _looks_like_html_prefix(head):
            return "вместо аудио скачался HTML (логин/нет прав)"
    except Exception:
        return None
    return None


def parse_audio_source_dirs(values: Any) -> List[Path]:
    out: List[Path] = []
    raw_values = values if isinstance(values, list) else ([values] if values else [])
    for raw in raw_values:
        for part in str(raw or "").split(";"):
            text = part.strip().strip('"')
            if text:
                out.append(Path(text))
    return out


def build_audio_source_index(source_dirs: List[Path]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for source_dir in source_dirs:
        try:
            base = Path(source_dir)
            if not base.exists() or not base.is_dir():
                print(f"[WARN] Локальная папка аудио не найдена: {base}", flush=True)
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                key = str(path.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        except Exception as e:
            print(f"[WARN] Не удалось просканировать папку аудио {source_dir}: {e}", flush=True)
    return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def find_local_audio_source(
    audio_index: List[Path],
    deal_id: Any,
    activity_id: Any,
    disk_file_id: Any,
    call_id: Any,
    disk_file_name: Any = None,
) -> Optional[Path]:
    if not audio_index:
        return None

    disk_name = str(disk_file_name or "").strip().lower()
    strong_tokens = [
        str(disk_file_id or "").strip(),
        str(activity_id or "").strip(),
        str(call_id or "").strip(),
        str(call_id or "").replace("VI_", "").strip(),
    ]
    weak_tokens = [str(deal_id or "").strip()]
    strong_tokens = [t.lower() for t in strong_tokens if len(t.strip()) >= 3]
    weak_tokens = [t.lower() for t in weak_tokens if len(t.strip()) >= 4]

    ranked: List[Tuple[int, float, Path]] = []
    for path in audio_index:
        try:
            name = path.name.lower()
            stem = path.stem.lower()
            score = 0
            if disk_name and name == disk_name:
                score += 120
            elif disk_name and (disk_name in name or name in disk_name):
                score += 90
            if any(token and token in name for token in strong_tokens):
                score += 80
            if any(token and token in stem for token in strong_tokens):
                score += 40
            if any(token and token in name for token in weak_tokens):
                score += 20
            if score > 0:
                ranked.append((score, path.stat().st_mtime if path.exists() else 0, path))
        except Exception:
            continue
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def download_audio_for_call(
    *,
    api: Bitrix24API,
    args: Any,
    row: Dict[str, Any],
    deal_id: Any,
    activity: Dict[str, Any],
    call_id: str,
    audio_source_index: List[Path],
    audio_dir: Path,
    ui_audio_dir: Path,
    ui_browser_session: Any = None,
) -> Tuple[Path, Any]:
    rr = resolve_call_recording(api, call_id=call_id, activity_id=safe_int(activity.get("ID")))
    row["disk_file_id"] = rr.disk_file_id
    row["recording_diagnostics"] = rr.diagnostics
    candidates = rr.candidates
    row["download_url"] = candidates[0] if candidates else None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_source = find_local_audio_source(
        audio_source_index,
        deal_id=deal_id,
        activity_id=activity.get("ID"),
        disk_file_id=row.get("disk_file_id"),
        call_id=call_id,
        disk_file_name=(rr.diagnostics or {}).get("disk_file_name"),
    )
    out_suffix = local_source.suffix if local_source else ".mp3"
    out_path = audio_dir / f"deal{deal_id}_act{activity.get('ID')}_{row.get('disk_file_id')}_{ts}{out_suffix}"
    if local_source:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_source, out_path)
        row["local_audio_source_used"] = True
        row["local_audio_source_path"] = str(local_source)
        print(f"[AUDIO] Использую локальный файл: activity_id={row.get('activity_id')} file={local_source}", flush=True)
    else:
        row["local_audio_source_used"] = False
        if not candidates:
            raise RuntimeError("Не нашёл URL кандидаты для скачивания (resolver не смог), и локальный аудиофайл тоже не найден.")
        rest_timeout_sec = max(5, int(getattr(args, "rest_timeout_sec", 20) or 20))
        dl = download_best_effort(candidates=candidates, out_path=out_path, timeout_sec=rest_timeout_sec, retries=0)
        if not dl.ok or not dl.path:
            row["download_attempts"] = [a.__dict__ for a in dl.attempts]
            if args.ui_download:
                try:
                    from ui_audio_downloader import UiBrowserSession

                    ui_res = None
                    ui_errors: List[str] = []
                    mode = str(getattr(args, "ui_download_mode", "auto") or "auto")
                    browser = str(getattr(args, "ui_browser", "chrome"))
                    ui_timeout_sec = max(5, int(getattr(args, "ui_timeout_sec", 20) or 20))
                    browser_profile_directory = str(getattr(args, "browser_profile_directory", "Default") or "Default")
                    if ui_browser_session is None:
                        ui_browser_session = UiBrowserSession(
                            downloads_dir=ui_audio_dir,
                            chrome_profile_dir=args.chrome_profile_dir,
                            browser=browser,
                            browser_profile_directory=browser_profile_directory,
                        )

                    if mode in {"direct", "auto"}:
                        for candidate in [html.unescape(c).strip() for c in candidates if isinstance(c, str) and c.startswith("http")]:
                            print(f"[UI] Пробую ссылку активности через {browser}, таймаут {ui_timeout_sec} сек.: {candidate}", flush=True)
                            ui_res = ui_browser_session.download_url(
                                candidate,
                                timeout_sec=ui_timeout_sec,
                                referer_url=row["deal_url"],
                            )
                            if ui_res.ok and ui_res.path:
                                break
                            ui_errors.append(f"url={candidate}: {ui_res.error if ui_res else 'no result'}")

                    if (ui_res is None or not ui_res.ok) and mode in {"timeline", "auto"}:
                        print(f"[UI] Пробую таймлайн сделки через {browser}, таймаут {ui_timeout_sec} сек.: activity_id={row.get('activity_id')}", flush=True)
                        ui_res = ui_browser_session.download_call_from_deal_timeline(
                            row["deal_url"],
                            int(row.get("activity_id") or 0),
                            timeout_sec=ui_timeout_sec,
                        )
                        if not ui_res.ok:
                            ui_errors.append(f"timeline activity_id={row.get('activity_id')}: {ui_res.error}")

                    row["ui_download_errors"] = ui_errors
                    if ui_res is None or not ui_res.ok or not ui_res.path:
                        raise RuntimeError("; ".join(ui_errors) or (ui_res.error if ui_res else "UI download failed"))
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(Path(ui_res.path).read_bytes())
                    row["ui_download_used"] = True
                    row["ui_download_path"] = str(ui_res.path)
                except Exception as e:
                    raise RuntimeError(f"Не удалось скачать аудио (REST+UI): {dl.error}; UI: {e}")
            else:
                raise RuntimeError(f"Не удалось скачать аудио: {dl.error}")
    row["audio_path"] = str(out_path)
    row["audio_size_bytes"] = int(out_path.stat().st_size) if out_path.exists() else None
    bad = validate_audio_file(out_path)
    if bad:
        raise RuntimeError(f"Скачанный файл не похож на аудио: {bad}")
    return out_path, ui_browser_session
