import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from autoresearch_filters.campaign import prepare

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dict():
    value = json.loads((ROOT / "configs/synthetic.json").read_text())
    value["source"] = str(ROOT / "data/synthetic.csv")
    return value


@pytest.fixture
def write_rule(tmp_path):
    def write(name: str, terms: list[dict], **extra) -> Path:
        rule = {"name": name, "hypothesis": f"test {name}", **extra}
        rule["expression"] = {"kind": "additive", "terms": terms}
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(rule))
        return path

    return write


@pytest.fixture
def campaign(tmp_path, config_dict, write_rule):
    config = tmp_path / "dataset.json"
    config.write_text(json.dumps(config_dict))
    path = tmp_path / "campaign"
    prepare(config, write_rule("base", [{"signal": "negative_error"}]), path)
    return path


@pytest.fixture
def screen_table() -> pd.DataFrame:
    """A table in the shape users arrive with: computed columns plus one outcome."""
    rng = np.random.default_rng(0)
    quality = rng.normal(size=120)
    return pd.DataFrame(
        {
            # "affinity" is an outcome word, but "predicted" says the number is computed.
            "predicted_affinity": 6 + quality,
            "docking_energy": -30 - 3 * quality,
            "affinity": 5 + quality,  # no computed word: must be treated as an outcome
            "note": ["text"] * 120,
            "batch": [7] * 120,
            "measured_binding": (quality + rng.normal(size=120) * 0.3 > 0).astype(int),
        }
    )


@pytest.fixture
def csv(tmp_path):
    def write(frame: pd.DataFrame, name: str = "screen.csv") -> Path:
        path = tmp_path / name
        frame.to_csv(path, index=False)
        return path

    return write
