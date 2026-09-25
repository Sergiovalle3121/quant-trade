"""Any trade or fill list: columns recognised by name, or mapped by the customer.

Every file here is synthetic. Column names follow the publicly documented
exports of common brokers, exchanges and journals; the rows are made up.
"""

from __future__ import annotations

import pytest
from test_audit_importers import xlsx

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
