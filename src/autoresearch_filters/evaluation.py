"""Fixed ranking metrics, cross-validation folds, and comparison against the baseline."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from .config import Config, Protocol, Split
from .rules import Rule, score

Metrics = dict[str, float | None]


def measure(y: np.ndarray, scores: np.ndarray, ids: np.ndarray, top_k: list[int]) -> Metrics:
    """ROC-AUC, PR-AUC and precision@K. AUCs are None when only one class is present."""
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    if len(y) == 0 or len(y) != len(scores) or not np.isfinite(scores).all():
        raise ValueError("metrics require nonempty, aligned labels and finite scores")
    both = 0 < y.sum() < len(y)
    out: Metrics = {
        "roc_auc": float(roc_auc_score(y, scores)) if both else None,
        "pr_auc": float(average_precision_score(y, scores)) if both else None,
    }
    # A stable ID breaks ties; neither row order nor labels resolve a tied score.
    ranked = np.lexsort((np.asarray(ids).astype(str), -scores))
    for k in top_k:
        out[f"precision@{k}"] = float(y[ranked[: min(k, len(y))]].mean())
    return out


def folds(frame: pd.DataFrame, split: Split) -> list[tuple[str, np.ndarray]]:
    """Validation folds as (label, row positions). Nothing is fitted on the other rows."""
    if split.cv == "logo":
        return [(g, np.flatnonzero(frame._group == g)) for g in sorted(frame._group.unique())]
    if frame._label.value_counts().min() < split.folds:
        raise ValueError("not enough positives/negatives for stratified CV")
    result = []
    for repeat in range(split.repeats):
        splitter = StratifiedKFold(
            split.folds, shuffle=True, random_state=split.seed + 100 + repeat
        )
        for fold, (_, val) in enumerate(splitter.split(frame, frame._label)):
            result.append((f"r{repeat}f{fold}", val))
    return result


def cross_validate(frame: pd.DataFrame, rule: Rule, config: Config) -> dict:
    """Score once, then macro-average the metrics over validation folds."""
    scores = score(rule, frame, config)
    y, ids = frame._label.to_numpy(), frame._id.to_numpy()
    per_fold = {
        label: measure(y[idx], scores[idx], ids[idx], config.protocol.top_k)
        for label, idx in folds(frame, config.split)
    }

    def column(key: str) -> list[float]:
        return [m[key] for m in per_fold.values() if m[key] is not None]

    keys = next(iter(per_fold.values())).keys()
    return {
        "metrics": {k: float(np.mean(column(k))) if column(k) else None for k in keys},
        "fold_sd": {
            k: float(np.std(column(k), ddof=1)) if len(column(k)) > 1 else None for k in keys
        },
        "folds": per_fold,
    }


def compare(candidate: dict, baseline: dict, protocol: Protocol) -> dict:
    """Deltas against the baseline on the same folds, broken guards, and a plain verdict.

    `noise` is the standard error of the per-fold difference in the primary metric.
    It is a rough yardstick (folds are few and not independent), not a significance test.
    """
    cand, base = candidate["metrics"], baseline["metrics"]
    delta = {k: None if cand[k] is None or base[k] is None else cand[k] - base[k] for k in base}
    broken = [k for k, d in delta.items() if d is None or d < -protocol.guard_tolerance]
    primary = protocol.primary_metric
    paired = [
        candidate["folds"][f][primary] - baseline["folds"][f][primary]
        for f in baseline["folds"]
        if candidate["folds"][f][primary] is not None and baseline["folds"][f][primary] is not None
    ]
    noise = float(np.std(paired, ddof=1) / np.sqrt(len(paired))) if len(paired) > 1 else None
    gain = delta[primary]
    if broken:
        verdict = "guard-broken"
    elif gain is not None and gain > 2 * (noise or 0) and gain > 0:
        verdict = "better"
    elif gain is not None and gain < -2 * (noise or 0) and gain < 0:
        verdict = "worse"
    else:
        verdict = "within-noise"
    return {"delta": delta, "noise": noise, "guards_broken": broken, "verdict": verdict}
