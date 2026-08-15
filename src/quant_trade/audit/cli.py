"""Typer surface for the offline Quant Research Auditor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from quant_trade.audit.models import AuditStatus, recompute_bundle_digest
from quant_trade.audit.package import PACKAGE_FILENAMES, initialize_package
from quant_trade.audit.runner import load_audit_input, run_audit, write_audit_bundle

audit_app = typer.Typer(help="Audit a BYOD research package without network or code execution.")

#: Exit codes, so a verdict can gate a script instead of only being printed.
_EXIT_CODES = {
    AuditStatus.PASS: 0,
    AuditStatus.INSUFFICIENT_EVIDENCE: 1,
    AuditStatus.NO_GO: 2,
}


@audit_app.callback()
def audit_root() -> None:
    """Inspect local research evidence; no network, execution, or live approval."""


@audit_app.command("init")
def audit_init(
    package_dir: Annotated[
        Path, typer.Option(help="Directory holding your dataset; templates are written here.")
    ],
    evaluation_cutoff_utc: Annotated[
        str, typer.Option(help="Last instant your research was allowed to see, e.g. 2024-12-31Z.")
    ],
    dataset: Annotated[
        str, typer.Option(help="Dataset file name inside --package-dir.")
    ] = "dataset.csv",
    timestamp_column: Annotated[str, typer.Option(help="Name of the event-time column.")] = (
        "timestamp"
    ),
    symbol_column: Annotated[
        str, typer.Option(help="Instrument column; ordering is checked per instrument.")
    ] = "symbol",
) -> None:
    """Write a package skeleton with every SHA-256 already computed.

    Hashing your own dataset by hand and pasting the digest into two files is
    the step most likely to be got wrong, and getting it wrong looks identical
    to unbound results.  This does that part for you and leaves the fields only
    you can know — data source, licence, capture time, costs, benchmarks — as
    explicit ``FILL_ME`` placeholders.  It never overwrites an existing file.
    """
    try:
        created, placeholders = initialize_package(
            package_dir,
            dataset_name=dataset,
            evaluation_cutoff_utc=evaluation_cutoff_utc,
            timestamp_column=timestamp_column,
            symbol_column=symbol_column,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                "created": [str(path) for path in created],
                "fields_you_must_still_fill": placeholders,
                "next_command": (
                    f"quant-trade audit run --config "
                    f"{Path(package_dir) / PACKAGE_FILENAMES['config']}"
                ),
            },
            sort_keys=True,
        )
    )


@audit_app.command("run")
def audit_run(
    config: Annotated[Path, typer.Option(help="Local YAML audit configuration.")],
    out_dir: Annotated[Path, typer.Option(help="Directory for audit.json and audit.html.")] = Path(
        "artifacts/audit"
    ),
    redact: Annotated[
        bool, typer.Option(help="Emit file names instead of local absolute paths.")
    ] = False,
) -> None:
    """Run a bounded local audit and emit deterministic JSON and HTML.

    Exits 0 on PASS, 1 on INSUFFICIENT_EVIDENCE, and 2 on NO_GO, so a pipeline
    can stop on a bad package instead of having to parse the report.
    """
    try:
        audit_input = load_audit_input(config)
        bundle = run_audit(audit_input, redact=redact)
        json_path, html_path = write_audit_bundle(bundle, out_dir)
    except (OSError, TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                "verdict": bundle.verdict.status.value,
                "bundle_digest": bundle.bundle_digest,
                "expected_profit_established": bundle.verdict.expected_profit_established,
                "real_money_authorized": bundle.verdict.real_money_authorized,
                "json": str(json_path),
                "html": str(html_path),
            },
            sort_keys=True,
        )
    )
    raise typer.Exit(code=_EXIT_CODES[bundle.verdict.status])


@audit_app.command("verify")
def audit_verify(
    bundle: Annotated[Path, typer.Option(help="A delivered audit.json to check.")],
) -> None:
    """Recompute a delivered bundle's digest from its own bytes.

    Requires no access to the original inputs and no trust in whoever sent the
    file.  Exits 0 when the digest matches and 2 when it does not.
    """
    try:
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        recomputed = recompute_bundle_digest(payload)
    except (OSError, TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    declared = str(payload["bundle_digest"])
    matches = recomputed == declared
    typer.echo(
        json.dumps(
            {
                "bundle": str(bundle),
                "declared_bundle_digest": declared,
                "recomputed_bundle_digest": recomputed,
                "matches": matches,
                "verdict": payload.get("verdict", {}).get("status"),
                "real_money_authorized": False,
            },
            sort_keys=True,
        )
    )
    if not matches:
        raise typer.Exit(code=2)


def register(parent: typer.Typer, *, name: str = "audit") -> None:
    """Attach this isolated app to the repository's root CLI."""
    parent.add_typer(audit_app, name=name)


__all__ = ["audit_app", "register"]
