"""Trusted preparation-only loaders. Rules cannot import or invoke these."""

from __future__ import annotations

import hashlib
import importlib
import json
from importlib.resources import files
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import pandas as pd

from .config import FeatureSpace, FileSource, LoaderSource

PREPROCESSING_VERSION = "1"


def igdesign(cache_dir: str) -> pd.DataFrame:
    """Download only pinned public CSVs; retain only inverse-folding candidates."""
    cache = Path(cache_dir)
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


def load_source(source: FileSource | LoaderSource, base: Path) -> pd.DataFrame:
    if isinstance(source, LoaderSource):
        module, name = source.hook.split(":")
        kwargs = dict(source.kwargs)
        # Hooks are trusted preparation code. Relative cache paths use config location.
        if "cache_dir" in kwargs:
            kwargs["cache_dir"] = str((base / kwargs["cache_dir"]).resolve())
        result = getattr(importlib.import_module(module), name)(**kwargs)
        if not isinstance(result, pd.DataFrame):
            raise TypeError("loader must return a pandas DataFrame")
        return result
    path = base / source.path
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            return pd.read_parquet(path)
        except ImportError as exc:
            raise ValueError(
                "Parquet needs an optional pandas engine; export CSV or install one"
            ) from exc
    raise ValueError("source file must be CSV or Parquet")


def preprocess(frame: pd.DataFrame, schema: FeatureSpace) -> tuple[pd.DataFrame, dict]:
    needed = {schema.id_column, schema.label_column, *schema.signals}
    if schema.group_column:
        needed.add(schema.group_column)
    if missing := needed - set(frame.columns):
        raise ValueError(f"missing columns: {sorted(missing)}")
    if (
        frame[schema.id_column].isna().any()
        or frame[schema.id_column].astype(str).duplicated().any()
    ):
        raise ValueError("candidate IDs must be non-null and unique")
    if frame[schema.label_column].isna().any():
        raise ValueError("labels cannot be missing")
    values = set(frame[schema.label_column].unique())
    if len(values) != 2 or schema.success_value not in values:
        raise ValueError("label must have exactly two values including configured success_value")
    if schema.group_column and frame[schema.group_column].isna().any():
        raise ValueError("groups cannot be missing")
    result = pd.DataFrame(
        {
            "_id": frame[schema.id_column].astype(str),
            "_label": (frame[schema.label_column] == schema.success_value).astype(int),
            "_group": frame[schema.group_column].astype(str)
            if schema.group_column
            else "ungrouped",
        }
    )
    keep = pd.Series(True, index=frame.index)
    missing_counts = {}
    for name, signal in schema.signals.items():
        original = frame[name]
        numeric = pd.to_numeric(original, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if (original.notna() & numeric.isna()).any():
            raise ValueError(f"signal {name!r} contains non-numeric or infinite values")
        missing_counts[name] = int(numeric.isna().sum())
        if signal.missing.policy == "error" and numeric.isna().any():
            raise ValueError(f"signal {name!r} has missing values")
        if signal.missing.policy == "drop":
            keep &= numeric.notna()
        if signal.missing.policy == "constant":
            numeric = numeric.fillna(signal.missing.value)
        result[name] = numeric
    result = result.loc[keep].sort_values("_id").reset_index(drop=True)
    return result, {"rows_in": len(frame), "rows_out": len(result), "missing": missing_counts}
