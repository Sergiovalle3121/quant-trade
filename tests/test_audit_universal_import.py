"""Any trade or fill list: columns recognised by name, or mapped by the customer.

Every file here is synthetic. Column names follow the publicly documented
tables or exports of common brokers, exchanges and journals; the rows are made up.
"""

from __future__ import annotations

import pytest
from test_audit_importers import fixture, xlsx

from quant_trade.audit import errors_pt
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import (
    NINJATRADER_EXECUTIONS_CSV,
    UNIVERSAL_FILLS_CSV,
    UNIVERSAL_TRADES_CSV,
    ReportFormatError,
    detect_format,
    import_report,
)
from quant_trade.audit.universal import guess_columns, normalise


def _net(report) -> list[float]:  # type: ignore[no-untyped-def]
    fees = report.trades.fees or [0.0] * len(report.trades.trades)
    return [round(t.pnl - f, 2) for t, f in zip(report.trades.trades, fees, strict=True)]


def _clean(report) -> None:  # type: ignore[no-untyped-def]
    assert untranslated({"inputs": {"parse_warnings": report.warnings}}) == []
    assert all(find_claims(warning) == [] for warning in report.warnings)


def _trades_csv(rows: int = 12) -> bytes:
    lines = ["Symbol,Open Time,Close Time,Type,Lots,Open Price,Close Price,Commission,Swap,Profit"]
    for i in range(rows):
        side = "Buy" if i % 2 == 0 else "Sell"
        move = 0.0020 if i % 3 else -0.0010
        entry = 1.1000
        exit_ = entry + move if side == "Buy" else entry - move
        profit = round(move * 100_000 * 0.5, 2)
        lines.append(
            f"EURUSD,2026-03-{i + 2:02d} 09:00:00,2026-03-{i + 2:02d} 15:30:00,{side},0.5,"
            f"{entry:.5f},{exit_:.5f},-3.50,-0.40,{profit:.2f}"
        )
    return ("\n".join(lines) + "\n").encode()


def test_a_trade_list_from_an_unlisted_platform_is_read_by_its_column_names() -> None:
    data = _trades_csv()
    assert detect_format(data) == UNIVERSAL_TRADES_CSV
    report = import_report(data, "export.csv", initial_balance=5_000)
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert len(report.trades.trades) == 12
    assert report.trades.sides[:2] == ["long", "short"]
    # Profit is gross (the moves explain it exactly); commission and swap are costs.
    assert report.fees == {"commission": pytest.approx(-42.0), "swap": pytest.approx(-4.8)}
    assert _net(report)[0] == round(-50.0 - 3.5 - 0.4, 2)
    assert report.metadata["column_entry_time"] == "Open Time"
    assert report.metadata["column_quantity"] == "Lots"
    assert report.initial_balance == 5_000
    _clean(report)


def test_ctrader_history_needs_an_explicit_monetary_result_column() -> None:
    data = fixture("ctrader_history_columns.csv")
    header = data.decode().splitlines()[0].split(",")
    columns = guess_columns(header)
    assert columns["quantity"] == header.index("Closing quantity")
    assert columns["side"] == header.index("Opening direction")
    assert "profit" not in columns
    # The guide's safe preparation step: rename the account-currency gross
    # result in a copy, preserving separate commissions and signed swaps.
    prepared = data.replace(b"Gross (currency)", b"profit", 1)
    report = import_report(prepared, "ctrader_universal.csv", initial_balance=10_000)
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert _net(report) == [48.5, -51.25, -10.5]
    assert report.metadata["column_profit"] == "profit"
    assert not any("no profit column" in warning for warning in report.warnings)
    _clean(report)


def _ctrader_with_status(*statuses: str) -> bytes:
    # Status is documented in Deal info, not as a promised Statement header.
    lines = fixture("ctrader_history_columns.csv").decode().splitlines()
    rows = [f"{row},{status}" for row, status in zip(lines[1:], statuses, strict=True)]
    return ("\n".join([f"{lines[0]},Status", *rows]) + "\n").encode()


#: The statuses the History page documents as attempts with no execution.
UNEXECUTED = ["Rejected", "Error", "Missed", "Internally rejected"]


@pytest.mark.parametrize("status", [*UNEXECUTED, "rejected", " Missed "])
def test_ctrader_unexecuted_deals_do_not_become_closed_trades(status: str) -> None:
    report = import_report(
        _ctrader_with_status("Filled", status, "Filled"),
        columns={"profit": "Gross (currency)"},
        initial_balance=10_000,
    )
    # The excluded row is otherwise numerically complete and has a loss.
    assert _net(report) == [48.5, -10.5]
    assert report.metadata["excluded_unfilled_deals"] == "1"
    assert any("without a filled status excluded" in warning for warning in report.warnings)
    _clean(report)


@pytest.mark.parametrize("status", ["", "Unknown", "Executed", "Closed"])
def test_ctrader_statuses_the_help_does_not_document_exclude_nothing(status: str) -> None:
    # A vocabulary the page does not document says nothing about execution:
    # every deal stays, as it did before the Status column was read at all.
    report = import_report(
        _ctrader_with_status(status, status, status),
        columns={"profit": "Gross (currency)"},
        initial_balance=10_000,
    )
    assert _net(report) == [48.5, -51.25, -10.5]
    assert "excluded_unfilled_deals" not in report.metadata
    assert not any("status" in warning for warning in report.warnings)
    _clean(report)


def test_ctrader_totals_row_and_repeated_header_are_not_unexecuted_deals() -> None:
    # Neither row is a deal: the totals row and the repeated header go through
    # ``without_totals`` and ``drop_repeated_rows``, not through the status count.
    lines = _ctrader_with_status("Filled", "Filled", "Filled").decode().splitlines()
    totals = "Total,,,,,,,,0.60,-3.00,-0.25,-10.00,-13.25,"
    data = ("\n".join([*lines, totals, lines[0]]) + "\n").encode()
    report = import_report(data, columns={"profit": "Gross (currency)"}, initial_balance=10_000)
    assert _net(report) == [48.5, -51.25, -10.5]
    assert "excluded_unfilled_deals" not in report.metadata
    assert not any("without a filled status" in warning for warning in report.warnings)
    _clean(report)


def test_ctrader_partially_filled_deals_keep_the_documented_closing_quantity() -> None:
    report = import_report(
        _ctrader_with_status("Filled", "Partially filled", "Filled"),
        columns={"profit": "Gross (currency)"},
    )
    assert [trade.quantity for trade in report.trades.trades] == [25_000, 25_000, 10_000]
    assert report.metadata["column_quantity"] == "Closing quantity"
    assert _net(report) == [48.5, -51.25, -10.5]
    _clean(report)


def test_ctrader_all_unexecuted_deals_are_refused_naming_their_statuses() -> None:
    with pytest.raises(ReportFormatError) as caught:
        import_report(
            _ctrader_with_status("Rejected", "Error", "Rejected"),
            columns={"profit": "Gross (currency)"},
        )
    assert caught.value.code == "deals_without_execution"
    english, spanish = str(caught.value), caught.value.localized("es")
    portuguese = errors_pt.portuguese(english)
    assert portuguese is not None
    for text in (english, spanish, portuguese):
        assert "(Rejected, Error)" in text, text
        assert find_claims(text) == [], text
    assert "no filled or partially filled deal" in english
    assert "sin ejecución" in spanish and "sem execução" in portuguese


def test_ctrader_mac_history_names_are_read_as_swap_and_commissions() -> None:
    # The Mac help (help.ctrader.com/ctrader-mac/trade/trade-watch/) names Swaps,
    # Broker commission and Conversion fee, and USD copies of the results.
    header = (
        "Deal ID,Order ID,Symbol,Opening direction,Opening time,Closing time,Entry price,"
        "Closing price,Closing quantity,Swaps,Broker commission,Conversion fee,"
        "Gross (currency),Net (currency),Gross USD,Net USD"
    )
    rows = (
        "101,51,EURUSD,Buy,2026-09-01 09:00:00,2026-09-01 10:00:00,1.1000,1.1020,0.25,"
        "-0.25,-1.25,-0.10,50.00,48.40,55.00,53.24",
        "102,51,EURUSD,Buy,2026-09-01 09:00:00,2026-09-02 10:00:00,1.1000,1.0980,0.25,"
        "0.00,-1.25,-0.10,-50.00,-51.35,-55.00,-56.49",
        "103,52,EURUSD,Sell,2026-09-03 09:00:00,2026-09-03 10:00:00,1.2000,1.2010,0.10,"
        "0.00,-0.50,-0.05,-10.00,-10.55,-11.00,-11.61",
    )
    data = ("\n".join([header, *rows]) + "\n").encode()
    # Unmapped, the only result name the reader knows is the USD net copy: the
    # guide says to map Gross (currency) and drop the USD columns.
    guessed = guess_columns(header.split(","))
    assert header.split(",")[guessed["profit"]] == "Net USD"
    report = import_report(data, columns={"profit": "Gross (currency)"}, initial_balance=10_000)
    assert report.metadata["column_commission"] == "Broker commission, Conversion fee"
    assert report.metadata["column_swap"] == "Swaps"
    assert report.fees == {"commission": pytest.approx(-3.25), "swap": pytest.approx(-0.25)}
    assert report.trades.fees == [pytest.approx(1.6), pytest.approx(1.35), pytest.approx(0.55)]
    assert _net(report) == [48.4, -51.35, -10.55]
    _clean(report)


def test_ctrader_status_filter_does_not_change_other_platforms_closed_status() -> None:
    lines = _trades_csv().decode().splitlines()
    data = "\n".join([f"{lines[0]},Status", *(f"{row},Closed" for row in lines[1:])]).encode()
    assert len(import_report(data).trades.trades) == 12


def test_ctrader_account_selection_counts_filled_deals_only() -> None:
    lines = _ctrader_with_status("Rejected", "Rejected", "Filled").decode().splitlines()
    rows = [f"{row},{account}" for row, account in zip(lines[1:], ("A", "A", "B"), strict=True)]
    data = ("\n".join([f"{lines[0]},Account", *rows]) + "\n").encode()
    report = import_report(
        data,
        columns={"profit": "Gross (currency)"},
        initial_balance=10_000,
    )
    # A has more rows but no executions. B's filled losing deal must remain.
    assert _net(report) == [-10.5]
    assert report.metadata["column_account"] == "Account"
    assert report.metadata["excluded_unfilled_deals"] == "2"
    assert "2 deal row(s) without a filled status excluded" in report.warnings
    _clean(report)


def test_spanish_headers_with_semicolons_and_decimal_commas() -> None:
    header = "Símbolo;Fecha de apertura;Fecha de cierre;Dirección;Cantidad;Precio de entrada;"
    header += "Precio de salida;Comisión;Resultado"
    rows = [
        f"SAN.MC;2026-02-{d:02d} 10:00;2026-02-{d:02d} 16:00;Compra;100;4,10;4,{15 + d};"
        f"1,50;{(0.05 + d / 100) * 100:.2f}".replace(".", ",")
        for d in range(2, 14)
    ]
    data = ("\n".join([header, *rows]) + "\n").encode()
    report = import_report(data, "cuenta.csv")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    first = report.trades.trades[0]
    assert (first.entry_price, first.exit_price) == (4.10, 4.17)
    assert first.pnl == pytest.approx(7.0)
    assert report.trades.sides[0] == "long"
    _clean(report)


def test_a_profit_that_already_subtracts_commission_is_read_as_net() -> None:
    lines = ["Ticker,Entry Date,Exit Date,Side,Shares,Entry Price,Exit Price,Fees,P&L"]
    for i in range(10):
        move = 1.0 + i / 10
        fee = 1.0 + (i % 3)
        lines.append(
            f"AAPL,2026-01-{i + 5:02d},2026-01-{i + 6:02d},Long,100,200,{200 + move:.2f},"
            f"{fee:.2f},{move * 100 - fee:.2f}"
        )
    report = import_report(("\n".join(lines) + "\n").encode(), "journal.csv")
    assert any("read as net" in warning for warning in report.warnings)
    first = report.trades.trades[0]
    assert first.pnl == pytest.approx(100.0)
    assert _net(report)[0] == pytest.approx(99.0)
    _clean(report)


def _crypto_fills() -> bytes:
    rows = [
        "Date(UTC),Pair,Side,Price,Executed,Amount,Fee",
        "2026-05-01 10:00:00,BTCUSDT,BUY,60000,0.010BTC,600USDT,0.60USDT",
        "2026-05-01 12:00:00,BTCUSDT,SELL,61000,0.004BTC,244USDT,0.24USDT",
        "2026-05-02 09:00:00,BTCUSDT,SELL,59000,0.006BTC,354USDT,0.00025BNB",
        "2026-05-03 09:00:00,ETHUSDT,SELL,3000,0.5ETH,1500USDT,1.5USDT",
        "2026-05-03 18:00:00,ETHUSDT,BUY,2900,0.5ETH,1450USDT,1.45USDT",
        "2026-05-04 09:00:00,ETHUSDT,BUY,2950,0.1ETH,295USDT,0.29USDT",
    ]
    return ("\n".join(rows) + "\n").encode()


def test_exchange_fills_are_paired_first_in_first_out() -> None:
    data = _crypto_fills()
    assert detect_format(data) == UNIVERSAL_FILLS_CSV
    report = import_report(data, "trade_history.csv", initial_balance=2_000)
    trades = report.trades.trades
    assert len(trades) == 3
    assert report.trades.sides == ["long", "long", "short"]
    by_exit = sorted(zip(report.symbols, trades, strict=True), key=lambda p: p[1].exit_time)
    assert [symbol for symbol, _ in by_exit] == ["BTCUSDT", "BTCUSDT", "ETHUSDT"]
    assert [round(trade.pnl, 2) for _, trade in by_exit] == [4.0, -6.0, 50.0]
    # The BNB fee cannot be priced in USDT: left out and said.
    assert any("another coin" in warning for warning in report.warnings)
    assert any("1 position(s) still open" in warning for warning in report.warnings)
    _clean(report)


def test_signed_quantities_and_unix_millisecond_times() -> None:
    rows = ["timestamp,symbol,qty,price,commission"]
    start = 1_767_225_600_000  # 2026-01-01 00:00 UTC
    for i in range(6):
        rows.append(f"{start + i * 7_200_000},ES,{1 if i % 2 == 0 else -1},{5000 + i},2.5")
    report = import_report(("\n".join(rows) + "\n").encode(), "fills.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert len(report.trades.trades) == 3
    assert report.trades.trades[0].entry_time.year == 2026
    assert any("sign of the quantity" in warning for warning in report.warnings)
    assert any("no profit column" in warning for warning in report.warnings)
    _clean(report)


def test_title_lines_above_the_header_are_skipped() -> None:
    body = _trades_csv().decode()
    data = f"Account statement\nGenerated 2026-04-01\n{body}".encode()
    assert import_report(data, "statement.csv").source_format == UNIVERSAL_TRADES_CSV


def test_an_excel_trade_list_is_read() -> None:
    header = ["Instrument", "Entry time", "Exit time", "Direction", "Qty", "Entry price",
              "Exit price", "PnL"]  # fmt: skip
    rows: list[list[object]] = [header]
    for i in range(8):
        serial = 46_000 + i  # Excel day serials
        rows.append(["NQ", serial + 0.4, serial + 0.45, "Short", 1, 20000, 19990, 200])
    report = import_report(xlsx({"Trades": rows}), "trades.xlsx", initial_balance=50_000)
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert len(report.trades.trades) == 8
    assert report.trades.sides[0] == "short"
    # 10 points pay 200: a multiplier of 20, inferred from the profit.
    assert report.trades.trades[0].quantity == pytest.approx(20.0)


def test_the_customer_maps_columns_the_names_do_not_explain() -> None:
    header = "Cuando entré,Cuando salí,Mercado,Cuánto,A cuánto entré,A cuánto salí,Gané"
    rows = [f"2026-06-{d:02d} 10:00,2026-06-{d:02d} 11:00,GC,1,2300,2302,200" for d in range(1, 9)]
    data = ("\n".join([header, *rows]) + "\n").encode()
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "mio.csv")
    assert refused.value.code in {"unknown_format", "universal_columns_missing"}
    mapping = {
        "entry_time": "Cuando entré",
        "exit_time": "Cuando salí",
        "quantity": "Cuánto",
        "entry_price": "A cuánto entré",
        "exit_price": "A cuánto salí",
        "profit": "Gané",
    }
    report = import_report(data, "mio.csv", columns=mapping)
    assert len(report.trades.trades) == 8
    assert report.metadata["column_profit"] == "Gané"
    with pytest.raises(ReportFormatError) as wrong:
        import_report(data, "mio.csv", columns={**mapping, "profit": "Perdí"})
    assert wrong.value.code == "universal_unknown_column"


def test_a_half_recognised_table_names_the_missing_columns() -> None:
    data = b"Date,Symbol,Side,Amount\n2026-01-02,AAPL,Buy,1000\n"
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "cash.csv")
    error = refused.value
    assert error.code == "universal_columns_missing"
    assert "price" in str(error) and "precio" in error.message_es
    assert "Date, Symbol, Side, Amount" in str(error)
    assert find_claims(str(error)) == [] and find_claims(error.message_es) == []


def test_an_equity_curve_is_not_mistaken_for_a_trade_list() -> None:
    data = b"timestamp,equity\n2026-01-01,10000\n2026-01-02,10050\n"
    assert detect_format(data) is None


def test_names_are_normalised_across_languages_and_units() -> None:
    assert normalise("Date(UTC)") == "date"
    assert normalise("Prix d'entrée") == "prixdentree"
    columns = guess_columns(["Date(UTC)", "OrderNo", "Pair", "Type", "Side", "Price",
                             "Executed", "Amount"])  # fmt: skip
    # "Side" beats "Type" (LIMIT/MARKET) and "Executed" beats "Amount" (quote value).
    assert columns["side"] == 4 and columns["quantity"] == 6


def test_german_and_french_closing_columns_are_recognised() -> None:
    # "ß" folds to "ss", and French writes "clôture" as often as "fermeture".
    german = ["Symbol", "Richtung", "Menge", "Eröffnungszeit", "Schließzeit",
              "Einstiegspreis", "Ausstiegspreis", "Gewinn", "Kommission"]  # fmt: skip
    french = ["Symbole", "Sens", "Quantité", "Date d'ouverture", "Date de clôture",
              "Prix d'entrée", "Prix de clôture", "Profit", "Commission"]  # fmt: skip
    for header in (german, french):
        columns = guess_columns(header)
        assert columns["exit_time"] == 4 and columns["exit_price"] == 6
        assert columns["commission"] == 8


def test_fees_all_in_another_coin_are_not_also_called_zero_commission() -> None:
    lines = ["Date(UTC),Pair,Side,Price,Executed,Fee"]
    for day in range(1, 7):
        lines.append(f"2026-03-{day:02d} 10:00:00,BTCUSDT,BUY,60000,0.01,0.00001 BNB")
        lines.append(f"2026-03-{day:02d} 16:00:00,BTCUSDT,SELL,60300,0.01,0.00001 BNB")
    report = import_report(("\n".join(lines) + "\n").encode(), "fills.csv", initial_balance=2_000)
    assert any("another coin" in warning for warning in report.warnings)
    assert not any("zero commission" in warning for warning in report.warnings)
    _clean(report)


def test_an_overflowing_trade_is_refused_not_audited_as_infinity() -> None:
    # 9e307 x 2 x 100 overflows to infinity; the audit used to crash on it (HTTP 500).
    lines = [
        "Symbol,DateTime,Buy/Sell,Quantity,TradePrice,Multiplier,FifoPnlRealized",
        "AAPL,20260115;093000,BUY,100,200,1,0",
        "AAPL,20260116;100000,SELL,-100,205,1,500",
        "SPY C600,20260120;110000,BUY,2,9e307,100,0",
        "SPY C600,20260121;110000,SELL,-2,9e307,100,9e307",
    ]
    with pytest.raises(ReportFormatError) as caught:
        import_report(("\n".join(lines) + "\n").encode(), "flex.csv", initial_balance=25_000)
    assert caught.value.code == "value_too_large"
    assert "2026-01-21" in str(caught.value)


def test_ninjatrader_executions_no_longer_call_the_point_value_an_inference() -> None:
    header = "Instrument;Action;Quantity;Price;Time;ID;E/X;Commission;Account display name"
    rows = [
        "MNQZ6;Buy;1;21000,00;2026-10-01 10:00:00;1;Entry;0,50 $;Sim101",
        "MNQZ6;Sell;1;21010,00;2026-10-01 10:05:00;2;Exit;0,50 $;Sim101",
    ]
    data = ("\n".join([header, *rows]) + "\n").encode()
    report = import_report(data, "Executions.csv")
    assert report.source_format == NINJATRADER_EXECUTIONS_CSV
    assert not any("contract size inferred" in warning for warning in report.warnings)


def test_a_repeated_time_column_holds_entry_and_exit_on_one_row() -> None:
    header = "Time,Side,Qty,Symbol,Price,Time,Price,Fee,PnL"
    rows = [
        f"2026-07-{d:02d} 09:00,Sell,2,XAUUSD,2400,2026-07-{d:02d} 12:00,2395,1.2,10"
        for d in range(1, 7)
    ]
    report = import_report(("\n".join([header, *rows]) + "\n").encode(), "history.csv")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    trade = report.trades.trades[0]
    assert (trade.entry_price, trade.exit_price) == (2400, 2395)
    assert trade.exit_time.hour == 12


def test_a_fred_series_names_its_dates_observation_date() -> None:
    from quant_trade.audit.schema import parse_equity_csv

    rows = [f"2020-{m:02d}-01,{100 + m}" for m in range(1, 13)]
    rows += [f"2021-{m:02d}-01,{112 + m}" for m in range(1, 13)]
    rows += [f"2022-{m:02d}-01,{124 + m}" for m in range(1, 13)]
    data = ("observation_date,SP500\n" + "\n".join(rows) + "\n").encode()
    series = parse_equity_csv(data.replace(b"SP500", b"value"))
    assert len(series.frame) == 36
