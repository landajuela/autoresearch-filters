"""Ranking metrics, including shallow-depth screening and explicit undefined values."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from .config import Protocol


def measure(
    y: np.ndarray, scores: np.ndarray, ids: np.ndarray, protocol: Protocol, seed: int
) -> dict[str, float | None]:
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    if len(y) == 0 or len(y) != len(scores) or not np.isfinite(scores).all():
        raise ValueError("metrics require nonempty, aligned labels and finite scores")
    if not set(y).issubset({0, 1}):
        raise ValueError("labels must be binary")
    positive, negative = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    both = bool(len(positive) and len(negative))
    out: dict[str, float | None] = {
        "n": float(len(y)),
        "prevalence": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, scores)) if both else None,
        "pr_auc": float(average_precision_score(y, scores)) if both else None,
        "partial_auc": float(roc_auc_score(y, scores, max_fpr=protocol.max_fpr)) if both else None,
        "balanced_roc_auc": None,
    }
    if both:
        rng = np.random.default_rng(seed)
        size = min(len(positive), len(negative))
        chosen = np.r_[rng.choice(positive, size, False), rng.choice(negative, size, False)]
        out["balanced_roc_auc"] = float(roc_auc_score(y[chosen], scores[chosen]))
    # A stable ID breaks ties; neither row order nor labels resolve a tied score.
    ranked = np.lexsort((np.asarray(ids).astype(str), -scores))
    for k in protocol.top_k:
        used = min(k, len(y))
        hits = int(y[ranked[:used]].sum())
        out[f"success@{k}"] = float(hits)
        out[f"precision@{k}"] = hits / used
        out[f"recall@{k}"] = hits / len(positive) if len(positive) else None
        out[f"effective_k@{k}"] = float(used)
    if protocol.target_prevalence is not None:
        for key in ("roc_auc", "pr_auc", "partial_auc"):
            out[f"matched_{key}"] = None
        if both:
            p = protocol.target_prevalence
            weight = np.where(y == 1, 1.0, len(positive) * (1 - p) / (p * len(negative)))
            out["matched_roc_auc"] = float(roc_auc_score(y, scores, sample_weight=weight))
            out["matched_pr_auc"] = float(average_precision_score(y, scores, sample_weight=weight))
            out["matched_partial_auc"] = float(
                roc_auc_score(y, scores, sample_weight=weight, max_fpr=protocol.max_fpr)
            )
    return out


def aggregate(rows: list[dict[str, float | None]]) -> dict[str, dict]:
    if not rows:
        raise ValueError("cannot aggregate zero metric records")
    out = {}
    for key in rows[0]:
        values = [r[key] for r in rows if r.get(key) is not None]
        out[key] = {
            "mean": float(np.mean(values)) if values else None,
            "std": float(np.std(values, ddof=1)) if len(values) > 1 else (0.0 if values else None),
            "valid": len(values),
            "total": len(rows),
        }
    return out
