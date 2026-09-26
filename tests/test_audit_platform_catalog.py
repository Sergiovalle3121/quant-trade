"""One export per platform, read by the universal importer.

Column names and value styles follow each platform's public export (its
help pages, and the open-source journal importers that read real files:
tradetally, Apache-2.0). Every row here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.importers import (
    UNIVERSAL_FILLS_CSV,
    UNIVERSAL_TRADES_CSV,
    ImportedReport,
    ReportFormatError,
    import_report,
)


def _read(lines: list[str], name: str = "export.csv", **kwargs: object) -> ImportedReport:
    data = ("\n".join(lines) + "\n").encode()
    report = import_report(data, name, initial_balance=25_000, **kwargs)  # type: ignore[arg-type]
    assert untranslated({"inputs": {"parse_warnings": report.warnings}}) == []
    assert all(find_claims(warning) == [] for warning in report.warnings)
    return report


def _net(report: ImportedReport) -> list[float]:
    fees = report.trades.fees or [0.0] * len(report.trades.trades)
    return [round(t.pnl - f, 2) for t, f in zip(report.trades.trades, fees, strict=True)]


def test_tradovate_position_history_pairs_buys_and_sells() -> None:
    header = (
        "Position ID,Timestamp,Trade Date,Net Pos,Net Price,Bought,Avg. Buy,Sold,Avg. Sell,"
        "Account,Contract,Product,Product Description,_priceFormat,_priceFormatType,_tickSize,"
        "Pair ID,Buy Fill ID,Sell Fill ID,Paired Qty,Buy Price,Sell Price,P/L,Currency,"
        "Bought Timestamp,Sold Timestamp"
    )
    rows = [
        # A long: bought 04/09 09:30, sold 09:40, 2 MNQ, +5 points = +20 USD.
        "1,04/09/2026 17:14:44,2026-04-09,0,,2,21000,2,21005,ACC1,MNQM6,MNQ,Micro,-2,0,0.25,"
        "11,12,13,2,21000.00,21005.00,20.00,USD,04/09/2026 09:30:00,04/09/2026 09:40:00",
        # A short: sold first at 10:00, bought back at 10:05, 1 MNQ, -3 points = +6 USD.
        "1,04/09/2026 17:14:44,2026-04-09,0,,1,20997,1,21000,ACC1,MNQM6,MNQ,Micro,-2,0,0.25,"
        "21,22,23,1,20997.00,21000.00,6.00,USD,04/09/2026 10:05:00,04/09/2026 10:00:00",
        "1,04/10/2026 17:14:44,2026-04-10,0,,1,21010,1,21000,ACC1,MNQM6,MNQ,Micro,-2,0,0.25,"
        "31,32,33,1,21010.00,21000.00,$(20.00),USD,04/10/2026 11:00:00,04/10/2026 11:30:00",
    ]
    report = _read([header, *rows], "Performance.csv")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert report.trades.sides == ["long", "short", "long"]
    assert [round(t.pnl, 2) for t in report.trades.trades] == [20.0, 6.0, -20.0]
    short = report.trades.trades[1]
    assert (short.entry_price, short.exit_price) == (21000.0, 20997.0)
    # Month first, settled by the Trade Date column even though no day passes 12.
    assert report.trades.trades[0].entry_time == datetime(2026, 4, 9, 9, 30, tzinfo=UTC)


def test_tradovate_orders_are_fills_priced_with_the_contract_point_value() -> None:
    header = "orderId,Account,Order ID,B/S,Contract,Product,avgPrice,filledQty,Fill Time,Status"
    rows = [
        "1,ACC1,1,Buy,ESZ6,ES,6000.00,1,09/21/2026 09:30:00,Filled",
        "2,ACC1,2,Sell,ESZ6,ES,6004.00,1,09/21/2026 09:45:00,Filled",
        "3,ACC1,3,Sell,ESZ6,ES,6010.00,0,09/21/2026 10:00:00,Canceled",
    ]
    report = _read([header, *rows], "Orders.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert [round(t.pnl, 2) for t in report.trades.trades] == [200.0]
    assert any("point value: ES x50" in warning for warning in report.warnings)
    assert not any("contract size inferred" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    ("code", "root", "value", "currency"),
    [
        ("FDAX 12-26", "FDAX", 25.0, "EUR"),
        ("FDXMZ6", "FDXM", 5.0, "EUR"),
        ("FDXSZ6", "FDXS", 1.0, "EUR"),
        ("FESXZ6", "FESX", 10.0, "EUR"),
        ("FSXEZ6", "FSXE", 1.0, "EUR"),
        ("FSMIZ6", "FSMI", 10.0, "CHF"),
        ("FVSZ6", "FVS", 100.0, "EUR"),
        ("FGBSZ6", "FGBS", 1_000.0, "EUR"),
        ("FGBMZ6", "FGBM", 1_000.0, "EUR"),
        ("FGBLZ6", "FGBL", 1_000.0, "EUR"),
        ("FGBXZ6", "FGBX", 1_000.0, "EUR"),
        ("BZ6", "B", 1_000.0, "USD"),
        ("GZ26", "G", 100.0, "USD"),
        ("SBH7", "SB", 1_120.0, "USD"),
        ("KCZ6", "KC", 375.0, "USD"),
        ("CTZ6", "CT", 500.0, "USD"),
        ("CCZ6", "CC", 10.0, "USD"),
        ("OJF7", "OJ", 150.0, "USD"),
        ("DXZ6", "DX", 1_000.0, "USD"),
        ("WINZ26", "WIN", 0.2, "BRL"),
        ("INDZ26", "IND", 1.0, "BRL"),
        ("WDOF27", "WDO", 10.0, "BRL"),
        ("DOLF27", "DOL", 50.0, "BRL"),
        ("IPC DC26", "IPC", 10.0, "MXN"),
        ("IPCDC26", "IPC", 10.0, "MXN"),
        ("MIP  MR27", "MIP", 2.0, "MXN"),
        ("DA DC26", "DA", 10_000.0, "MXN"),
        ("DA19 DC16", "DA", 10_000.0, "MXN"),
        # CME codes that share a first letter keep their own contract.
        ("GCZ6", "GC", 100.0, "USD"),
        ("MGCZ6", "MGC", 10.0, "USD"),
        ("SIZ6", "SI", 5_000.0, "USD"),
        ("ZBZ6", "ZB", 1_000.0, "USD"),
        ("ZFZ6", "ZF", 1_000.0, "USD"),
        ("CLZ6", "CL", 1_000.0, "USD"),
    ],
)
def test_eurex_and_ice_contracts_carry_their_point_value(
    code: str, root: str, value: float, currency: str
) -> None:
    from quant_trade.audit.universal import _contract

    assert _contract(code) == (root, value, currency)


@pytest.mark.parametrize(
    "ticker",
    ["B", "G", "FDAX", "BRK", "GOOG", "SB", "ZN6", "WIN", "DOL", "INDA", "IPC", "DA", "DAL"],
)
def test_a_bare_root_or_a_share_ticker_is_not_a_contract(ticker: str) -> None:
    from quant_trade.audit.universal import _contract

    assert _contract(ticker) is None


def test_eurex_fills_are_priced_in_euros_and_mixed_currencies_are_named() -> None:
    header = "Account,B/S,Contract,avgPrice,filledQty,Fill Time"
    rows = [
        "ACC1,Buy,FDAXZ6,24000.0,1,09/21/2026 09:30:00",
        "ACC1,Sell,FDAXZ6,24010.0,1,09/21/2026 09:45:00",
    ]
    report = _read([header, *rows], "fills.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [250.0]
    assert any("point value: FDAX x25 EUR" in warning for warning in report.warnings)
    assert not any("different currencies" in warning for warning in report.warnings)
    mixed = _read(
        [
            header,
            *rows,
            "ACC1,Buy,ESZ6,6000.0,1,09/22/2026 09:30:00",
            "ACC1,Sell,ESZ6,6002.0,1,09/22/2026 09:45:00",
        ],
        "fills.csv",
    )
    assert [round(t.pnl, 2) for t in mixed.trades.trades] == [250.0, 100.0]
    assert any("different currencies (EUR, USD)" in warning for warning in mixed.warnings)


def test_b3_mini_index_fills_are_priced_in_reais() -> None:
    header = "Account,B/S,Contract,avgPrice,filledQty,Fill Time"
    rows = [
        "ACC1,Buy,WINZ26,130000,2,09/21/2026 10:00:00",
        "ACC1,Sell,WINZ26,130250,2,09/21/2026 10:30:00",
    ]
    report = _read([header, *rows], "fills.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [100.0]
    assert any("point value: WIN x0.2 BRL" in warning for warning in report.warnings)


def test_mexder_ipc_fills_are_priced_in_pesos() -> None:
    header = "Account,B/S,Contract,avgPrice,filledQty,Fill Time"
    rows = [
        "ACC1,Sell,IPC DC26,60000,1,09/21/2026 08:00:00",
        "ACC1,Buy,IPC DC26,59900,1,09/21/2026 09:00:00",
    ]
    report = _read([header, *rows], "fills.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [1000.0]
    assert any("point value: IPC x10 MXN" in warning for warning in report.warnings)


def test_topstepx_trades_with_a_zone_after_the_time() -> None:
    header = (
        "Id,ContractName,EnteredAt,ExitedAt,EntryPrice,ExitPrice,Fees,PnL,Size,Type,TradeDay,"
        "TradeDuration,Commissions"
    )
    rows = [
        "1,MNQZ6,10/01/2026 21:13:23 +02:00,10/01/2026 21:20:00 +02:00,21000,21010,0.74,40,2,"
        "Long,2026-10-01T00:00:00,00:06:37,",
        "2,MNQZ6,10/02/2026 15:00:00 +02:00,10/02/2026 15:05:00 +02:00,21010,21000,0.37,20,1,"
        "Short,2026-10-02T00:00:00,00:05:00,",
    ]
    report = _read([header, *rows], "trades_export.csv")
    trades = report.trades.trades
    assert report.trades.sides == ["long", "short"]
    assert trades[0].entry_time == datetime(2026, 10, 1, 19, 13, 23, tzinfo=UTC)
    assert _net(report) == [39.26, 19.63]


def test_interactive_brokers_flex_trades_with_compact_times() -> None:
    header = (
        "ClientAccountID,CurrencyPrimary,AssetClass,Symbol,DateTime,TradeDate,Buy/Sell,"
        "Quantity,TradePrice,IBCommission,IBCommissionCurrency,Multiplier,FifoPnlRealized"
    )
    rows = [
        "U1,USD,STK,AAPL,20260115;093000,20260115,BUY,100,200,-1,USD,1,0",
        "U1,USD,STK,AAPL,20260116;100000,20260116,SELL,-100,205,-1,USD,1,498",
        "U1,USD,OPT,SPY 260220C00600000,20260120;110000,20260120,BUY,2,3.10,-1.3,USD,100,0",
        "U1,USD,OPT,SPY 260220C00600000,20260121;110000,20260121,SELL,-2,3.60,-1.3,USD,100,97.4",
    ]
    report = _read([header, *rows], "flex.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    trades = report.trades.trades
    assert len(trades) == 2
    # FifoPnlRealized already subtracts both commissions: read as net.
    assert any("read as net" in warning for warning in report.warnings)
    assert [round(t.pnl, 2) for t in trades] == [500.0, 100.0]
    assert trades[0].entry_time == datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


def _flex_xml(*elements: str, doctype: str = "") -> bytes:
    body = "\n".join(elements)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}\n'
        '<FlexQueryResponse queryName="trades" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U1" fromDate="20260101" toDate="20260131">'
        f"<Trades>\n{body}\n</Trades></FlexStatement></FlexStatements></FlexQueryResponse>"
    ).encode()


_FLEX_FILLS = (
    '<Trade accountId="U1" currency="USD" assetCategory="STK" symbol="AAPL" '
    'dateTime="20260115;093000" tradeDate="20260115" quantity="100" tradePrice="200" '
    'ibCommission="-1" ibCommissionCurrency="USD" multiplier="1" fifoPnlRealized="0" '
    'buySell="BUY" levelOfDetail="EXECUTION" />',
    '<Trade accountId="U1" currency="USD" assetCategory="STK" symbol="AAPL" '
    'dateTime="20260116;100000" tradeDate="20260116" quantity="-100" tradePrice="205" '
    'ibCommission="-1" ibCommissionCurrency="USD" multiplier="1" fifoPnlRealized="498" '
    'buySell="SELL" levelOfDetail="EXECUTION" />',
    # An order-level summary row repeats the executions: never read.
    '<Order accountId="U1" symbol="AAPL" dateTime="20260116;100000" quantity="-100" '
    'tradePrice="205" buySell="SELL" levelOfDetail="ORDER" />',
)


def test_interactive_brokers_flex_xml_reads_like_the_flex_csv() -> None:
    import io  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    report = _read([_flex_xml(*_FLEX_FILLS).decode()], "flex.xml")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert [round(t.pnl, 2) for t in report.trades.trades] == [500.0]
    assert report.trades.trades[0].entry_time == datetime(2026, 1, 15, 9, 30, tzinfo=UTC)
    assert any("read as net" in warning for warning in report.warnings)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("flex.xml", _flex_xml(*_FLEX_FILLS))
    zipped = import_report(buffer.getvalue(), "flex.zip")
    assert [round(t.pnl, 2) for t in zipped.trades.trades] == [500.0]


def test_a_flex_xml_without_executions_says_how_to_add_them() -> None:
    with pytest.raises(ReportFormatError) as refused:
        import_report(_flex_xml(_FLEX_FILLS[2]), "flex.xml")
    error = refused.value
    assert error.code == "flex_no_trades"
    assert "Execution" in str(error) and "Execution" in error.localized("es")
    assert error.localized("pt").startswith("o extrato da Interactive Brokers não tem operações")
    assert find_claims(str(error)) == [] and find_claims(error.localized("es")) == []


def test_a_flex_xml_with_made_up_attribute_names_is_refused_quickly() -> None:
    import time  # noqa: PLC0415

    trades = [
        '<Trade levelOfDetail="EXECUTION" '
        + " ".join(f'a{row}x{col}="1"' for col in range(20))
        + " />"
        for row in range(2_000)
    ]
    started = time.perf_counter()
    with pytest.raises(ReportFormatError) as refused:
        import_report(_flex_xml(*trades), "flex.xml")
    assert refused.value.code == "flex_too_large"
    assert refused.value.localized("pt").startswith("o extrato da Interactive Brokers é grande")
    assert time.perf_counter() - started < 5
    assert find_claims(str(refused.value)) == []
    assert find_claims(refused.value.localized("es")) == []


def test_a_flex_xml_with_a_document_type_is_refused() -> None:
    doctype = '<!DOCTYPE r [<!ENTITY x "y">]>'
    with pytest.raises(ReportFormatError) as refused:
        import_report(_flex_xml(*_FLEX_FILLS, doctype=doctype), "flex.xml")
    assert refused.value.code == "xml_doctype"


def test_interactive_brokers_activity_statement_trades_section() -> None:
    lines = [
        "Statement,Header,Field Name,Field Value",
        "Statement,Data,Title,Activity Statement",
        "Account Information,Header,Field Name,Field Value",
        "Account Information,Data,Name,-",
        "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,"
        "T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code",
        'Trades,Data,Order,Stocks,USD,MSFT,"2026-02-02, 10:00:00",50,400,401,-20000,-1,20001,'
        "0,50,O",
        'Trades,Data,Order,Stocks,USD,MSFT,"2026-02-03, 15:00:00",-50,410,410,20500,-1,-20001,'
        "498,0,C",
        "Trades,SubTotal,,Stocks,USD,MSFT,,0,,,500,-2,0,498,50,",
        "Trades,Total,,Stocks,USD,,,,,,500,-2,0,498,50,",
        "Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount",
    ]
    report = _read(lines, "U1234567_2026.csv")
    trades = report.trades.trades
    assert len(trades) == 1
    assert round(trades[0].pnl, 2) == 500.0
    assert trades[0].exit_time == datetime(2026, 2, 3, 15, tzinfo=UTC)


def test_schwab_realized_gain_loss() -> None:
    header = (
        "Symbol,Name,Closed Date,Opened Date,Quantity,Proceeds Per Share,Cost Per Share,"
        "Proceeds,Cost Basis (CB),Gain/Loss ($),Gain/Loss (%),Term,Wash Sale?"
    )
    rows = [
        "NVDA,NVIDIA CORP,03/20/2026,03/02/2026,10,$130.00,$120.00,$1300.00,$1200.00,$100.00,"
        "8.33%,Short Term,No",
        "AMD,ADVANCED MICRO,03/25/2026,03/05/2026,20,$150.00,$160.00,$3000.00,$3200.00,"
        "($200.00),-6.25%,Short Term,No",
    ]
    report = _read([header, *rows], "Realized_Gain_Loss.csv")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert report.trades.sides == ["long", "long"]
    assert [round(t.pnl, 2) for t in report.trades.trades] == [100.0, -200.0]


def test_schwab_transactions_newest_first_with_dates_only() -> None:
    header = "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount"
    rows = [
        "03/16/2026,Sell,TSLA,TESLA INC,5,$260.00,$0.05,$1299.95",
        "03/16/2026,Buy,TSLA,TESLA INC,5,$250.00,,-$1250.00",
        "03/05/2026,Sell,AAPL,APPLE INC,1,$201.00,,$201.00",
        "03/05/2026,Buy,AAPL,APPLE INC,1,$200.00,,-$200.00",
        "03/02/2026,Qualified Dividend,KO,COCA COLA,,,,$12.00",
    ]
    report = _read([header, *rows], "Transactions.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert report.trades.sides == ["long", "long"]
    assert _net(report) == [1.0, 49.95]


def test_webull_orders_use_the_fill_price_not_the_limit() -> None:
    header = (
        "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,Time-in-Force,Placed Time,"
        "Filled Time"
    )
    rows = [
        "AMC,AMC,Buy,Filled,100,100,@5.00,5.02,DAY,03/13/2026 09:31:00 EDT,03/13/2026 09:31:05 EDT",
        "AMC,AMC,Sell,Filled,100,100,@5.30,5.31,DAY,03/13/2026 10:00:00 EDT,"
        "03/13/2026 10:00:02 EDT",
        "AMC,AMC,Sell,Cancelled,0,100,@6.00,,DAY,03/13/2026 11:00:00 EDT,",
    ]
    report = _read([header, *rows], "Webull_Orders_Records.csv")
    trade = report.trades.trades[0]
    assert (trade.entry_price, trade.exit_price) == (5.02, 5.31)
    assert trade.entry_time == datetime(2026, 3, 13, 13, 31, 5, tzinfo=UTC)


def test_thinkorswim_account_statement_trade_history() -> None:
    lines = [
        "Account Statement for 123 since 3/1/26 through 3/31/26",
        "Cash Balance",
        "DATE,TIME,TYPE,REF #,DESCRIPTION,Misc Fees,Commissions & Fees,AMOUNT,BALANCE",
        "3/2/26,09:30:00,TRD,1,BOT +100 AAPL @200,,,-20000,5000",
        "Account Trade History",
        ",Exec Time,Spread,Side,Qty,Pos Effect,Symbol,Exp,Strike,Type,Price,Net Price,Order Type",
        ",3/17/26 10:00:00,STOCK,SELL,-100,TO CLOSE,AAPL,,,STOCK,203.00,203.00,LMT",
        ",3/16/26 09:30:00,STOCK,BUY,+100,TO OPEN,AAPL,,,STOCK,200.00,200.00,LMT",
        "Equities",
        "Symbol,Description,Qty,Trade Price",
    ]
    report = _read(lines, "2026-03-31-AccountStatement.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert [round(t.pnl, 2) for t in report.trades.trades] == [300.0]


def test_tradestation_clock_only_times_join_the_trade_date() -> None:
    header = (
        "Account,T/D,S/D,Currency,Type,Side,Symbol,Qty,Price,Exec Time,Comm,SEC,TAF,"
        "Gross Proceeds,Net Proceeds"
    )
    rows = [
        "11,03/16/2026,03/17/2026,USD,2,B,QQQ,10,500.00,09:45:00,1.00,0,0,-5000,-5001",
        "11,03/16/2026,03/17/2026,USD,2,S,QQQ,10,502.50,14:15:30,1.00,0.02,0.01,5025,5023.97",
    ]
    report = _read([header, *rows], "TradeStation.csv")
    trade = report.trades.trades[0]
    assert trade.exit_time == datetime(2026, 3, 16, 14, 15, 30, tzinfo=UTC)
    assert round(trade.pnl, 2) == 25.0


def test_tastytrade_options_use_the_multiplier_column() -> None:
    header = (
        "Date,Type,Sub Type,Action,Symbol,Instrument Type,Description,Value,Quantity,"
        "Average Price,Commissions,Fees,Multiplier,Root Symbol,Underlying Symbol,"
        "Expiration Date,Strike Price,Call or Put,Order #,Currency"
    )
    rows = [
        "2026-04-02T14:00:00+0000,Trade,Sell to Close,SELL_TO_CLOSE,SPY 260417C00600000,"
        "Equity Option,Sold 1 SPY,250.00,1,2.50,-1.00,-0.14,100,SPY,SPY,4/17/26,600,CALL,2,USD",
        "2026-04-01T14:00:00+0000,Trade,Buy to Open,BUY_TO_OPEN,SPY 260417C00600000,"
        "Equity Option,Bought 1 SPY,-200.00,1,2.00,-1.00,-0.14,100,SPY,SPY,4/17/26,600,CALL,1,USD",
        "2026-04-01T00:00:00+0000,Money Movement,Deposit,,,,Deposit,5000,,,,,,,,,,,,USD",
    ]
    report = _read([header, *rows], "tastytrade_transactions.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [50.0]
    assert _net(report) == [47.72]


def test_fidelity_account_history_actions_in_words() -> None:
    lines = [
        "",
        "Brokerage",
        "Run Date,Account,Action,Symbol,Security Description,Security Type,Quantity,"
        "Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date",
        "05/14/2026,Z1,YOU SOLD APPLE INC (AAPL) (Cash),AAPL,APPLE INC,Cash,-10,210,,0.02,,2099.98,"
        "05/13/2026",
        "05/04/2026,Z1,YOU BOUGHT APPLE INC (AAPL) (Cash),AAPL,APPLE INC,Cash,10,200,,,,-2000,"
        "05/05/2026",
        '"The data and information in this spreadsheet is provided to you solely for your use"',
    ]
    report = _read(lines, "History_for_Account_Z1.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [100.0]


def test_etrade_transactions() -> None:
    header = "TransactionDate,TransactionType,SecurityType,Symbol,Quantity,Amount,Price,Commission"
    rows = [
        "06/01/26,Bought,EQ,F,100,-1200,12.00,0",
        "06/15/26,Sold,EQ,F,-100,1250,12.50,0",
    ]
    report = _read([header, *rows], "DownloadTxnHistory.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [50.0]


def test_etoro_closed_positions() -> None:
    header = (
        "Position ID,Action,Amount,Units,Open Date,Close Date,Leverage,Spread,Profit,"
        "Open Rate,Close Rate,Take profit rate,Stop lose rate"
    )
    rows = [
        "1,Buy Apple,1000,5,15/01/2026 14:30:00,20/01/2026 15:00:00,1,0,50,200,210,0,0",
        "2,Sell Tesla,500,2,21/01/2026 14:30:00,22/01/2026 16:00:00,1,0,-20,250,260,0,0",
    ]
    report = _read([header, *rows], "etoro-account-statement.csv")
    assert report.trades.sides == ["long", "short"]
    assert [round(t.pnl, 2) for t in report.trades.trades] == [50.0, -20.0]


XTB_HEADER = (
    "Position,Symbol,Type,Volume,Open time,Open price,Close time,Close price,Open origin,"
    "Close origin,Purchase value,Sale value,SL,TP,Margin,Commission,Swap,Rollover,Gross P/L,"
    "Comment"
)
XTB_ROWS = [
    ["101", "AAPL.US", "BUY", 10, "02/03/2026 15:30:00", 200, "04/03/2026 16:00:00", 210,
     "xStation5", "xStation5", 2000, 2100, 0, 0, 0, -1.0, 0, 0, 100.0, ""],
    ["102", "EURUSD", "SELL", 0.1, "13/03/2026 08:00:00", 1.09, "13/03/2026 12:00:00", 1.088,
     "xStation5", "xStation5", 10900, 10880, 0, 0, 0, 0, -0.5, -0.25, 20.0, ""],
    ["103", "AAPL.US", "BUY", 5, "16/03/2026 15:30:00", 212, "17/03/2026 16:00:00", 208,
     "xStation5", "xStation5", 1060, 1040, 0, 0, 0, -1.0, 0, 0, -20.0, ""],
]  # fmt: skip


def test_xtb_closed_positions_csv_skips_the_total_row() -> None:
    lines = [XTB_HEADER] + [",".join(str(cell) for cell in row) for row in XTB_ROWS]
    lines.append("Total,,,,,,,,,,,,,,,-2,-0.5,-0.25,100,")
    report = _read(["Name,Demo", "Currency,USD", "", *lines], "account_123_closed.csv")
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert report.trades.sides == ["long", "short", "long"]
    assert [round(t.pnl, 2) for t in report.trades.trades] == [100.0, 20.0, -20.0]
    # Commission and both financing columns (Swap and Rollover) are costs.
    assert _net(report) == [99.0, 19.25, -21.0]
    assert report.metadata["column_commission"] == "Commission, Rollover"
    assert not any("dropped" in warning for warning in report.warnings)
    assert report.symbols == ["AAPL.US", "EURUSD", "AAPL.US"]


def test_xtb_xlsx_with_account_rows_and_an_empty_first_column() -> None:
    from test_audit_importers import xlsx

    top: list[list[object]] = [[None, "Name and surname", "Demo"], [None, "Account", "123"]]
    top += [[None]] * 10
    sheet = [*top, [None, *XTB_HEADER.split(",")], *[[None, *row] for row in XTB_ROWS]]
    sheet.append([None, "Total", *[None] * 14, -2, -0.5, -0.25, 100])
    data = xlsx({"CLOSED POSITION HISTORY": sheet, "CASH OPERATION HISTORY": [["ID"]]})
    report = import_report(data, "account_123_xStation5.xlsx", initial_balance=25_000)
    assert report.source_format == UNIVERSAL_TRADES_CSV
    assert _net(report) == [99.0, 19.25, -21.0]
    assert report.trades.trades[0].entry_time == datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


def test_bybit_closed_pnl_asks_for_the_executions_instead() -> None:
    # Bybit's Closed P&L export (column names as open-source journal importers
    # read it) has one close time per position and no opening time.
    header = (
        "Contracts,Closing Direction,Qty,Entry Price,Exit Price,Closed P&L,Exit Type,"
        "Trade Time(UTC+0)"
    )
    rows = [
        "BTCUSDT,Sell,0.01,60000,60500,4.3,Trade,2025-12-01 15:00:00",
        "BTCUSDT,Buy,0.01,61000,60800,1.3,Trade,2025-12-02 15:00:00",
    ]
    with pytest.raises(ReportFormatError) as info:
        _read([header, *rows], "bybit-closed-pnl.csv")
    assert info.value.code == "universal_close_time_only"
    assert "Trade History" in str(info.value) and "Trade History" in info.value.message_es
    assert find_claims(str(info.value)) == [] and find_claims(info.value.message_es) == []


def test_contracts_names_the_instrument_when_exec_qty_is_the_size() -> None:
    header = (
        "Contracts,Direction,Exec Qty,Exec Price,Trading Fee,Order Type,Transaction Time(UTC+0)"
    )
    rows = [
        "BTCUSDT,Buy,0.01,60000,0.33,Market,2025-12-01 10:00:00",
        "BTCUSDT,Sell,0.01,60500,0.33,Market,2025-12-01 14:00:00",
        "ETHUSDT,Sell,0.5,3000,0.8,Market,2025-12-02 10:00:00",
        "ETHUSDT,Buy,0.5,2950,0.8,Market,2025-12-02 12:00:00",
    ]
    report = _read([header, *rows], "executions.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert report.symbols == ["BTCUSDT", "ETHUSDT"]
    assert report.trades.sides == ["long", "short"]
    assert [round(t.pnl, 2) for t in report.trades.trades] == [5.0, 25.0]
    assert report.metadata["column_quantity"] == "Exec Qty"


def test_numeric_contracts_is_the_size_not_the_instrument() -> None:
    header = "Time,Side,Contracts,Filled Qty,Price"
    rows = ["2026-03-02 10:00,Buy,2,2,5000", "2026-03-02 11:00,Sell,2,2,5010"]
    report = _read([header, *rows], "executions.csv")
    assert report.symbols == [""]
    assert "column_symbol" not in report.metadata
    assert [round(t.pnl, 2) for t in report.trades.trades] == [20.0]


# DEGIRO's Transactions export in each language it ships (layouts from
# open-source portfolio trackers that read it). Two unnamed currency columns
# follow the price and the local value; the quantity's sign is the side.
DEGIRO_LAYOUTS = {
    "en": (
        "Date,Time,Product,ISIN,Reference exchange,Venue,Quantity,Price,,Local value,,Value EUR,"
        "Exchange rate,AutoFX Fee,Transaction and/or third party fees EUR,Total EUR,Order ID",
        "{d},{t},{p},{i},NDQ,XNAS,{q},{px},USD,{lv},USD,{v},1.00,{fx},{fee},{tot},{o}",
    ),
    "es": (
        "Fecha,Hora,Producto,ISIN,Bolsa de referencia,Centro de ejecución,Número,Precio,,"
        "Valor local,,Valor EUR,Tipo de cambio,Comision AutoFX,"
        "Costes de transaccion y/o externos EUR,Total EUR,ID Orden,",
        "{d},{t},{p},{i},NDQ,XNAS,{q},{px},USD,{lv},USD,{v},1.00,{fx},{fee},{tot},{o},",
    ),
    "pt": (
        "Data,Hora,Produto,ISIN,Bolsa de referência,Bolsa,Quantidade,Preços,,Valor local,,"
        "Valor EUR,Taxa de Câmbio,Taxa Autofx,Custos de transação e/ou taxas de terceiros,"
        "Total EUR,ID da Ordem,",
        "{d},{t},{p},{i},NDQ,XNAS,{q},{px},USD,{lv},USD,{v},1.00,{fx},{fee},{tot},{o},",
    ),
    "fr": (
        "Date,Heure,Produit,Code ISIN,Place boursière sectionnée,Lieu d'exécution,Quantité,"
        "Cours,,Montant devise locale,,Montant EUR,Taux de change,Frais conversion AutoFX,"
        "Frais de courtage et/ou de parties,Montant négocié EUR,ID Ordre",
        "{d},{t},{p},{i},NDQ,XNAS,{q},{px},USD,{lv},USD,{v},1.00,{fx},{fee},{tot},{o}",
    ),
    "nl": (
        "Datum,Tijd,Product,ISIN,Beurs,Uitvoeringsplaats,Aantal,Koers,,Lokale waarde,,Waarde,,"
        "Wisselkoers,Transactiekosten,,Totaal,,Order ID",
        "{d},{t},{p},{i},NDQ,XNAS,{q},{px},USD,{lv},USD,{v},EUR,1.00,{fee},EUR,{tot},EUR,{o}",
    ),
    "de": (
        "Datum,Uhrzeit,Produkt,ISIN,Referenzbörse,Anzahl,,Kurs,,Wert in Lokalwährun,,Wert,"
        "Wechselkurs,,Transaktionskost,,Gesamt,Order-ID",
        "{d},{t},{p},{i},NDQ,{q},,{px},USD,{lv},USD,{v},1.00,EUR,{fee},EUR,{tot},{o}",
    ),
}
DEGIRO_FILLS = [
    # 10 Apple bought at 190, sold at 195 the next day: +50 less 2.5 of costs.
    ("15-03-2026", "10:00", "APPLE INC", "US0378331005", "10", "190.00", "0.50", "-1.00", "a1"),
    ("16-03-2026", "15:30", "APPLE INC", "US0378331005", "-10", "195.00", "", "-1.00", "b2"),
    # 5 Microsoft bought at 400 and sold at 398 the same day: -10 less 2 of costs.
    ("17-03-2026", "09:15", "MICROSOFT CORP", "US5949181045", "5", "400.00", "", "-1.00", "c3"),
    ("17-03-2026", "16:05", "MICROSOFT CORP", "US5949181045", "-5", "398.00", "", "-1.00", "d4"),
]


@pytest.mark.parametrize("language", sorted(DEGIRO_LAYOUTS))
def test_degiro_transactions_in_every_language(language: str) -> None:
    header, template = DEGIRO_LAYOUTS[language]
    rows = []
    for day, clock, product, isin, quantity, price, autofx, fee, order in DEGIRO_FILLS:
        value = -float(quantity) * float(price)
        rows.append(
            template.format(
                d=day,
                t=clock,
                p=product,
                i=isin,
                q=quantity,
                px=price,
                lv=f"{value:.2f}",
                v=f"{value:.2f}",
                fx=f"-{autofx}" if autofx else "",
                fee=fee,
                tot=f"{value - 1:.2f}",
                o=order,
            )  # fmt: skip
        )
    report = _read([header, *rows], "Transactions.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert report.symbols == ["APPLE INC", "MICROSOFT CORP"]
    assert report.trades.sides == ["long", "long"]
    # The clock sits in its own column next to the date and is kept.
    assert report.trades.trades[0].entry_time == datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    assert report.trades.trades[1].exit_time == datetime(2026, 3, 17, 16, 5, tzinfo=UTC)
    has_autofx = language not in {"nl", "de"}
    assert _net(report) == [47.5 if has_autofx else 48.0, -12.0]


@pytest.mark.parametrize(
    ("time_header", "buy_time", "sell_time"),
    [
        ("Time", "2026-03-15 14:30:03.613", "2026-03-16 15:30:03.120"),
        ("Time (UTC)", "2026-03-15 14:30:03+00:00", "2026-03-16 15:30:03+00:00"),
    ],
)
def test_trading212_history_reads_the_order_type_and_skips_cash_rows(
    time_header: str, buy_time: str, sell_time: str
) -> None:
    header = (
        f"Action,{time_header},ISIN,Ticker,Name,No. of shares,Price / share,"
        "Currency (Price / share),Exchange rate,Result,Currency (Result),Total,Currency (Total),"
        "Withholding tax,Currency (Withholding tax),Notes,ID,Currency conversion fee,"
        "Currency (Currency conversion fee)"
    )
    rows = [
        "Deposit,2026-03-01 09:00:00,,,,,,,,,,1000.00,EUR,,,,D1,,",
        f"Market buy,{buy_time},DE0007164600,SAP,SAP SE,2,200.00,EUR,1.00,,EUR,400.00,EUR,,,,"
        "EOF1,,",
        f"Limit sell,{sell_time},DE0007164600,SAP,SAP SE,2,205.00,EUR,1.00,10.00,EUR,410.00,"
        "EUR,,,,EOF2,,",
        "Dividend (Dividend),2026-03-20 08:00:00,DE0007164600,SAP,SAP SE,2,1.10,EUR,1.00,,EUR,"
        "2.20,EUR,0.30,EUR,,DV1,,",
    ]
    report = _read([header, *rows], "trading212.csv")
    assert report.symbols == ["SAP"]
    assert report.trades.sides == ["long"]
    assert _net(report) == [10.0]
    entry = report.trades.trades[0].entry_time.replace(microsecond=0)
    assert entry == datetime(2026, 3, 15, 14, 30, 3, tzinfo=UTC)


def test_kucoin_fills_use_the_zone_in_the_column_name() -> None:
    header = (
        "UID,Account Type,Order ID,Symbol,Side,Order Type,Avg. Filled Price,Filled Amount,"
        "Filled Volume,Filled Volume (USDT),Filled Time(UTC+02:00),Fee,Tax,Maker/Taker,"
        "Fee Currency,Account Mode"
    )
    rows = [
        "1001,mainAccount,o1,BTC-USDT,BUY,LIMIT,60000,0.1,6000,6000,2026-03-15 11:00:00,6,,"
        "MAKER,USDT,CLASSIC",
        "1001,mainAccount,o2,BTC-USDT,SELL,LIMIT,61000,0.1,6100,6100,2026-03-16 11:00:00,6.1,,"
        "TAKER,USDT,CLASSIC",
    ]
    report = _read([header, *rows], "kucoin.csv")
    assert report.symbols == ["BTC-USDT"]
    assert report.metadata["column_quantity"] == "Filled Amount"
    assert _net(report) == [87.9]
    # 11:00 at UTC+2 is 09:00 UTC, and the times are no longer read as naive.
    assert report.trades.trades[0].entry_time == datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
    assert not any("no timezone" in warning for warning in report.warnings)


def test_bybit_derivatives_trade_history_opens_and_closes_positions() -> None:
    # Bybit spells its own header "Trasaction ID"; the zone is in the time's name.
    header = (
        "Contracts,Order No.,Direction,Order Type,Filled Qty,Filled Price,Order Price,"
        "Filled Type,Trading Fee Rate,Fees Paid,Trasaction ID,Transaction Time(UTC+10),"
        "Final Balance (USDT)"
    )
    rows = [
        "BTCUSDT,o1,Open Long,Market,0.01,60000,0,Trade,0.00055,0.33,t1,2026-03-15 10:00:00,1000",
        "BTCUSDT,o2,Close Long,Market,0.01,60500,0,Trade,0.00055,0.33,t2,2026-03-15 14:00:00,1004",
        "ETHUSDT,o3,Open Short,Market,0.5,3000,0,Trade,0.00055,0.8,t3,2026-03-16 10:00:00,1004",
        "ETHUSDT,o4,Close Short,Market,0.5,2950,0,Trade,0.00055,0.8,t4,2026-03-16 12:00:00,1028",
    ]
    report = _read([header, *rows], "bybit.csv")
    assert report.source_format == UNIVERSAL_FILLS_CSV
    assert report.symbols == ["BTCUSDT", "ETHUSDT"]
    assert report.trades.sides == ["long", "short"]
    assert _net(report) == [4.34, 23.4]
    assert report.trades.trades[0].entry_time == datetime(2026, 3, 15, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(("direction", "side"), [("Close Long", "long"), ("Close Short", "short")])
def test_a_closed_trade_named_by_its_position_keeps_that_direction(
    direction: str, side: str
) -> None:
    header = "Symbol,Direction,Open Time,Close Time,Qty,Entry Price,Exit Price"
    rows = [f"BTCUSDT,{direction},2026-03-15 10:00,2026-03-15 14:00,1,60000,60500"]
    report = _read([header, *rows], "closed.csv")
    assert report.trades.sides == [side]


def test_ctrader_history() -> None:
    header = (
        "ID,Symbol,Opening Direction,Opening Time (UTC+0),Closing Time (UTC+0),Entry price,"
        "Closing Price,Closing Quantity,Commission,Swap,Net USD,Balance USD"
    )
    rows = [
        "1,EURUSD,Buy,02/03/2026 08:00:00.000,02/03/2026 12:00:00.000,1.08000,1.08200,"
        "1.00 Lots,-6.00,0,194.00,10194.00",
        "2,EURUSD,Sell,05/03/2026 08:00:00.000,05/03/2026 16:00:00.000,1.09000,1.09100,"
        "0.50 Lots,-3.00,-1.20,-54.20,10139.80",
        "3,EURUSD,Buy,13/03/2026 08:00:00.000,13/03/2026 09:00:00.000,1.08500,1.08600,"
        "1.00 Lots,-6.00,0,94.00,10233.80",
    ]
    report = _read([header, *rows], "cTrader_history.csv")
    assert report.trades.sides == ["long", "short", "long"]
    assert any("read as net" in warning for warning in report.warnings)
    assert _net(report) == [194.0, -54.2, 94.0]


def test_ctrader_history_with_month_names_and_the_account_currency() -> None:
    header = (
        "ID,Symbol,Opening Direction,Opening Time (UTC+3),Closing Time (UTC+3),Entry Price,"
        "Closing Price,Closing Quantity,Net AUD,Balance AUD"
    )
    rows = [
        "1,EURUSD,Buy,07 Aug 2026 20:00:00.000,07 Aug 2026 21:50:45.162,1.10000,1.10200,"
        "1.00 Lots,200.00,25200.00",
        "2,EURUSD,Sell,08 Aug 2026 09:00:00.000,08 Aug 2026 10:05:12.001,1.10300,1.10400,"
        "1.00 Lots,-100.00,25100.00",
        "3,GBPUSD,Buy,09 Aug 2026 13:00:00.000,09 Aug 2026 14:00:00.000,1.30000,1.30150,"
        "0.50 Lots,75.00,25175.00",
    ]
    report = _read([header, *rows], "cTrader_history.csv")
    trades = report.trades.trades
    assert report.trades.sides == ["long", "short", "long"]
    assert _net(report) == [200.0, -100.0, 75.0]
    closed = trades[0].exit_time.replace(microsecond=0)
    assert closed == datetime(2026, 8, 7, 18, 50, 45, tzinfo=UTC)


def test_ctrader_net_column_in_the_balance_currency_wins() -> None:
    for order in (("Net USD", "Net EUR"), ("Net EUR", "Net USD")):
        header = (
            "ID,Symbol,Opening Direction,Opening Time (UTC+0),Closing Time (UTC+0),"
            f"Entry Price,Closing Price,Closing Quantity,{order[0]},{order[1]},Balance EUR"
        )
        rows = []
        for n, (usd, eur) in enumerate(((110.0, 100.0), (-55.0, -50.0), (22.0, 20.0)), start=13):
            net = (usd, eur) if order[0] == "Net USD" else (eur, usd)
            rows.append(
                f"{n},EURUSD,Buy,{n:02d}/03/2026 08:00:00.000,{n:02d}/03/2026 12:00:00.000,"
                f"1.08000,1.08100,1.00 Lots,{net[0]},{net[1]},25000"
            )
        assert _net(_read([header, *rows], "cTrader_history.csv")) == [100.0, -50.0, 20.0]


def test_rithmic_completed_orders_with_the_zone_named_in_words() -> None:
    lines = [
        "Completed Orders",
        "Account,Status,Buy/Sell,Qty Filled,Symbol,Exchange,Avg Fill Price,Order Type,"
        "Update Time (EDT)",
        "ACC1,Filled,B,1,ESU6,CME,5000.00,Market,2026-08-03 09:31:00",
        "ACC1,Filled,S,1,ESU6,CME,5004.00,Market,2026-08-03 10:15:00",
        "ACC1,Filled,S,2,ESU6,CME,5010.00,Limit,2026-08-04 09:40:00",
        "ACC1,Filled,B,2,ESU6,CME,5006.50,Market,2026-08-04 11:02:00",
    ]
    report = _read(lines, "rithmic_completed_orders.csv")
    trades = report.trades.trades
    assert report.trades.sides == ["long", "short"]
    assert [round(t.pnl, 2) for t in trades] == [200.0, 350.0]
    assert trades[0].entry_time == datetime(2026, 8, 3, 13, 31, tzinfo=UTC)


def test_binance_futures_with_realized_profit_and_fee_coin() -> None:
    header = "Date(UTC),Symbol,Side,Price,Quantity,Amount,Fee,Fee Coin,Realized Profit"
    rows = [
        "2026-07-01 10:00:00,ETHUSDT,BUY,3000,1,3000,1.2,USDT,0",
        "2026-07-01 12:00:00,ETHUSDT,SELL,3050,1,3050,1.22,USDT,50",
        "2026-07-02 12:00:00,ETHUSDT,SELL,3100,0.5,1550,0.0003,BNB,0",
    ]
    report = _read([header, *rows], "Export Trade History.csv")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [50.0]
    assert any("another coin" in warning for warning in report.warnings)


def test_kraken_trades() -> None:
    header = "txid,ordertxid,pair,time,type,ordertype,price,cost,fee,vol,margin,misc,ledgers"
    rows = [
        "T1,O1,XBTUSD,2026-08-01 09:00:00.1234,buy,limit,60000,600,0.96,0.01,0,,L1",
        "T2,O2,XBTUSD,2026-08-03 09:00:00.5678,sell,limit,62000,620,0.99,0.01,0,,L2",
    ]
    report = _read([header, *rows], "trades.csv")
    assert _net(report) == [18.05]


def test_coinbase_transactions() -> None:
    header = (
        "Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,"
        "Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),"
        "Fees and/or Spread,Notes"
    )
    rows = [
        "2026-08-01T10:00:00Z,Buy,SOL,10,USD,$150.00,$1500.00,$1510.00,$10.00,Bought 10 SOL",
        "2026-08-05T10:00:00Z,Receive,SOL,1,USD,$155.00,,,,Received 1 SOL",
        "2026-08-09T10:00:00Z,Sell,SOL,10,USD,$160.00,$1600.00,$1590.00,$10.00,Sold 10 SOL",
    ]
    report = _read([header, *rows], "coinbase.csv")
    assert _net(report) == [80.0]


def test_sierra_chart_trade_activity_keeps_the_fills() -> None:
    header = "ActivityType\tDateTime\tSymbol\tQuantity\tBuySell\tPrice\tFillPrice\tFilledQuantity"
    rows = [
        "Orders\t2026-09-01 09:30:00.000\tESZ6.CME\t1\tBuy\t6000\t\t",
        "Fills\t2026-09-01 09:30:01.000\tESZ6.CME\t1\tBuy\t\t6000.25\t1",
        "Fills\t2026-09-01 09:40:00.000\tESZ6.CME\t1\tSell\t\t6002.25\t1",
    ]
    report = _read([header, *rows], "TradeActivityLog.txt")
    assert [round(t.pnl, 2) for t in report.trades.trades] == [100.0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20260115;093000", datetime(2026, 1, 15, 9, 30, tzinfo=UTC)),
        ("2026-01-15, 09:30:00", datetime(2026, 1, 15, 9, 30, tzinfo=UTC)),
        ("1/15/26 09:30:00", datetime(2026, 1, 15, 9, 30, tzinfo=UTC)),
        ("01/15/2026 09:30:00 EST", datetime(2026, 1, 15, 14, 30, tzinfo=UTC)),
        ("15/01/2026 09:30:00 +01:00", datetime(2026, 1, 15, 8, 30, tzinfo=UTC)),
        ("07 Aug 2026 21:50:45", datetime(2026, 8, 7, 21, 50, 45, tzinfo=UTC)),
        ("02-Jan-2026 09:30", datetime(2026, 1, 2, 9, 30, tzinfo=UTC)),
        ("15 ene 2026", datetime(2026, 1, 15, tzinfo=UTC)),
        ("09 out 2026", datetime(2026, 10, 9, tzinfo=UTC)),
        ("08 set 2026", datetime(2026, 9, 8, tzinfo=UTC)),
        ("12 fév 2026", datetime(2026, 2, 12, tzinfo=UTC)),
        ("03 août 2026 10:00", datetime(2026, 8, 3, 10, tzinfo=UTC)),
        ("05 Mär 2026", datetime(2026, 3, 5, tzinfo=UTC)),
        ("06 Okt 2026", datetime(2026, 10, 6, tzinfo=UTC)),
        ("07 ott 2026", datetime(2026, 10, 7, tzinfo=UTC)),
        ("08 dez 2026", datetime(2026, 12, 8, tzinfo=UTC)),
    ],
)
def test_platform_time_styles(text: str, expected: datetime) -> None:
    from quant_trade.audit.universal import _times

    assert _times([text], False).values == [expected]
