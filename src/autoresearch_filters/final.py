"""Locked final endpoint. No discovery command imports this module."""

from pathlib import Path

import pandas as pd

from .config import digest
from .dev import load_dev, record_base
from .io import now, read_json, verify_file, write_json
from .metrics import aggregate, measure
from .rules import Rule, score


def final(work: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("run output already exists")
    bundle = load_dev(work)
    decision = read_json(work / "transfer/decision.json")
    if digest(decision) != read_json(work / "transfer/decision-seal.json")["hash"]:
        raise ValueError("frozen selection decision changed")
    rule = Rule.model_validate(decision["chosen_rule"])
    if digest(rule) != decision["chosen_rule_hash"]:
        raise ValueError("final rule differs from frozen selection")
    record = record_base(bundle, "final", rule)
    # This capability is intentionally only in this module. Exclusive creation is race-safe.
    write_json(
        work / "final-consumed.json",
        {"timestamp": now(), "rule_hash": digest(rule), "config_hash": record["config_hash"]},
        exclusive=True,
    )
    seal = read_json(work / "seal.json")
    verify_file(work / "vault/holdout.csv", seal["holdout_hash"])
    frame = pd.read_csv(work / "vault/holdout.csv", dtype={"_id": str, "_group": str})
    metrics = measure(
        frame._label.to_numpy(),
        score(rule, frame, bundle.schema),
        frame._id.to_numpy(),
        bundle.protocol,
        bundle.manifest["split"]["seed"] + 9000,
    )
    record.update(
        {
            "summary": aggregate([metrics]),
            "metrics": metrics,
            "selection_decision": decision,
            "final_seed": bundle.manifest["split"]["seed"] + 9000,
            "holdout_hash": seal["holdout_hash"],
        }
    )
    record["notes"].append("Final holdout evaluated once. No selection may follow this result.")
    write_json(output, record, exclusive=True)
    return record
