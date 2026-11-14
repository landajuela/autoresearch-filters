import json

import numpy as np
import pandas as pd
import pytest

from autoresearch_filters.bootstrap import choose_range, choose_top_k, initialise
from autoresearch_filters.campaign import evaluate, prepare
from autoresearch_filters.data import row_ids


def table(rows: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    quality = rng.normal(size=rows)
    return pd.DataFrame(
        {
            # "affinity" is an outcome word, but "predicted" says the number is computed.
            "predicted_affinity": 6 + quality,
            "docking_energy": -30 - 3 * quality,
            "affinity": 5 + quality,  # no computed word: must be treated as an outcome
            "note": ["text"] * rows,
            "batch": [7] * rows,
            "measured_binding": (quality + rng.normal(size=rows) * 0.3 > 0).astype(int),
        }
    )


@pytest.fixture
def csv(tmp_path):
    def write(frame: pd.DataFrame, name: str = "screen.csv"):
        path = tmp_path / name
        frame.to_csv(path, index=False)
        return path

    return write


def test_init_infers_outcome_signals_and_directions(tmp_path, csv):
    report = initialise(csv(table()), root=tmp_path)
    config = json.loads((tmp_path / "configs/screen.json").read_text())

    assert config["label_column"] == "measured_binding"
    assert config["success_value"] == 1
    assert config["id_column"] is None and config["group_column"] is None
    assert list(config["signals"]) == ["predicted_affinity", "docking_energy"]
    assert config["signals"]["docking_energy"]["direction"] == "lower_is_better"
    assert config["signals"]["predicted_affinity"]["direction"] == "higher_is_better"
    assert report["skipped"]["affinity"].startswith("looks like a measured outcome")
    assert report["skipped"]["note"] == "not numeric"
    assert report["skipped"]["batch"] == "same value in every row"
    assert config["source"] == "../screen.csv"

    baseline = json.loads((tmp_path / "rules/screen-baseline.json").read_text())
    assert [t["signal"] for t in baseline["expression"]["terms"]] == list(config["signals"])
    assert [t["weight"] for t in baseline["expression"]["terms"]] == [1, 1]


def test_flags_override_inference(tmp_path, csv):
    initialise(
        csv(table()),
        root=tmp_path,
        label="measured_binding",
        success="0",
        lower=["predicted_affinity"],
        signals=["predicted_affinity", "affinity"],
        baseline_signal="affinity",
        name="my-run",
    )
    config = json.loads((tmp_path / "configs/my-run.json").read_text())
    assert config["success_value"] == 0
    assert list(config["signals"]) == ["predicted_affinity", "affinity"]  # --signals wins
    assert config["signals"]["predicted_affinity"]["direction"] == "lower_is_better"
    baseline = json.loads((tmp_path / "rules/my-run-baseline.json").read_text())
    assert [t["signal"] for t in baseline["expression"]["terms"]] == ["affinity"]


def test_group_column_switches_to_leave_one_group_out(tmp_path, csv):
    frame = table()
    frame["target"] = ["t1", "t2", "t3", "t4"] * (len(frame) // 4)
    initialise(csv(frame), root=tmp_path, group="target")
    config = json.loads((tmp_path / "configs/screen.json").read_text())
    assert config["group_column"] == "target"
    assert config["split"]["cv"] == "logo"
    assert config["split"]["holdout_groups"] == ["t4"]  # last group, fixed before any search
    assert "target" not in config["signals"]


def test_bad_input_is_refused(tmp_path, csv):
    with pytest.raises(ValueError, match="not one of"):
        initialise(csv(table()), root=tmp_path, baseline_signal="nope")
    with pytest.raises(ValueError, match="not signals"):
        initialise(csv(table()), root=tmp_path, lower=["note"])
    with pytest.raises(ValueError, match="not in the table"):
        initialise(csv(table()), root=tmp_path, signals=["ghost"])
    with pytest.raises(ValueError, match="no column named"):
        initialise(csv(table()), root=tmp_path, label="ghost")
    three = table().assign(measured_binding=[0, 1, 2] * 40)
    with pytest.raises(ValueError, match="distinct values, not 2"):
        initialise(csv(three), root=tmp_path, label="measured_binding")
    strings = table().assign(measured_binding=["left", "right"] * 60)
    with pytest.raises(ValueError, match="which of"):
        initialise(csv(strings), root=tmp_path, label="measured_binding")
    assert not (tmp_path / "configs").exists()  # nothing written on any failure


def test_existing_files_are_not_clobbered(tmp_path, csv):
    path = csv(table())
    initialise(path, root=tmp_path)
    (tmp_path / "configs/screen.json").write_text("{}")
    with pytest.raises(ValueError, match="already exists"):
        initialise(path, root=tmp_path)
    assert (tmp_path / "configs/screen.json").read_text() == "{}"
    initialise(path, root=tmp_path, force=True)
    assert json.loads((tmp_path / "configs/screen.json").read_text())["name"] == "screen"


def test_table_without_id_column_runs_the_whole_loop(tmp_path, csv):
    report = initialise(csv(table()), root=tmp_path)
    campaign = tmp_path / "campaign"
    rows = prepare(report["config_path"], report["baseline_path"], campaign)
    assert rows[1]["metrics"]["roc_auc"] > 0.5
    ids = pd.read_csv(campaign / "data/discovery.csv", dtype={"_id": str})._id
    assert ids.str.fullmatch(r"row\d{3}").all() and ids.is_unique

    idea = tmp_path / "idea.json"
    idea.write_text(
        json.dumps(
            {
                "name": "docking-only",
                "hypothesis": "one signal instead of the mean of two",
                "parent": "screen-baseline",
                "expression": {
                    "kind": "additive",
                    "terms": [{"signal": "docking_energy", "weight": 1}],
                },
            }
        )
    )
    assert evaluate(campaign, idea)["verdict"] in {"better", "worse", "within-noise"}


def test_row_ids_sort_in_source_order():
    ids = row_ids(pd.DataFrame(index=range(1000)))
    assert ids.iloc[0] == "row000" and ids.iloc[999] == "row999"
    assert sorted(ids) == list(ids)  # lexical order is source order, so tie-breaks are stable


@pytest.mark.parametrize(
    ("values", "expected"),
    [([0.42, 1.81], [0.4, 1.9]), ([-62.4, -18.1], [-63.0, -18.0]), ([0, 15], [0.0, 15.0])],
)
def test_choose_range_rounds_outward(values, expected):
    low, high = choose_range(pd.Series(values))
    assert [low, high] == expected
    assert low <= min(values) and high >= max(values)


def test_choose_top_k_stays_inside_a_fold():
    assert choose_top_k(240, 3) == [5, 10]
    assert choose_top_k(10_000, 3) == [5, 10, 20, 50]
    assert choose_top_k(40, 3) == [1]
