# autoresearch-filters

A small, CPU-only harness for discovering **interpretable, training-free
screening rules**. A coding agent (Claude, Codex, ...) proposes one small JSON
formula at a time, a fixed evaluator scores it, and every step lands in a
journal you can inspect later. The output is a readable rule, never a fitted model.

## The loop

1. **Prepare (once).** The data is cut into three piles: *discovery* (look at it
   freely), *verification* (used once) and the *final holdout* (used once). The
   baseline rule is scored on discovery; that is the number to beat.
2. **Try an idea.** Write a new JSON rule with a sentence saying why it should
   help, and run `filters eval`. The result is appended to the journal.
3. **Repeat** a few times, using what was learned to choose the next idea.
4. **Verify (one shot).** Name 1-3 finalists. The best eligible one on discovery
   is tested once on the verification pile. If it does not beat the baseline
   there, the baseline is kept. Either way the campaign is now frozen.
5. **Final (one shot).** The frozen rule is scored on the locked holdout.

The agent follows [AGENTS.md](AGENTS.md). Nothing is pushed anywhere.

## Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). The public
IgDesign example downloads seven small CSVs with pinned checksums.

```sh
uv sync --frozen --dev
export FILTERS_CAMPAIGN=quickstart          # or pass -c quickstart to every command

uv run filters prepare --config configs/igdesign.json --baseline rules/baseline.json
uv run filters eval rules/additive.json
uv run filters eval rules/gated.json
uv run filters note "Both ideas break a guard; verifying them anyway as the pre-stated finalists."
uv run filters log --html                   # table in the terminal + campaigns/quickstart/journal.html

uv run filters verify rules/additive.json rules/gated.json   # one use
uv run filters final                                         # one use
```

This replays the shipped demonstration; its ideas and outcomes are already
public, so it is not a fresh study. For a network-free run use
`--config configs/synthetic.json --baseline rules/synthetic.json`.

## The journal

Everything a campaign did is in `campaigns/NAME/journal.jsonl`: one JSON line per
event, appended by the commands themselves. `filters log` prints it:

```
#  kind     data          rule                      parent      roc_auc        Δ  ±noise  pr_auc  precision@5  precision@10  precision@20  verdict
0  prepare  igdesign: discovery 361, verification 361, holdout 125 rows
1  eval     discovery     abb2-hcdr3                –            0.6222        –       –  0.4034       0.4000        0.3833        0.3500  · baseline
2  note     Replay of the original demonstration ...
3  eval     discovery     abb2-plus-weak-esmfold    abb2-hcdr3   0.6157  -0.0065  0.0300  0.3929       0.3667        0.3833        0.3667  ⚠ guard-broken
4  eval     discovery     abb2-with-regime-esmfold  abb2-hcdr3   0.6300  +0.0077  0.0107  0.4198       0.4000        0.3500        0.3417  ⚠ guard-broken
5  note     Both ideas break a guard on discovery ...
6  verify   verification  abb2-hcdr3                –            0.6003        –       –  0.4048       0.3333        0.3167        0.3417  ✕ baseline-kept
7  final    holdout       abb2-hcdr3                –            0.6797        –       –  0.4150       0.6000        0.6000        0.5000  ■ final
```

That is the committed [demo journal](campaigns/demo/journal.jsonl), computed by
this code on the pinned public release. Both ideas were rejected and the
baseline was kept: a small demonstration of the mechanics, not a benchmark result.

- **Each row stands alone.** It holds the rule's name, parent, hypothesis,
  readable formula, full JSON, metrics, Δ against the baseline on the same data,
  per-fold values of the primary metric, the verdict, and the git commit that
  was checked out when it ran.
- **`parent`** links an idea to the rule it came from, so the journal is a tree.
- **Verdicts** are computed, not hand-written: `better`, `within-noise`, `worse`
  (primary-metric change against twice the `noise`), or `guard-broken` (ROC-AUC,
  PR-AUC or a precision@K fell more than `guard_tolerance` below the baseline).
  Errors such as an unknown signal are logged as `error`.
- **`noise`** is the standard error of the per-fold difference from the
  baseline. With a handful of folds it is a rough yardstick, not a significance test.
- **`filters log --html`** writes one self-contained page: headline tiles, the
  primary metric of every idea in the order tried, the lineage tree, and the
  full journal with expandable details. It is regenerated on demand and git-ignored.

Commit `journal.jsonl` together with each new rule. The campaign's `data/`
directory is git-ignored.

## Rule language

`n(signal)` clips a signal to its configured range, scales it to [0, 1] and
orients it so that higher is better.

| Kind | Formula |
| --- | --- |
| `additive` | `sum(w * n(signal)) / sum(w)`, weights ≥ 0 |
| `product` | `product(n(signal) ** exponent)`, exponents > 0 |
| `gated` | an additive or product base, plus `weight * (n(signal) - center)` terms that are active only where a raw signal passes a threshold |

See [rules/gated.json](rules/gated.json) for all of it in one file. A gate's
weight may be negative, and a `center` of 0.5 lets it both reward and penalize.
Rules cannot reference labels or any column outside the config's signal list,
and cannot load code or fit anything.

## How a rule gets accepted

- **Discovery** scores are cross-validated: leave-one-group-out, or repeated
  stratified K-fold. Nothing is fitted, so folds only define how scores are averaged.
- **`verify`** considers only finalists that improve the primary metric on
  discovery without breaking a guard, takes the best, and accepts it only if it
  also improves the primary metric on the reserved rows with all guards intact.
  The row records the discovery gain, the transfer gain, their gap, and how many
  ideas had been evaluated before.
- **One use** is enforced by marker files written before the reserved data is
  read. This prevents accidents; it is not tamper-proof against someone who
  deletes files on purpose.

To use your own data see [docs/adding-datasets.md](docs/adding-datasets.md);
for the example's provenance and licensing see [data/README.md](data/README.md).

## Development

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Dependencies are NumPy, pandas, scikit-learn, Pydantic and Typer. Code is
[MIT licensed](LICENSE). The repository's first version had per-run record files,
hash seals and a wider rule language; its original demonstration records are in
git history (`results/demo/` at commit `93e9ecb`) and report the same numbers
as the demo journal above.
