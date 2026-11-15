import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autoresearch_filters.bootstrap import draft_rule, initialise
from autoresearch_filters.campaign import prepare
from autoresearch_filters.cli import _resolve, app

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch, screen_table):
    """A working directory holding only data/screen.csv, as a new user would have."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    screen_table.to_csv(tmp_path / "data/screen.csv", index=False)
    return tmp_path


def test_resolve_bare_names_to_the_conventional_folder():
    assert _resolve(Path("screen"), "configs") == Path("configs/screen.json")
    assert _resolve(Path("configs/screen.json"), "configs") == Path("configs/screen.json")
    assert _resolve(Path("other/screen.json"), "configs") == Path("other/screen.json")
    assert _resolve(Path("/abs/screen.json"), "rules") == Path("/abs/screen.json")


def test_three_commands_take_a_bare_table_to_a_scored_idea(project):
    assert runner.invoke(app, ["init", "--data", "data/screen.csv"]).exit_code == 0
    assert (project / "configs/screen.json").exists()
    assert (project / "rules/screen-baseline.json").exists()

    # --config takes the bare name, and --baseline defaults to what `init` wrote.
    prepared = runner.invoke(app, ["prepare", "--config", "screen", "-c", "run1"])
    assert prepared.exit_code == 0, prepared.output
    assert "baseline" in prepared.output

    drafted = runner.invoke(
        app,
        [
            "idea",
            "docking-only",
            "--why",
            "one column may carry it",
            "--signals",
            "docking_energy",
            "-c",
            "run1",
        ],
    )
    assert drafted.exit_code == 0, drafted.output
    rule = json.loads((project / "rules/docking-only.json").read_text())
    assert rule["parent"] == "screen-baseline"
    assert rule["hypothesis"] == "one column may carry it"
    assert rule["expression"]["terms"] == [{"signal": "docking_energy", "weight": 1.0}]

    scored = runner.invoke(app, ["eval", "docking-only", "-c", "run1"])
    assert scored.exit_code == 0, scored.output
    assert "docking-only" in scored.output
    kinds = [json.loads(line)["kind"] for line in (project / "campaigns/run1/journal.jsonl").open()]
    assert kinds == ["prepare", "eval", "eval"]


def test_prepare_without_a_baseline_says_which_file_is_missing(project):
    runner.invoke(app, ["init", "--data", "data/screen.csv", "--name", "other"])
    (project / "rules/other-baseline.json").unlink()
    result = runner.invoke(app, ["prepare", "--config", "other", "-c", "run1"])
    assert result.exit_code != 0
    assert "rules/other-baseline.json does not exist" in result.output


def test_idea_needs_a_prepared_campaign_and_a_real_hypothesis(project, tmp_path):
    runner.invoke(app, ["init", "--data", "data/screen.csv"])
    early = runner.invoke(app, ["idea", "x", "--why", "too soon", "-c", "run1"])
    assert early.exit_code != 0 and "not a prepared campaign" in early.output

    runner.invoke(app, ["prepare", "--config", "screen", "-c", "run1"])
    for args, expected in [
        (["--why", "   "], "--why is the hypothesis"),
        (["--why", "ok", "--signals", "ghost"], "unknown signals"),
        (["--why", "ok", "--weights", "1,2,3"], "weights for"),  # only 2 signals exist
        (["--why", "ok", "--weights", "heavy"], "must be numbers"),
        (["--why", "ok", "--signals", "docking_energy,docking_energy"], "listed twice"),
    ]:
        result = runner.invoke(app, ["idea", "bad", *args, "-c", "run1"])
        assert result.exit_code != 0, args
        assert expected in result.output, args
    assert not (project / "rules/bad.json").exists()


def test_draft_rule_builds_products_and_refuses_to_clobber(tmp_path, csv, screen_table):
    report = initialise(csv(screen_table), root=tmp_path)
    campaign = tmp_path / "campaign"
    prepare(report["config_path"], report["baseline_path"], campaign)

    drafted = draft_rule(
        campaign,
        "both-scopes",
        why="both must hold",
        signals=["predicted_affinity", "docking_energy"],
        weights=[1, 2],
        product=True,
        parent="screen-baseline",
        root=tmp_path,
    )
    expression = json.loads(drafted["path"].read_text())["expression"]
    assert expression["kind"] == "product"
    assert expression["factors"] == [
        {"signal": "predicted_affinity", "exponent": 1},
        {"signal": "docking_energy", "exponent": 2},
    ]

    with pytest.raises(ValueError, match="already exists"):
        draft_rule(campaign, "both-scopes", why="again", root=tmp_path)
    assert draft_rule(campaign, "both-scopes", why="again", root=tmp_path, force=True)


def test_drafted_rule_defaults_to_every_signal_and_the_campaign_baseline(
    tmp_path, csv, screen_table
):
    report = initialise(csv(screen_table), root=tmp_path)
    campaign = tmp_path / "campaign"
    prepare(report["config_path"], report["baseline_path"], campaign)
    drafted = draft_rule(campaign, "all-signals", why="start from everything", root=tmp_path)
    rule = drafted["rule"]
    assert rule.parent == "screen-baseline"
    assert [term.signal for term in rule.expression.terms] == [
        "predicted_affinity",
        "docking_energy",
    ]
