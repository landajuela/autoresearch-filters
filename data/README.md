# Data catalog

Start with `prepared/` for campaign input tables, `raw/` for the original source
files, and `examples/` for the small synthetic examples. Read
[PROVENANCE.md](PROVENANCE.md) for licenses, label definitions, import decisions,
and limitations.

## Directory layout

```text
data/
├── README.md                 # This catalog and migration guide
├── PROVENANCE.md             # Sources, licenses, and preparation methods
├── examples/                # Small synthetic CSVs included in Git
├── manifests/               # Pinned download URLs and checksums included in Git
│   └── public-datasets.json
├── raw/                     # Original downloads, grouped by source
│   ├── igdesign/
│   ├── overath/
│   ├── bits-to-binders/
│   ├── linsky/
│   ├── rocklin/
│   ├── cao-bennett/
│   ├── proteingym/
│   └── megascale/
├── prepared/                # One directory per dataset config
│   └── <config-name>/        # igdesign, public-overath, etc.
│       ├── candidates.csv    # Candidate table; see the config's source setting
│       ├── audit.json        # Labels, exclusions, counts, and CSV checksum
│       └── init.log          # Original filters init output, when --init was used
├── cache/downloads/         # Temporary downloads; created only when needed
└── notes/                   # Local dataset survey and research notes
```

`raw/`, `prepared/`, `cache/`, and `notes/` are local and git-ignored.
The catalog, provenance guide, manifests, and synthetic examples belong in Git.
Download archives keep their upstream filenames, and their licenses and release
metadata stay beside them. Partial downloads are kept in `cache/`, separate from
verified source files. Use campaign journals for research history and current results.

Campaign splits and append-only journals live separately in
[`../campaigns/`](../campaigns/). Files under a campaign's `data/locked/` are
reserved for the one-use commands and are never ordinary preparation inputs.

## Datasets

The links to downloaded data and campaign journals are available in workspaces
where those local artifacts have been created. Config names match the directory
names under `prepared/`.

| Dataset | Usable rows | Prepared data | Config | Campaign journal |
| --- | ---: | --- | --- | --- |
| IgDesign original benchmark | 847 | [CSV](prepared/igdesign/candidates.csv), [audit](prepared/igdesign/audit.json) | [igdesign](../configs/igdesign.json) | [search-1](../campaigns/search-1/journal.html), [demo](../campaigns/demo/journal.html) |
| Overath binder scoring | 3,737 | [CSV](prepared/public-overath/candidates.csv), [audit](prepared/public-overath/audit.json) | [public-overath](../configs/public-overath.json) | [20261116](../campaigns/public-overath-20261116/journal.html) |
| Bits to Binders | 6,801 | [CSV](prepared/public-bits-to-binders/candidates.csv), [audit](prepared/public-bits-to-binders/audit.json) | [public-bits-to-binders](../configs/public-bits-to-binders.json) | [20261116](../campaigns/public-bits-to-binders-20261116/journal.html) |
| Linsky scaffold designs | 30,830 | [CSV](prepared/public-linsky/candidates.csv), [audit](prepared/public-linsky/audit.json) | [public-linsky](../configs/public-linsky.json) | [20261116](../campaigns/public-linsky-20261116/journal.html) |
| Rocklin stability designs | 15,718 | [CSV](prepared/public-rocklin/candidates.csv), [audit](prepared/public-rocklin/audit.json) | [public-rocklin](../configs/public-rocklin.json) | [20261116](../campaigns/public-rocklin-20261116/journal.html) |
| Cao/Bennett retrospective binders | 699,405 | [CSV](prepared/public-cao-bennett/candidates.csv), [audit](prepared/public-cao-bennett/audit.json) | [public-cao-bennett](../configs/public-cao-bennett.json) | [20261116](../campaigns/public-cao-bennett-20261116/journal.html) |
| ProteinGym v1.3 substitutions | 2,465,767 | [CSV](prepared/public-proteingym/candidates.csv), [audit](prepared/public-proteingym/audit.json) | [public-proteingym](../configs/public-proteingym.json) | [20261116](../campaigns/public-proteingym-20261116/journal.html) |
| MegaScale subset in ProteinGym | 117,811 | [CSV](prepared/public-megascale-proteingym/candidates.csv), [audit](prepared/public-megascale-proteingym/audit.json) | [public-megascale-proteingym](../configs/public-megascale-proteingym.json) | [20261116](../campaigns/public-megascale-proteingym-20261116/journal.html) |

Counts are after cohort filtering, duplicate handling, and missing-oracle
exclusions; a CSV may still include rows that its config's missing-value policy
drops. ProteinGym also has an [assay audit](prepared/public-proteingym/assay-audit.json).
Its MegaScale subset is included in the ProteinGym total. Overath overlaps
Cao/Bennett. These datasets are not independent replications.

The seven `20261116` public campaigns completed search, verification, and final
scoring and are frozen. Their journals are the authoritative result records.
A new campaign name or re-splitting the same exposed rows does not provide fresh
reserved data.

The complete MegaScale measurement archive is in `raw/megascale/`. Only the
ProteinGym subset has a prepared table with the chosen computational scores;
experimental dG/ddG values are outcomes, not additional oracle signals.

IgDesign's seven original upstream CSVs are in [raw/igdesign/](raw/igdesign/).
They contain 1,243 source rows, including controls and other methods. The
[prepared export](prepared/igdesign/candidates.csv) contains the original
benchmark's 847 inverse-folding candidates, 249 binders, seven systems, and four
precomputed scRMSD signals. It keeps the original IDs, `system`, and `Binder`
labels; all seven source checksums and the filtering decisions are in its audit.

[configs/igdesign.json](../configs/igdesign.json) continues to use the verified
built-in loader. The prepared CSV is an equivalent export for browsing and
downstream use; it does not change the original benchmark or provide fresh
reserved data. The [packaged IgDesign manifest](../src/autoresearch_filters/igdesign_manifest.json)
remains its authoritative URL/checksum record. The historical `search-1` journal
contains discovery research; `demo` completed verification and final scoring.

## Synthetic examples

- [examples/example_screen.csv](examples/example_screen.csv): 240 synthetic
  candidates for the quickstart; regenerate with `uv run python scripts/make_example_screen.py`.
- [examples/synthetic.csv](examples/synthetic.csv): the deterministic 192-row
  test fixture, used by [configs/synthetic.json](../configs/synthetic.json).

Both are covered by the repository's MIT license and are not experimental evidence.

## Download and prepare

Run commands from the repository root. Downloads are checksum-verified and
reused; preparation refuses to overwrite an existing prepared dataset directory.

```sh
uv run python scripts/download_igdesign.py
uv run python scripts/prepare_igdesign.py
uv run python scripts/download_public_datasets.py
uv run python scripts/prepare_public_datasets.py \
    overath bits-to-binders linsky rocklin cao-bennett proteingym
```

The `proteingym` preparation also creates `public-megascale-proteingym`.
These preparation commands are for a fresh cache; they do not need to be rerun
after the directory reorganization. Add `--init` only when creating new configs
and baseline rules; existing ones are never overwritten. Preparation does not
run rule search, verification, or final scoring.

The [public dataset manifest](manifests/public-datasets.json) resolves each file's
`path` relative to `data/raw/`. Label definitions and reproducibility details are
in [PROVENANCE.md](PROVENANCE.md).

## Previous paths

The November 2026 reorganization moved files without changing CSV/archive bytes.
Scripts, live configs, examples, and docs use the new paths. Historical campaign
config snapshots, journals, and original import logs retain their original text;
their old source paths map as follows:

| Previous location | Current location |
| --- | --- |
| `data/synthetic.csv`, `data/example_screen.csv` | `data/examples/` with the same filenames |
| `data/downloads/<IgDesign CSV>` | `data/raw/igdesign/<same filename>` |
| `data/downloads/public-datasets/<dataset>/<file>` | `data/raw/<dataset>/<file>` |
| `.../prepared/public-<dataset>.csv` | `data/prepared/public-<dataset>/candidates.csv` |
| `.../prepared/public-<dataset>.json` | `data/prepared/public-<dataset>/audit.json` |
| `.../prepared/public-<dataset>.init.log` | `data/prepared/public-<dataset>/init.log` |
| `.../prepared/proteingym-assay-audit.json` | `data/prepared/public-proteingym/assay-audit.json` |
| `data/public-datasets-manifest.json` | `data/manifests/public-datasets.json` |
| `data/dataset-candidates.md` | `data/notes/dataset-candidates.md` |
| Download `.part` and `.chunk*` files | `data/cache/downloads/<dataset>/` |
| Old download README, campaign summaries/log exports, and download plans | Removed during cleanup; original campaign journals remain in `campaigns/` |

Campaign directories, splits, frozen rules, and one-use markers were not moved
or edited. Their evaluation commands read the preserved campaign splits, so
the historical source paths do not affect scoring.

Obsolete `.part` and `.chunk*` files from the completed MegaScale and ProteinGym
downloads were subsequently removed after their complete archives in `raw/`
passed the pinned SHA-256 checks. The downloader recreates `cache/downloads/`
when needed. Source archives, prepared tables, audits, and campaign journals
remain available.
