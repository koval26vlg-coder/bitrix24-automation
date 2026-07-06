from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIRST_RESPONSE_SLA_HOURS = 0.5
MAX_GAP_BETWEEN_CALLS_HOURS = 72.0

DEFAULT_KPI_CONFIG: dict[str, Any] = {
    "profile": {"name": "default", "version": "1"},
    "sla": {"first_response_hours": 0.5, "max_gap_between_calls_hours": 72.0},
    "weights": {
        "overall": {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50},
        "discipline_split": {"first_response": 1.0, "cadence": 0.0},
        "crm_alignment_split": {"deal_quality": 0.6, "alignment": 0.4},
    },
    "deal_quality_weights": {
        "comment_matches_call": 40,
        "has_next_step_activity": 30,
        "next_step_has_comment": 20,
        "next_step_not_overdue": 10,
    },
    "call_quality_weights": {
        "greeting": 25,
        "needs_discovery": 30,
        "objection_work": 20,
        "next_step": 25,
    },
    "alignment_weights": {
        "title_hit": 10,
        "title_hit_cap": 40,
        "amount_mentioned": 0,
        "next_step_synced": 100,
    },
    "patterns": {
        "greeting": [r"\b(добрый|здравств\w*|привет)\b"],
        "needs_discovery": [
            r"\b(потребност\w*|задач\w*|нужно|необходим\w*|интересу\w*|уточн\w*|подскаж\w*|что нужно|что необходимо)\b"  # noqa: E501
        ],
        "objection_work": [
            r"\b(дорог\w*|возраж\w*|сомнен\w*|не подходит|не смож\w*|не получится|нет возможности|подума\w*)\b"  # noqa: E501
        ],
        "next_step": [
            r"\b(договор\w*|следующ\w*|перезвон\w*|отправ\w*|вышл\w*|встреч\w*|созвон\w*|уточн\w*|согласу\w*)\b"
        ],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def validate_kpi_config(kpi: dict[str, Any]) -> None:
    if not isinstance(kpi, dict):
        raise RuntimeError("KPI config: должен быть объектом")
    prof = kpi.get("profile")
    if not isinstance(prof, dict) or not str(prof.get("name") or "").strip():
        raise RuntimeError("KPI config: profile.name обязателен (строка)")
    sla = kpi.get("sla")
    if not isinstance(sla, dict):
        raise RuntimeError("KPI config: sla должен быть объектом")
    fr = float(sla.get("first_response_hours", FIRST_RESPONSE_SLA_HOURS))
    mg = float(sla.get("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS))
    if fr <= 0 or mg <= 0:
        raise RuntimeError("KPI config: sla значения должны быть > 0")
    weights = kpi.get("weights")
    if not isinstance(weights, dict):
        raise RuntimeError("KPI config: weights должен быть объектом")
    overall = weights.get("overall")
    if not isinstance(overall, dict):
        raise RuntimeError("KPI config: weights.overall должен быть объектом")
    total = (
        float(overall.get("call_quality", 0))
        + float(overall.get("discipline", 0))
        + float(overall.get("crm_alignment", 0))
    )
    if not (0.95 <= total <= 1.05):
        raise RuntimeError(
            f"KPI config: weights.overall должны суммироваться примерно в 1.0 (сейчас {total})"
        )
    patterns = kpi.get("patterns")
    if patterns is not None:
        if not isinstance(patterns, dict):
            raise RuntimeError("KPI config: patterns должен быть объектом")
        for key, arr in patterns.items():
            if not isinstance(arr, list):
                raise RuntimeError(f"KPI config: patterns.{key} должен быть списком regex-строк")
            for pattern in arr:
                if not isinstance(pattern, str):
                    raise RuntimeError(f"KPI config: patterns.{key} содержит не строку")


def enforce_reaction_kpi(kpi: dict[str, Any]) -> dict[str, Any]:
    """
    Единая итоговая оценка: разговор + ведение CRM. Скорость реакции не влияет на итог.
    """
    sla = kpi.setdefault("sla", {})
    if isinstance(sla, dict):
        sla["first_response_hours"] = FIRST_RESPONSE_SLA_HOURS
        sla.setdefault("max_gap_between_calls_hours", MAX_GAP_BETWEEN_CALLS_HOURS)
    weights = kpi.setdefault("weights", {})
    if isinstance(weights, dict):
        weights["overall"] = {"call_quality": 0.50, "discipline": 0.0, "crm_alignment": 0.50}
        weights["discipline_split"] = {"first_response": 1.0, "cadence": 0.0}
    return kpi


def load_kpi_config(path: str | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_KPI_CONFIG)
    if not path:
        cfg = enforce_reaction_kpi(cfg)
        validate_kpi_config(cfg)
        return cfg
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("--kpi-config должен содержать JSON-объект")
    merged = _deep_merge(cfg, raw)
    if isinstance(merged.get("profile"), dict):
        merged["profile"].setdefault("name", Path(path).name)
        merged["profile"].setdefault("version", "1")
    else:
        merged["profile"] = {"name": Path(path).name, "version": "1"}
    merged = enforce_reaction_kpi(merged)
    validate_kpi_config(merged)
    return merged
