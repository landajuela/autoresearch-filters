"""Append-only campaign journal: one JSON line per event, plus a terminal view of it."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SYMBOLS = {
    "baseline": "·",
    "better": "▲",
    "worse": "▼",
    "within-noise": "≈",
    "guard-broken": "⚠",
    "error": "✕",
    "accepted": "✓",
    "baseline-kept": "✕",
    "final": "■",
}


def read(campaign: Path) -> list[dict]:
    path = campaign / "journal.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def append(campaign: Path, kind: str, **fields: object) -> dict:
    """Add one event. `commit` is HEAD when the command ran; the rule itself is in the row."""
    row = {
        "seq": len(read(campaign)),
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "kind": kind,
        **fields,
        "commit": _commit(),
    }
    campaign.mkdir(parents=True, exist_ok=True)
    with (campaign / "journal.jsonl").open("a") as stream:
        stream.write(json.dumps(row, allow_nan=False) + "\n")
    return row


def primary_metric(rows: list[dict]) -> str:
    return next(
        (r["config"]["protocol"]["primary_metric"] for r in rows if "config" in r), "roc_auc"
    )


def num(value: float | None, signed: bool = False) -> str:
    return "–" if value is None else f"{value:+.4f}" if signed else f"{value:.4f}"


def badge(row: dict) -> str:
    verdict = row.get("verdict", "")
    return f"{SYMBOLS.get(verdict, '')} {verdict}".strip()


def table(rows: list[dict]) -> str:
    """The whole campaign at a glance. Δ is against the baseline on the same data pile."""
    primary = primary_metric(rows)
    metric_rows = [r for r in rows if "metrics" in r]
    others = [k for k in (metric_rows[0]["metrics"] if metric_rows else {}) if k != primary]
    header = ["#", "kind", "data", "rule", "parent", primary, "Δ", "±noise", *others, "verdict"]
    body = []
    for r in rows:
        if r["kind"] == "prepare":
            sizes = ", ".join(f"{k} {v}" for k, v in r["rows"].items())
            body.append([str(r["seq"]), "prepare", f"{r['dataset']}: {sizes} rows"])
        elif r["kind"] == "note":
            body.append([str(r["seq"]), "note", r["text"]])
        elif "metrics" not in r:
            body.append([str(r["seq"]), r["kind"], f"{r['rule']}: ✕ {r.get('error', '')}"])
        else:
            m, d = r["metrics"], r.get("delta") or {}
            body.append(
                [
                    str(r["seq"]),
                    r["kind"],
                    r["data"],
                    r["rule"],
                    r.get("parent") or "–",
                    num(m[primary]),
                    num(d.get(primary), signed=True),
                    num(r.get("noise")),
                    *[num(m[k]) for k in others],
                    badge(r),
                ]
            )
    full = [row for row in [header, *body] if len(row) == len(header)]
    widths = [max(len(row[i]) for row in full) for i in range(len(header))]
    widths[1] = max(len(row[1]) for row in [header, *body])

    def line(cells: list[str]) -> str:
        if len(cells) != len(header):  # free-text rows span the table
            return f"{cells[0]:>{widths[0]}}  {cells[1]:<{widths[1]}}  {cells[2]}"
        text = [cells[0].rjust(widths[0])]
        text += [c.ljust(w) for c, w in zip(cells[1:5], widths[1:5], strict=True)]
        text += [c.rjust(w) for c, w in zip(cells[5:-1], widths[5:-1], strict=True)]
        return "  ".join([*text, cells[-1]]).rstrip()

    return "\n".join(line(cells) for cells in [header, *body])


def summary(row: dict, primary: str) -> str:
    """What a command prints after appending its row."""
    lines = [f"#{row['seq']} {row['kind']}: {row.get('rule', '')}  {badge(row)}".rstrip()]
    if "formula" in row:
        lines.append(row["formula"])
    for key, value in (row.get("metrics") or {}).items():
        delta = (row.get("delta") or {}).get(key)
        extra = f"  Δ {num(delta, signed=True)}" if delta is not None else ""
        if key == primary and row.get("noise") is not None:
            extra += f"  (noise ±{num(row['noise'])})"
        lines.append(f"  {key:<13} {num(value)}{extra}")
    if row.get("guards_broken"):
        lines.append(f"  guards broken: {', '.join(row['guards_broken'])}")
    if row["kind"] == "verify":
        picked = row["selected"] or "none eligible"
        lines.append(f"  selected on discovery: {picked}; frozen rule: {row['frozen']}")
    return "\n".join(lines)
