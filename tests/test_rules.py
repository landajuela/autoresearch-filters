import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from autoresearch_filters.config import FeatureSpace
from autoresearch_filters.rules import Rule, pretty, score, validate_rule


@pytest.fixture
def schema():
    return FeatureSpace.model_validate(
        {
            "name": "fixture",
            "id_column": "id",
            "label_column": "label",
            "success_value": 1,
            "signals": {
                "x": {"direction": "higher_is_better", "range": [0, 10]},
                "error": {"direction": "lower_is_better", "range": [0, 10]},
            },
        }
    )


def test_gate_hand_arithmetic_and_round_trip(schema):
    rule = Rule.model_validate(
        {
            "name": "nested",
            "hypothesis": "fixture",
            "expression": {
                "kind": "gated",
                "base": {"kind": "additive", "terms": [{"signal": "x"}]},
                "gates": [
                    {
                        "name": "outer",
                        "when": {"signal": "x", "op": ">", "value": 5},
                        "adjustments": [{"signal": "error", "weight": 2, "center": 0.5}],
                        "children": [
                            {
                                "name": "inner",
                                "when": {"signal": "error", "op": "<", "value": 3},
                                "adjustments": [{"signal": "x", "weight": -1, "center": 0.5}],
                            }
                        ],
                    }
                ],
            },
        }
    )
    frame = pd.DataFrame({"x": [2, 8, 8, 5], "error": [2, 2, 8, 1]})
    # outer: +2*(0.8-.5)=.6; inner: -(0.8-.5)=-.3; third: +2*(.2-.5)=-.6
    np.testing.assert_allclose(score(rule, frame, schema), [0.2, 1.1, 0.2, 0.5])
    restored = Rule.model_validate_json(rule.model_dump_json())
    assert restored == rule
    assert pretty(restored, schema) == pretty(rule, schema)
    assert "lower_is_better" in pretty(rule, schema)


@pytest.mark.parametrize(
    "expression,expected",
    [
        (
            {"kind": "product", "factors": [{"signal": "x", "exponent": 2}, {"signal": "error"}]},
            [0.032, 0.128],
        ),
        (
            {
                "kind": "hard",
                "condition": {
                    "kind": "any",
                    "conditions": [
                        {"kind": "threshold", "signal": "x", "op": ">", "value": 5},
                        {"kind": "threshold", "signal": "error", "op": "<", "value": 3},
                    ],
                },
            },
            [1, 1],
        ),
        (
            {
                "kind": "additive",
                "terms": [{"signal": "x", "weight": 1}, {"signal": "error", "weight": 3}],
            },
            [0.65, 0.35],
        ),
    ],
)
def test_primitives(schema, expression, expected):
    rule = Rule(name="fixture", hypothesis="known answers", expression=expression)
    np.testing.assert_allclose(
        score(rule, pd.DataFrame({"x": [2, 8], "error": [2, 8]}), schema), expected
    )
    assert pretty(Rule.model_validate_json(rule.model_dump_json()), schema) == pretty(rule, schema)


def test_forbidden_and_direction(schema):
    for term in [{"signal": "label"}, {"signal": "error", "direction": "higher_is_better"}]:
        rule = Rule(
            name="bad", hypothesis="invalid", expression={"kind": "additive", "terms": [term]}
        )
        with pytest.raises(ValueError):
            validate_rule(rule, schema)


@pytest.mark.parametrize(
    "expression",
    [
        {"kind": "additive", "terms": [{"signal": "x", "weight": 0}]},
        {"kind": "product", "factors": [{"signal": "x", "exponent": -1}]},
        {"kind": "additive", "terms": [{"signal": "x", "clip": [2, 1]}]},
        {"kind": "python", "code": "print(1)"},
        {"kind": "constant", "value": float("nan")},
    ],
)
def test_invalid_rule(expression):
    with pytest.raises(ValidationError):
        Rule(name="bad", hypothesis="invalid", expression=expression)
