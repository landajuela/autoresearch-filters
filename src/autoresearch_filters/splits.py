"""All partitions are generated once, using stable IDs, and persisted by prepare."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GroupShuffleSplit,
    LeaveOneGroupOut,
    StratifiedKFold,
    train_test_split,
)

from .config import SplitConfig


def holdout_indices(frame: pd.DataFrame, config: SplitConfig) -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(len(frame))
    if config.holdout == "random":
        return train_test_split(
            idx, test_size=config.holdout_fraction, stratify=frame._label, random_state=config.seed
        )
    groups = frame._group.astype(str)
    if config.holdout_groups:
        missing = set(config.holdout_groups) - set(groups)
        if missing:
            raise ValueError(f"unknown holdout groups: {missing}")
        mask = groups.isin(config.holdout_groups).to_numpy()
        if mask.all():
            raise ValueError("holdout consumes all groups")
        return idx[~mask], idx[mask]
    splitter = GroupShuffleSplit(
        n_splits=1, test_size=config.holdout_fraction, random_state=config.seed
    )
    return next(splitter.split(idx, groups=groups))


def verification_indices(frame: pd.DataFrame, config: SplitConfig) -> tuple[np.ndarray, np.ndarray]:
    if config.verification == "group":
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=config.seed + 1)
        return next(splitter.split(frame, groups=frame._group))
    # Stratification splits both positive and negative rows into disjoint halves.
    return train_test_split(
        np.arange(len(frame)), test_size=0.5, stratify=frame._label, random_state=config.seed + 1
    )


def cv_partitions(frame: pd.DataFrame, config: SplitConfig) -> list[dict]:
    partitions = []
    for repeat in range(config.repeats):
        seed = config.seed + 100 + repeat
        if config.dev == "logo":
            splitter = LeaveOneGroupOut()
        elif config.dev == "group":
            # Randomly permuted group names make GroupKFold re-splits work on sklearn >=1.5.
            unique = np.unique(frame._group)
            shuffled = np.random.default_rng(seed).permutation(unique)
            remap = {g: i for i, g in enumerate(shuffled)}
            groups = frame._group.map(remap).to_numpy()
            # Assign shuffled groups round-robin: balanced group count, not row count.
            if len(unique) < config.folds:
                raise ValueError("not enough groups for requested group folds")
            for fold in range(config.folds):
                val = np.flatnonzero(groups % config.folds == fold)
                train = np.flatnonzero(groups % config.folds != fold)
                partitions.append(_partition(frame, train, val, repeat, fold, seed))
            continue
        else:
            if frame._label.value_counts().min() < config.folds:
                raise ValueError("not enough positives/negatives for stratified CV")
            splitter = StratifiedKFold(config.folds, shuffle=True, random_state=seed)
        group_values = frame._group if config.dev == "logo" else None
        for fold, (train, val) in enumerate(splitter.split(frame, frame._label, group_values)):
            partitions.append(_partition(frame, train, val, repeat, fold, seed))
    return partitions


def _partition(frame, train, val, repeat, fold, seed) -> dict:
    return {
        "repeat": repeat,
        "fold": fold,
        "seed": seed,
        "train_ids": frame.iloc[train]._id.tolist(),
        "validation_ids": frame.iloc[val]._id.tolist(),
    }
