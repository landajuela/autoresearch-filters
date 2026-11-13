"""Thin command line interface; the final-holdout module is imported only by final."""

from pathlib import Path
from typing import Annotated

import typer

from .io import read_json
from .reporting import summarize
from .rules import load_rule

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
Work = Annotated[Path, typer.Option(help="Prepared campaign directory")]
Output = Annotated[Path, typer.Option(help="New immutable JSON record path")]


def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, OSError, AssertionError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def prepare(config: Annotated[Path, typer.Option()], work: Work = Path("work/igdesign")):
    """Fetch, validate, partition and seal a dataset (idempotent for identical config)."""
    from .prepare import prepare as prepare_dataset

    typer.echo(invoke(prepare_dataset, config, work))


@app.command("eval")
def evaluate(
    rule: Annotated[Path, typer.Option()],
    output: Output,
    work: Work = Path("work/igdesign"),
    mode: str = "dev",
):
    """Evaluate discovery CV; bounded search outputs are hypotheses, never selections."""
    from .dev import evaluate as evaluate_rule

    result = invoke(evaluate_rule, work, invoke(load_rule, rule), output, mode)
    typer.echo(summarize(result))


@app.command("transfer-check")
def transfer_check(
    work: Work = Path("work/igdesign"),
    plan: Annotated[
        Path | None, typer.Option(help="Register 1–3 candidates before verification")
    ] = None,
    output: Annotated[Path | None, typer.Option()] = None,
):
    """With --plan: seal hypotheses. With --output: select, verify once, then freeze."""
    from .transfer import register
    from .transfer import transfer_check as check

    if (plan is None) == (output is None):
        raise typer.BadParameter("provide exactly one of --plan or --output")
    if plan is not None:
        result = invoke(register, work, plan)
        typer.echo(
            f"Registered {len(result['candidates'])} candidates; verification remains sealed."
        )
    else:
        typer.echo(summarize(invoke(check, work, output)))


@app.command("gate-scan")
def gate_scan(
    base: Annotated[Path, typer.Option()],
    regime_signal: Annotated[str, typer.Option()],
    adjustment_signal: Annotated[str, typer.Option()],
    thresholds: Annotated[str, typer.Option(help="Comma-separated fine grid; no argmax selection")],
    output: Output,
    work: Work = Path("work/igdesign"),
    op: str = ">",
):
    """Compare local/overall AUC and base-signal redundancy on discovery rows."""
    from .diagnostics import gate_scan as scan

    try:
        grid = [float(value) for value in thresholds.split(",")]
    except ValueError as exc:
        raise typer.BadParameter("thresholds must be comma-separated numbers") from exc
    result = invoke(
        scan, work, invoke(load_rule, base), regime_signal, grid, adjustment_signal, op, output
    )
    typer.echo(summarize(result))


@app.command()
def report(
    record: Annotated[Path, typer.Option()],
    log: Annotated[Path | None, typer.Option(help="Append one machine-derived audit row")] = None,
    commit: str = "HEAD",
    rule_path: str = "rules/current.json",
    decision: str = "hypothesis",
    note: str = "",
):
    """Read metrics or link an immutable record to its tested, committed rule."""
    from .reporting import append_result

    typer.echo(summarize(invoke(read_json, record)))
    if log is not None:
        invoke(append_result, record, log, commit, rule_path, decision, note)
        typer.echo(f"Appended audit row to {log}")


@app.command()
def final(output: Output, work: Work = Path("work/igdesign")):
    """Evaluate the frozen rule on the locked holdout once; a second call fails."""
    from .final import final as run_final

    typer.echo(summarize(invoke(run_final, work, output)))


if __name__ == "__main__":
    app()
