"""Content hashes and exclusive writes used by all protocol stages."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def now() -> str:
    return datetime.now(UTC).isoformat()


def git_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"commit": None, "dirty": True}


def verify_file(path: Path, expected: str) -> None:
    if file_hash(path) != expected:
        raise ValueError(f"sealed file changed: {path.name}; do not alter an active campaign")
