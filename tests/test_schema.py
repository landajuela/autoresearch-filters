import copy

import pandas as pd
import pytest
from pydantic import ValidationError

from autoresearch_filters.config import DatasetConfig
from autoresearch_filters.datasets import preprocess


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["signals"]["confidence"].update(range=[1, 0]),
        lambda c: c["signals"]["confidence"].update(direction="higher"),
        lambda c: c["signals"]["confidence"].update(oracle=False),
        lambda c: c["signals"]["confidence"].update(range=[0, float("inf")]),
        lambda c: c["signals"]["confidence"].update(missing={"policy": "constant"}),
        lambda c: c["signals"]["confidence"].update(missing={"policy": "median"}),
        lambda c: c.update(exclude_columns=["confidence"]),
        lambda c: c["signals"].update(success=c["signals"]["confidence"]),
        lambda c: c["signals"].update(_label=c["signals"]["confidence"]),
        lambda c: c["split"].update(repeats=4),
        lambda c: c.update(group_column=None),
        lambda c: c["protocol"].update(top_k=[0]),
        lambda c: c.update(typo=True),
    ],
)
def test_invalid_schema(config_dict, change):
    change(config_dict)
    with pytest.raises(ValidationError):
        DatasetConfig.model_validate(config_dict)


def test_missing_policies_and_outcome_exclusion(config_dict):
    raw = pd.read_csv(config_dict["source"]["path"])
    raw.loc[0, "confidence"] = float("nan")
    cfg = DatasetConfig.model_validate(config_dict)
    with pytest.raises(ValueError, match="missing"):
        preprocess(raw, cfg.feature_space())
    for policy, expected in [("drop", len(raw) - 1), ("constant", len(raw))]:
        config = copy.deepcopy(config_dict)
        config["signals"]["confidence"]["missing"] = {"policy": policy}
        if policy == "constant":
            config["signals"]["confidence"]["missing"]["value"] = 0.5
        result, audit = preprocess(raw, DatasetConfig.model_validate(config).feature_space())
        assert len(result) == expected
        assert "measured_response" not in result
        assert audit["missing"]["confidence"] == 1


def test_invalid_labels_ids_and_numbers(config_dict):
    raw = pd.read_csv(config_dict["source"]["path"])
    schema = DatasetConfig.model_validate(config_dict).feature_space()
    for column, value in [
        ("success", None),
        ("id", None),
        ("group", None),
        ("confidence", float("inf")),
    ]:
        changed = raw.copy()
        changed.loc[0, column] = value
        with pytest.raises(ValueError):
            preprocess(changed, schema)
