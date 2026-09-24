"""``quant-trade audit``: run an audit from files, serve the web app, purge old
uploads, and answer a client's privacy request (``export``, ``delete``,
``unpublish``, ``waitlist-remove``).

``run`` is the whole product without a browser: the operator receives a CSV
by e-mail, runs one command, and sends back ``report.html``. ``serve`` and
the store commands need the ``web`` extra and import it lazily so the core CLI never
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
from quant_trade.audit.prop_presets import DEFAULT_PRESET, PRESETS
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

codes_app = typer.Typer(
    help=(
        "Access codes: sell an audit outside the service (bank transfer, Mercado Pago, "
        "WhatsApp) and hand out a code. Codes are stored hashed and printed once."
    ),
    no_args_is_help=True,
)
audit_app.add_typer(codes_app, name="codes")

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
    output_dir: Annotated[Path, typer.Option(help="Where audit.json and report.html go")],
    equity: Annotated[
        Path | None,
        typer.Option(help="CSV with timestamp + equity (or return); optional with --report"),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option(
            help="Platform report: MT5/MT4 HTML, TradingView CSV/XLSX, NinjaTrader, "
            "QuantConnect, backtesting.py or vectorbt trades"
        ),
    ] = None,
    optimization: Annotated[
        Path | None,
        typer.Option(help="MT5 optimisation XML; its passes become the MEASURED trial count"),
    ] = None,
    challenge: Annotated[
        str | None,
        typer.Option(help=f"Prop-firm preset to simulate (default {DEFAULT_PRESET})"),
    ] = None,
    initial_balance: Annotated[
        float | None,
        typer.Option(help="Starting balance, used only when the report states none", min=0),
    ] = None,
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
    """Audit one backtest and write ``audit.json`` and ``report.html``.

    Give ``--equity`` (a curve), ``--report`` (the platform's own file), or
    both: the report then supplies the trades and the equity file the curve.
    """
    if equity is None and report is None:
        raise typer.BadParameter("give --equity, --report, or both")
    if challenge is not None and challenge not in PRESETS:
        raise typer.BadParameter(
            f"unknown challenge preset {challenge!r}; see: quant-trade audit presets"
        )
    try:
        declared = DeclaredMetadata(
            trials=trials,
            cost_bps_per_side=cost_bps,
            oos_start=oos_start,
            description=description,
            benchmark_applicable=benchmark_applicable,
            locale=locale,
            initial_balance=initial_balance or None,
            challenge=challenge,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        inputs = build_inputs(
            _read(equity, what="equity"),
            declared,
            trades_bytes=_read(trades, what="trades"),
            benchmark_bytes=_read(benchmark, what="benchmark"),
            variants_bytes=_read(variants, what="variants"),
            report_bytes=_read(report, what="report"),
            report_filename=report.name if report is not None else None,
            optimization_bytes=_read(optimization, what="optimization"),
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


@audit_app.command("presets")
def presets() -> None:
    """List the prop-firm challenge presets, with their source and date."""
    table = Table(title="Prop-firm challenge presets (rules as posted on the date shown)")
    for column in ("key", "firm / program / phase", "target", "daily", "total", "min days"):
        table.add_column(column)
    table.add_column("source, read on")
    for key in sorted(PRESETS):
        rules = PRESETS[key]
        daily = "-" if rules.max_daily_loss is None else f"{rules.max_daily_loss:.1%}"
        marker = " (default)" if key == DEFAULT_PRESET else ""
        table.add_row(
            key + marker,
            f"{rules.firm} / {rules.program} / {rules.phase}",
            f"{rules.profit_target:.1%}",
            f"{daily} ({rules.daily_loss_basis})",
            f"{rules.max_total_loss:.1%} ({rules.total_loss_type})",
            str(rules.min_trading_days),
            f"{rules.source_url}, {rules.as_of}",
        )
    Console(width=200).print(table)


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


@audit_app.command("export")
def export(
    audit_id: Annotated[str, typer.Argument(help="The audit id from the client's private link")],
    out: Annotated[Path | None, typer.Option(help="Output directory")] = None,
) -> None:
    """Write everything held on one audit to a folder (a client's access request).

    Check the client's private link before answering: the id alone is not
    proof that the audit is theirs. The folder lands under ``outputs/`` by
    default, which git ignores.
    """
    store = _store()
    record = store.get_audit(audit_id, with_blobs=True)
    if record is None:
        typer.echo(f"no audit with id {audit_id}", err=True)
        raise typer.Exit(code=1)
    target = out or Path("outputs") / "audit_export" / audit_id
    target.mkdir(parents=True, exist_ok=True)
    publication = store.publication_for_audit(audit_id)
    summary = {
        "id": record.id,
        "created_at": record.created_at,
        "paid": record.paid,
        "paid_at": record.paid_at,
        "payment_reference": record.stripe_session_id,
        "client_ip": record.client_ip,
        "overall_class": record.overall_class,
        "file_sha256": record.digests,
        "purged_at": record.purged_at,
        "published_at": publication.created_at if publication else None,
        "public_id": publication.public_id if publication else None,
    }
    atomic_write_json(target / "record.json", summary)
    written = ["record.json"]
    if record.declared_json:
        atomic_write_text(target / "declared.json", record.declared_json)
        written.append("declared.json")
    if record.result_json:
        atomic_write_text(target / AUDIT_JSON, record.result_json)
        written.append(AUDIT_JSON)
    if record.report_html:
        atomic_write_text(target / REPORT_HTML, record.report_html)
        written.append(REPORT_HTML)
    uploads = {
        "equity.csv": record.equity_csv,
        "trades.csv": record.trades_csv,
        "benchmark.csv": record.benchmark_csv,
        "variants.csv": record.variants_csv,
        **(record.files or {}),
    }
    for name, data in sorted(uploads.items()):
        if data is None:
            continue
        safe = Path(name).name or "upload"
        (target / f"upload_{safe}").write_bytes(data)
        written.append(f"upload_{safe}")
    typer.echo(f"wrote {len(written)} file(s) to {target}: {', '.join(written)}")


@audit_app.command("delete")
def delete(
    audit_id: Annotated[str, typer.Argument(help="The audit id from the client's private link")],
    yes: Annotated[bool, typer.Option("--yes", help="Actually delete")] = False,
) -> None:
    """Delete one audit completely at its client's request: files, report,
    hashes, class and verification page.

    Without ``--yes`` only shows what would be deleted. Check the client's
    private link first: the id alone is not proof that the audit is theirs.
    """
    store = _store()
    record = store.get_audit(audit_id)
    if record is None:
        typer.echo(f"no audit with id {audit_id}", err=True)
        raise typer.Exit(code=1)
    published = store.publication_for_audit(audit_id) is not None
    what = (
        f"audit {audit_id} (created {record.created_at}, class {record.overall_class}, "
        f"{'paid' if record.paid else 'unpaid'}, {'published' if published else 'not published'})"
    )
    if not yes:
        typer.echo(f"would delete {what}; pass --yes")
        return
    store.delete_audit(audit_id)
    typer.echo(f"deleted {what}")


@audit_app.command("unpublish")
def unpublish(
    audit_id: Annotated[str, typer.Argument(help="The audit id from the client's private link")],
) -> None:
    """Withdraw an audit's public verification page and badge (also after a purge)."""
    if _store().unpublish(audit_id):
        typer.echo(f"unpublished {audit_id}")
    else:
        typer.echo(f"audit {audit_id} has no public page", err=True)
        raise typer.Exit(code=1)


@audit_app.command("waitlist-remove")
def waitlist_remove(
    email: Annotated[str, typer.Argument(help="The address to remove")],
    yes: Annotated[bool, typer.Option("--yes", help="Actually delete")] = False,
) -> None:
    """Remove an e-mail from the updates list. Without ``--yes`` only checks it."""
    store = _store()
    if not store.remove_waitlist(email, dry_run=not yes):
        typer.echo("that address is not on the list", err=True)
        raise typer.Exit(code=1)
    typer.echo("removed from the list" if yes else "on the list; pass --yes to remove it")


def _store() -> Any:
    try:
        from quant_trade.audit.settings import AuditSettings
        from quant_trade.audit.store import make_store
    except ImportError as exc:  # pragma: no cover - the web extra is missing
        raise typer.BadParameter('requires: python -m pip install -e ".[web]"') from exc
    return make_store(AuditSettings.from_env().database_url)


@codes_app.command("create")
def codes_create(
    credits: Annotated[int, typer.Option(help="Audits this code unlocks", min=1)],
    note: Annotated[str, typer.Option(help="Who bought it, how they paid")] = "",
    expires_days: Annotated[
        int | None, typer.Option(help="Days until the code expires (default: never)", min=1)
    ] = None,
) -> None:
    """Create a code and print it once. It cannot be shown again."""
    code, record = _store().create_access_code(
        credits=credits, note=note, at=datetime.now(UTC), expires_days=expires_days
    )
    typer.echo(code)
    expiry = record.expires_at or "never"
    typer.echo(
        f"id {record.id} · {record.credits_total} credit(s) · expires {expiry} · "
        "copy the code now: only its hash is stored",
        err=True,
    )


@codes_app.command("list")
def codes_list() -> None:
    """List codes by id with their credits. The codes themselves are never shown."""
    table = Table(title="Access codes (codes are stored hashed and never shown)")
    for column in ("id", "note", "used", "total", "left", "created", "expires", "state"):
        table.add_column(column)
    for record in _store().list_access_codes():
        table.add_row(
            record.id,
            record.note,
            str(record.credits_used),
            str(record.credits_total),
            str(record.credits_left),
            record.created_at,
            record.expires_at or "-",
            "disabled" if record.disabled else "active",
        )
    Console(width=160).print(table)


@codes_app.command("disable")
def codes_disable(code_id: Annotated[str, typer.Argument(help="The id from codes list")]) -> None:
    """Stop a code from unlocking anything more (for a leaked or refunded code)."""
    if _store().disable_access_code(code_id):
        typer.echo(f"disabled {code_id}")
    else:
        typer.echo(f"no active code with id {code_id}", err=True)
        raise typer.Exit(code=1)


__all__ = ["audit_app", "codes_app"]
