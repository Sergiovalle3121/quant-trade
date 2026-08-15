from __future__ import annotations

import json

import pytest
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


_REQUIRED_GOAL_OPTIONS = {
    "--goal-starting-amount": "200",
    "--goal-target-amount": "240",
    "--goal-currency": "USD",
    "--horizon-months": "12",
}


def _invoke_without_goal_option(missing_option: str):
    args = [
        "assess",
        "--total-risk-capital-usd",
        "200",
        "--proposed-canary-usd",
        "20",
        "--eligible-asset-count",
        "20",
    ]
    for option, value in _REQUIRED_GOAL_OPTIONS.items():
        if option != missing_option:
            args.extend((option, value))
    return CliRunner().invoke(wealth_app, args, terminal_width=200, color=False)


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


@pytest.mark.parametrize("missing_option", tuple(_REQUIRED_GOAL_OPTIONS))
def test_goal_currency_amounts_and_horizon_are_required_not_guessed(
    missing_option: str,
) -> None:
    result = _invoke_without_goal_option(missing_option)
    assert result.exit_code == 2
    assert f"Missing option '{missing_option}'" in result.output


def test_goal_options_are_documented_as_required() -> None:
    help_result = CliRunner().invoke(
        wealth_app, ["assess", "--help"], terminal_width=200, color=False
    )
    assert help_result.exit_code == 0
    for option in _REQUIRED_GOAL_OPTIONS:
        assert option in help_result.output
