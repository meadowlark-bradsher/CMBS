"""Reference kit loaders: YAML quirks are absorbed at load time."""

import pytest

from cmbs.adapters.itbench import load_builtin_kit as load_itbench_kit
from cmbs.adapters.twenty_questions import load_builtin_kit as load_20q_kit
from cmbs.adapters.twenty_questions.kit import _kit_from_text


@pytest.mark.parametrize("name", ["20q_4", "20q_8"])
def test_builtin_20q_kits_have_string_outcome_keys(name):
    kit = load_20q_kit(name)
    assert kit.hypotheses
    for spec in kit.actions.values():
        assert set(spec.keep) == {"yes", "no"}
        assert set(spec.keep["yes"]) | set(spec.keep["no"]) == set(kit.hypotheses)


def test_20q_quoted_and_mixed_case_outcomes_are_accepted():
    kit = _kit_from_text(
        """
hypotheses: [a, b]
actions:
  - id: q
    question: "Is it a?"
    keep:
      "Yes": [a]
      'NO': [b]
"""
    )
    assert kit.actions["q"].keep == {"yes": ["a"], "no": ["b"]}


def test_20q_invalid_outcome_key_raises():
    with pytest.raises(ValueError, match="must be yes/no"):
        _kit_from_text(
            """
hypotheses: [a]
actions:
  - id: q
    question: "?"
    keep:
      maybe: [a]
      no: []
"""
        )


def test_20q_missing_outcome_raises():
    with pytest.raises(ValueError, match="missing outcome"):
        _kit_from_text(
            """
hypotheses: [a]
actions:
  - id: q
    question: "?"
    keep:
      yes: [a]
"""
        )


@pytest.mark.parametrize("name", ["itb_min_4", "itb_sre_6"])
def test_builtin_itbench_kits_load(name):
    kit = load_itbench_kit(name)
    assert kit.hypotheses
    assert list(kit.actions) == kit.actions_order
    for action_id, spec in kit.actions.items():
        assert set(kit.oracle_table[action_id]) == set(spec.outcomes)
