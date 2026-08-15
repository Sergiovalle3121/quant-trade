"""Typer surface for the offline Quant Research Auditor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from quant_trade.audit.runner import load_audit_input, run_audit, write_audit_bundle

audit_app = typer.Typer(help="Audit a BYOD research package without network or code execution.")


@audit_app.callback()
def audit_root() -> None:
    """Inspect local research evidence; no network, execution, or live approval."""


@audit_app.command("run")
def audit_run(
    config: Annotated[Path, typer.Option(help="Local YAML audit configuration.")],
    out_dir: Annotated[Path, typer.Option(help="Directory for audit.json and audit.html.")] = Path(
        "artifacts/audit"
    ),
) -> None:
    """Run a bounded local audit and emit deterministic JSON and HTML."""
    try:
        audit_input = load_audit_input(config)
        bundle = run_audit(audit_input)
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


def register(parent: typer.Typer, *, name: str = "audit") -> None:
    """Attach this isolated app to the repository's root CLI."""
    parent.add_typer(audit_app, name=name)


__all__ = ["audit_app", "register"]
