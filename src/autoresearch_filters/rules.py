"""A closed, deterministic rule language. No eval(), fitting, or Python hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Self

import numpy as np
import pandas as pd
from pydantic import Field, FiniteFloat, TypeAdapter, model_validator

from .config import Direction, FeatureSpace, StrictModel


class Threshold(StrictModel):
    kind: Literal["threshold"] = "threshold"
    signal: str
    op: Literal[">", ">=", "<", "<="]
    value: FiniteFloat


class Junction(StrictModel):
    kind: Literal["all", "any"]
    conditions: list[Condition] = Field(min_length=1, max_length=16)


Condition = Annotated[Threshold | Junction, Field(discriminator="kind")]
Junction.model_rebuild()


class Term(StrictModel):
    signal: str
    clip: tuple[FiniteFloat, FiniteFloat] | None = None
    direction: Direction | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        if self.clip is not None and self.clip[0] >= self.clip[1]:
            raise ValueError("term clip must have lo < hi")
        return self


class WeightedTerm(Term):
    weight: float = Field(default=1, ge=0)


class Factor(Term):
    exponent: float = Field(default=1, gt=0)


class Adjustment(Term):
    weight: FiniteFloat = 1
    center: FiniteFloat = 0


class Hard(StrictModel):
    kind: Literal["hard"] = "hard"
    condition: Condition


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


class Constant(StrictModel):
    kind: Literal["constant"] = "constant"
    value: FiniteFloat


class Gate(StrictModel):
    name: str
    when: Threshold
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=32)
    children: list[Gate] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def check(self) -> Self:
        if not self.adjustments and not self.children:
            raise ValueError("gate needs adjustments or child gates")
        return self


class Gated(StrictModel):
    kind: Literal["gated"] = "gated"
    base: Node
    gates: list[Gate] = Field(min_length=1, max_length=16)


Node = Annotated[Hard | Additive | Product | Constant | Gated, Field(discriminator="kind")]
Gated.model_rebuild()
NODE = TypeAdapter(Node)


class Rule(StrictModel):
    name: str
    hypothesis: str = Field(min_length=1)
    expression: Node

    @model_validator(mode="after")
    def depth_limit(self) -> Self:
        def depth(obj: object) -> int:
            if isinstance(obj, dict):
                return 1 + max((depth(v) for v in obj.values()), default=0)
            if isinstance(obj, list):
                return max((depth(v) for v in obj), default=0)
            return 0

        if depth(self.expression.model_dump()) > 12:
            raise ValueError("rule exceeds the shallow-tree depth limit")
        return self


def load_rule(path: Path) -> Rule:
    return Rule.model_validate_json(path.read_text())


def referenced_signals(rule: Rule) -> set[str]:
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


def validate_rule(rule: Rule, schema: FeatureSpace) -> None:
    unknown = referenced_signals(rule) - schema.signals.keys()
    if unknown:
        raise ValueError(f"rule references forbidden/unknown signals: {sorted(unknown)}")

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            if obj.get("direction") and obj["direction"] != schema.signals[obj["signal"]].direction:
                raise ValueError(f"direction for {obj['signal']} contradicts dataset schema")
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(rule.model_dump())


def normalize(values: np.ndarray, lo: float, hi: float, direction: Direction) -> np.ndarray:
    result = np.clip((values - lo) / (hi - lo), 0, 1)
    return result if direction == "higher_is_better" else 1 - result


def term_values(term: Term, frame: pd.DataFrame, schema: FeatureSpace) -> np.ndarray:
    signal = schema.signals[term.signal]
    lo, hi = term.clip or signal.range
    return normalize(frame[term.signal].to_numpy(float), lo, hi, signal.direction)


def condition_values(condition: Condition, frame: pd.DataFrame) -> np.ndarray:
    if isinstance(condition, Threshold):
        value = frame[condition.signal].to_numpy(float)
        operations = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal}
        return operations[condition.op](value, condition.value)
    values = [condition_values(c, frame) for c in condition.conditions]
    return (np.logical_and if condition.kind == "all" else np.logical_or).reduce(values)


def score(rule: Rule, frame: pd.DataFrame, schema: FeatureSpace) -> np.ndarray:
    validate_rule(rule, schema)

    def gate_value(gate: Gate) -> np.ndarray:
        adjustment = np.zeros(len(frame))
        for term in gate.adjustments:
            adjustment += term.weight * (term_values(term, frame, schema) - term.center)
        for child in gate.children:
            adjustment += gate_value(child)
        return condition_values(gate.when, frame) * adjustment

    def evaluate(node: Node) -> np.ndarray:
        if isinstance(node, Constant):
            return np.full(len(frame), node.value)
        if isinstance(node, Hard):
            return condition_values(node.condition, frame).astype(float)
        if isinstance(node, Additive):
            return sum(t.weight * term_values(t, frame, schema) for t in node.terms) / sum(
                t.weight for t in node.terms
            )
        if isinstance(node, Product):
            return np.prod(
                [term_values(t, frame, schema) ** t.exponent for t in node.factors], axis=0
            )
        return evaluate(node.base) + sum(gate_value(g) for g in node.gates)

    result = evaluate(rule.expression)
    if not np.isfinite(result).all():
        raise ValueError("rule produced non-finite scores")
    return result


def pretty(rule: Rule, schema: FeatureSpace) -> str:
    """Canonical pseudo-formula; explicit directions make sign mistakes visible."""
    validate_rule(rule, schema)

    def term(t: Term) -> str:
        signal = schema.signals[t.signal]
        lo, hi = t.clip or signal.range
        return f"n({json.dumps(t.signal)}, {lo:g}..{hi:g}, {signal.direction})"

    def condition(c: Condition) -> str:
        if isinstance(c, Threshold):
            return f"{json.dumps(c.signal)} {c.op} {c.value:g}"
        return "(" + f" {c.kind.upper()} ".join(condition(x) for x in c.conditions) + ")"

    def gate(g: Gate) -> str:
        parts = [f"{t.weight:g} * ({term(t)} - {t.center:g})" for t in g.adjustments]
        parts.extend(gate(child) for child in g.children)
        return f"1[{condition(g.when)}] * ({' + '.join(parts)})"

    def expr(node: Node) -> str:
        if isinstance(node, Constant):
            return f"{node.value:g}"
        if isinstance(node, Hard):
            return f"1[{condition(node.condition)}]"
        if isinstance(node, Additive):
            return (
                "("
                + " + ".join(f"{t.weight:g} * {term(t)}" for t in node.terms)
                + (f") / {sum(t.weight for t in node.terms):g}")
            )
        if isinstance(node, Product):
            return " * ".join(f"{term(t)}^{t.exponent:g}" for t in node.factors)
        return f"({expr(node.base)}) + " + " + ".join(gate(g) for g in node.gates)

    return f"score = {expr(rule.expression)}"
