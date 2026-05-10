import json

import pytest

from pipelines.kpi import load_kpi_config, validate_kpi_config


def test_default_kpi_uses_call_and_crm_formula():
    kpi = load_kpi_config(None)

    assert kpi["sla"]["first_response_hours"] == 0.5
    assert kpi["weights"]["overall"] == {
        "call_quality": 0.50,
        "discipline": 0.0,
        "crm_alignment": 0.50,
    }


def test_custom_kpi_is_merged_but_overall_formula_is_enforced(tmp_path):
    config = tmp_path / "kpi.json"
    config.write_text(
        json.dumps(
            {
                "profile": {"name": "custom"},
                "weights": {"overall": {"call_quality": 0.2, "discipline": 0.7, "crm_alignment": 0.1}},
                "patterns": {"next_step": ["следующий шаг"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    kpi = load_kpi_config(str(config))

    assert kpi["profile"]["name"] == "custom"
    assert kpi["weights"]["overall"]["discipline"] == 0.0
    assert kpi["weights"]["overall"]["call_quality"] == 0.50
    assert kpi["patterns"]["next_step"] == ["следующий шаг"]


def test_invalid_kpi_patterns_are_rejected():
    with pytest.raises(RuntimeError, match="patterns.next_step"):
        validate_kpi_config(
            {
                "profile": {"name": "bad"},
                "sla": {"first_response_hours": 0.5, "max_gap_between_calls_hours": 72},
                "weights": {"overall": {"call_quality": 0.5, "discipline": 0.0, "crm_alignment": 0.5}},
                "patterns": {"next_step": "not a list"},
            }
        )
