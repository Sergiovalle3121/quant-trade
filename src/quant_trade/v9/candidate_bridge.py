"""Connect a backtest candidate to a paper session.

V8 could produce a passing campaign and, in the same run, write a paper status
that said ``NOT_STARTED_NO_CANDIDATE``. The two halves never spoke: the
artifact generator called the not-started constructor unconditionally, so the
one thing an operator would check to find out whether there was something to
run reported that there was not.

The bridge makes the three cases distinct and mutually exclusive:

``NOT_STARTED_NO_CANDIDATE``
    no campaign reached ``BACKTEST_CANDIDATE``. Nothing to run.
``CANDIDATE_READY_PAPER_NOT_STARTED``
    a candidate exists, a manifest was built and frozen, and the exact command
    to start the session is in the artifact. The session has not been started —
    which is a fact about operations, not about the candidate.
``PAPER_RUNNING`` / ``PAPER_HALTED`` / ``PAPER_STOPPED``
    a session exists; its own status governs.

The distinction matters because "no candidate" and "candidate not launched"
call for opposite actions from whoever reads the file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.v9.paper_session import SessionConfig

STATUS_NO_CANDIDATE = "NOT_STARTED_NO_CANDIDATE"
STATUS_CANDIDATE_READY = "CANDIDATE_READY_PAPER_NOT_STARTED"

#: Bars are hourly, so a session driven by them must tolerate an hour between
#: ticks. A 15-minute staleness threshold would trip on the first bar.
HOURLY_STALE_TICK_SECONDS = 2 * 3600.0


@dataclass
class PaperCandidateManifestV9:
    """Everything frozen at the moment a candidate becomes runnable."""

    candidate_id: str
    hypothesis_id: str
    created_at_utc: str
    preregistration_hash: str
    code_commit_sha: str
    dataset_sha256: str
    cost_bundle_sha256: str
    strategy: dict[str, Any]
    execution: dict[str, Any]
    allocation: dict[str, Any]
    limits: dict[str, Any]
    expected_economics: dict[str, Any] = field(default_factory=dict)

    @property
    def manifest_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact": "PAPER_CANDIDATE_MANIFEST_V9",
            "schema_version": 2,
            **asdict(self),
        }
        payload["manifest_sha256"] = self.manifest_sha256
        payload["safety"] = {
            "live_order_submission": "DISABLED",
            "live_broker_execution": "DISABLED",
            "real_money_authorized": False,
        }
        return payload

    def session_config(self, session_id: str) -> SessionConfig:
        """Derive the paper session config. Nothing is invented here."""
        return SessionConfig(
            session_id=session_id,
            candidate_id=self.candidate_id,
            manifest_sha256=self.manifest_sha256,
            initial_capital_usd=float(self.allocation["capital_usd"]),
            strategy=dict(self.strategy),
            execution=dict(self.execution),
            max_drawdown=float(self.limits["max_drawdown"]),
            perp_leverage=float(self.limits.get("perp_leverage", 3.0)),
            stale_tick_seconds=float(
                self.limits.get("stale_tick_seconds", HOURLY_STALE_TICK_SECONDS)
            ),
        )


@dataclass
class CandidateBridgeResult:
    status: str
    candidate_id: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)
    start_command: str = ""
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def has_candidate(self) -> bool:
        return self.status != STATUS_NO_CANDIDATE

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["has_candidate"] = self.has_candidate
        return payload


def build_manifest_from_campaign(
    campaign: Any,
    *,
    created_at_utc: str,
    code_commit_sha: str = "",
    capital_usd: float = 1_000.0,
    max_drawdown: float = 0.10,
) -> PaperCandidateManifestV9:
    """Freeze a passing campaign into a runnable manifest."""
    selected = str(campaign.holdout.get("selected", "") or "")
    parameters: dict[str, Any] = next(
        (
            dict(v["parameters"])
            for v in campaign.variants_evaluated
            if v.get("variant_id") == selected
        ),
        {},
    )
    venues = campaign.evidence.get("venues", {}) or {}
    first_venue: dict[str, Any] = next(iter(venues.values()), {})
    capacity = float(campaign.capacity.get("capacity_notional_usd", 0.0) or 0.0)
    target_notional = min(capital_usd, capacity) if capacity > 0 else capital_usd
    cost_stack = campaign.cost_stack or {}
    by_name = {c["name"]: float(c["value"]) for c in cost_stack.get("components", []) or []}
    return PaperCandidateManifestV9(
        candidate_id=f"{campaign.hypothesis_id}-{selected}" if selected else campaign.hypothesis_id,
        hypothesis_id=campaign.hypothesis_id,
        created_at_utc=created_at_utc,
        preregistration_hash=campaign.preregistration_hash,
        code_commit_sha=code_commit_sha,
        dataset_sha256=str((first_venue.get("sufficiency", {}) or {}).get("evidence_sha256", "")),
        cost_bundle_sha256=str(cost_stack.get("bundle_sha256", "")),
        strategy={
            "entry_threshold": float(parameters.get("entry_threshold", 0.0)),
            "trailing_window": int(parameters.get("trailing_window", 1)),
            "target_notional_usd": target_notional,
        },
        execution={
            "latency_ms": 250,
            "slippage_bps": by_name.get("slippage", 1.0),
            "max_participation": 0.01,
            "spot_fee_bps": by_name.get("spot_taker_fee", 10.0),
            "perp_fee_bps": by_name.get("perp_taker_fee", 5.5),
        },
        allocation={"capital_usd": capital_usd, "paper_only": True},
        limits={
            "max_drawdown": max_drawdown,
            "perp_leverage": 3.0,
            "stale_tick_seconds": HOURLY_STALE_TICK_SECONDS,
            "capacity_notional_usd": capacity,
        },
        expected_economics={
            "holdout_net_return": campaign.economics.get("holdout_net_return"),
            "oos_net_return": campaign.economics.get("oos_net_return"),
            "net_return_2x_costs": campaign.economics.get("net_return_2x_costs"),
        },
    )


def bridge_candidate_to_paper(
    campaigns: list[Any],
    *,
    created_at_utc: str,
    state_dir: str | Path,
    code_commit_sha: str = "",
    capital_usd: float = 1_000.0,
    candidate_status: str = "BACKTEST_CANDIDATE",
) -> CandidateBridgeResult:
    """Turn the campaign results into a runnable paper handoff, or say why not."""
    promoted = [c for c in campaigns if getattr(c, "status", "") == candidate_status]
    if not promoted:
        return CandidateBridgeResult(
            status=STATUS_NO_CANDIDATE,
            reason=(
                "no campaign reached "
                f"{candidate_status}: "
                + "; ".join(f"{c.hypothesis_id}={c.status}" for c in campaigns)
            ),
            notes=[
                "there is nothing to run; a session started here would produce an "
                "equity curve that means nothing",
            ],
        )
    best = max(promoted, key=lambda c: float(c.economics.get("net_return", 0.0) or 0.0))
    manifest = build_manifest_from_campaign(
        best,
        created_at_utc=created_at_utc,
        code_commit_sha=code_commit_sha,
        capital_usd=capital_usd,
    )
    return CandidateBridgeResult(
        status=STATUS_CANDIDATE_READY,
        candidate_id=manifest.candidate_id,
        manifest=manifest.to_dict(),
        start_command=(
            f"quant-trade v9 paper-start --state-dir {Path(state_dir).as_posix()} "
            f"--manifest <path-to-manifest.json>"
        ),
        reason=(
            f"{best.hypothesis_id} reached {candidate_status}; the manifest is frozen "
            "and the session is startable"
        ),
        notes=[
            "the session has not been started: that is a fact about operations, "
            "not about the candidate",
            "72h of wall-clock paper is the minimum before any canary discussion, "
            "and it cannot be simulated or accelerated",
        ],
    )


__all__ = [
    "HOURLY_STALE_TICK_SECONDS",
    "STATUS_CANDIDATE_READY",
    "STATUS_NO_CANDIDATE",
    "CandidateBridgeResult",
    "PaperCandidateManifestV9",
    "bridge_candidate_to_paper",
    "build_manifest_from_campaign",
]
