# Add a dataset

1. Check the source's license. Record URL/revision, retrieval date and
   checksums in `data/README.md`. Prefer a pinned download over vendoring.
2. Supply a CSV (or Parquet, if a pandas engine is installed) with a unique
   candidate ID, a label with exactly two values, optionally a group column,
   and numeric computed signals.
3. Write a config. Only the signals you list are kept; every other column,
   including measured outcomes, is dropped at `prepare` and cannot appear in a rule.

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
