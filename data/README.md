# Data provenance and licensing

Two files are vendored, both synthetic and both covered by this repository's MIT
license. Neither is experimental evidence.

- `synthetic.csv`: a deterministic 192-row test fixture.
- `example_screen.csv`: a deterministic 240-row table in the shape users arrive
  with, computed columns plus one experimental outcome and no ID or group column.
  Regenerate it with `uv run python scripts/make_example_screen.py`; the latent
  quality, the per-column signal strength and the outcome are drawn from a fixed
  seed, so `docking_energy` is informative and `strain_energy` carries nothing by
  construction.

## IgDesign (download only)

- Upstream: [AbSciBio/igdesign](https://github.com/AbSciBio/igdesign).
- Pinned commit: `70431eef0afaf0496d7d84e22dfdc1980ec9e70e`.
- License checked and files retrieved: **2026-11-13**.
- The repository's [LICENSE at this revision](https://github.com/AbSciBio/igdesign/blob/70431eef0afaf0496d7d84e22dfdc1980ec9e70e/LICENSE)
  is MIT, copyright 2024 Absci. Its text refers to software and associated
  documentation; we did not find a separate data-specific license in the inspected
  data directory. We make no assumption about additional rights: **the upstream
  CSVs are not redistributed here**. Downloaded files remain in ignored
  `data/downloads/`. The code license in this repository does not relicense them.
- [Pinned release documentation](https://github.com/AbSciBio/igdesign/blob/70431eef0afaf0496d7d84e22dfdc1980ec9e70e/README.md)
  describes the SPR labels and structural consistency columns.
- [Download manifest](../src/autoresearch_filters/igdesign_manifest.json) records
  the exact seven public CSV URLs and SHA-256 digests. `prepare` verifies cached
  bytes too. It does not download models, checkpoints, sensorgrams, or other data.

The shipped loader uses the seven unblinded systems. It excludes the blinded
CD40 file. It keeps only `Method == "Inverse Folding"`, excluding positive
controls and SAbDab rows. Each candidate ID is the source filename plus original
zero-based row position. The system is the filename stem. `Binder == True` is
success, as supplied by the release; no affinity threshold is invented.
Only four precomputed scRMSD columns enter the example rule space. All are raw,
non-negated deviations: smaller is declared better. Clip ranges of 0–10 angstrom
are **pre-specified harness choices**, not published or fitted cutoffs. Missing
values in any configured signal drop the row before splitting. Experimental
affinity and replicate columns are not in the signal allowlist, so they are
dropped at preparation. No sequences are used as learned features.

The final system, `Utomilumab-TNFRSF9`, was fixed before evaluating any rule
(alphabetically last among the shipped filenames). The other systems form the
train pool. A seeded stratified split reserves half the pool positives and half
the negatives for one-use verification. Discovery and verification each use
leave-one-system-out evaluation. This split-positive check tests new rows within
systems, not new-system generalization; only the final system is group-disjoint
from the entire train pool.

To download and prepare:

```sh
uv run filters prepare --config configs/igdesign.json --baseline rules/baseline.json -c my-study
```

Or fetch and checksum just the upstream files with
`uv run python scripts/download_igdesign.py`. `data/downloads/` and `campaigns/`
are both git-ignored, so neither the upstream CSVs nor your split data and journals
are committed. The one journal kept in the repo, `docs/example-journal.jsonl`,
contains aggregate metrics, not candidate features or experimental labels.
