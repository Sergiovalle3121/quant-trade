from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from quant_trade.ops.wealth_plan import (
    GrowthGoal,
    WealthPlanRequest,
    evaluate_wealth_plan,
)


def _goal(**overrides: object) -> GrowthGoal:
    values: dict[str, object] = {
        "starting_amount": 200.0,
        "target_amount": 240.0,
        "currency": "USD",
        "horizon_months": 12,
        "illustrative_annual_return_fraction": 0.0,
        "monthly_contribution": 0.0,
    }
    values.update(overrides)
    return GrowthGoal(**values)  # type: ignore[arg-type]


def _request(**overrides: object) -> WealthPlanRequest:
    values: dict[str, object] = {
        "total_risk_capital_usd": 2_000.0,
        "proposed_canary_usd": 200.0,
        "eligible_asset_count": 20,
        "minimum_notional_usd": 5.0,
        "minimum_notional_cushion_fraction": 0.20,
        "goal": _goal(),
    }
    values.update(overrides)
    return WealthPlanRequest(**values)  # type: ignore[arg-type]


def test_two_hundred_total_risk_capital_means_twenty_dollar_canary_and_no_go() -> None:
    result = evaluate_wealth_plan(_request(total_risk_capital_usd=200.0, proposed_canary_usd=20.0))

    assert result.status == "NO_GO"
    assert result.allowed_canary_usd == pytest.approx(20.0)
    assert result.per_asset_cap_usd == pytest.approx(1.0)
    assert result.minimum_per_asset_outlay_usd == pytest.approx(6.0)
    assert any("per-asset cap" in item for item in result.blocking_conditions)


def test_two_hundred_canary_is_not_backed_by_two_hundred_total() -> None:
    result = evaluate_wealth_plan(_request(total_risk_capital_usd=200.0, proposed_canary_usd=200.0))

    assert result.status == "NO_GO"
    assert result.allowed_canary_usd == pytest.approx(20.0)
    assert any("exceeds the allowed" in item for item in result.blocking_conditions)


def test_two_hundred_canary_backed_by_two_thousand_total_is_arithmetically_feasible() -> None:
    result = evaluate_wealth_plan(_request())

    assert result.status == "FEASIBLE"
    assert result.allowed_canary_usd == pytest.approx(200.0)
    assert result.per_asset_cap_usd == pytest.approx(10.0)
    assert result.minimum_canary_usd == pytest.approx(120.0)
    assert result.minimum_total_risk_capital_usd == pytest.approx(1_200.0)
    assert result.required_total_risk_capital_usd_for_proposed_canary == pytest.approx(2_000.0)
    assert result.is_verified()
    payload = result.to_dict()
    assert payload["automatic_transition_authorized"] is False
    assert payload["external_action_authorized"] is False
    assert payload["real_money_authorized"] is False
    assert payload["profit_claim_authorized"] is False


def test_minimum_notional_and_cushion_are_explicit_not_live_market_claims() -> None:
    lower = evaluate_wealth_plan(_request(minimum_notional_cushion_fraction=0.0))
    higher = evaluate_wealth_plan(_request(minimum_notional_cushion_fraction=1.1))

    assert lower.status == "FEASIBLE"
    assert lower.minimum_per_asset_outlay_usd == pytest.approx(5.0)
    assert higher.status == "NO_GO"
    assert higher.minimum_per_asset_outlay_usd == pytest.approx(10.5)


def test_missing_execution_or_goal_evidence_is_insufficient() -> None:
    missing_notional = evaluate_wealth_plan(_request(minimum_notional_usd=None))
    missing_goal = evaluate_wealth_plan(_request(goal=None))

    assert missing_notional.status == "INSUFFICIENT_EVIDENCE"
    assert "minimum_notional_usd" in missing_notional.missing_conditions
    assert missing_goal.status == "INSUFFICIENT_EVIDENCE"
    assert "goal" in missing_goal.missing_conditions


def test_fewer_than_twenty_distinct_eligible_assets_is_no_go() -> None:
    result = evaluate_wealth_plan(_request(eligible_asset_count=19))

    assert result.status == "NO_GO"
    assert any("20 are required" in item for item in result.blocking_conditions)


def test_one_month_thousand_x_is_explicitly_rejected_as_an_impossible_shortcut() -> None:
    result = evaluate_wealth_plan(_request(goal=_goal(target_amount=200_000.0, horizon_months=1)))
    projection = result.goal_projection

    assert projection is not None
    assert projection.target_multiple == pytest.approx(1_000.0)
    assert projection.required_horizon_return_fraction == pytest.approx(999.0)
    assert projection.required_monthly_compound_return_fraction == pytest.approx(999.0)
    assert projection.extreme_1000x_target is True
    assert projection.impossible_1000x_one_month_target is True
    assert "not a forecast" in projection.warning
    assert result.status == "NO_GO"
    assert any("1000x target in one month" in item for item in result.blocking_conditions)


def test_five_thousand_x_is_a_configurable_same_currency_scenario_not_an_fx_assumption() -> None:
    result = evaluate_wealth_plan(
        _request(
            goal=_goal(
                starting_amount=200.0,
                target_amount=1_000_000.0,
                currency="MXN",
                horizon_months=120,
            )
        )
    )
    projection = result.goal_projection

    assert projection is not None
    assert projection.currency == "MXN"
    assert projection.target_multiple == pytest.approx(5_000.0)
    assert projection.extreme_1000x_target is True
    assert projection.impossible_1000x_one_month_target is False


def test_contribution_math_reports_time_and_required_contribution_without_a_promise() -> None:
    result = evaluate_wealth_plan(
        _request(
            goal=_goal(
                starting_amount=100.0,
                target_amount=220.0,
                horizon_months=12,
                illustrative_annual_return_fraction=0.0,
                monthly_contribution=10.0,
            )
        )
    )
    projection = result.goal_projection

    assert projection is not None
    assert projection.illustrative_months_to_target == 12
    assert projection.required_monthly_contribution_for_horizon == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_risk_capital_usd", True),
        ("total_risk_capital_usd", float("nan")),
        ("proposed_canary_usd", float("inf")),
        ("minimum_notional_usd", False),
        ("minimum_notional_cushion_fraction", -0.1),
        ("eligible_asset_count", True),
    ],
)
def test_invalid_capital_inputs_fail_closed_and_remain_digestible(
    field: str,
    value: object,
) -> None:
    result = evaluate_wealth_plan(_request(**{field: value}))

    assert result.status == "NO_GO"
    assert len(result.request_digest) == 64
    assert len(result.assessment_digest) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starting_amount", True),
        ("target_amount", float("nan")),
        ("horizon_months", False),
        ("illustrative_annual_return_fraction", float("inf")),
        ("monthly_contribution", -1.0),
        ("currency", "usd"),
    ],
)
def test_invalid_goal_inputs_never_produce_a_projection(field: str, value: object) -> None:
    result = evaluate_wealth_plan(_request(goal=_goal(**{field: value})))

    assert result.status == "NO_GO"
    assert result.goal_projection is None


def test_overflowing_derived_arithmetic_fails_closed() -> None:
    capital = evaluate_wealth_plan(
        _request(minimum_notional_usd=1e308, minimum_notional_cushion_fraction=1e308)
    )
    goal = evaluate_wealth_plan(_request(goal=_goal(starting_amount=5e-324, target_amount=1e308)))

    assert capital.status == "NO_GO"
    assert any("arithmetic" in item for item in capital.blocking_conditions)
    assert goal.status == "NO_GO"
    assert any("arithmetic" in item for item in goal.blocking_conditions)


def test_request_and_result_are_deeply_immutable_and_export_only_copies() -> None:
    result = evaluate_wealth_plan(_request())

    with pytest.raises(FrozenInstanceError):
        result.request.total_risk_capital_usd = 999.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.roadmap[0].action = "route an order"  # type: ignore[misc]

    exported = result.to_dict()
    exported["roadmap"][0]["action"] = "route an order"
    exported["goal_projection"]["target_multiple"] = 1.0
    assert result.roadmap[0].action != "route an order"
    assert result.goal_projection is not None
    assert result.goal_projection.target_multiple == pytest.approx(1.2)


def test_digests_are_canonical_sensitive_and_forgery_is_detected() -> None:
    first = evaluate_wealth_plan(_request())
    repeated = evaluate_wealth_plan(_request())
    changed = evaluate_wealth_plan(_request(goal=_goal(monthly_contribution=1.0)))
    forged = replace(first, status="NO_GO")

    assert first.request_digest == repeated.request_digest
    assert first.assessment_digest == repeated.assessment_digest
    assert first.request_digest != changed.request_digest
    assert first.assessment_digest != changed.assessment_digest
    assert not forged.is_verified()


def test_roadmap_combines_revenue_and_research_without_claiming_either_will_pay() -> None:
    result = evaluate_wealth_plan(_request())

    assert {item.workstream for item in result.roadmap} == {"AUDIT_REVENUE", "H2_RESEARCH"}
    assert all("$" not in item.acceptance for item in result.roadmap)
    assert all("guarante" not in item.action.lower() for item in result.roadmap)
