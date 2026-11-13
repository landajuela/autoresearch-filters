"""Strict JSON configuration. Dataset semantics never live in a rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Direction = Literal["higher_is_better", "lower_is_better"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def digest(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class Missing(StrictModel):
    policy: Literal["error", "drop", "constant"] = "error"
    value: FiniteFloat | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        if (self.policy == "constant") != (self.value is not None):
            raise ValueError("missing.value is required only for policy='constant'")
        return self


class Signal(StrictModel):
    direction: Direction
    range: tuple[FiniteFloat, FiniteFloat]
    missing: Missing = Missing()
    units: str | None = None
    description: str = ""
    oracle: bool = True
    expected_positive_auc: bool = True

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.range[0] >= self.range[1]:
            raise ValueError("signal range must have lo < hi")
        return self


class FeatureSpace(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    id_column: str
    label_column: str
    success_value: str | int | bool
    group_column: str | None = None
    signals: dict[str, Signal] = Field(min_length=1)
    exclude_columns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check(self) -> Self:
        forbidden = set(self.exclude_columns) | {
            self.label_column,
            self.id_column,
            "_id",
            "_label",
            "_group",
        }
        if self.group_column:
            forbidden.add(self.group_column)
        overlap = forbidden & self.signals.keys()
        if overlap:
            raise ValueError(f"excluded, label, group or ID columns cannot be signals: {overlap}")
        if any(not s.oracle for s in self.signals.values()):
            raise ValueError("rule-space signals must be computed oracles, never measured outcomes")
        if len({self.id_column, self.label_column, self.group_column} - {None}) != (
            3 if self.group_column else 2
        ):
            raise ValueError("ID, label and group columns must be distinct")
        return self


class FileSource(StrictModel):
    kind: Literal["file"] = "file"
    path: str


class LoaderSource(StrictModel):
    kind: Literal["loader"] = "loader"
    hook: str = Field(pattern=r"^[\w.]+:[\w]+$")
    kwargs: dict = Field(default_factory=dict)


Source = Annotated[FileSource | LoaderSource, Field(discriminator="kind")]


class SplitConfig(StrictModel):
    holdout: Literal["random", "group", "external"] = "random"
    holdout_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    holdout_groups: list[str] = Field(default_factory=list)
    external: FileSource | None = None
    dev: Literal["random", "logo", "group"] = "random"
    folds: int = Field(default=3, ge=2)
    repeats: int = Field(default=5, ge=5)
    seed: int = Field(default=1729, ge=0, le=2**31 - 10000)
    verification: Literal["split_positive", "group"] = "split_positive"

    @model_validator(mode="after")
    def check(self) -> Self:
        if (self.holdout == "external") != (self.external is not None):
            raise ValueError("external holdout strategy requires an external file source")
        if self.holdout_groups and self.holdout != "group":
            raise ValueError("holdout_groups requires holdout='group'")
        if len(set(self.holdout_groups)) != len(self.holdout_groups):
            raise ValueError("holdout_groups must be unique")
        return self


class Protocol(StrictModel):
    top_k: list[int] = Field(default=[5, 10, 20], min_length=1)
    max_fpr: float = Field(default=0.1, gt=0, le=1)
    target_prevalence: float | None = Field(default=None, gt=0, lt=1)
    match_holdout_prevalence: bool = False
    sign_policy: Literal["warn", "error"] = "warn"
    sign_tolerance: float = Field(default=0.02, ge=0, lt=0.5)
    primary_metric: Literal["roc_auc", "pr_auc", "partial_auc"] = "roc_auc"
    guard_tolerance: float = Field(default=0.01, ge=0, lt=1)
    minimum_transfer_gain: float = Field(default=0.0, ge=0, lt=1)
    search_budget: int = Field(default=12, ge=1, le=100)

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.match_holdout_prevalence and self.target_prevalence is not None:
            raise ValueError("choose declared target_prevalence OR match_holdout_prevalence")
        if any(k < 1 for k in self.top_k) or len(set(self.top_k)) != len(self.top_k):
            raise ValueError("top_k must contain distinct positive integers")
        return self


class DatasetConfig(FeatureSpace):
    source: Source
    split: SplitConfig = SplitConfig()
    protocol: Protocol = Protocol()

    @model_validator(mode="after")
    def check_groups(self) -> Self:
        if (
            self.split.holdout == "group"
            or self.split.dev in {"logo", "group"}
            or self.split.verification == "group"
        ) and not self.group_column:
            raise ValueError("group-based splitting requires group_column")
        return self

    def feature_space(self) -> FeatureSpace:
        return FeatureSpace.model_validate(self.model_dump(include=set(FeatureSpace.model_fields)))


def load_config(path: Path) -> DatasetConfig:
    return DatasetConfig.model_validate_json(path.read_text())
