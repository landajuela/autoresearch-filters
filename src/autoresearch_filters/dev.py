"""Discovery evaluation. This module cannot load sources, transfer data, or a holdout."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .config import FeatureSpace, Protocol, digest
from .io import file_hash, git_state, now, read_json, verify_file, write_json
from .metrics import aggregate, measure
from .rules import Rule, Term, pretty, score, term_values


@dataclass(frozen=True)
class DevBundle:
    """Contains only discovery rows and feature semantics; no source or holdout path."""

    frame: pd.DataFrame
    schema: FeatureSpace
    protocol: Protocol
    partitions: list[dict]
    manifest: dict


def load_dev(work: Path) -> DevBundle:
    seal = read_json(work / "seal.json")
    root = work / "dev"
    verify_file(root / "manifest.json", seal["dev_manifest_hash"])
    manifest = read_json(root / "manifest.json")
    for name, expected in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("dev manifest may name only local files")
        verify_file(root / name, expected)
    return DevBundle(
        pd.read_csv(root / "discovery.csv", dtype={"_id": str, "_group": str}),
        FeatureSpace.model_validate_json((root / "schema.json").read_text()),
        Protocol.model_validate_json((root / "protocol.json").read_text()),
        read_json(root / "partitions.json")["folds"],
        manifest,
    )


def sign_diagnostics(bundle: DevBundle) -> list[dict]:
    result = []
    for name, signal in bundle.schema.signals.items():
        values = term_values(Term(signal=name), bundle.frame, bundle.schema)
        auc = float(roc_auc_score(bundle.frame._label, values))
        inverted = signal.expected_positive_auc and auc < 0.5 - bundle.protocol.sign_tolerance
        result.append({"signal": name, "oriented_auc": auc, "inverted": inverted})
        if inverted:
            message = (
                f"SIGN WARNING: {name!r} has oriented AUC {auc:.4f} < 0.5; "
                "check negative-valued errors and declared direction. Do not auto-flip it."
            )
            if bundle.protocol.sign_policy == "error":
                raise AssertionError(message)
            warnings.warn(message, UserWarning, stacklevel=2)
    return result


def evaluate_frame(
    frame: pd.DataFrame,
    rule: Rule,
    schema: FeatureSpace,
    protocol: Protocol,
    partitions: list[dict],
) -> dict:
    predictions = score(rule, frame, schema)
    indices = {value: i for i, value in enumerate(frame._id)}
    folds = []
    for part in partitions:
        if set(part["train_ids"]) & set(part["validation_ids"]):
            raise ValueError("CV train/validation overlap")
        val = np.array([indices[value] for value in part["validation_ids"]])
        metrics = measure(
            frame._label.to_numpy()[val],
            predictions[val],
            frame._id.to_numpy()[val],
            protocol,
            part["seed"] + part["fold"] * 10000,
        )
        folds.append(
            {
                "repeat": part["repeat"],
                "fold": part["fold"],
                "metric_seed": part["seed"] + part["fold"] * 10000,
                "metrics": metrics,
            }
        )
    repeats = []
    for repeat in sorted({f["repeat"] for f in folds}):
        summary = aggregate([f["metrics"] for f in folds if f["repeat"] == repeat])
        repeats.append({key: item["mean"] for key, item in summary.items()})
    return {
        "summary": aggregate(repeats),
        "fold_summary": aggregate([f["metrics"] for f in folds]),
        "repeats": repeats,
        "folds": folds,
    }


def record_base(bundle: DevBundle, mode: str, rule: Rule) -> dict:
    return {
        "record_version": 1,
        "mode": mode,
        "timestamp": now(),
        "git": git_state(),
        "dataset": bundle.schema.name,
        "config_hash": bundle.manifest["config_hash"],
        "dataset_hash": bundle.manifest["dataset_hash"],
        "cache_key": bundle.manifest["cache_key"],
        "partition_hash": bundle.manifest["files"]["partitions.json"],
        "preprocessing": bundle.manifest["preprocessing"],
        "seeds": bundle.manifest["seeds"],
        "rule_hash": digest(rule),
        "implementation_hash": digest(
            {path.name: file_hash(path) for path in sorted(Path(__file__).parent.glob("*.py"))}
        ),
        "environment": {
            package: version(package)
            for package in ["autoresearch-filters", "numpy", "pandas", "scikit-learn", "pydantic"]
        },
        "rule": rule.model_dump(mode="json"),
        "formula": pretty(rule, bundle.schema),
        "notes": ["CV standard deviation is repeat variability, not a confidence interval."]
        + (
            [
                "LOGO repeats reuse identical natural-balance folds; "
                "they are not independent evidence."
            ]
            if bundle.manifest["split"]["dev"] == "logo"
            else []
        ),
    }


def evaluate(work: Path, rule: Rule, output: Path, mode: str = "dev") -> dict:
    if mode not in {"dev", "search"}:
        raise ValueError("eval permits dev/search only; final uses a separate code path")
    if (work / "transfer/consumed.json").exists() or (work / "final-consumed.json").exists():
        raise ValueError("campaign is frozen after transfer verification; stop searching")
    if output.exists():
        raise ValueError("run output already exists; records are immutable")
    bundle = load_dev(work)
    if mode == "search":
        budget_dir = work / "search-budget"
        budget_dir.mkdir(exist_ok=True)
        for slot in range(bundle.protocol.search_budget):
            try:
                write_json(
                    budget_dir / f"{slot:03d}.json", {"rule_hash": digest(rule)}, exclusive=True
                )
                break
            except FileExistsError:
                continue
        else:
            raise ValueError("search budget exhausted; scans are hypothesis generators only")
    record = record_base(bundle, mode, rule)
    try:
        record["sign_diagnostics"] = sign_diagnostics(bundle)
        # Preprocessed snapshots are the dataset/partition/version cache. No fitted preprocessing.
        record.update(
            evaluate_frame(bundle.frame, rule, bundle.schema, bundle.protocol, bundle.partitions)
        )
        record["status"] = "ok"
    except (ValueError, AssertionError) as exc:
        record.update({"status": "failed", "error": str(exc), "selection_eligible": False})
        write_json(output, record, exclusive=True)
        raise
    record["selection_eligible"] = False  # Only transfer-check can authorize a new incumbent.
    write_json(output, record, exclusive=True)
    return record
