import numpy as np
import pytest

from autoresearch_filters.config import Protocol
from autoresearch_filters.evaluation import compare, measure


def test_known_ranking():
    result = measure(
        np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8]), np.array(list("abcd")), [1, 2, 9]
    )
    assert result["roc_auc"] == 0.75
    assert result["pr_auc"] == pytest.approx(5 / 6)
    assert result["precision@1"] == 1
    assert result["precision@2"] == 0.5
    assert result["precision@9"] == 0.5  # K larger than the fold uses every row


def test_ties_use_ids_and_undefined_metrics_are_visible():
    y, score, ids = np.array([0, 1, 1, 0]), np.ones(4), np.array(["b", "a", "d", "c"])
    first = measure(y, score, ids, [1])
    order = np.array([3, 2, 1, 0])
    assert first == measure(y[order], score[order], ids[order], [1])
    assert first["precision@1"] == 1
    assert measure(np.zeros(4), score, ids, [1])["roc_auc"] is None
    with pytest.raises(ValueError):
        measure(y, np.array([1, np.nan, 1, 1]), ids, [1])


def result(folds: list[float], precision: float = 0.5) -> dict:
    return {
        "metrics": {"roc_auc": float(np.mean(folds)), "precision@5": precision},
        "folds": {f"f{i}": {"roc_auc": v} for i, v in enumerate(folds)},
    }


def test_compare_verdicts():
    protocol = Protocol(top_k=[5])
    base = result([0.60, 0.70, 0.65])
    steady = compare(result([0.65, 0.75, 0.70]), base, protocol)
    assert steady["verdict"] == "better" and steady["delta"]["roc_auc"] == pytest.approx(0.05)
    assert compare(result([0.90, 0.60, 0.50]), base, protocol)["verdict"] == "within-noise"
    assert compare(result([0.595, 0.695, 0.645]), base, protocol)["verdict"] == "worse"
    broken = compare(result([0.65, 0.75, 0.70], precision=0.4), base, protocol)
    assert broken["verdict"] == "guard-broken" and broken["guards_broken"] == ["precision@5"]
