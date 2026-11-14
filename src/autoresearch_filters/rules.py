"""A closed, deterministic rule language. No eval(), fitting, or Python hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Self

import numpy as np
import pandas as pd
from pydantic import Field, FiniteFloat, model_validator

from .config import Config, StrictModel

OPERATIONS = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}


class WeightedTerm(StrictModel):
    signal: str
    weight: float = Field(default=1, ge=0)


class Factor(StrictModel):
    signal: str
    exponent: float = Field(default=1, gt=0)


class Adjustment(StrictModel):
    signal: str
    weight: FiniteFloat = 1
    center: FiniteFloat = 0


class Threshold(StrictModel):
    signal: str
    op: Literal[">", ">=", "<", "<="]
    value: FiniteFloat


class Additive(StrictModel):
    kind: Literal["additive"] = "additive"
    terms: list[WeightedTerm] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def check(self) -> Self:
        if sum(t.weight for t in self.terms) <= 0:
            raise ValueError("additive weights must have a positive sum")
        return self


class Product(StrictModel):
    kind: Literal["product"] = "product"
    factors: list[Factor] = Field(min_length=1, max_length=32)


class Gate(StrictModel):
    name: str
    when: Threshold
    adjustments: list[Adjustment] = Field(min_length=1, max_length=32)


class Gated(StrictModel):
    kind: Literal["gated"] = "gated"
    base: Annotated[Additive | Product, Field(discriminator="kind")]
    gates: list[Gate] = Field(min_length=1, max_length=16)


class Rule(StrictModel):
    name: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    parent: str | None = None  # name of the rule this idea was derived from
    expression: Annotated[Additive | Product | Gated, Field(discriminator="kind")]


def load_rule(path: Path) -> Rule:
    return Rule.model_validate_json(path.read_text())


def signals(rule: Rule) -> set[str]:
    found: set[str] = set()

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            if "signal" in obj:
                found.add(obj["signal"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(rule.model_dump())
    return found


def validate_rule(rule: Rule, config: Config) -> None:
    if unknown := signals(rule) - config.signals.keys():
        raise ValueError(f"rule references forbidden/unknown signals: {sorted(unknown)}")


def normalized(signal: str, frame: pd.DataFrame, config: Config) -> np.ndarray:
    """Clip to the declared range, scale to [0, 1], and orient so higher is better."""
    spec = config.signals[signal]
    lo, hi = spec.range
    result = np.clip((frame[signal].to_numpy(float) - lo) / (hi - lo), 0, 1)
    return result if spec.direction == "higher_is_better" else 1 - result


def score(rule: Rule, frame: pd.DataFrame, config: Config) -> np.ndarray:
    validate_rule(rule, config)

    def n(signal: str) -> np.ndarray:
        return normalized(signal, frame, config)

    def base(node: Additive | Product) -> np.ndarray:
        if isinstance(node, Additive):
            total = sum(t.weight for t in node.terms)
            return sum(t.weight * n(t.signal) for t in node.terms) / total
        return np.prod([n(f.signal) ** f.exponent for f in node.factors], axis=0)

    def gate(g: Gate) -> np.ndarray:
        active = OPERATIONS[g.when.op](frame[g.when.signal].to_numpy(float), g.when.value)
        return active * sum(a.weight * (n(a.signal) - a.center) for a in g.adjustments)

    node = rule.expression
    if isinstance(node, Gated):
        result = base(node.base) + sum(gate(g) for g in node.gates)
    else:
        result = base(node)
    if not np.isfinite(result).all():
        raise ValueError("rule produced non-finite scores")
    return result


def pretty(rule: Rule, config: Config) -> str:
    """Readable pseudo-formula; explicit ranges and directions make sign mistakes visible."""
    validate_rule(rule, config)

    def n(signal: str) -> str:
        spec = config.signals[signal]
        return f"n({json.dumps(signal)}, {spec.range[0]:g}..{spec.range[1]:g}, {spec.direction})"

    def base(node: Additive | Product) -> str:
        if isinstance(node, Additive):
            terms = " + ".join(f"{t.weight:g} * {n(t.signal)}" for t in node.terms)
            return f"({terms}) / {sum(t.weight for t in node.terms):g}"
        return " * ".join(f"{n(f.signal)}^{f.exponent:g}" for f in node.factors)

    def gate(g: Gate) -> str:
        parts = " + ".join(f"{a.weight:g} * ({n(a.signal)} - {a.center:g})" for a in g.adjustments)
        return f"1[{json.dumps(g.when.signal)} {g.when.op} {g.when.value:g}] * ({parts})"

    node = rule.expression
    if isinstance(node, Gated):
        return f"score = ({base(node.base)}) + " + " + ".join(gate(g) for g in node.gates)
    return f"score = {base(node)}"
