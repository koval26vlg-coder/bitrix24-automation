from __future__ import annotations

from typing import Any

from bitrix.api import Bitrix24API


async def attach_transcription_to_bitrix(
    api: Bitrix24API, call_id: str, transcript_text: str, duration: int
) -> dict[str, Any]:
    text = (transcript_text or "").strip()
    if not text:
        raise RuntimeError("Пустая расшифровка (transcript_text)")
    duration = int(duration or 60)
    duration = max(1, duration)
    msg = {"SIDE": "User", "MESSAGE": text, "START_TIME": 0, "STOP_TIME": duration}

    variants = [str(call_id or "").strip()]
    if variants[0].startswith("VI_"):
        variants.append(variants[0][3:])

    seen = set()
    errors: list[str] = []
    for cid in variants:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            res = await api.call(
                "telephony.call.attachTranscription", {"CALL_ID": cid, "MESSAGES": [msg]}
            )
            result = res.get("result", {}) or {}
            return {"call_id_used": cid, "result": result}
        except Exception as e:
            errors.append(f"{cid}: {e}")

    raise RuntimeError("Не удалось прикрепить расшифровку в Bitrix: " + " | ".join(errors))
