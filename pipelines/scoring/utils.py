from __future__ import annotations

import re


def _manager_lines(text: str) -> str:
    """
    Извлекает только реплики менеджера, если транскрипт имеет формат роли.
    Это значительно повышает точность оценки KPI именно сотрудника.
    """
    lines = text.split("\n")
    manager_text = []
    for line in lines:
        if line.lower().startswith(("менеджер:", "m:", "manager:")):
            manager_text.append(line.split(":", 1)[1].strip())

    if not manager_text:
        return text  # Fallback на весь текст, если ролей нет
    return " ".join(manager_text)


def _clean_text_for_report(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _context(text: str, start: int, end: int, radius: int = 180) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = _clean_text_for_report(text[left:right])
    return snippet[:700]


def _first_match(text: str, patterns: list[str]) -> re.Match[str] | None:
    for pattern in patterns:
        try:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match
        except re.error:
            continue
    return None
