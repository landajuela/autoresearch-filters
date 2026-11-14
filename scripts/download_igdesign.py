"""Fetch the pinned release into the ignored cache, using the same verified loader."""

from pathlib import Path

from autoresearch_filters.data import igdesign

if __name__ == "__main__":
    frame = igdesign(Path(__file__).resolve().parents[1] / "data/downloads")
    print(f"Verified public CSVs; {len(frame)} inverse-folding candidate rows available.")
