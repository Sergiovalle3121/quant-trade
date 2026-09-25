"""The money of a real account: deposits, withdrawals and open positions.

A synthetic MetaTrader 4 statement reproduces the pattern investors are
warned about: a small account doubles, falls back, receives a large deposit
in the drawdown and then loses money, while its time-weighted percentage
still reads as a gain. Every test is offline and deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from quant_trade.audit.account import FLOATING_FAIL, account_review
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import MT4_STATEMENT_HTML, MT5_TESTER_HTML, import_report
from quant_trade.audit.report import render
from quant_trade.audit.schema import DeclaredMetadata, ParsedTrades, build_inputs
from quant_trade.core.models import Trade

START = datetime(2024, 3, 4, 9, 0, tzinfo=UTC)


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y.%m.%d %H:%M:%S")


def _statement(events: list[tuple[str, float]], *, floating: float, balance: float) -> bytes:
    """An MT4 statement: ``("deposit", amount)`` or ``("trade", profit)`` rows."""
    rows = []
    day = START
    ticket = 1000
    for kind, amount in events:
        ticket += 1
        if kind == "deposit":
            label = "Deposit" if amount > 0 else "Withdrawal"
            rows.append(
                f"<tr align=right><td title='{label}'>{ticket}</td><td class=msdate nowrap>"
                f"{_stamp(day)}</td><td>balance</td><td colspan=10 align=left>{label}</td>"
                f"<td class=mspt>{_money(amount)}</td></tr>"
            )
        else:
            close = 1.08 + amount / 100_000
            rows.append(
                f"<tr align=right><td>{ticket}</td><td class=msdate nowrap>{_stamp(day)}</td>"
                "<td>buy</td><td class=mspt>1.00</td><td>eurusd</td><td>1.08000</td>"
                "<td>0.00000</td><td>0.00000</td><td class=msdate nowrap>"
                f"{_stamp(day + timedelta(hours=3))}</td><td>{close:.5f}</td>"
                "<td class=mspt>0.00</td><td class=mspt>0.00</td><td class=mspt>0.00</td>"
                f"<td class=mspt>{_money(amount)}</td></tr>"
            )
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    closed = sum(amount for kind, amount in events if kind == "trade")
    html = (
        "<html><head><title>Statement: 1 - Trader</title></head><body><table>"
        "<tr align=left><td colspan=2><b>Account: 1</b></td><td colspan=2><b>Currency: USD"
        "</b></td></tr><tr align=left><td colspan=13><b>Closed Transactions:</b></td></tr>"
        "<tr align=center><td>Ticket</td><td nowrap>Open Time</td><td>Type</td><td>Size</td>"
        "<td>Item</td><td>Price</td><td>S / L</td><td>T / P</td><td nowrap>Close Time</td>"
        "<td>Price</td><td>Commission</td><td>Taxes</td><td>Swap</td><td>Profit</td></tr>"
        + "".join(rows)
        + "<tr align=right><td colspan=12 align=right><b>Closed P/L:</b></td>"
        f"<td colspan=2 align=right class=mspt><b>{_money(closed)}</b></td></tr>"
        "<tr align=left><td colspan=14><b>Summary:</b></td></tr>"
        "<tr align=right><td colspan=2><b>Closed Trade P/L:</b></td><td colspan=2 class=mspt>"
        f"<b>{_money(closed)}</b></td><td colspan=4><b>Floating P/L:</b></td><td class=mspt>"
        f"<b>{_money(floating)}</b></td></tr>"
        "<tr align=right><td colspan=2><b>Balance:</b></td><td colspan=2 class=mspt>"
        f"<b>{_money(balance)}</b></td><td colspan=4><b>Equity:</b></td><td class=mspt>"
        f"<b>{_money(balance + floating)}</b></td></tr></table></body></html>"
    )
    return html.encode("utf-8")


#: 1 000 doubles, falls back 25 %, receives 20 000 and then loses 1 000.
TOPPED_UP = [
    ("deposit", 1_000.0),
    *[("trade", 100.0)] * 10,
    ("trade", -500.0),
    ("deposit", 20_000.0),
    ("trade", -1_000.0),
]


def _audit(data: bytes, locale: str = "es"):  # type: ignore[no-untyped-def]
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale=locale),
        report_bytes=data,
        report_filename="statement.htm",
    )
    return run_audit(inputs, bootstrap_samples=200)


def test_importer_lists_every_deposit_and_withdrawal() -> None:
    imported = import_report(
        _statement([*TOPPED_UP, ("deposit", -300.0)], floating=0.0, balance=19_200.0),
        "statement.htm",
    )
    assert imported.source_format == MT4_STATEMENT_HTML
    assert [amount for _, amount in imported.cash_flows] == [1_000.0, 20_000.0, -300.0]


def test_topped_up_account_shows_the_gap_between_percentage_and_money() -> None:
    result = _audit(_statement(TOPPED_UP, floating=-3_000.0, balance=19_500.0))
    account = result.account
    assert account is not None and account["status"] == "MEASURED"
    assert account["deposits"]["total"]["value"] == pytest.approx(21_000.0)
    assert account["trading_result"]["value"] == pytest.approx(-500.0)
    assert account["percent_gain"]["value"] > 0.3
    assert account["result_on_deposits"]["evidence"] == "MEASURED"
    assert account["top_ups"]["value"] == 1
    deposit = account["deposit_list"][0]
    assert deposit["amount"]["value"] == pytest.approx(20_000.0)
    assert deposit["balance_before"]["value"] == pytest.approx(1_500.0)
    assert deposit["drawdown"]["value"] == pytest.approx(-0.25)
    assert account["floating_pnl"]["evidence"] == "DECLARED"
    assert account["clean"] is False
    severities = {flag["code"]: flag["severity"] for flag in result.red_flags}
    assert severities["GAIN_INFLATED_BY_FLOWS"] == "WARN"
    assert severities["DEPOSIT_DURING_DRAWDOWN"] == "WARN"
    assert severities["FLOATING_LOSS_AT_END"] == "WARN"
    codes = {question["code"] for question in result.vendor_questions}
    assert {"deposits", "open_positions"} <= codes


@pytest.mark.parametrize("locale", ["es", "en"])
def test_account_section_renders_clean_in_both_languages(locale: str) -> None:
    result = _audit(_statement(TOPPED_UP, floating=-3_000.0, balance=19_500.0), locale)
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert ("dinero real de la cuenta" if locale == "es" else "real money") in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_steady_account_raises_no_account_flag() -> None:
    events = [("deposit", 10_000.0), *[("trade", 50.0), ("trade", -20.0)] * 12]
    result = _audit(_statement(events, floating=0.0, balance=10_360.0))
    assert result.account is not None and result.account["clean"] is True
    codes = {flag["code"] for flag in result.red_flags}
    assert not codes & {"GAIN_INFLATED_BY_FLOWS", "DEPOSIT_DURING_DRAWDOWN", "FLOATING_LOSS_AT_END"}


def _trades(profits: list[float]) -> ParsedTrades:
    trades = [
        Trade(
            entry_time=START + timedelta(days=i),
            exit_time=START + timedelta(days=i, hours=2),
            quantity=1.0,
            entry_price=100.0,
            exit_price=100.0 + profit,
            pnl=profit,
            return_pct=profit / 100.0,
        )
        for i, profit in enumerate(profits)
    ]
    return ParsedTrades(
        trades=trades, sides=["long"] * len(trades), client_pnl=list(profits), invalid_rows=0
    )


def _frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(days=i - 1) for i in range(len(values))],
            "equity": values,
        }
    )


def test_large_floating_loss_is_serious() -> None:
    _, flags = account_review(
        source_format=MT4_STATEMENT_HTML,
        cash_flows=[(START - timedelta(days=1), 10_000.0)],
        trades=_trades([10.0, 20.0]),
        frame=_frame([10_000.0, 10_010.0, 10_030.0]),
        metadata={
            "declared_floating_pnl": f"{-(FLOATING_FAIL + 0.05) * 10_030:.2f}",
            "declared_balance": "10 030.00",
        },
    )
    assert [(flag.code, flag.severity) for flag in flags] == [("FLOATING_LOSS_AT_END", "FAIL")]


def test_backtest_is_not_an_account_history() -> None:
    review, flags = account_review(
        source_format=MT5_TESTER_HTML,
        cash_flows=[(START, 10_000.0)],
        trades=_trades([10.0]),
        frame=_frame([10_000.0, 10_010.0]),
        metadata={},
    )
    assert review["status"] == "NOT_MEASURED" and flags == []
