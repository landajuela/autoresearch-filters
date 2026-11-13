# Contributing

Use Python 3.11+ and uv. Read [AGENTS.md](AGENTS.md) before experiments.

```sh
uv sync --frozen --dev
uv run pre-commit install
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Infrastructure changes and scientific rule experiments are separate work. Fixes
need meaningful tests for the changed behavior. During an active campaign the
schema, source bytes, splits, preprocessing, metrics and selection policy are
frozen. Do not repair a disappointing result by editing infrastructure or trying
another split. A necessary protocol correction invalidates prior results; report
that correction and start a clearly labeled new study, never silently overwrite
a run or reopen a consumed verifier/holdout.

Rules are JSON. Every hypothesis, negative result and exception belongs in the
append-only experiment trail. Do not add a fitted estimator or executable code
to the rule interpreter. Any future fitted baseline belongs in a separate,
explicitly labeled module. Distillation is not implemented and would have to
produce artifacts labeled **distilled**, never discovered.

CSV works with the base dependencies. Parquet accepts an already installed
pandas-compatible engine; none is bundled because it would enlarge the default
installation. Ask before adding any dependency heavier than the existing stack,
or redistributing data with unclear rights. Include provenance and retrieval
dates for new data sources. Keep public logs free of local credentials and
private datasets. This repository does not create remotes or push automatically.
