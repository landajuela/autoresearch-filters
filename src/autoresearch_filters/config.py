"""Strict JSON dataset configuration. Dataset semantics never live in a rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Direction = Literal["higher_is_better", "lower_is_better"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def digest(rule: BaseModel) -> str:
    """Short hash of a rule's formula; its name, hypothesis and JSON formatting do not matter."""
    formula = rule.model_dump(mode="json")["expression"]
    text = json.dumps(formula, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class Signal(StrictModel):
    direction: Direction
    range: tuple[FiniteFloat, FiniteFloat]
    missing: Literal["error", "drop"] = "error"
    description: str = ""

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.range[0] >= self.range[1]:
            raise ValueError("signal range must have lo < hi")
        return self


class Split(StrictModel):
    """Holdout: the named groups, or else a stratified random fraction."""

    holdout_groups: list[str] = Field(default_factory=list)
    holdout_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    cv: Literal["logo", "random"] = "random"
    folds: int = Field(default=3, ge=2)
    repeats: int = Field(default=5, ge=5)
    seed: int = Field(default=1729, ge=0, le=2**31 - 1000)


class Protocol(StrictModel):
    top_k: list[int] = Field(default=[5, 10, 20], min_length=1)
    primary_metric: Literal["roc_auc", "pr_auc"] = "roc_auc"
    guard_tolerance: float = Field(default=0.01, ge=0, lt=1)

    @model_validator(mode="after")
    def check(self) -> Self:
        if any(k < 1 for k in self.top_k) or len(set(self.top_k)) != len(self.top_k):
            raise ValueError("top_k must contain distinct positive integers")
        return self


class Config(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    source: str  # CSV/Parquet path relative to the config file, or a built-in loader name
    id_column: str
    label_column: str
    success_value: str | int | bool
    group_column: str | None = None
    signals: dict[str, Signal] = Field(min_length=1)
    split: Split = Split()
    protocol: Protocol = Protocol()

    @model_validator(mode="after")
    def check(self) -> Self:
        columns = [self.id_column, self.label_column]
        columns += [self.group_column] if self.group_column else []
        if len(set(columns)) != len(columns):
            raise ValueError("ID, label and group columns must be distinct")
        if overlap := {*columns, "_id", "_label", "_group"} & self.signals.keys():
            raise ValueError(f"ID, label and group columns cannot be signals: {sorted(overlap)}")
        if (self.split.cv == "logo" or self.split.holdout_groups) and not self.group_column:
            raise ValueError("group-based splitting requires group_column")
        return self


def load_config(path: Path) -> Config:
    return Config.model_validate_json(path.read_text())
