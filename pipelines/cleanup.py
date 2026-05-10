from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def cleanup_old_chrome_tmp_profiles(base_dir: Path, keep_days: int = 7) -> int:
    try:
        if keep_days <= 0:
            return 0
        now = time.time()
        removed = 0
        for path in base_dir.glob("chrome_profile_tmp_*"):
            try:
                age_days = (now - path.stat().st_mtime) / (3600 * 24)
                if age_days < keep_days:
                    continue
                for sub in sorted(path.rglob("*"), reverse=True):
                    try:
                        if sub.is_file() or sub.is_symlink():
                            sub.unlink(missing_ok=True)  # type: ignore[call-arg]
                        else:
                            sub.rmdir()
                    except Exception:
                        pass
                try:
                    path.rmdir()
                except Exception:
                    pass
                removed += 1
            except Exception:
                continue
        return removed
    except Exception:
        return 0


def cleanup_old_outputs(base_dir: Path, keep_days: int = 30, extra_audio_dirs: Optional[List[Path]] = None) -> Dict[str, int]:
    counts = {"reports": 0, "audio": 0, "transcripts": 0, "total": 0}
    try:
        if keep_days <= 0:
            return counts
        base_dir = Path(base_dir)
        cutoff = time.time() - (float(keep_days) * 24 * 3600)

        def remove_file(path: Path, bucket: str) -> None:
            try:
                if not path.exists() or path.is_dir():
                    return
                if path.stat().st_mtime >= cutoff:
                    return
                path.unlink(missing_ok=True)  # type: ignore[call-arg]
                counts[bucket] = counts.get(bucket, 0) + 1
                counts["total"] += 1
            except Exception:
                return

        for pattern in ("bitnewton_sync_report_*.json", "bitnewton_sync_report_*.xlsx"):
            for path in base_dir.glob(pattern):
                remove_file(path, "reports")

        cleanup_dirs: List[Tuple[Path, str]] = [
            (base_dir / "audio", "audio"),
            (base_dir / "audio_ui", "audio"),
            (base_dir / "transcripts", "transcripts"),
        ]
        for extra in extra_audio_dirs or []:
            extra_path = Path(extra)
            if extra_path not in [path for path, _ in cleanup_dirs]:
                cleanup_dirs.append((extra_path, "audio"))

        for folder, bucket in cleanup_dirs:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                remove_file(path, bucket)
            for path in sorted(folder.rglob("*"), reverse=True):
                try:
                    if path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                except Exception:
                    continue
        return counts
    except Exception:
        return counts
