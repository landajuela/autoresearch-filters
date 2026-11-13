"""Verify public audit records and git provenance without opening any dataset."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from autoresearch_filters.config import digest
from autoresearch_filters.io import file_hash
from autoresearch_filters.rules import Rule


def verify(log: Path) -> int:
    count = 0
    for line in log.read_text().splitlines():
        row = json.loads(line)
        path = Path(row["record"])
        record = json.loads(path.read_text())
        assert file_hash(path) == row["record_hash"], f"Record changed: {path}"
        assert record["config_hash"] == row["config_hash"]
        assert record.get("summary", {}) == row["metrics"]
        content = subprocess.check_output(
            ["git", "show", f"{row['commit']}:{row['rule_path']}"], text=True
        )
        assert digest(Rule.model_validate_json(content)) == row["rule_hash"] == record["rule_hash"]
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", row["commit"], "src/autoresearch_filters"],
            text=True,
        ).splitlines()
        code = {
            Path(name).name: hashlib.sha256(
                subprocess.check_output(["git", "show", f"{row['commit']}:{name}"])
            ).hexdigest()
            for name in names
            if name.endswith(".py")
        }
        assert digest(code) == record["implementation_hash"], f"Implementation changed: {path}"
        count += 1
    return count


if __name__ == "__main__":
    print(f"Verified {verify(Path(sys.argv[1]))} audit rows; no dataset or holdout opened.")
