"""A closed, deterministic rule language. No eval(), fitting, or Python hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Self

import numpy as np
import pandas as pd
from pydantic import (
    Field,
    FiniteFloat,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .config import Config, StrictModel

OPERATIONS = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}
MAX_TREE_DEPTH = 16
MAX_TREE_NODES = 255


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


class Constant(StrictModel):
    kind: Literal["constant"] = "constant"
    value: FiniteFloat


class Conditional(StrictModel):
    kind: Literal["conditional"] = "conditional"
    when: Threshold
    then: Expression
    else_branch: Expression = Field(alias="else")

    @model_serializer(mode="wrap")
    def serialize_branches(self, handler: SerializerFunctionWrapHandler):
        # Journals, digests and frozen rules use model_dump without by_alias=True.
        # Always retain the loadable JSON spelling, including in nested branches.
        result = handler(self)
        if "else_branch" in result:
            result["else"] = result.pop("else_branch")
        return result


Expression = Annotated[
    Additive | Product | Gated | Constant | Conditional, Field(discriminator="kind")
]
Conditional.model_rebuild()


class Rule(StrictModel):
    name: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    parent: str | None = None  # name of the rule this idea was derived from
    expression: Expression

    @model_validator(mode="after")
    def bounded_tree(self) -> Self:
        pending = [(self.expression, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if count > MAX_TREE_NODES:
                raise ValueError(f"expression tree exceeds {MAX_TREE_NODES} nodes")
            if isinstance(node, Conditional):
                if depth >= MAX_TREE_DEPTH:
                    raise ValueError(f"conditional nesting exceeds {MAX_TREE_DEPTH} levels")
                pending.extend([(node.then, depth + 1), (node.else_branch, depth + 1)])
        return self


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

    def base(node: Additive | Product, part: pd.DataFrame) -> np.ndarray:
        if isinstance(node, Additive):
            total = sum(t.weight for t in node.terms)
            return sum(t.weight * normalized(t.signal, part, config) for t in node.terms) / total
        return np.prod(
            [normalized(f.signal, part, config) ** f.exponent for f in node.factors], axis=0
        )

    def gate(g: Gate, part: pd.DataFrame) -> np.ndarray:
        active = OPERATIONS[g.when.op](part[g.when.signal].to_numpy(float), g.when.value)
        return active * sum(
            a.weight * (normalized(a.signal, part, config) - a.center) for a in g.adjustments
        )

    def evaluate(node: Expression, part: pd.DataFrame) -> np.ndarray:
        if isinstance(node, Conditional):
            active = OPERATIONS[node.when.op](
                part[node.when.signal].to_numpy(float), node.when.value
            )
            result = np.empty(len(part), dtype=float)
            # Partition by position: duplicate/nonconsecutive DataFrame indices are valid.
            # Do not compute an unselected branch (np.where would evaluate both).
            if active.any():
                result[active] = evaluate(node.then, part.iloc[np.flatnonzero(active)])
            if (~active).any():
                result[~active] = evaluate(node.else_branch, part.iloc[np.flatnonzero(~active)])
            return result
        if isinstance(node, Constant):
            return np.full(len(part), node.value, dtype=float)
        if isinstance(node, Gated):
            return base(node.base, part) + sum(gate(g, part) for g in node.gates)
        return base(node, part)

    result = evaluate(rule.expression, frame)
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

    def expression(node: Expression) -> str:
        if isinstance(node, Conditional):
            condition = f"{json.dumps(node.when.signal)} {node.when.op} {node.when.value:g}"
            return (
                f"if [{condition}] then ({expression(node.then)}) "
                f"else ({expression(node.else_branch)})"
            )
        if isinstance(node, Constant):
            return f"{node.value:g}"
        if isinstance(node, Gated):
            return f"({base(node.base)}) + " + " + ".join(gate(g) for g in node.gates)
        return base(node)

    return f"score = {expression(rule.expression)}"
