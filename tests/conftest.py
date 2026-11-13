import json
from pathlib import Path

import pytest

from autoresearch_filters.prepare import prepare

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dict():
    value = json.loads((ROOT / "configs/synthetic.json").read_text())
    value["source"]["path"] = str(ROOT / "data/synthetic.csv")
    return value


@pytest.fixture
def campaign(tmp_path, config_dict):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(config_dict))
    work = tmp_path / "work"
    prepare(path, work)
    return work
