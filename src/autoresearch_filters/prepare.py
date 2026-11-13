"""The only stage (besides final) allowed to handle final-holdout data."""

from pathlib import Path

import pandas as pd

from .config import digest, load_config
from .datasets import PREPROCESSING_VERSION, load_source, preprocess
from .io import file_hash, read_json, verify_file, write_json
from .splits import cv_partitions, holdout_indices, verification_indices


def prepare(config_path: Path, work: Path) -> dict:
    config = load_config(config_path)
    config_hash = digest(config)
    seal_path = work / "seal.json"
    if seal_path.exists():
        seal = read_json(seal_path)
        if seal["config_hash"] != config_hash or seal["preprocessing"] != PREPROCESSING_VERSION:
            raise ValueError(
                "configuration changed: cache invalidated; use a new campaign directory"
            )
        # Idempotence needs no source, verifier or holdout reads. Dev checks its own files.
        return {"status": "already_prepared", "config_hash": config_hash}
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise ValueError(
            "prepare requires an empty directory; partial preparations are not reusable"
        )
    schema = config.feature_space()
    raw = load_source(config.source, config_path.parent)
    frame, audit = preprocess(raw, schema)
    if config.split.holdout == "external":
        external = load_source(config.split.external, config_path.parent)
        holdout, external_audit = preprocess(external, schema)
        pool = frame
        if set(pool._id) & set(holdout._id):
            raise ValueError("external holdout overlaps pool candidate IDs")
        if schema.group_column and set(pool._group) & set(holdout._group):
            raise ValueError("external holdout overlaps pool groups")
    else:
        pool_idx, hold_idx = holdout_indices(frame, config.split)
        pool, holdout = frame.iloc[pool_idx], frame.iloc[hold_idx]
        external_audit = None
    selection_idx, verification_idx = verification_indices(pool, config.split)
    discovery, verification = pool.iloc[selection_idx], pool.iloc[verification_idx]
    for name, part in [
        ("discovery", discovery),
        ("verification", verification),
        ("holdout", holdout),
    ]:
        if len(part) == 0 or part._label.nunique() != 2:
            raise ValueError(f"{name} must contain both classes; pre-specify a suitable split")
    paths = {
        "discovery": work / "dev/discovery.csv",
        "verification": work / "transfer/verification.csv",
        "holdout": work / "vault/holdout.csv",
    }
    for name, part in [
        ("discovery", discovery),
        ("verification", verification),
        ("holdout", holdout),
    ]:
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        part.sort_values("_id").to_csv(paths[name], index=False)
    # Generate partitions against the serialized representation used by every later process.
    discovery = pd.read_csv(paths["discovery"], dtype={"_id": str, "_group": str})
    verification = pd.read_csv(paths["verification"], dtype={"_id": str, "_group": str})
    write_json(work / "dev/schema.json", schema.model_dump(mode="json"))
    protocol = config.protocol.model_dump(mode="json")
    if config.protocol.match_holdout_prevalence:
        # Explicit opt-in, fixed before discovery: disclose only aggregate prevalence.
        protocol["target_prevalence"] = float(holdout._label.mean())
        protocol["match_holdout_prevalence"] = False
    write_json(work / "dev/protocol.json", protocol)
    write_json(work / "dev/partitions.json", {"folds": cv_partitions(discovery, config.split)})
    write_json(
        work / "transfer/partitions.json", {"folds": cv_partitions(verification, config.split)}
    )
    source_fingerprint = digest(
        {
            "pool": digest(pool.to_dict(orient="list")),
            "holdout": digest(holdout.to_dict(orient="list")),
        }
    )
    dev_files = {p.name: file_hash(p) for p in (work / "dev").iterdir() if p.is_file()}
    cache_key = digest(
        {
            "dataset": source_fingerprint,
            "config": config_hash,
            "partition": dev_files["partitions.json"],
            "preprocessing": PREPROCESSING_VERSION,
        }
    )
    manifest = {
        "config_hash": config_hash,
        "dataset_hash": source_fingerprint,
        "cache_key": cache_key,
        "preprocessing": PREPROCESSING_VERSION,
        "files": dev_files,
        "split": config.split.model_dump(exclude={"external"}),
        "prevalence_source": (
            "holdout_aggregate_at_prepare"
            if config.protocol.match_holdout_prevalence
            else "declared"
            if config.protocol.target_prevalence is not None
            else "disabled"
        ),
        "seeds": [config.split.seed, config.split.seed + 1]
        + [config.split.seed + 100 + i for i in range(config.split.repeats)],
    }
    write_json(work / "dev/manifest.json", manifest)
    seal = {
        "config_hash": config_hash,
        "preprocessing": PREPROCESSING_VERSION,
        "dev_manifest_hash": file_hash(work / "dev/manifest.json"),
        "verification_hash": file_hash(paths["verification"]),
        "verification_partitions_hash": file_hash(work / "transfer/partitions.json"),
        "holdout_hash": file_hash(paths["holdout"]),
        "cache_key": cache_key,
    }
    # Detailed preprocessing statistics can include final rows, so keep them inside the vault.
    write_json(work / "vault/preparation_audit.json", {"source": audit, "external": external_audit})
    write_json(seal_path, seal, exclusive=True)
    return {"status": "prepared", "config_hash": config_hash, "cache_key": cache_key}


def verify_dev_manifest(work: Path) -> dict:
    seal = read_json(work / "seal.json")
    verify_file(work / "dev/manifest.json", seal["dev_manifest_hash"])
    return seal
