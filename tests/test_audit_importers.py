"""Importers: the trader's own platform file becomes trades and a balance curve.

Fixtures under ``tests/fixtures/audit_imports`` are the synthetic samples
from ``docs/research/audit_iteration4/formats_*.json`` (no client file is
ever committed). Workbooks and larger reports are generated in the tests.
"""

from __future__ import annotations

import io
import random
import re
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
    CONVERSION_DRIFT_WARNING,
    FLOATING_DRAWDOWN_WARNING,
    MT4_STATEMENT_HTML,
    MT4_TESTER_HTML,
    MT5_HISTORY_HTML,
    MT5_HISTORY_XLSX,
    MT5_OPTIMIZATION_XML,
    MT5_TESTER_HTML,
    MT5_TESTER_XLSX,
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
    # One trade per closing deal, as the tester counts "Total Trades": a
    # partial close, two entries closed by one deal (one trade at their
    # volume-weighted entry), and a netting reversal (in/out).
    assert gross(report) == [25.0, -10.0, 57.5, 20.0, -20.0]
    assert report.trades.sides == ["long", "long", "short", "long", "short"]
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
    assert gross(report) == [25.0, -10.0, 57.5, 20.0, -20.0]


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
    assert info.value.localized("es") == info.value.message_es
    assert info.value.localized("en") == str(info.value)
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


# ---------------------------------------------------------------------------
# Layouts found in real public reports (docs/research/audit_iteration4/
# real_reports_check.md). Each fixture below is synthetic: it reproduces the
# structure of a real file, never its contents.
# ---------------------------------------------------------------------------


def _mt5_tester_variant(*replacements: tuple[str, str]) -> bytes:
    text = fixture("mt5_tester.html").decode("utf-8")
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text.encode("utf-8")


def test_mt5_build_1940_headers_trade_and_profit_column() -> None:
    # Build 1940 wrote "Trade" and "Profit Column" in the Deals header,
    # "Net profit" in the summary and the deals count under "Total Trades".
    report = import_report(
        _mt5_tester_variant(
            ("<b>Deal</b>", "<b>Trade</b>"),
            ("<b>Profit</b>", "<b>Profit Column</b>"),
            ("Total Net Profit:", "Net profit:"),
            ("Total Deals:", "Total Trades:"),
        )
    )
    assert gross(report) == [25.0, -10.0, 57.5, 20.0, -20.0]
    assert report.initial_balance == 10_000.0
    assert equity_rows(report)[-1] == ("2024-01-08", pytest.approx(10_063.05))
    assert report.metadata["declared_total_net_profit"] == "63.05"
    assert report.metadata["declared_total_trades"] == "5"
    assert not any("the report states" in w for w in report.warnings)


RUSSIAN_MT5 = (
    ("Expert:", "Советник:"),
    ("Symbol:", "Символ:"),
    ("Period:", "Период:"),
    ("Currency:", "Валюта:"),
    ("Initial Deposit:", "Начальный депозит:"),
    ("Leverage:", "Плечо:"),
    ("History Quality:", "Качество истории:"),
    ("Total Net Profit:", "Чистая прибыль:"),
    ("Total Trades:", "Всего трейдов:"),
    ("Total Deals:", "Всего сделок:"),
    ("<b>Deals</b>", "<b>Сделки</b>"),
    ("<b>Deal</b>", "<b>Сделка</b>"),
    ("<b>Direction</b>", "<b>Направление</b>"),
    ("<b>Commission</b>", "<b>Комиссия</b>"),
    ("<b>Swap</b>", "<b>Своп</b>"),
    ("<b>Profit</b>", "<b>Прибыль</b>"),
    ("<b>Balance</b>", "<b>Баланс</b>"),
    ("Strategy Tester Report", "Отчет Тестера стратегий"),
)
SPANISH_MT5 = (
    ("Initial Deposit:", "Depósito inicial:"),
    ("Total Net Profit:", "Beneficio Neto:"),
    ("Total Trades:", "Total de Trades:"),
    ("Total Deals:", "Total de transacciones:"),
)
#: The labels a real Spanish MetaTrader 5 terminal prints (public reports,
#: docs/research/audit_iteration4/mt_languages_check.md), which differ from the help.
SPANISH_MT5_TERMINAL = (
    ("Initial Deposit:", "Depósito inicial:"),
    ("Total Net Profit:", "Beneficio Neto:"),
    ("Total Trades:", "Total de operaciones ejecutadas:"),
    ("Total Deals:", "Total de transacciones:"),
)


#: The labels of real Italian MetaTrader 5 tester reports (same document).
ITALIAN_MT5 = (
    ("Initial Deposit:", "Deposito Iniziale:"),
    ("Currency:", "Valuta:"),
    ("Total Net Profit:", "Profitto Totale Netto:"),
    ("Total Trades:", "Numero di Operazioni di Trading Totali:"),
    ("Total Deals:", "Affari Totali:"),
)


@pytest.mark.parametrize(
    "labels",
    [RUSSIAN_MT5, SPANISH_MT5, SPANISH_MT5_TERMINAL, ITALIAN_MT5],
    ids=["ru", "es", "es-terminal", "it"],
)
def test_mt5_summary_labels_in_other_languages(labels: tuple[tuple[str, str], ...]) -> None:
    report = import_report(utf16(_mt5_tester_variant(*labels)))
    assert report.source_format == MT5_TESTER_HTML
    assert gross(report) == [25.0, -10.0, 57.5, 20.0, -20.0]
    assert report.initial_balance == 10_000.0
    assert report.metadata["declared_total_net_profit"] == "63.05"
    assert report.metadata["declared_total_trades"] == "5"
    assert report.metadata["declared_total_deals"] == "9"
    assert report.currency == "USD"
    assert not any("the report states" in w for w in report.warnings)


BALANCE_DRAWDOWN_ROW = (
    '<tr align="right"><td nowrap colspan="3">Total Deals:</td>',
    '<tr align="right"><td nowrap colspan="3">Balance Drawdown Maximal:</td>'
    "<td nowrap><b>{value} (0.22%)</b></td></tr>"
    '<tr align="right"><td nowrap colspan="3">Total Deals:</td>',
)


def test_mt5_balance_drawdown_is_checked_against_the_deals() -> None:
    old, new = BALANCE_DRAWDOWN_ROW
    # The Balance column falls from 10 085.05 to 10 063.05: 22.00.
    report = import_report(_mt5_tester_variant((old, new.format(value="22.00"))))
    assert report.metadata["declared_balance_drawdown_maximal"] == "22.00 (0.22%)"
    assert not any("the report states" in w for w in report.warnings)
    edited = import_report(_mt5_tester_variant((old, new.format(value="12.00"))))
    assert any(
        "balance drawdown maximal: the report states 12.00 but the rows add up to 22.00" in w
        for w in edited.warnings
    )


def _as_workbook_rows(html: bytes) -> list[list[object]]:
    """The rows the terminal's XLSX export writes for the same report.

    Summary labels and values are spread over merged cells (empty cells in
    between) and numbers are typed; table rows keep their columns.
    """
    from quant_trade.audit.importers import _read_html, decode_text

    rows: list[list[object]] = []
    for row in _read_html(decode_text(html)).rows:
        values: list[object] = []
        for text in row.texts:
            plain = text.replace(" ", "")
            try:
                number: object = float(plain)
            except ValueError:
                number = text or None
            values.append(number)
        if values and isinstance(values[0], str) and values[0].endswith(":"):
            spread: list[object] = []
            for value in values:
                spread.extend([value, None, None])
            values = spread
        rows.append(values)
    return rows


@pytest.mark.parametrize(
    ("name", "expected"),
    [("mt5_tester.html", MT5_TESTER_XLSX), ("mt5_history.html", MT5_HISTORY_XLSX)],
)
def test_mt5_xlsx_export_reads_like_the_html_report(name: str, expected: str) -> None:
    html_report = import_report(fixture(name))
    workbook = xlsx({"Sheet1": _as_workbook_rows(fixture(name))})
    assert detect_format(workbook, "report.xlsx") == expected
    report = import_report(workbook)
    assert report.source_format == expected
    assert gross(report) == gross(html_report)
    assert report.initial_balance == html_report.initial_balance
    assert report.fees == html_report.fees
    assert equity_rows(report) == equity_rows(html_report)
    assert report.metadata.get("declared_total_net_profit") is not None
    assert not any("the report states" in w for w in report.warnings)


def test_mt4_statement_before_build_600_has_no_taxes_column() -> None:
    text = fixture("mt4_statement.htm").decode("utf-8")
    text = text.replace("<td>Commission</td><td>Taxes</td>", "<td>Commission</td>")
    text = re.sub(
        r"(<td class=mspt>-?[\d.]+</td>)<td class=mspt>0\.00</td>(<td class=mspt>-?[\d.]+</td>"
        r"<td class=mspt>-?[\d ,.]+</td></tr>)",
        r"\1\2",
        text,
    )
    report = import_report(text.encode("cp1252"))
    modern = import_report(fixture("mt4_statement.htm"))
    assert report.source_format == MT4_STATEMENT_HTML
    assert gross(report) == gross(modern)
    assert report.fees == {"commission": -14.0, "swap": -10.3, "fee": 0.0}
    assert report.initial_balance == modern.initial_balance


NUMBERED_MT4_STATEMENT = """<html><head><title>Statement: '000000 ', Name</title></head><body>
<table>
<tr><td>A/C No: 0000000</td><td>Name: Name</td><td>2024.03.08 18:30 (server time)</td></tr>
<tr><td colspan=15><b>Closed Transactions:</b></td></tr>
<tr><td>N</td><td>Ticket</td><td>Open Time</td><td>Type</td><td>Lots</td><td>Symbol</td>
<td>Price</td><td>S/L</td><td>T/P</td><td>Close Time</td><td>Price</td><td>Commis</td>
<td>Swap</td><td>Trade P/L</td><td>Comment</td></tr>
<tr><td>1</td><td>100</td><td>2024.03.01 08:00</td><td>balance</td><td>Deposit</td>
<td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>25000.00</td>
<td>Deposit</td></tr>
<tr><td>2</td><td>101</td><td>2024.03.04 09:15</td><td>buy</td><td>1.00</td><td>eurusd</td>
<td>1.0850</td><td>0.0000</td><td>0.0000</td><td>2024.03.04 11:40</td><td>1.0870</td>
<td>-7.00</td><td>0.00</td><td>200.00</td><td>EA_one</td></tr>
<tr><td>Total for:EA_one</td><td>200.00</td><td>Profit Factor: 0.00</td><td></td></tr>
<tr><td>3</td><td>102</td><td>2024.03.05 10:00</td><td>sell</td><td>0.50</td><td>eurusd</td>
<td>1.0900</td><td>0.0000</td><td>0.0000</td><td>2024.03.06 09:30</td><td>1.0930</td>
<td>-3.50</td><td>-1.20</td><td>-150.00</td><td>EA_two</td></tr>
</table></body></html>"""


def test_mt4_statement_with_row_numbers_and_comments() -> None:
    report = import_report(NUMBERED_MT4_STATEMENT.encode("cp1252"))
    assert report.source_format == MT4_STATEMENT_HTML
    assert gross(report) == [200.0, -150.0]
    assert report.trades.sides == ["long", "short"]
    assert report.initial_balance == 25_000.0
    assert report.fees == {"commission": -10.5, "swap": -1.2, "fee": 0.0}
    assert equity_rows(report)[-1][1] == pytest.approx(25_000 + 50 - 11.7)


def _mt5_deals_report(deals: list[tuple[str, str, str, str, float, float, float]]) -> bytes:
    """A minimal MT5 tester report: (time, symbol, type, direction, volume, price, profit)."""
    balance = 10_000.0
    rows = [
        "<tr><td>2024.01.01 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10000.00</td><td>10000.00</td>"
        "<td></td></tr>"
    ]
    for number, (moment, symbol, kind, direction, volume, price, profit) in enumerate(
        deals, start=2
    ):
        balance += profit
        rows.append(
            f"<tr><td>{moment}</td><td>{number}</td><td>{symbol}</td><td>{kind}</td>"
            f"<td>{direction}</td><td>{volume}</td><td>{price}</td><td>{number}</td>"
            f"<td>0.00</td><td>0.00</td><td>{profit:.2f}</td><td>{balance:.2f}</td><td></td></tr>"
        )
    return (
        "<html><head><title>Strategy Tester Report</title></head><body><table>"
        "<tr><td>Initial Deposit:</td><td>10 000.00</td></tr>"
        '<tr bgcolor="#E5F0FC"><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td>'
        "<td>Direction</td><td>Volume</td><td>Price</td><td>Order</td><td>Commission</td>"
        "<td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td></tr>"
        + "".join(rows)
        + "</table></body></html>"
    ).encode("utf-8")


def test_mt5_hedging_close_takes_the_entry_its_profit_explains() -> None:
    # Two EURUSD buys of the same volume are open; the first close is at a
    # profit only the SECOND entry explains (a hedging EA closing its newer
    # position first). First-in first-out would pair it with the older one.
    deals = [
        ("2024.01.02 09:00:00", "EURUSD", "buy", "in", 0.1, 1.1000, 0.0),
        ("2024.01.02 10:00:00", "EURUSD", "sell", "out", 0.1, 1.1010, 10.0),
        ("2024.01.02 11:00:00", "EURUSD", "buy", "in", 0.1, 1.1000, 0.0),
        ("2024.01.02 12:00:00", "EURUSD", "sell", "out", 0.1, 1.0990, -10.0),
        ("2024.01.03 09:00:00", "EURUSD", "buy", "in", 0.1, 1.1000, 0.0),
        ("2024.01.03 09:30:00", "EURUSD", "buy", "in", 0.1, 1.1050, 0.0),
        ("2024.01.03 10:00:00", "EURUSD", "sell", "out", 0.1, 1.1060, 10.0),
        ("2024.01.03 11:00:00", "EURUSD", "sell", "out", 0.1, 1.1020, 20.0),
        ("2024.01.04 09:00:00", "EURUSD", "sell", "in", 0.1, 1.1000, 0.0),
        ("2024.01.04 10:00:00", "EURUSD", "buy", "out", 0.1, 1.0970, 30.0),
    ]
    report = import_report(_mt5_deals_report(deals))
    assert gross(report) == [10.0, -10.0, 10.0, 20.0, 30.0]
    entries = [trade.entry_price for trade in report.trades.trades]
    assert entries == pytest.approx([1.1000, 1.1000, 1.1050, 1.1000, 1.1000])
    assert_recomputed_matches(report)
    assert any(w.startswith("hedging account") for w in report.warnings)


def test_mt5_conversion_drift_is_sized_per_trade() -> None:
    # USDJPY in a USD account: 0.1 lot moving 0.50 yen pays 5 000 yen,
    # converted at each close's own rate, so the USD per point drifts.
    deals = []
    for day, rate in enumerate((140.0, 145.0, 150.0, 155.0), start=2):
        profit = round(0.5 * 0.1 * 100_000 / rate, 2)
        deals += [
            (f"2024.01.0{day} 09:00:00", "USDJPY", "buy", "in", 0.1, rate - 0.5, 0.0),
            (f"2024.01.0{day} 15:00:00", "USDJPY", "sell", "out", 0.1, rate, profit),
        ]
    report = import_report(_mt5_deals_report(deals))
    assert any(w.startswith(CONVERSION_DRIFT_WARNING) for w in report.warnings)
    assert_recomputed_matches(report)
    sizes = [trade.quantity for trade in report.trades.trades]
    assert sizes[0] > sizes[-1]


def test_one_contract_size_is_kept_when_profits_agree() -> None:
    report = import_report(fixture("mt5_tester.html"))
    assert not any(w.startswith(CONVERSION_DRIFT_WARNING) for w in report.warnings)


def test_new_real_layout_warnings_have_spanish() -> None:
    from quant_trade.audit.i18n import spanish

    old, new = BALANCE_DRAWDOWN_ROW
    drift = []
    for day, rate in enumerate((140.0, 145.0, 150.0, 155.0), start=2):
        profit = round(0.5 * 0.1 * 100_000 / rate, 2)
        drift += [
            (f"2024.01.0{day} 09:00:00", "USDJPY", "buy", "in", 0.1, rate - 0.5, 0.0),
            (f"2024.01.0{day} 15:00:00", "USDJPY", "sell", "out", 0.1, rate, profit),
        ]
    hedged = [
        ("2024.01.02 09:00:00", "EURUSD", "buy", "in", 0.1, 1.1000, 0.0),
        ("2024.01.02 09:30:00", "EURUSD", "buy", "in", 0.1, 1.1050, 0.0),
        ("2024.01.02 10:00:00", "EURUSD", "sell", "out", 0.1, 1.1060, 10.0),
        ("2024.01.02 11:00:00", "EURUSD", "sell", "out", 0.1, 1.1020, 20.0),
    ]
    reports = [
        import_report(_mt5_tester_variant((old, new.format(value="12.00")))),
        import_report(_mt5_deals_report(drift)),
        import_report(_mt5_deals_report(hedged)),
    ]
    warnings = [w for report in reports for w in report.warnings]
    assert any("balance drawdown maximal" in w for w in warnings)
    assert any(w.startswith(CONVERSION_DRIFT_WARNING) for w in warnings)
    assert any(w.startswith("hedging account") for w in warnings)
    assert [w for w in warnings if spanish(w) is None] == []


def test_tradingview_rounded_small_pnl_is_not_another_contract_size() -> None:
    """A one-unit forex trade that made 0.00127 is printed 0.001: that is
    rounding, not a contract size of 0.79 or a hidden cost."""
    from datetime import UTC, datetime

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs, printed_step

    assert printed_step(0.001) == pytest.approx(0.001)
    assert printed_step(-0.0005) == pytest.approx(0.0001)
    assert printed_step(437.5) == pytest.approx(0.1)
    header = (
        "Trade #,Type,Date/Time,Signal,Price USD,Position size (qty),Position size (value),"
        "Net P&L USD,Net P&L %,Run-up USD,Run-up %,Drawdown USD,Drawdown %,"
        "Cumulative P&L USD,Cumulative P&L %"
    )
    lines = [header]
    price, cumulative = 1.1295, 0.0
    for number in range(1, 41):
        move = (0.00127 if number % 3 else -0.00212) * (1 if number % 2 else -1)
        side = "long" if number % 2 else "short"
        exit_price = round(price + (move if side == "long" else -move), 5)
        pnl = round(move, 3) or (0.001 if move > 0 else -0.001)
        cumulative = round(cumulative + pnl, 3)
        day = f"2022-01-{number % 28 + 1:02d}"
        for kind, when, at in (
            ("Entry", f"{day}T09:00:00-0500", price),
            ("Exit", f"{day}T15:00:00-0500", exit_price),
        ):
            lines.append(
                f"{number},{kind} {side},{day},sig,{at},1,{price},{pnl},0.1,0.003,0.2,"
                f"-0.002,-0.2,{cumulative},0".replace(f",{day},", f",{when},", 1)
            )
        price = exit_price
    data = ("\n".join(lines) + "\n").encode()
    report = import_report(data, "trades.csv")
    assert all(trade.quantity == 1.0 for trade in report.trades.trades)
    assert not any("contract size" in warning for warning in report.warnings)
    result = run_audit(
        build_inputs(None, DeclaredMetadata(), report_bytes=data, report_filename="trades.csv"),
        now=datetime(2026, 1, 1, tzinfo=UTC),
        audit_id="tv-round",
        bootstrap_samples=20,
    )
    assert "TRADE_PNL_MISMATCH" not in {flag["code"] for flag in result.red_flags}


def test_spanish_terminal_labels_map_to_the_english_names() -> None:
    from quant_trade.audit.importers import _MT5_LABEL_ALIASES

    real = {
        "Expert": "Experto",
        "Company": "Corredor",
        "Total Trades": "Total de operaciones ejecutadas",
        "Balance Drawdown Maximal": "Reducción máxima del balance",
        "Equity Drawdown Maximal": "Reducción máxima de la equidad",
        "Equity Drawdown Relative": "Reducción relativa de la equidad",
        "Profit Factor": "Factor de Beneficio",
    }
    for english, spanish in real.items():
        assert spanish.lower() in {alias.lower() for alias in _MT5_LABEL_ALIASES[english]}


def _with_decimal_commas(html: bytes) -> bytes:
    """The fixture as a terminal set to Spanish or Portuguese could print it.

    Every figure's decimal point becomes a comma (``10 000,00``, ``0,2 / 0,2``);
    dates such as ``2024.01.02`` keep their dots. No public report written
    this way was found, so this synthetic case guards the reader.
    """
    text = html.decode("utf-8")
    text = re.sub(r"(?<=[>\s(/])(-?\d[\d ]*)\.(\d+)(?=[<%)\s/])", r"\1,\2", text)
    assert "10 000,00" in text and "2024.01.02" in text
    return text.encode("utf-8")


def test_mt5_report_with_decimal_commas_reads_the_same() -> None:
    from quant_trade.audit.report import _lead_number

    plain = import_report(fixture("mt5_tester.html"))
    commas = import_report(_with_decimal_commas(fixture("mt5_tester.html")))
    assert gross(commas) == gross(plain) == [25.0, -10.0, 57.5, 20.0, -20.0]
    assert commas.initial_balance == plain.initial_balance == 10_000.0
    assert [t.quantity for t in commas.trades.trades] == [t.quantity for t in plain.trades.trades]
    assert [t.entry_price for t in commas.trades.trades] == [
        t.entry_price for t in plain.trades.trades
    ]
    assert commas.fees == plain.fees
    assert _lead_number(commas.metadata["declared_total_net_profit"]) == 63.05


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 234,56", 1234.56),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1,234", 1234.0),
        ("-12,5", -12.5),
        ("(1 234,56)", -1234.56),
        ("12,345,678", 12_345_678.0),
    ],
)
def test_numbers_with_a_decimal_comma(text: str, expected: float) -> None:
    from quant_trade.audit.importers import _num

    assert _num(text) == expected
