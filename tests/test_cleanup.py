import os
import time

from pipelines.cleanup import cleanup_old_chrome_tmp_profiles, cleanup_old_outputs


def _touch_old(path, days=40):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    old_time = time.time() - days * 24 * 3600
    os.utime(path, (old_time, old_time))


def _age_tree(path, days=40):
    old_time = time.time() - days * 24 * 3600
    for item in sorted(path.rglob("*"), reverse=True):
        os.utime(item, (old_time, old_time))
    os.utime(path, (old_time, old_time))


def test_cleanup_old_outputs_removes_old_reports_audio_and_transcripts(tmp_path):
    old_report = tmp_path / "bitnewton_sync_report_old.json"
    fresh_report = tmp_path / "bitnewton_sync_report_fresh.json"
    old_audio = tmp_path / "audio" / "old.mp3"
    old_transcript = tmp_path / "transcripts" / "old.txt"
    extra_audio = tmp_path / "external_audio" / "old.wav"

    _touch_old(old_report)
    fresh_report.write_text("fresh", encoding="utf-8")
    _touch_old(old_audio)
    _touch_old(old_transcript)
    _touch_old(extra_audio)

    counts = cleanup_old_outputs(tmp_path, keep_days=30, extra_audio_dirs=[tmp_path / "external_audio"])

    assert counts == {"reports": 1, "audio": 2, "transcripts": 1, "total": 4}
    assert not old_report.exists()
    assert fresh_report.exists()
    assert not old_audio.exists()
    assert not old_transcript.exists()
    assert not extra_audio.exists()


def test_cleanup_old_chrome_tmp_profiles_removes_old_profile_tree(tmp_path):
    old_profile_file = tmp_path / "chrome_profile_tmp_old" / "Default" / "Cookies"
    fresh_profile_file = tmp_path / "chrome_profile_tmp_fresh" / "Default" / "Cookies"
    _touch_old(old_profile_file)
    _age_tree(tmp_path / "chrome_profile_tmp_old")
    fresh_profile_file.parent.mkdir(parents=True, exist_ok=True)
    fresh_profile_file.write_text("fresh", encoding="utf-8")

    removed = cleanup_old_chrome_tmp_profiles(tmp_path, keep_days=30)

    assert removed == 1
    assert not (tmp_path / "chrome_profile_tmp_old").exists()
    assert (tmp_path / "chrome_profile_tmp_fresh").exists()
