from __future__ import annotations

import re
from re import Pattern
from typing import Any

from pipelines.scoring.utils import _context

OBJECTION_RULES: list[tuple[str, str, str]] = [
    (
        "Цена / бюджет",
        r"\b(дорог\w*|цена|стоимост\w*|сколько\s+стоит|нет\s+бюджета|дороже|дешевле)\b",
        "Признать вопрос цены, разложить стоимость на состав услуги, показать выгоду/риск бездействия и предложить следующий шаг.",  # noqa: E501
    ),
    (
        "Нет потребности / не актуально",
        r"\b(не\s+надо|не\s+нужно|не\s+актуаль\w*|не\s+интерес\w*|не\s+подходит|не\s+требуется)\b",
        "Уточнить контекст клиента, почему сейчас не актуально, и предложить минимальный следующий шаг или полезную альтернативу.",  # noqa: E501
    ),
    (
        "Ограничение / отказ",
        r"\b(не\s+смож\w*|не\s+можем|не\s+получится|нет\s+возможности|невозможно|такого\s+нет)\b",
        "Не оставлять клиента с отказом: объяснить ограничение, предложить близкий рабочий вариант и согласовать дальнейшее действие.",  # noqa: E501
    ),
    (
        "Пауза на решение",
        r"\b(подума\w*|посмотр\w*|обсуд\w*|решим|перезвоните\s+позже|не\s+сейчас)\b",
        "Согласовать конкретный срок возврата, критерии решения и что клиенту нужно прислать до следующего контакта.",  # noqa: E501
    ),
    (
        "Непонимание / сомнение",
        r"\b(не\s+понимаю|непонятн\w*|сомнева\w*|что\s+это|как\s+это\s+работает|зачем)\b",
        "Переформулировать простыми словами, задать уточняющий вопрос и проверить, стало ли клиенту понятно.",  # noqa: E501
    ),
]

HANDLING_RE: Pattern[str] = re.compile(
    r"\b(понима\w*|давайте|уточн\w*|предлож\w*|вариант\w*|альтернатив\w*|в\s+таком\s+случае|тогда|можем|"
    r"входит|стоимост\w*|выгод\w*|риск\w*|сравн\w*|перезвон\w*|отправ\w*|согласу\w*)\b",
    re.IGNORECASE,
)

CALM_RESPONSE_RE: Pattern[str] = re.compile(
    r"\b(понима\w*|соглас\w*|да,|конечно|верно|логично|слышу|это\s+нормально)\b", re.IGNORECASE
)
REASON_QUESTION_RE: Pattern[str] = re.compile(
    r"\b(почему|что\s+именно|с\s+чем\s+связан\w*|какая\s+причин\w*|что\s+смущает|из-за\s+чего|расскажите)\b",
    re.IGNORECASE,
)


def _objection_matches(raw: str) -> list[dict[str, Any]]:
    lower = raw.lower()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for label, pattern, suggestion in OBJECTION_RULES:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            key = (label, match.start())
            if key in seen:
                continue
            seen.add(key)
            after = lower[match.end() : match.end() + 600]

            out.append(
                {
                    "label": label,
                    "start": match.start(),
                    "end": match.end(),
                    "fragment": _context(raw, match.start(), match.end(), radius=140),
                    "handled": bool(HANDLING_RE.search(after)),
                    "calm": bool(CALM_RESPONSE_RE.search(after)),
                    "reason": bool(REASON_QUESTION_RE.search(after)),
                    "suggestion": suggestion,
                }
            )
    return sorted(out, key=lambda x: int(x.get("start") or 0))
