"""Fetch pinned source files into data/raw/<dataset>; resume downloads in data/cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/raw"
CACHE = ROOT / "data/cache/downloads"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", help="Download only this dataset; repeatable")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/manifests/public-datasets.json").read_text())
    known = {item["dataset"] for item in manifest["files"]}
    if unknown := set(args.dataset or []) - known:
        parser.error(f"Unknown datasets: {sorted(unknown)}")
    for item in manifest["files"]:
        if args.dataset and item["dataset"] not in args.dataset:
            continue
        path = DATA / item["path"]
        if not path.resolve().is_relative_to(DATA.resolve()):
            raise ValueError("Manifest path escapes raw data directory")
        if path.exists():
            if sha256(path) != item["sha256"]:
                raise ValueError(f"Cached checksum mismatch: {path}")
            print(f"Verified cached {item['path']}", flush=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = CACHE / (item["path"] + ".part")
        if not partial.resolve().is_relative_to(CACHE.resolve()):
            raise ValueError("Manifest path escapes download cache")
        partial.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "curl",
                "-L",
                "--fail",
                "--show-error",
                "--retry",
                "3",
                "--connect-timeout",
                "30",
                "--continue-at",
                "-",
                item["url"],
                "--output",
                str(partial),
            ],
            check=True,
        )
        if partial.stat().st_size != item["bytes"] or sha256(partial) != item["sha256"]:
            raise ValueError(f"Downloaded checksum mismatch: {partial}")
        partial.rename(path)
        print(f"Downloaded and verified {item['path']}", flush=True)


if __name__ == "__main__":
    main()
