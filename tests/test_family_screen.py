"""Adversarial tests for the pre-data capital screen.

The screen exists to refuse a family before it consumes a trial, so the cases
that matter most are the ones where it must refuse: a position below the venue
minimum, frictions that eat the whole Sharpe, a subscription larger than the
account, a licence that forbids the use, and data that cannot be point-in-time.
"""

from __future__ import annotations

import pytest

from quant_trade.ops.family_screen import (
    FamilyScreen,
    StrategyFamilyProfile,
    minimum_capital_for_shape,
    screen_families,
    screen_family,
)
from quant_trade.ops.growth_feasibility import MAXIMUM_CREDIBLE_NET_SHARPE


def _profile(**overrides: object) -> StrategyFamilyProfile:
    """A deliberately benign baseline: US$100 of fractional US equities."""
    base: dict[str, object] = {
        "family_id": "baseline",
        "capital_usd": 100.0,
        "concurrent_positions": 5,
        "annual_rebalances": 12.0,
        "portfolio_fraction_traded_per_rebalance": 1.0,
        "per_side_cost_bps": 1.0,
        "minimum_notional_usd": 1.0,
        "reference_unit_price_usd": 500.0,
        "fractional_units_supported": True,
        "monthly_data_cost_usd": 0.0,
        "data_licence_status": "NOT_REQUIRED",
        "point_in_time_data_available": True,
        "assumed_annual_volatility": 0.30,
    }
    base.update(overrides)
    return StrategyFamilyProfile(**base)  # type: ignore[arg-type]


def test_a_runnable_shape_is_feasible_without_claiming_any_edge() -> None:
    screen = screen_family(_profile())
    assert screen.status == "FEASIBLE"
    assert screen.binding_constraint == "none"
    payload = screen.to_dict()
    assert payload["edge_established"] is False
    assert payload["preregistration_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert payload["evidence_class"] == "ASSUMPTION"


def test_a_wide_cross_section_at_small_capital_is_blocked_by_the_venue_minimum() -> None:
    """20 names out of US$100 is US$5 each; a US$10 minimum makes it unrunnable."""
    screen = screen_family(_profile(concurrent_positions=20, minimum_notional_usd=10.0))
    assert screen.status == "NO_GO"
    assert screen.binding_constraint == "min_notional"
    assert screen.capital_per_position_usd == pytest.approx(5.0)
    assert screen.minimum_capital_for_this_shape_usd == pytest.approx(200.0)


def test_without_fractional_units_the_share_price_binds_not_the_venue_minimum() -> None:
    screen = screen_family(
        _profile(
            concurrent_positions=5,
            fractional_units_supported=False,
            reference_unit_price_usd=500.0,
            minimum_notional_usd=1.0,
        )
    )
    assert screen.status == "NO_GO"
    assert screen.binding_constraint == "indivisible_unit"
    assert screen.minimum_executable_outlay_usd == pytest.approx(500.0)


def test_weekly_crypto_rotation_is_blocked_by_cost_drag_alone() -> None:
    """52 round trips at 25 bps a side is 26%/yr before any signal exists."""
    screen = screen_family(_profile(annual_rebalances=52.0, per_side_cost_bps=25.0))
    assert screen.annual_turnover_cost_fraction == pytest.approx(0.26)
    assert screen.breakeven_gross_sharpe == pytest.approx(0.8667, abs=1e-4)
    # 0.87 is brutal but below the ceiling, so cost is reported, not fatal.
    assert screen.status == "FEASIBLE"

    daily = screen_family(_profile(annual_rebalances=252.0, per_side_cost_bps=25.0))
    assert daily.status == "NO_GO"
    assert daily.binding_constraint == "cost_drag"
    assert daily.breakeven_gross_sharpe is not None
    assert daily.breakeven_gross_sharpe > MAXIMUM_CREDIBLE_NET_SHARPE


def test_a_data_subscription_larger_than_the_account_is_blocked() -> None:
    screen = screen_family(_profile(monthly_data_cost_usd=99.0, data_licence_status="NOT_REQUIRED"))
    assert screen.status == "NO_GO"
    assert screen.annual_fixed_cost_fraction == pytest.approx(11.88)
    assert any("outside the account" in reason for reason in screen.blocking_conditions)


def test_the_same_subscription_stops_binding_once_capital_is_large_enough() -> None:
    """The screen is about the ratio, not about disliking paid data."""
    screen = screen_family(_profile(monthly_data_cost_usd=99.0, capital_usd=50_000.0))
    assert screen.annual_fixed_cost_fraction == pytest.approx(0.02376)
    assert screen.status == "FEASIBLE"


def test_a_non_commercial_licence_blocks_regardless_of_the_arithmetic() -> None:
    screen = screen_family(_profile(data_licence_status="NON_COMMERCIAL"))
    assert screen.status == "NO_GO"
    assert any("forbids commercial use" in reason for reason in screen.blocking_conditions)


def test_an_unknown_licence_is_missing_evidence_never_permission() -> None:
    screen = screen_family(_profile(data_licence_status="UNKNOWN"))
    assert screen.status == "INSUFFICIENT_EVIDENCE"
    assert "verified_data_licence" in screen.missing_conditions


def test_data_that_cannot_be_point_in_time_is_blocked() -> None:
    screen = screen_family(_profile(point_in_time_data_available=False))
    assert screen.status == "NO_GO"
    assert screen.binding_constraint == "no_point_in_time_data"


@pytest.mark.parametrize(
    "field",
    [
        "family_id",
        "capital_usd",
        "concurrent_positions",
        "annual_rebalances",
        "portfolio_fraction_traded_per_rebalance",
        "per_side_cost_bps",
        "minimum_notional_usd",
        "reference_unit_price_usd",
        "fractional_units_supported",
        "monthly_data_cost_usd",
        "data_licence_status",
        "point_in_time_data_available",
        "assumed_annual_volatility",
    ],
)
def test_every_absent_field_is_insufficient_evidence(field: str) -> None:
    screen = screen_family(_profile(**{field: None}))
    assert screen.status == "INSUFFICIENT_EVIDENCE"
    assert field in screen.missing_conditions


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "5", object(), -1.0])
def test_invalid_numbers_block_rather_than_crash(bad: object) -> None:
    screen = screen_family(_profile(capital_usd=bad))
    assert screen.status == "NO_GO"
    assert screen.profile_digest


@pytest.mark.parametrize("bad", ["yes", 1, "PENDING", ""])
def test_an_unrecognised_licence_state_is_blocked_not_ignored(bad: object) -> None:
    screen = screen_family(_profile(data_licence_status=bad))
    assert screen.status == "NO_GO"


def test_a_non_boolean_flag_is_blocked() -> None:
    assert screen_family(_profile(fractional_units_supported="true")).status == "NO_GO"
    assert screen_family(_profile(point_in_time_data_available=1)).status == "NO_GO"


def test_trading_more_than_the_whole_portfolio_is_blocked() -> None:
    screen = screen_family(_profile(portfolio_fraction_traded_per_rebalance=1.5))
    assert screen.status == "NO_GO"
    assert any("cannot exceed 1" in reason for reason in screen.blocking_conditions)


def test_partial_rotation_costs_proportionally_less() -> None:
    full = screen_family(_profile(annual_rebalances=12.0, per_side_cost_bps=25.0))
    quarter = screen_family(
        _profile(
            annual_rebalances=12.0,
            per_side_cost_bps=25.0,
            portfolio_fraction_traded_per_rebalance=0.25,
        )
    )
    assert full.annual_turnover_cost_fraction is not None
    assert quarter.annual_turnover_cost_fraction == pytest.approx(
        full.annual_turnover_cost_fraction / 4.0
    )


def test_minimum_capital_helper_agrees_with_the_screen() -> None:
    for fractional in (True, False):
        screen = screen_family(
            _profile(
                concurrent_positions=20,
                minimum_notional_usd=10.0,
                reference_unit_price_usd=500.0,
                fractional_units_supported=fractional,
            )
        )
        assert screen.minimum_capital_for_this_shape_usd == minimum_capital_for_shape(
            concurrent_positions=20,
            minimum_notional_usd=10.0,
            reference_unit_price_usd=500.0,
            fractional_units_supported=fractional,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"concurrent_positions": 0},
        {"concurrent_positions": -3},
        {"minimum_notional_usd": float("nan")},
        {"reference_unit_price_usd": -1.0},
    ],
)
def test_minimum_capital_helper_rejects_impossible_inputs(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "concurrent_positions": 10,
        "minimum_notional_usd": 1.0,
        "reference_unit_price_usd": 100.0,
        "fractional_units_supported": True,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        minimum_capital_for_shape(**base)  # type: ignore[arg-type]


def test_screening_a_matrix_preserves_order_and_independence() -> None:
    profiles = (
        _profile(family_id="a"),
        _profile(family_id="b", data_licence_status="NON_COMMERCIAL"),
        _profile(family_id="c"),
    )
    screens = screen_families(profiles)
    assert [screen.profile.family_id for screen in screens] == ["a", "b", "c"]
    assert [screen.status for screen in screens] == ["FEASIBLE", "NO_GO", "FEASIBLE"]


def test_screening_is_deterministic_and_digest_bound() -> None:
    first, second = screen_family(_profile()), screen_family(_profile())
    assert first == second
    assert first.screen_digest == second.screen_digest
    assert first.is_verified() is True


def test_a_tampered_screen_fails_to_recompute() -> None:
    honest = screen_family(_profile(data_licence_status="NON_COMMERCIAL"))
    forged = FamilyScreen(
        profile=honest.profile,
        status="FEASIBLE",
        binding_constraint="none",
        capital_per_position_usd=honest.capital_per_position_usd,
        minimum_executable_outlay_usd=honest.minimum_executable_outlay_usd,
        minimum_capital_for_this_shape_usd=honest.minimum_capital_for_this_shape_usd,
        annual_round_trips=honest.annual_round_trips,
        annual_turnover_cost_fraction=honest.annual_turnover_cost_fraction,
        annual_fixed_cost_fraction=honest.annual_fixed_cost_fraction,
        total_annual_cost_fraction=honest.total_annual_cost_fraction,
        breakeven_gross_sharpe=honest.breakeven_gross_sharpe,
        blocking_conditions=(),
        missing_conditions=(),
        profile_digest=honest.profile_digest,
        screen_digest=honest.screen_digest,
    )
    assert forged.is_verified() is False


def test_a_non_profile_object_is_rejected() -> None:
    with pytest.raises(TypeError):
        screen_family({"family_id": "x"})  # type: ignore[arg-type]
