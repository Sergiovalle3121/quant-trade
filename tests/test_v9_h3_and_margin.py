"""Margin, intrabar liquidation, and the two-venue H3 balance sheet."""

from __future__ import annotations

import pytest

from quant_trade.v9.h3_ledger import (
    DispersionBar,
    H3LedgerError,
    VenueBook,
    VenueCosts,
    dispersion_capacity,
    run_dispersion,
)
from quant_trade.v9.margin import (
    InstrumentRisk,
    MarginError,
    MarginState,
    RiskTier,
    capital_requirement,
    default_instrument_risk,
)

HOUR_MS = 3_600_000
BASE_MS = 1_700_000_000_000


# --- risk tiers ------------------------------------------------------------------


def test_maintenance_steps_up_with_notional() -> None:
    risk = default_instrument_risk("bybit")
    small = risk.maintenance_margin(10_000.0) / 10_000.0
    large = risk.maintenance_margin(500_000.0) / 500_000.0
    assert large > small


def test_the_top_tier_is_the_ceiling() -> None:
    risk = default_instrument_risk("bybit")
    assert risk.tier_for(10_000_000.0) is risk.tiers[-1]


def test_maintenance_above_initial_is_rejected() -> None:
    with pytest.raises(MarginError, match="liquidatable the moment it opened"):
        RiskTier(
            max_notional_usd=1_000.0,
            initial_margin_rate=0.01,
            maintenance_margin_rate=0.05,
        )


def test_unordered_tiers_are_rejected() -> None:
    with pytest.raises(MarginError, match="ordered by max_notional_usd"):
        InstrumentRisk(
            venue="bybit",
            instrument="BTCUSDT",
            tiers=(
                RiskTier(1_000_000.0, 0.25, 0.025),
                RiskTier(50_000.0, 0.10, 0.005),
            ),
            min_order_qty=0.001,
            qty_step=0.001,
            tick_size=0.1,
            min_notional_usd=5.0,
        )


def test_quantity_rounds_down_to_the_lot_grid() -> None:
    risk = default_instrument_risk("bybit")
    assert risk.round_quantity(0.0019) == pytest.approx(0.001)
    assert risk.round_quantity(0.0005) == 0.0


def test_an_order_below_the_venue_minimum_is_not_tradeable() -> None:
    risk = default_instrument_risk("bybit")
    ok, why = risk.is_tradeable(0.0005, 64_000.0)
    assert not ok
    assert "below the venue minimum" in why


def test_a_notional_below_the_venue_minimum_is_not_tradeable() -> None:
    risk = InstrumentRisk(
        venue="bybit",
        instrument="BTCUSDT",
        tiers=(RiskTier(1_000_000.0, 0.10, 0.005),),
        min_order_qty=0.001,
        qty_step=0.001,
        tick_size=0.1,
        min_notional_usd=100.0,
    )
    ok, why = risk.is_tradeable(0.001, 50.0)
    assert not ok
    assert "notional" in why


# --- intrabar liquidation -----------------------------------------------------------


def _short(quantity: float = -0.05, price: float = 64_000.0) -> MarginState:
    state = MarginState(risk=default_instrument_risk("bybit"))
    state.open(quantity=quantity, price=price)
    return state


def test_a_short_is_measured_against_the_high_not_the_close() -> None:
    """The event a close-only check cannot see."""
    state = _short()
    # The bar spikes 20% and comes back to where it started.
    event = state.check_intrabar(high=76_800.0, low=63_000.0, at_ms=BASE_MS)
    assert event is not None
    assert state.liquidations == 1
    assert event["breach_mark"] == 76_800.0
    assert "adverse extreme" in event["reason"]


def test_a_long_is_measured_against_the_low() -> None:
    state = MarginState(risk=default_instrument_risk("bybit"))
    state.open(quantity=0.05, price=64_000.0)
    assert state.worst_mark(high=70_000.0, low=50_000.0) == 50_000.0
    assert state.check_intrabar(high=70_000.0, low=50_000.0, at_ms=BASE_MS) is not None


def test_a_quiet_bar_does_not_liquidate() -> None:
    state = _short()
    assert state.check_intrabar(high=64_200.0, low=63_800.0, at_ms=BASE_MS) is None
    assert state.liquidations == 0
    assert state.quantity == pytest.approx(-0.05)


def test_a_liquidation_closes_the_position_and_charges_a_penalty() -> None:
    state = _short()
    event = state.check_intrabar(high=100_000.0, low=63_000.0, at_ms=BASE_MS)
    assert event is not None
    assert event["penalty_usd"] > 0
    assert state.quantity == 0.0
    assert state.posted_margin_usd == 0.0
    assert state.emergency_reserve_usd == 0.0


def test_a_flat_position_cannot_liquidate() -> None:
    state = MarginState(risk=default_instrument_risk("bybit"))
    assert state.check_intrabar(high=1e9, low=1.0, at_ms=BASE_MS) is None


def test_variation_margin_moves_with_the_mark() -> None:
    state = _short()
    assert state.variation_margin(63_000.0) > 0  # a short gains as price falls
    assert state.variation_margin(65_000.0) < 0


# --- capital requirement -------------------------------------------------------------


def test_capital_requirement_counts_every_immobilised_dollar() -> None:
    requirement = capital_requirement(
        notional_usd=10_000.0,
        risk=default_instrument_risk("bybit"),
        round_trip_cost_fraction=0.006,
    )
    assert requirement.spot_capital_usd == 10_000.0
    assert requirement.initial_margin_usd > 0
    assert requirement.emergency_reserve_usd > 0
    assert requirement.fee_reserve_usd == pytest.approx(60.0)
    assert requirement.total_capital_usd > requirement.spot_capital_usd
    assert 0 < requirement.capital_efficiency < 1


def test_a_perp_only_structure_posts_no_spot_capital() -> None:
    requirement = capital_requirement(
        notional_usd=10_000.0,
        risk=default_instrument_risk("bybit"),
        round_trip_cost_fraction=0.006,
        spot_leg=False,
    )
    assert requirement.spot_capital_usd == 0.0
    assert requirement.total_capital_usd < 10_000.0


def test_the_capital_formula_matches_what_the_margin_state_posts() -> None:
    """The requirement and the ledger must share one definition."""
    risk = default_instrument_risk("bybit")
    notional = 10_000.0
    requirement = capital_requirement(
        notional_usd=notional, risk=risk, round_trip_cost_fraction=0.0
    )
    state = MarginState(risk=risk)
    posted = state.open(quantity=-notional / 64_000.0, price=64_000.0)
    assert posted == pytest.approx(
        requirement.initial_margin_usd + requirement.emergency_reserve_usd, rel=1e-9
    )


def test_zero_notional_is_rejected() -> None:
    with pytest.raises(MarginError, match="notional_usd must be > 0"):
        capital_requirement(
            notional_usd=0.0,
            risk=default_instrument_risk("bybit"),
            round_trip_cost_fraction=0.0,
        )


# --- H3 dispersion ---------------------------------------------------------------------


def _costs(venue: str, taker: float) -> VenueCosts:
    return VenueCosts(
        venue=venue,
        perp_taker_bps=taker,
        half_spread_bps=1.0,
        slippage_bps=1.0,
        impact_bps=1.0,
        transfer_out_fraction=0.0015,
        transfer_hours=1.0,
    )


def _books(cash: float = 5_000.0) -> tuple[VenueBook, VenueBook]:
    return (
        VenueBook(
            venue="bybit",
            costs=_costs("bybit", 5.5),
            risk=default_instrument_risk("bybit"),
            cash_usd=cash,
        ),
        VenueBook(
            venue="okx",
            costs=_costs("okx", 5.0),
            risk=default_instrument_risk("okx", "BTC-USDT-SWAP"),
            cash_usd=cash,
        ),
    )


def _bars(
    count: int = 60,
    *,
    funding_a: float = 0.0004,
    funding_b: float = 0.0001,
    spike_at: int | None = None,
    funding_every: int = 8,
    volume_a: float = 5e6,
    volume_b: float = 3e6,
) -> list[DispersionBar]:
    bars = []
    for index in range(count):
        mark = 64_000.0 + index * 5
        high_a = mark * (3.0 if spike_at == index else 1.002)
        bars.append(
            DispersionBar(
                start_ms=BASE_MS + index * HOUR_MS,
                end_ms=BASE_MS + (index + 1) * HOUR_MS,
                observed_at_ms=BASE_MS + (index + 1) * HOUR_MS,
                mark_a=mark,
                high_a=high_a,
                low_a=mark * 0.998,
                mark_b=mark + 3,
                high_b=(mark + 3) * 1.002,
                low_b=(mark + 3) * 0.998,
                settled_funding_a=funding_a if index % funding_every == 0 else 0.0,
                settled_funding_b=funding_b if index % funding_every == 0 else 0.0,
                quote_volume_a=volume_a,
                quote_volume_b=volume_b,
            )
        )
    return bars


def _run(**overrides):
    book_a, book_b = _books()
    return (
        run_dispersion(
            _bars(**overrides.pop("bars_kwargs", {})),
            book_a=book_a,
            book_b=book_b,
            entry_threshold=overrides.pop("entry_threshold", 0.00005),
            trailing_window=overrides.pop("trailing_window", 3),
            target_notional_usd=overrides.pop("target_notional_usd", 2_000.0),
            transfer_reserve_fraction=overrides.pop("transfer_reserve_fraction", 1.0),
        ),
        book_a,
        book_b,
    )


def test_returns_come_from_equity_not_from_a_pnl_sum() -> None:
    result, _a, _b = _run()
    assert len(result.equity_curve) == len(result.returns) + 1
    for index, value in enumerate(result.returns):
        previous = result.equity_curve[index]
        current = result.equity_curve[index + 1]
        assert value == pytest.approx(current / previous - 1.0, rel=1e-12)


def test_the_flow_journal_reconciles_with_the_equity_change() -> None:
    result, _a, _b = _run()
    assert result.reconciled
    assert result.reconciliation_error == pytest.approx(0.0, abs=1e-6)


def test_each_venue_pays_its_own_fees() -> None:
    """V8 charged Bybit's schedule on both legs; the two must differ."""
    result, book_a, book_b = _run()
    assert book_a.fees_usd > 0
    assert book_b.fees_usd > 0
    assert book_a.fees_usd != book_b.fees_usd
    assert book_a.costs.perp_taker_bps != book_b.costs.perp_taker_bps


def test_costs_reduce_the_net_return() -> None:
    result, _a, _b = _run()
    assert result.totals["fees_usd"] > 0
    assert result.totals["transfer_usd"] > 0
    assert result.net_return < 0 or result.totals["funding_spread_usd"] > 0


def test_capacity_is_the_minimum_of_both_venues() -> None:
    capacity = dispersion_capacity(_bars(volume_a=5e6, volume_b=3e6))
    assert capacity["available"]
    assert capacity["capacity_usd"] == pytest.approx(
        min(capacity["venue_a_capacity_usd"], capacity["venue_b_capacity_usd"])
    )
    assert capacity["binding_venue"] == "b"


def test_capacity_binds_on_whichever_venue_is_thinner() -> None:
    capacity = dispersion_capacity(_bars(volume_a=1e6, volume_b=9e6))
    assert capacity["binding_venue"] == "a"


def test_capacity_is_unknown_when_a_venue_has_no_volume() -> None:
    capacity = dispersion_capacity(_bars(volume_b=0.0))
    assert not capacity["available"]
    assert "one or both venues" in capacity["reason"]


def test_an_intrabar_spike_liquidates_and_is_counted() -> None:
    # Funding every bar keeps the position continuously open, so the spike
    # lands on a live short rather than on a flat book.
    result, _a, _b = _run(bars_kwargs={"spike_at": 20, "funding_every": 1})
    assert result.liquidations >= 1
    assert result.totals["liquidation_penalty_usd"] > 0
    assert any("liquidation on bybit" in p for p in result.problems)


def test_too_few_aligned_bars_is_refused() -> None:
    book_a, book_b = _books()
    with pytest.raises(H3LedgerError, match="history on BOTH venues"):
        run_dispersion(
            _bars(3),
            book_a=book_a,
            book_b=book_b,
            entry_threshold=0.0,
            trailing_window=10,
            target_notional_usd=1_000.0,
        )


def test_a_bar_with_low_above_high_is_refused() -> None:
    with pytest.raises(H3LedgerError, match="low cannot exceed high"):
        DispersionBar(
            start_ms=0,
            end_ms=1,
            observed_at_ms=1,
            mark_a=100.0,
            high_a=90.0,
            low_a=110.0,
            mark_b=100.0,
            high_b=110.0,
            low_b=90.0,
        )


def test_a_notional_below_the_venue_minimum_is_reported_not_traded() -> None:
    book_a, book_b = _books()
    result = run_dispersion(
        _bars(40),
        book_a=book_a,
        book_b=book_b,
        entry_threshold=0.00005,
        trailing_window=3,
        target_notional_usd=1.0,  # far below the lot minimum
    )
    assert result.entries == 0
    assert any("below the venue minimum" in p for p in result.problems)


def test_zero_capital_is_refused() -> None:
    book_a, book_b = _books(cash=0.0)
    with pytest.raises(H3LedgerError, match="positive starting capital"):
        run_dispersion(
            _bars(40),
            book_a=book_a,
            book_b=book_b,
            entry_threshold=0.0,
            trailing_window=3,
            target_notional_usd=1_000.0,
        )


def test_the_artifact_states_the_return_definition() -> None:
    result, _a, _b = _run()
    payload = result.to_dict()
    assert payload["artifact"] == "H3_LEDGER_RECONCILIATION"
    assert "equity_t/equity_{t-1}" in payload["note"]
    assert "neither venue's costs are applied to the other's leg" in payload["note"]
    assert payload["observations"] == len(result.returns)
