"""Robinhood's Account Activity report: synthetic rows in the column layout
its help centre and open-source importers describe (never a customer file)."""

from __future__ import annotations

import csv
import io

import pytest

from quant_trade.audit import i18n
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import (
    ROBINHOOD_CSV,
    ROBINHOOD_MOVES_WARNING,
    ROBINHOOD_UNOPENED_WARNING,
    detect_format,
    import_report,
)

HEADER = [
    "Activity Date", "Process Date", "Settle Date", "Instrument", "Description", "Trans Code",
    "Quantity", "Price", "Amount",
]  # fmt: skip
DISCLAIMER = ["", "", "", "", "", "", "", "", "The data provided is for informational purposes."]


def _row(day: str, symbol: str, description: str, code: str, quantity: str = "",
         price: str = "", amount: str = "") -> list[str]:  # fmt: skip
    return [day, day, day, symbol, description, code, quantity, price, amount]


def _report(rows: list[list[str]]) -> bytes:
    """Newest first, as Robinhood lists it, with the disclaimer at the end."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerows([HEADER, *reversed(rows), DISCLAIMER])
    return buffer.getvalue().encode()


APPLE = "Apple\nCUSIP: 037833100"
SPY_CALL = "SPY 3/15/2024 Call $500.00"


def _trades(rows: list[list[str]]) -> list[tuple[float, float, float]]:
    report = import_report(_report(rows), "Robinhood.csv")
    return [
        (trade.entry_price, trade.exit_price, round(trade.pnl, 2)) for trade in report.trades.trades
    ]


def _warnings(rows: list[list[str]]) -> list[str]:
    return import_report(_report(rows), "Robinhood.csv").warnings


def test_share_and_option_trades_are_read_and_cash_rows_skipped() -> None:
    rows = [
        _row("3/01/2024", "", "ACH Deposit", "ACH", amount="$5,000.00"),
        _row("3/04/2024", "AAPL", APPLE, "Buy", "10", "$175.10", "($1,751.00)"),
        _row("3/10/2024", "SPY", SPY_CALL, "BTO", "2", "$4.20", "($840.00)"),
        _row("3/12/2024", "SPY", SPY_CALL, "STC", "2", "$6.10", "$1,220.00"),
        _row("3/14/2024", "AAPL", APPLE, "Sell", "10", "$172.50", "$1,725.00"),
        _row(
            "3/15/2024",
            "AAPL",
            "Cash Div: R/D 2024-03-11 - 10 shares at 0.24",
            "CDIV",
            amount="$2.40",
        ),  # fmt: skip
        _row("3/20/2024", "", "Interest Payment", "INT", amount="$0.51"),
    ]
    data = _report(rows)
    assert detect_format(data) == ROBINHOOD_CSV
    report = import_report(data, "Robinhood.csv")
    assert report.source_format == ROBINHOOD_CSV
    # A call is 100 shares a contract: (6.10 - 4.20) x 2 x 100.
    assert _trades(rows) == [(4.2, 6.1, 380.0), (175.1, 172.5, -26.0)]
    assert not any("still open" in warning for warning in report.warnings)


def test_regulatory_fees_are_the_gap_between_cash_and_fill_value() -> None:
    rows = [
        _row("3/04/2024", "SPY", SPY_CALL, "BTO", "1", "$4.20", "($420.03)"),
        _row("3/05/2024", "SPY", SPY_CALL, "STC", "1", "$5.00", "$499.95"),
    ]
    # 80 of premium; the 0.03 and 0.05 of fees are the trade's costs.
    assert _trades(rows) == [(4.2, 5.0, 80.0)]
    assert import_report(_report(rows), "Robinhood.csv").fees["commission"] == pytest.approx(-0.08)


def test_expired_options_close_at_no_premium() -> None:
    long_call = [
        _row("2/10/2024", "SPY", SPY_CALL, "BTO", "1", "$4.20", "($420.00)"),
        _row("3/15/2024", "SPY", f"Option Expiration for {SPY_CALL}", "OEXP", "1"),
    ]
    # The record shows the smallest tick as the exit price; the result is at zero.
    assert _trades(long_call) == [(4.2, 0.01, -420.0)]
    short_put = [
        _row("2/10/2024", "SPY", "SPY 3/15/2024 Put $450.00", "STO", "3", "$1.50", "$450.00"),
        _row(
            "3/15/2024", "SPY", "Option Expiration for SPY 3/15/2024 Put $450.00", "OEXP", "3S"
        ),  # fmt: skip
    ]
    assert _trades(short_put) == [(1.5, 0.01, 450.0)]


def test_a_reverse_split_rescales_the_shares_held() -> None:
    rows = [
        _row("1/05/2026", "AKAN", "Akanda", "Buy", "200", "$1.00", "($200.00)"),
        _row("1/12/2026", "AKAN", "Akanda reverse split", "SPR", "200S"),
        _row("1/12/2026", "AKAN", "Akanda reverse split", "SPR", "40"),
        _row("1/20/2026", "AKAN", "Akanda", "Sell", "40", "$6.00", "$240.00"),
    ]
    assert _trades(rows) == [(5.0, 6.0, 40.0)]
    assert _warnings(rows) == [w for w in _warnings(rows) if "share movement" not in w]


def test_a_symbol_exchange_carries_the_shares_to_the_new_symbol() -> None:
    rows = [
        _row("7/01/2021", "CCIV", "Churchill Capital IV", "Buy", "200", "$20.00", "($4,000.00)"),
        _row("7/26/2021", "CCIV", "Churchill Capital IV", "SXCH", "200S"),
        _row("7/26/2021", "LCID", "Lucid Group", "SXCH", "200"),
        _row("8/02/2021", "LCID", "Lucid Group", "Sell", "200", "$25.00", "$5,000.00"),
    ]
    report = import_report(_report(rows), "Robinhood.csv")
    assert [round(trade.pnl, 2) for trade in report.trades.trades] == [1000.0]


def test_closes_of_positions_opened_before_the_file_are_left_out_and_said() -> None:
    rows = [
        _row("3/04/2024", "AAPL", APPLE, "Buy", "5", "$175.00", "($875.00)"),
        # Ten sold, five of them bought before the file starts: no short is invented.
        _row("3/14/2024", "AAPL", APPLE, "Sell", "10", "$180.00", "$1,800.00"),
        _row("3/15/2024", "SPY", SPY_CALL, "STC", "1", "$6.10", "$610.00"),
        _row("3/18/2024", "MSFT", "Microsoft", "ACATI", "3"),
        _row("3/19/2024", "MSFT", "Microsoft", "Buy", "1", "$400.00", "($400.00)"),
        _row("3/20/2024", "MSFT", "Microsoft", "Sell", "1", "$410.00", "$410.00"),
    ]
    assert _trades(rows) == [(175.0, 180.0, 25.0), (400.0, 410.0, 10.0)]
    warnings = _warnings(rows)
    assert ROBINHOOD_UNOPENED_WARNING.format(n=2) in warnings
    assert ROBINHOOD_MOVES_WARNING.format(n=1) in warnings


def test_a_position_still_open_at_the_end_is_left_out() -> None:
    rows = [
        _row("3/04/2024", "AAPL", APPLE, "Buy", "10", "$175.00", "($1,750.00)"),
        _row("3/05/2024", "AAPL", APPLE, "Sell", "4", "$180.00", "$720.00"),
    ]
    report = import_report(_report(rows), "Robinhood.csv")
    assert [round(trade.pnl, 2) for trade in report.trades.trades] == [20.0]
    assert any("1 position(s) still open" in warning for warning in report.warnings)


@pytest.mark.parametrize("n", [1, 4])
@pytest.mark.parametrize("template", [ROBINHOOD_UNOPENED_WARNING, ROBINHOOD_MOVES_WARNING])
def test_the_new_warnings_read_in_every_language(template: str, n: int) -> None:
    english = template.format(n=n)
    for locale in ("es", "pt"):
        text = i18n.localize(english, locale)
        assert text != english and str(n) in text, (locale, text)
        assert find_claims(text) == []
    assert find_claims(i18n.localize(english, "en")) == []
