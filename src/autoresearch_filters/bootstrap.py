"""Authoring helpers: get a table, and then an idea, into the loop without writing JSON.

Everything here is label-free except counting the two outcome classes: directions come
from flags or the column name, ranges from the observed bounds. Nothing is chosen by
looking at which columns predict the outcome, because that choice would be fitting.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd

from .config import load_config
from .data import preprocess, read_table
from .rules import load_rule

# A measured outcome must never become a signal, so these names are skipped by default.
OUTCOME_WORDS = (
    "measured",
    "observed",
    "experimental",
    "experiment",
    "assay",
    "outcome",
    "label",
    "truth",
    "binder",
    "binding",
    "hit",
    "active",
    "activity",
    "success",
    "response",
    "affinity",
    "kd",
    "ki",
    "ic50",
    "ec50",
    "titer",
    "titre",
    "potency",
    "validated",
)
# ... unless the name also says the number was computed rather than measured.
COMPUTED_WORDS = (
    "predicted",
    "pred",
    "prediction",
    "calc",
    "calculated",
    "computed",
    "estimated",
    "expected",
    "insilico",
    "silico",
    "sim",
    "simulated",
    "model",
    "score",
    "docking",
    "dock",
    "prior",
    "feature",
)
# Names that usually mean a smaller value is better. Every guess is printed for review:
# a negated score is the trap, since "negative_error" matches "error" but wants higher.
LOWER_WORDS = (
    "rmsd",
    "rmse",
    "mae",
    "error",
    "err",
    "deviation",
    "distance",
    "dist",
    "loss",
    "energy",
    "strain",
    "clash",
    "penalty",
    "cost",
    "violation",
    "perplexity",
    "pvalue",
    "fdr",
    "risk",
    "ic50",
    "ec50",
    "kd",
    "ki",
    "variance",
)
TRUTHY = ("true", "yes", "y", "1", "hit", "binder", "success", "active", "positive", "pass")


def _tokens(column: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", str(column).lower()) if token]


def _matches(column: str, words: Iterable[str]) -> bool:
    tokens = _tokens(column)
    return any(
        word in tokens or (len(word) >= 4 and any(word in token for token in tokens))
        for word in words
    )


def _is_measured(column: str) -> bool:
    """A name that says measured outcome and does not say computed."""
    return _matches(column, OUTCOME_WORDS) and not _matches(column, COMPUTED_WORDS)


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    if not slug:
        raise ValueError(f"cannot make a config name from {text!r}; pass --name")
    return slug


def _scalar(value: object) -> str | int | bool:
    """A JSON-safe copy of a pandas/numpy label value."""
    native = value.item() if hasattr(value, "item") else value
    if isinstance(native, bool | int | str):
        return native
    if isinstance(native, float) and native.is_integer():
        return int(native)
    return str(native)


def choose_label(frame: pd.DataFrame, requested: str) -> str:
    """The experimental outcome: the requested column, or the one binary column."""
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"no column named {requested!r}; columns are {list(frame.columns)}")
        column = requested
    else:
        binary = [c for c in frame.columns if frame[c].dropna().nunique() == 2]
        named = [c for c in binary if _matches(c, OUTCOME_WORDS)]
        if len(named) == 1:
            column = named[0]
        elif binary and frame.columns[-1] in binary:
            column = frame.columns[-1]  # the convention: outcome last
        elif len(binary) == 1:
            column = binary[0]
        elif binary:
            raise ValueError(f"several columns could be the outcome: {binary}; pass --label")
        else:
            raise ValueError(
                "no column has exactly two distinct values; the outcome must be binary "
                "(0/1, True/False, hit/miss). Threshold it yourself and say so in a note"
            )
    series = frame[column]
    if series.isna().any():
        raise ValueError(f"outcome column {column!r} has missing values; they cannot be guessed")
    if series.nunique() != 2:
        raise ValueError(
            f"outcome column {column!r} has {series.nunique()} distinct values, not 2; "
            "the harness ranks against a binary outcome"
        )
    return column


def choose_success(series: pd.Series, requested: str) -> str | int | bool:
    """Which of the two outcome values counts as a success."""
    values = list(pd.unique(series))
    if requested:
        matched = [v for v in values if str(v) == requested]
        if not matched:
            raise ValueError(f"--success {requested!r} is not one of {values}")
        return _scalar(matched[0])
    truthy = [v for v in values if str(v).strip().lower() in TRUTHY]
    if len(truthy) == 1:
        return _scalar(truthy[0])
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
        return _scalar(max(values))
    raise ValueError(f"cannot tell which of {values} means success; pass --success VALUE")


def choose_signals(
    frame: pd.DataFrame, reserved: Sequence[str], requested: Sequence[str]
) -> tuple[list[str], dict[str, str]]:
    """Numeric candidate columns, plus the reason each other column was left out."""
    skipped: dict[str, str] = {}
    kept: list[str] = []
    for column in frame.columns:
        if column in reserved:
            skipped[column] = "outcome, ID or group column"
            continue
        if requested and column not in requested:
            skipped[column] = "not listed in --signals"
            continue
        values = frame[column]
        numeric = pd.to_numeric(values, errors="coerce")
        if (values.notna() & numeric.isna()).any() or numeric.notna().sum() == 0:
            skipped[column] = "not numeric"
            continue
        if numeric.dropna().nunique() < 2:
            skipped[column] = "same value in every row"
            continue
        if not requested and _is_measured(column):
            skipped[column] = "looks like a measured outcome; add it by hand if it is computed"
            continue
        kept.append(column)
    if missing := [c for c in requested if c not in frame.columns]:
        raise ValueError(f"--signals names columns that are not in the table: {missing}")
    if not kept:
        raise ValueError(f"no usable signal columns found; skipped: {skipped}")
    return kept, skipped


def choose_direction(column: str, lower: Sequence[str], higher: Sequence[str]) -> tuple[str, str]:
    """The declared direction and where it came from. A direction is a claim, not a fit."""
    if column in lower and column in higher:
        raise ValueError(f"{column!r} is in both --lower and --higher")
    if column in lower:
        return "lower_is_better", "--lower"
    if column in higher:
        return "higher_is_better", "--higher"
    if _matches(column, LOWER_WORDS):
        return "lower_is_better", "guessed from the name: CHECK IT"
    return "higher_is_better", "default: CHECK IT"


def choose_range(values: pd.Series) -> list[float]:
    """Observed bounds, rounded outward to two significant digits of the span.

    Label-free, and fixed here so that every later rule normalizes the same way. A range
    much wider than the data shrinks a signal's influence inside an additive rule.
    """
    lo, hi = float(values.min()), float(values.max())
    step = 10 ** (math.floor(math.log10(hi - lo)) - 1)
    return [round(math.floor(lo / step) * step, 10), round(math.ceil(hi / step) * step, 10)]


def choose_top_k(rows: int, folds: int) -> list[int]:
    """K values that stay inside a validation fold: holdout 20%, then half for verification."""
    fold = max(int(rows * 0.8 / 2 / max(folds, 1)), 1)
    return [k for k in (5, 10, 20, 50) if k <= max(fold // 3, 1)] or [1]


def draft_rule(
    campaign: Path,
    name: str,
    *,
    why: str,
    signals: Sequence[str] = (),
    weights: Sequence[float] = (),
    parent: str = "",
    product: bool = False,
    root: Path = Path(),
    force: bool = False,
) -> dict:
    """Write rules/NAME.json for one idea: chosen signals, a parent, and a hypothesis."""
    data = campaign / "data"
    if not (data / "config.json").exists():
        raise ValueError(f"{campaign} is not a prepared campaign; run `filters prepare` first")
    config = load_config(data / "config.json")
    if not why.strip():
        raise ValueError("--why is the hypothesis; say what changes and why it should help")
    chosen = list(signals) or list(config.signals)
    if unknown := [s for s in chosen if s not in config.signals]:
        raise ValueError(f"unknown signals {unknown}; this dataset has {list(config.signals)}")
    if len(set(chosen)) != len(chosen):
        raise ValueError(f"a signal is listed twice: {chosen}")
    numbers = list(weights) or [1.0] * len(chosen)
    if len(numbers) != len(chosen):
        raise ValueError(f"{len(numbers)} weights for {len(chosen)} signals")
    key, field = ("factors", "exponent") if product else ("terms", "weight")
    rule = {
        "name": _slug(name),
        "parent": parent or json.loads((data / "baseline.json").read_text())["name"],
        "hypothesis": why.strip(),
        "expression": {
            "kind": "product" if product else "additive",
            key: [{"signal": s, field: w} for s, w in zip(chosen, numbers, strict=True)],
        },
    }
    path = root / "rules" / f"{rule['name']}.json"
    _write(path, rule, force)
    try:
        return {"path": path, "rule": load_rule(path), "config": config}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write(path: Path, value: dict, force: bool) -> None:
    if path.exists() and not force:
        raise ValueError(f"{path} already exists; pass --name NAME or --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def initialise(
    data: Path,
    *,
    label: str = "",
    success: str = "",
    id_column: str = "",
    group: str = "",
    signals: Sequence[str] = (),
    lower: Sequence[str] = (),
    higher: Sequence[str] = (),
    name: str = "",
    baseline_signal: str = "",
    root: Path = Path(),
    force: bool = False,
) -> dict:
    """Write configs/NAME.json and rules/NAME-baseline.json for a results table."""
    frame = read_table(data)
    if frame.empty:
        raise ValueError(f"{data} has no rows")
    label_column = choose_label(frame, label)
    for column, flag in ((id_column, "--id"), (group, "--group")):
        if column and column not in frame.columns:
            raise ValueError(f"{flag} names {column!r}, which is not a column in {data.name}")
    reserved = [c for c in (label_column, id_column, group) if c]
    kept, skipped = choose_signals(frame, reserved, signals)
    for flag, named in (("--lower", lower), ("--higher", higher)):
        if unknown := [c for c in named if c not in kept]:
            raise ValueError(f"{flag} names columns that are not signals: {unknown}")

    chosen = {}
    for column in kept:
        direction, source = choose_direction(column, lower, higher)
        numeric = pd.to_numeric(frame[column], errors="coerce")
        chosen[column] = {
            "spec": {
                "direction": direction,
                "range": choose_range(numeric.dropna()),
                "missing": "drop" if numeric.isna().any() else "error",
            },
            "direction_source": source,
            "missing_rows": int(numeric.isna().sum()),
        }

    folds = frame[group].nunique() if group else 3
    config = {
        "name": _slug(name or data.stem),
        "source": os.path.relpath(data.resolve(), (root / "configs").resolve()),
        "id_column": id_column or None,
        "label_column": label_column,
        "success_value": choose_success(frame[label_column], success),
        "group_column": group or None,
        "signals": {column: value["spec"] for column, value in chosen.items()},
        "split": (
            {"holdout_groups": sorted(frame[group].astype(str).unique())[-1:], "cv": "logo"}
            if group
            else {"holdout_fraction": 0.2, "cv": "random", "folds": 3, "repeats": 5}
        ),
        "protocol": {
            "top_k": choose_top_k(len(frame), folds),
            "primary_metric": "roc_auc",
            "guard_tolerance": 0.01,
        },
    }
    if baseline_signal and baseline_signal not in chosen:
        raise ValueError(f"--baseline-signal {baseline_signal!r} is not one of {kept}")
    terms = [baseline_signal] if baseline_signal else kept
    baseline = {
        "name": f"{config['name']}-baseline",
        "hypothesis": (
            f"Rank candidates by {terms[0]} alone, in its declared direction. "
            "Nothing is fitted; this is only the number every idea must beat."
            if len(terms) == 1
            else f"Rank candidates by the equal-weight mean of all {len(terms)} declared "
            "signals: the naive consensus of every computed column, with nothing fitted. "
            "This is only the number every idea must beat, not a claim that it is good."
        ),
        "expression": {"kind": "additive", "terms": [{"signal": t, "weight": 1} for t in terms]},
    }

    config_path = root / "configs" / f"{config['name']}.json"
    baseline_path = root / "rules" / f"{config['name']}-baseline.json"
    _write(config_path, config, force)
    try:
        _write(baseline_path, baseline, force)
        # Fail here rather than at `prepare`: this validates the config and the whole table.
        usable = preprocess(frame, load_config(config_path))
    except Exception:
        config_path.unlink(missing_ok=True)
        baseline_path.unlink(missing_ok=True)
        raise
    positives = int(usable._label.sum())
    return {
        "config_path": config_path,
        "baseline_path": baseline_path,
        "config": config,
        "signals": chosen,
        "skipped": skipped,
        "rows": len(frame),
        "usable_rows": len(usable),
        "positives": positives,
        "negatives": len(usable) - positives,
        "baseline_terms": terms,
    }
