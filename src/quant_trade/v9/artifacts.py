"""Deterministic regeneration of every V9 artifact.

Determinism here means the same thing it meant in V8: a fixed evaluation
clock, seeded resampling, no wall-clock reads, and no artifact that reads
another artifact this generator produced. Regenerating twice on the same
inputs is byte-identical, and a test asserts it.

The honest shape of this run is worth stating up front, because a reader who
skims the JSON should not have to infer it. Outbound HTTPS to every
venue-published domain — three Bybit and three OKX — is refused at CONNECT by
the environment's egress policy. So no campaign has been measured, and the
trading state is ``NOT_MEASURED``. What *is* computable without price history
is computed and reported: the cost stack and the executable-capital floor.
Those are properties of venue rules, not of market history.

The mining route was retired after this sprint's artifacts were first emitted.
Its gates and errata remain part of the sealed V9 pre-registration — the
declaration is history and its hash does not move — but no mining artifact is
generated any more. See docs/MINING_RETIREMENT.md.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.v9 import V9_SCHEMA_VERSION
from quant_trade.v9.acquisition import evaluate_acquisition
from quant_trade.v9.canary import evaluate_canary_readiness_v9
from quant_trade.v9.candidate_bridge import STATUS_NO_CANDIDATE
from quant_trade.v9.cost_evidence import BundleSet, assumption_bundle
from quant_trade.v9.economic_status import guard_artifacts
from quant_trade.v9.margin import default_instrument_risk
from quant_trade.v9.preregistration import (
    PROMOTION_GATES,
    V8_ERRATA,
    freeze_hash,
    preregistration,
)
from quant_trade.v9.small_capital import DEFAULT_CAPITAL_LADDER, build_feasibility_curve
from quant_trade.v9.trial_ledger import GlobalTrialLedger

#: Fixed evaluation clock. Nothing in this module reads the wall clock.
EVALUATED_AT_UTC = "2026-07-28T20:00:00Z"

#: The merge commit V9 started from.
BASE_SHA = "3818c2d127a17ae26e86b3c75087d04f88681048"

#: Reference BTC price used only to express venue-rule arithmetic in USD. It
#: is an ASSUMPTION and every artifact that consumes it says so.
REFERENCE_BTC_USD = 60_000.0

#: The recorded network probe is an INPUT under its own name. The generator
#: never reads back a file it wrote, which is what keeps regeneration 2
#: independent of regeneration 1.
RECORDED_PROBE_FILENAME = "NETWORK_REACHABILITY_PROBE.recorded.json"

ARTIFACT_NAMES = (
    "DATA_AND_COST_EVIDENCE_INDEX.json",
    "GLOBAL_TRIAL_LEDGER_SUMMARY.json",
    "OOS_CAMPAIGN_RESULTS.json",
    "HOLDOUT_VERDICT.json",
    "SMALL_CAPITAL_FEASIBILITY.json",
    "H3_LEDGER_RECONCILIATION.json",
    "PAPER_DAEMON_STATUS.json",
    "PROFIT_CLAIM_GUARD.json",
    "CANARY_READINESS_V9.json",
    "BLOCKERS.json",
    "REGENERATION_MANIFEST.json",
)

STATE_NOT_MEASURED = "NOT_MEASURED"
STATE_BLOCKED = "BLOCKED_EVIDENCE"


@dataclass
class GenerationResult:
    out_dir: str
    hashes: dict[str, str] = field(default_factory=dict)
    trading_state: str = STATE_NOT_MEASURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "out_dir": self.out_dir,
            "trading_state": self.trading_state,
            "artifact_sha256": dict(sorted(self.hashes.items())),
        }


def _source_commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


# --- trading artifacts -------------------------------------------------------


def _evidence_index(
    evidence_root: Path, probe: dict[str, Any], bundles: BundleSet
) -> dict[str, Any]:
    status = evaluate_acquisition(
        evidence_root=evidence_root,
        since_utc="2024-07-28T00:00:00Z",
        until_utc="2026-07-28T00:00:00Z",
        min_days=PROMOTION_GATES["min_span_days"],
        min_settlements=PROMOTION_GATES["min_unique_settlements"],
    )
    payload = status.to_dict()
    payload["evaluated_at_utc"] = EVALUATED_AT_UTC
    payload["preregistration_hash"] = freeze_hash()
    payload["network_probe"] = {
        "attempted_at_utc": probe.get("attempted_at_utc"),
        "any_reachable": probe.get("any_reachable", False),
        "blocked_venues": probe.get("blocked_venues", []),
        "hosts": [
            {
                "venue": p.get("venue"),
                "host": p.get("host"),
                "outcome": p.get("outcome"),
                "error": p.get("error"),
            }
            for p in probe.get("probes", []) or []
        ],
        "policy": probe.get("policy", ""),
    }
    payload["cost_evidence"] = bundles.to_dict()
    payload["cost_evidence_promotable"] = bundles.promotable
    payload["note"] = (
        "Market data and cost evidence are indexed together because a campaign "
        "needs both and is blocked by whichever is missing. Here both are "
        "missing: egress is refused, and the only fee schedules available are "
        "ASSUMPTION-class retail defaults."
    )
    return payload


def _oos_campaign_results(bundles: BundleSet) -> dict[str, Any]:
    """What each hypothesis would be run through, and why none has been."""
    hypotheses = [
        {
            "hypothesis_id": "H1",
            "title": "cash-and-carry funding capture, BTC perp vs spot",
            "state": STATE_NOT_MEASURED,
            "measured": False,
            "reason": (
                "no settled funding series exists: every Bybit and OKX domain is "
                "refused at CONNECT by the environment's egress policy"
            ),
        },
        {
            "hypothesis_id": "H2",
            "title": "term-structure basis premium across horizons",
            "state": STATE_NOT_MEASURED,
            "measured": False,
            "reason": "no mark or index series exists for either venue",
        },
        {
            "hypothesis_id": "H3",
            "title": "cross-venue dispersion, Bybit against OKX",
            "state": STATE_NOT_MEASURED,
            "measured": False,
            "reason": (
                "requires both venues simultaneously; neither is reachable, and "
                "a single-venue substitute would not be the hypothesis"
            ),
        },
    ]
    return {
        "artifact": "OOS_CAMPAIGN_RESULTS",
        "schema_version": V9_SCHEMA_VERSION,
        # A register of what each hypothesis would be run through and why none
        # has been: declared intent, with each campaign's own NOT_MEASURED
        # state speaking for itself.
        "evidence_class": "DECLARED",
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "preregistration_hash": freeze_hash(),
        "campaigns": hypotheses,
        "states_permitted": [STATE_NOT_MEASURED, "MEASURED_REJECTED", "BACKTEST_CANDIDATE"],
        "split_scheme": {
            "train_fraction": 0.50,
            "walk_forward_fraction": 0.30,
            "holdout_fraction": 0.20,
            "selection_rule": (
                "each window selects on data ending at test_start - purge - "
                "embargo and is scored on its test block only"
            ),
        },
        "cost_evidence_class": bundles.to_dict().get("weakest_evidence_class"),
        "why_not_a_negative_result": (
            "NOT_MEASURED is not a negative finding. Nothing about these "
            "hypotheses has been tested, so a claim that no edge exists would "
            "assert a result that was never obtained. The distinction is kept "
            "in the vocabulary itself: the negative-result token is not a legal "
            "V9 state and appears in no artifact."
        ),
    }


def _holdout_verdict() -> dict[str, Any]:
    return {
        "artifact": "HOLDOUT_VERDICT",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "preregistration_hash": freeze_hash(),
        "state": STATE_NOT_MEASURED,
        "sealed": False,
        "revealed": False,
        "reveals_used": 0,
        "reason": (
            "there is no series to split, so no holdout has been sealed and none has been revealed"
        ),
        "contract": [
            "the holdout is the most recent 20% and is sealed by hash before any "
            "evaluation touches it",
            "it may be revealed exactly once, and the reveal is recorded",
            "a negative holdout rejects: full-sample performance never rescues it",
            "selection never reads it, in any window",
        ],
    }


def _h3_reconciliation() -> dict[str, Any]:
    return {
        "artifact": "H3_LEDGER_RECONCILIATION",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "state": STATE_NOT_MEASURED,
        "bars": 0,
        "flow_reconciliation_error": None,
        "liquidations": 0,
        "reason": "no two-venue series exists; both venues are blocked",
        "contract": [
            "each venue keeps its own book: cash, margin posted, position, and "
            "capital in transit between venues",
            "each bar's return is equity_t / equity_{t-1} - 1, derived from the "
            "books rather than summed from per-leg percentage moves",
            "every bar reconciles: opening equity + flows - costs = closing equity",
            "capacity is min(Bybit, OKX) and the binding venue is named",
            "a single liquidation blocks promotion outright",
        ],
        # Cross-reference to the V8 erratum this artifact answers. It is not a
        # closure verdict: nothing here re-runs V8 or checks that the defect is
        # gone, so the field names the erratum and stops there.
        "v8_erratum_addressed": "E6",
        "v8_erratum_closure_state": STATE_NOT_MEASURED,
    }


def _paper_daemon_status() -> dict[str, Any]:
    return {
        "artifact": "PAPER_DAEMON_STATUS",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "status": STATUS_NO_CANDIDATE,
        "state": STATE_NOT_MEASURED,
        "sessions": 0,
        "events_processed": 0,
        "wall_clock_seconds": 0.0,
        "clock_source": None,
        "reason": (
            "no campaign reached BACKTEST_CANDIDATE, because no campaign was "
            "measured; a session started here would produce an equity curve "
            "that means nothing"
        ),
        "commands": [
            "quant-trade v9 paper-start --state-dir <dir> --manifest <manifest.json>",
            "quant-trade v9 paper-run --state-dir <dir> --ticks <ticks.jsonl>",
            "quant-trade v9 paper-status --state-dir <dir>",
            "quant-trade v9 paper-resume --state-dir <dir>",
            "quant-trade v9 paper-stop --state-dir <dir>",
            "quant-trade v9 paper-report --state-dir <dir>",
        ],
        "guarantees": [
            "equity is derived from the position ledger; a caller cannot supply "
            "a return, a P&L or a cash yield",
            "runtime accumulates from timestamps persisted at each advance; an "
            "injected clock marks the session unpromotable forever",
            "the journal is appended before the checkpoint moves, so a crash "
            "between the two replays to the same state",
            "one writer at a time, enforced by a lease token",
        ],
        "live_order_submission": "DISABLED",
        "orders_submitted_live": 0,
    }


def _small_capital(bundles: BundleSet) -> dict[str, Any]:
    """Computable without price history: it is a property of venue rules."""
    risk = default_instrument_risk("bybit", "BTCUSDT")
    bybit = bundles.bundles.get("bybit")
    okx = bundles.bundles.get("okx")
    spot_bps = bybit.taker_bps("spot") if bybit else 10.0
    perp_bps = okx.taker_bps("perp") if okx else 5.5
    curve = build_feasibility_curve(
        risk=risk,
        price=REFERENCE_BTC_USD,
        spot_taker_bps=spot_bps,
        perp_taker_bps=perp_bps,
        ladder=DEFAULT_CAPITAL_LADDER,
        fee_floor_usd=0.10,
    )
    payload = curve.to_dict()
    # The whole curve is venue-rule arithmetic on an assumed reference price;
    # the strategy-level state below stays NOT_MEASURED, which is about the
    # missing return series, not about these inputs.
    payload["evidence_class"] = "ASSUMPTION"
    payload["evaluated_at_utc"] = EVALUATED_AT_UTC
    payload["preregistration_hash"] = freeze_hash()
    payload["reference_price_evidence_class"] = "ASSUMPTION"
    payload["cost_evidence_class"] = bundles.to_dict().get("weakest_evidence_class")
    payload["oos_distribution_available"] = False
    payload["state"] = STATE_NOT_MEASURED
    payload["what_is_and_is_not_measured"] = (
        "The executable-capital floor and the binding constraint at each rung "
        "are real: they follow from the venue's lot step, minimum notional, "
        "margin schedule and fee floors. The RETURN columns are absent, because "
        "there is no out-of-sample series to resample."
    )
    payload["v8_erratum_addressed"] = "E8"
    payload["v8_erratum_closure_state"] = STATE_NOT_MEASURED
    return payload


# --- cross-cutting artifacts -------------------------------------------------


def _blockers(probe: dict[str, Any], bundles: BundleSet) -> dict[str, Any]:
    hosts = [f"{p.get('host')} ({p.get('outcome')})" for p in (probe.get("probes", []) or [])]
    return {
        "artifact": "BLOCKERS",
        "schema_version": V9_SCHEMA_VERSION,
        # A curated register of what blocks the work: declared, with each
        # entry quoting its measured evidence verbatim.
        "evidence_class": "DECLARED",
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "blockers": [
            {
                "blocker_id": "B-EGRESS",
                "severity": "blocking",
                "summary": (
                    "outbound HTTPS to every venue-published domain is refused at "
                    "CONNECT by the environment's egress policy"
                ),
                "evidence": hosts,
                "consequence": "no market data, so every trading hypothesis is NOT_MEASURED",
                "owner": "environment operator",
                "resolution": (
                    "run the acquisition runbook in DATA_AND_COST_EVIDENCE_INDEX "
                    "on a host with egress and import the resulting pack, which "
                    "verifies byte-for-byte before extracting"
                ),
                "workarounds_refused": (
                    "proxies, VPN exits, mirrors and third-party redistributors "
                    "were not used; routing around an organisational restriction "
                    "is out of scope and would invalidate the provenance anyway"
                ),
            },
            {
                "blocker_id": "B-COST-EVIDENCE",
                "severity": "blocking",
                "summary": (
                    "the only fee schedules available are ASSUMPTION-class retail "
                    "defaults; no account-specific schedule has been captured"
                ),
                "evidence": [f"weakest class: {bundles.to_dict().get('weakest_evidence_class')}"],
                "consequence": "no campaign could promote even if data existed",
                "owner": "repository owner",
                "resolution": (
                    "capture your own fee schedule read-only and import it with "
                    "`quant-trade v9 cost-import`; the repository never sees the key"
                ),
            },
            {
                "blocker_id": "B-PAPER-DURATION",
                "severity": "blocking",
                "summary": (
                    "no paper session has run; a promotable session needs 72 real "
                    "hours and 500 events, which cannot be simulated forward"
                ),
                "evidence": ["sessions: 0"],
                "consequence": "canary readiness is unreachable",
                "owner": "repository owner",
                "resolution": "start a session once a candidate exists and let it run",
            },
        ],
        "note": (
            "Every blocker here is external to the code. None of them is "
            "resolvable by changing a threshold, and none has been worked around."
        ),
    }


def generate_v9_artifacts(
    repo_root: str | Path = ".",
    *,
    evidence_root: str | Path | None = None,
    out_dir: str | Path | None = None,
    source_commit_sha: str | None = None,
    trial_ledger_path: str | Path | None = None,
) -> GenerationResult:
    """Regenerate every V9 artifact deterministically."""
    root = Path(repo_root)
    evidence = Path(evidence_root) if evidence_root is not None else root / "data" / "v9_evidence"
    out = Path(out_dir) if out_dir is not None else root / "artifacts" / "v9"
    out.mkdir(parents=True, exist_ok=True)
    commit = source_commit_sha if source_commit_sha is not None else _source_commit(root)

    probe_path = out / RECORDED_PROBE_FILENAME
    probe = load_json(probe_path) if probe_path.exists() else {}
    probe = probe if isinstance(probe, dict) else {}

    bundles = BundleSet()
    for venue in ("bybit", "okx"):
        bundles.add(assumption_bundle(venue, captured_at_utc=EVALUATED_AT_UTC))

    ledger_path = (
        Path(trial_ledger_path) if trial_ledger_path is not None else evidence / "trials.jsonl"
    )
    ledger = GlobalTrialLedger(ledger_path)
    ledger_summary = ledger.summary()
    ledger_summary["evaluated_at_utc"] = EVALUATED_AT_UTC
    ledger_summary["state"] = STATE_NOT_MEASURED
    ledger_summary["v8_erratum_addressed"] = "E4"
    ledger_summary["v8_erratum_closure_state"] = STATE_NOT_MEASURED
    ledger_summary["deflation_note"] = (
        "The deflated Sharpe requires this ledger. With trial_registry=None or a "
        "zero cross-trial variance it degenerates into the probabilistic Sharpe, "
        "which is what V8 reported under the DSR label."
    )

    paper = _paper_daemon_status()
    canary = evaluate_canary_readiness_v9(
        evaluated_at_utc=EVALUATED_AT_UTC, paper_status=paper
    ).to_dict()
    # The evaluation genuinely ran over its stated inputs; the thresholds it
    # applied sit under "required", which is declaration-shaped by name.
    canary["evidence_class"] = "MEASURED"

    payloads: dict[str, Any] = {
        "DATA_AND_COST_EVIDENCE_INDEX.json": _evidence_index(evidence, probe, bundles),
        "GLOBAL_TRIAL_LEDGER_SUMMARY.json": ledger_summary,
        "OOS_CAMPAIGN_RESULTS.json": _oos_campaign_results(bundles),
        "HOLDOUT_VERDICT.json": _holdout_verdict(),
        "SMALL_CAPITAL_FEASIBILITY.json": _small_capital(bundles),
        "H3_LEDGER_RECONCILIATION.json": _h3_reconciliation(),
        "PAPER_DAEMON_STATUS.json": paper,
        "CANARY_READINESS_V9.json": canary,
        "BLOCKERS.json": _blockers(probe, bundles),
    }

    # The claim guard runs over everything else, then becomes an artifact
    # itself — it must not scan its own output, which would be circular.
    guard = guard_artifacts(payloads)
    # The guard scanned real payload bytes at generation time: its verdict is
    # a measurement of this artifact set, and says so.
    payloads["PROFIT_CLAIM_GUARD.json"] = {"evidence_class": "MEASURED", **guard.to_dict()}

    hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        atomic_write_json(out / name, payload)
        hashes[name] = sha256_of_file(out / name)

    manifest = {
        "artifact": "REGENERATION_MANIFEST",
        "schema_version": V9_SCHEMA_VERSION,
        # File hashes computed from bytes this run wrote; the embedded sealed
        # pre-registration is declaration-shaped by key and covers itself.
        "evidence_class": "MEASURED",
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "base_sha": BASE_SHA,
        "source_commit_sha": commit,
        "preregistration_hash": freeze_hash(),
        "preregistration": preregistration().to_dict(),
        "v8_errata_count": len(V8_ERRATA),
        "evidence_root": evidence.as_posix(),
        "trading_state": STATE_NOT_MEASURED,
        "artifact_sha256": dict(sorted(hashes.items())),
        "regeneration_command": "python -m quant_trade.v9.artifacts --source-commit-sha <sha>",
        "determinism": (
            "Fixed evaluation clock, seeded resampling, no wall-clock reads, and "
            "no artifact read back from this generator's own output. The network "
            "probe and any captured buy/info are INPUTS under .recorded.json "
            "names. Regenerating on the same inputs is byte-identical."
        ),
        "safety": {
            "live_order_submission": "DISABLED",
            "live_broker_execution": "DISABLED",
            "mining_purchase_execution": "DISABLED",
            "deposit_execution": "DISABLED",
            "withdrawal_execution": "DISABLED",
            "wallet_signing": "DISABLED",
            "aws_alibaba_hashing": "PROHIBITED",
            "cloud_resource_creation": "DISABLED",
            "external_spend": "DISABLED",
            "orders_submitted": 0,
            "hashrate_purchased": 0,
            "funds_moved_usd": 0.0,
            "cloud_resources_created": 0,
            "secrets_requested": 0,
            "secrets_stored": 0,
        },
    }
    atomic_write_json(out / "REGENERATION_MANIFEST.json", manifest)
    hashes["REGENERATION_MANIFEST.json"] = sha256_of_file(out / "REGENERATION_MANIFEST.json")
    return GenerationResult(
        out_dir=str(out),
        hashes=hashes,
        trading_state=STATE_NOT_MEASURED,
    )


def artifact_fingerprint(hashes: dict[str, str]) -> str:
    return sha256_of_text(canonical_dumps(dict(sorted(hashes.items()))))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate the V9 artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--source-commit-sha", default=None)
    args = parser.parse_args(argv)
    result = generate_v9_artifacts(
        args.repo_root,
        evidence_root=args.evidence_root,
        out_dir=args.out_dir,
        source_commit_sha=args.source_commit_sha,
    )
    print(f"trading: {result.trading_state}")
    for name, digest in sorted(result.hashes.items()):
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_NAMES",
    "BASE_SHA",
    "EVALUATED_AT_UTC",
    "RECORDED_PROBE_FILENAME",
    "REFERENCE_BTC_USD",
    "GenerationResult",
    "artifact_fingerprint",
    "generate_v9_artifacts",
    "main",
]
