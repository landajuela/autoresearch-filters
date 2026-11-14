"""Load a source table, normalize its columns, and cut it into the three piles."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .config import Config


def igdesign(cache: Path) -> pd.DataFrame:
    """Download only pinned public CSVs; retain only inverse-folding candidates."""
    cache.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        files("autoresearch_filters").joinpath("igdesign_manifest.json").read_text()
    )
    frames = []
    for item in manifest["files"]:
        path = cache / item["name"]
        if not path.exists():
            with urlopen(item["url"], timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError(f"upstream checksum mismatch: {item['name']}")
            path.write_bytes(content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"cached checksum mismatch: {path}")
        frame = pd.read_csv(path)
        frame["candidate_id"] = [f"{path.stem}:{i}" for i in range(len(frame))]
        frame["system"] = path.stem
        frames.append(frame.loc[frame["Method"] == "Inverse Folding"])
    return pd.concat(frames, ignore_index=True)


LOADERS = {"igdesign": igdesign}


def read_table(path: Path) -> pd.DataFrame:
    """Read a results table. Row order is preserved, because it can stand in for an ID."""
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"source must be a CSV/Parquet path or one of {sorted(LOADERS)}: {path}")


def load_source(config: Config, base: Path) -> pd.DataFrame:
    """`base` is the config file's directory; downloads are cached in ../data/downloads."""
    if config.source in LOADERS:
        return LOADERS[config.source]((base / "../data/downloads").resolve())
    return read_table(base / config.source)


def row_ids(frame: pd.DataFrame) -> pd.Series:
    """Zero-padded source row positions, for a table that carries no ID column."""
    width = len(str(max(len(frame) - 1, 0)))
    return pd.Series([f"row{i:0{width}d}" for i in range(len(frame))], index=frame.index)


def preprocess(frame: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Keep only _id, _label, _group and the allowlisted numeric signals. Nothing is fitted."""
    needed = {config.label_column, *config.signals}
    for optional in (config.id_column, config.group_column):
        if optional:
            needed.add(optional)
    if missing := needed - set(frame.columns):
        raise ValueError(f"missing columns: {sorted(missing)}")
    if config.id_column:
        ids = frame[config.id_column]
        if ids.isna().any() or ids.astype(str).duplicated().any():
            raise ValueError("candidate IDs must be non-null and unique")
    else:
        ids = row_ids(frame)  # no ID column declared: the source row position is the ID
    labels = frame[config.label_column]
    if labels.isna().any():
        raise ValueError("labels cannot be missing")
    if labels.nunique() != 2 or config.success_value not in set(labels.unique()):
        raise ValueError("label must have exactly two values including configured success_value")
    if config.group_column and frame[config.group_column].isna().any():
        raise ValueError("groups cannot be missing")
    result = pd.DataFrame(
        {
            "_id": ids.astype(str),
            "_label": (labels == config.success_value).astype(int),
            "_group": frame[config.group_column].astype(str)
            if config.group_column
            else "ungrouped",
        }
    )
    keep = pd.Series(True, index=frame.index)
    for name, signal in config.signals.items():
        numeric = pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if (frame[name].notna() & numeric.isna()).any():
            raise ValueError(f"signal {name!r} contains non-numeric or infinite values")
        if numeric.isna().any():
            if signal.missing == "error":
                raise ValueError(f"signal {name!r} has missing values")
            keep &= numeric.notna()
        result[name] = numeric
    return result.loc[keep].sort_values("_id").reset_index(drop=True)


def split(frame: pd.DataFrame, config: Config) -> dict[str, pd.DataFrame]:
    """Holdout first; then a stratified half of the remaining pool is reserved for verification."""
    cfg = config.split
    if cfg.holdout_groups:
        if missing := set(cfg.holdout_groups) - set(frame._group):
            raise ValueError(f"unknown holdout groups: {sorted(missing)}")
        mask = frame._group.isin(cfg.holdout_groups)
        pool, holdout = frame[~mask], frame[mask]
    else:
        pool, holdout = train_test_split(
            frame, test_size=cfg.holdout_fraction, stratify=frame._label, random_state=cfg.seed
        )
    discovery, verification = train_test_split(
        pool, test_size=0.5, stratify=pool._label, random_state=cfg.seed + 1
    )
    piles = {"discovery": discovery, "verification": verification, "holdout": holdout}
    for name, part in piles.items():
        if part._label.nunique() != 2:
            raise ValueError(f"{name} must contain both classes; pre-specify a suitable split")
    return {name: part.sort_values("_id").reset_index(drop=True) for name, part in piles.items()}


def read_pile(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"_id": str, "_group": str})
