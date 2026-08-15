"""CLI for transparent, non-authorizing wealth-plan arithmetic."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from quant_trade.ops.growth_feasibility import (
    TargetFeasibilityRequest,
    evaluate_target_feasibility,
)
from quant_trade.ops.wealth_plan import GrowthGoal, WealthPlanRequest, evaluate_wealth_plan

wealth_app = typer.Typer(
    help="Evaluate small-capital constraints and illustrative goal arithmetic."
)


@wealth_app.callback()
def wealth_root() -> None:
    """Keep wealth calculations under explicit, non-actioning subcommands."""


@wealth_app.command("assess")
def assess_wealth_plan(
    total_risk_capital_usd: Annotated[
        float, typer.Option(help="Total capital explicitly affordable as a complete loss.")
    ],
    proposed_canary_usd: Annotated[
        float, typer.Option(help="Proposed research canary, not a deposit authorization.")
    ],
    eligible_asset_count: Annotated[
        int, typer.Option(help="Distinct instruments supported by supplied evidence.")
    ],
    goal_starting_amount: Annotated[
        float, typer.Option(help="Goal starting amount, in --goal-currency.")
    ],
    goal_target_amount: Annotated[
        float, typer.Option(help="Goal target amount, in --goal-currency.")
    ],
    goal_currency: Annotated[
        str, typer.Option(help="Explicit same-currency code; no FX rate is assumed.")
    ],
    horizon_months: Annotated[int, typer.Option(help="Illustrative goal horizon.")],
    minimum_notional_usd: Annotated[
        float, typer.Option(help="Observed minimum order notional assumption in USD.")
    ] = 5.0,
    minimum_notional_cushion_fraction: Annotated[
        float, typer.Option(help="Additional fraction reserved over the minimum notional.")
    ] = 0.20,
    illustrative_annual_return_fraction: Annotated[
        float, typer.Option(help="Scenario assumption only, never a return forecast.")
    ] = 0.0,
    monthly_contribution: Annotated[
        float, typer.Option(help="Same-currency contribution at each month end.")
    ] = 0.0,
) -> None:
    """Print a fail-closed assessment; never route money or establish expected profit."""
    result = evaluate_wealth_plan(
        WealthPlanRequest(
            total_risk_capital_usd=total_risk_capital_usd,
            proposed_canary_usd=proposed_canary_usd,
            eligible_asset_count=eligible_asset_count,
            minimum_notional_usd=minimum_notional_usd,
            minimum_notional_cushion_fraction=minimum_notional_cushion_fraction,
            goal=GrowthGoal(
                starting_amount=goal_starting_amount,
                target_amount=goal_target_amount,
                currency=goal_currency,
                horizon_months=horizon_months,
                illustrative_annual_return_fraction=illustrative_annual_return_fraction,
                monthly_contribution=monthly_contribution,
            ),
        )
    )
    typer.echo(json.dumps(result.to_dict(), sort_keys=True))


@wealth_app.command("target-feasibility")
def assess_target_feasibility(
    start: Annotated[
        float, typer.Option(help="Starting capital in USD, treated as a real constraint.")
    ],
    target: Annotated[float, typer.Option(help="Target capital in USD.")],
    days: Annotated[int, typer.Option(help="Horizon length, in --basis days.")],
    basis: Annotated[
        str, typer.Option(help="CALENDAR or TRADING; decides days per year.")
    ] = "CALENDAR",
    sharpe: Annotated[
        float, typer.Option(help="Assumed net-of-cost Sharpe. An assumption, never a measurement.")
    ] = 0.0,
    volatility: Annotated[
        float, typer.Option(help="Assumed annual volatility as a fraction, e.g. 0.30.")
    ] = 0.30,
    kelly_fraction: Annotated[
        float, typer.Option(help="Fraction of the growth-optimal long position.")
    ] = 0.5,
    annual_round_trips: Annotated[
        float, typer.Option(help="Full position rotations per year.")
    ] = 0.0,
    round_trip_cost_bps: Annotated[
        float, typer.Option(help="All-in cost of one round trip, in basis points.")
    ] = 0.0,
    monthly_fixed_cost_usd: Annotated[
        float, typer.Option(help="Data and tooling paid monthly regardless of activity.")
    ] = 0.0,
) -> None:
    """Print whether a target is reachable under declared assumptions.

    Reports the required compound return, the volatility that maximises the
    chance of success, the ceiling on that chance, and the Sharpe each ceiling
    would demand.  It never establishes expected profit or authorises money.
    """
    result = evaluate_target_feasibility(
        TargetFeasibilityRequest(
            starting_capital_usd=start,
            target_capital_usd=target,
            horizon_days=days,
            horizon_basis=basis,
            assumed_net_sharpe=sharpe,
            assumed_annual_volatility=volatility,
            kelly_fraction=kelly_fraction,
            annual_round_trips=annual_round_trips,
            round_trip_cost_bps=round_trip_cost_bps,
            monthly_fixed_cost_usd=monthly_fixed_cost_usd,
        )
    )
    typer.echo(json.dumps(result.to_dict(), sort_keys=True))


__all__ = ["wealth_app"]
