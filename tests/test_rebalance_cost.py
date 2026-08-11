"""Tests for applying the measured cost model to a portfolio rebalance.

The properties under test are the ones that decide whether a low-cap backtest
is honest: an unfillable order must not become an expensive order, an
unmeasured tier must not borrow a measured one's numbers, and the turnover
convention must match the gate that turnover is judged against.
"""

from __future__ import annotations

import pytest

from quant_trade.costs.crypto_lowcap import DEFAULT_TIER_PROFILES, CostModelError
from quant_trade.costs.rebalance import (
    QUANTILE_P50,
    QUANTILE_P75,
    max_fully_executable_notional,
    rebalance_cost,
)

MID_CAP = 500e6
LOW_CAP = 50e6
MICRO_CAP = 5e6
MEGA_CAP = 50e9
DUST_CAP = 100e3


def test_a_full_replacement_is_one_turnover() -> None:
    """Repo convention: sum |delta w| = 2.0 is one full round trip."""
    result = rebalance_cost(
        {"A": 1.0},
        {"B": 1.0},
        {"A": MID_CAP, "B": MID_CAP},
        portfolio_value_usd=10_000.0,
    )
    assert result.turnover == pytest.approx(1.0)
    assert result.refused_legs == 0


def test_no_change_costs_nothing() -> None:
    result = rebalance_cost(
        {"A": 0.5, "B": 0.5},
        {"A": 0.5, "B": 0.5},
        {"A": MID_CAP, "B": MID_CAP},
        portfolio_value_usd=10_000.0,
    )
    assert result.cost_usd == 0.0
    assert result.turnover == 0.0
    assert result.legs == []


def test_one_way_legs_sum_to_the_round_trip_cost() -> None:
    """Buying then later selling the same position must cost the round trip.

    This is the consistency check between this module and the turnover
    arithmetic in docs/CRYPTO_LOWCAP_COST_MODEL.md: turnover 1.0 at a given
    tier and size should drag by that tier's round-trip cost.
    """
    caps = {"A": LOW_CAP}
    buy = rebalance_cost({}, {"A": 1.0}, caps, portfolio_value_usd=1_000.0)
    sell = rebalance_cost({"A": 1.0}, {}, caps, portfolio_value_usd=1_000.0)
    total_bps = buy.cost_bps_of_portfolio + sell.cost_bps_of_portfolio
    # low tier, $1,000, p75: exec 25.4 bps round trip + 2 x 10 bps taker
    assert total_bps == pytest.approx(25.4 + 20.0, rel=1e-6)
    assert buy.turnover + sell.turnover == pytest.approx(1.0)


def test_a_bigger_order_pays_the_next_calibrated_rate_never_an_invented_one() -> None:
    caps = {"A": LOW_CAP}
    small = rebalance_cost({}, {"A": 1.0}, caps, portfolio_value_usd=1_000.0)
    between = rebalance_cost({}, {"A": 1.0}, caps, portfolio_value_usd=1_500.0)
    at_5k = rebalance_cost({}, {"A": 1.0}, caps, portfolio_value_usd=5_000.0)
    # $1,500 pays the $5,000 rate, not something interpolated from $1,000
    assert between.cost_bps_of_portfolio == pytest.approx(at_5k.cost_bps_of_portfolio)
    assert between.cost_bps_of_portfolio > small.cost_bps_of_portfolio


def _micro():
    return next(p for p in DEFAULT_TIER_PROFILES if p.tier == "micro")


def test_capacity_and_calibration_limits_are_different_refusals() -> None:
    """Conflating them invents a capacity limit where only a measurement gap is.

    The model was calibrated at $100-$10,000 for small capital. A $250,000
    order in mega is not impossible, it is unmeasured — and capping it at
    $10,000 would assert a depth limit for Bitcoin that nothing measured.
    A $9,000 order in micro is a different matter: only 75% of sampled micro
    books filled $10,000 and 92% filled $5,000, so that IS a capacity fact.
    """
    beyond = rebalance_cost(
        {}, {"A": 1.0}, {"A": MEGA_CAP}, portfolio_value_usd=250_000.0
    )
    assert beyond.unpriceable_legs == 1
    assert beyond.capped_legs == 0
    assert "NOT_MEASURED at this size" in beyond.legs[0].reason
    assert beyond.achieved_weights == {}

    capacity = rebalance_cost(
        {}, {"A": 1.0}, {"A": MICRO_CAP}, portfolio_value_usd=9_000.0
    )
    assert capacity.capped_legs == 1
    assert capacity.unpriceable_legs == 0
    assert "capacity" in capacity.legs[0].reason


def test_micro_capacity_stops_at_the_last_fully_fillable_size() -> None:
    """75% of micro books filled $10k and 92% filled $5k, so neither counts."""
    profile = _micro()
    assert max_fully_executable_notional(profile) == pytest.approx(1_000.0)
    result = rebalance_cost(
        {}, {"A": 1.0}, {"A": MICRO_CAP}, portfolio_value_usd=4_000.0
    )
    assert result.capped_legs == 1
    assert result.legs[0].executed_notional_usd == pytest.approx(1_000.0)
    assert result.achieved_weights["A"] == pytest.approx(0.25)


def test_a_looser_executable_fraction_admits_more_size() -> None:
    """The threshold is a declared assumption, so its effect must be visible."""
    strict = max_fully_executable_notional(_micro(), 1.0)
    loose = max_fully_executable_notional(_micro(), 0.90)
    assert loose > strict


def test_achieved_weights_are_what_the_next_period_must_use() -> None:
    caps = {"A": MICRO_CAP, "B": MEGA_CAP}
    result = rebalance_cost({}, {"A": 0.5, "B": 0.5}, caps, portfolio_value_usd=4_000.0)
    assert result.achieved_weights["B"] == pytest.approx(0.5)  # mega fills $2,000
    assert result.achieved_weights["A"] == pytest.approx(0.25)  # micro caps at $1,000
    assert result.achieved_weights["A"] < 0.5


def test_a_coin_outside_every_calibrated_tier_is_refused_not_guessed() -> None:
    result = rebalance_cost(
        {}, {"A": 1.0}, {"A": DUST_CAP}, portfolio_value_usd=1_000.0
    )
    assert result.unpriceable_legs == 1
    assert result.cost_usd == 0.0
    assert result.achieved_weights == {}  # the position was never opened
    assert "NOT_MEASURED" in result.legs[0].reason


def test_a_coin_with_no_market_cap_is_refused(tmp_path) -> None:
    result = rebalance_cost({}, {"A": 1.0}, {}, portfolio_value_usd=1_000.0)
    assert result.unpriceable_legs == 1
    assert not result.legs[0].executable


def test_p75_is_never_cheaper_than_p50() -> None:
    caps = {"A": LOW_CAP}
    p50 = rebalance_cost(
        {}, {"A": 1.0}, caps, portfolio_value_usd=5_000.0, quantile=QUANTILE_P50
    )
    p75 = rebalance_cost(
        {}, {"A": 1.0}, caps, portfolio_value_usd=5_000.0, quantile=QUANTILE_P75
    )
    assert p75.cost_bps_of_portfolio >= p50.cost_bps_of_portfolio


def test_cost_rises_monotonically_down_the_tiers() -> None:
    costs = []
    for cap in (MEGA_CAP, 5e9, MID_CAP, LOW_CAP, MICRO_CAP):
        result = rebalance_cost({}, {"A": 1.0}, {"A": cap}, portfolio_value_usd=1_000.0)
        costs.append(result.cost_bps_of_portfolio)
    assert costs == sorted(costs), f"cost should worsen down the tiers, got {costs}"


def test_invalid_inputs_are_refused() -> None:
    with pytest.raises(CostModelError):
        rebalance_cost({}, {"A": 1.0}, {"A": MID_CAP}, portfolio_value_usd=0.0)
    with pytest.raises(CostModelError):
        rebalance_cost(
            {}, {"A": 1.0}, {"A": MID_CAP}, portfolio_value_usd=1_000.0, quantile="p99"
        )


def test_partial_rebalance_turnover_is_proportional() -> None:
    caps = {"A": MID_CAP, "B": MID_CAP}
    result = rebalance_cost(
        {"A": 1.0}, {"A": 0.75, "B": 0.25}, caps, portfolio_value_usd=10_000.0
    )
    # |delta| = 0.25 + 0.25 = 0.5 -> turnover 0.25
    assert result.turnover == pytest.approx(0.25)
