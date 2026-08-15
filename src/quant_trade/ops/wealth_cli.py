"""CLI for transparent, non-authorizing wealth-plan arithmetic."""

from __future__ import annotations

import json
from typing import Annotated

import typer

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


__all__ = ["wealth_app"]
