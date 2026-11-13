"""One-use verification of a small, registered candidate batch."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pandas as pd
from pydantic import Field, model_validator

from .config import StrictModel, digest
from .dev import evaluate_frame, load_dev, record_base
from .io import now, read_json, verify_file, write_json
from .rules import Rule, load_rule, validate_rule


class Candidate(StrictModel):
    path: str
    reason: str = Field(min_length=12)


class Plan(StrictModel):
    baseline: str
    candidates: list[Candidate] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len({c.path for c in self.candidates} | {self.baseline}) != len(self.candidates) + 1:
            raise ValueError("candidate and baseline paths must be distinct")
        return self


def register(work: Path, plan_path: Path) -> dict:
    bundle = load_dev(work)
    if (work / "transfer/consumed.json").exists():
        raise ValueError("verification has already been consumed")
    plan = Plan.model_validate_json(plan_path.read_text())
    baseline = load_rule(plan_path.parent / plan.baseline)
    candidates = [load_rule(plan_path.parent / c.path) for c in plan.candidates]
    for rule in [baseline, *candidates]:
        validate_rule(rule, bundle.schema)
    if len({digest(r) for r in [baseline, *candidates]}) != len(candidates) + 1:
        raise ValueError("registered rules must be distinct")
    registration = {
        "registered_at": now(),
        "plan_hash": digest(plan),
        "baseline": baseline.model_dump(mode="json"),
        "candidates": [
            {"rule": rule.model_dump(mode="json"), "reason": candidate.reason}
            for rule, candidate in zip(candidates, plan.candidates, strict=True)
        ],
        "config_hash": bundle.manifest["config_hash"],
    }
    write_json(work / "transfer/registration.json", registration, exclusive=True)
    # This hash is checked before consuming verification, protecting accidental edits.
    write_json(
        work / "transfer/registration-seal.json", {"hash": digest(registration)}, exclusive=True
    )
    return registration


def means(evaluation: dict) -> dict[str, float | None]:
    return {key: value["mean"] for key, value in evaluation["summary"].items()}


def guard_failures(candidate: dict, baseline: dict, tolerance: float) -> list[str]:
    names = ["roc_auc", "pr_auc", *[k for k in baseline if k.startswith("precision@")]]
    return [
        key
        for key in names
        if candidate.get(key) is None
        or baseline.get(key) is None
        or candidate[key] < baseline[key] - tolerance
    ]


def transfer_check(work: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("run output already exists")
    bundle = load_dev(work)
    registration = read_json(work / "transfer/registration.json")
    if digest(registration) != read_json(work / "transfer/registration-seal.json")["hash"]:
        raise ValueError("registration changed after it was sealed")
    if registration["config_hash"] != bundle.manifest["config_hash"]:
        raise ValueError("registration belongs to a different configuration")
    baseline = Rule.model_validate(registration["baseline"])
    candidates = [Rule.model_validate(c["rule"]) for c in registration["candidates"]]
    primary = bundle.protocol.primary_metric

    def discovery(rule: Rule) -> dict:
        return evaluate_frame(bundle.frame, rule, bundle.schema, bundle.protocol, bundle.partitions)

    baseline_dev = discovery(baseline)
    base_values = means(baseline_dev)
    evaluated = [(rule, discovery(rule)) for rule in candidates]
    eligible = [
        (rule, result)
        for rule, result in evaluated
        if not guard_failures(means(result), base_values, bundle.protocol.guard_tolerance)
        and means(result)[primary] is not None
        and base_values[primary] is not None
        and means(result)[primary] > base_values[primary]
    ]
    # Selection happens only on discovery; verifier is still unopened here.
    selected, selected_dev = max(
        eligible, key=lambda item: means(item[1])[primary], default=(baseline, baseline_dev)
    )
    record = record_base(bundle, "transfer", selected)
    record["registration"] = registration
    record["discovery_candidates"] = [
        {
            "rule_hash": digest(rule),
            "name": rule.name,
            "evaluation": result,
            "guard_failures": guard_failures(
                means(result), base_values, bundle.protocol.guard_tolerance
            ),
        }
        for rule, result in evaluated
    ]
    # Exclusive claim BEFORE opening any verifier rows. A failed run stays consumed.
    write_json(
        work / "transfer/consumed.json",
        {
            "timestamp": now(),
            "selected_hash": digest(selected),
            "registration_hash": digest(registration),
        },
        exclusive=True,
    )
    seal = read_json(work / "seal.json")
    verify_file(work / "transfer/verification.csv", seal["verification_hash"])
    verify_file(work / "transfer/partitions.json", seal["verification_partitions_hash"])
    verification = pd.read_csv(
        work / "transfer/verification.csv", dtype={"_id": str, "_group": str}
    )
    if set(verification._id) & set(bundle.frame._id):
        raise ValueError("verification overlaps discovery")
    partitions = read_json(work / "transfer/partitions.json")["folds"]
    baseline_transfer = evaluate_frame(
        verification, baseline, bundle.schema, bundle.protocol, partitions
    )
    selected_transfer = evaluate_frame(
        verification, selected, bundle.schema, bundle.protocol, partitions
    )
    before, after = means(baseline_transfer), means(selected_transfer)
    failures = guard_failures(after, before, bundle.protocol.guard_tolerance)
    dev_gain = means(selected_dev)[primary] - base_values[primary]
    transfer_gain = (
        after[primary] - before[primary]
        if after[primary] is not None and before[primary] is not None
        else None
    )
    accepted = (
        digest(selected) != digest(baseline)
        and not failures
        and transfer_gain is not None
        and transfer_gain > bundle.protocol.minimum_transfer_gain
    )
    chosen = selected if accepted else baseline
    reason = (
        "Candidate survives disjoint verification and guard metrics."
        if accepted
        else "Candidate failed discovery or transfer criteria; retain baseline and stop."
    )
    decision = {
        "accepted": accepted,
        "reason": reason,
        "dev_gain": dev_gain,
        "transfer_gain": transfer_gain,
        "optimism_gap": dev_gain - transfer_gain if transfer_gain is not None else None,
        "guard_failures": failures,
        "stop_search": True,
        "chosen_rule_hash": digest(chosen),
        "chosen_rule": chosen.model_dump(mode="json"),
    }
    record.update(
        {
            **selected_transfer,
            "baseline_discovery": baseline_dev,
            "selected_discovery": selected_dev,
            "baseline_transfer": baseline_transfer,
            "decision": decision,
            "verification_partition_hash": seal["verification_partitions_hash"],
        }
    )
    write_json(output, record, exclusive=True)
    write_json(work / "transfer/decision.json", decision, exclusive=True)
    write_json(work / "transfer/decision-seal.json", {"hash": digest(decision)}, exclusive=True)
    return record
