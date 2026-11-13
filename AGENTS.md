# Agent instructions: autoresearch-filters

## Hard constraints — read before every experiment

**The artifact is a deterministic, interpretable JSON rule. No fitting inside a
rule. The audit trail is part of the deliverable. Never invent results.**

1. **Select only with train-pool evidence.** The final holdout is locked, opened
   once after the rule is frozen, and never used to choose a rule, threshold,
   gate, metric, split, or stopping time. Never inspect `work/*/vault/`.
2. **Never select a gate/threshold/term by scanning many candidates and taking
   the dev-CV argmax.** Screens and extra guards can still remember the search
   maximum. A bounded scan is a hypothesis generator, not selection evidence.
3. **Pre-specify 1–3 mechanistically motivated candidates.** Register exact rule
   snapshots. Select on discovery rows and measure the chosen rule on the
   disjoint verification half, including the other half of the positives.
   A group-reserved verifier is also supported. Do not inspect
   `work/*/transfer/verification.csv` or use its labels in rule design.
4. **Use the gate diagnostic.** A useful adjustment should discriminate better
   inside its regime than overall, with adequate positive/negative support,
   and add information beyond the base signals. Check the reported local
   correlations. Local AUC alone is not sufficient; correlation alone is not
   proof of independence. A signal may need opposite signed weights in two gates.
5. **Re-map thresholds finely before judging them.** Look for a broad plateau
   and prefer its center to a narrow argmax spike. State the grid and center
   rationale in advance where possible. Do not turn a plateau check into a
   hidden manual sweep. `search` has a fixed evaluation budget; one bounded
   `gate-scan` grid is allowed per campaign.
6. **At least five distinct CV repeat seeds.** Do not mistake reshuffled folds
   for independent replications. LOGO repeats have identical natural-balance
   folds: zero repeat SD is not certainty. Also inspect fold SD. Dev-to-unseen
   optimism can exceed the repeat noise band; a gain smaller than the observed
   optimism gap is not evidence of transfer. Never estimate that gap by
   repeatedly opening the final holdout.
7. **Guard both ranking objectives.** While optimizing ROC, watch PR-AUC and
   precision@K; while optimizing PR/partial AUC, also watch ROC. Reject
   deterioration beyond the precommitted tolerance. Prefer a comparable point
   on a stable plateau to a trade-off hidden by a single friendly metric.
8. **Record negative results and errors.** Every evaluated hypothesis, including
   rejected gates and sign failures, gets an immutable record and an audit row
   with the reason. Never erase a failed experiment or re-label it as a win.
9. **Stop when gains do not transfer.** Large dev gain with negligible transfer,
   growing optimism, or broken guards is a stop signal, not an invitation to
   accumulate more gates. The provided one-use verifier freezes the campaign
   after its decision, successful or not. Do not reset markers or change seeds
   to get another chance. Further research needs genuinely fresh reserved data.
10. **Keep infrastructure fixed.** During discovery edit only `rules/*.json`,
    the pre-specified plan, and append-only experiment records/notes. Do not
    change `src/`, dataset configs, source bytes, exclusions, normalization
    directions, partitions, preprocessing, metrics, budgets, or decision policy.
    Infrastructure bugs require a separate, disclosed protocol correction and
    invalidation of affected results; never silently repair a scientific run.

Computed oracles only: never include binder labels, experimental affinity,
replicate success rates, IDs, group names or any excluded column as rule terms.
A declared direction is authoritative. Negative-valued error signals often need
`higher_is_better`. Investigate an inverted-AUC warning; never silently auto-flip
it. If a signal is mechanistically uncertain, state that uncertainty in its schema.

The local boundary prevents accidental dev reads. It is not an OS security
sandbox against an agent deliberately opening files. Keep the raw release and
vault inaccessible to a discovery agent when deploying across trust boundaries.
Never create a remote or push unless the human asks.

## Fixed example protocol

Use `configs/igdesign.json` as committed. It pins public input checksums,
excludes control/SAbDab rows and measured outcomes, and fixes
`Utomilumab-TNFRSF9` as the final system. The six other systems form the pool;
its seeded, stratified halves are discovery and one-use verification.
Each half uses leave-one-system-out folds, repeated with five distinct seeds.
No model is fitted on the training side of a fold. Aggregation is macro over
folds, then over repeats. Top-K is per system/fold. Final is the one new system.
Prevalence matching is off in this example; do not turn it on mid-campaign.

All commands run from the repository root. Use a fresh campaign **only for a
new study or a transparent reproduction**, never to reuse a consumed verifier
for more selection. Installation and initial preparation:

```sh
uv sync --frozen --dev
mkdir -p results/local
uv run filters prepare --config configs/igdesign.json --work work/igdesign
uv run filters eval --work work/igdesign --rule rules/baseline.json \
  --output results/local/00-baseline.json > results/local/00-baseline.log
```

Create `results/local/` before shell redirection (`mkdir -p results/local`).
The public quickstart uses `results/local/` so it does not overwrite demo evidence.

## The loop and exact commit/log convention

1. State one small change and its expected mechanism in the rule's `hypothesis`.
   Give each rule a new filename; retain earlier rules. Use explicit JSON and
   schema directions, not Python. Do not add a fitted model. Test serialization
   and inspect the canonical formula printed by `eval`.
2. Run fixed discovery CV:

   ```sh
   uv run filters eval --work work/igdesign --rule rules/additive.json \
     --output results/local/01-additive.json > results/local/01-additive.log
   ```

3. Read metrics with `uv run filters report --record results/local/01-additive.json`.
   Record the primary metric, PR and top-K guards, variability and uncertainty.
   A dev improvement remains a hypothesis until transfer verification.
4. Commit the rule with a descriptive message including its expected effect:

   ```sh
   git add rules/additive.json
   git commit -m "experiment: add weak alternate-model consistency term to test complementary ranking"
   uv run filters report --record results/local/01-additive.json \
     --log results/local/results.jsonl --commit HEAD --rule-path rules/additive.json \
     --decision hypothesis --note "Pre-stated alternate-model term; transfer pending."
   git add -f results/local/01-additive.json results/local/01-additive.log results/local/results.jsonl
   git commit -m "audit: record additive-rule discovery outcome"
   ```

   The run record contains the **pre-run** git state (possibly dirty), embedded
   rule, implementation hash and dataset/protocol/partition hashes. The audit
   row binds a **post-run** commit and verifies the exact rule and implementation
   against that commit. There is no impossible self-referential commit hash.
   Logs are machine-derived, never hand-transcribed. Use `rejected` and an
   explanatory note for failures. Do not amend away earlier experiment history.
5. Use observed discovery evidence to state the next small hypothesis, while
   keeping the candidate family small. Before transfer, register the batch:

   ```sh
   uv run filters transfer-check --work work/igdesign --plan experiments/plan.json
   uv run filters transfer-check --work work/igdesign --output results/local/03-transfer.json
   ```

   Plan paths are relative to the plan file. Registration stores immutable
   snapshots; later edits to those files do not change the registered candidates.
   The command selects at most one candidate on discovery, verifies it once,
   compares guard metrics, and retains the baseline on failure. Do not edit
   `decision.json`. All unselected and failed candidates remain in the record.
6. After the decision, run final **once**:

   ```sh
   uv run filters final --work work/igdesign --output results/local/04-final.json
   ```

   It automatically loads the frozen selected rule. It has no arbitrary `--rule`
   override. The consumption marker is claimed before data are opened. A crashed
   final stays consumed; report the failure rather than clearing the marker.
   Log the final with `--decision final` and the frozen rule's committed path.

For diagnostics (hypotheses only):

```sh
uv run filters gate-scan --work work/igdesign --base rules/baseline.json \
  --regime-signal 'HCDR3 scRMSD (ABB2)' --adjustment-signal 'HCDR3 scRMSD (ESMFold)' \
  --thresholds '2,2.25,2.5,2.75,3' --op '>' --output results/local/gate-diagnostic.json
```

No claim here is an established benchmark result. The selection guardrails are
project policy motivated by the supplied research brief. Report actual evidence
and limitations. Distilling an ensemble into conjunctions is a gray area and is
not implemented. If introduced separately, label every artifact **distilled**,
not discovered; fitted baselines must also remain separate from the rule artifact.
