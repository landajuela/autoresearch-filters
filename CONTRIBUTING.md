# Contributing

Use Python 3.11+ and uv. Read [AGENTS.md](AGENTS.md) before running experiments.

```sh
uv sync --frozen --dev
uv run pre-commit install
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Infrastructure changes and rule experiments are separate work. Do not repair a
disappointing result by editing the evaluator or trying another split: a
protocol fix invalidates earlier results, so disclose it and start a new
campaign. Rules stay JSON; do not add fitted estimators or executable code to
the rule interpreter. Record provenance and retrieval dates for new data
sources, and do not redistribute data with unclear rights.
