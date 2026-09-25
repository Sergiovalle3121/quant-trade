"""Refusal messages that tell the customer what is actually wrong with the file."""

from __future__ import annotations

import pytest

from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.importers import ReportFormatError, import_report
from quant_trade.audit.schema import ParseError, parse_equity_csv

TRADES_HEADER = "Symbol,Open Time,Close Time,Qty,Entry Price,Exit Price,Profit\n"


def _trades(rows: int, *, backwards: bool = False) -> bytes:
    lines = []
    for day in range(1, rows + 1):
        entry, exit_ = f"2026-01-{day:02d} 10:00", f"2026-01-{day:02d} 12:00"
        if backwards:
            entry, exit_ = exit_, entry
        lines.append(f"EURUSD,{entry},{exit_},1,1.1,1.101,1\n")
    return (TRADES_HEADER + "".join(lines)).encode("utf-8")


def _clean(error: ReportFormatError | ParseError) -> None:
    for text in (str(error), error.message_es or ""):
        assert_report_clean(text)


def test_trade_list_in_the_curve_box_is_sent_to_the_report_box() -> None:
    with pytest.raises(ParseError) as info:
        parse_equity_csv(_trades(10), what="equity")
    assert info.value.code == "trade_list_as_curve"
    assert "Your platform report" in str(info.value)
    assert "Informe de tu plataforma" in (info.value.message_es or "")
    _clean(info.value)


def test_a_table_without_dates_that_is_not_a_trade_list_keeps_the_date_message() -> None:
    with pytest.raises(ParseError) as info:
        parse_equity_csv(b"a,b\n1,2\n", what="equity")
    assert info.value.code == "missing_timestamp"


def test_every_exit_before_its_entry_says_so() -> None:
    with pytest.raises(ReportFormatError) as info:
        import_report(_trades(10, backwards=True), "trades.csv")
    assert info.value.code == "exits_before_entries"
    assert "swapped" in str(info.value)
    assert "intercambiadas" in info.value.message_es
    _clean(info.value)


def test_a_few_backwards_rows_are_still_dropped_quietly() -> None:
    data = _trades(10) + b"EURUSD,2026-02-02 12:00,2026-02-02 10:00,1,1.1,1.101,1\n"
    report = import_report(data, "trades.csv")
    assert len(report.symbols) == 10
    assert any("dropped" in warning for warning in report.warnings)


def test_fills_that_never_close_count_the_open_positions() -> None:
    data = (
        b"Time,Symbol,Side,Quantity,Price\n"
        b"2026-01-02 10:00,AAPL,Buy,10,190\n"
        b"2026-01-03 10:00,MSFT,Buy,5,410\n"
        b"2026-01-04 10:00,AAPL,Buy,10,191\n"
    )
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "fills.csv")
    assert info.value.code == "no_closed_trades"
    assert "2 position(s) opened and never closed" in str(info.value)
    assert "2 posición(es) se abrieron y no se cerraron" in info.value.message_es
    _clean(info.value)
