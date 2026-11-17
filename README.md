# autoresearch-filters

Find a short scoring formula that puts the good candidates first, and keep an
honest record of everything that was tried.

**It is built to be driven by a coding agent — `claude` or `codex`.** Open
[Claude Code](https://github.com/anthropics/claude-code) or
[Codex](https://github.com/openai/codex) in this folder and it reads
[AGENTS.md](AGENTS.md) and runs the search for you: one idea at a time, a
mechanistic reason written before each score, every attempt kept in the log, and
a stop before the two one-use checks so you decide what gets verified. Jump to
[Hand the search to claude or codex](#hand-the-search-to-claude-or-codex) for
the prompt. The commands below are the ones it runs, so doing a round by hand
first is the quickest way to see what it will do.

**You bring a table.** One row per candidate, any number of computed columns,
one experimental outcome with two values. No IDs, no setup, no training data.

```csv
docking_energy,predicted_affinity,shape_complementarity,measured_binding
-37.39,6.038,0.691,0
-44.12,7.742,0.637,1
```

**You get a formula you can read**, and a verdict it had to earn:

```
#2 eval: drop-polar-contacts   roc_auc 0.8069  Δ +0.0361  (noise ±0.0090)   ▲ better
```

It is never a trained model. Every rule is a small JSON file you can read, argue
with, and apply by hand — and every idea that was tried stays in the log,
including the ones that failed.

The method, and the antibody results it was built for, are described in
[Autoresearch Discovery of Interpretable Filter Rules for Antibody Binder
Classification](https://doi.org/10.64898/2026.05.05.723069) (bioRxiv, 2026) —
please [cite it](#citation) if you use this.

## Try it now

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
three commands on the example table shipped here (240 synthetic rows):

```sh
uv run filters init --data data/examples/example_screen.csv  # 1. read the table
uv run filters prepare --config example_screen -c run1    # 2. split it, score the baseline
uv run filters eval drop-polar-contacts -c run1           # 3. try an idea
```

Step 1 writes two files and tells you what it decided:

```
data/examples/example_screen.csv: 240 rows, 6 signals kept
outcome 'measured_binding': success is 1, 84 of 240 usable rows
  docking_energy: lower_is_better [guessed from the name: CHECK IT], range [-54, -19]
  predicted_affinity: higher_is_better [default: CHECK IT], range [3.9, 8.4]
  ...
Wrote configs/example_screen.json and rules/example_screen-baseline.json
```

Step 2 splits the data, scores the baseline, and flags anything suspicious:

```
signal 'docking_energy': oriented discovery AUC 0.7908
signal 'polar_contacts': oriented discovery AUC 0.4413  <-- below 0.5: check the declared direction
#1 eval: example_screen-baseline  · baseline
  roc_auc       0.7709
```

Step 3 tries one idea — drop the signal whose declared direction the data
contradicts — and it earns a verdict:

```
#2 eval: drop-polar-contacts  ▲ better
  roc_auc       0.8069  Δ +0.0361  (noise ±0.0090)
```

## Use your own table

Same three commands, your file:

```sh
uv run filters init --data path/to/your_table.csv
uv run filters prepare --config your_table -c run1
```

`init` prints every decision. Two of them are yours to check:

- **Direction.** It guesses from the column name (`*_energy`, `*_rmsd` mean
  smaller is better) and marks every guess `CHECK IT`. A direction is a claim
  about the signal, never something to fit. Fix one with
  `--lower "docking_energy,rmsd_to_model"` or `--higher "confidence"`.
- **What counts as a signal.** Columns that look measured rather than computed
  (`affinity`, `assay`, `measured_*`) are skipped and the reason is printed, so
  an outcome cannot leak into a rule. `predicted_affinity` is kept.

`configs/NAME.json` is a plain file you own — edit anything `init` got wrong,
then run `prepare`. Other flags: `--label`, `--group` (a target or batch column:
switches to leave-one-group-out), `--signals "a,b,c"`, `--baseline-signal`.
Full reference: [docs/adding-datasets.md](docs/adding-datasets.md).

## Try your own idea

An idea is one change with a reason, written **before** you score it:

```sh
uv run filters idea docking-only \
    --signals "docking_energy,predicted_affinity" \
    --why "The two strongest columns measure the same binding geometry; the rest may be noise." \
    -c run1

uv run filters eval docking-only -c run1
```

That writes `rules/docking-only.json`, with the baseline as its parent. Add
`--weights "1,0.5"` to weight the signals, or `--product` to require both to be
good instead of averaging them. Everything is a plain file; see
[writing a rule by hand](#writing-a-rule-by-hand) for the full grammar.

## Hand the search to claude or codex

This is what the repository is for. Run `claude` or `codex` in this folder —
both read `AGENTS.md` — and paste:

```
Read AGENTS.md and follow it exactly. Run a rule-search campaign on the IgDesign example.

Setup:
- Campaign name: search-1 (pass -c search-1 to every command).
- Prepare with configs/igdesign.json and rules/baseline.json.

Search:
- First analyse campaigns/search-1/data/discovery.csv and record what you find with `filters note`.
- Then try up to 6 ideas, one at a time. Each idea is a new file in rules/ with a unique name,
  a hypothesis written before you evaluate it, and a parent.
- After each eval, add a note saying what you learned and what you will try next, then commit
  the rule and the journal together.
- Do not sweep thresholds or weights. Do not open anything under data/locked/.

Stop:
- Stop when you have used 6 ideas or when nothing beats the baseline beyond noise.
- Do NOT run `filters verify` or `filters final`. Run `filters log --html -c search-1`,
  show me the table, tell me which finalists (if any) you would verify and why, and wait.
```

Swap the two paths in "Prepare with" for the ones `init` wrote to search your
own data. Watch it work at any time:

```sh
uv run filters log --html -c search-1 && open campaigns/search-1/journal.html
```

## What those commands actually did

Your rows are cut into three piles, and only the first one is open:

```
your table ──┬──► discovery      the search plays here, as often as it likes
             ├──► verification   opened once, to check the best idea is real
             └──► holdout        opened once, at the very end, for the honest number
```

Then the loop is just:

1. **Baseline.** Its score on discovery is the number to beat.
2. **One idea at a time.** A new formula, a reason written first, a score.
3. **Repeat** a few times. Every attempt is logged, winners and losers alike.
4. **Verify once.** Up to three finalists; the best is tested on the
   verification pile. If it does not beat the baseline there, the baseline wins.
5. **Final once.** The winner is scored on the holdout. The campaign is over.

Steps 4 and 5 work exactly one time each. That is the point: a formula that
only looked good by luck on discovery gets caught.

To watch all five steps on real data, including the two one-use steps, play the
antibody example (a small public dataset, downloaded on first run):

```sh
export FILTERS_CAMPAIGN=quickstart
uv run filters prepare --config igdesign --baseline baseline
uv run filters eval additive
uv run filters eval gated
uv run filters log --html
uv run filters verify additive gated
uv run filters final
```

Both ideas there are known to fail, so you can see a search end honestly: the
baseline is kept and scored on the holdout.

## Commands

| Command | What it does |
| --- | --- |
| `filters init --data TABLE` | Reads your table; writes a config and a baseline rule |
| `filters prepare --config C` | Splits the data, scores the baseline. Once per campaign |
| `filters idea NAME --why "..."` | Writes a rule file for one idea |
| `filters eval RULE` | Scores one idea on discovery |
| `filters note "TEXT"` | Writes a comment into the log |
| `filters log` | Shows the log. Add `--html` for a page with a chart |
| `filters verify RULE...` | Tests the best of 1-3 finalists on verification. **One use** |
| `filters final` | Scores the winner on the holdout. **One use** |

Anywhere a config or rule is expected, a bare name works: `--config example_screen`
means `configs/example_screen.json`, and `eval docking-only` means
`rules/docking-only.json`.

Each campaign lives in `campaigns/NAME`, chosen with `-c NAME` or
`FILTERS_CAMPAIGN` (default: `main`). That directory is git-ignored: it holds
your split data and your journal, and stays on the machine that ran the search.

## The log

Every command appends a line to `campaigns/NAME/journal.jsonl`. Nothing is ever
removed, so failed ideas stay visible. `filters log` shows it as a table
(shortened here):

```
#  kind     data          rule                      roc_auc        Δ  ±noise  verdict
1  eval     discovery     abb2-hcdr3                 0.6222        –       –  · baseline
3  eval     discovery     abb2-plus-weak-esmfold     0.6157  -0.0065  0.0300  ⚠ guard-broken
4  eval     discovery     abb2-with-regime-esmfold   0.6300  +0.0077  0.0107  ⚠ guard-broken
6  verify   verification  abb2-hcdr3                 0.6003        –       –  ✕ baseline-kept
7  final    holdout       abb2-hcdr3                 0.6797        –       –  ■ final
```

That is a real journal, kept here as
[docs/example-journal.jsonl](docs/example-journal.jsonl): two ideas, both
rejected, baseline kept. Read it as a page with:

```sh
mkdir -p campaigns/example && cp docs/example-journal.jsonl campaigns/example/journal.jsonl
uv run filters log --html -c example
```

How to read a row:

- **Δ** is the change against the baseline on the same folds.
- **±noise** is roughly how much Δ wobbles between folds. A Δ smaller than about
  twice the noise means little. With few folds this is a rough guide only.
- **verdict** is computed for you:

| Verdict | Meaning |
| --- | --- |
| `better` / `worse` | The main score moved by more than the noise |
| `within-noise` | No clear change |
| `guard-broken` | Another score (PR-AUC or precision@K) dropped too far. The idea cannot win |
| `error` | The rule was invalid, for example an unknown signal |

`filters log --html` also writes a page with a chart of every idea in the order
tried, a tree of which idea came from which, and the details of each one.

## Writing a rule by hand

`filters idea` covers the common cases; past that, a rule is just a JSON file in
`rules/`:

```json
{
  "name": "abb2-plus-weak-esmfold",
  "parent": "abb2-hcdr3",
  "hypothesis": "A second structure model may add information.",
  "expression": {
    "kind": "additive",
    "terms": [
      {"signal": "HCDR3 scRMSD (ABB2)", "weight": 1},
      {"signal": "HCDR3 scRMSD (ESMFold)", "weight": 0.25}
    ]
  }
}
```

`parent` is the rule this idea was built from; `hypothesis` is why it should
work, written before you score it. Signals used in scoring formulas are rescaled
to 0-1 so that higher always means better, using the range declared in the config.
Threshold conditions use raw signal values, before rescaling or orientation.

| Kind | What it computes |
| --- | --- |
| `additive` | A weighted average of signals |
| `product` | Signals multiplied together, so all must be good |
| `gated` | A base formula plus a correction that applies only when a signal is above or below a threshold. See [rules/gated.json](rules/gated.json) |
| `conditional` | Choose exactly one of `then` and `else` using a raw-value threshold. Either branch can contain another conditional or a scoring formula. See [rules/tree.json](rules/tree.json) |
| `constant` | Return a specified finite score, useful for tree leaves |

A rule can only use signals listed in the dataset config. It cannot see the
labels, and it cannot run code.

### Nested conditional rules

Write a tree by hand, then evaluate it with the usual `filters eval` command.
This expression, from [rules/tree.json](rules/tree.json), illustrates two nested
decisions using signals in `configs/synthetic.json`:

```json
{
  "kind": "conditional",
  "when": {"signal": "confidence", "op": "<", "value": 0.4},
  "then": {
    "kind": "conditional",
    "when": {"signal": "stabilizer", "op": "<", "value": 0.8},
    "then": {"kind": "constant", "value": 0},
    "else": {"kind": "additive", "terms": [{"signal": "confidence"}]}
  },
  "else": {"kind": "additive", "terms": [{"signal": "confidence"}]}
}
```

This assigns zero when both raw confidence is below 0.4 and raw stabilizer is
below 0.8; otherwise it returns normalized confidence. The thresholds illustrate
syntax and have no claimed experimental benefit.

- `when` requires a signal, one of `<`, `<=`, `>`, `>=`, and a finite threshold.
  Equality follows the chosen operator. For example, confidence exactly 0.4
  takes the outer `else` branch above.
- Both `then` and `else` are required. Either can be `conditional`, `additive`,
  `product`, `gated`, or `constant`. Each row receives only its selected branch's
  score. Independent gates within a `gated` leaf still add their corrections.
- Constants are finite ranking scores, not fitted probabilities; they are not
  normalized or clipped. Formula leaves retain their existing normalization.
- Every condition and leaf must reference only the config's allowed signals,
  including branches that no current row reaches. Nested decisions can express
  AND/OR logic; there are no separate compound-condition operators.
- Trees allow at most 16 conditional levels along a path and 255 decision/leaf
  nodes in total. A `gated` leaf retains its existing gate and term limits.

The CLI and HTML journal display the nested formula and preserve the complete
JSON rule. `filters idea` still drafts additive/product rules; conditional rules
are authored by hand. Tree structure, thresholds, and leaf values are fixed in
the JSON: the evaluator does no fitting or threshold search. Existing campaign
freeze and one-use verification/holdout rules apply to trees as well.

## Citation

If this repository or the method is useful to you, cite the paper:

> Landajuela, M. (2026). *Autoresearch Discovery of Interpretable Filter Rules
> for Antibody Binder Classification.* bioRxiv.
> [doi:10.64898/2026.05.05.723069](https://doi.org/10.64898/2026.05.05.723069)

```bibtex
@article{landajuela2026autoresearch,
  title   = {Autoresearch Discovery of Interpretable Filter Rules for Antibody Binder Classification},
  author  = {Landajuela, Mikel},
  journal = {bioRxiv},
  year    = {2026},
  doi     = {10.64898/2026.05.05.723069},
  url     = {https://www.biorxiv.org/content/10.64898/2026.05.05.723069v2}
}
```

[CITATION.cff](CITATION.cff) carries the same reference in machine-readable
form, so GitHub's "Cite this repository" button points at the paper rather than
at the code.

## More

- [AGENTS.md](AGENTS.md): the rules an agent follows, and why.
- [docs/adding-datasets.md](docs/adding-datasets.md): every config field, and
  what to fix by hand when a guess is wrong.
- [Data catalog and directory guide](data/README.md): example tables, raw
  downloads, prepared datasets, configs, and campaign journals.
- [Data provenance and licensing](data/PROVENANCE.md): sources, labels,
  import decisions, and interpretation limits.
- The one-use limits are enforced by marker files. They prevent accidents; they
  do not stop someone who deletes files on purpose.

Development: `uv run ruff check . && uv run pytest`. Code is [MIT licensed](LICENSE).
