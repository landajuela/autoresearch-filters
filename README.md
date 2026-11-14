# autoresearch-filters

Let a coding agent (Claude, Codex, ...) search for a simple scoring formula
that ranks good candidates above bad ones, and keep an honest log of
everything it tried.

The result is a short, readable formula in a JSON file. It is never a trained model.

## Your own data in three commands

One row per candidate: as many computed columns as you like, plus **one
experimental outcome column with two values**. No ID column and no group column
are needed.

```csv
docking_energy,predicted_affinity,shape_complementarity,measured_binding
-37.39,6.038,0.691,0
-44.12,7.742,0.637,1
```

```sh
uv sync --frozen --dev

# 1. read the table; write a dataset config and a baseline rule
uv run filters init --data data/example_screen.csv

# 2. split the data and score the baseline
uv run filters prepare --config configs/example_screen.json \
    --baseline rules/example_screen-baseline.json -c run1

# 3. try an idea
uv run filters eval rules/example_screen-drop-weak.json -c run1
```

That runs on `data/example_screen.csv`, a synthetic 240-row table in exactly the
shape above. Step 3 is a real first idea: it drops the one signal whose declared
direction the discovery rows contradict, and earns a `better` verdict.

With your own table, swap in its path. `init` prints everything it decided, and
two of those decisions are yours to check:

- **Direction.** It guesses from the column name (`*_energy`, `*_rmsd` and the
  like mean smaller is better) and prints every guess. A direction is a claim
  about the signal, never something to fit. Correct one with
  `--lower "docking_energy,rmsd_to_model"` or `--higher "confidence"`.
- **What is a signal.** Columns that look measured rather than computed
  (`affinity`, `assay`, `measured_*`) are skipped, and the reason is printed. A
  measured outcome used as a signal would leak the answer into the rule.

`configs/NAME.json` is a plain file you own; edit it if a guess is wrong. Other
flags: `--label COLUMN` for the outcome, `--group COLUMN` for a target or batch
column (switches to leave-one-group-out), `--signals "a,b,c"` to pick columns
yourself, `--baseline-signal COLUMN` to make one signal the number to beat
instead of the mean of all of them.

## Launch a search

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), open
Claude Code or Codex in this folder (`claude` or `codex`), and paste:

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

Watch the progress at any time:

```sh
uv run filters log --html -c search-1
open campaigns/search-1/journal.html
```

When you are happy with the finalists, tell the agent: "verify X and Y, then
run final". Those two steps work only once per campaign.

Change the campaign name for each new search. For your own data, run `filters
init` first and point the prompt at the config and baseline rule it wrote (see
[docs/adding-datasets.md](docs/adding-datasets.md)).

## How it works

Your data is split into three piles:

| Pile | Who can look | Used for |
| --- | --- | --- |
| **Discovery** | The agent, freely | Trying ideas |
| **Verification** | Nobody, until the end | One check that the best idea is real |
| **Holdout** | Nobody, until the very end | The final, honest score |

Then the agent works in a loop:

1. **Start** from a baseline formula. Its score on discovery is the number to beat.
2. **Try an idea**: write a new formula with one sentence on why it should help, and score it.
3. **Repeat** a few times.
4. **Verify once**: pick up to three finalists. The best one is tested on the
   verification pile. If it does not beat the baseline there, the baseline wins.
5. **Final, once**: the winner is scored on the holdout. The campaign is over.

Steps 4 and 5 work only one time each. That is the point: a formula that only
looked good by luck on discovery gets caught.

## Run the antibody example end to end

The example above stops before the one-use steps. This one plays a whole
campaign, including both of them, on a small public antibody dataset
(downloaded on first run):

```sh
uv sync --frozen --dev
export FILTERS_CAMPAIGN=quickstart

uv run filters prepare --config configs/igdesign.json --baseline rules/baseline.json
uv run filters eval rules/additive.json
uv run filters eval rules/gated.json
uv run filters log --html

uv run filters verify rules/additive.json rules/gated.json
uv run filters final
```

It replays two ideas that are already known to fail, so you can watch a search
end honestly: the baseline is kept and scored on the holdout.

## Commands

| Command | What it does |
| --- | --- |
| `filters init --data T` | Reads your table; writes a config and a baseline rule |
| `filters prepare` | Splits the data and scores the baseline. Once per campaign |
| `filters eval RULE` | Scores one idea on discovery |
| `filters note "TEXT"` | Writes a comment into the log |
| `filters log` | Shows the log. Add `--html` for a page with a chart |
| `filters verify RULE...` | Tests the best of 1-3 finalists on verification. **One use** |
| `filters final` | Scores the winner on the holdout. **One use** |

Each campaign lives in `campaigns/NAME`. Choose it with `-c NAME` or
`FILTERS_CAMPAIGN`. That directory is git-ignored: it holds your split data and
your journal, and it stays on the machine that ran the search.

## The log

Every command adds a line to `campaigns/NAME/journal.jsonl`. Nothing is ever
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

This is a real journal, kept in the repo as
[docs/example-journal.jsonl](docs/example-journal.jsonl): two ideas, both
rejected, baseline kept.

How to read it:

- **Δ** is the change against the baseline on the same pile.
- **±noise** is roughly how much Δ wobbles between folds. A Δ smaller than about
  twice the noise means little. With few folds this is a rough guide only.
- **verdict** is computed for you:

| Verdict | Meaning |
| --- | --- |
| `better` / `worse` | The main score moved by more than the noise |
| `within-noise` | No clear change |
| `guard-broken` | Another score (PR-AUC or precision@K) dropped too far. The idea cannot win |
| `error` | The rule was invalid, for example an unknown signal |

`filters log --html` writes `campaigns/NAME/journal.html` with a chart of every
idea in the order tried, a tree showing which idea came from which, and the
details of each one. To read the example above that way:

```sh
mkdir -p campaigns/example && cp docs/example-journal.jsonl campaigns/example/journal.jsonl
uv run filters log --html -c example
```

## Writing a rule

A rule is a JSON file in `rules/`:

```json
{
  "name": "abb2-plus-weak-esmfold",
  "hypothesis": "A second structure model may add information.",
  "parent": "abb2-hcdr3",
  "expression": {
    "kind": "additive",
    "terms": [
      {"signal": "HCDR3 scRMSD (ABB2)", "weight": 1},
      {"signal": "HCDR3 scRMSD (ESMFold)", "weight": 0.25}
    ]
  }
}
```

`parent` is the rule this idea was built from. There are three kinds of formula.
Every signal is first rescaled to 0-1 so that higher always means better.

| Kind | What it computes |
| --- | --- |
| `additive` | A weighted average of signals |
| `product` | Signals multiplied together, so all must be good |
| `gated` | A base formula, plus a correction that only applies when a signal is above or below a threshold. See [rules/gated.json](rules/gated.json) |

A rule can only use the signals listed in the dataset config. It cannot see the
labels and cannot run code.

## More

- [AGENTS.md](AGENTS.md): the rules the agent follows.
- [docs/adding-datasets.md](docs/adding-datasets.md): every config field, and
  what to fix by hand when a guess is wrong.
- [docs/example-journal.jsonl](docs/example-journal.jsonl): a finished campaign,
  as `filters log` reads it.
- [data/README.md](data/README.md): where the example data comes from, and its license.
- The one-use limits are enforced by marker files. They prevent accidents; they
  do not stop someone who deletes files on purpose.

Development: `uv run ruff check . && uv run pytest`. Code is [MIT licensed](LICENSE).
