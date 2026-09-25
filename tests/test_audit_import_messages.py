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
    assert "2 positions opened and never closed" in str(info.value)
    assert "2 posiciones se abrieron y no se cerraron" in info.value.message_es
    assert "universal" not in str(info.value) + info.value.message_es
    _clean(info.value)


def test_one_position_never_closed_is_singular() -> None:
    data = b"Time,Symbol,Side,Quantity,Price\n2026-01-02 10:00,AAPL,Buy,10,190\n"
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "fills.csv")
    assert "1 position opened and never closed" in str(info.value)
    assert "1 posición se abrió y no se cerró" in info.value.message_es


def test_fill_list_in_the_curve_box_is_sent_to_the_report_box() -> None:
    data = (
        b"Time,Symbol,Side,Quantity,Price\n"
        b"2026-01-02 10:00,AAPL,Buy,10,190\n"
        b"2026-01-03 10:00,AAPL,Sell,10,191\n"
    )
    with pytest.raises(ParseError) as info:
        parse_equity_csv(data, what="equity")
    assert info.value.code == "trade_list_as_curve"


@pytest.mark.parametrize(
    ("role", "english", "spanish"),
    [
        ("quantity", "as quantity holds no numbers", "como cantidad no tiene números"),
        ("entry_time", "as entry time holds no dates", "como hora de entrada no tiene fechas"),
    ],
)
def test_a_text_column_mapped_to_a_number_or_time_is_named(
    role: str, english: str, spanish: str
) -> None:
    columns = {
        "entry_time": "Open Time",
        "exit_time": "Close Time",
        "quantity": "Qty",
        "entry_price": "Entry Price",
        "exit_price": "Exit Price",
    }
    columns[role] = "Notiz"
    data = (TRADES_HEADER.rstrip("\n") + ",Notiz\n").encode() + b"".join(
        line + b",hello\n" for line in _trades(5).splitlines()[1:]
    )
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "trades.csv", columns=columns)
    assert info.value.code == "universal_column_unreadable"
    assert f'"Notiz" you chose {english}' in str(info.value)
    assert f"«Notiz» que elegiste {spanish}" in info.value.message_es
    _clean(info.value)


@pytest.mark.parametrize("price", ["0", "-1.1"])
def test_zero_or_negative_prices_say_so(price: str) -> None:
    data = _trades(5).replace(b",1.1,", f",{price},".encode())
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "trades.csv")
    assert "positive prices and volume" in str(info.value)
    assert "precio y volumen positivos" in info.value.message_es


def test_zero_price_fills_say_so() -> None:
    data = (
        b"Time,Symbol,Side,Quantity,Price\n"
        b"2026-01-02 10:00,AAPL,Buy,10,0\n"
        b"2026-01-03 10:00,AAPL,Sell,10,0\n"
    )
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "fills.csv")
    assert "precio y volumen positivos" in info.value.message_es


def test_two_exports_pasted_together_count_each_position_once() -> None:
    from test_audit_platform_catalog import XTB_HEADER, XTB_ROWS

    lines = [",".join(str(cell) for cell in row) for row in XTB_ROWS]
    data = "\n".join([XTB_HEADER, *lines, *lines]) + "\n"
    report = import_report(data.encode(), "xtb.csv", initial_balance=25_000)
    assert len(report.symbols) == 3
    assert "3 repeated row(s) (the same position listed twice) counted once" in report.warnings


def test_partial_closes_sharing_a_position_id_are_all_kept() -> None:
    from test_audit_platform_catalog import XTB_HEADER, XTB_ROWS

    first = [str(cell) for cell in XTB_ROWS[0]]
    second = list(first)
    second[6], second[7], second[18] = "15/03/2026 16:00:00", "211", "110.0"
    data = "\n".join([XTB_HEADER, ",".join(first), ",".join(second)]) + "\n"
    report = import_report(data.encode(), "xtb.csv", initial_balance=25_000)
    assert len(report.symbols) == 2
    assert not any("repeated" in warning for warning in report.warnings)


def test_identical_fills_without_an_id_are_real_and_kept() -> None:
    data = (
        b"Time,Symbol,Side,Quantity,Price\n"
        b"2026-01-02 10:00,AAPL,Buy,10,190\n"
        b"2026-01-02 10:00,AAPL,Buy,10,190\n"
        b"2026-01-03 10:00,AAPL,Sell,20,191\n"
    )
    report = import_report(data, "fills.csv", initial_balance=25_000)
    assert sum(t.quantity for t in report.trades.trades) == 20
    assert not any("repeated" in warning for warning in report.warnings)


def test_a_named_format_drops_repeated_rows_too() -> None:
    from test_audit_importers import fixture

    text = fixture("ninjatrader.csv").decode()
    header, *rows = text.splitlines()
    once = import_report(text.encode(), "ninjatrader.csv")
    twice = import_report("\n".join([header, *rows, *rows]).encode(), "ninjatrader.csv")
    assert len(twice.trades.trades) == len(once.trades.trades)
    assert any("counted once" in warning for warning in twice.warnings)


@pytest.mark.parametrize("order_column", ["Order ID", "Order", "Orden", "ID"])
def test_two_identical_partial_fills_of_one_order_are_both_kept(order_column: str) -> None:
    data = (
        f"Time,Symbol,Side,Quantity,Price,{order_column}\n"
        "2026-03-02 10:00:00,ES,Buy,1,5000,A1\n"
        "2026-03-02 10:00:00,ES,Buy,1,5000,A1\n"
        "2026-03-02 11:00:00,ES,Sell,2,5010,B7\n"
    ).encode()
    report = import_report(data, "fills.csv", initial_balance=25_000)
    assert sum(t.quantity for t in report.trades.trades) == 2
    assert not any("repeated" in w or "still open" in w for w in report.warnings)


def test_rows_with_a_blank_id_are_never_dropped() -> None:
    from test_audit_platform_catalog import XTB_HEADER, XTB_ROWS

    line = ",".join(str(cell) for cell in ["", *XTB_ROWS[2][1:]])
    data = "\n".join([XTB_HEADER, line, line]) + "\n"
    report = import_report(data.encode(), "xtb.csv", initial_balance=25_000)
    assert len(report.symbols) == 2
    assert not any("repeated" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    ("name", "minutes"),
    [
        ("Time(UTC+530)", 330),
        ("Time (UTC+05:30)", 330),
        ("Time (GMT-3)", -180),
        ("Time (UTC+14)", 840),
        ("Time (UTC+99)", None),
        ("Time (UTC-13)", None),
        ("Time (UTC+0575)", None),
    ],
)
def test_a_zone_in_the_column_name_must_be_one_a_clock_uses(name: str, minutes: int | None) -> None:
    from quant_trade.audit.universal import header_zone

    assert header_zone(name) == minutes


def test_an_impossible_zone_in_the_column_name_keeps_the_no_timezone_warning() -> None:
    data = (
        b"Time (UTC+99),Symbol,Side,Quantity,Price\n"
        b"2026-03-02 10:00,ES,Buy,1,5000\n"
        b"2026-03-02 11:00,ES,Sell,1,5010\n"
    )
    report = import_report(data, "fills.csv", initial_balance=25_000)
    assert report.trades.trades[0].entry_time.hour == 10
    assert any("no timezone" in warning for warning in report.warnings)


def test_a_blank_clock_next_to_its_date_keeps_the_row_at_midnight() -> None:
    data = (
        b"Date,Time,Product,Quantity,Price,Order ID\n"
        b"15-03-2026,,APPLE INC,10,190,a1\n"
        b"16-03-2026,15:30,APPLE INC,-10,195,b2\n"
    )
    report = import_report(data, "Transactions.csv", initial_balance=25_000)
    assert [t.pnl for t in report.trades.trades] == [50.0]
    assert report.trades.trades[0].entry_time.hour == 0


def test_a_fill_with_an_unreadable_time_names_the_trade_it_breaks() -> None:
    from quant_trade.audit.i18n import spanish

    data = (
        b"Time,Symbol,Side,Quantity,Price\n"
        b"2026-03-02 10:00,ES,Buy,1,5000\n"
        b"2026-03-02 11:00,ES,Sell,1,4990\n"
        b"2026-13-45 10:00,NQ,Buy,1,20000\n"
        b"2026-03-04 11:00,NQ,Sell,1,19500\n"
    )
    report = import_report(data, "fills.csv", initial_balance=25_000)
    line = (
        "NQ: a fill with an unreadable time (2026-13-45 10:00) was left out; the trade it "
        "opened or closed is missing from the results"
    )
    assert line in report.warnings
    assert spanish(line) == (
        "NQ: se dejó fuera una ejecución con hora ilegible (2026-13-45 10:00); la operación "
        "que abrió o cerró falta en los resultados"
    )


def test_trades_with_unreadable_times_are_named_then_counted() -> None:
    from quant_trade.audit.i18n import spanish

    bad = b"".join(
        f"EURUSD,never,2026-02-{day:02d} 12:00,1,1.1,1.101\n".encode() for day in range(1, 8)
    )
    report = import_report(_trades(5) + bad, "trades.csv", initial_balance=25_000)
    named = [w for w in report.warnings if w.startswith("EURUSD: a trade with an unreadable time")]
    assert len(named) == 5
    assert "(never)" in named[0]
    assert "2 more row(s) with an unreadable time were left out" in report.warnings
    assert spanish("1 more row(s) with an unreadable time were left out") == (
        "se dejó fuera 1 fila más con hora ilegible"
    )
    for warning in report.warnings:
        assert_report_clean(warning)
