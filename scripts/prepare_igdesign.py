"""Export the original IgDesign benchmark cohort and audit into data/prepared/igdesign.

Use the existing verified loader, signal allowlist, label, and missing-value policy.
This creates a convenient master table; it does not create or evaluate a campaign.
"""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pandas as pd

from autoresearch_filters.config import load_config
from autoresearch_filters.data import igdesign, preprocess
from autoresearch_filters.rules import load_rule

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/prepared/igdesign"


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite prepared dataset: {OUT}")
    config = load_config(ROOT / "configs/igdesign.json")
    baseline = load_rule(ROOT / "rules/baseline.json")
    manifest = json.loads(
        files("autoresearch_filters").joinpath("igdesign_manifest.json").read_text()
    )
    cache = ROOT / "data/raw/igdesign"
    source = igdesign(cache)  # Verifies every source checksum before returning rows.
    complete = preprocess(source, config)
    columns = [config.id_column, config.group_column, config.label_column, *config.signals]
    table = source[columns].sort_values(config.id_column).reset_index(drop=True)
    source_files = [
        {**item, "rows": len(pd.read_csv(cache / item["name"]))} for item in manifest["files"]
    ]
    source_rows = sum(item["rows"] for item in source_files)
    summary = {
        "name": config.name,
        "source_revision": manifest["revision"],
        "source_manifest": "src/autoresearch_filters/igdesign_manifest.json",
        "source_files": source_files,
        "source_rows": source_rows,
        "excluded_non_inverse_folding_rows": source_rows - len(source),
        "prepared_rows": len(table),
        "complete_rows": len(complete),
        "positives": int(complete._label.sum()),
        "groups": int(complete._group.nunique()),
        "holdout_groups": config.split.holdout_groups,
        "signals": {name: spec.model_dump(mode="json") for name, spec in config.signals.items()},
        "baseline_rule": baseline.name,
        "columns": columns,
        "excluded_columns": sorted(set(source.columns) - set(columns)),
        "missing_signal_rows": {name: int(table[name].isna().sum()) for name in config.signals},
        "rows_dropped_by_missing_policy": len(table) - len(complete),
        "notes": [
            "Seven pinned unblinded source systems; the blinded CD40 file is excluded.",
            "The verified original loader keeps Method == 'Inverse Folding', excluding "
            "controls and SAbDab rows. Raw source files retain all original rows and columns.",
            "Candidate IDs preserve source filename stem and original zero-based row position; "
            "system names and the published Binder booleans are unchanged.",
            "Only ID, system, Binder, and the four predeclared scRMSD signals are exported. "
            "Affinities, replicates, sequences, and other source columns are not rule terms.",
            "All four signal directions remain lower_is_better with fixed [0, 10] angstrom "
            "ranges and the original drop policy. No fitting, threshold tuning, or deduplication.",
            "configs/igdesign.json retains its built-in source loader and existing protocol. "
            "This CSV is a convenient export of that same input cohort, not a new dataset "
            "or fresh reserved data. No campaign, split, or journal is created or changed.",
            "See data/PROVENANCE.md for source licensing and interpretation limits.",
        ],
    }
    OUT.mkdir(parents=True)
    path = OUT / "candidates.csv"
    table.to_csv(path, index=False)
    summary["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "audit.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"Wrote {path}: {len(table)} candidates, {summary['complete_rows']} usable, "
        f"{summary['positives']} binders, {summary['groups']} systems."
    )
    print(f"Wrote {OUT / 'audit.json'}; verified all {len(source_files)} pinned source files.")


if __name__ == "__main__":
    main()
