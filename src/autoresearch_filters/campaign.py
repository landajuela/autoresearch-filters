"""The research loop: prepare, eval, verify once, final once. Every step appends to the journal.

Layout of a campaign directory:

    journal.jsonl                   append-only log of everything that happened (commit this)
    data/config.json                the dataset configuration fixed at prepare time
    data/baseline.json              the rule every idea is compared against
    data/discovery.csv              free to inspect
    data/locked/verification.csv    read once, by `verify`
    data/locked/holdout.csv         read once, by `final`
    data/verify-used.json, data/final-used.json, data/frozen.json   one-use markers and outcome
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from . import journal
from .config import Config, digest, load_config
from .data import load_source, preprocess, read_pile, split
from .evaluation import compare, cross_validate, measure
from .rules import Rule, load_rule, normalized, pretty, score


def _write(path: Path, value: object) -> None:
    """Exclusive create: a second writer fails, which is what makes a marker one-use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def _load(campaign: Path) -> tuple[Config, Rule]:
    data = campaign / "data"
    if not (data / "config.json").exists():
        raise ValueError(f"{campaign} is not a prepared campaign; run `filters prepare` first")
    return load_config(data / "config.json"), load_rule(data / "baseline.json")


def _describe(rule: Rule, config: Config, result: dict) -> dict:
    """Journal fields shared by every row that reports a rule's metrics."""
    return {
        "rule": rule.name,
        "rule_hash": digest(rule),
        "formula": pretty(rule, config),
        "metrics": result["metrics"],
    }


def prepare(config_path: Path, baseline_path: Path, campaign: Path) -> list[dict]:
    """Cut the data into three piles and record the baseline as the number to beat."""
    data = campaign / "data"
    if data.exists() or journal.read(campaign):
        raise ValueError(f"{campaign} already exists; use a new campaign directory")
    config = load_config(config_path)
    baseline = load_rule(baseline_path)
    piles = split(preprocess(load_source(config, config_path.parent), config), config)
    discovery = piles["discovery"]
    result = cross_validate(discovery, baseline, config)  # validates the rule before writing
    for name, part in piles.items():
        path = data / ("discovery.csv" if name == "discovery" else f"locked/{name}.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        part.to_csv(path, index=False)
    _write(data / "config.json", config.model_dump(mode="json"))
    _write(data / "baseline.json", baseline.model_dump(mode="json"))
    # Oriented single-signal AUC on discovery rows: below 0.5 contradicts the declared direction.
    signal_auc = {
        name: float(roc_auc_score(discovery._label, normalized(name, discovery, config)))
        for name in config.signals
    }
    rows = [
        journal.append(
            campaign,
            "prepare",
            dataset=config.name,
            rows={name: len(part) for name, part in piles.items()},
            discovery_positives=int(discovery._label.sum()),
            signal_auc=signal_auc,
            config=config.model_dump(mode="json"),
        ),
        journal.append(
            campaign,
            "eval",
            data="discovery",
            **_describe(baseline, config, result),
            parent=None,
            hypothesis=baseline.hypothesis,
            fold_sd=result["fold_sd"],
            folds=_primary_by_fold(result, config),
            verdict="baseline",
            rule_json=baseline.model_dump(mode="json"),
        ),
    ]
    return rows


def _primary_by_fold(result: dict, config: Config) -> dict:
    return {f: m[config.protocol.primary_metric] for f, m in result["folds"].items()}


def _require_open(campaign: Path) -> None:
    if (campaign / "data/verify-used.json").exists():
        raise ValueError("campaign is frozen after verification; stop searching")


def evaluate(campaign: Path, rule_path: Path) -> dict:
    """Score one idea on discovery CV and append the outcome, good or bad, to the journal."""
    config, baseline = _load(campaign)
    _require_open(campaign)
    seen = [r for r in journal.read(campaign) if r["kind"] == "eval" and "rule_hash" in r]
    try:
        rule = load_rule(rule_path)
        if previous := [r for r in seen if r["rule_hash"] == digest(rule)]:
            return previous[0]  # deterministic, so a repeat adds nothing to the journal
        names = {r["rule"] for r in seen}
        if rule.name in names:
            raise ValueError(f"a different rule named {rule.name!r} is already in the journal")
        parent = rule.parent or baseline.name
        if parent not in names:
            raise ValueError(f"parent {parent!r} has not been evaluated in this campaign")
        discovery = read_pile(campaign / "data/discovery.csv")
        result = cross_validate(discovery, rule, config)
        comparison = compare(result, cross_validate(discovery, baseline, config), config.protocol)
    except ValueError as exc:
        failure = {"rule": rule_path.stem, "verdict": "error", "error": str(exc)}
        journal.append(campaign, "eval", data="discovery", **failure)
        raise
    return journal.append(
        campaign,
        "eval",
        data="discovery",
        **_describe(rule, config, result),
        parent=parent,
        hypothesis=rule.hypothesis,
        fold_sd=result["fold_sd"],
        folds=_primary_by_fold(result, config),
        **comparison,
        rule_json=rule.model_dump(mode="json"),
    )


def note(campaign: Path, text: str) -> dict:
    """Free-text journal entry: what was looked at, why the next idea follows, why to stop."""
    _load(campaign)
    if not text.strip():
        raise ValueError("note text is empty")
    return journal.append(campaign, "note", text=text.strip())


def verify(campaign: Path, rule_paths: list[Path]) -> dict:
    """Pick at most one of 1-3 named finalists on discovery, test it once on reserved rows."""
    config, baseline = _load(campaign)
    _require_open(campaign)
    if not 1 <= len(rule_paths) <= 3:
        raise ValueError("verify takes 1-3 pre-specified finalists")
    rules = [load_rule(path) for path in rule_paths]
    if len({digest(r) for r in [baseline, *rules]}) != len(rules) + 1:
        raise ValueError("finalists must be distinct from each other and from the baseline")
    protocol, primary = config.protocol, config.protocol.primary_metric
    discovery = read_pile(campaign / "data/discovery.csv")
    base_dev = cross_validate(discovery, baseline, config)
    candidates = []
    for rule in rules:
        result = cross_validate(discovery, rule, config)
        candidates.append((rule, result, compare(result, base_dev, protocol)))
    eligible = [
        c for c in candidates if not c[2]["guards_broken"] and (c[2]["delta"][primary] or 0) > 0
    ]
    selected = max(eligible, key=lambda c: c[1]["metrics"][primary], default=None)
    evaluated = sum(r["kind"] == "eval" and "rule_hash" in r for r in journal.read(campaign)) - 1
    # Claim the one use BEFORE opening any reserved rows. A crashed run stays consumed.
    _write(campaign / "data/verify-used.json", {"finalists": [r.name for r in rules]})
    reserved = read_pile(campaign / "data/locked/verification.csv")
    base_ver = cross_validate(reserved, baseline, config)
    row = {
        "data": "verification",
        "ideas_evaluated_before": evaluated,
        "finalists": [
            {"rule": r.name, "rule_hash": digest(r), "discovery": res["metrics"], **cmp}
            for r, res, cmp in candidates
        ],
        "selected": selected[0].name if selected else None,
        "baseline_metrics": base_ver["metrics"],
    }
    accepted = False
    if selected:
        rule, _, dev = selected
        result = cross_validate(reserved, rule, config)
        transfer = compare(result, base_ver, protocol)
        gain = transfer["delta"][primary]
        accepted = not transfer["guards_broken"] and gain is not None and gain > 0
        row |= {
            **_describe(rule, config, result),
            "delta": transfer["delta"],
            "noise": transfer["noise"],
            "guards_broken": transfer["guards_broken"],
            "dev_gain": dev["delta"][primary],
            "transfer_gain": gain,
            "optimism_gap": None if gain is None else dev["delta"][primary] - gain,
        }
    else:
        row |= _describe(baseline, config, base_ver)
    frozen = selected[0] if accepted else baseline
    _write(campaign / "data/frozen.json", frozen.model_dump(mode="json"))
    return journal.append(
        campaign,
        "verify",
        **row,
        accepted=accepted,
        verdict="accepted" if accepted else "baseline-kept",
        frozen=frozen.name,
        rule_json=frozen.model_dump(mode="json"),
    )


def final(campaign: Path) -> dict:
    """Score the frozen rule once on the locked holdout. There is no rule argument."""
    config, baseline = _load(campaign)
    frozen_path = campaign / "data/frozen.json"
    if not frozen_path.exists():
        raise ValueError("nothing is frozen yet; run `filters verify` first")
    rule = load_rule(frozen_path)
    if (campaign / "data/final-used.json").exists():
        raise ValueError("the final holdout has already been used; the campaign is over")
    _write(campaign / "data/final-used.json", {"rule": rule.name, "rule_hash": digest(rule)})
    holdout = read_pile(campaign / "data/locked/holdout.csv")

    def pooled(r: Rule) -> dict:
        y, ids = holdout._label.to_numpy(), holdout._id.to_numpy()
        return measure(y, score(r, holdout, config), ids, config.protocol.top_k)

    metrics = pooled(rule)
    row = {"rule": rule.name, "rule_hash": digest(rule), "formula": pretty(rule, config)}
    if digest(rule) != digest(baseline):
        base = pooled(baseline)
        row["baseline_metrics"] = base
        row["delta"] = {
            k: None if metrics[k] is None or base[k] is None else metrics[k] - base[k] for k in base
        }
    return journal.append(
        campaign,
        "final",
        data="holdout",
        **row,
        metrics=metrics,
        rows=len(holdout),
        positives=int(np.sum(holdout._label)),
        verdict="final",
        rule_json=rule.model_dump(mode="json"),
    )
