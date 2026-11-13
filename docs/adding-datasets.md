# Add a dataset

1. Check source licensing and whether redistribution is allowed. Record the
   source URL/revision, retrieval date and checksums in `data/README.md`. Prefer
   a pinned download over vendoring. Never invent missing labels or provenance.
2. Supply a CSV with a stable unique candidate ID, exactly two non-missing label
   values, optional non-missing groups, and computed numeric oracle signals.
   Configure `success_value` with the same type as the loaded label. Labels,
   experimental measurements, group names and identifiers are not rule features.
3. Copy a JSON config. Paths in file sources are relative to the config file.
   List only admissible signals. For each, declare `direction`, finite increasing
   `range`, and `missing` policy (`error`, `drop`, or `constant` with `value`).
   No mean/median imputation or other learned preprocessing occurs. Missing IDs,
   groups or labels fail. Non-numeric and infinite signals fail. Drops happen
   before splitting and are audited inside the preparation vault.
4. Pre-specify the holdout (`random`, `group`, or `external`), verification
   (`split_positive` or `group`), dev CV (`random`, `logo`, or `group`), seed,
   folds, at least five repeats, top-K values, partial-AUC FPR limit, primary
   metric and guard tolerances. Do not choose these using rule outcomes.
5. Use a simple declarative rule referencing the configured signals. Prepare
   once and check discovery sign diagnostics. Resolve a schema mistake as a
   disclosed protocol correction, not by silently flipping a rule's sign.
6. Register a small candidate family and follow [AGENTS.md](../AGENTS.md).

```json
{
  "name": "screen",
  "source": {"kind": "file", "path": "../data/my_screen.csv"},
  "id_column": "candidate_id",
  "label_column": "validated",
  "success_value": true,
  "group_column": "target",
  "signals": {
    "negative_error": {
      "direction": "higher_is_better", "range": [-30, 0],
      "missing": {"policy": "constant", "value": -30},
      "units": "angstrom", "description": "Negated predicted error",
      "oracle": true, "expected_positive_auc": true
    }
  },
  "exclude_columns": ["experimental_affinity"],
  "split": {"holdout": "group", "dev": "group", "folds": 3, "repeats": 5, "seed": 42},
  "protocol": {"top_k": [5, 10], "max_fpr": 0.1, "sign_policy": "error"}
}
```

For pre-split external data, set `split.holdout` to `external` and
`split.external` to `{"kind":"file","path":"../data/test.csv"}`. Pool and
external files use the same schema. IDs must be disjoint; if groups are supplied,
those must be disjoint too. Enough positives and negatives must remain in each
partition, and enough groups must remain for group CV.

Parquet paths are supported through pandas if a Parquet engine is already
installed; CSV needs no additional dependency. For bespoke sources use
`{"kind":"loader","hook":"your_package.module:load","kwargs":{...}}`.
The hook returns a pandas DataFrame. Only trusted preparation invokes this Python
hook; it is not part of the closed rule language. The optional `cache_dir` keyword
is resolved relative to the config. Other custom kwargs are passed unchanged.
A loader should pin and verify its inputs, like the shipped IgDesign loader.
