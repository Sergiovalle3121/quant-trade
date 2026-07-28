"""Frozen V9 pre-registration, and the errata against V8's reported numbers.

Two things are fixed here before anything runs. The first is the usual
pre-registration content: gates, splits, cost treatment, falsifiers. The
second is new and matters more — a written record of which V8 numbers were
wrong and why, so that "V9 reports a different figure" is a correction with a
cause rather than a quiet revision.

The gates below are *stricter* than V8's in three places and looser in none.
Every V9 gate that V8 also had keeps V8's threshold; the additions close holes
that V8's own artifacts walked through.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

REGISTERED_AT_UTC = "2026-07-28T14:00:00Z"
REGISTERED_AT_COMMIT = "3818c2d127a17ae26e86b3c75087d04f88681048"

#: V8's gates, kept, plus the ones its own defects showed were missing.
PROMOTION_GATES: dict[str, Any] = {
    # --- inherited from V8, unchanged ---
    "min_span_days": 730.0,
    "min_unique_settlements": 1000,
    "min_walk_forward_windows": 5,
    "min_probabilistic_sharpe": 0.95,
    "min_deflated_sharpe": 0.95,
    "max_cscv_pbo": 0.50,
    "require_bootstrap_p05_positive": True,
    "require_positive_at_2x_costs": True,
    "report_3x_costs": True,
    "require_zero_liquidations": True,
    "require_reconciled_ledger": True,
    "require_majority_positive_walk_forward": True,
    "require_beats_cash": True,
    "require_beats_buy_and_hold": True,
    "require_untouched_holdout": True,
    "require_real_provenance": True,
    "require_promotable_cost_evidence": True,
    # --- added in V9, each closing a hole V8's artifacts went through ---
    "require_positive_holdout": True,
    "require_per_window_oos_selection": True,
    "require_hash_chained_trial_ledger": True,
    "require_nonzero_cross_trial_sharpe_variance": True,
    "require_per_venue_cost_bundles": True,
    "require_equity_derived_returns": True,
    "require_observed_at_timestamps": True,
    "require_executable_at_capital": True,
    "forbid_caller_supplied_pnl": True,
    "forbid_injected_wall_clock": True,
}

#: Chronological split. Unchanged from V8 in shape; V9 fixes how it is *used*.
DATA_SPLITS: dict[str, Any] = {
    "scheme": "chronological",
    "train_fraction": 0.50,
    "walk_forward_fraction": 0.30,
    "holdout_fraction": 0.20,
    "holdout_position": "most_recent",
    "walk_forward": {
        "train_size": 720,
        "test_size": 240,
        "step_size": 240,
        "purge_bars": 6,
        "embargo_bars": 1,
    },
    "selection_rule": (
        "each window selects on data ending at test_start - purge - embargo and "
        "is scored on the test block only; the holdout is sealed before any "
        "evaluation and revealed once"
    ),
}

#: Mining thresholds, fixed before any shadow window opens so that a window
#: cannot be declared long enough after the fact.
MINING_GATES: dict[str, Any] = {
    "min_shadow_days": 14.0,
    "min_shadow_snapshots": 2000,
    "require_pool_payout_evidence": True,
    "require_quote_economics_agreement": True,
    "max_evidence_age_seconds": 21600.0,
    "require_beats_holding_btc": True,
    "require_beats_holding_cash": True,
    "require_payout_above_minimum": True,
    "forbid_assumption_class_inputs": True,
    "forbid_injected_wall_clock": True,
}


@dataclass(frozen=True)
class Erratum:
    """One V8 number that was wrong, what it should have been, and why."""

    erratum_id: str
    artifact: str
    v8_claim: str
    defect: str
    correction: str
    magnitude: str
    v9_module: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: The V8 corrections. Each has a regression test; none is a matter of taste.
V8_ERRATA: tuple[Erratum, ...] = (
    Erratum(
        erratum_id="E1",
        artifact="CANARY_READINESS.json",
        v8_claim="READY_PENDING_HUMAN_AUTHORISATION",
        defect=(
            "the gate failed open: a missing value counted as satisfied, a bool "
            "passed the numeric check, and the three loss limits were never "
            "compared to each other, so reconciled=false with an engaged kill "
            "switch and limits of {-1, 0, 'bad'} still returned ready"
        ),
        correction=(
            "every limit must be present, numeric, positive and ordered "
            "per_trade <= daily <= total; reconciliation must be exactly True; "
            "an engaged kill switch disqualifies"
        ),
        magnitude="a readiness verdict that was structurally unreachable became reachable",
        v9_module="quant_trade.v9.canary",
    ),
    Erratum(
        erratum_id="E2",
        artifact="PAPER_STATUS.json",
        v8_claim="paper fills and equity as reported",
        defect=(
            "a paper_fill could be booked with no matching paper_order, and the "
            "caller supplied the resulting return directly"
        ),
        correction=(
            "a fill must resolve to a live order; equity is derived from the "
            "position ledger and cannot be passed in"
        ),
        magnitude="paper P&L was an input, not a measurement",
        v9_module="quant_trade.v9.paper_engine",
    ),
    Erratum(
        erratum_id="E3",
        artifact="revenue-run output",
        v8_claim="PAPER_STATUS=NOT_STARTED_NO_CANDIDATE with H1 a candidate",
        defect="a candidate that existed was reported as absent",
        correction="CANDIDATE_READY_PAPER_NOT_STARTED",
        magnitude="the difference between 'nothing qualified' and 'we have not started'",
        v9_module="quant_trade.v9.candidate_bridge",
    ),
    Erratum(
        erratum_id="E4",
        artifact="TRADING_LEADERBOARD.json",
        v8_claim="deflated Sharpe reported alongside PSR",
        defect=(
            "the deflated Sharpe was computed with sharpe_variance=0 and a trial "
            "count of one, which makes the deflation term vanish; the reported "
            "DSR was the PSR under another name"
        ),
        correction=(
            "DSR takes the real cross-trial Sharpe variance and trial count from "
            "a mandatory hash-chained ledger; a null or empty ledger raises"
        ),
        magnitude=(
            "at a fixed candidate Sharpe: DSR 0.9996 at 1 trial, 0.7527 at 5, "
            "0.1867 at 20, 0.0110 at 100 — V8 always reported the 1-trial figure"
        ),
        v9_module="quant_trade.v9.trial_ledger",
    ),
    Erratum(
        erratum_id="E5",
        artifact="REAL_TRADING_CAMPAIGNS.json",
        v8_claim="walk-forward out-of-sample results",
        defect=(
            "variant selection ran on the full sample, then reported performance "
            "on windows drawn from that same sample; the OOS series had been "
            "seen at selection time"
        ),
        correction=(
            "each window selects on strictly prior data ending at "
            "test_start - purge - embargo and is scored on the test block only"
        ),
        magnitude="the previously reported OOS series was in-sample",
        v9_module="quant_trade.v9.oos",
    ),
    Erratum(
        erratum_id="E6",
        artifact="REAL_TRADING_CAMPAIGNS.json (H3)",
        v8_claim="dispersion returns as the sum of per-leg percentage moves",
        defect=(
            "summing leg returns assumes both legs are the same size and that "
            "margin and in-transit capital are free"
        ),
        correction=(
            "a per-venue book with cash, margin posted, positions and capital in "
            "transit; each bar's return is equity_t/equity_{t-1} - 1 with a flow "
            "reconciliation that must balance, and capacity is min(Bybit, OKX)"
        ),
        magnitude="returns and capacity were both overstated by an unquantified amount",
        v9_module="quant_trade.v9.h3_ledger",
    ),
    Erratum(
        erratum_id="E7",
        artifact="COST_MODEL / campaign inputs",
        v8_claim="fee constants applied per venue",
        defect=(
            "costs were literals with no provenance, no expiry and no venue "
            "binding, so one venue's schedule could be applied to another"
        ),
        correction=(
            "CostEvidenceBundle carries raw bytes, sha256, effective window and "
            "an evidence class; a REAL class without bytes is rejected and two "
            "venues sharing one bundle is detected"
        ),
        magnitude="cost inputs were unfalsifiable",
        v9_module="quant_trade.v9.cost_evidence",
    ),
    Erratum(
        erratum_id="E8",
        artifact="CAPITAL / paper launch",
        v8_claim="$166,667 minimum capital",
        defect=(
            "that figure was the capital a $100k reference position happened to "
            "immobilise, presented as a floor"
        ),
        correction=(
            "a feasibility curve from $100 to $10,000 that finds the largest "
            "position each balance can actually place, or returns "
            "INSUFFICIENT_EXECUTABLE_CAPITAL and names the binding constraint"
        ),
        magnitude=(
            "the executable floor under the modelled venue rules is $75, not "
            "$166,667 — three orders of magnitude. Below it the 0.001 BTC lot "
            "step binds, not capital. At $75-$100 a $0.10 per-fill floor raises "
            "break-even funding to 0.0000741 per 8h against 0.0000489 at every "
            "larger rung: a 52% penalty invisible in a bps-only cost model"
        ),
        v9_module="quant_trade.v9.small_capital",
    ),
    Erratum(
        erratum_id="E9",
        artifact="MINING_MARKETPLACE_SCAN.json",
        v8_claim="hashrate priced as units x price x days in USD",
        defect=(
            "SHA-256 is quoted in BTC per PH/s per day; converting without the "
            "unit multiplier misprices hashrate by 1,000x, min/max speed limit "
            "was read as available supply, and a bid was assumed to fill"
        ),
        correction=(
            "public/buy/info is the unit authority, the limit is documented as a "
            "request rather than supply, and the fill ratio comes from the bid's "
            "position in the order book"
        ),
        magnitude="a factor of 1,000 on the cost of hashrate",
        v9_module="quant_trade.v9.mining_units",
    ),
    Erratum(
        erratum_id="E10",
        artifact="MINING_CASHFLOW",
        v8_claim="a USD purchase with a single buyer fee",
        defect=(
            "spend did not follow delivery, the buyer fee was applied to "
            "deposited rather than spent funds, the fixed order fee and deposit "
            "fee were absent, unspent budget was consumed rather than refunded, "
            "balances reset per order, and the ledger was USD"
        ),
        correction=(
            "sixteen corrections listed in mining_cashflow.B4_CORRECTIONS, each "
            "with its own test; the ledger is BTC with USD as a parallel view"
        ),
        magnitude="every fee and the currency of the whole calculation",
        v9_module="quant_trade.v9.mining_cashflow",
    ),
    Erratum(
        erratum_id="E11",
        artifact="all campaign artifacts",
        v8_claim="NO_EDGE_FOUND",
        defect=(
            "no campaign was ever measured — egress to every venue was refused — "
            "so 'no edge' asserted a result that had not been obtained"
        ),
        correction="NOT_MEASURED, with an operator runbook and a verifying import path",
        magnitude="a claim about the market replaced by a claim about the data",
        v9_module="quant_trade.v9.acquisition",
    ),
)


@dataclass(frozen=True)
class FalsifierSpec:
    """What would make a hypothesis wrong, written before it is tested."""

    hypothesis_id: str
    falsifiers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "falsifiers": list(self.falsifiers)}


FALSIFIERS: tuple[FalsifierSpec, ...] = (
    FalsifierSpec(
        hypothesis_id="H1",
        falsifiers=(
            "realised funding net of the full cost stack is below break-even in "
            "the majority of walk-forward windows",
            "the holdout return is negative",
            "any window liquidates",
            "the edge does not survive 2x costs",
        ),
    ),
    FalsifierSpec(
        hypothesis_id="H2",
        falsifiers=(
            "the basis premium does not exceed the round-trip cost at any horizon",
            "the holdout return is negative",
            "capacity at the minimum venue is below the executable minimum",
        ),
    ),
    FalsifierSpec(
        hypothesis_id="H3",
        falsifiers=(
            "equity-derived returns are negative once both venues' fees and margin are charged",
            "min(Bybit, OKX) capacity cannot support the minimum executable size",
            "the flow reconciliation does not balance",
        ),
    ),
    FalsifierSpec(
        hypothesis_id="MINING",
        falsifiers=(
            "no pool payout record shows coins received for accepted hashrate",
            "the realised payout rate is below the modelled rate",
            "the campaign does not beat holding BTC",
            "the campaign does not beat holding cash",
        ),
    ),
)

#: Cost treatment, fixed so that a campaign cannot quietly drop a component.
COST_TREATMENT: dict[str, Any] = {
    "multipliers": [1.0, 2.0, 3.0],
    "per_leg_attribution": True,
    "fills_per_round_trip": {"two_leg": 4, "single_leg": 2},
    "components": [
        "spot taker fee",
        "perp taker fee",
        "spread cost",
        "slippage",
        "borrow or margin funding",
        "transfer and withdrawal frictions",
    ],
    "fee_floor_applied_per_fill": True,
    "note": (
        "V8 charged the sum of all per-fill frictions four times, applying the "
        "spot fee to perp fills; the leg field fixes the attribution."
    ),
}


@dataclass(frozen=True)
class V9Preregistration:
    registered_at_utc: str = REGISTERED_AT_UTC
    registered_at_commit: str = REGISTERED_AT_COMMIT
    promotion_gates: dict[str, Any] = field(default_factory=lambda: dict(PROMOTION_GATES))
    mining_gates: dict[str, Any] = field(default_factory=lambda: dict(MINING_GATES))
    data_splits: dict[str, Any] = field(default_factory=lambda: dict(DATA_SPLITS))
    cost_treatment: dict[str, Any] = field(default_factory=lambda: dict(COST_TREATMENT))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "V9_PREREGISTRATION",
            "schema_version": 1,
            "registered_at_utc": self.registered_at_utc,
            "registered_at_commit": self.registered_at_commit,
            "promotion_gates": dict(sorted(self.promotion_gates.items())),
            "mining_gates": dict(sorted(self.mining_gates.items())),
            "data_splits": self.data_splits,
            "cost_treatment": self.cost_treatment,
            "falsifiers": [f.to_dict() for f in FALSIFIERS],
            "v8_errata": [e.to_dict() for e in V8_ERRATA],
            "gates_relaxed_from_v8": [],
            "note": (
                "No V8 gate was relaxed. Ten were added, each closing a hole a "
                "V8 artifact went through."
            ),
        }


def preregistration() -> V9Preregistration:
    return V9Preregistration()


def freeze_hash() -> str:
    """The hash that travels with every V9 artifact."""
    return sha256_of_text(canonical_dumps(preregistration().to_dict()))


__all__ = [
    "COST_TREATMENT",
    "DATA_SPLITS",
    "FALSIFIERS",
    "MINING_GATES",
    "PROMOTION_GATES",
    "REGISTERED_AT_COMMIT",
    "REGISTERED_AT_UTC",
    "V8_ERRATA",
    "Erratum",
    "FalsifierSpec",
    "V9Preregistration",
    "freeze_hash",
    "preregistration",
]
