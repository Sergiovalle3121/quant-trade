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
    ],
)
def test_platform_time_styles(text: str, expected: datetime) -> None:
    from quant_trade.audit.universal import _times

    assert _times([text], False).values == [expected]
