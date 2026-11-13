import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

from autoresearch_filters.config import SplitConfig
from autoresearch_filters.dev import evaluate, load_dev, sign_diagnostics
from autoresearch_filters.final import final
from autoresearch_filters.io import read_json
from autoresearch_filters.prepare import prepare
from autoresearch_filters.rules import Rule, load_rule
from autoresearch_filters.splits import cv_partitions
from autoresearch_filters.transfer import register, transfer_check

ROOT = Path(__file__).resolve().parents[1]


def test_determinism_and_group_disjointness(campaign, tmp_path, config_dict):
    config = tmp_path / "duplicate.json"
    config.write_text(json.dumps(config_dict))
    other = tmp_path / "other"
    prepare(config, other)
    for name in ["dev/partitions.json", "dev/discovery.csv", "vault/holdout.csv", "seal.json"]:
        assert (campaign / name).read_bytes() == (other / name).read_bytes()
    bundle = load_dev(campaign)
    hold = pd.read_csv(campaign / "vault/holdout.csv")
    verifier = pd.read_csv(campaign / "transfer/verification.csv")
    assert not set(bundle.frame._id) & set(verifier._id)
    assert not set(bundle.frame._group) & set(hold._group)
    assert not set(verifier._group) & set(hold._group)
    assert len({p["seed"] for p in bundle.partitions}) == 5
    for strategy in ["group", "logo", "random"]:
        parts = cv_partitions(bundle.frame, SplitConfig(dev=strategy, folds=3))
        for part in parts:
            assert not set(part["train_ids"]) & set(part["validation_ids"])
            if strategy != "random":
                indexed = bundle.frame.set_index("_id")
                assert not set(indexed.loc[part["train_ids"], "_group"]) & set(
                    indexed.loc[part["validation_ids"], "_group"]
                )


def test_dev_never_opens_holdout_verifier_or_source(campaign, tmp_path, monkeypatch):
    original_read = pd.read_csv
    opened = []

    def safe_read(path, *args, **kwargs):
        assert Path(path) == campaign / "dev/discovery.csv"
        opened.append(str(path))
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", safe_read)
    original_open = Path.open

    def safe_open(path, *args, **kwargs):
        assert "vault" not in path.parts
        assert path.name != "verification.csv"
        assert path.name != "synthetic.csv"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", safe_open)
    result = evaluate(campaign, load_rule(ROOT / "rules/synthetic.json"), tmp_path / "dev.json")
    assert result["summary"]["roc_auc"]["mean"] == 1
    assert opened


def test_sign_trap_errors_instead_of_flipping(campaign):
    bundle = load_dev(campaign)
    assert all(not row["inverted"] for row in sign_diagnostics(bundle))
    schema = bundle.schema.model_dump()
    schema["signals"]["negative_error"]["direction"] = "lower_is_better"
    inverted = dataclasses.replace(bundle, schema=type(bundle.schema).model_validate(schema))
    with pytest.raises(AssertionError, match="SIGN WARNING"):
        sign_diagnostics(inverted)
    warning = dataclasses.replace(
        inverted, protocol=inverted.protocol.model_copy(update={"sign_policy": "warn"})
    )
    with pytest.warns(UserWarning, match="negative_error"):
        sign_diagnostics(warning)


def test_config_and_data_tampering_rejected(campaign, tmp_path, config_dict):
    config_dict["protocol"]["max_fpr"] = 0.2
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(config_dict))
    with pytest.raises(ValueError, match="configuration changed"):
        prepare(path, campaign)
    with (campaign / "dev/discovery.csv").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="sealed file changed"):
        load_dev(campaign)


def register_constant(campaign, tmp_path):
    candidate = Rule(
        name="flat",
        hypothesis="A deliberately uninformative negative control.",
        expression={"kind": "constant", "value": 0.5},
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json())
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "baseline": str(ROOT / "rules/synthetic.json"),
                "candidates": [{"path": str(candidate_path), "reason": candidate.hypothesis}],
            }
        )
    )
    register(campaign, plan)
    return plan


def test_transfer_and_final_are_once_only(campaign, tmp_path, monkeypatch):
    register_constant(campaign, tmp_path)
    original_read = pd.read_csv

    def no_final(path, *args, **kwargs):
        assert "vault" not in Path(path).parts
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", no_final)
    result = transfer_check(campaign, tmp_path / "transfer.json")
    assert not result["decision"]["accepted"]
    with pytest.raises(FileExistsError):
        transfer_check(campaign, tmp_path / "transfer-again.json")
    with pytest.raises(ValueError, match="frozen"):
        evaluate(campaign, load_rule(ROOT / "rules/synthetic.json"), tmp_path / "after.json")
    monkeypatch.setattr(pd, "read_csv", original_read)
    result = final(campaign, tmp_path / "final.json")
    assert result["metrics"]["roc_auc"] == 1
    with pytest.raises(FileExistsError):
        final(campaign, tmp_path / "final-again.json")


def test_failed_final_is_consumed(campaign, tmp_path):
    register_constant(campaign, tmp_path)
    transfer_check(campaign, tmp_path / "transfer.json")
    (campaign / "vault/holdout.csv").write_text("tampered")
    with pytest.raises(ValueError, match="sealed file"):
        final(campaign, tmp_path / "final.json")
    assert (campaign / "final-consumed.json").exists()


def test_external_holdout_overlap_is_rejected(tmp_path, config_dict):
    config_dict["split"] = {"holdout": "external", "external": config_dict["source"]}
    path = tmp_path / "external.json"
    path.write_text(json.dumps(config_dict))
    with pytest.raises(ValueError, match="overlaps"):
        prepare(path, tmp_path / "work")


def test_random_holdout(tmp_path, config_dict):
    config_dict["split"] = {"holdout": "random", "dev": "random"}
    path = tmp_path / "random.json"
    path.write_text(json.dumps(config_dict))
    prepare(path, tmp_path / "random")
    assert read_json(tmp_path / "random/seal.json")["config_hash"]


def test_preparation_idempotent_without_reading_sources(
    campaign, tmp_path, config_dict, monkeypatch
):
    path = tmp_path / "same.json"
    path.write_text(json.dumps(config_dict))

    def fail(*args, **kwargs):
        raise AssertionError("unexpected source read")

    monkeypatch.setattr(pd, "read_csv", fail)
    assert prepare(path, campaign)["status"] == "already_prepared"
