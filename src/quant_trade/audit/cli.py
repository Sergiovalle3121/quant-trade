"""``quant-trade audit``: run an audit from files, serve the web app, purge old uploads.

``run`` is the whole product without a browser: the operator receives a CSV
by e-mail, runs one command, and sends back ``report.html``. ``serve`` and
``purge`` need the ``web`` extra and import it lazily so the core CLI never
depends on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.audit.engine import run_audit
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs
from quant_trade.evidence.canonical_json import atomic_write_json, atomic_write_text
from quant_trade.research.holdout_seal import HoldoutSeal, seal_holdout

audit_app = typer.Typer(
    help=(
        "Audit a client-supplied backtest. Research-only; not investment advice. "
        "No execution, no custody, no keys."
    ),
    no_args_is_help=True,
)

AUDIT_JSON = "audit.json"
REPORT_HTML = "report.html"


def _read(path: Path | None, *, what: str) -> bytes | None:
    if path is None:
        return None
    if not path.exists():
        raise typer.BadParameter(f"{what} file not found: {path}")
    return path.read_bytes()


def _print_verdict(payload: dict[str, Any]) -> None:
    console = Console()
    verdict = payload["verdict"]
    table = Table(title=f"Backtest audit · class {verdict['overall']}")
    table.add_column("dimension")
    table.add_column("status")
    table.add_column("reasons")
    for dimension in verdict["dimensions"]:
        table.add_row(dimension["name"], dimension["status"], "; ".join(dimension["reasons"]))
    console.print(table)
    console.print(verdict["summary"])
    flags = payload["red_flags"]
    if flags:
        listed = ", ".join(f"{flag['code']}({flag['severity']})" for flag in flags)
        console.print(f"red flags: {listed}")


@audit_app.command("run")
def run(
    equity: Annotated[Path, typer.Option(help="CSV with timestamp + equity (or return)")],
    output_dir: Annotated[Path, typer.Option(help="Where audit.json and report.html go")],
    trades: Annotated[Path | None, typer.Option(help="CSV of closed trades")] = None,
    benchmark: Annotated[Path | None, typer.Option(help="CSV with a benchmark equity")] = None,
    variants: Annotated[Path | None, typer.Option(help="CSV matrix of variant returns")] = None,
    trials: Annotated[int, typer.Option(help="Trials the client declares", min=1)] = 1,
    cost_bps: Annotated[float, typer.Option(help="Declared cost per side, bps", min=0)] = 0.0,
    oos_start: Annotated[str | None, typer.Option(help="Declared out-of-sample start")] = None,
    description: Annotated[str, typer.Option(help="Client's description")] = "",
    locale: Annotated[str, typer.Option(help="es or en")] = "es",
    benchmark_applicable: Annotated[bool, typer.Option(help="Benchmark applies")] = True,
    seed: Annotated[int, typer.Option(help="Bootstrap seed")] = 12345,
    bootstrap_samples: Annotated[int, typer.Option(help="Bootstrap samples", min=10)] = 1000,
    paid: Annotated[bool, typer.Option("--paid/--preview", help="Full report or preview")] = False,
) -> None:
    """Audit one backtest and write ``audit.json`` and ``report.html``."""
    try:
        declared = DeclaredMetadata(
            trials=trials,
            cost_bps_per_side=cost_bps,
            oos_start=oos_start,
            description=description,
            benchmark_applicable=benchmark_applicable,
            locale=locale,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        inputs = build_inputs(
            _read(equity, what="equity") or b"",
            declared,
            trades_bytes=_read(trades, what="trades"),
            benchmark_bytes=_read(benchmark, what="benchmark"),
            variants_bytes=_read(variants, what="variants"),
        )
    except ParseError as exc:
        typer.echo(f"cannot audit: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    result = run_audit(
        inputs, seed=seed, bootstrap_samples=bootstrap_samples, now=datetime.now(UTC)
    )
    html_text, json_text = render(result, watermark=not paid, free_mode=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")
    atomic_write_json(output_dir / AUDIT_JSON, payload)
    atomic_write_text(output_dir / REPORT_HTML, html_text)
    seal = payload["seal"].get("holdout_seal")
    if seal:
        known = {f.name for f in HoldoutSeal.__dataclass_fields__.values()}
        seal_holdout(output_dir, HoldoutSeal(**{k: v for k, v in seal.items() if k in known}))
    _print_verdict(payload)
    typer.echo(f"wrote {output_dir / AUDIT_JSON} and {output_dir / REPORT_HTML}")


@audit_app.command("serve")
def serve(
    host: Annotated[str, typer.Option(help="Bind address")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Port")] = 8000,
) -> None:
    """Serve the upload form and reports. Requires the ``web`` extra."""
    try:
        import uvicorn

        from quant_trade.audit.web import create_app
    except ImportError as exc:
        raise typer.BadParameter('audit serve requires: python -m pip install -e ".[web]"') from exc
    uvicorn.run(create_app(), host=host, port=port)


@audit_app.command("purge")
def purge(
    days: Annotated[int, typer.Option(help="Retention in days", min=1)] = 30,
    yes: Annotated[bool, typer.Option("--yes", help="Actually delete")] = False,
) -> None:
    """Delete uploads and reports of unpaid audits older than ``--days``.

    Without ``--yes`` only reports how many would be purged: deletion needs
    explicit confirmation.
    """
    try:
        from quant_trade.audit.settings import AuditSettings
        from quant_trade.audit.store import make_store
    except ImportError as exc:
        raise typer.BadParameter('audit purge requires: python -m pip install -e ".[web]"') from exc
    settings = AuditSettings.from_env()
    store = make_store(settings.database_url)
    count = store.purge_expired(datetime.now(UTC), retention_days=days, dry_run=not yes)
    if yes:
        typer.echo(f"purged {count} audit(s) older than {days} day(s)")
    else:
        typer.echo(f"{count} audit(s) older than {days} day(s) would be purged; pass --yes")


__all__ = ["audit_app"]
