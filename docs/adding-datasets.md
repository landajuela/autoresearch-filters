# Add a dataset

## The quick path

```sh
uv run filters init --data path/to/your_table.csv
```

The table needs one row per candidate, numeric computed columns, and one outcome
column with exactly two values. `init` writes `configs/NAME.json` and
`rules/NAME-baseline.json`, then prints every decision it made. It refuses to
overwrite either file; pass `--name` or `--force`.

Then `uv run filters prepare --config NAME -c run1` starts the campaign: a bare
name means `configs/NAME.json`, and the baseline defaults to the rule `init`
wrote beside it.

| Flag | Use it when |
| --- | --- |
| `--label COLUMN` | The outcome column is not the last one and not obvious from its name |
| `--success VALUE` | Neither outcome value looks like a success (`yes`, `1`, `hit`, ...) |
| `--lower "a,b"` / `--higher "c"` | A guessed direction is wrong |
| `--signals "a,b,c"` | You want exactly these columns as signals, nothing else |
| `--id COLUMN` | Rows have real IDs. Otherwise the source row position is the ID |
| `--group COLUMN` | Rows cluster by target, batch or series. Switches to leave-one-group-out, holding out the last group |
| `--baseline-signal COLUMN` | One established score is the number to beat, instead of the mean of every column |
| `--name NAME` | You want a config name other than the file stem |

What `init` chooses, and how:

- **Signals**: every numeric column that is not the outcome, ID or group, has
  more than one distinct value, and does not look measured rather than computed.
  `predicted_affinity` is kept; a bare `affinity` is skipped, because a measured
  outcome used as a signal leaks the answer into the rule. Everything skipped is
  printed with its reason.
- **Direction**: from `--lower` / `--higher`, else guessed from the column name.
  Every guess is printed and marked. **Check each one.** A negated score is the
  trap: `negative_error` wants `higher_is_better`. A direction is a claim about
  the signal; `prepare` prints an oriented AUC below 0.5 when the data
  contradicts the claim, and that is something to investigate and note, never to
  silently flip.
- **Range**: the observed minimum and maximum, rounded outward. This uses no
  labels. It fixes how every later rule normalizes that signal, so it is part of
  the protocol, not of a rule. A range much wider than the data shrinks the
  signal's influence inside an additive rule and pushes `product` rules towards
  being a re-scaled `additive` rule.
- **Split**: without `--group`, 20% is held out at random and half the rest is
  reserved for verification, with 3-fold stratified CV repeated 5 times on
  discovery. With `--group`, the last group by name becomes the holdout and
  discovery uses leave-one-group-out.
- **precision@K**: K values that stay inside a validation fold.

Nothing here is chosen by looking at which columns predict the outcome. That
choice would be fitting, and it belongs to the search, in the journal, where
every idea is counted.

## Writing a config by hand

Only the signals you list are kept; every other column, including measured
outcomes, is dropped at `prepare` and cannot appear in a rule. Check the source's
license first, and record URL/revision, retrieval date and checksums in
`data/README.md`; prefer a pinned download over vendoring.

```json
{
  "name": "screen",
  "source": "../data/my_screen.csv",
  "id_column": "candidate_id",
  "label_column": "validated",
  "success_value": true,
  "group_column": "target",
  "signals": {
    "negative_error": {
      "direction": "higher_is_better",
      "range": [-30, 0],
      "missing": "drop",
      "description": "Negated predicted error in angstrom"
    }
  },
  "split": {"holdout_groups": ["target-9"], "cv": "logo", "seed": 42},
  "protocol": {"top_k": [5, 10], "primary_metric": "roc_auc", "guard_tolerance": 0.01}
}
```

| Field | Meaning |
| --- | --- |
| `source` | Path relative to the config file, or the built-in loader name `igdesign` |
| `id_column` | Optional. Omit it and the source row position is the candidate ID |
| `success_value` | The outcome value that counts as a success |
| `group_column` | Optional. Required for `logo` CV or `holdout_groups` |
| `signals.*.direction` | `higher_is_better` or `lower_is_better`. A negated error needs **higher** |
| `signals.*.range` | Clip range used to normalize the signal to [0, 1]. Fixed in advance, not fitted |
| `signals.*.missing` | `error` (default) or `drop` the row before splitting. There is no imputation |
| `split.holdout_groups` | Groups that form the final holdout. If empty, a stratified `holdout_fraction` (default 0.2) is used |
| `split.cv` | `logo` (leave one group out) or `random` (stratified `folds` × `repeats`, at least 5 repeats) |
| `protocol.top_k` | The K values for precision@K |
| `protocol.primary_metric` | `roc_auc` or `pr_auc`; the number an idea must improve |
| `protocol.guard_tolerance` | How far any metric may fall below the baseline before the rule is rejected |

After the holdout is removed, a seeded stratified half of the remaining rows is
reserved for the one-use verification. Fix all of these choices before looking
at any rule outcome, then follow [AGENTS.md](../AGENTS.md).

A note on group splits: with few groups, or groups of very different size and
success rate, leave-one-group-out folds are noisy and a macro-averaged metric
can be dominated by one small fold. Look at the per-fold numbers in the journal
before believing a small gain.
