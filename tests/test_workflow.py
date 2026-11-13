import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autoresearch_filters.cli import app
from autoresearch_filters.config import digest
from autoresearch_filters.dev import evaluate
from autoresearch_filters.diagnostics import gate_scan
from autoresearch_filters.final import final
from autoresearch_filters.io import read_json
from autoresearch_filters.reporting import append_result
from autoresearch_filters.rules import Rule, load_rule
from autoresearch_filters.transfer import Plan, register, transfer_check

ROOT = Path(__file__).resolve().parents[1]


def test_transfer_accepts_on_unseen_rows_and_freezes_snapshot(campaign, tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        Rule(
            name="constant",
            hypothesis="Uninformative initial rule",
            expression={"kind": "constant", "value": 0.5},
        ).model_dump_json()
    )
    candidate = tmp_path / "candidate.json"
    shutil.copy(ROOT / "rules/synthetic.json", candidate)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "baseline": str(baseline),
                "candidates": [
                    {
                        "path": str(candidate),
                        "reason": "Confidence orders synthetic outcomes by construction.",
                    }
                ],
            }
        )
    )
    register(campaign, plan)
    original = load_rule(candidate)
    # The verifier uses the registered snapshot, not a mutable path.
    candidate.write_text(baseline.read_text())
    checked = transfer_check(campaign, tmp_path / "transfer.json")
    assert checked["decision"]["accepted"]
    assert checked["decision"]["chosen_rule_hash"] == digest(original)
    assert final(campaign, tmp_path / "final.json")["rule_hash"] == digest(original)


def test_gate_diagnostic_and_budget(campaign, tmp_path):
    baseline = load_rule(ROOT / "rules/synthetic.json")
    record = gate_scan(
        campaign, baseline, "confidence", [0.1, 0.3], "negative_error", ">", tmp_path / "scan.json"
    )
    assert not record["selection_eligible"]
    for row in record["diagnostics"]:
        assert row["local_correlations_with_base_signals"]["confidence"] == pytest.approx(1)
    with pytest.raises(FileExistsError):
        gate_scan(
            campaign, baseline, "confidence", [0.2], "stabilizer", ">", tmp_path / "scan2.json"
        )
    for i in range(12):
        evaluate(campaign, baseline, tmp_path / f"search-{i}.json", mode="search")
    with pytest.raises(ValueError, match="budget exhausted"):
        evaluate(campaign, baseline, tmp_path / "exhausted.json", mode="search")


def test_plan_is_small_and_prespecified():
    with pytest.raises(ValueError):
        Plan(
            baseline="base",
            candidates=[{"path": str(i), "reason": "A mechanical reason"} for i in range(4)],
        )


def test_cli_prepare_eval_report(tmp_path):
    runner = CliRunner()
    work = str(tmp_path / "work")
    prepared = runner.invoke(
        app, ["prepare", "--config", str(ROOT / "configs/synthetic.json"), "--work", work]
    )
    assert prepared.exit_code == 0, prepared.output
    output = str(tmp_path / "run.json")
    evaluated = runner.invoke(
        app,
        ["eval", "--rule", str(ROOT / "rules/synthetic.json"), "--work", work, "--output", output],
    )
    assert evaluated.exit_code == 0, evaluated.output
    reported = runner.invoke(app, ["report", "--record", output])
    assert reported.exit_code == 0
    assert "roc_auc: 1.000000" in reported.output
    denied = runner.invoke(
        app,
        [
            "eval",
            "--rule",
            str(ROOT / "rules/synthetic.json"),
            "--work",
            work,
            "--output",
            output,
            "--mode",
            "final",
        ],
    )
    assert denied.exit_code != 0


def test_audit_binds_metrics_rule_and_implementation(campaign, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "rules").mkdir(parents=True)
    shutil.copy(ROOT / "rules/synthetic.json", repo / "rules/current.json")
    shutil.copytree(
        ROOT / "src/autoresearch_filters",
        repo / "src/autoresearch_filters",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.chdir(repo)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()

    git("init", "-b", "main")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    record = tmp_path / "record.json"
    evaluate(campaign, load_rule(repo / "rules/current.json"), record)
    row = append_result(
        record,
        tmp_path / "log.jsonl",
        "HEAD",
        "rules/current.json",
        "baseline",
        "Measured fixture.",
    )
    assert row["metrics"]["roc_auc"]["mean"] == 1
    assert row["commit"] == git("rev-parse", "HEAD")
    with pytest.raises(ValueError, match="already"):
        append_result(
            record, tmp_path / "log.jsonl", "HEAD", "rules/current.json", "baseline", "duplicate"
        )
    with pytest.raises(ValueError, match="transfer-check"):
        append_result(
            record, tmp_path / "bad.jsonl", "HEAD", "rules/current.json", "accepted", "invalid"
        )
    (repo / "src/autoresearch_filters/__init__.py").write_text("# changed\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "change code",
    )
    with pytest.raises(ValueError, match="implementation differs"):
        append_result(
            record, tmp_path / "other.jsonl", "HEAD", "rules/current.json", "baseline", "invalid"
        )


def test_prevalence_opt_in(tmp_path, config_dict):
    from autoresearch_filters.prepare import prepare

    config_dict["protocol"]["match_holdout_prevalence"] = True
    config = tmp_path / "config.json"
    config.write_text(json.dumps(config_dict))
    work = tmp_path / "matched"
    prepare(config, work)
    record = evaluate(work, load_rule(ROOT / "rules/synthetic.json"), tmp_path / "matched.json")
    assert record["summary"]["matched_pr_auc"]["mean"] == 1
    assert (
        read_json(work / "dev/manifest.json")["prevalence_source"] == "holdout_aggregate_at_prepare"
    )
