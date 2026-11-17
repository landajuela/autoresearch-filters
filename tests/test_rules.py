import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from autoresearch_filters.config import Config, digest
from autoresearch_filters.rules import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    Rule,
    load_rule,
    pretty,
    score,
    signals,
)

CONFIG = Config.model_validate(
    {
        "name": "toy",
        "source": "toy.csv",
        "id_column": "id",
        "label_column": "y",
        "success_value": 1,
        "signals": {
            "up": {"direction": "higher_is_better", "range": [0, 10]},
            "err": {"direction": "lower_is_better", "range": [0, 4]},
        },
    }
)
FRAME = pd.DataFrame({"up": [0.0, 5.0, 20.0], "err": [0.0, 1.0, 4.0]})


def rule(expression: dict) -> Rule:
    return Rule.model_validate({"name": "r", "hypothesis": "h", "expression": expression})


def test_additive_normalizes_clips_and_orients():
    r = rule({"kind": "additive", "terms": [{"signal": "up"}, {"signal": "err", "weight": 3}]})
    # n(up) = [0, .5, 1] (clipped); n(err) = [1, .75, 0] (lower is better)
    assert score(r, FRAME, CONFIG) == pytest.approx([0.75, 0.6875, 0.25])


def test_product_and_gate_arithmetic():
    product = rule({"kind": "product", "factors": [{"signal": "up"}, {"signal": "err"}]})
    assert score(product, FRAME, CONFIG) == pytest.approx([0, 0.375, 0])
    gate = {
        "name": "bad-err",
        "when": {"signal": "err", "op": ">", "value": 0.5},
        "adjustments": [{"signal": "up", "weight": 0.5, "center": 0.5}],
    }
    base = {"kind": "additive", "terms": [{"signal": "err"}]}
    gated = rule({"kind": "gated", "base": base, "gates": [gate]})
    # Gate is on the RAW value; the adjustment is centered, so it can reward or penalize.
    assert score(gated, FRAME, CONFIG) == pytest.approx([1, 0.75, 0.25])
    text = pretty(gated, CONFIG)
    assert '1["err" > 0.5]' in text and "lower_is_better" in text


def test_language_is_closed():
    with pytest.raises(ValueError, match="unknown signals"):
        score(rule({"kind": "additive", "terms": [{"signal": "y"}]}), FRAME, CONFIG)
    for bad in [
        {"kind": "python", "code": "1"},
        {"kind": "additive", "terms": [{"signal": "up", "weight": -1}]},
        {"kind": "additive", "terms": [{"signal": "up", "fit": True}]},
        {"kind": "additive", "terms": []},
    ]:
        with pytest.raises(ValidationError):
            rule(bad)


def test_digest_ignores_formatting_but_not_content():
    a = rule({"kind": "additive", "terms": [{"signal": "up"}]})
    b = rule({"terms": [{"weight": 1.0, "signal": "up"}], "kind": "additive"})
    c = rule({"kind": "additive", "terms": [{"signal": "err"}]})
    assert digest(a) == digest(b) != digest(c)


def test_config_rejects_outcome_columns_as_signals_and_unknown_keys():
    raw = CONFIG.model_dump(mode="json")
    leaky = {**raw, "signals": {**raw["signals"], "y": raw["signals"]["up"]}}
    with pytest.raises(ValidationError, match="cannot be signals"):
        Config.model_validate(leaky)
    with pytest.raises(ValidationError):
        Config.model_validate({**raw, "surprise": 1})
    with pytest.raises(ValidationError, match="group_column"):
        Config.model_validate({**raw, "split": {"cv": "logo"}})


@pytest.fixture
def nested_expression():
    return {
        "kind": "conditional",
        "when": {"signal": "up", "op": "<", "value": 5},
        "then": {
            "kind": "conditional",
            "when": {"signal": "err", "op": ">", "value": 1},
            "then": {"kind": "constant", "value": -0.25},
            "else": {"kind": "product", "factors": [{"signal": "up"}, {"signal": "err"}]},
        },
        "else": {
            "kind": "conditional",
            "when": {"signal": "err", "op": ">=", "value": 4},
            "then": {
                "kind": "gated",
                "base": {"kind": "additive", "terms": [{"signal": "err"}]},
                "gates": [
                    {
                        "name": "up-adjustment",
                        "when": {"signal": "up", "op": ">=", "value": 5},
                        "adjustments": [{"signal": "up", "weight": 0.5, "center": 0.5}],
                    }
                ],
            },
            "else": {"kind": "additive", "terms": [{"signal": "up"}, {"signal": "err"}]},
        },
    }


def test_nested_branches_score_all_leaf_types_in_original_row_order(nested_expression):
    frame = pd.DataFrame(
        {"up": [2, 4, 5, 20, 10, -2, 5], "err": [2, 1, 2, 4, 0, 1, 4]},
        index=[9, 9, 3, 20, 20, 9, 3],
    )
    r = rule(nested_expression)
    # Both sides contain another conditional. Leaves cover constants and all legacy formulas.
    assert score(r, frame, CONFIG) == pytest.approx([-0.25, 0.3, 0.5, 0.25, 1, 0, 0])
    assert signals(r) == {"up", "err"}
    assert score(r, frame.iloc[:0], CONFIG).shape == (0,)
    text = pretty(r, CONFIG)
    assert text.count("if [") == text.count(" then (") == text.count(" else (") == 3
    assert 'if ["up" < 5]' in text and 'if ["err" >= 4]' in text
    assert "lower_is_better" in text and "then (-0.25)" in text


@pytest.mark.parametrize(
    ("op", "expected"),
    [("<", [2, -1, -1]), ("<=", [2, 2, -1]), (">", [-1, -1, 2]), (">=", [-1, 2, 2])],
)
def test_conditional_boundaries_use_raw_values_not_normalized_scores(op, expected):
    r = rule(
        {
            "kind": "conditional",
            "when": {"signal": "err", "op": op, "value": 1},
            "then": {"kind": "constant", "value": 2},
            "else": {"kind": "constant", "value": -1},
        }
    )
    assert score(r, FRAME, CONFIG) == pytest.approx(expected)


def test_conditional_evaluates_only_the_selected_rows_in_each_branch():
    r = rule(
        {
            "kind": "conditional",
            "when": {"signal": "up", "op": "<", "value": 5},
            "then": {
                "kind": "gated",
                "base": {"kind": "additive", "terms": [{"signal": "up"}]},
                "gates": [
                    {
                        "name": "large-adjustment",
                        "when": {"signal": "up", "op": ">=", "value": 0},
                        "adjustments": [{"signal": "up", "weight": 1e308, "center": -1}],
                    }
                ],
            },
            "else": {"kind": "constant", "value": 0.5},
        }
    )
    # Computing the then formula for up=20 would overflow, but that row takes else.
    with np.errstate(over="raise", invalid="raise"):
        assert score(r, FRAME, CONFIG) == pytest.approx([1e308, 0.5, 0.5])
        assert score(r, FRAME.iloc[1:], CONFIG) == pytest.approx([0.5, 0.5])


@pytest.mark.parametrize("location", ["when", "leaf"])
@pytest.mark.parametrize("forbidden", ["y", "_label", "_id", "_group", "unknown"])
def test_unselected_nested_branches_still_validate_all_signals(
    nested_expression, location, forbidden
):
    # The outer then branch is unreachable for these rows, but its terms must be allowlisted.
    branch = nested_expression["then"]
    if location == "when":
        branch["when"]["signal"] = forbidden
    else:
        branch["else"]["factors"][0]["signal"] = forbidden
    r = rule(nested_expression)
    with pytest.raises(ValueError, match="unknown signals"):
        score(r, FRAME.iloc[1:], CONFIG)
    with pytest.raises(ValueError, match="unknown signals"):
        pretty(r, CONFIG)


def test_nested_rules_round_trip_through_journal_and_frozen_json(nested_expression, tmp_path):
    r = rule(nested_expression)
    dumped = r.model_dump(mode="json")
    assert "else_branch" not in json.dumps(dumped)
    assert "else" in dumped["expression"]["else"]
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps(dumped))
    for restored in [
        load_rule(frozen),
        Rule.model_validate_json(r.model_dump_json()),
        Rule.model_validate(r.model_dump()),
        Rule.model_validate(r.model_dump(by_alias=True)),
    ]:
        assert restored == r
        assert digest(restored) == digest(r)
        assert pretty(restored, CONFIG) == pretty(r, CONFIG)
    changed = copy.deepcopy(nested_expression)
    changed["then"]["when"]["value"] = 2
    assert digest(rule(changed)) != digest(r)
    changed = copy.deepcopy(nested_expression)
    changed["then"]["then"]["value"] = 0
    assert digest(rule(changed)) != digest(r)
    for mode in ["validation", "serialization"]:
        schema = Rule.model_json_schema(mode=mode)
        branch_schema = schema["$defs"]["Conditional"]
        assert {"when", "then", "else"} <= set(branch_schema["required"])


@pytest.mark.parametrize("missing", ["when", "then", "else"])
def test_conditional_requires_a_condition_and_both_branches(nested_expression, missing):
    del nested_expression[missing]
    with pytest.raises(ValidationError):
        rule(nested_expression)


@pytest.mark.parametrize(
    "invalid_leaf",
    [
        {"kind": "constant", "value": float("nan")},
        {"kind": "constant", "value": float("inf")},
        {"kind": "constant", "value": 1, "fit": True},
        {"kind": "python", "code": "1"},
    ],
)
def test_tree_leaves_keep_the_language_closed(nested_expression, invalid_leaf):
    nested_expression["else"]["else"] = invalid_leaf
    with pytest.raises(ValidationError):
        rule(nested_expression)


@pytest.mark.parametrize("bad_threshold", [float("nan"), float("inf"), float("-inf")])
def test_tree_thresholds_must_be_finite(nested_expression, bad_threshold):
    nested_expression["else"]["when"]["value"] = bad_threshold
    with pytest.raises(ValidationError):
        rule(nested_expression)


def test_tree_size_and_depth_are_bounded():
    def split(then, otherwise):
        return {
            "kind": "conditional",
            "when": {"signal": "up", "op": "<", "value": 5},
            "then": then,
            "else": otherwise,
        }

    leaf = {"kind": "constant", "value": 0}
    chain = leaf
    for _ in range(MAX_TREE_DEPTH):
        chain = split(chain, leaf)
    assert score(rule(chain), FRAME, CONFIG) == pytest.approx([0, 0, 0])
    with pytest.raises(ValidationError, match="nesting exceeds"):
        rule(split(chain, leaf))
    full, nodes = leaf, 1
    while 2 * nodes + 1 <= MAX_TREE_NODES:
        full, nodes = split(full, full), 2 * nodes + 1
    rule(full)
    with pytest.raises(ValidationError, match="tree exceeds"):
        rule(split(full, full))


def test_documented_tree_example_loads_with_the_synthetic_config():
    from autoresearch_filters.config import load_config
    from autoresearch_filters.rules import validate_rule

    root = Path(__file__).resolve().parents[1]
    r = load_rule(root / "rules/tree.json")
    config = load_config(root / "configs/synthetic.json")
    validate_rule(r, config)
    frame = pd.DataFrame({"confidence": [0.2, 0.2, 0.8], "stabilizer": [0.3, 0.9, 0.1]})
    assert score(r, frame, config) == pytest.approx([0, 0.2, 0.8])
