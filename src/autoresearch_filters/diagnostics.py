"""Bounded gate diagnostics on discovery data, never a selection oracle."""

from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from .dev import load_dev, record_base
from .io import write_json
from .rules import Rule, Term, Threshold, condition_values, referenced_signals, term_values


def gate_scan(
    work: Path,
    rule: Rule,
    regime_signal: str,
    thresholds: list[float],
    adjustment_signal: str,
    op: str,
    output: Path,
) -> dict:
    if (work / "transfer/consumed.json").exists():
        raise ValueError("campaign is frozen; no diagnostics after transfer verification")
    if output.exists():
        raise ValueError("run output already exists")
    bundle = load_dev(work)
    if not 1 <= len(thresholds) <= bundle.protocol.search_budget:
        raise ValueError("threshold grid exceeds the fixed diagnostic budget")
    for name in [regime_signal, adjustment_signal]:
        if name not in bundle.schema.signals:
            raise ValueError(f"forbidden/unknown signal: {name}")
    # One diagnostic grid per campaign: broad repeated scans cannot evade the budget.
    write_json(
        work / "gate-scan-consumed.json",
        {
            "regime": regime_signal,
            "adjustment": adjustment_signal,
            "thresholds": thresholds,
        },
        exclusive=True,
    )
    values = term_values(Term(signal=adjustment_signal), bundle.frame, bundle.schema)
    labels = bundle.frame._label.to_numpy()
    overall = float(roc_auc_score(labels, values))
    rows = []
    base_signals = sorted(referenced_signals(rule))
    for threshold in sorted(set(thresholds)):
        condition = Threshold(signal=regime_signal, op=op, value=threshold)
        mask = condition_values(condition, bundle.frame)
        y = labels[mask]
        both = len(np.unique(y)) == 2
        local = float(roc_auc_score(y, values[mask])) if both else None
        correlations = {}
        for signal in base_signals:
            other = term_values(Term(signal=signal), bundle.frame, bundle.schema)[mask]
            correlations[signal] = (
                float(np.corrcoef(values[mask], other)[0, 1])
                if len(y) > 2 and np.std(values[mask]) > 0 and np.std(other) > 0
                else None
            )
        rows.append(
            {
                "threshold": threshold,
                "n": len(y),
                "positives": int(y.sum()),
                "overall_auc": overall,
                "local_auc": local,
                "local_minus_overall": local - overall if local is not None else None,
                "local_correlations_with_base_signals": correlations,
            }
        )
    record = record_base(bundle, "gate-scan", rule)
    record.update(
        {
            "diagnostics": rows,
            "regime_signal": regime_signal,
            "adjustment_signal": adjustment_signal,
            "op": op,
            "selection_eligible": False,
        }
    )
    record["notes"].append(
        "Hypothesis generation only. Inspect support, redundancy and a fine threshold plateau; "
        "no threshold is selected by this command. Local AUC alone is insufficient."
    )
    write_json(output, record, exclusive=True)
    return record
