"""Daily quantity needs a monetary curve tied to the uploaded trade sizes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from quant_trade.audit.engine import LADDER_FLOWS, LADDER_NOT_SHOWN_WHY, run_audit
from quant_trade.audit.sample import _sample_report, synthetic_live_statement
from quant_trade.audit.schema import AuditInputs, AuditResult, DeclaredMetadata, build_inputs

NOW = datetime(2026, 10, 11, tzinfo=UTC)
KEY = "ftmo-2step-phase1"


def _inputs(report: bytes, filename: str) -> AuditInputs:
    return build_inputs(
        None,
        DeclaredMetadata(challenge=KEY),
        report_bytes=report,
        report_filename=filename,
        now=NOW,
    )


def _audit(inputs: AuditInputs) -> AuditResult:
    return run_audit(
        inputs,
        now=NOW,
        bootstrap_samples=20,
        risk_samples=20,
        challenge_samples=100,
    )


def test_flow_adjusted_index_cannot_measure_money_loss_per_quantity() -> None:
    inputs = _inputs(synthetic_live_statement(), "SyntheticSampleLive.csv")
    assert inputs.cash_flows
    result = _audit(inputs)
    assert result.challenge is not None
    sizing = result.challenge["sizing"]
    assert sizing["status"] == "MEASURED" and len(sizing["rows"]) == 4
    daily = sizing["daily_limit"]
    assert daily["status"] == "NOT_MEASURED"
    assert daily["reason"] == LADDER_FLOWS
    assert "quantity" not in daily


def test_unreconciled_separate_curve_cannot_measure_quantity_from_trades() -> None:
    inputs = _inputs(_sample_report(), "SyntheticSampleEA.html")
    frame = inputs.equity.frame.copy()
    frame["equity"] *= 2
    inputs = replace(inputs, equity=replace(inputs.equity, frame=frame), balance_only=False)
    result = _audit(inputs)
    assert result.challenge is not None
    daily = result.challenge["sizing"]["daily_limit"]
    assert daily["status"] == "NOT_MEASURED"
    assert daily["reason"] == LADDER_NOT_SHOWN_WHY.format(
        why="flows, currency conversion or open positions could explain the difference"
    )
    assert "quantity" not in daily


def test_reconstructed_money_curve_retains_its_original_lot_measurement() -> None:
    inputs = _inputs(_sample_report(), "SyntheticSampleEA.html")
    result = _audit(inputs)
    assert result.challenge is not None
    daily = result.challenge["sizing"]["daily_limit"]
    assert daily["status"] == "MEASURED"
    assert daily["unit"] == "lot"
    assert daily["quantity_profile"]["median"]["value"] == pytest.approx(0.5)
    assert daily["quantity"]["evidence"] == "MEASURED"


def test_assumed_balance_cannot_measure_copy_fall_or_capital_quantity() -> None:
    lines = ["Symbol,Side,Lots,Entry Time,Exit Time,Entry Price,Exit Price,Profit"]
    for index in range(60):
        day = datetime(2024, 1, 1) + timedelta(days=2 * index)
        profit = 40 if index % 2 == 0 else -20
        lines.append(
            f"EURUSD,Buy,2,{day:%Y-%m-%d} 09:00,{day:%Y-%m-%d} 10:00,"
            f"100,{100 + profit / 2},{profit}"
        )
    inputs = _inputs(("\n".join(lines) + "\n").encode(), "UnknownBalance.csv")
    assert inputs.initial_balance == 10_000
    assert any("starting balance; 10,000 was assumed" in note for note in inputs.warnings)
    result = _audit(inputs)
    assert result.capital is not None
    assert result.capital["status"] == "MEASURED"
    assert result.capital["fall_reference"]["evidence"] == "MEASURED"
    assert result.capital["starting_balance"]["evidence"] == "NOT_MEASURED"
    assert all(row["quantity"]["evidence"] == "NOT_MEASURED" for row in result.capital["rows"])
    assert all(row["fall_pct"]["evidence"] == "NOT_MEASURED" for row in result.capital["copy_rows"])


def test_detected_martingale_withholds_capital_and_challenge_lots() -> None:
    rows = [
        "<html><head><title>Strategy Tester: Synthetic sizing</title></head><body><table>",
        "<tr><td>Symbol</td><td>EURUSD</td></tr>",
        "<tr><td>Initial deposit</td><td>10000</td></tr>",
    ]
    balance = 10_000.0
    for index in range(60):
        day = datetime(2024, 1, 1) + timedelta(days=2 * index)
        # After each loss the next trade doubles; a win resets the size.
        lots = 0.5 if index % 2 == 0 else 1.0
        profit = -100.0 if index % 2 == 0 else 160.0
        exit_price = 1.1 + profit / (lots * 100_000)
        balance += profit
        rows.extend(
            [
                f"<tr><td>{2 * index + 1}</td><td>{day:%Y.%m.%d} 09:00</td>"
                f"<td>buy</td><td>{index + 1}</td><td>{lots}</td><td>1.10000</td>"
                "<td>0</td><td>0</td><td></td><td></td></tr>",
                f"<tr><td>{2 * index + 2}</td><td>{day:%Y.%m.%d} 10:00</td>"
                f"<td>close</td><td>{index + 1}</td><td>{lots}</td>"
                f"<td>{exit_price:.5f}</td><td>0</td><td>0</td>"
                f"<td>{profit}</td><td>{balance}</td></tr>",
            ]
        )
    inputs = _inputs("".join([*rows, "</table></body></html>"]).encode(), "SyntheticSizing.htm")
    assert inputs.quantity_unit == "lot"
    assert inputs.trade_quantities == inputs.trade_lots == [0.5, 1.0] * 30
    result = _audit(inputs)
    assert "MARTINGALE_SIZING" in {flag["code"] for flag in result.red_flags}
    # The importer did establish lots; withholding is due to the detected pattern.
    assert result.costs["break_even_per_lot"]["evidence"] == "MEASURED"
    assert result.capital is not None and result.capital["status"] == "MEASURED"
    assert result.capital["quantity_profile"]["median"]["evidence"] == "NOT_MEASURED"
    assert all(row["quantity"]["evidence"] == "NOT_MEASURED" for row in result.capital["rows"])
    assert result.challenge is not None
    sizing = result.challenge["sizing"]
    assert sizing["size_per_trade"]["evidence"] == "NOT_MEASURED"
    assert "size grows after losses" in sizing["size_per_trade"]["note"]
    assert all("average_lot" not in row for row in sizing["rows"])
    assert sizing["daily_limit"]["status"] == "NOT_MEASURED"
    assert "size grows after losses" in sizing["daily_limit"]["reason"]
    assert "quantity" not in sizing["daily_limit"]
