import pandas as pd
import pytest
from pydantic import ValidationError

from autoresearch_filters.config import Config, digest
from autoresearch_filters.rules import Rule, pretty, score

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
