# Agent instructions: autoresearch-filters

The deliverable is a deterministic, interpretable JSON rule plus an honest
journal of how it was found. No fitting inside a rule. Never invent results.

## The loop

All commands run from the repository root. `-c NAME` picks the campaign
directory `campaigns/NAME` (default `main`, or `$FILTERS_CAMPAIGN`).

```sh
uv sync --frozen --dev
uv run filters prepare --config configs/igdesign.json --baseline rules/baseline.json -c NAME
```

For a dataset that has no config yet, write one first with
`uv run filters init --data path/to/table.csv`, check every direction and skipped
column it reports, and say in a note what you changed and why.

Then repeat, one small idea at a time:

1. Write a new file in `rules/` (never edit an evaluated one). Give it a unique
   `name`, a `hypothesis` stating the change and its expected mechanism, and a
   `parent`: the name of the rule it was derived from.
2. `uv run filters eval rules/my-idea.json -c NAME`. The outcome is appended to
   `campaigns/NAME/journal.jsonl` automatically, including failures and errors.
3. `uv run filters note "..." -c NAME` to record what you looked at in the
   discovery data, why the next idea follows, or why you are stopping.
4. Commit the rule, with the outcome in the message:
   `git add rules/my-idea.json && git commit -m "experiment: ..."`
   `campaigns/` is git-ignored, so the journal stays on this machine: it is the
   record of the search, not a build artifact. Keep the campaign directory, and
   share `filters log --html` output rather than rewriting history. Each journal
   row already stores the commit it was produced at.

`uv run filters log -c NAME` shows the whole search; `--html` also writes a page
with the progress chart and the lineage of ideas.

To finish, name 1-3 finalists. Both of these work exactly once per campaign:

```sh
uv run filters verify rules/a.json rules/b.json -c NAME   # picks on discovery, tests on reserved rows, freezes
uv run filters final -c NAME                              # scores the frozen rule on the locked holdout
```

## Rules of the game

1. **Only discovery data informs choices.** You may analyze
   `campaigns/NAME/data/discovery.csv` freely. Never open anything under
   `campaigns/NAME/data/locked/`, and never delete a `*-used.json` marker,
   `frozen.json`, or a campaign directory to get another attempt.
2. **The journal is append-only.** Never edit or remove a line. A rejected idea
   stays rejected; a new idea gets a new rule file and a new row.
3. **Few, motivated ideas.** Each idea needs a mechanistic reason written before
   it is evaluated. Do not sweep thresholds or weights and keep the argmax; if
   you check a threshold's neighbourhood, say so in a note and prefer the center
   of a broad plateau to a spike. Every evaluation is counted in the journal.
4. **Read the verdict honestly.** `within-noise` is not a win. `guard-broken`
   means ROC-AUC, PR-AUC or a precision@K fell more than the tolerance below the
   baseline, and such a rule cannot be selected. `noise` is a rough yardstick
   from a handful of folds, not a significance test; look at the per-fold values.
5. **Stop when gains do not transfer.** After `verify`, the campaign is frozen
   whatever the outcome. More research needs genuinely fresh reserved data.
6. **Infrastructure stays fixed during a campaign.** Change only `rules/*.json`
   and the journal (through the commands). Do not touch `src/`, configs, splits,
   metrics or tolerances to rescue a result. A real bug needs a separate,
   disclosed fix and a new campaign.
7. **Signals are computed oracles only.** Labels, measured outcomes, IDs and
   group names are never rule terms. A signal's declared direction is
   authoritative; `prepare` prints each signal's oriented AUC on discovery, and a
   value below 0.5 is something to investigate and note, never to silently flip.

The locked directory is a convention that prevents accidents, not a security
boundary. Never create a remote or push unless the human asks.
