# Data provenance and licensing

See the [data catalog](README.md) for the directory layout and links to each dataset.

Two files are vendored, both synthetic and both covered by this repository's MIT
license. Neither is experimental evidence.

- [`examples/synthetic.csv`](examples/synthetic.csv): a deterministic 192-row test fixture.
- [`examples/example_screen.csv`](examples/example_screen.csv): a deterministic 240-row table in the shape users arrive
  with, computed columns plus one experimental outcome and no ID or group column.
  Regenerate it with `uv run python scripts/make_example_screen.py`; the latent
  quality, the per-column signal strength and the outcome are drawn from a fixed
  seed, so `docking_energy` is informative and `strain_energy` carries nothing by
  construction.

## IgDesign (downloaded locally)

- Upstream: [AbSciBio/igdesign](https://github.com/AbSciBio/igdesign).
- Pinned commit: `70431eef0afaf0496d7d84e22dfdc1980ec9e70e`.
- License checked and files retrieved: **2026-11-13**.
- The repository's [LICENSE at this revision](https://github.com/AbSciBio/igdesign/blob/70431eef0afaf0496d7d84e22dfdc1980ec9e70e/LICENSE)
  is MIT, copyright 2024 Absci. Its text refers to software and associated
  documentation; we did not find a separate data-specific license in the inspected
  data directory. We make no assumption about additional rights: **the upstream
  CSVs are not redistributed here**. Downloaded files remain in ignored
  `data/raw/igdesign/`. The code license in this repository does not relicense them.
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

The seven original CSVs contain 1,243 source rows. The existing loader retains
847 inverse-folding candidates: 249 published binders across seven systems,
with all four allowed signals present. A consolidated local copy is available
as [prepared/igdesign/candidates.csv](prepared/igdesign/candidates.csv), with an
[import audit](prepared/igdesign/audit.json) recording the source checksums,
exclusions, original columns, and exported-table checksum.

Reproduce this export with `uv run python scripts/prepare_igdesign.py`. It uses
the existing loader and config, refuses to overwrite an existing export, and
does not create campaign splits or evaluate rules. The export retains the
original `candidate_id`, `system`, `Binder`, and four signal columns. The
original config still uses the built-in loader; the export is an equivalent
view of that cohort, not a new source of independent reserved data.

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
`uv run python scripts/download_igdesign.py`. `data/raw/igdesign/` and `campaigns/`
are both git-ignored, so neither the upstream CSVs nor your split data and journals
are committed. The one journal kept in the repo, `docs/example-journal.jsonl`,
contains aggregate metrics, not candidate features or experimental labels.

## Additional public design and variant datasets

The November 2026 survey was imported into ignored
`data/raw/` and `data/prepared/`. Raw data, prepared tables, import audits and
campaign journals remain local. The downloader, preparation code, configs and
baseline rules contain no upstream data rows.

The [public dataset manifest](manifests/public-datasets.json) records exact source
URLs, pinned GitHub revisions or archive versions, retrieval dates, byte counts
and SHA-256 checksums. The large Zenodo archives are also checked against their
published MD5 checksums. These sources are not relicensed by this repository:

| Source | Revision / release | License provenance |
| --- | --- | --- |
| [Overath binder scoring](https://github.com/DigBioLab/de_novo_binder_scoring) | `3d4fc2710ae23e578190503164777240f99ce976` | Upstream repository MIT license; no additional data-specific license was established. Data are downloaded locally, not redistributed. |
| [Bits to Binders](https://github.com/kosonocky/bits-to-binders) | `43eeeaf7e6ab629e796c9fe8d20b0ef70a3610d9` | Upstream repository MIT license; its LICENSE is retained with the download. |
| [Linsky scaffold designs and re-scored Rocklin designs](https://github.com/strauchlab/scaffold_design) | `f10c9eac924af91f4dff0d7e50b2641257341e3a` | No standalone repository license found. The [Linsky article](https://pmc.ncbi.nlm.nih.gov/articles/PMC9684540/) is CC BY 4.0; this is not assumed to independently relicense the original Rocklin data. No data are redistributed here. |
| [Cao/Bennett retrospective screen](https://pmc.ncbi.nlm.nih.gov/articles/PMC10163288/) | Bennett 2023 `scripts_and_main_pdbs.tar.gz`, checksum pinned in manifest | Article CC BY 4.0; the IPD-hosted supplement has no separately established data license. No data are redistributed here. |
| [ProteinGym](https://zenodo.org/records/15293562) | Data v1.3; reference/config commit `144fe22b07dfaeec2b366f2346203a9838a55b4c` | Zenodo release declares MIT. Upstream LICENSE and archive checksums are retained. Cite the underlying experimental studies as well as ProteinGym. |
| [MegaScale](https://zenodo.org/records/7992926) | `v2_230420`, record `7992926` | Zenodo release declares CC BY 4.0. The authors request registration of data use; no registration or message was submitted on the user's behalf. |

Use these commands from the repository root to reproduce the imports into a
fresh local cache. The preparation script refuses to overwrite tables or
configs; it does not fit models, evaluate candidate rules, or run the one-use
verification/final steps.

```sh
uv run python scripts/download_public_datasets.py
uv run python scripts/prepare_public_datasets.py \
    overath bits-to-binders linsky rocklin cao-bennett proteingym
```

These commands reuse the checked-in configurations. When creating configurations
for the first time in a workspace without those files, add `--init`; it refuses
to overwrite existing configs or baselines.

With `--init`, the preparation script calls `filters init` with explicit signal allowlists and
directions. It preserves the label-free ranges suggested by `init`, adds signal
descriptions, and selects PR-AUC as the primary metric before any evaluation.
All reported skipped columns are IDs, groups or the outcome; upstream columns
outside the allowlist are excluded when the candidate table is assembled.
Each `data/prepared/<config-name>/audit.json` explains those exclusions and
retains the checksum of its neighboring `candidates.csv`. Initialization output
is kept alongside them as `init.log`.

| Config name | Outcome and cohort | Baseline / grouping |
| --- | --- | --- |
| `public-overath` | Published binary binder annotation; 3,760 exported rows before missing-score exclusions | AF3 `ipSAE_min`; target groups |
| `public-bits-to-binders` | Published `Up` enrichment call versus `Down`/`Not Sig` among recovered, DNA-detected competitor designs; organizer controls excluded | Boltz maximum interface ipSAE; competitor team groups |
| `public-linsky` | Both protease stability scores > 0.5, as in the authors' classifier notebook | Rosetta energy per residue; fold groups, with missing coil labels restored from design names |
| `public-rocklin` | Both protease stability scores > 1.0, using the original paper's stringent cutoff | Rosetta energy per residue; topology groups |
| `public-cao-bennett` | Released `binder_4000_nm` annotations for the retrospective screen | AF2 interface PAE; biological target groups (`IL7Ra_graft` grouped with `IL7Ra`) |
| `public-proteingym` | Published assay-specific `DMS_score_bin` annotations, validated against the separate assay archive | ESM2-650M; UniProt groups |
| `public-megascale-proteingym` | Only the 64 Tsuboyama assays with released ProteinGym predictions; published median-based labels | ESM2-650M; UniProt groups |

For Linsky and Rocklin, exact sequence duplicates are collapsed before splitting:
each protease measurement is summarized by its median, and the representative
computed structure is the lexicographically first description, with source row
order breaking ties. No most-stable replicate or best-scoring structure is
selected. Missing experimental measurements are removed before labeling. The
constant `unsat_hbond = 911` column is excluded from both tables. Bits to Binders
shape-complementarity columns are constant zero and are also excluded.

Cao/Bennett exact duplicate rows are collapsed. Conflicting repeated target/design
IDs stop the import. Its prospective figure-data export has only 9,999 rows,
two targets and one positive, so it is not presented as the complete prospective
screen or used for a separate campaign.

The full MegaScale measurement archive is downloaded, but its inferred
experimental dG/ddG values are outcomes, not eligible computational signals.
The prepared MegaScale campaign is explicitly the ProteinGym subset; additional
oracle scores are required for a campaign covering the full original dataset.
ProteinGym uses five predeclared zero-shot model families: ESM2-650M, ESM1v
ensemble, ProteinMPNN, ESM-IF1 and GEMME. No supervised model outputs enter rules.
Its binary labels often mean above an assay median, not above a universal
biochemical activity threshold. The downloaded v1.3 substitution tables contain
2,465,767 assay/variant records, including 117,811 in the 64-assay MegaScale
subset; headline counts for the broader benchmark are not substituted for these
verified counts. Repeated variants in different assays remain separate records,
so identical variants as well as sequence relatives can span discovery and
verification. Most ProteinGym rows are variants of existing proteins rather than
de novo designs.

All new configs use the alphabetically last group as the final holdout, fixed
before baseline evaluation. Discovery and verification are seeded, stratified
halves of the remaining rows and use leave-one-group-out evaluation. As with
IgDesign, **verification is not group-disjoint from discovery**; only the final
holdout is group-disjoint. Exact duplicate removal does not establish homology
independence. Overath overlaps Cao/Bennett, and the MegaScale/ProteinGym campaign
is a subset of ProteinGym: do not count these as independent replications.

For a genuinely new study with fresh reserved data, create a campaign after
checking its audit. A new campaign name alone does not make reused data fresh:

```sh
uv run filters prepare --config public-overath -c public-overath-NEW
```

Signal directions are never silently reversed when the discovery AUC is below
0.5. Such findings belong in the campaign journal, along with the import choices
and limitations. No rule-search or reserved-data evaluation is part of dataset
preparation.
