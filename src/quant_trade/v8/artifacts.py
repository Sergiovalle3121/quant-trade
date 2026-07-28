"""Deterministic regeneration of every V8 artifact.

Two properties make these files worth having, and both are enforced here
rather than assumed:

**Determinism.** Regenerating on the same frozen evidence produces
byte-identical files. Everything time-dependent is pinned — a fixed
evaluation clock, no wall-clock reads, no randomness, seeded bootstraps — and
the network probe is *read from a recorded artifact* rather than re-run,
because a live probe is by definition not reproducible. A test regenerates
twice and compares hashes.

**No silent optimism.** Where something was not measured, the artifact says
``measured: false`` and carries the reason, instead of a zero that reads like
a finding. The diagnosis distinguishes "the strategy lost money" from "we
never got the data", which are the two conclusions most easily confused and
the most expensive to confuse.

This module performs only local reads and writes. It never opens a socket,
submits an order, or authorises spend.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.v8 import V8_SCHEMA_VERSION
from quant_trade.v8.campaigns import (
    STATUS_NO_EVIDENCE,
    STATUS_PAPER_CANDIDATE,
    CampaignResult,
    additional_hypotheses_unlocked,
    run_all_campaigns,
)
from quant_trade.v8.canary import evaluate_canary_readiness
from quant_trade.v8.paper_launch import not_started_report
from quant_trade.v8.preregistration import PROMOTION_GATES, freeze_hash, preregistration
from quant_trade.v8.validation import validate_evidence_dir

#: Fixed evaluation clock. Regeneration must not depend on when it runs.
EVALUATED_AT_UTC = "2026-07-28T08:00:00Z"

#: The V7 commit this sprint started from.
BASE_SHA = "596c2accd5c535f3c537a4439a96b94e521e4018"

ARTIFACT_NAMES = (
    "V8_PREREGISTRATION.json",
    "EVIDENCE_INDEX.json",
    "REAL_TRADING_CAMPAIGNS.json",
    "TRADING_LEADERBOARD.json",
    "MINING_MARKETPLACE_SCAN.json",
    "UNIFIED_OPPORTUNITY_BOARD.json",
    "PAPER_STATUS.json",
    "CANARY_READINESS.json",
    "NO_EDGE_DIAGNOSIS.json",
    "REGENERATION_MANIFEST.json",
)

#: Recorded inputs the generator reads rather than re-measures.
NETWORK_PROBE_FILENAME = "NETWORK_REACHABILITY_PROBE.json"
RECORDED_MINING_SCAN_FILENAME = "MINING_MARKETPLACE_SCAN.recorded.json"

OUTCOME_PAPER_CANDIDATE = "PAPER_CANDIDATE"
OUTCOME_NO_EDGE = "NO_EDGE_FOUND"


def _source_commit(repo_root: Path) -> str:
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


@dataclass
class GenerationResult:
    out_dir: str
    hashes: dict[str, str]
    outcome: str
    campaigns: list[CampaignResult]

    def to_dict(self) -> dict[str, Any]:
        return {"out_dir": self.out_dir, "hashes": self.hashes, "outcome": self.outcome}


# --- evidence index --------------------------------------------------------------


def _evidence_index(evidence_root: Path, probe: dict[str, Any]) -> dict[str, Any]:
    from quant_trade.v8.backfill import evidence_dir_for

    datasets: list[dict[str, Any]] = []
    total_pages = total_bytes = total_settlements = 0
    for venue in ("bybit", "okx"):
        directory = evidence_dir_for(evidence_root, venue, "BTC")
        entry: dict[str, Any] = {
            "venue": venue,
            "symbol": "BTC-USDT",
            "directory": str(directory.relative_to(evidence_root))
            if directory.is_relative_to(evidence_root)
            else str(directory),
            "present": directory.exists(),
        }
        if not directory.exists():
            entry["reason"] = "no evidence directory: acquisition never completed for this venue"
            datasets.append(entry)
            continue
        context_path = directory / "backfill_result.json"
        context = load_json(context_path) if context_path.exists() else {}
        context = context if isinstance(context, dict) else {}
        validation = validate_evidence_dir(
            directory,
            since_ms=int(context.get("since_ms", 0) or 0),
            until_ms=int(context.get("until_ms", 0) or 0),
            interval_minutes=int(context.get("interval_minutes", 60) or 60),
            venue=venue,
            symbol="BTC",
        )
        settlements = validation.settlements or {}
        entry.update(
            {
                "provenance": validation.provenance,
                "raw_pages": validation.raw_pages,
                "raw_bytes": validation.raw_bytes,
                "receipts": validation.receipts,
                "receipt_chain_clean": not validation.receipt_chain_problems,
                "unique_settlements": settlements.get("unique_settlements", 0),
                "span_days": settlements.get("span_days", 0.0),
                "interval_changes": settlements.get("interval_changes", 0),
                "realized_rate_rows": settlements.get("realized_rate_rows", 0),
                "announced_rate_rows": settlements.get("announced_rate_rows", 0),
                "panel_rows": sum(
                    int(s.get("rows", 0)) for s in (validation.series or {}).values()
                ),
                "validation_clean": validation.is_clean,
                "problems": validation.problems[:10],
            }
        )
        total_pages += validation.raw_pages
        total_bytes += validation.raw_bytes
        total_settlements += int(settlements.get("unique_settlements", 0) or 0)
        datasets.append(entry)

    return {
        "artifact": "EVIDENCE_INDEX",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "evidence_root": str(evidence_root),
        "datasets": datasets,
        "totals": {
            "raw_pages": total_pages,
            "raw_bytes": total_bytes,
            "unique_settlements": total_settlements,
            "venues_with_evidence": sum(1 for d in datasets if d.get("present")),
        },
        "requirements": {
            "min_span_days": PROMOTION_GATES["min_span_days"],
            "min_unique_settlements": PROMOTION_GATES["min_unique_settlements"],
            "required_provenance": "real (receipt-verified live capture)",
        },
        "acquisition_blocker": {
            "reachable_venues": probe.get("reachable_venues", []),
            "blocked_venues": probe.get("blocked_venues", []),
            "probes": probe.get("probes", []),
            "policy": probe.get("policy", ""),
        },
        "rebuild_command": (
            "quant-trade v8 evidence-backfill --venue <bybit|okx> --symbol BTC "
            "--since <iso> --until <iso> && quant-trade v8 evidence-pack"
        ),
    }


# --- campaigns / leaderboard -------------------------------------------------------


def _campaigns_artifact(campaigns: list[CampaignResult]) -> dict[str, Any]:
    unlocked, unlock_reason = additional_hypotheses_unlocked(campaigns)
    return {
        "artifact": "REAL_TRADING_CAMPAIGNS",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "preregistration_hash": freeze_hash(),
        "campaigns": [c.to_dict() for c in campaigns],
        "executed_count": sum(1 for c in campaigns if c.ran),
        "promoted_count": sum(1 for c in campaigns if c.promoted),
        "additional_hypotheses": {
            "unlocked": unlocked,
            "reason": unlock_reason,
            "registered": ["H6", "H7"],
            "executed": [],
        },
    }


def _leaderboard(campaigns: list[CampaignResult]) -> dict[str, Any]:
    rows = []
    for campaign in campaigns:
        economics = campaign.economics
        statistics = campaign.statistics
        rows.append(
            {
                "rank": None,
                "hypothesis_id": campaign.hypothesis_id,
                "title": campaign.title,
                "status": campaign.status,
                "measured": campaign.ran,
                "net_return": economics.get("net_return"),
                "net_return_2x_costs": economics.get("net_return_2x_costs"),
                "net_return_3x_costs": economics.get("net_return_3x_costs"),
                "max_drawdown": economics.get("max_drawdown"),
                "sharpe_per_period": statistics.get("sharpe_per_period"),
                "probabilistic_sharpe": statistics.get("probabilistic_sharpe"),
                "deflated_sharpe": statistics.get("deflated_sharpe"),
                "cscv_pbo": (statistics.get("cscv") or {}).get("pbo"),
                "bootstrap_p05": (statistics.get("bootstrap") or {}).get("total_return_p05"),
                "capacity_notional_usd": campaign.capacity.get("capacity_notional_usd"),
                "blocking_reasons": campaign.blocking_reasons[:5],
            }
        )
    measured = [r for r in rows if r["measured"]]
    measured.sort(key=lambda r: float(r["net_return"] or 0.0), reverse=True)  # type: ignore[arg-type]
    for index, row in enumerate(measured, start=1):
        row["rank"] = index
    ordered = measured + [r for r in rows if not r["measured"]]
    winner = next(
        (r for r in ordered if r["status"] == STATUS_PAPER_CANDIDATE),
        None,
    )
    return {
        "artifact": "TRADING_LEADERBOARD",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "rows": ordered,
        "winner": winner,
        "note": (
            "Unmeasured rows are listed last and are never ranked. A campaign "
            "that did not run has no economic position, favourable or otherwise."
        ),
    }


# --- diagnosis ---------------------------------------------------------------------


def _diagnosis(campaigns: list[CampaignResult]) -> dict[str, Any]:
    entries = []
    for campaign in campaigns:
        economics = campaign.economics
        statistics = campaign.statistics
        break_even = campaign.break_even.get("scenarios", {})
        entry: dict[str, Any] = {
            "hypothesis_id": campaign.hypothesis_id,
            "title": campaign.title,
            "status": campaign.status,
            "measured": campaign.ran,
            "gross_return": economics.get("gross_return"),
            "gross_components": economics.get("gross_components"),
            "cost_components": economics.get("cost_components"),
            "total_costs": economics.get("total_costs"),
            "net_return": economics.get("net_return"),
            "max_drawdown": economics.get("max_drawdown"),
            "sharpe_per_period": statistics.get("sharpe_per_period"),
            "probabilistic_sharpe": statistics.get("probabilistic_sharpe"),
            "deflated_sharpe": statistics.get("deflated_sharpe"),
            "cscv_pbo": (statistics.get("cscv") or {}).get("pbo"),
            "bootstrap_p05": (statistics.get("bootstrap") or {}).get("total_return_p05"),
            "net_return_2x_costs": economics.get("net_return_2x_costs"),
            "net_return_3x_costs": economics.get("net_return_3x_costs"),
            "holdout_net_return": economics.get("holdout_net_return"),
            "minimum_capital_usd": campaign.break_even.get("capital", {}).get("total_capital_usd"),
            "capacity_notional_usd": campaign.capacity.get("capacity_notional_usd"),
            "promotion_reasons": [g["gate"] for g in campaign.gate_results if g.get("passed")],
            "rejection_reasons": campaign.blocking_reasons,
            "break_even": {
                "required_funding_rate_per_8h_1x": break_even.get("1x", {}).get(
                    "required_funding_rate_per_interval"
                ),
                "required_funding_rate_per_8h_2x": break_even.get("2x", {}).get(
                    "required_funding_rate_per_interval"
                ),
                "required_funding_rate_per_8h_3x": break_even.get("3x", {}).get(
                    "required_funding_rate_per_interval"
                ),
                "required_annualized_funding_1x": break_even.get("1x", {}).get(
                    "required_annualized_funding"
                ),
                "round_trip_cost_fraction": break_even.get("1x", {}).get("round_trip_fraction"),
                "annual_carrying_fraction": break_even.get("1x", {}).get(
                    "annual_carrying_fraction"
                ),
            },
        }
        entry["what_would_have_to_change"] = _what_would_change(campaign, entry)
        entries.append(entry)

    unmeasured = [e for e in entries if not e["measured"]]
    return {
        "artifact": "NO_EDGE_DIAGNOSIS",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "preregistration_hash": freeze_hash(),
        "candidates": entries,
        "summary": {
            "measured": len(entries) - len(unmeasured),
            "unmeasured": len(unmeasured),
            "promoted": sum(1 for e in entries if e["status"] == STATUS_PAPER_CANDIDATE),
        },
        "interpretation": (
            "A candidate with measured=false has no economic verdict. Its "
            "break-even numbers are still exact — they follow from the cost "
            "stack and holding period, not from price history — so they define "
            "the bar the missing data would have to clear."
        ),
        "next_preregistered_experiment": _next_experiment(campaigns),
    }


def _what_would_change(campaign: CampaignResult, entry: dict[str, Any]) -> list[str]:
    """Concrete, quantified changes that would move this candidate to viable."""
    changes: list[str] = []
    if not campaign.ran:
        if campaign.status == STATUS_NO_EVIDENCE:
            changes.append(
                "Acquire the dataset. Nothing about this hypothesis has been "
                "measured, so no economic change is implied by its current state."
            )
        else:
            for reason in campaign.blocking_reasons[:5]:
                changes.append(f"Close the evidence shortfall: {reason}")
        required = entry["break_even"]["required_funding_rate_per_8h_1x"]
        if required is not None:
            changes.append(
                f"Once acquired, average settled funding must exceed {required:.8f} "
                f"per 8h settlement ({entry['break_even']['required_annualized_funding_1x']:.2%} "
                "annualised) merely to cover frictions at 1x costs."
            )
        return changes

    net = float(entry["net_return"] or 0.0)
    if net <= 0:
        deficit = -net
        changes.append(
            f"Net return is {net:.4%}; it must improve by {deficit:.4%} to reach "
            "break-even, through either lower fees or higher settled funding."
        )
    two_x = entry["net_return_2x_costs"]
    if two_x is not None and float(two_x) <= 0:
        changes.append(
            f"At 2x costs the return is {float(two_x):.4%}; the strategy has no "
            "margin for cost error and would need roughly half its current "
            "friction to survive the stress case."
        )
    for gate in campaign.gate_results:
        if gate.get("passed"):
            continue
        if gate["gate"] == "cost_evidence_promotable":
            changes.append(
                "Capture the venue fee schedule from the venue itself. The current "
                "stack is assumption-based, which is disqualifying regardless of "
                "how good the returns look."
            )
        elif gate["gate"] in ("probabilistic_sharpe", "deflated_sharpe"):
            changes.append(
                f"{gate['gate']} is {gate['observed']}, below {gate['required']}; "
                "this needs a longer or steadier return series, not a new variant."
            )
        elif gate["gate"] == "beats_buy_and_hold":
            changes.append(
                f"Buy-and-hold returned {gate['required']}; the carry must exceed "
                "it to justify its operational complexity."
            )
    return changes


def _next_experiment(campaigns: list[CampaignResult]) -> dict[str, Any]:
    unmeasured = [c for c in campaigns if not c.ran]
    if unmeasured:
        return {
            "experiment_id": "V9-E1",
            "title": "Complete the blocked acquisition, then re-run H1-H3 unchanged",
            "rationale": (
                "H1-H3 were never measured. Registering new hypotheses before the "
                "registered ones have been tested would be starting a second "
                "search while the first is still open."
            ),
            "preconditions": [
                "outbound HTTPS to api.bybit.com and www.okx.com permitted by the "
                "egress policy, or an operator-supplied evidence pack imported and "
                "verified",
                "venue fee schedules captured from the venue, upgrading the cost "
                "stack from ASSUMPTION_UNVERIFIED to REAL",
            ],
            "frozen_parameters": (
                f"unchanged from the V8 pre-registration; freeze hash {freeze_hash()}"
            ),
            "falsifier": (
                "If 730 days of receipt-verified evidence on both venues yields no "
                "hypothesis clearing the gates, cash-and-carry on these venues is "
                "abandoned as a source of edge at this capital scale."
            ),
        }
    return {
        "experiment_id": "V9-E2",
        "title": "Execute the registered H6/H7 additional hypotheses",
        "rationale": (
            "H1-H3 were measured and rejected on their economics, which unlocks "
            "the two additional hypotheses registered in advance."
        ),
        "preconditions": ["H1-H3 measured and rejected", "cost evidence upgraded to REAL"],
        "frozen_parameters": f"H6/H7 as registered; freeze hash {freeze_hash()}",
        "falsifier": (
            "If H6 and H7 also fail after costs, the low-turnover directional "
            "family is abandoned for this universe."
        ),
    }


# --- board -------------------------------------------------------------------------


def _unified_board(campaigns: list[CampaignResult], mining: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for campaign in campaigns:
        venues = campaign.evidence.get("venues", {}) or {}
        first_venue: dict[str, Any] = next(iter(venues.values()), {})
        rows.append(
            {
                "opportunity_id": f"trading:{campaign.hypothesis_id}",
                "kind": "TRADING",
                "status": campaign.status,
                "measured": campaign.ran,
                "expected_return_over_horizon": campaign.economics.get("net_return"),
                "horizon_days": (first_venue.get("sufficiency", {}) or {}).get("span_days"),
                "capacity_notional_usd": campaign.capacity.get("capacity_notional_usd"),
                "allocation_weight": 0.0,
                "blocking_reasons": campaign.blocking_reasons[:3],
            }
        )
    rows.append(
        {
            "opportunity_id": "mining:nicehash",
            "kind": "MINING_MARKETPLACE",
            "status": mining.get("status"),
            "measured": bool(mining.get("quotes")),
            "expected_return_over_horizon": None,
            "horizon_days": None,
            "capacity_notional_usd": None,
            "allocation_weight": 0.0,
            "blocking_reasons": mining.get("errors", [])[:3],
        }
    )
    rows.append(
        {
            "opportunity_id": "cash",
            "kind": "CASH",
            "status": "AVAILABLE",
            "measured": True,
            "expected_return_over_horizon": 0.04,
            "horizon_days": 365.0,
            "capacity_notional_usd": None,
            "allocation_weight": 1.0,
            "blocking_reasons": [],
        }
    )
    promoted = [r for r in rows if r["status"] == STATUS_PAPER_CANDIDATE]
    return {
        "artifact": "UNIFIED_OPPORTUNITY_BOARD",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "rows": rows,
        "allocation": {
            "cash_weight": 1.0 if not promoted else 0.0,
            "non_cash_weight": 0.0 if not promoted else 1.0,
            "paper_only": True,
            "real_money_authorized": False,
        },
        "note": (
            "Cash holds the entire allocation whenever no opportunity has "
            "cleared its gates. An unmeasured opportunity receives zero weight; "
            "it is not treated as a small positive."
        ),
    }


# --- generation ---------------------------------------------------------------------


def generate_v8_artifacts(
    repo_root: str | Path = ".",
    *,
    evidence_root: str | Path | None = None,
    out_dir: str | Path | None = None,
    source_commit_sha: str | None = None,
    trial_registry_path: str | Path | None = None,
) -> GenerationResult:
    """Regenerate every V8 artifact deterministically."""
    root = Path(repo_root)
    evidence = Path(evidence_root) if evidence_root is not None else root / "data" / "v8_evidence"
    out = Path(out_dir) if out_dir is not None else root / "artifacts" / "v8"
    out.mkdir(parents=True, exist_ok=True)
    commit = source_commit_sha if source_commit_sha is not None else _source_commit(root)

    probe_path = out / NETWORK_PROBE_FILENAME
    probe = load_json(probe_path) if probe_path.exists() else {}
    probe = probe if isinstance(probe, dict) else {}

    campaigns = run_all_campaigns(evidence_root=evidence, trial_registry_path=trial_registry_path)
    # A recorded scan is an INPUT, kept under its own name. The generator
    # never reads its own output back: that would make the second regeneration
    # depend on the first, which is exactly the property being tested.
    recorded_scan = out / RECORDED_MINING_SCAN_FILENAME
    mining = load_json(recorded_scan) if recorded_scan.exists() else {}
    mining = mining if isinstance(mining, dict) else {}
    if not mining:
        mining = _blocked_mining_scan(probe)

    promoted = [c for c in campaigns if c.promoted]
    outcome = OUTCOME_PAPER_CANDIDATE if promoted else OUTCOME_NO_EDGE

    paper = not_started_report(
        reason=(
            "no hypothesis reached PAPER_CANDIDATE; "
            + "; ".join(f"{c.hypothesis_id}={c.status}" for c in campaigns)
        )
    ).to_dict()
    canary = evaluate_canary_readiness(
        evaluated_at_utc=EVALUATED_AT_UTC, paper_status=paper
    ).to_dict()

    payloads: dict[str, Any] = {
        "V8_PREREGISTRATION.json": preregistration().to_dict() | {"freeze_hash": freeze_hash()},
        "EVIDENCE_INDEX.json": _evidence_index(evidence, probe),
        "REAL_TRADING_CAMPAIGNS.json": _campaigns_artifact(campaigns),
        "TRADING_LEADERBOARD.json": _leaderboard(campaigns),
        "MINING_MARKETPLACE_SCAN.json": mining,
        "UNIFIED_OPPORTUNITY_BOARD.json": _unified_board(campaigns, mining),
        "PAPER_STATUS.json": paper,
        "CANARY_READINESS.json": canary,
        "NO_EDGE_DIAGNOSIS.json": _diagnosis(campaigns),
    }

    hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        atomic_write_json(out / name, payload)
        hashes[name] = sha256_of_file(out / name)

    manifest = {
        "artifact": "REGENERATION_MANIFEST",
        "schema_version": V8_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "base_sha": BASE_SHA,
        "source_commit_sha": commit,
        "preregistration_hash": freeze_hash(),
        "evidence_root": str(evidence),
        "outcome": outcome,
        "artifact_sha256": dict(sorted(hashes.items())),
        "regeneration_command": ("python -m quant_trade.v8.artifacts --source-commit-sha <sha>"),
        "determinism": (
            "Fixed evaluation clock, seeded bootstraps, no wall-clock reads, and "
            "the network probe read from its recorded artifact rather than "
            "re-run. Regenerating on the same evidence is byte-identical."
        ),
        "safety": {
            "orders_submitted": 0,
            "deposits": 0,
            "withdrawals": 0,
            "cloud_resources_created": 0,
            "miners_started": 0,
            "real_money_authorized": False,
        },
    }
    atomic_write_json(out / "REGENERATION_MANIFEST.json", manifest)
    hashes["REGENERATION_MANIFEST.json"] = sha256_of_file(out / "REGENERATION_MANIFEST.json")
    return GenerationResult(out_dir=str(out), hashes=hashes, outcome=outcome, campaigns=campaigns)


def _blocked_mining_scan(probe: dict[str, Any]) -> dict[str, Any]:
    from quant_trade.v8.hashrate_market import STATUS_BLOCKED_NETWORK, MarketplaceScan

    scan = MarketplaceScan(
        provider="nicehash",
        status=STATUS_BLOCKED_NETWORK,
        scanned_at_utc=EVALUATED_AT_UTC,
    )
    scan.blocked_hosts.append("api2.nicehash.com")
    scan.errors.append(
        "api2.nicehash.com: outbound HTTPS refused by the environment's egress "
        "policy (CONNECT answered 403), consistent with the venue probe"
    )
    scan.notes.append(
        "no marketplace prices were captured, so no hashrate opportunity was "
        "priced; DISCOVERY_ONLY would overstate what is known"
    )
    if probe.get("blocked_venues"):
        scan.notes.append(
            "the same egress policy blocks "
            + ", ".join(str(v) for v in probe.get("blocked_venues", []))
        )
    return scan.to_dict()


def artifact_fingerprint(hashes: dict[str, str]) -> str:
    return sha256_of_text(canonical_dumps(dict(sorted(hashes.items()))))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate the V8 artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--source-commit-sha", default=None)
    args = parser.parse_args(argv)
    result = generate_v8_artifacts(
        args.repo_root,
        evidence_root=args.evidence_root,
        out_dir=args.out_dir,
        source_commit_sha=args.source_commit_sha,
    )
    print(f"outcome: {result.outcome}")
    for name, digest in sorted(result.hashes.items()):
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_NAMES",
    "BASE_SHA",
    "EVALUATED_AT_UTC",
    "NETWORK_PROBE_FILENAME",
    "RECORDED_MINING_SCAN_FILENAME",
    "OUTCOME_NO_EDGE",
    "OUTCOME_PAPER_CANDIDATE",
    "GenerationResult",
    "artifact_fingerprint",
    "generate_v8_artifacts",
    "main",
]
