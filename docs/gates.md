# Gates and local diagnostics

A normalized signal uses the dataset's declared direction:

\[
u(x)=\operatorname{clip}((x-l)/(h-l),0,1),\qquad
n(x)=u(x)\ \text{or}\ 1-u(x).
\]

The second form applies when lower is better. A negative error, such as `-PAE`,
may instead need higher-is-better: values nearer zero represent smaller error.
The harness checks oriented single-signal AUC on discovery rows. A contradictory
AUC triggers a loud warning or assertion, according to the fixed protocol.
It never learns or flips the direction. Finite samples, weak signals, clipping
and confounding can also produce a low AUC; investigate rather than treating
this diagnostic as proof of a sign error.

The recursive score language is:

\[
s(x)=b(x)+\sum_g \mathbf 1[c_g(x)]\left[
\sum_k w_{gk}\{n_{gk}(x)-a_{gk}\}+\sum_{j\in\mathrm{children}(g)}G_j(x)
\right].
\]

Each gate has one raw-signal comparison and can contain more gates. Children
are active only when all ancestor conditions are true. Sibling gates add; they
are not implicitly exclusive. Express an if/else by complementary `<=` and `>`
conditions. Adjustments have a signed weight, optional clip range, optional
asserted direction and a center (default zero). Direction assertions must agree
with the dataset. Base additive weights are nonnegative and normalized by their
sum; product exponents are positive. A gate adjustment is **not** divided by
base weights. Scores may lie outside [0,1]; they are rankings, not probabilities.

Centering at 0.5 rewards the upper half of normalized quality and penalizes the
lower half. A negative adjustment can down-weight a base confidence specifically
where it is untrustworthy. The same signal may have opposite signs in sibling
regimes. Hard conjunctions/disjunctions are `hard` nodes with `all`/`any`
conditions; products use `factors` and positive `exponent` values.

```json
{
  "name": "conditional-stabilizer",
  "hypothesis": "Test complementary structural evidence when the base model is less self-consistent.",
  "expression": {
    "kind": "gated",
    "base": {"kind": "additive", "terms": [{"signal": "HCDR3 scRMSD (ABB2)"}]},
    "gates": [{
      "name": "less-consistent-base",
      "when": {"signal": "HCDR3 scRMSD (ABB2)", "op": ">", "value": 2.5},
      "adjustments": [{"signal": "HCDR3 scRMSD (ESMFold)", "weight": 0.25, "center": 0.5}]
    }]
  }
}
```

The pretty-printer renders explicit normalization ranges and directions. JSON
is the lossless interchange format: parsing serialized JSON preserves both
arithmetic and the canonical pseudo-formula. Pseudo-formulas are human output,
not an executable expression parser. Unknown nodes, callable hooks, arbitrary
Python, non-finite numbers, and excessively deep trees are rejected.

`gate-scan` compares a candidate signal's oriented AUC overall with its AUC
inside each regime. It also reports sample/positive counts and Pearson
correlation with each of the base rule's signals **inside that same regime**.
A locally informative but redundant signal need not improve the base. A tiny
regime can generate an impressive but unstable AUC. Single-class regimes yield
`null`, not a fabricated AUC. These are descriptive diagnostics without
multiplicity-adjusted significance claims.

The scan neither ranks thresholds nor selects one. Fix a small fine grid, inspect
support and smoothness, and prefer a broad plateau's center. If checking actual
rule metrics across a fine threshold grid, use bounded `eval --mode search`,
record every variant, and treat the output only as hypotheses. New proposals
still require disjoint verification; dev-CV argmax is not the decision procedure.
