"""Adversarial tests for target-feasibility arithmetic.

The golden values here are the numbers quoted in
``docs/CLAUDE_ALPHA_SEARCH_REPORT.md``.  If a change moves them, the report is
wrong until it is updated; that is the point of pinning them.
"""

from __future__ import annotations

import math

import pytest

from quant_trade.ops.growth_feasibility import (
    MAXIMUM_CREDIBLE_NET_SHARPE,
    MAXIMUM_KELLY_FRACTION,
    TargetFeasibility,
    TargetFeasibilityRequest,
    breakeven_gross_sharpe,
    evaluate_target_feasibility,
    hit_probability,
    kelly_growth_rate,
    maximum_hit_probability,
    median_log_growth,
    required_sharpe_for_probability,
    turnover_cost_drag,
    variance_optimal_volatility,
    years_to_multiple,
)

TEN_THOUSAND_X = 10_000.0
ONE_MONTH_YEARS = 30.0 / 365.0


def _request(**overrides: object) -> TargetFeasibilityRequest:
    base: dict[str, object] = {
        "starting_capital_usd": 100.0,
        "target_capital_usd": 1_000_000.0,
        "horizon_days": 30,
        "horizon_basis": "CALENDAR",
        "assumed_net_sharpe": 1.0,
        "assumed_annual_volatility": 0.30,
        "kelly_fraction": 0.5,
        "annual_round_trips": 52.0,
        "round_trip_cost_bps": 50.0,
        "monthly_fixed_cost_usd": 99.0,
    }
    base.update(overrides)
    return TargetFeasibilityRequest(**base)  # type: ignore[arg-type]


def test_required_daily_return_for_ten_thousand_x() -> None:
    result = evaluate_target_feasibility(_request())
    assert result.compounding is not None
    assert result.compounding.target_multiple == pytest.approx(TEN_THOUSAND_X)
    assert result.compounding.required_return_per_period_fraction == pytest.approx(
        0.359356, abs=5e-6
    )
    assert result.compounding.required_return_per_trading_session_fraction == pytest.approx(
        0.559990, abs=5e-6
    )
    assert result.compounding.extreme_target_multiple is True


def test_more_volatility_stops_helping_at_the_variance_optimum() -> None:
    """The whole point: past this level, extra risk lowers P(success)."""
    optimum = variance_optimal_volatility(TEN_THOUSAND_X, ONE_MONTH_YEARS)
    assert optimum == pytest.approx(14.97, abs=0.01)
    best = hit_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.0, optimum)
    for wrong in (optimum / 4.0, optimum / 2.0, optimum * 2.0, optimum * 4.0):
        assert hit_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.0, wrong) < best
    assert best == pytest.approx(maximum_hit_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.0))


def test_probability_ceiling_with_no_edge_is_one_in_112915() -> None:
    ceiling = maximum_hit_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.0)
    assert ceiling == pytest.approx(8.856e-06, rel=1e-3)
    assert 1.0 / ceiling == pytest.approx(112_915, rel=1e-3)


def test_even_an_elite_sharpe_cannot_buy_a_five_percent_chance() -> None:
    for sharpe in (0.0, 1.0, 2.0, 3.0):
        assert maximum_hit_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, sharpe) < 0.05
    assert required_sharpe_for_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.05) == pytest.approx(
        9.23, abs=0.01
    )
    assert required_sharpe_for_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, 0.50) == pytest.approx(
        14.97, abs=0.01
    )


def test_at_the_optimal_volatility_the_median_is_capital_divided_by_the_multiple() -> None:
    """An exact identity, not an approximation: median = W0 / M at sigma*."""
    for start, multiple in ((100.0, 10_000.0), (200.0, 5_000.0), (1_000.0, 250.0)):
        optimum = variance_optimal_volatility(multiple, ONE_MONTH_YEARS)
        median = start * math.exp(median_log_growth(0.0, optimum, ONE_MONTH_YEARS))
        assert median == pytest.approx(start / multiple, rel=1e-9)


def test_kelly_growth_rates_match_the_closed_forms() -> None:
    for sharpe in (0.5, 1.0, 1.5, 2.0):
        assert kelly_growth_rate(sharpe, 1.0) == pytest.approx(sharpe**2 / 2.0)
        assert kelly_growth_rate(sharpe, 0.5) == pytest.approx(3.0 * sharpe**2 / 8.0)
    assert years_to_multiple(TEN_THOUSAND_X, 1.0, 0.5) == pytest.approx(24.56, abs=0.01)
    assert years_to_multiple(TEN_THOUSAND_X, 2.0, 1.0) == pytest.approx(4.61, abs=0.01)


def test_oversizing_past_twice_kelly_never_reaches_the_target() -> None:
    assert kelly_growth_rate(2.0, MAXIMUM_KELLY_FRACTION) == pytest.approx(0.0)
    assert years_to_multiple(TEN_THOUSAND_X, 2.0, 2.5) is None


def test_cost_drag_and_fixed_cost_arithmetic() -> None:
    assert turnover_cost_drag(52.0, 50.0) == pytest.approx(0.26)
    assert breakeven_gross_sharpe(0.26, 0.30) == pytest.approx(0.8667, abs=1e-4)
    result = evaluate_target_feasibility(_request())
    assert result.costs is not None
    assert result.costs.monthly_fixed_cost_fraction_of_capital == pytest.approx(0.99)
    assert result.costs.annual_fixed_cost_fraction_of_capital == pytest.approx(11.88)


def test_a_ten_thousand_x_month_is_no_go_with_named_reasons() -> None:
    result = evaluate_target_feasibility(_request())
    assert result.status == "NO_GO"
    assert result.feasible is False
    joined = " | ".join(result.blocking_conditions)
    assert "net Sharpe of 9.23" in joined
    assert "fixed costs consume 1188% of the capital per year" in joined


def test_a_modest_target_with_no_fixed_cost_is_arithmetically_consistent() -> None:
    result = evaluate_target_feasibility(
        _request(
            target_capital_usd=110.0,
            horizon_days=365,
            monthly_fixed_cost_usd=0.0,
            annual_round_trips=12.0,
            round_trip_cost_bps=2.0,
        )
    )
    assert result.status == "FEASIBLE"
    assert result.to_dict()["real_money_authorized"] is False
    assert result.to_dict()["profit_claim_authorized"] is False


def test_feasible_still_authorizes_nothing() -> None:
    payload = evaluate_target_feasibility(
        _request(target_capital_usd=110.0, horizon_days=365, monthly_fixed_cost_usd=0.0)
    ).to_dict()
    for flag in (
        "automatic_transition_authorized",
        "external_action_authorized",
        "real_money_authorized",
        "profit_claim_authorized",
    ):
        assert payload[flag] is False
    assert payload["evidence_class"] == "ASSUMPTION"


@pytest.mark.parametrize(
    "field",
    [
        "starting_capital_usd",
        "target_capital_usd",
        "horizon_days",
        "horizon_basis",
        "assumed_net_sharpe",
        "assumed_annual_volatility",
        "kelly_fraction",
        "annual_round_trips",
        "round_trip_cost_bps",
        "monthly_fixed_cost_usd",
    ],
)
def test_every_absent_field_is_insufficient_evidence_not_a_verdict(field: str) -> None:
    # Start from a request that is otherwise FEASIBLE, so the only thing that can
    # move the status is the field being removed.
    overrides: dict[str, object] = {
        "target_capital_usd": 110.0,
        "horizon_days": 365,
        "monthly_fixed_cost_usd": 0.0,
    }
    overrides[field] = None
    result = evaluate_target_feasibility(_request(**overrides))
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert field in result.missing_conditions


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "1.0", object()])
def test_non_numeric_and_non_finite_inputs_block_rather_than_crash(bad: object) -> None:
    result = evaluate_target_feasibility(_request(assumed_annual_volatility=bad))
    assert result.status == "NO_GO"
    assert result.request_digest


@pytest.mark.parametrize("sharpe", [-2.0, -1.0, 0.0])
def test_a_non_positive_sharpe_grows_nothing_because_shorting_is_not_permitted(
    sharpe: float,
) -> None:
    """S**2 would report a positive rate by discarding the sign; long-only cannot."""
    assert kelly_growth_rate(sharpe, 0.5) == 0.0
    result = evaluate_target_feasibility(
        _request(assumed_net_sharpe=sharpe, target_capital_usd=110.0, monthly_fixed_cost_usd=0.0)
    )
    assert result.growth_path is not None
    assert result.growth_path.annual_log_growth_rate == 0.0
    assert result.growth_path.years_to_target_multiple is None


def test_a_target_below_the_starting_capital_is_blocked() -> None:
    result = evaluate_target_feasibility(_request(target_capital_usd=50.0))
    assert result.status == "NO_GO"
    assert any(
        "must exceed starting_capital_usd" in reason for reason in result.blocking_conditions
    )


def test_an_unknown_horizon_basis_is_blocked() -> None:
    result = evaluate_target_feasibility(_request(horizon_basis="WEEKS"))
    assert result.status == "NO_GO"
    assert any("CALENDAR or TRADING" in reason for reason in result.blocking_conditions)


def test_kelly_beyond_the_ceiling_is_blocked() -> None:
    result = evaluate_target_feasibility(_request(kelly_fraction=3.0))
    assert result.status == "NO_GO"
    assert any("exceeds 2" in reason for reason in result.blocking_conditions)


def test_the_screening_ceiling_is_the_declared_constant() -> None:
    """A future edit that quietly raises the ceiling has to change this test."""
    assert MAXIMUM_CREDIBLE_NET_SHARPE == 3.0


def test_evaluation_is_deterministic_and_digest_bound() -> None:
    first = evaluate_target_feasibility(_request())
    second = evaluate_target_feasibility(_request())
    assert first == second
    assert first.assessment_digest == second.assessment_digest
    assert first.is_verified() is True


def test_a_tampered_result_fails_to_recompute() -> None:
    honest = evaluate_target_feasibility(_request())
    forged = TargetFeasibility(
        request=honest.request,
        status="FEASIBLE",
        compounding=honest.compounding,
        reachability=honest.reachability,
        costs=honest.costs,
        growth_path=honest.growth_path,
        blocking_conditions=(),
        missing_conditions=(),
        request_digest=honest.request_digest,
        assessment_digest=honest.assessment_digest,
    )
    assert forged.is_verified() is False


def test_a_non_request_object_is_rejected() -> None:
    with pytest.raises(TypeError):
        evaluate_target_feasibility({"starting_capital_usd": 100.0})  # type: ignore[arg-type]


@pytest.mark.parametrize("multiple", [1.0, 0.5, 0.0, -2.0, float("nan"), float("inf")])
def test_public_helpers_reject_a_non_multiple(multiple: float) -> None:
    with pytest.raises(ValueError):
        variance_optimal_volatility(multiple, ONE_MONTH_YEARS)
    with pytest.raises(ValueError):
        maximum_hit_probability(multiple, ONE_MONTH_YEARS, 1.0)


@pytest.mark.parametrize("probability", [0.0, 1.0, -0.1, 1.5])
def test_required_sharpe_rejects_a_probability_outside_the_open_unit_interval(
    probability: float,
) -> None:
    with pytest.raises(ValueError):
        required_sharpe_for_probability(TEN_THOUSAND_X, ONE_MONTH_YEARS, probability)
