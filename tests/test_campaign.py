import json

import pandas as pd
import pytest

from autoresearch_filters import journal
from autoresearch_filters.campaign import evaluate, final, note, prepare, verify
from autoresearch_filters.report import render


def pile(campaign, name):
    return pd.read_csv(campaign / "data" / name, dtype=str)


def test_prepare_makes_disjoint_piles_and_a_baseline_row(campaign, tmp_path, write_rule):
    discovery, reserved, holdout = (
        pile(campaign, n)
        for n in ["discovery.csv", "locked/verification.csv", "locked/holdout.csv"]
    )
    ids = [set(p._id) for p in (discovery, reserved, holdout)]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert set(holdout._group) == {"g7"} and "g7" not in set(discovery._group) | set(
        reserved._group
    )
    assert "measured_response" not in discovery.columns  # only allowlisted signals survive
    rows = journal.read(campaign)
    assert [r["kind"] for r in rows] == ["prepare", "eval"]
    assert rows[1]["verdict"] == "baseline" and rows[1]["rule"] == "base"
    assert rows[0]["signal_auc"]["confidence"] > 0.5
    with pytest.raises(ValueError, match="already exists"):
        prepare(
            tmp_path / "dataset.json", write_rule("again", [{"signal": "confidence"}]), campaign
        )


def test_eval_logs_every_outcome_once(campaign, write_rule):
    idea = write_rule("conf", [{"signal": "confidence"}])
    row = evaluate(campaign, idea)
    assert row["seq"] == 2 and row["parent"] == "base" and row["data"] == "discovery"
    assert row["delta"]["roc_auc"] == pytest.approx(
        row["metrics"]["roc_auc"] - journal.read(campaign)[1]["metrics"]["roc_auc"]
    )
    assert row["verdict"] in {"better", "within-noise", "worse", "guard-broken"}
    assert row["rule_json"]["expression"]["terms"][0]["signal"] == "confidence"
    assert evaluate(campaign, idea)["seq"] == 2  # same rule again: nothing new is logged
    child = evaluate(campaign, write_rule("conf2", [{"signal": "stabilizer"}], parent="conf"))
    assert child["parent"] == "conf"
    with pytest.raises(ValueError, match="unknown signals"):
        evaluate(campaign, write_rule("leak", [{"signal": "measured_response"}]))
    with pytest.raises(ValueError, match="parent"):
        evaluate(
            campaign,
            write_rule(
                "orphan",
                [{"signal": "stabilizer", "weight": 2}, {"signal": "confidence"}],
                parent="nobody",
            ),
        )
    note(campaign, "two failures recorded")
    rows = journal.read(campaign)
    assert [r["seq"] for r in rows] == list(range(7))
    assert [r.get("verdict") for r in rows[4:6]] == ["error", "error"]
    assert "leak" in journal.table(rows) and "two failures recorded" in journal.table(rows)
    html = render(rows, "test")
    assert "conf2" in html and "<svg" in html


def test_verify_and_final_are_one_use(campaign, write_rule):
    with pytest.raises(ValueError, match="verify"):
        final(campaign)
    good = write_rule("conf", [{"signal": "confidence"}])
    same = write_rule("base-copy", [{"signal": "negative_error"}])
    with pytest.raises(ValueError, match="distinct"):
        verify(campaign, [same])
    with pytest.raises(ValueError, match="1-3"):
        verify(campaign, [good] * 4)
    assert not (campaign / "data/verify-used.json").exists()  # rejected calls consume nothing
    row = verify(campaign, [good])
    assert row["data"] == "verification" and row["frozen"] in {"conf", "base"}
    assert row["accepted"] == (row["frozen"] == "conf")
    assert row["finalists"][0]["rule"] == "conf"
    frozen = json.loads((campaign / "data/frozen.json").read_text())
    assert frozen["name"] == row["frozen"]
    with pytest.raises(ValueError, match="frozen"):
        verify(campaign, [good])
    with pytest.raises(ValueError, match="frozen"):
        evaluate(campaign, write_rule("late", [{"signal": "stabilizer"}]))
    last = final(campaign)
    assert last["data"] == "holdout" and last["rule"] == row["frozen"]
    assert last["rows"] == len(pile(campaign, "locked/holdout.csv"))
    with pytest.raises(ValueError, match="already been used"):
        final(campaign)
    assert [r["kind"] for r in journal.read(campaign)] == ["prepare", "eval", "verify", "final"]


def test_accepted_candidate_is_frozen_and_compared_on_holdout(tmp_path, config_dict, write_rule):
    # A deliberately poor baseline, so the informative signal must win and transfer.
    config = tmp_path / "dataset.json"
    config.write_text(json.dumps(config_dict))
    campaign = tmp_path / "c2"
    prepare(config, write_rule("weak", [{"signal": "stabilizer"}]), campaign)
    row = verify(campaign, [write_rule("conf", [{"signal": "confidence"}])])
    assert row["accepted"] and row["selected"] == row["frozen"] == "conf"
    assert row["transfer_gain"] > 0 and row["optimism_gap"] == pytest.approx(
        row["dev_gain"] - row["transfer_gain"]
    )
    last = final(campaign)
    assert last["rule"] == "conf" and last["delta"]["roc_auc"] > 0
