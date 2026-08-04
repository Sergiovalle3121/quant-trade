"""``quant-trade v9`` — paper daemon, cost import, artifacts.

What this interface deliberately lacks is part of its design. There is no
command that submits an order to a venue, buys hashrate, deposits, withdraws,
signs a transaction, or creates a cloud resource. There is no flag that
promotes recorded bytes to ``live`` provenance, no flag that supplies a return
or a P&L to the paper engine, and no flag that supplies elapsed time. Each of
those absences corresponds to a way a previous sprint's numbers were made to
look better than the evidence supported.

``cost-import`` is the one command that touches account-specific data, and it
takes a *file of response bytes the operator already captured*. It never asks
for a key, never reads one from the environment, and never signs a request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from quant_trade.evidence.canonical_json import atomic_write_json, canonical_dumps

v9_app = typer.Typer(help="V9 profitability evidence and autonomous paper.")

DEFAULT_STATE_DIR = "data/v9_paper"
DEFAULT_EVIDENCE_ROOT = "data/v9_evidence"
DEFAULT_ARTIFACT_DIR = "artifacts/v9"


def _echo(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


# --- paper daemon -----------------------------------------------------------


@v9_app.command("paper-start")
def paper_start(
    manifest: Annotated[str, typer.Option(help="Frozen candidate manifest JSON.")],
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
    session_id: Annotated[str, typer.Option(help="Identifier for this session.")] = "v9-paper-1",
    capital_usd: Annotated[float, typer.Option(help="Starting paper capital.")] = 1_000.0,
) -> None:
    """Start a paper session from a frozen manifest.

    The manifest is the only source of strategy and execution parameters, and
    its hash is recorded in the session, so a session cannot be quietly
    retuned once it is running.
    """
    from quant_trade.evidence.canonical_json import load_json, sha256_of_file
    from quant_trade.v9.paper_session import PaperSession, SessionConfig

    payload = load_json(manifest)
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{manifest} is not a manifest object")

    session = PaperSession(state_dir)
    config = SessionConfig(
        session_id=session_id,
        candidate_id=str(payload.get("candidate_id", "")),
        manifest_sha256=str(payload.get("manifest_sha256") or sha256_of_file(manifest)),
        initial_capital_usd=capital_usd,
        strategy=dict(payload.get("strategy", {}) or {}),
        execution=dict(payload.get("execution", {}) or {}),
        max_drawdown=float((payload.get("limits", {}) or {}).get("max_drawdown", 0.10)),
        perp_leverage=float((payload.get("limits", {}) or {}).get("perp_leverage", 3.0)),
        started_at_utc=str(payload.get("created_at_utc", "")),
    )
    session.start(config)
    _echo(session.status_report())


@v9_app.command("paper-run")
def paper_run(
    ticks: Annotated[str, typer.Option(help="JSONL file of observed market ticks.")],
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
) -> None:
    """Feed observed market ticks to a running session.

    Ticks are the only input. There is no option to pass a return, a yield or
    a P&L: the engine derives what the market was worth from what the market
    did, which is the difference between a measurement and an assertion.
    """
    from quant_trade.v9.paper_engine import MarketTick
    from quant_trade.v9.paper_session import PaperSession

    session = PaperSession(state_dir)
    session.resume()
    known = set(MarketTick.__dataclass_fields__)
    batch: list[MarketTick] = []
    for line in Path(ticks).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        batch.append(MarketTick(**{k: v for k, v in row.items() if k in known}))
    result = session.advance(batch)
    _echo(result)


@v9_app.command("paper-status")
def paper_status(
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
) -> None:
    """Report a session's state without moving it."""
    from quant_trade.v9.paper_session import PaperSession

    session = PaperSession(state_dir)
    session.resume()
    _echo(session.status_report())


@v9_app.command("paper-resume")
def paper_resume(
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
) -> None:
    """Reopen a session after a restart and replay its journal exactly once."""
    from quant_trade.v9.paper_session import PaperSession

    session = PaperSession(state_dir)
    session.resume()
    report = session.status_report()
    _echo(
        {
            "resumed": True,
            "status": report["status"],
            "events_processed": report["events_processed"],
            "wall_clock_hours": report["wall_clock_hours"],
            "reconciliation": report["reconciliation"],
        }
    )


@v9_app.command("paper-stop")
def paper_stop(
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
) -> None:
    """Stop a session and release its writer lease."""
    from quant_trade.v9.paper_session import PaperSession

    session = PaperSession(state_dir)
    session.resume()
    session.stop()
    _echo({"stopped": True, "state_dir": state_dir})


@v9_app.command("paper-report")
def paper_report(
    state_dir: Annotated[str, typer.Option(help="Session state directory.")] = DEFAULT_STATE_DIR,
    out: Annotated[str, typer.Option(help="Where to write the report.")] = (
        f"{DEFAULT_ARTIFACT_DIR}/PAPER_DAEMON_STATUS.json"
    ),
) -> None:
    """Write the session report, including whether its clock can be trusted."""
    from quant_trade.v9.paper_session import PaperSession

    session = PaperSession(state_dir)
    session.resume()
    report = session.status_report()
    atomic_write_json(out, report)
    typer.echo(f"wrote {out}")
    _echo(
        {
            "status": report["status"],
            "clock_source": report["clock_source"],
            "clock_is_persisted": report["clock_is_persisted"],
            "wall_clock_hours": report["wall_clock_hours"],
            "reconciled": report["reconciliation"]["reconciled"],
            "promotable": (report["clock_is_persisted"] and report["reconciliation"]["reconciled"]),
        }
    )


# --- cost evidence ----------------------------------------------------------


@v9_app.command("cost-import")
def cost_import(
    venue: Annotated[str, typer.Option(help="bybit or okx.")],
    raw: Annotated[str, typer.Option(help="File of response bytes you captured.")],
    effective_from: Annotated[str, typer.Option(help="ISO-8601 UTC.")],
    expires_at: Annotated[str, typer.Option(help="ISO-8601 UTC.")],
    instrument: Annotated[str, typer.Option(help="Instrument the schedule covers.")] = "BTCUSDT",
    leg: Annotated[str, typer.Option(help="OKX only: spot or perp.")] = "spot",
    out_dir: Annotated[str, typer.Option(help="Where to write the bundle.")] = (
        DEFAULT_EVIDENCE_ROOT
    ),
) -> None:
    """Import a fee schedule from bytes you already captured.

    This command never asks for a key, never reads one from the environment,
    and never signs a request. You run the venue call yourself; this takes the
    response file and records its sha256 alongside the parsed rates, so the
    numbers a campaign uses can be traced to bytes rather than to a constant.
    """
    from quant_trade.v9.cost_evidence import (
        CostEvidenceBundle,
        parse_bybit_fee_rate,
        parse_okx_trade_fee,
    )

    payload = Path(raw).read_bytes()
    key = venue.strip().lower()
    if key == "bybit":
        schedules = parse_bybit_fee_rate(
            payload,
            instrument=instrument,
            captured_at_utc=effective_from,
            effective_from_utc=effective_from,
            expires_at_utc=expires_at,
        )
    elif key == "okx":
        schedules = parse_okx_trade_fee(
            payload,
            instrument=instrument,
            leg=leg,
            captured_at_utc=effective_from,
            effective_from_utc=effective_from,
            expires_at_utc=expires_at,
        )
    else:
        raise typer.BadParameter(f"unknown venue {venue!r}; expected bybit or okx")

    bundle = CostEvidenceBundle(
        venue=key, schedules=tuple(schedules), captured_at_utc=effective_from
    )
    target = Path(out_dir) / f"cost_bundle_{key}.json"
    atomic_write_json(target, bundle.to_dict())
    _echo(
        {
            "venue": key,
            "bundle_sha256": bundle.bundle_sha256,
            "weakest_evidence_class": bundle.weakest_evidence_class,
            "promotable": bundle.promotable,
            "written_to": str(target),
            "secrets_stored": 0,
        }
    )


@v9_app.command("cost-instructions")
def cost_instructions(
    venue: Annotated[str, typer.Option(help="bybit or okx.")],
) -> None:
    """Print how to capture your own fee schedule, and what never to send."""
    from quant_trade.v9.cost_evidence import operator_capture_instructions

    _echo(operator_capture_instructions(venue))


# --- acquisition ------------------------------------------------------------


@v9_app.command("acquisition-status")
def acquisition_status(
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    since: Annotated[str, typer.Option(help="ISO-8601 UTC.")] = "2024-07-28T00:00:00Z",
    until: Annotated[str, typer.Option(help="ISO-8601 UTC.")] = "2026-07-28T00:00:00Z",
) -> None:
    """Report what evidence exists, and hand back a runbook when it does not."""
    from quant_trade.v9.acquisition import evaluate_acquisition
    from quant_trade.v9.preregistration import PROMOTION_GATES

    status = evaluate_acquisition(
        evidence_root=evidence_root,
        since_utc=since,
        until_utc=until,
        min_days=float(PROMOTION_GATES["min_span_days"]),
        min_settlements=int(PROMOTION_GATES["min_unique_settlements"]),
    )
    _echo(status.to_dict())


# --- artifacts --------------------------------------------------------------


@v9_app.command("artifacts")
def artifacts(
    repo_root: Annotated[str, typer.Option()] = ".",
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    out_dir: Annotated[str, typer.Option()] = DEFAULT_ARTIFACT_DIR,
    source_commit_sha: Annotated[str, typer.Option()] = "",
) -> None:
    """Regenerate every V9 artifact deterministically."""
    from quant_trade.v9.artifacts import generate_v9_artifacts

    result = generate_v9_artifacts(
        repo_root,
        evidence_root=evidence_root,
        out_dir=out_dir,
        source_commit_sha=source_commit_sha or None,
    )
    _echo(result.to_dict())


@v9_app.command("claim-guard")
def claim_guard(
    artifact_dir: Annotated[str, typer.Option()] = DEFAULT_ARTIFACT_DIR,
    docs_dir: Annotated[str, typer.Option()] = "docs",
) -> None:
    """Scan artifacts and docs for profit language the evidence cannot support."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.v9.economic_status import guard_artifacts, scan_for_unsupported_claims

    payloads: dict[str, object] = {}
    for path in sorted(Path(artifact_dir).glob("*.json")):
        if path.name == "PROFIT_CLAIM_GUARD.json":
            continue  # scanning the guard's own output would be circular
        payloads[path.name] = load_json(path)
    report = guard_artifacts(payloads)
    for path in sorted(Path(docs_dir).glob("*V9*.md")):
        report.scanned_sources.append(path.name)
        report.findings.extend(
            scan_for_unsupported_claims(
                path.read_text(encoding="utf-8"), source=path.name, context="report_prose"
            )
        )
    _echo(report.to_dict())


@v9_app.command("safety-report")
def safety_report() -> None:
    """State the execution boundary as data, so it can be checked rather than trusted."""
    from quant_trade.v9.safety import safety_report as build

    _echo(build())


def _canonical(payload: object) -> str:  # pragma: no cover - helper for callers
    return canonical_dumps(payload)


__all__ = ["v9_app"]
