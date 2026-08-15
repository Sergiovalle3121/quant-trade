from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.ops.wealth_cli import wealth_app


def _invoke(total: str, canary: str):
    return CliRunner().invoke(
        wealth_app,
        [
            "assess",
            "--total-risk-capital-usd",
            total,
            "--proposed-canary-usd",
            canary,
            "--eligible-asset-count",
            "20",
            "--goal-starting-amount",
            "200",
            "--goal-target-amount",
            "240",
            "--goal-currency",
            "USD",
            "--horizon-months",
            "12",
        ],
    )


def test_two_hundred_total_is_no_go_and_never_authorizes_money() -> None:
    result = _invoke("200", "20")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "NO_GO"
    assert payload["allowed_canary_usd"] == 20.0
    assert payload["real_money_authorized"] is False
    assert payload["profit_claim_authorized"] is False


def test_two_hundred_canary_requires_two_thousand_total() -> None:
    result = _invoke("2000", "200")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "FEASIBLE"
    assert payload["required_total_risk_capital_usd_for_proposed_canary"] == 2000.0
    assert payload["real_money_authorized"] is False


def test_goal_currency_amounts_and_horizon_are_required_not_guessed() -> None:
    result = CliRunner().invoke(
        wealth_app,
        [
            "assess",
            "--total-risk-capital-usd",
            "200",
            "--proposed-canary-usd",
            "20",
            "--eligible-asset-count",
            "20",
        ],
    )
    assert result.exit_code != 0
    assert "--goal-starting-amount" in result.output
    help_result = CliRunner().invoke(wealth_app, ["assess", "--help"])
    assert help_result.exit_code == 0
    for option in (
        "--goal-starting-amount",
        "--goal-target-amount",
        "--goal-currency",
        "--horizon-months",
    ):
        assert option in help_result.output
