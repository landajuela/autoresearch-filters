import json
from pathlib import Path

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
