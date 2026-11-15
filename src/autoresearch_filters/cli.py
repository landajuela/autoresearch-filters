"""Thin command line interface over the campaign loop."""

from pathlib import Path
from typing import Annotated

import typer

from . import campaign as loop
from . import journal

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
Campaign = Annotated[
    str,
    typer.Option("--campaign", "-c", envvar="FILTERS_CAMPAIGN", help="Name under campaigns/"),
]


def run(function, name: str, *args):
    try:
        return function(Path("campaigns") / name, *args)
    except (ValueError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def show(name: str, *rows: dict) -> None:
    primary = journal.primary_metric(journal.read(Path("campaigns") / name))
    for row in rows:
        typer.echo(journal.summary(row, primary))


def _columns(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _resolve(value: Path, folder: str) -> Path:
    """`example` means `configs/example.json`; a path with a slash or suffix is left alone."""
    if value.suffix or len(value.parts) > 1:
        return value
    return Path(folder) / f"{value}.json"


@app.command()
def init(
    data: Annotated[Path, typer.Option(help="CSV/Parquet table: computed columns + one outcome")],
    label: Annotated[str, typer.Option(help="Outcome column; inferred when omitted")] = "",
    success: Annotated[str, typer.Option(help="Outcome value that means success")] = "",
    lower: Annotated[
        str, typer.Option(help="Columns where SMALLER is better, comma-separated")
    ] = "",
    higher: Annotated[
        str, typer.Option(help="Columns where LARGER is better, comma-separated")
    ] = "",
    signals: Annotated[str, typer.Option(help="Use exactly these signal columns")] = "",
    id_column: Annotated[str, typer.Option("--id", help="ID column; row position if omitted")] = "",
    group: Annotated[str, typer.Option(help="Group column, e.g. target or batch")] = "",
    name: Annotated[str, typer.Option(help="Config name; the file stem if omitted")] = "",
    baseline_signal: Annotated[str, typer.Option(help="Baseline is this one signal")] = "",
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files")] = False,
):
    """Write a dataset config and a baseline rule for your own table, then print what to run."""
    from .bootstrap import initialise

    try:
        report = initialise(
            data,
            label=label,
            success=success,
            id_column=id_column,
            group=group,
            signals=_columns(signals),
            lower=_columns(lower),
            higher=_columns(higher),
            name=name,
            baseline_signal=baseline_signal,
            force=force,
        )
    except (ValueError, OSError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    config = report["config"]
    typer.echo(f"{data}: {report['rows']} rows, {len(config['signals'])} signals kept")
    typer.echo(
        f"outcome {config['label_column']!r}: success is {config['success_value']!r}, "
        f"{report['positives']} of {report['usable_rows']} usable rows"
    )
    for column, found in report["signals"].items():
        lo, hi = found["spec"]["range"]
        missing = (
            f", {found['missing_rows']} rows dropped for missing values"
            if found["missing_rows"]
            else ""
        )
        typer.echo(
            f"  {column}: {found['spec']['direction']} [{found['direction_source']}], "
            f"range [{lo:g}, {hi:g}]{missing}"
        )
    for column, reason in report["skipped"].items():
        typer.echo(f"  skipped {column}: {reason}")
    typer.echo(f"\nWrote {report['config_path']} and {report['baseline_path']}")
    typer.echo("Check every direction before searching: a direction is a claim about the")
    typer.echo("signal, and `prepare` prints an oriented AUC below 0.5 when a claim looks wrong.")
    if min(report["positives"], report["negatives"]) < 30:
        typer.echo(
            f"Caution: only {report['positives']} successes and {report['negatives']} failures, "
            "so per-fold metrics will be very noisy."
        )
    typer.echo("\nThen run:")
    typer.echo(
        f"  uv run filters prepare --config {report['config_path']} "
        f"--baseline {report['baseline_path']} -c run1"
    )
    typer.echo("  uv run filters eval rules/my-idea.json -c run1       # one idea at a time")
    typer.echo("See docs/adding-datasets.md for what to fix by hand, AGENTS.md for the loop.")


@app.command()
def prepare(
    config: Annotated[Path, typer.Option(help="configs/NAME.json, or just NAME")],
    baseline: Annotated[
        Path | None, typer.Option(help="Rule to beat; the one `init` wrote by default")
    ] = None,
    campaign: Campaign = "main",
):
    """Cut the data into discovery / verification / holdout and score the baseline."""
    config = _resolve(config, "configs")
    if baseline is None:
        baseline = Path("rules") / f"{config.stem}-baseline.json"
        if not baseline.exists():
            raise typer.BadParameter(f"pass --baseline: {baseline} does not exist")
    rows = run(lambda c: loop.prepare(config, _resolve(baseline, "rules"), c), campaign)
    for name, auc in rows[0]["signal_auc"].items():
        flag = "  <-- below 0.5: check the declared direction" if auc < 0.5 else ""
        typer.echo(f"signal {name!r}: oriented discovery AUC {auc:.4f}{flag}")
    show(campaign, rows[1])


@app.command("eval")
def evaluate(rule: Path, campaign: Campaign = "main"):
    """Score one rule on discovery CV and log it. Failures are logged too."""
    show(campaign, run(loop.evaluate, campaign, _resolve(rule, "rules")))


@app.command()
def idea(
    name: Annotated[str, typer.Argument(help="Short name; becomes rules/NAME.json")],
    why: Annotated[str, typer.Option("--why", help="The hypothesis: what changes and why")],
    signals: Annotated[str, typer.Option(help="Signals to combine; all of them by default")] = "",
    weights: Annotated[str, typer.Option(help="One per signal, comma-separated; all 1")] = "",
    parent: Annotated[str, typer.Option("--from", help="Rule it came from; the baseline")] = "",
    product: Annotated[
        bool, typer.Option("--product", help="Multiply instead of averaging")
    ] = False,
    campaign: Campaign = "main",
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing rule file")] = False,
):
    """Write a rule file for one idea, hypothesis first, ready for `filters eval`."""
    from .bootstrap import draft_rule
    from .rules import pretty

    try:
        numbers = [float(part) for part in _columns(weights)]
    except ValueError as exc:
        raise typer.BadParameter(f"--weights must be numbers: {weights!r}") from exc
    drafted = run(
        lambda c: draft_rule(
            c,
            name,
            why=why,
            signals=_columns(signals),
            weights=numbers,
            parent=parent,
            product=product,
            force=force,
        ),
        campaign,
    )
    typer.echo(f"Wrote {drafted['path']}  (parent: {drafted['rule'].parent})")
    typer.echo(pretty(drafted["rule"], drafted["config"]))
    typer.echo(f"\nNext: uv run filters eval {drafted['path']} -c {campaign}")


@app.command()
def note(text: str, campaign: Campaign = "main"):
    """Add a free-text entry to the journal."""
    run(loop.note, campaign, text)


@app.command()
def verify(rules: list[Path], campaign: Campaign = "main"):
    """ONE USE: pick among 1-3 finalists on discovery, test once on reserved rows, freeze."""
    show(campaign, run(loop.verify, campaign, [_resolve(rule, "rules") for rule in rules]))


@app.command()
def final(campaign: Campaign = "main"):
    """ONE USE: score the frozen rule on the locked holdout."""
    show(campaign, run(loop.final, campaign))


@app.command()
def log(
    campaign: Campaign = "main",
    html: Annotated[bool, typer.Option("--html", help="Also write journal.html")] = False,
):
    """Show how the search went: every idea, note and decision in order."""
    from .report import render

    path = Path("campaigns") / campaign
    rows = journal.read(path)
    if not rows:
        typer.echo(f"Error: no journal in {path}", err=True)
        raise typer.Exit(1)
    typer.echo(journal.table(rows))
    if html:
        (path / "journal.html").write_text(render(rows, campaign))
        typer.echo(f"\nWrote {path / 'journal.html'}")


if __name__ == "__main__":
    app()
