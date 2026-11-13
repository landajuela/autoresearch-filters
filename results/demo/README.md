# Measured IgDesign demonstration

All numbers below were computed by this repository on the pinned public release.
This is a small demonstration of the audit and selection mechanics, not an
optimized benchmark or evidence that the gated rule generalizes. Both proposed
changes were rejected. No thresholds, weights, seeds or tolerances were retuned.

| Stage | Rule | ROC-AUC | PR-AUC (AP) | Precision@10 | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| Discovery | [Baseline](00-baseline.json) | 0.622241 | 0.403403 | 0.383333 | Initial baseline |
| Discovery | [Flat additive](03-additive.json) | 0.615707 | 0.392905 | 0.383333 | Rejected: ROC/PR and precision@5 |
| Discovery | [Gated](04-gated.json) | 0.629986 | 0.419848 | 0.350000 | Rejected: precision@10 |
| Reserved verification | [Baseline](05-transfer.json) | 0.600349 | 0.404750 | 0.316667 | Baseline retained; no candidate eligible |
| Locked final | [Baseline](06-final.json) | 0.679676 | 0.415034 | 0.600000 | One-use final, no further selection |

Discovery and verification metrics are macro means across six system folds.
Five seeded LOGO repeats reuse those same folds, so natural-metric repeat SD is
zero; this does **not** measure uncertainty across new systems. The JSON records
also provide fold SD, valid-fold counts, balanced ROC resampling, partial AUC,
and top-K success/precision/recall at K=5,10,20. Final is a single held-out system
with 125 candidates (28 binders), not another CV mean. Its reported SD of zero
is the one-observation convention, not an error bar.

## What happened

1. The simple ABB2 HCDR3 rule established the baseline. Direction checks flagged
   pooled ABB3 and ESMFold AUC below 0.5. The raw scRMSD directions remained
   lower-is-better; no automatic sign flip occurred.
2. A [bounded diagnostic](01-gate-diagnostic.json) checked the pre-stated
   threshold grid 2, 2.25, 2.5, 2.75, 3 angstrom. At the pre-stated center 2.5,
   ESMFold oriented AUC was 0.615215 inside the regime versus 0.395835 overall,
   with local base-signal Pearson correlation -0.323653 and 32 positives among
   131 rows. These descriptive statistics motivated a hypothesis; they do not
   establish independence, a stable optimum, or statistical significance. We
   retained 2.5 rather than selecting the scan maximum at 2.75.
3. Two exact candidates were [registered](02-registration.json) before either
   candidate evaluation: a weak global ESMFold term and the same type of evidence
   applied only in the less-consistent ABB2 regime, centered at 0.5. Weight 0.25
   was pre-specified and never swept.
4. The flat additive comparator reduced ROC/AP and precision@5; although
   precision@20 improved, this failed the fixed guards.
5. The gate improved discovery ROC/AP/partial AUC, but precision@10 dropped by
   0.033333, exceeding the 0.01 tolerance. This is a recorded negative result,
   showing why a ROC gain alone does not justify keeping a screening rule.
6. Neither candidate qualified for transfer selection. The [transfer command](05-transfer.json)
   retained and evaluated the baseline on reserved rows. **No candidate was
   measured on verification**, so there is no candidate-transfer estimate.
   The zero gain/optimism fields in that record compare baseline with itself.
7. The frozen baseline was evaluated once on Utomilumab–TNFRSF9. No search or
   selection followed this final result.

## Evidence and reproduction

- [Append-only results log](results.jsonl): six rows derived from immutable run
  records, with full commit hashes, rule hashes, decisions and reasons.
- JSON files contain all metrics, rule/config/dataset/partition/implementation
  hashes, pre-run git state, environment versions and seeds. Matching `.log`
  files capture actual command output, including sign warnings.
- [Registered plan](../../experiments/plan.json) and [dataset config](../../configs/igdesign.json)
  describe all discretionary choices. The evaluator implementation was frozen
  before this demonstration. Post-run audit commits verify both the rule and
  interpreter hash; the record's earlier git commit is intentionally different.
- The local ignored `work/igdesign/` directory holds persisted discovery,
  verification and holdout partitions and the consumed markers. Public records
  carry their hashes; preparation recreates the same partitions from the pinned
  input and seeds. Candidate data and experimental labels are not committed.
- Run `uv run python scripts/verify_audit.py results/demo/results.jsonl` to
  verify record hashes and committed rule/evaluator provenance without data reads.

The [README quickstart](../../README.md#quickstart-public-igdesign-data) replays
fixed hypotheses into a fresh local output directory. Reproduction does not
restore independent unseen evidence for further tuning. The Git history records
separate implementation, hypothesis, rejected-experiment and audit commits.
No GitHub remote is configured.
