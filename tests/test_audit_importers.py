"""Importers: the trader's own platform file becomes trades and a balance curve.

Fixtures under ``tests/fixtures/audit_imports`` are the synthetic samples
from ``docs/research/audit_iteration4/formats_*.json`` (no client file is
ever committed). Workbooks and larger reports are generated in the tests.
"""

from __future__ import annotations

import io
import random
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from quant_trade.audit.costs import gross_pnls
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.importers import (
    BACKTESTINGPY_CSV,
    CONTRACT_SIZE_WARNING,
    FLOATING_DRAWDOWN_WARNING,
    MT4_STATEMENT_HTML,
    MT4_TESTER_HTML,
    MT5_HISTORY_HTML,
    MT5_OPTIMIZATION_XML,
    MT5_TESTER_HTML,
    NAIVE_TIME_WARNING,
    NINJATRADER_CSV,
    QUANTCONNECT_TRADES_CSV,
    TRADINGVIEW_CSV,
    TRADINGVIEW_XLSX,
    VECTORBT_CSV,
    ImportedReport,
    ReportFormatError,
    detect_format,
    import_report,
    parse_optimization,
)
from quant_trade.audit.schema import (
    MAX_UPLOAD_BYTES,
    MIN_OBSERVATIONS,
    ParseError,
    parse_equity_csv,
)

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def utf16(data: bytes) -> bytes:
    """What the MetaTrader 5 terminal writes: UTF-16 LE with a BOM."""
    return b"\xff\xfe" + data.decode("utf-8").encode("utf-16-le")


def equity_rows(report: ImportedReport) -> list[tuple[str, float]]:
    lines = report.equity_csv.decode("utf-8").strip().splitlines()
    assert lines[0] == "timestamp,equity"
    return [(day, float(value)) for day, value in (line.split(",") for line in lines[1:])]


def gross(report: ImportedReport) -> list[float]:
    return [round(trade.pnl, 2) for trade in report.trades.trades]


def assert_recomputed_matches(report: ImportedReport) -> None:
    """The audit recomputes gross P&L from prices; it must land on the platform's."""
    recomputed = gross_pnls(report.trades.trades, report.trades.sides)
    for ours, theirs in zip(recomputed, report.trades.client_pnl, strict=True):
        assert theirs is not None
        assert ours == pytest.approx(theirs, abs=0.02)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mt5_tester.html", MT5_TESTER_HTML),
        ("mt5_history.html", MT5_HISTORY_HTML),
        ("mt4_tester.htm", MT4_TESTER_HTML),
        ("mt4_statement.htm", MT4_STATEMENT_HTML),
        ("mt5_optimization.xml", MT5_OPTIMIZATION_XML),
        ("tradingview_g3b.csv", TRADINGVIEW_CSV),
        ("tradingview_g1.csv", TRADINGVIEW_CSV),
        ("ninjatrader.csv", NINJATRADER_CSV),
        ("quantconnect_trades.csv", QUANTCONNECT_TRADES_CSV),
        ("backtestingpy_trades.csv", BACKTESTINGPY_CSV),
        ("backtestingpy_v03.csv", BACKTESTINGPY_CSV),
        ("vectorbt_trades.csv", VECTORBT_CSV),
    ],
)
def test_detects_every_fixture_by_content(name: str, expected: str) -> None:
    assert detect_format(fixture(name)) == expected
    assert detect_format(fixture(name), "misleading.txt") == expected


def test_unknown_files_are_not_detected() -> None:
    assert detect_format(b"timestamp,equity\n2024-01-01,100\n") is None
    assert detect_format(b"<html><body><p>hello</p></body></html>") is None
    assert detect_format(b"") is None


# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("encode", [lambda data: data, utf16], ids=["utf8", "utf16"])
def test_mt5_tester_pairs_partial_closes_hedges_and_reversals(encode) -> None:  # type: ignore[no-untyped-def]
    report = import_report(encode(fixture("mt5_tester.html")))
    assert report.source_format == MT5_TESTER_HTML
    # Six FIFO round trips from five closing deals: a partial close, two
    # entries closed by one deal, and a netting reversal (in/out).
    assert gross(report) == [25.0, -10.0, 27.5, 30.0, 20.0, -20.0]
    assert report.trades.sides == ["long", "long", "short", "short", "long", "short"]
    assert report.fees == {"commission": -8.4, "swap": -1.05}
    net = sum(gross(report)) + report.fees["commission"] + report.fees["swap"]
    assert net == pytest.approx(63.05)
    assert report.initial_balance == 10_000.0
    assert report.currency == "USD"
    rows = equity_rows(report)
    assert rows[0] == ("2024-01-01", 10_000.0)
    assert rows[-1] == ("2024-01-08", pytest.approx(10_063.05))
    assert [day for day, _ in rows] == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
    ]
    assert any(w.startswith(CONTRACT_SIZE_WARNING) for w in report.warnings)
    assert FLOATING_DRAWDOWN_WARNING in report.warnings
    assert NAIVE_TIME_WARNING in report.warnings
    assert any("end of the test" in w for w in report.warnings)
    assert report.metadata["strategy"] == "FixtureEA"
    assert report.metadata["inputs"] == "2"
    assert report.metadata["declared_total_net_profit"] == "63.05"
    assert report.metadata["history_quality"] == "100% real ticks"
    assert (report.metadata["start"], report.metadata["end"]) == ("2024-01-01", "2024-01-09")
    assert_recomputed_matches(report)
    # Every declared total reconciles, so no mismatch warning appears.
    assert not any("the report states" in w for w in report.warnings)


def test_mt5_tester_quantity_is_lots_times_contract_size() -> None:
    report = import_report(fixture("mt5_tester.html"))
    first = report.trades.trades[0]
    assert first.quantity == pytest.approx(0.1 * 100_000)
    assert first.return_pct == pytest.approx(25.0 / (1.1 * 10_000))


def test_mt5_localised_titles_fall_back_to_structure() -> None:
    text = fixture("mt5_tester.html").decode("utf-8")
    for english, other in (
        ("<b>Deals</b>", "<b>成交</b>"),
        ("<b>Direction</b>", "<b>方向</b>"),
        ("<b>Balance</b>", "<b>余额</b>"),
        ("Strategy Tester Report", "策略测试报告"),
        ('content="strategy tester"', 'content="x"'),
    ):
        text = text.replace(english, other)
    report = import_report(text.encode("utf-8"))
    assert report.source_format == MT5_TESTER_HTML
    assert gross(report) == [25.0, -10.0, 27.5, 30.0, 20.0, -20.0]


def test_mt5_balance_break_is_reported_not_hidden() -> None:
    text = fixture("mt5_tester.html").decode("utf-8").replace("10 022.90", "10 122.90")
    report = import_report(text.encode("utf-8"))
    assert any("Balance cell(s) do not equal" in w for w in report.warnings)


def test_mt5_declared_total_mismatch_is_reported() -> None:
    text = fixture("mt5_tester.html").decode("utf-8").replace("<b>63.05</b>", "<b>99.00</b>")
    report = import_report(text.encode("utf-8"))
    assert any("net profit: the report states 99.00" in w for w in report.warnings)


def test_mt5_history_uses_positions_and_keeps_personal_data_out() -> None:
    data = fixture("mt5_history.html")
    report = import_report(utf16(data))
    assert report.source_format == MT5_HISTORY_HTML
    assert gross(report) == [-9.0, 20.0]
    assert report.trades.sides == ["short", "long"]
    assert report.fees == {"commission": pytest.approx(-0.98), "swap": pytest.approx(-0.62)}
    assert report.initial_balance == 1_000.0
    assert report.currency == "USD"
    assert report.metadata["margin_mode"] == "Hedge"
    assert any("after the last trade ignored" in w for w in report.warnings)
    flat = " ".join(report.metadata.values()) + " ".join(report.warnings)
    assert "12345678" not in flat
    assert "Demo Trader" not in flat
    assert equity_rows(report)[-1] == ("2024-03-05", pytest.approx(1_009.40))
    assert_recomputed_matches(report)


def test_mt5_history_without_positions_pairs_deals() -> None:
    text = fixture("mt5_history.html").decode("utf-8")
    start = text.index('<tr align="center"><th colspan="14" style="height: 25px">'
                       '<div style="font: 10pt Tahoma"><b>Positions</b>')  # fmt: skip
    end = text.index('<tr align="center"><th colspan="14" style="height: 25px">'
                     '<div style="font: 10pt Tahoma"><b>Orders</b>')  # fmt: skip
    report = import_report((text[:start] + text[end:]).encode("utf-8"))
    assert report.source_format == MT5_HISTORY_HTML
    assert gross(report) == [-9.0, 20.0]
    assert report.fees["commission"] == pytest.approx(-0.98)
    assert "fee" in report.fees


def _deal_row(
    time: str,
    deal: int,
    symbol: str,
    kind: str,
    direction: str,
    volume: str,
    price: str,
    commission: float,
    profit: float,
    balance: float,
    comment: str = "",
) -> str:
    cells = [
        time,
        str(deal),
        symbol,
        kind,
        direction,
        volume,
        price,
        str(deal),
        f"{commission:.2f}",
        "0.00",
        f"{profit:.2f}",
        f"{balance:,.2f}".replace(",", " "),
        comment,
    ]
    return "<tr bgcolor=#FFFFFF align=right>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def mt5_tester_report(
    trades: int, *, seed: int = 7, deposit_on: int | None = None, start: date | None = None
) -> bytes:
    """A deterministic MT5 tester report: one EURUSD trade per business day."""
    rng = random.Random(seed)
    day = start or date(2024, 1, 2)
    balance = 10_000.0
    rows = [_deal_row(f"{day:%Y.%m.%d} 00:00:00", 1, "", "balance", "", "", "", 0, 10_000, balance)]
    deal = 2
    for index in range(trades):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        entry = round(1.1 + rng.uniform(-0.01, 0.01), 5)
        exit_ = round(entry + rng.uniform(-0.002, 0.0022), 5)
        side = "buy" if index % 3 else "sell"
        closing = "sell" if side == "buy" else "buy"
        direction = 1 if side == "buy" else -1
        profit = round((exit_ - entry) * direction * 0.1 * 100_000, 2)
        balance -= 0.7
        rows.append(
            _deal_row(
                f"{day:%Y.%m.%d} 09:00:00",
                deal,
                "EURUSD",
                side,
                "in",
                "0.1",
                f"{entry:.5f}",
                -0.7,
                0.0,
                balance,
            )  # fmt: skip
        )
        balance += profit - 0.7
        rows.append(
            _deal_row(
                f"{day:%Y.%m.%d} 15:00:00",
                deal + 1,
                "EURUSD",
                closing,
                "out",
                "0.1",
                f"{exit_:.5f}",
                -0.7,
                profit,
                balance,
            )  # fmt: skip
        )
        deal += 2
        if deposit_on is not None and index == deposit_on:
            balance += 5_000
            rows.append(
                _deal_row(
                    f"{day:%Y.%m.%d} 18:00:00",
                    deal,
                    "",
                    "balance",
                    "",
                    "",
                    "",
                    0,
                    5_000,
                    balance,
                    "Deposit",
                )  # fmt: skip
            )
            deal += 1
        day += timedelta(days=1)
    header = "".join(
        f"<td nowrap><b>{name}</b></td>"
        for name in [
            "Time",
            "Deal",
            "Symbol",
            "Type",
            "Direction",
            "Volume",
            "Price",
            "Order",
            "Commission",
            "Swap",
            "Profit",
            "Balance",
            "Comment",
        ]
    )
    html = (
        "<html><head><title>Strategy Tester Report</title>"
        '<meta name="generator" content="strategy tester"></head><body><table>'
        '<tr><td nowrap colspan="3">Initial Deposit:</td><td><b>10 000.00</b></td></tr>'
        '<tr><td nowrap colspan="3">Currency:</td><td><b>USD</b></td></tr>'
        "</table><table>"
        '<tr align="center"><th colspan="13"><b>Deals</b></th></tr>'
        f'<tr align="center" bgcolor="#E5F0FC">{header}</tr>' + "".join(rows) + "</table>"
        "</body></html>"
    )
    return html.encode("utf-8")


def test_generated_mt5_report_feeds_the_equity_parser() -> None:
    report = import_report(utf16(mt5_tester_report(90)))
    assert len(report.trades.trades) == 90
    series = parse_equity_csv(report.equity_csv)
    assert series.observations >= MIN_OBSERVATIONS
    assert series.frame["equity"].iloc[0] == 10_000.0
    assert_recomputed_matches(report)
    assert not any("do not equal" in w for w in report.warnings)


def test_deposit_mid_history_is_removed_from_returns() -> None:
    plain = import_report(mt5_tester_report(40))
    funded = import_report(mt5_tester_report(40, deposit_on=10))
    assert any("flow-adjusted index" in w for w in funded.warnings)
    assert not any("flow-adjusted index" in w for w in plain.warnings)
    plain_returns = parse_equity_csv(plain.equity_csv).returns
    funded_returns = parse_equity_csv(funded.equity_csv).returns
    # The deposit adds no return; later returns shrink because the account is larger.
    assert funded_returns.iloc[:11].tolist() == pytest.approx(plain_returns.iloc[:11].tolist())
    assert funded_returns.abs().max() < 0.01


# ---------------------------------------------------------------------------
# MetaTrader 4
# ---------------------------------------------------------------------------


def test_mt4_tester_groups_by_ticket_and_skips_cancelled_orders() -> None:
    report = import_report(fixture("mt4_tester.htm"))
    assert report.source_format == MT4_TESTER_HTML
    assert gross(report) == [-0.4, 100.0, -30.0, 25.5]
    assert report.trades.sides == ["long", "short", "long", "long"]
    assert report.fees == {}
    assert any("already includes swap and commission" in w for w in report.warnings)
    assert any("end of the test" in w for w in report.warnings)
    assert report.metadata["inputs"] == "3"
    assert report.metadata["modelling_quality"] == "90.00%"
    assert equity_rows(report)[-1] == ("2024-01-05", pytest.approx(10_095.10))


def test_mt4_cp1252_statement_with_partial_close_credit_and_flows() -> None:
    text = fixture("mt4_statement.htm").decode("utf-8").replace("Demo Trader", "José Núñez")
    report = import_report(text.encode("cp1252"))
    assert report.source_format == MT4_STATEMENT_HTML
    assert sorted(gross(report)) == [-225.0, -145.0, 200.0]
    assert report.fees["commission"] == pytest.approx(-14.0)
    assert report.fees["swap"] == pytest.approx(-10.3)
    assert report.initial_balance == 10_000.0
    assert any("credit row(s) excluded" in w for w in report.warnings)
    assert equity_rows(report)[-1] == ("2024-03-06", pytest.approx(9_805.70))
    flat = " ".join(report.metadata.values())
    assert "Núñez" not in flat and "12345678" not in flat


# ---------------------------------------------------------------------------
# TradingView
# ---------------------------------------------------------------------------


def test_tradingview_current_layout_with_bom_and_open_trade() -> None:
    report = import_report(b"\xef\xbb\xbf" + fixture("tradingview_g3b.csv"))
    assert report.source_format == TRADINGVIEW_CSV
    assert gross(report) == [52.0, -37.5]
    assert report.fees == {"commission": -6.0}
    assert report.currency == "USD"
    assert any("open trade(s)" in w for w in report.warnings)
    assert any("10,000 was assumed" in w for w in report.warnings)
    assert_recomputed_matches(report)


def test_tradingview_legacy_layout_descending_and_exit_first() -> None:
    report = import_report(fixture("tradingview_g1.csv"))
    assert gross(report) == [49.6, -41.1]
    assert report.trades.sides == ["long", "short"]
    assert "commission" not in report.fees
    # The net P&L bends the implied size to 1.02; it is snapped back to 1.
    assert report.trades.trades[0].quantity == 2.0


GERMAN_HEADER = (
    "Trade #,Typ,Datum und Uhrzeit,Signal,Preis USD,Größe (Menge),Größe (Wert),G&V netto USD,"
    "G&V netto %,Positive Exkursion USD,Positive Exkursion %,Negative Exkursion USD,"
    "Negative Exkursion %,Kumulativer G&V USD,Kumulativer G&V %"
)


def test_tradingview_german_headers_and_day_first_dates() -> None:
    rows = [
        "1,Long-Ausstieg,14/03/2025 14:00,TP,105,2,200,10,5,12,6,-3,-1.5,10,0.1",
        "1,Long-Einstieg,13/03/2025 08:00,Long,100,2,200,10,5,12,6,-3,-1.5,10,0.1",
        "2,Short-Ausstieg,18/03/2025 13:00,Offen,99,1,100,1,1,2,2,-1,-1,11,0.11",
        "2,Short-Einstieg,17/03/2025 10:00,Short,100,1,100,1,1,2,2,-1,-1,11,0.11",
    ]
    report = import_report("\n".join([GERMAN_HEADER, *rows]).encode("utf-8"))
    assert gross(report) == [10.0]
    trade = report.trades.trades[0]
    assert (trade.entry_time.day, trade.entry_time.month) == (13, 3)
    assert any("open trade(s)" in w for w in report.warnings)


def test_tradingview_unknown_language_uses_column_positions() -> None:
    header = ",".join(f"Columna {i}" for i in range(15))
    header = "Trade #,Type," + header.split(",", 2)[2]
    rows = [
        "1,Salida larga,2025-03-14 14:00,TP,105,2,200,10,5,12,6,-3,-1.5,10,0.1",
        "1,Entrada larga,2025-03-13 08:00,Long,100,2,200,10,5,12,6,-3,-1.5,10,0.1",
    ]
    report = import_report("\n".join([header, *rows]).encode("utf-8"))
    assert gross(report) == [10.0]
    assert report.trades.sides == ["long"]


def test_ambiguous_dates_are_refused_in_both_languages() -> None:
    rows = [
        "1,Exit long,04/03/2025 14:00,TP,105,2,200,10,5,12,6,-3,-1.5,10,0.1",
        "1,Entry long,03/03/2025 08:00,Long,100,2,200,10,5,12,6,-3,-1.5,10,0.1",
    ]
    header = GERMAN_HEADER.replace("Typ", "Type")
    with pytest.raises(ReportFormatError) as info:
        import_report("\n".join([header, *rows]).encode("utf-8"))
    assert info.value.code == "ambiguous_dates"
    assert "AAAA-MM-DD" in info.value.message_es


def xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    """A minimal workbook: shared strings for text, typed numbers, inline strings."""
    shared: list[str] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        entries = []
        rels = []
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            entries.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(
                f'<Relationship Id="rId{index}" Type="worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
            xml_rows = []
            for r, row in enumerate(rows, start=1):
                cells = []
                for c, value in enumerate(row):
                    ref = f"{chr(65 + c)}{r}"
                    if value is None:
                        continue
                    if isinstance(value, int | float):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    elif r == 1:
                        cells.append(
                            f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                        )
                    else:
                        shared.append(str(value))
                        cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>",
            )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(entries)}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{''.join(rels)}</Relationships>",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{escape(text)}</t></si>" for text in shared)
            + "</sst>",
        )
    return buffer.getvalue()


TV_XLSX_HEADER: list[object] = [
    "Trade #",
    "Type",
    "Date and time",
    "Signal",
    "Price USDT",
    "Size (qty)",
    "Size (value)",
    "Net P&L USDT",
    "Net P&L %",
    "Favorable excursion USDT",
    "Favorable excursion %",
    "Adverse excursion USDT",
    "Adverse excursion %",
    "Cumulative P&L USDT",
    "Cumulative P&L %",
]


def test_tradingview_xlsx_reads_serial_dates_and_properties() -> None:
    workbook = xlsx(
        {
            "Performance": [["", "All USDT"], ["Initial capital", 100]],
            "List of trades": [
                TV_XLSX_HEADER,
                [
                    1,
                    "Exit long",
                    44952.375,
                    "TP1 VWAP",
                    1618.65,
                    0.0128,
                    19.97,
                    0.71,
                    3.53,
                    0.83,
                    4.13,
                    -0.48,
                    -2.42,
                    0.63,
                    0.63,
                ],
                [
                    1,
                    "Entry long",
                    44952,
                    "Long",
                    1560.29,
                    0.0128,
                    19.97,
                    0.71,
                    3.53,
                    0.83,
                    4.13,
                    -0.48,
                    -2.42,
                    0.63,
                    0.63,
                ],
            ],  # fmt: skip
            "Properties": [
                ["name", "value"],
                ["Symbol", "OKX:ETHUSDT.P"],
                ["Currency", "USDT"],
                ["Length", "20"],
                ["Initial capital", "100"],
                ["Commission", "0.1"],
            ],
        }
    )
    assert detect_format(workbook) == TRADINGVIEW_XLSX
    report = import_report(workbook)
    assert report.source_format == TRADINGVIEW_XLSX
    assert gross(report) == [0.71]
    trade = report.trades.trades[0]
    assert trade.entry_time.isoformat() == "2023-01-26T00:00:00+00:00"
    assert trade.exit_time.isoformat() == "2023-01-26T09:00:00+00:00"
    assert report.initial_balance == 100.0
    assert report.currency == "USDT"
    assert report.metadata["symbol"] == "OKX:ETHUSDT.P"
    assert report.metadata["inputs"] == "1"
    assert any("Properties: Initial capital" in w for w in report.warnings)


def test_xlsx_that_inflates_past_the_limit_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"\0" * 41_000_000)
    with pytest.raises(ReportFormatError) as info:
        import_report(buffer.getvalue())
    assert info.value.code == "xlsx_too_large"
    assert detect_format(buffer.getvalue()) is None


# ---------------------------------------------------------------------------
# NinjaTrader, QuantConnect, backtesting.py, vectorbt
# ---------------------------------------------------------------------------


def test_ninjatrader_money_formats_and_fees() -> None:
    report = import_report(fixture("ninjatrader.csv"))
    assert gross(report) == [312.5, -400.0]
    assert report.fees == {"commission": pytest.approx(-15.24)}
    assert any("ES 03-26 x50" in w for w in report.warnings)
    assert report.metadata["strategy"] == "DemoStrategy"
    assert_recomputed_matches(report)


def test_ninjatrader_european_locale() -> None:
    text = (
        "Trade number;Instrument;Account;Strategy;Market pos.;Qty;Entry price;Exit price;"
        "Entry time;Exit time;Entry name;Exit name;Profit;Cum. net profit;Commission;MAE;MFE;"
        "ETD;Bars;\n"
        "1;ES 03-26;Backtest;S;Long;1;6010,25;6016,50;16/1/2026 9:35:00;16/1/2026 10:05:00;"
        "L;PT;307,42 €;307,42 €;5,08 €;62,50 €;325,00 €;17,58 €;6;\n"
        "2;ES 03-26;Backtest;S;Short;1;6021,00;6025,00;17/1/2026 11:10:00;17/1/2026 11:25:00;"
        "S;SL;-205,08 €;102,34 €;5,08 €;200,00 €;75,00 €;280,08 €;3;\n"
    )
    report = import_report(text.encode("utf-8"))
    assert gross(report) == [312.5, -200.0]
    assert report.trades.trades[0].entry_time.day == 16


def test_quantconnect_gross_pnl_and_utc_times() -> None:
    report = import_report(fixture("quantconnect_trades.csv"))
    assert gross(report) == [180.0, -125.0]
    assert report.fees == {"commission": -2.0}
    assert report.metadata["symbol"] == "SPY"
    assert NAIVE_TIME_WARNING not in report.warnings


def test_backtestingpy_versions() -> None:
    current = import_report(fixture("backtestingpy_trades.csv"))
    assert gross(current) == [149.24, -277.95]
    assert current.trades.sides == ["long", "short"]
    assert current.fees == {"commission": pytest.approx(-3.89)}
    legacy = import_report(fixture("backtestingpy_v03.csv"))
    assert gross(legacy) == [2071.6]
    assert legacy.fees == {}
    assert any("fill prices" in w for w in legacy.warnings)


def test_vectorbt_closed_trades_and_variants() -> None:
    report = import_report(fixture("vectorbt_trades.csv"))
    assert gross(report) == [950.0, -360.0]
    assert report.fees == {"commission": pytest.approx(-79.03)}
    assert any("open trade(s)" in w for w in report.warnings)
    # Trades close on a Saturday, so the curve uses calendar days.
    days = [day for day, _ in equity_rows(report)]
    assert "2024-01-06" in days
    text = fixture("vectorbt_trades.csv").decode("utf-8")
    extra = "3,3,ETH-USD,1.0,2024-01-02,2300.0,1.0,2024-01-03,2310.0,1.0,8.0,0.0035,Long,Closed,3\n"
    variants = import_report((text + extra).encode("utf-8"))
    assert variants.metadata["variants"] == "2"
    assert len(variants.trades.trades) == 2


# ---------------------------------------------------------------------------
# Starting balance, limits and errors
# ---------------------------------------------------------------------------


def test_declared_initial_balance_is_used_only_when_the_file_has_none() -> None:
    declared = import_report(fixture("quantconnect_trades.csv"), initial_balance=50_000)
    assert declared.initial_balance == 50_000
    assert equity_rows(declared)[0][1] == 50_000
    assert not any("was assumed" in w for w in declared.warnings)
    stated = import_report(fixture("mt5_tester.html"), initial_balance=50_000)
    assert stated.initial_balance == 10_000


def test_balance_that_goes_below_zero_asks_for_the_real_balance() -> None:
    assert import_report(fixture("backtestingpy_v03.csv"), initial_balance=1_000).trades
    text = fixture("backtestingpy_trades.csv").decode("utf-8").replace("-279.9", "-20000")
    with pytest.raises(ReportFormatError) as info:
        import_report(text.encode("utf-8"))
    assert info.value.code == "balance_not_positive"


def test_optimisation_file_is_not_a_report() -> None:
    with pytest.raises(ReportFormatError) as info:
        import_report(fixture("mt5_optimization.xml"))
    assert info.value.code == "optimization_file"


def test_unknown_and_oversized_files_raise_parse_errors() -> None:
    with pytest.raises(ParseError) as info:
        import_report(b"timestamp,equity\n2024-01-01,100\n2024-01-02,101\n")
    assert isinstance(info.value, ReportFormatError)
    assert info.value.code == "unknown_format"
    assert "MetaTrader" in str(info.value) and "MetaTrader" in info.value.message_es
    with pytest.raises(ReportFormatError) as big:
        import_report(b"x" * (MAX_UPLOAD_BYTES + 1))
    assert big.value.code == "file_too_large"
    with pytest.raises(ReportFormatError) as empty:
        import_report(b"   ")
    assert empty.value.code == "empty_file"


def test_report_with_no_closed_trades_names_the_problem() -> None:
    text = fixture("tradingview_g3b.csv").decode("utf-8").splitlines()
    only_open = "\n".join([text[0], text[5], text[6]])
    with pytest.raises(ReportFormatError) as info:
        import_report(only_open.encode("utf-8"))
    assert info.value.code == "no_closed_trades"


# ---------------------------------------------------------------------------
# MetaTrader 5 optimisation
# ---------------------------------------------------------------------------


def optimisation_xml(passes: int) -> str:
    header = ["Pass", "Result", "Profit"] + [
        "Expected Payoff",
        "Profit Factor",
        "Recovery Factor",
        "Sharpe Ratio",
        "Custom",
        "Equity DD %",
        "Trades",
        "FastMA",
        "SlowMA",
    ]

    def row(values: list[str], kind: str) -> str:
        return (
            "<Row>"
            + "".join(f'<Cell><Data ss:Type="{kind}">{value}</Data></Cell>' for value in values)
            + "</Row>"
        )

    body = [row(header, "String")]
    for index in range(passes):
        body.append(row([str(index), "10000", "5", "1", "1.1", "0.5", "0.2", "0", "3", "40",
                         str(5 + index % 10), str(20 + index // 10)], "Number"))  # fmt: skip
    return (
        '<?xml version="1.0"?>\n<?mso-application progid="Excel.Sheet"?>\n'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        + "".join(body)
        + "</Table></Worksheet></Workbook>"
    )


def test_optimisation_counts_passes_and_names_parameters() -> None:
    summary = parse_optimization(fixture("mt5_optimization.xml"))
    assert summary.passes == 1
    assert summary.parameters == ["FastMA"]
    big = parse_optimization(utf16(optimisation_xml(250).encode("utf-8")))
    assert big.source_format == MT5_OPTIMIZATION_XML
    assert big.passes == 250
    assert big.parameters == ["FastMA", "SlowMA"]


def test_optimisation_refuses_doctypes_and_other_files() -> None:
    hostile = optimisation_xml(3).replace(
        "<?mso-application", '<!DOCTYPE x [<!ENTITY a "aaaa">]><?mso-application'
    )
    with pytest.raises(ReportFormatError) as info:
        parse_optimization(hostile.encode("utf-8"))
    assert info.value.code == "xml_doctype"
    with pytest.raises(ReportFormatError) as other:
        parse_optimization(fixture("mt5_tester.html"))
    assert other.value.code == "not_optimization"


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def test_every_warning_and_error_message_passes_the_profit_claim_guard() -> None:
    texts: list[str] = []
    for path in sorted(FIXTURES.iterdir()):
        if path.suffix == ".xml":
            texts.extend(parse_optimization(path.read_bytes()).warnings)
            continue
        report = import_report(path.read_bytes())
        texts.extend(report.warnings)
        texts.extend(report.metadata.values())
    for data in (b"nope,nope\n1,2\n", fixture("mt5_optimization.xml"), b"x" * 10):
        try:
            import_report(data)
        except ReportFormatError as error:
            texts.extend([str(error), error.message_es])
    assert texts
    assert_report_clean(*texts)
