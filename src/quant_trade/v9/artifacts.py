"""Deterministic regeneration of every V9 artifact.

Determinism here means the same thing it meant in V8: a fixed evaluation
clock, seeded resampling, no wall-clock reads, and no artifact that reads
another artifact this generator produced. Regenerating twice on the same
inputs is byte-identical, and a test asserts it.

The honest shape of this run is worth stating up front, because a reader who
skims the JSON should not have to infer it. Outbound HTTPS to every
venue-published domain — three Bybit, three OKX, the hashrate marketplace and
two pools — is refused at CONNECT by the environment's egress policy. So no
campaign has been measured, and the trading state is ``NOT_MEASURED``. What
*is* computable without price history is computed and reported: the cost
stack, the executable-capital floor, the unit conversions, and the full fee
arithmetic of a hashrate order. Those are properties of venue rules, not of
market history, and they are the durable output of a blocked sprint.
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
from quant_trade.v9.mining_cashflow import (
    B4_CORRECTIONS,
    DeliveryProfile,
    HashrateOrder,
    MarketplaceFees,
    NetworkState,
    PoolTerms,
    run_campaign,
)
from quant_trade.v9.mining_evidence import (
    STATUS_BLOCKED as MINING_BLOCKED,
)
from quant_trade.v9.mining_evidence import (
    evaluate_mining_evidence,
    mining_canary_manifest,
)
from quant_trade.v9.mining_shadow import (
    GAP_THRESHOLD_SECONDS,
    MIN_SHADOW_DAYS,
    MIN_SHADOW_SNAPSHOTS,
)
from quant_trade.v9.mining_units import (
    CANONICAL_SHA256_UNIT,
    SPEED_UNIT_HASHES,
    parse_buy_info,
)
from quant_trade.v9.preregistration import (
    MINING_GATES,
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
RECORDED_BUY_INFO_FILENAME = "NICEHASH_BUY_INFO.recorded.json"

ARTIFACT_NAMES = (
    "DATA_AND_COST_EVIDENCE_INDEX.json",
    "GLOBAL_TRIAL_LEDGER_SUMMARY.json",
    "OOS_CAMPAIGN_RESULTS.json",
    "HOLDOUT_VERDICT.json",
    "SMALL_CAPITAL_FEASIBILITY.json",
    "H3_LEDGER_RECONCILIATION.json",
    "PAPER_DAEMON_STATUS.json",
    "MINING_EVIDENCE_INDEX.json",
    "UNIT_CONVERSION_AUDIT.json",
    "MINING_CASHFLOW.json",
    "MINING_SHADOW_STATUS.json",
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
    mining_state: str = MINING_BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "out_dir": self.out_dir,
            "trading_state": self.trading_state,
            "mining_state": self.mining_state,
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


# --- mining artifacts --------------------------------------------------------


def _unit_conversion_audit(spec: Any) -> dict[str, Any]:
    """The dimensional arithmetic, worked, so a reader can check it by hand."""
    worked: list[dict[str, Any]] = []
    for quoted_unit in ("PH", "TH", "GH"):
        multiplier = SPEED_UNIT_HASHES[quoted_unit] / SPEED_UNIT_HASHES[CANONICAL_SHA256_UNIT]
        worked.append(
            {
                "quoted_unit": f"{quoted_unit}/s",
                "canonical_unit": f"{CANONICAL_SHA256_UNIT}/s",
                "hashes_per_quoted_unit": SPEED_UNIT_HASHES[quoted_unit],
                "canonical_units_per_quoted_unit": multiplier,
                "example_quote_btc_per_unit_day": 0.001,
                "naive_usd_per_canonical_unit_day": 0.001 * REFERENCE_BTC_USD,
                "correct_usd_per_canonical_unit_day": 0.001 * REFERENCE_BTC_USD / multiplier,
                "error_factor_if_skipped": multiplier,
            }
        )
    payload: dict[str, Any] = {
        "artifact": "UNIT_CONVERSION_AUDIT",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "speed_unit_hashes": dict(sorted(SPEED_UNIT_HASHES.items())),
        "canonical_unit": CANONICAL_SHA256_UNIT,
        "worked_examples": worked,
        "btc_usd_reference": REFERENCE_BTC_USD,
        "btc_usd_evidence_class": "ASSUMPTION",
        "v8_erratum_addressed": "E9",
        "v8_erratum_closure_state": STATE_NOT_MEASURED,
        "note": (
            "SHA-256 is quoted in PH/s. Skipping the conversion overstates the "
            "cost of hashrate by exactly 1,000x, which is large enough to turn "
            "any rental into an obvious loss or an obvious win depending on the "
            "direction of the mistake."
        ),
    }
    if spec is not None:
        payload["observed_market_spec"] = spec.to_dict()
    else:
        payload["observed_market_spec"] = None
        payload["observed_market_spec_reason"] = (
            "public/buy/info was not captured: the marketplace host is refused "
            "at CONNECT, so no live speed unit is on record"
        )
    return payload


def _mining_cashflow_demo() -> dict[str, Any]:
    """The fee arithmetic on a RECORDED_TEST order, labelled as such.

    This is not a result. It exists so the sixteen corrections are visible as
    numbers rather than as prose, on inputs that are explicitly synthetic.
    """
    from quant_trade.v9.mining_units import MarketSpec

    spec = MarketSpec(
        algorithm="SHA256",
        market="EU",
        speed_text="PH",
        min_order_amount_btc=0.001,
        min_speed_limit=0.1,
        max_speed_limit=1000.0,
        min_price_btc=0.0001,
        max_price_btc=10.0,
        enabled=True,
        down_step=-0.0001,
        raw_sha256="",
        captured_at_utc=EVALUATED_AT_UTC,
        evidence_class="SYNTHETIC",
        source_url="synthetic fixture; no marketplace was contacted",
    )
    fees = MarketplaceFees(
        order_creation_fee_btc=0.00001,
        buyer_fee_rate_on_spend=0.03,
        deposit_fee_btc=0.00002,
        withdrawal_fee_btc=0.00003,
        cancellation_fee_btc=0.00001,
    )
    pool = PoolTerms(
        pool_name="synthetic-pool",
        payout_scheme="FPPS",
        pool_fee_rate=0.02,
        minimum_payout_btc=0.0005,
        payout_evidence_class="SYNTHETIC",
    )
    network = NetworkState(
        network="bitcoin-mainnet",
        difficulty=1.1e14,
        block_reward_btc=3.125,
        difficulty_drift_per_day=0.0015,
    )
    order = HashrateOrder(
        spec=spec,
        price_btc_per_speed_unit_day=0.001,
        amount_btc=0.01,
        speed_limit=1.0,
        duration_hours=24.0,
    )
    ledger, outcomes = run_campaign(
        [(order, DeliveryProfile(fill_ratio_at_price=0.85))],
        deposit_btc=0.05,
        fees=fees,
        pool=pool,
        network=network,
        btc_usd=REFERENCE_BTC_USD,
    )
    summary = ledger.summary(horizon_days=1.0)
    return {
        "artifact": "MINING_CASHFLOW",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "state": STATE_NOT_MEASURED,
        "evidence_class": "SYNTHETIC",
        "inputs_are_synthetic": True,
        "corrections_applied": list(B4_CORRECTIONS),
        "fees": fees.to_dict(),
        "pool": pool.to_dict(),
        "order": order.to_dict(),
        "outcome": outcomes[0].to_dict(),
        "ledger": summary,
        "interpretation": (
            "These numbers demonstrate the fee arithmetic on synthetic inputs. "
            "They say nothing about whether renting hashrate is worthwhile: the "
            "difficulty, the price, the delivery ratio and the pool terms were "
            "all chosen, not observed."
        ),
    }


def _mining_evidence_index(probe: dict[str, Any], spec: Any) -> dict[str, Any]:
    gate = evaluate_mining_evidence(
        market_quotes=0 if spec is None else 1,
        market_blocked=spec is None,
        pool=None,
    )
    # No budget can be derived while the marketplace is unreadable. This call
    # site used to invoke derive_canary_budget() with six invented fee
    # literals and publish the result as terms derived from the venue's own
    # minimum order amount and fees - inside the same artifact that reports
    # market_quotes 0 and "no quote exists to price anything from". The venue
    # has supplied nothing, so the budget stays absent rather than imagined.
    budget = None
    manifest = mining_canary_manifest(
        gate,
        budget=budget,
        max_loss_btc=None,
        # Operator-chosen safety ceilings, not venue terms: they cap what a
        # first purchase could ever be, and are assumptions until a real
        # quote exists to check them against.
        price_ceiling_btc=0.001,
        speed_limit=1.0,
        max_duration_hours=24.0,
        pool_name="<operator's own pool account>",
        worker="<operator's own worker>",
        btc_usd_reference=REFERENCE_BTC_USD,
        notes=[
            "No budget is stated. Deriving one needs the venue's minimum order "
            "amount, its fees and the pool's payout minimum, none of which has "
            "been read. The ceilings below are operator-chosen limits, class "
            "ASSUMPTION; they bound a purchase, they do not price one.",
        ],
    )
    payload = gate.to_dict()
    payload.update(
        {
            "artifact": "MINING_EVIDENCE_INDEX",
            "schema_version": V9_SCHEMA_VERSION,
            "evaluated_at_utc": EVALUATED_AT_UTC,
            "marketplace_blocked": spec is None,
            "pool_adapter_attached": False,
            "pool_payout_records": 0,
            "gates": dict(sorted(MINING_GATES.items())),
            "canary_manifest": manifest,
            # This artifact mixes a measured blocking result with unmeasured
            # ceilings; say so rather than letting the reader assume one class.
            "canary_manifest_evidence_class": "ASSUMPTION",
            "blocked_hosts": [
                {"host": p.get("host"), "outcome": p.get("outcome"), "error": p.get("error")}
                for p in probe.get("probes", []) or []
            ],
            "note": (
                "Marketplace prices are a quote; pool payouts are the product. "
                "Without the second, the route cannot exceed SHADOW_MARKET_ONLY "
                "however attractive the arithmetic looks."
            ),
        }
    )
    return payload


def _mining_shadow_status() -> dict[str, Any]:
    return {
        "artifact": "MINING_SHADOW_STATUS",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "status": MINING_BLOCKED,
        "collector_running": False,
        "snapshots": 0,
        "observed_days": 0.0,
        "gaps": 0,
        "thresholds": {
            "min_shadow_days": MIN_SHADOW_DAYS,
            "min_shadow_snapshots": MIN_SHADOW_SNAPSHOTS,
            "gap_threshold_seconds": GAP_THRESHOLD_SECONDS,
        },
        "blocking_reasons": [
            "the marketplace host is refused at CONNECT, so no snapshot can be "
            "captured and the window has not opened",
        ],
        "anti_forgery": [
            "elapsed days accumulate from persisted wall-clock stamps, so a "
            "replay advances the snapshot count and not the window",
            "the journal is hash-chained: an edited or removed record is detectable",
            "downtime is recorded as a gap and excluded from observed time",
            "the bidding policy is frozen at start; changing it restarts the window",
            "an injected clock marks the window unpromotable forever",
        ],
        "orders_placed": 0,
        "btc_spent": 0.0,
        "purchase_authorized": False,
    }


# --- cross-cutting artifacts -------------------------------------------------


def _blockers(probe: dict[str, Any], bundles: BundleSet) -> dict[str, Any]:
    hosts = [f"{p.get('host')} ({p.get('outcome')})" for p in (probe.get("probes", []) or [])]
    return {
        "artifact": "BLOCKERS",
        "schema_version": V9_SCHEMA_VERSION,
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
                "blocker_id": "B-POOL-EVIDENCE",
                "severity": "blocking",
                "summary": "no pool payout record exists, so delivery and payment are unobserved",
                "evidence": ["pool hosts refused at CONNECT"],
                "consequence": "the mining route is capped at SHADOW_MARKET_ONLY",
                "owner": "repository owner",
                "resolution": "attach a read-only pool adapter on a host with egress",
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

    buy_info_path = out / RECORDED_BUY_INFO_FILENAME
    spec = None
    if buy_info_path.exists():
        spec = parse_buy_info(
            buy_info_path.read_bytes(),
            algorithm="SHA256",
            market="EU",
            captured_at_utc=EVALUATED_AT_UTC,
            evidence_class="RECORDED_TEST",
            source_url="https://api2.nicehash.com/main/api/v2/public/buy/info",
        )

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

    payloads: dict[str, Any] = {
        "DATA_AND_COST_EVIDENCE_INDEX.json": _evidence_index(evidence, probe, bundles),
        "GLOBAL_TRIAL_LEDGER_SUMMARY.json": ledger_summary,
        "OOS_CAMPAIGN_RESULTS.json": _oos_campaign_results(bundles),
        "HOLDOUT_VERDICT.json": _holdout_verdict(),
        "SMALL_CAPITAL_FEASIBILITY.json": _small_capital(bundles),
        "H3_LEDGER_RECONCILIATION.json": _h3_reconciliation(),
        "PAPER_DAEMON_STATUS.json": paper,
        "MINING_EVIDENCE_INDEX.json": _mining_evidence_index(probe, spec),
        "UNIT_CONVERSION_AUDIT.json": _unit_conversion_audit(spec),
        "MINING_CASHFLOW.json": _mining_cashflow_demo(),
        "MINING_SHADOW_STATUS.json": _mining_shadow_status(),
        "CANARY_READINESS_V9.json": canary,
        "BLOCKERS.json": _blockers(probe, bundles),
    }

    # The claim guard runs over everything else, then becomes an artifact
    # itself — it must not scan its own output, which would be circular.
    guard = guard_artifacts(payloads)
    payloads["PROFIT_CLAIM_GUARD.json"] = guard.to_dict()

    hashes: dict[str, str] = {}
    for name, payload in payloads.items():
        atomic_write_json(out / name, payload)
        hashes[name] = sha256_of_file(out / name)

    manifest = {
        "artifact": "REGENERATION_MANIFEST",
        "schema_version": V9_SCHEMA_VERSION,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "base_sha": BASE_SHA,
        "source_commit_sha": commit,
        "preregistration_hash": freeze_hash(),
        "preregistration": preregistration().to_dict(),
        "v8_errata_count": len(V8_ERRATA),
        "evidence_root": str(evidence),
        "trading_state": STATE_NOT_MEASURED,
        "mining_state": MINING_BLOCKED,
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
        mining_state=MINING_BLOCKED,
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
    print(f"trading: {result.trading_state}  mining: {result.mining_state}")
    for name, digest in sorted(result.hashes.items()):
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_NAMES",
    "BASE_SHA",
    "EVALUATED_AT_UTC",
    "RECORDED_BUY_INFO_FILENAME",
    "RECORDED_PROBE_FILENAME",
    "REFERENCE_BTC_USD",
    "GenerationResult",
    "artifact_fingerprint",
    "generate_v9_artifacts",
    "main",
]
