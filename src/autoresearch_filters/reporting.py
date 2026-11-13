"""Human summaries and append-only audit rows derived from immutable run records."""

import hashlib
import json
import subprocess
from pathlib import Path

from .config import digest
from .io import file_hash, now, read_json
from .rules import Rule


def summarize(record: dict) -> str:
    lines = [f"{record['mode']}: {record['rule']['name']}", record["formula"]]
    if record.get("status") == "failed":
        lines.append(f"FAILED: {record['error']}")
    if "summary" in record:
        for key, item in record["summary"].items():
            mean, std = item["mean"], item["std"]
            value = "undefined" if mean is None else f"{mean:.6f} ± {std:.6f}"
            lines.append(f"  {key}: {value} ({item['valid']}/{item['total']} valid)")
    if "decision" in record:
        lines.append(json.dumps(record["decision"], indent=2))
    if "diagnostics" in record:
        lines.append(json.dumps(record["diagnostics"], indent=2))
    lines.extend(record.get("notes", []))
    return "\n".join(lines)


def append_result(
    record_path: Path, log: Path, commit: str, rule_path: str, decision: str, note: str
) -> dict:
    if decision not in {"baseline", "hypothesis", "accepted", "rejected", "final", "diagnostic"}:
        raise ValueError("invalid audit decision")
    if not note.strip():
        raise ValueError("audit note must explain the outcome, including failures")
    record = read_json(record_path)
    try:
        full_commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], text=True
        ).strip()
        content = subprocess.check_output(["git", "show", f"{full_commit}:{rule_path}"], text=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("commit must contain the tested rule at --rule-path") from exc
    if digest(Rule.model_validate_json(content)) != record["rule_hash"]:
        raise ValueError("committed rule differs from the rule embedded in the run record")
    # Bind the post-run commit to the interpreter/evaluator that actually ran, too.
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", full_commit, "src/autoresearch_filters"], text=True
    ).splitlines()
    implementation = {
        Path(name).name: hashlib.sha256(
            subprocess.check_output(["git", "show", f"{full_commit}:{name}"])
        ).hexdigest()
        for name in names
        if name.endswith(".py")
    }
    if digest(implementation) != record["implementation_hash"]:
        raise ValueError("committed implementation differs from the evaluator used for this run")
    if decision == "accepted" and not record.get("decision", {}).get("accepted"):
        raise ValueError("only a successful transfer-check can mark a rule accepted")
    if decision == "final" and record["mode"] != "final":
        raise ValueError("only a final record can be logged as final")
    record_hash = file_hash(record_path)
    if log.exists():
        existing = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        if any(row["record_hash"] == record_hash for row in existing):
            raise ValueError("this run record is already in the audit log")
    row = {
        "logged_at": now(),
        "commit": full_commit,
        "rule_path": rule_path,
        "rule_hash": record["rule_hash"],
        "record": str(record_path),
        "record_hash": record_hash,
        "mode": record["mode"],
        "config_hash": record["config_hash"],
        "metrics": record.get("summary", {}),
        "decision": decision,
        "note": note,
    }
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    return row
