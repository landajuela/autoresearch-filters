# autoresearch-filters

A small, CPU-only research harness for discovering **interpretable,
training-free screening rules**. A coding agent proposes a small change to a
JSON formula, runs a fixed evaluation, reads the recorded metrics, commits the
rule, appends its outcome to an audit log, and uses the evidence to decide what
to try next. Read [AGENTS.md](AGENTS.md) for the canonical agent prompt.

The output is an auditable rule, never a fitted random forest, boosted tree or
neural network. You supply already computed oracle signals and real outcome
labels. The agent can be Codex, Claude, or another coding agent; no LLM API or
model weights are bundled. This is a from-scratch implementation of the loop,
not a reproduction of private prototypes or a claimed benchmark winner.

## Quickstart: public IgDesign data

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
from this repository. The pinned download is seven small CSVs (under 1 MB total).
No model inference, GPU or training is required. The evaluation itself is a
short laptop workload; first installation/download time depends on your network.

```sh
uv sync --frozen --dev
mkdir -p results/local
uv run filters prepare --config configs/igdesign.json --work work/igdesign

uv run filters eval --work work/igdesign --rule rules/baseline.json \
  --output results/local/00-baseline.json > results/local/00-baseline.log

# Register the exact two hypotheses before testing their outcomes.
uv run filters transfer-check --work work/igdesign --plan experiments/plan.json
uv run filters eval --work work/igdesign --rule rules/additive.json \
  --output results/local/01-additive.json > results/local/01-additive.log
uv run filters eval --work work/igdesign --rule rules/gated.json \
  --output results/local/02-gated.json > results/local/02-gated.log
uv run filters transfer-check --work work/igdesign \
  --output results/local/03-transfer.json > results/local/03-transfer.log

# The selected rule is now frozen. This endpoint can be called only once.
uv run filters final --work work/igdesign \
  --output results/local/04-final.json > results/local/04-final.log
uv run filters report --record results/local/04-final.json
```

This replays a **pre-specified demonstration**, not a fresh independent benchmark
study: the shipped candidates and public example results are already visible.
Use fresh reserved evidence for new scientific selection. `prepare` is idempotent
for an unchanged campaign. Run filenames are immutable; transfer and final are
one-use. Do not delete markers or change seeds to make more attempts.

The example uses the public [IgDesign release](https://github.com/AbSciBio/igdesign)
and its supplied `Binder` labels. The loader uses inverse-folding candidates from
seven unblinded antibody–antigen systems and existing scRMSD signals. The fixed
final system is `Utomilumab-TNFRSF9`; the remaining systems form a train pool split
into discovery and reserved verification rows. Both halves use leave-one-system-out
CV. The final system is never scored during dev. See
[data provenance, exclusions and licensing](data/README.md) for exact decisions.
Upstream data are downloaded with pinned SHA-256 checksums, never vendored.

For a network-free dataset after package installation:

```sh
uv run filters prepare --config configs/synthetic.json --work work/synthetic
uv run filters eval --work work/synthetic --rule rules/synthetic.json \
  --output results/local/synthetic.json
uv run pytest
```

## Dataset schema

[Pydantic v2 models](src/autoresearch_filters/config.py) reject unknown keys,
invalid ranges, contradictory options and outcome columns in the signal space.
A JSON dataset config declares:

| Field | Meaning |
| --- | --- |
| `source` | CSV/Parquet path, or trusted preparation-only `module:function` loader |
| `id_column` | Stable unique candidate ID for persisted partitions and tie-breaking |
| `label_column`, `success_value` | Binary experimental outcome and positive value |
| `group_column` | Optional system/target grouping |
| `signals` | Allowlisted computed oracles: direction, numeric range, missing policy, optional units/description |
| `exclude_columns` | Measurements/metadata explicitly forbidden in rules |
| `split` | Holdout, verification and CV strategies; fixed seeds, folds and repeats |
| `protocol` | Top-K, partial-AUC limit, sign checks, objective, guards and search budget |

Each signal declares `higher_is_better` or `lower_is_better`. A negated error can
need **higher**-is-better even though a positive error needs **lower**-is-better.
Oriented single-signal AUC is checked on discovery rows and warns loudly or
asserts when it contradicts that declaration. Nothing silently flips signs.
Missing policies are `error`, `drop`, or a pre-specified `constant`; no fitted
imputation occurs. See [how to add a dataset](docs/adding-datasets.md).

## Rule language, including gates

Let `n(signal)` clip-normalize to [0,1] in the dataset's declared direction.
The same formula works on new column semantics without code changes.

| Primitive | Formula/behavior |
| --- | --- |
| Hard filter | Conjunctions/disjunctions of raw comparisons, producing 0 or 1 |
| Soft additive | `sum(w * n(signal)) / sum(w)` with nonnegative weights |
| Product | `product(n(signal) ** exponent)` with positive exponents |
| Gated | Base score plus signed, optionally centered terms active only in a named regime |

A gate has a signal, threshold and active side, a list of adjustments, and optional
child gates. Children require all ancestor conditions. Opposite signed weights
in different regimes can reward a signal in one region and discount it elsewhere.
A 0.5 center allows both penalties and rewards. Custom clip ranges are allowed;
direction overrides must agree with the schema. See [gate arithmetic and diagnostic](docs/gates.md)
and the concrete [gated rule](rules/gated.json).

The canonical pretty-printer emits a readable pseudo-formula with explicit ranges
and directions. Lossless round trips use JSON; the pseudo-formula is explanatory,
not executable code. No rule can load a model, import Python, call a loader, or fit.

## Fixed evaluation and selection

- Splits: external holdout, seeded stratified random holdout, group-disjoint holdout;
  random CV, leave-one-group-out and repeated group-disjoint CV. Partitions are
  persisted with IDs, hashes and seeds. At least five repeat seeds are required.
- Metrics: natural ROC-AUC, balanced-subsample ROC-AUC, PR-AUC (average precision),
  standardized partial ROC-AUC, and success/precision/recall@K. Means and sample
  SDs are reported over repeats and over folds. LOGO repeat SD can be zero because
  natural folds repeat exactly; it is not an uncertainty guarantee.
- Prevalence matching: optionally reweight negatives to a pre-specified target
  prevalence. A separate explicit opt-in can freeze the holdout's aggregate ratio
  during preparation; it is off in the shipped example. Dev never opens its rows.
- `eval --mode dev` measures discovery CV. `eval --mode search` enforces a bounded
  hypothesis-generation budget. Neither authorizes accepting a rule.
- `transfer-check --plan` seals 1–3 candidates and their reasons. The check selects
  on discovery and measures on reserved rows, guarding PR and top-K along with ROC.
  It then freezes either the surviving candidate or the original baseline.
- `final` evaluates that frozen choice once on the locked holdout. Dev code has no
  source/holdout loader. Consumed markers cannot be reset through the CLI.

**Never take a large dev scan's argmax as a discovery.** Prefer small mechanistic
hypotheses and broad threshold plateaus. Check local discriminativeness **and**
redundancy before adding a gate. Record negative results. Stop if dev gains fail
to transfer; more CV repeats do not repair selection bias. The full
[selection rationale and boundary](docs/selection.md) describes limitations,
undefined metrics, aggregation and the deliberately conservative one-use policy.

## Audit trail and demonstration

Every evaluated run emits an immutable JSON record and a human-readable stdout
log. Records embed the formula, rule and implementation hashes, pre-run git state,
source/config/partition/cache hashes, seeds, package versions and all metrics.
The normalized snapshot cache is invalidated by config/preprocessing changes.

After committing a rule, append an audit row **from the JSON**, not by scraping:

```sh
uv run filters report --record results/local/01-additive.json \
  --log results/local/results.jsonl --commit HEAD --rule-path rules/additive.json \
  --decision hypothesis --note 'Pre-stated complementary score; transfer pending.'
```

The append command checks that the cited commit contains the exact evaluated rule
and evaluator implementation. The pre-run commit and post-run commit are separate
fields, avoiding self-reference. `accepted` is permitted only for successful
transfer records. Keep all rejected hypotheses, with explanatory notes.
See [the measured demonstration](results/demo/README.md) for committed records
and outcomes. No performance target was set and no favorable result is promised.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pre-commit install
```

The GitHub Actions workflow runs lint, format and the synthetic suite without
fetching IgDesign. Core dependencies are NumPy, pandas, scikit-learn, Pydantic
and Typer; no ML training stack is installed. Parquet requires an optional,
already installed pandas engine; CSV works out of the box. See
[CONTRIBUTING.md](CONTRIBUTING.md). Code is [MIT licensed](LICENSE).
[CITATION.cff](CITATION.cff) is explicitly a placeholder for release metadata.
