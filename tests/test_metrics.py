import numpy as np
import pytest

from autoresearch_filters.config import Protocol
from autoresearch_filters.metrics import aggregate, measure


def test_known_ranking_and_prevalence():
    protocol = Protocol(top_k=[1, 2, 9], max_fpr=0.5, target_prevalence=0.25)
    result = measure(
        np.array([0, 0, 1, 1]),
        np.array([0.1, 0.4, 0.35, 0.8]),
        np.array(["a", "b", "c", "d"]),
        protocol,
        10,
    )
    assert result["roc_auc"] == 0.75
    assert result["balanced_roc_auc"] == 0.75
    assert result["pr_auc"] == pytest.approx(5 / 6)
    assert result["partial_auc"] == pytest.approx(2 / 3)
    assert result["success@2"] == 1
    assert result["precision@2"] == 0.5
    assert result["recall@2"] == 0.5
    assert result["effective_k@9"] == 4
    assert result["success@9"] == 2
    assert result["matched_pr_auc"] == pytest.approx(0.7)
    assert result["matched_roc_auc"] == result["roc_auc"]


def test_ties_use_ids_and_undefined_metrics_are_visible():
    y, score, ids = np.array([0, 1, 1, 0]), np.ones(4), np.array(["b", "a", "d", "c"])
    protocol = Protocol(top_k=[1])
    first = measure(y, score, ids, protocol, 3)
    order = np.array([3, 2, 1, 0])
    assert first == measure(y[order], score[order], ids[order], protocol, 3)
    assert first["success@1"] == 1
    undefined = measure(np.zeros(4), score, ids, protocol, 3)
    assert undefined["roc_auc"] is None
    assert undefined["recall@1"] is None
    summary = aggregate([first, undefined])
    assert summary["roc_auc"]["valid"] == 1
    assert summary["roc_auc"]["total"] == 2


def test_balanced_sampling_reproducible():
    y = np.array([1] * 7 + [0] * 40)
    score = np.random.default_rng(4).uniform(size=len(y))
    ids = np.arange(len(y)).astype(str)
    assert measure(y, score, ids, Protocol(), 42) == measure(y, score, ids, Protocol(), 42)
