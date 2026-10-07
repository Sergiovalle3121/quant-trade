"""Separate local CLI: no web routes, broker connections or credentials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
import typer

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.config import PersonalPaperError

app = typer.Typer(help="Private simulated ETF observations. No real orders or live approval.")


def _print(value: Any) -> None:
    if isinstance(value, dict) and "worker" in value:
        value = {
            "checked_at": value["manifest"]["last_checked_at"],
            "status": value["status"],
            "closed_sessions": value["manifest"]["closed_sessions"],
            "quotes": value["worker"]["quotes"],
            "budget": value["worker"]["budget"],
            "paused_books": [k for k, b in value["books"].items() if b["paused"]],
            "pause_reasons": {
                k: b.get("pause_reason") for k, b in value["books"].items() if b["paused"]
            },
            "max_drawdown": max(b["drawdown"] for b in value["books"].values()),
            "warning": value.get("warning"),
            "real_money_approved": False,
        }
    if isinstance(value, dict) and "manifest" in value:
        value = {**value, "manifest": dict(value["manifest"])}
        value["manifest"]["historical_trial_count"] = len(value["manifest"]["historical_trials"])
        value["manifest"].pop("historical_trials")
        value["manifest"].pop("historical_trial_ids")
    typer.echo(json.dumps(value, indent=2, allow_nan=False))


@app.command("demo-data")
def demo_data(output: Annotated[Path, typer.Option(help="Ignored scratch destination")]) -> None:
    from quant_trade.personal_paper.demo import create_demo

    _print({k: str(v) for k, v in create_demo(output).items()})


@app.command("fetch-data")
def fetch_data(
    cache: Annotated[Path, typer.Option(help="Private ignored cache directory")],
    start: Annotated[str, typer.Option(help="Development warm-up begins here")] = "2020-01-02",
) -> None:
    from quant_trade.personal_paper.fetch import fetch_snapshot

    _print({"snapshot": str(fetch_snapshot(start, cache)), "real_money_approved": False})


@app.command("worker")
def worker_command(
    config: Annotated[Path, typer.Option()],
    database: Annotated[Path, typer.Option()],
    cache: Annotated[Path, typer.Option()],
    start: Annotated[str, typer.Option()] = "2020-01-02",
    expenses: Annotated[Path | None, typer.Option(help="Observed monthly expenses CSV")] = None,
) -> None:
    from quant_trade.personal_paper.worker import run_once

    try:
        _print(run_once(config, database, cache, start=start, expenses=expenses))
    except Exception as exc:
        # No substitute price or fill is created after a provider/input failure.
        typer.echo(f"Private worker blocked: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("run")
def run_command(
    config: Annotated[Path, typer.Option(help="Frozen personal config")],
    data: Annotated[Path, typer.Option(help="Cached canonical daily OHLCV")],
    fx: Annotated[Path, typer.Option(help="Sourced USD/MXN observations")],
    database: Annotated[Path, typer.Option(help="Private SQLite state")],
    mode: Annotated[str, typer.Option(help="development or prospective")] = "development",
    quotes: Annotated[
        Path | None, typer.Option(help="Optional observable next-open quotes")
    ] = None,
    calendar: Annotated[
        Path | None, typer.Option(help="Optional official session calendar")
    ] = None,
) -> None:
    try:
        _print(
            engine.run(
                config, data, fx, database, mode=mode, quotes_path=quotes, calendar_path=calendar
            )
        )
    except (PersonalPaperError, ValueError) as exc:
        typer.echo(f"Paper input refused: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("status")
def status_command(database: Annotated[Path, typer.Option()]) -> None:
    _print(engine.status(database))


@app.command("pause")
def pause_command(
    database: Annotated[Path, typer.Option()], reason: Annotated[str, typer.Option()]
) -> None:
    try:
        engine.pause(database, reason)
    except PersonalPaperError as exc:
        typer.echo(f"Paper pause refused: {exc}", err=True)
        raise typer.Exit(2) from exc
    _print(engine.status(database))


@app.command("resume")
def resume_command(
    database: Annotated[Path, typer.Option()],
    review: Annotated[str, typer.Option(help="Written human review, at least 20 characters")],
) -> None:
    try:
        engine.resume(database, review)
    except PersonalPaperError as exc:
        typer.echo(f"Paper resume refused: {exc}", err=True)
        raise typer.Exit(2) from exc
    _print(engine.status(database))


@app.command("export")
def export_command(
    database: Annotated[Path, typer.Option()], output: Annotated[Path, typer.Option()]
) -> None:
    _print(engine.export(database, output))


@app.command("backup")
def backup_command(
    database: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option(help="New destination; never replaces existing state")],
) -> None:
    from quant_trade.personal_paper.backup import create_backup

    _print(create_backup(database, output))


@app.command("economic-review")
def economic_review(
    database: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    costs: Annotated[Path | None, typer.Option(help="Observed expense coverage CSV")] = None,
) -> None:
    from quant_trade.personal_paper.economic import evaluate_economic

    paths = engine.export(database, output)
    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    if (
        manifest["prospective_started_at"] is None
        or manifest["clock_source"] != "SYSTEM_UTC"
        or manifest["data_kind"] != "market"
    ):
        result = {
            "status": "INCONCLUSIVE",
            "reason": "development, synthetic data or an injected clock cannot validate an edge",
            "real_money_approved": False,
        }
    else:
        ledger = output / "frozen_historical_trials.jsonl"
        ledger.write_text(
            "\n".join(json.dumps(t, sort_keys=True) for t in manifest["historical_trials"]) + "\n",
            encoding="utf-8",
        )
        result = evaluate_economic(
            pd.read_csv(paths["curves"]),
            prospective_started_at=manifest["prospective_started_at"],
            evidence_kind=manifest["evidence_kind"],
            ledger_path=ledger,
            baseline_capital_mxn=manifest["capital_mxn"],
            calendar_verified=manifest.get("calendar_verified", False),
            frozen_economic_protocol_sha256=manifest.get("economic_protocol_sha256"),
            observed_costs=pd.read_csv(costs) if costs else None,
        )
    (output / "economic_review.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    _print(result)
