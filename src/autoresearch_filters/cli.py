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


@app.command()
def prepare(
    config: Annotated[Path, typer.Option(help="Dataset config JSON")],
    baseline: Annotated[Path, typer.Option(help="Rule every idea is compared against")],
    campaign: Campaign = "main",
):
    """Cut the data into discovery / verification / holdout and score the baseline."""
    rows = run(lambda c: loop.prepare(config, baseline, c), campaign)
    for name, auc in rows[0]["signal_auc"].items():
        flag = "  <-- below 0.5: check the declared direction" if auc < 0.5 else ""
        typer.echo(f"signal {name!r}: oriented discovery AUC {auc:.4f}{flag}")
    show(campaign, rows[1])


@app.command("eval")
def evaluate(rule: Path, campaign: Campaign = "main"):
    """Score one rule on discovery CV and log it. Failures are logged too."""
    show(campaign, run(loop.evaluate, campaign, rule))


@app.command()
def note(text: str, campaign: Campaign = "main"):
    """Add a free-text entry to the journal."""
    run(loop.note, campaign, text)


@app.command()
def verify(rules: list[Path], campaign: Campaign = "main"):
    """ONE USE: pick among 1-3 finalists on discovery, test once on reserved rows, freeze."""
    show(campaign, run(loop.verify, campaign, rules))


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
