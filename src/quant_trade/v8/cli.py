"""``quant-trade v8`` — evidence acquisition, campaigns, paper and artifacts.

Deliberate omissions are as much a part of this interface as the commands.
There is no flag to label captured data as ``live``: provenance follows from
*how* the bytes were obtained, so the live path sets it and the fixture path
sets it, and no operator can promote recorded responses by passing an
argument. There is likewise no command that buys, deposits, withdraws, starts
a miner, or submits an order.
"""

from __future__ import annotations

import calendar
import json
import time
from pathlib import Path
from typing import Annotated

import typer

from quant_trade.evidence.canonical_json import atomic_write_json, canonical_dumps

v8_app = typer.Typer(help="V8 real-alpha evidence, campaigns, paper and artifacts.")

DEFAULT_EVIDENCE_ROOT = "data/v8_evidence"
DEFAULT_ARTIFACT_DIR = "artifacts/v8"


def _parse_utc(value: str) -> int:
    """ISO-8601 UTC to epoch milliseconds. Local timezones never enter here."""
    text = value.strip().replace("Z", "")
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return int(calendar.timegm(time.strptime(text, pattern)) * 1000)
        except ValueError:
            continue
    raise typer.BadParameter(f"cannot parse {value!r} as an ISO-8601 UTC timestamp")


@v8_app.command("probe-network")
def probe_network(
    out: Annotated[str, typer.Option(help="Where to write the probe artifact.")] = (
        f"{DEFAULT_ARTIFACT_DIR}/NETWORK_REACHABILITY_PROBE.json"
    ),
) -> None:
    """Probe each venue's own documented domains and record what happened.

    Only venue-published hosts are tried. A blocked host is reported, never
    routed around.
    """
    from quant_trade.v8.network_probe import probe_domains

    report = probe_domains()
    atomic_write_json(out, report.to_dict())
    for probe in report.probes:
        typer.echo(f"{probe.venue:6} {probe.host:24} {probe.outcome:24} {probe.error[:60]}")
    typer.echo(f"reachable: {report.reachable_venues or 'none'}")
    typer.echo(f"blocked:   {report.blocked_venues or 'none'}")
    typer.echo(f"written:   {out}")


@v8_app.command("evidence-backfill")
def evidence_backfill(
    venue: Annotated[str, typer.Option(help="bybit or okx.")],
    symbol: Annotated[str, typer.Option(help="Canonical base, e.g. BTC.")] = "BTC",
    since: Annotated[str, typer.Option(help="ISO-8601 UTC lower bound.")] = "",
    until: Annotated[str, typer.Option(help="ISO-8601 UTC upper bound.")] = "",
    interval_minutes: Annotated[int, typer.Option(help="Bar interval.")] = 60,
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    build_panel: Annotated[bool, typer.Option(help="Build the carry panel after.")] = True,
) -> None:
    """Backfill spot/perp/mark/index/funding from the venue's public API.

    Resumable and idempotent: pages already archived are replayed from disk,
    so an interrupted run continues rather than restarting. A blocked network
    records the verbatim error and exits non-zero.
    """
    from quant_trade.v8.backfill import STATUS_OK, BackfillRequest, run_backfill
    from quant_trade.v8.panel_builder import build_panel_from_evidence

    if not since or not until:
        raise typer.BadParameter("--since and --until are required")
    since_ms, until_ms = _parse_utc(since), _parse_utc(until)
    request = BackfillRequest(
        venue=venue.lower(),
        symbol=symbol,
        since_ms=since_ms,
        until_ms=until_ms,
        interval_minutes=interval_minutes,
    )
    # source_kind is NOT an option: only a genuine live fetch may claim it.
    result = run_backfill(request, evidence_root, source_kind="live")
    typer.echo(f"status: {result.status}")
    for kind, series in sorted(result.series.items()):
        typer.echo(
            f"  {kind:8} rows={series.rows:<7} fetched={series.pages_fetched:<5} "
            f"replayed={series.pages_replayed:<5} {series.error[:70]}"
        )
    if result.blocked_hosts:
        typer.echo(f"blocked hosts: {', '.join(result.blocked_hosts)}")
    if result.status != STATUS_OK:
        typer.echo(f"evidence dir: {result.evidence_dir}")
        raise typer.Exit(code=1)
    if build_panel:
        built = build_panel_from_evidence(
            result.evidence_dir,
            venue=request.venue,
            symbol=symbol,
            interval_minutes=interval_minutes,
            since_ms=since_ms,
            until_ms=until_ms,
            provenance="real",
        )
        typer.echo(f"panel: {built.status} rows={built.rows} settlements={built.settlements}")
        for problem in built.problems[:5]:
            typer.echo(f"  problem: {problem}")


@v8_app.command("evidence-validate")
def evidence_validate(
    venue: Annotated[str, typer.Option()],
    symbol: Annotated[str, typer.Option()] = "BTC",
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
) -> None:
    """Validate an evidence directory against the pre-registered gates."""
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.v8.backfill import evidence_dir_for
    from quant_trade.v8.preregistration import PROMOTION_GATES
    from quant_trade.v8.validation import sufficiency_report, validate_evidence_dir

    directory = evidence_dir_for(evidence_root, venue, symbol)
    context_path = directory / "backfill_result.json"
    context = load_json(context_path) if context_path.exists() else {}
    context = context if isinstance(context, dict) else {}
    validation = validate_evidence_dir(
        directory,
        since_ms=int(context.get("since_ms", 0) or 0),
        until_ms=int(context.get("until_ms", 0) or 0),
        interval_minutes=int(context.get("interval_minutes", 60) or 60),
        venue=venue,
        symbol=symbol,
    )
    sufficiency = sufficiency_report(
        validation,
        min_days=float(PROMOTION_GATES["min_span_days"]),
        min_settlements=int(PROMOTION_GATES["min_unique_settlements"]),
    )
    typer.echo(canonical_dumps({"validation": validation.to_dict(), "sufficiency": sufficiency}))
    if not sufficiency["sufficient"]:
        raise typer.Exit(code=1)


@v8_app.command("evidence-pack")
def evidence_pack(
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    out_dir: Annotated[str, typer.Option()] = "data/v8_packs",
    pack_id: Annotated[str, typer.Option()] = "v8",
    created_at_utc: Annotated[str, typer.Option()] = "2026-07-28T08:00:00Z",
    redistribution: Annotated[
        str, typer.Option(help="PERMITTED_DOCUMENTED | PROHIBITED_DOCUMENTED | UNRESOLVED")
    ] = "UNRESOLVED",
    reason: Annotated[str, typer.Option()] = "",
    source_terms: Annotated[str, typer.Option()] = "",
) -> None:
    """Build a deterministic, content-addressed evidence pack."""
    from quant_trade.v8.evidence_pack import build_evidence_pack

    root = Path(evidence_root)
    sources = {
        directory.name: directory
        for directory in sorted(root.iterdir())
        if directory.is_dir() and (directory / "receipts.jsonl").exists()
    }
    if not sources:
        typer.echo(f"no evidence directories under {root}")
        raise typer.Exit(code=1)
    manifest = build_evidence_pack(
        sources,
        out_dir,
        pack_id=pack_id,
        created_at_utc=created_at_utc,
        rebuild_command=(
            "quant-trade v8 evidence-backfill --venue <venue> --symbol BTC "
            "--since <iso> --until <iso>"
        ),
        redistribution_stance=redistribution,
        redistribution_reason=reason,
        redistribution_source_terms=source_terms,
    )
    typer.echo(f"archive:      {manifest.archive_name}")
    typer.echo(f"sha256:       {manifest.archive_sha256}")
    typer.echo(f"merkle_root:  {manifest.merkle_root}")
    typer.echo(f"files:        {len(manifest.entries)}")
    typer.echo(f"bytes:        {manifest.total_bytes} raw / {manifest.archive_bytes} packed")
    typer.echo(f"committable:  {manifest.redistribution['committable_to_git']}")


@v8_app.command("evidence-verify")
def evidence_verify(
    pack: Annotated[str, typer.Option(help="Path to the .tar.gz pack.")],
    manifest: Annotated[str, typer.Option(help="Path to EVIDENCE_PACK_MANIFEST.json.")],
    import_to: Annotated[str, typer.Option(help="Extract here when verified.")] = "",
) -> None:
    """Verify a pack byte-for-byte, re-parsing every archived response."""
    from quant_trade.v8.evidence_pack import import_evidence_pack, verify_evidence_pack

    report = (
        import_evidence_pack(pack, manifest, import_to)
        if import_to
        else verify_evidence_pack(pack, manifest)
    )
    typer.echo(f"status:            {report.status}")
    typer.echo(f"files:             {report.files_matched}/{report.files_checked}")
    typer.echo(f"archive sha256:    {report.archive_sha256_matches}")
    typer.echo(f"merkle root:       {report.merkle_root_matches}")
    typer.echo(f"receipt chains:    {report.receipt_chains_verified}")
    typer.echo(f"pages re-parsed:   {report.pages_reparsed}")
    typer.echo(f"series rebuilt:    {report.series_rebuilt}")
    for problem in report.problems[:10]:
        typer.echo(f"  problem: {problem}")
    if not report.is_verified:
        raise typer.Exit(code=1)


@v8_app.command("campaign")
def campaign(
    hypothesis: Annotated[str, typer.Option(help="H1, H2, H3 or 'all'.")] = "all",
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    trial_registry: Annotated[str, typer.Option()] = "",
) -> None:
    """Run pre-registered campaigns against the available evidence."""
    from quant_trade.v8.campaigns import run_all_campaigns, run_campaign

    registry = trial_registry or None
    if hypothesis.lower() == "all":
        results = run_all_campaigns(evidence_root=evidence_root, trial_registry_path=registry)
    else:
        results = [
            run_campaign(
                hypothesis.upper(), evidence_root=evidence_root, trial_registry_path=registry
            )
        ]
    for result in results:
        typer.echo(f"{result.hypothesis_id}: {result.status}")
        if result.ran:
            typer.echo(
                f"  net={result.economics.get('net_return'):.6f} "
                f"2x={result.economics.get('net_return_2x_costs'):.6f} "
                f"3x={result.economics.get('net_return_3x_costs'):.6f}"
            )
        for reason in result.blocking_reasons[:4]:
            typer.echo(f"  blocked: {reason}")
    if not any(r.promoted for r in results):
        typer.echo("outcome: NO_EDGE_FOUND (no hypothesis cleared every gate)")


@v8_app.command("paper-status")
def paper_status(
    state_dir: Annotated[str, typer.Option(help="Paper session state directory.")],
    wall_clock_seconds: Annotated[float, typer.Option()] = 0.0,
) -> None:
    """Report a paper session's real state. Never claims more than it ran."""
    from quant_trade.v8.paper_launch import paper_session_status

    if not (Path(state_dir) / "state.json").exists():
        typer.echo(f"no paper session at {state_dir}")
        raise typer.Exit(code=1)
    report = paper_session_status(state_dir, wall_clock_seconds=wall_clock_seconds)
    typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))


@v8_app.command("revenue-run")
def revenue_run(
    repo_root: Annotated[str, typer.Option()] = ".",
    evidence_root: Annotated[str, typer.Option()] = DEFAULT_EVIDENCE_ROOT,
    out_dir: Annotated[str, typer.Option()] = DEFAULT_ARTIFACT_DIR,
    source_commit_sha: Annotated[str, typer.Option()] = "",
    verify_determinism: Annotated[
        bool, typer.Option(help="Regenerate twice and compare hashes.")
    ] = False,
) -> None:
    """Run the whole V8 pipeline and regenerate every artifact.

    This is the end-to-end command: campaigns, paper gating, canary readiness,
    the opportunity board and the diagnosis, all written deterministically.
    """
    from quant_trade.v8.artifacts import artifact_fingerprint, generate_v8_artifacts

    first = generate_v8_artifacts(
        repo_root,
        evidence_root=evidence_root,
        out_dir=out_dir,
        source_commit_sha=source_commit_sha or None,
    )
    typer.echo(f"outcome: {first.outcome}")
    for name, digest in sorted(first.hashes.items()):
        typer.echo(f"{digest}  {name}")
    if verify_determinism:
        second = generate_v8_artifacts(
            repo_root,
            evidence_root=evidence_root,
            out_dir=out_dir,
            source_commit_sha=source_commit_sha or None,
        )
        if artifact_fingerprint(first.hashes) != artifact_fingerprint(second.hashes):
            differing = [
                name for name, digest in first.hashes.items() if second.hashes.get(name) != digest
            ]
            typer.echo(f"NON-DETERMINISTIC: {sorted(differing)}")
            raise typer.Exit(code=1)
        typer.echo("determinism: two regenerations produced identical hashes")


__all__ = ["v8_app"]
