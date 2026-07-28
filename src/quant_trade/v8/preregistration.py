"""Frozen V8 pre-registration: what will be tested, decided before testing.

The point of pre-registration is to make one specific fraud impossible — the
one where a researcher runs many variants, keeps the flattering one, and
presents it as though it had been the plan. So the universe, periodicity,
signal, variant list, cost treatment, data splits, falsifiers and promotion
gates are all fixed *here*, in code, and hashed. The hash goes into every
artifact a campaign produces. If a parameter moves after results are seen, the
hash moves with it, and the change is visible in the diff and in the artifact.

The gates are the V7 gates, unchanged. Lowering a threshold to manufacture a
winner is the failure mode this whole repository exists to prevent, so the
values below are duplicated deliberately rather than read from a config a
campaign could override.

H1–H3 are the primary hypotheses and run first. H6 and H7 are registered but
**may only execute after H1–H3 have completed**, and together may contribute
at most :data:`MAX_ADDITIONAL_VARIANTS` variants — a cap that exists so a
rejected primary hypothesis cannot quietly turn into an unbounded search.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

REGISTERED_AT_UTC = "2026-07-28T06:30:00Z"
REGISTERED_AT_COMMIT = "596c2accd5c535f3c537a4439a96b94e521e4018"

#: Hard ceiling on additional (H6/H7) variants, counted together.
MAX_ADDITIONAL_VARIANTS = 8

#: The promotion gates. Fixed at registration; a campaign may read them and
#: may never relax them.
PROMOTION_GATES: dict[str, Any] = {
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
}

#: Chronological split. The holdout is the most recent slice and is never read
#: during tuning — a campaign that touches it outside final scoring fails.
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
}


@dataclass(frozen=True)
class Variant:
    """One pre-registered parameter combination."""

    variant_id: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HypothesisSpec:
    hypothesis_id: str
    title: str
    thesis: str
    priority: str  # "PRIMARY" | "ADDITIONAL"
    venues: tuple[str, ...]
    instruments: tuple[str, ...]
    periodicity: str
    signal: str
    variants: tuple[Variant, ...]
    cost_treatment: str
    falsifiers: tuple[str, ...]
    benchmarks: tuple[str, ...]
    capacity_notes: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["variants"] = [v.to_dict() for v in self.variants]
        payload["variant_count"] = len(self.variants)
        return payload


def _carry_variants(prefix: str) -> tuple[Variant, ...]:
    """Four combinations, exactly as registered in V6/V7. No grid search."""
    return tuple(
        Variant(
            variant_id=f"{prefix}-t{int(threshold * 1e5)}-w{window}",
            parameters={"entry_threshold": threshold, "trailing_window": window},
        )
        for threshold in (0.00005, 0.0001)
        for window in (3, 6)
    )


H1 = HypothesisSpec(
    hypothesis_id="H1",
    title="Bybit BTC spot/perp cash-and-carry",
    thesis=(
        "Long BTCUSDT spot, short BTCUSDT linear perpetual on Bybit, held "
        "delta-neutral, earns positive net carry from settled funding after "
        "the full cost stack."
    ),
    priority="PRIMARY",
    venues=("bybit",),
    instruments=("bybit:BTC-USDT:spot", "bybit:BTC-USDT:linear-perp"),
    periodicity="1h bars; funding accrues only at settlement instants",
    signal=(
        "Trailing mean of the SETTLED funding series, held constant between "
        "settlements. Enter when it exceeds entry_threshold, else hold flat. "
        "Announced/predicted rates carry no entry authority."
    ),
    variants=_carry_variants("H1"),
    cost_treatment="conservative_cost_stack('bybit'); 1x/2x/3x reported",
    falsifiers=(
        "net marked-equity return <= 0 over the campaign",
        "net return <= 0 at 2x costs",
        "bootstrap P05 of total return <= 0",
        "a majority of walk-forward windows negative",
        "any liquidation or maintenance-margin breach along the path",
        "does not beat holding cash",
        "does not beat buy-and-hold BTC",
    ),
    benchmarks=("cash", "buy_and_hold_btc"),
    capacity_notes=(
        "Sized against observed bar volume; capacity is the notional that "
        "keeps modelled impact within the priced allowance."
    ),
)

H2 = HypothesisSpec(
    hypothesis_id="H2",
    title="OKX BTC spot/swap cash-and-carry on settled realizedRate",
    thesis=(
        "The same delta-neutral carry on OKX (BTC-USDT spot vs "
        "BTC-USDT-SWAP), driven strictly by the settled realizedRate rather "
        "than the announced fundingRate."
    ),
    priority="PRIMARY",
    venues=("okx",),
    instruments=("okx:BTC-USDT:spot", "okx:BTC-USDT:linear-perp"),
    periodicity="1h bars; funding accrues only at settlement instants",
    signal=(
        "Trailing mean of the settled realizedRate series, held constant "
        "between settlements. fundingRate is used only where OKX published no "
        "realizedRate, and every such row is counted and reported."
    ),
    variants=_carry_variants("H2"),
    cost_treatment="conservative_cost_stack('okx'); 1x/2x/3x reported",
    falsifiers=H1.falsifiers,
    benchmarks=("cash", "buy_and_hold_btc"),
    capacity_notes=H1.capacity_notes,
)

H3 = HypothesisSpec(
    hypothesis_id="H3",
    title="Bybit/OKX BTC funding dispersion, full venue-switching cost",
    thesis=(
        "When settled funding on the two venues diverges, long the "
        "lower-funding perpetual and short the higher-funding perpetual, "
        "collecting the spread. Requires both venue panels; must beat "
        "max(H1, H2, cash) after the complete cost of operating on two "
        "venues, including capital transfer and the unhedged window."
    ),
    priority="PRIMARY",
    venues=("bybit", "okx"),
    instruments=("bybit:BTC-USDT:linear-perp", "okx:BTC-USDT:linear-perp"),
    periodicity="1h bars aligned across venues; settled funding per venue",
    signal=(
        "Trailing mean of the settled funding SPREAD (bybit minus okx), held "
        "between settlements. Enter when |spread| exceeds entry_threshold."
    ),
    variants=_carry_variants("H3"),
    cost_treatment=(
        "conservative_cost_stack(venue, cross_venue=True) on both legs; 1x/2x/3x reported"
    ),
    falsifiers=(
        *H1.falsifiers,
        "does not beat max(H1, H2)",
        "either venue panel is missing or fails validation",
    ),
    benchmarks=("cash", "buy_and_hold_btc", "H1", "H2"),
    capacity_notes=(
        "Capacity is the minimum of the two venues' capacity, further reduced "
        "by the capital that must sit idle in transit."
    ),
)

H6 = HypothesisSpec(
    hypothesis_id="H6",
    title="Low-turnover BTC/ETH time-series momentum with volatility targeting",
    thesis=(
        "A slow time-series momentum signal on BTC and ETH, sized to a "
        "constant volatility target, earns a positive risk-adjusted return "
        "after costs at low turnover."
    ),
    priority="ADDITIONAL",
    venues=("bybit",),
    instruments=("bybit:BTC-USDT:spot", "bybit:ETH-USDT:spot"),
    periodicity="daily rebalance, weekly signal",
    signal="Sign of the trailing return over `lookback_days`, vol-targeted to 10% annual",
    variants=(
        Variant("H6-lb90", {"lookback_days": 90, "vol_target_annual": 0.10}),
        Variant("H6-lb180", {"lookback_days": 180, "vol_target_annual": 0.10}),
    ),
    cost_treatment="conservative_cost_stack('bybit') on spot legs only; 1x/2x/3x",
    falsifiers=(
        "net return <= 0 after costs",
        "does not beat buy-and-hold on the same instruments",
        "turnover exceeds the registered ceiling",
    ),
    benchmarks=("cash", "buy_and_hold_btc", "buy_and_hold_eth"),
    capacity_notes="Spot-only, no leverage; capacity bounded by daily volume.",
)

H7 = HypothesisSpec(
    hypothesis_id="H7",
    title="Low-turnover BTC/ETH/cash relative rotation, unlevered",
    thesis=(
        "Rotating between BTC, ETH and cash on relative trailing strength, "
        "without leverage and at low turnover, beats holding either asset."
    ),
    priority="ADDITIONAL",
    venues=("bybit",),
    instruments=("bybit:BTC-USDT:spot", "bybit:ETH-USDT:spot", "cash"),
    periodicity="weekly rebalance",
    signal="Hold the higher trailing-`lookback_days` return of BTC/ETH; cash when both negative",
    variants=(
        Variant("H7-lb60", {"lookback_days": 60}),
        Variant("H7-lb120", {"lookback_days": 120}),
    ),
    cost_treatment="conservative_cost_stack('bybit') on every rotation; 1x/2x/3x",
    falsifiers=(
        "net return <= 0 after costs",
        "does not beat the better of buy-and-hold BTC / ETH",
        "uses leverage",
    ),
    benchmarks=("cash", "buy_and_hold_btc", "buy_and_hold_eth"),
    capacity_notes="Spot-only, unlevered; capacity bounded by daily volume.",
)

PRIMARY_HYPOTHESES: tuple[HypothesisSpec, ...] = (H1, H2, H3)
ADDITIONAL_HYPOTHESES: tuple[HypothesisSpec, ...] = (H6, H7)
ALL_HYPOTHESES: tuple[HypothesisSpec, ...] = PRIMARY_HYPOTHESES + ADDITIONAL_HYPOTHESES


@dataclass
class Preregistration:
    registered_at_utc: str
    registered_at_commit: str
    hypotheses: tuple[HypothesisSpec, ...]
    gates: dict[str, Any] = field(default_factory=lambda: dict(PROMOTION_GATES))
    splits: dict[str, Any] = field(default_factory=lambda: dict(DATA_SPLITS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "V8_PREREGISTRATION",
            "schema_version": 1,
            "registered_at_utc": self.registered_at_utc,
            "registered_at_commit": self.registered_at_commit,
            "gates": self.gates,
            "splits": self.splits,
            "max_additional_variants": MAX_ADDITIONAL_VARIANTS,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
        }

    @property
    def freeze_hash(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict()))


def preregistration() -> Preregistration:
    return Preregistration(
        registered_at_utc=REGISTERED_AT_UTC,
        registered_at_commit=REGISTERED_AT_COMMIT,
        hypotheses=ALL_HYPOTHESES,
    )


def freeze_hash() -> str:
    """SHA-256 of the frozen registration. Rides in every campaign artifact."""
    return preregistration().freeze_hash


def hypothesis(hypothesis_id: str) -> HypothesisSpec:
    for spec in ALL_HYPOTHESES:
        if spec.hypothesis_id == hypothesis_id:
            return spec
    raise ValueError(f"unknown hypothesis {hypothesis_id!r}")


def additional_variant_budget() -> int:
    return sum(len(h.variants) for h in ADDITIONAL_HYPOTHESES)


__all__ = [
    "ADDITIONAL_HYPOTHESES",
    "ALL_HYPOTHESES",
    "DATA_SPLITS",
    "MAX_ADDITIONAL_VARIANTS",
    "PRIMARY_HYPOTHESES",
    "PROMOTION_GATES",
    "REGISTERED_AT_COMMIT",
    "REGISTERED_AT_UTC",
    "HypothesisSpec",
    "Preregistration",
    "Variant",
    "additional_variant_budget",
    "freeze_hash",
    "hypothesis",
    "preregistration",
]
