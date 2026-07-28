"""Paper launch, gated on an actual candidate.

Nothing here starts a session on a hypothesis that did not pass. That is the
entire design constraint: a paper session for a strategy nobody validated
produces an equity curve, a dashboard and a sense of progress, all of which
are indistinguishable from the real thing and none of which mean anything.
So :func:`launch_paper_session` takes a manifest, and a manifest can only be
built from a campaign whose status is ``PAPER_CANDIDATE``.

Two further honesty rules are enforced mechanically rather than by convention:

* **Wall-clock and replay are different clocks.** A session that processed
  two years of recorded bars in ninety seconds ran for ninety seconds. The
  status separates ``wall_clock_seconds`` from ``simulated_span_days`` and
  refuses to add them together, so no report can imply the session has been
  live for days when it has been live for minutes.
* **A resume command is part of the deliverable.** A session that only exists
  inside one process is not an operational thing, so the status carries the
  exact supervised command that continues it.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    sha256_of_text,
)
from quant_trade.v8.campaigns import STATUS_PAPER_CANDIDATE, CampaignResult

PAPER_STATUS_NOT_STARTED = "NOT_STARTED_NO_CANDIDATE"
PAPER_STATUS_RUNNING = "RUNNING"
PAPER_STATUS_STOPPED = "STOPPED"

#: Clock semantics a session can advance under. Never mixed in one report.
CLOCK_WALL = "wall_clock"
CLOCK_REPLAY = "historical_replay"

#: Hard safety posture. Every field is asserted by a test.
SAFETY_POSTURE = {
    "real_money_authorized": False,
    "order_routing_enabled": False,
    "withdrawals_enabled": False,
    "deposits_enabled": False,
    "credentials_required": False,
    "venue_connectivity": "market_data_read_only",
}


class NoCandidateError(RuntimeError):
    """Refused to build a paper manifest without a passing campaign."""


@dataclass
class PaperCandidateManifest:
    """Everything frozen at the moment a candidate is accepted for paper."""

    candidate_id: str
    hypothesis_id: str
    title: str
    created_at_utc: str
    preregistration_hash: str
    code_commit_sha: str
    evidence: dict[str, Any] = field(default_factory=dict)
    frozen_config: dict[str, Any] = field(default_factory=dict)
    cost_stack: dict[str, Any] = field(default_factory=dict)
    allocation: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    expected_economics: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=lambda: dict(SAFETY_POSTURE))

    @property
    def manifest_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict(include_hash=False)))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact": "PAPER_CANDIDATE_MANIFEST",
            "schema_version": 1,
            **asdict(self),
        }
        if include_hash:
            payload["manifest_sha256"] = self.manifest_sha256
        return payload


def _code_commit_sha(repo_root: str | Path) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def build_paper_candidate_manifest(
    campaign: CampaignResult,
    *,
    created_at_utc: str,
    repo_root: str | Path = ".",
    capital_usd: float = 10_000.0,
    max_drawdown: float = 0.10,
    max_position_notional_usd: float | None = None,
) -> PaperCandidateManifest:
    """Freeze a passing campaign into a paper manifest.

    Raises :class:`NoCandidateError` for anything that did not pass every
    gate — including a campaign that never ran, which is the case this whole
    module exists to refuse.
    """
    if campaign.status != STATUS_PAPER_CANDIDATE:
        raise NoCandidateError(
            f"{campaign.hypothesis_id} is {campaign.status}, not "
            f"{STATUS_PAPER_CANDIDATE}; there is no candidate to launch. "
            f"Blocking reasons: {campaign.blocking_reasons[:3]}"
        )
    if capital_usd <= 0:
        raise ValueError("capital_usd must be > 0")

    selected = campaign.holdout.get("selected")
    parameters: dict[str, Any] = next(
        (v["parameters"] for v in campaign.variants_evaluated if v.get("variant_id") == selected),
        {},
    )
    capacity = float(campaign.capacity.get("capacity_notional_usd", 0.0) or 0.0)
    notional_cap = (
        max_position_notional_usd
        if max_position_notional_usd is not None
        else min(capital_usd, capacity)
        if capacity > 0
        else capital_usd
    )
    evidence_sha = ""
    for payload in campaign.evidence.get("venues", {}).values():
        evidence_sha = str(payload.get("sufficiency", {}).get("evidence_sha256", ""))
        if evidence_sha:
            break

    manifest = PaperCandidateManifest(
        candidate_id=f"{campaign.hypothesis_id}-{selected}",
        hypothesis_id=campaign.hypothesis_id,
        title=campaign.title,
        created_at_utc=created_at_utc,
        preregistration_hash=campaign.preregistration_hash,
        code_commit_sha=_code_commit_sha(repo_root),
        evidence={
            "dataset_sha256": evidence_sha,
            "venues": {
                venue: {
                    "directory": payload.get("directory"),
                    "provenance": payload.get("provenance"),
                    "raw_pages": payload.get("raw_pages"),
                    "receipts": payload.get("receipts"),
                    "span_days": payload.get("sufficiency", {}).get("span_days"),
                    "unique_settlements": payload.get("sufficiency", {}).get("unique_settlements"),
                }
                for venue, payload in campaign.evidence.get("venues", {}).items()
            },
        },
        frozen_config={
            "variant_id": selected,
            "parameters": parameters,
            "holdout": campaign.holdout,
        },
        cost_stack=campaign.cost_stack,
        allocation={
            "capital_usd": capital_usd,
            "instrument_weight": 1.0,
            "cash_weight": 0.0,
            "paper_only": True,
        },
        limits={
            "max_drawdown": max_drawdown,
            "max_position_notional_usd": notional_cap,
            "capacity_notional_usd": capacity,
            "kill_switch_on_reconciliation_error": True,
        },
        expected_economics={
            "net_return": campaign.economics.get("net_return"),
            "net_return_2x_costs": campaign.economics.get("net_return_2x_costs"),
            "net_return_3x_costs": campaign.economics.get("net_return_3x_costs"),
            "max_drawdown": campaign.economics.get("max_drawdown"),
            "holdout_net_return": campaign.economics.get("holdout_net_return"),
        },
    )
    return manifest


@dataclass
class PaperSessionReport:
    status: str
    reason: str = ""
    session_id: str = ""
    candidate_id: str = ""
    manifest_sha256: str = ""
    state_dir: str = ""
    clock: str = CLOCK_WALL
    started_at_utc: str = ""
    last_event_at_utc: str = ""
    wall_clock_seconds: float = 0.0
    simulated_span_days: float = 0.0
    events_processed: int = 0
    signals_emitted: int = 0
    paper_orders: int = 0
    paper_fills: int = 0
    equity_usd: float = 0.0
    drawdown: float = 0.0
    reconciliation: dict[str, Any] = field(default_factory=dict)
    heartbeat_at_utc: str = ""
    resume_command: str = ""
    safety: dict[str, Any] = field(default_factory=lambda: dict(SAFETY_POSTURE))
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact": "PAPER_STATUS",
            "schema_version": 1,
            **asdict(self),
        }
        payload["duration_note"] = (
            f"wall-clock {self.wall_clock_seconds:.1f}s; simulated span "
            f"{self.simulated_span_days:.2f}d. These are different clocks and "
            "are never summed."
        )
        return payload


def not_started_report(reason: str, *, resume_command: str = "") -> PaperSessionReport:
    """The honest status when no candidate exists: nothing is running."""
    return PaperSessionReport(
        status=PAPER_STATUS_NOT_STARTED,
        reason=reason,
        resume_command=resume_command,
        notes=[
            "no paper session was started; a session on an unvalidated "
            "hypothesis would produce an equity curve that means nothing",
            "the portfolio therefore remains 100% cash",
        ],
    )


def launch_paper_session(
    manifest: PaperCandidateManifest,
    state_dir: str | Path,
    *,
    started_at_utc: str,
    clock: str = CLOCK_WALL,
) -> PaperSessionReport:
    """Start a shadow/paper session from a frozen candidate manifest."""
    if clock not in (CLOCK_WALL, CLOCK_REPLAY):
        raise ValueError(f"clock must be {CLOCK_WALL!r} or {CLOCK_REPLAY!r}")
    from quant_trade.opportunities.shadow import shadow_start

    out = Path(state_dir)
    allocation = {
        "artifact": "PAPER_ALLOCATION",
        "paper_only": True,
        "total_capital_usd": float(manifest.allocation["capital_usd"]),
        "candidate_id": manifest.candidate_id,
        "manifest_sha256": manifest.manifest_sha256,
        "rows": [
            {
                "opportunity_id": manifest.candidate_id,
                "weight": 1.0,
                "capital_usd": float(manifest.allocation["capital_usd"]),
            }
        ],
    }
    state = shadow_start(
        out,
        allocation,
        started_at_utc=started_at_utc,
        commit_sha=manifest.code_commit_sha,
        max_drawdown=float(manifest.limits["max_drawdown"]),
    )
    atomic_write_json(out / "paper_candidate_manifest.json", manifest.to_dict())
    return PaperSessionReport(
        status=PAPER_STATUS_RUNNING,
        session_id=str(state["session_id"]),
        candidate_id=manifest.candidate_id,
        manifest_sha256=manifest.manifest_sha256,
        state_dir=str(out),
        clock=clock,
        started_at_utc=started_at_utc,
        equity_usd=float(manifest.allocation["capital_usd"]),
        resume_command=resume_command_for(out),
        heartbeat_at_utc=started_at_utc,
    )


#: Event kinds the paper journal understands.
EVENT_KINDS = ("signal", "paper_order", "paper_fill", "mark")

PAPER_EVENTS_FILENAME = "paper_events.jsonl"


def _read_paper_events(state_dir: Path) -> list[dict[str, Any]]:
    import json

    path = state_dir / PAPER_EVENTS_FILENAME
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _append_paper_events(state_dir: Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append trading-semantics events, hash-chained and exactly once.

    The shadow WAL owns equity and recovery, but its record carries only the
    cash-accrual fields — it has no notion of a signal, an order or a fill.
    Rather than widen that contract, the paper layer keeps its own journal
    with the same discipline: strictly increasing sequence, a hash chain, and
    a replayed batch that is skipped rather than double-counted.
    """
    existing = _read_paper_events(state_dir)
    by_seq = {int(record["seq"]): record for record in existing}
    previous_hash = str(existing[-1]["record_sha256"]) if existing else "0" * 64
    appended: list[dict[str, Any]] = []
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / PAPER_EVENTS_FILENAME).open("a", encoding="utf-8") as handle:
        for event in events:
            seq = int(event["seq"])
            kind = str(event.get("kind", "mark"))
            if kind not in EVENT_KINDS:
                raise ValueError(f"event kind must be one of {EVENT_KINDS}, got {kind!r}")
            payload = {
                "seq": seq,
                "timestamp_utc": str(event["timestamp_utc"]),
                "kind": kind,
                "cash_yield_daily": float(event.get("cash_yield_daily", 0.0)),
                "notional_usd": float(event.get("notional_usd", 0.0)),
                "previous_sha256": previous_hash,
            }
            prior = by_seq.get(seq)
            if prior is not None:
                comparable = {k: prior[k] for k in payload if k != "previous_sha256"}
                if comparable != {k: v for k, v in payload.items() if k != "previous_sha256"}:
                    raise ValueError(f"sequence {seq} conflicts with the paper event journal")
                continue
            payload["record_sha256"] = sha256_of_text(canonical_dumps(payload))
            handle.write(canonical_dumps(payload) + "\n")
            handle.flush()
            previous_hash = str(payload["record_sha256"])
            by_seq[seq] = payload
            appended.append(payload)
    return appended


def advance_paper_session(
    state_dir: str | Path,
    events: list[dict[str, Any]],
    *,
    clock: str = CLOCK_WALL,
    wall_clock_seconds: float | None = None,
    monotonic: Any = None,
) -> PaperSessionReport:
    """Apply market events exactly once and report what actually happened."""
    from quant_trade.opportunities.shadow import shadow_advance, shadow_status

    out = Path(state_dir)
    timer = monotonic or time.monotonic
    started = timer()
    if events:
        _append_paper_events(out, events)
        shadow_advance(
            out,
            [
                {
                    "seq": int(e["seq"]),
                    "timestamp_utc": str(e["timestamp_utc"]),
                    "cash_yield_daily": float(e.get("cash_yield_daily", 0.0)),
                }
                for e in events
            ],
        )
    elapsed = wall_clock_seconds if wall_clock_seconds is not None else timer() - started
    return _report(out, clock=clock, wall_clock_seconds=elapsed, status_fn=shadow_status)


def _report(
    state_dir: Path, *, clock: str, wall_clock_seconds: float, status_fn: Any
) -> PaperSessionReport:
    from quant_trade.carry.quality import parse_utc

    status = status_fn(state_dir)
    manifest_path = state_dir / "paper_candidate_manifest.json"
    manifest_sha = ""
    candidate_id = ""
    if manifest_path.exists():
        from quant_trade.evidence.canonical_json import load_json

        payload = load_json(manifest_path)
        if isinstance(payload, dict):
            manifest_sha = str(payload.get("manifest_sha256", ""))
            candidate_id = str(payload.get("candidate_id", ""))

    stamps: list[str] = []
    orders = fills = signals = 0
    for event in _read_paper_events(state_dir):
        stamps.append(str(event.get("timestamp_utc", "")))
        kind = str(event.get("kind", ""))
        if kind == "signal":
            signals += 1
        elif kind == "paper_order":
            orders += 1
        elif kind == "paper_fill":
            fills += 1
    simulated_days = 0.0
    if len(stamps) >= 2:
        simulated_days = (parse_utc(stamps[-1]) - parse_utc(stamps[0])).total_seconds() / 86_400.0

    return PaperSessionReport(
        status=PAPER_STATUS_RUNNING
        if status.get("status") == "RUNNING"
        else str(status.get("status", PAPER_STATUS_STOPPED)),
        session_id=str(status.get("session_id", "")),
        candidate_id=candidate_id,
        manifest_sha256=manifest_sha,
        state_dir=str(state_dir),
        clock=clock,
        started_at_utc=str(status.get("started_at_utc", "")),
        last_event_at_utc=stamps[-1] if stamps else "",
        wall_clock_seconds=float(wall_clock_seconds),
        simulated_span_days=simulated_days,
        events_processed=int(status.get("events_processed", 0)),
        signals_emitted=signals,
        paper_orders=orders,
        paper_fills=fills,
        equity_usd=float(status.get("equity_usd", 0.0)),
        drawdown=float(status.get("drawdown", 0.0)),
        reconciliation=dict(status.get("last_reconcile", {}) or {}),
        heartbeat_at_utc=stamps[-1] if stamps else str(status.get("started_at_utc", "")),
        resume_command=resume_command_for(state_dir),
        notes=(
            [f"integrity: {status['integrity_error']}"] if status.get("integrity_error") else []
        ),
    )


def paper_session_status(
    state_dir: str | Path, *, clock: str = CLOCK_WALL, wall_clock_seconds: float = 0.0
) -> PaperSessionReport:
    from quant_trade.opportunities.shadow import shadow_status

    return _report(
        Path(state_dir),
        clock=clock,
        wall_clock_seconds=wall_clock_seconds,
        status_fn=shadow_status,
    )


def resume_command_for(state_dir: str | Path) -> str:
    """The exact supervised command that continues this session."""
    return f"quant-trade v8 paper-status --state-dir {Path(state_dir).as_posix()}"


__all__ = [
    "CLOCK_REPLAY",
    "CLOCK_WALL",
    "PAPER_STATUS_NOT_STARTED",
    "PAPER_STATUS_RUNNING",
    "PAPER_STATUS_STOPPED",
    "SAFETY_POSTURE",
    "NoCandidateError",
    "PaperCandidateManifest",
    "PaperSessionReport",
    "advance_paper_session",
    "build_paper_candidate_manifest",
    "launch_paper_session",
    "not_started_report",
    "paper_session_status",
    "resume_command_for",
]
