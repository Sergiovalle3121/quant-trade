"""Files that used to crash, hang or exhaust memory: each one now gets a
clear answer quickly, and nothing here reaches the network."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, synthetic_mt5_report

from quant_trade.audit import analytics, importers
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import spanish
from quant_trade.audit.importers import ReportFormatError, import_report, read_xlsx
from quant_trade.audit.redflags import _grid_and_concurrency
from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs, parse_equity_csv
from quant_trade.core.models import Trade

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _curve(values: list[float], *, freq: str = "B", column: str = "equity") -> bytes:
    stamps = pd.date_range("2021-01-04", periods=len(values), freq=freq)
    return csv_bytes(pd.DataFrame({"timestamp": stamps, column: values}))


# --- equity that reaches zero ----------------------------------------------


def test_equity_that_goes_below_zero_is_refused_with_the_date() -> None:
    values = [100.0 - i for i in range(150)]  # a cumulative P&L style curve
    with pytest.raises(ParseError) as info:
        parse_equity_csv(_curve(values))
    assert info.value.code == "equity_not_positive"
    assert "2021-05-24" in str(info.value)  # row 100, where it reaches 0
    assert "saldo de la cuenta" in info.value.message_es
    assert find_claims(str(info.value)) == []
    assert find_claims(info.value.message_es) == []


def test_cumulative_profit_starting_at_zero_is_refused() -> None:
    with pytest.raises(ParseError) as info:
        parse_equity_csv(_curve([0.0, 5.0, 12.0, 9.0]))
    assert info.value.code == "equity_not_positive"


def test_return_of_minus_100_percent_is_refused() -> None:
    returns = [0.01, -0.02, -1.0, 0.03]
    with pytest.raises(ParseError) as info:
        parse_equity_csv(_curve(returns, column="return"))
    assert info.value.code == "return_below_total_loss"
    assert find_claims(info.value.message_es) == []


# --- curves logged faster than the one-year horizon can hold ----------------


def test_curve_logged_every_second_is_audited_without_huge_memory() -> None:
    # 300 rows one second apart infer ~31.5 million periods per year: a
    # one-year path per sample would need gigabytes.
    stamps = pd.date_range("2024-03-01 10:00:00", periods=300, freq="s")
    rng = np.random.default_rng(1)
    equity = 10_000 * np.cumprod(1 + rng.normal(0, 0.001, 300))
    data = csv_bytes(pd.DataFrame({"timestamp": stamps, "equity": equity}))
    inputs = build_inputs(data, DeclaredMetadata())
    returns = inputs.equity.frame["ret"].dropna()
    risk = analytics.drawdown_risk(returns, periods_per_year=inputs.periods_per_year, seed=0)
    assert risk["max_drawdown"]["p95"]["evidence"] == "NOT_MEASURED"
    assert risk["max_drawdown"]["p95"]["note"] == analytics.TOO_SHORT_FOR_HORIZON
    assert spanish(analytics.TOO_SHORT_FOR_HORIZON)


def test_minute_curve_is_compounded_into_short_paths() -> None:
    rng = np.random.default_rng(2)
    returns = rng.normal(0.00001, 0.0005, 40_000)
    risk = analytics.drawdown_risk(returns, periods_per_year=525_960, samples=300, seed=0)
    method = risk["method"]
    assert method["periods_per_step"] == 53
    assert method["horizon_periods"] >= 525_960
    assert method["observations"] == 40_000
    assert risk["max_drawdown"]["p50"]["evidence"] == "MEASURED"
    # The fan and the time under water are reported in the uploaded periods.
    assert risk["fan"]["period"][-1] >= 525_960 - 53
    assert risk["longest_underwater_periods"]["p50"]["value"] % 53 == 0


def test_daily_curve_is_not_compounded() -> None:
    returns = np.random.default_rng(3).normal(0.0005, 0.01, 500)
    risk = analytics.drawdown_risk(returns, periods_per_year=252, samples=200, seed=0)
    assert risk["method"]["periods_per_step"] == 1
    assert risk["method"]["horizon_periods"] == 252


# --- hostile workbooks -------------------------------------------------------


def _workbook(sheet_xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml", "<workbook><sheets><sheet name='S' id='1'/></sheets></workbook>"
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{sheet_xml}</sheetData></worksheet>"
        )
    return buffer.getvalue()


def test_cell_far_past_the_last_column_is_ignored() -> None:
    # One cell at column ZZZZZZZZ used to ask for a row of ~2e11 cells.
    sheet = "<row r='1'><c r='A1'><v>1</v></c><c r='ZZZZZZZZ1'><v>2</v></c></row>"
    assert read_xlsx(_workbook(sheet)) == {"S": [[1.0]]}


def test_sheet_spread_over_too_many_cells_is_refused() -> None:
    rows = "".join(f"<row><c r='IU{i}'><v>1</v></c></row>" for i in range(1, 20_000))
    with pytest.raises(ReportFormatError) as info:
        read_xlsx(_workbook(rows))
    assert info.value.code == "xlsx_too_large"


# --- trade-pattern scan -------------------------------------------------------


def _reference(order, trades, sides, symbols) -> tuple[int, int]:
    """The original quadratic scan, kept as the definition to match."""
    adds = 0
    most = 0
    for i in order:
        trade = trades[i]
        open_same = [
            j
            for j in order
            if j != i
            and symbols[j] == symbols[i]
            and trades[j].entry_time <= trade.entry_time < trades[j].exit_time
            and (trades[j].entry_time, j) < (trade.entry_time, i)
        ]
        most = max(most, len(open_same) + 1)
        for j in open_same:
            if sides[j] != sides[i]:
                continue
            if (
                trade.entry_price < trades[j].entry_price
                if sides[i] == "long"
                else trade.entry_price > trades[j].entry_price
            ):
                adds += 1
                break
    return adds, most


def _random_trades(n: int, seed: int) -> tuple[list[Trade], list[str], list[str]]:
    rng = np.random.default_rng(seed)
    trades = []
    for _ in range(n):
        entry = int(rng.integers(0, 200))
        # Some trades close before they open (bad rows) or at their entry.
        exit_ = entry + int(rng.integers(-2, 30))
        price = float(rng.integers(95, 105))
        trades.append(
            Trade(
                entry_time=T0 + timedelta(hours=entry),
                exit_time=T0 + timedelta(hours=exit_),
                quantity=1.0,
                entry_price=price,
                exit_price=price,
                pnl=0.0,
                return_pct=0.0,
            )
        )
    sides = [("long", "short")[int(x)] for x in rng.integers(0, 2, n)]
    symbols = [("EURUSD", "GBPUSD", "XAUUSD")[int(x)] for x in rng.integers(0, 3, n)]
    return trades, sides, symbols


@pytest.mark.parametrize("seed", range(12))
def test_trade_scan_matches_the_original_definition(seed: int) -> None:
    trades, sides, symbols = _random_trades(250, seed)
    order = sorted(range(len(trades)), key=lambda i: (trades[i].entry_time, i))
    assert _grid_and_concurrency(order, trades, sides, symbols) == _reference(
        order, trades, sides, symbols
    )


def test_fifty_thousand_trades_scan_in_one_pass() -> None:
    # Quadratic, this took minutes; one sweep takes well under a second.
    trades, sides, symbols = _random_trades(50_000, 99)
    order = sorted(range(len(trades)), key=lambda i: (trades[i].entry_time, i))
    adds, most = _grid_and_concurrency(order, trades, sides, symbols)
    assert 0 < adds < 50_000
    assert most > 1


# --- large platform reports ---------------------------------------------------


def test_html_report_is_parsed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    original = importers._read_html

    def counting(text: str):
        calls.append(len(text))
        return original(text)

    monkeypatch.setattr(importers, "_read_html", counting)
    report = import_report(synthetic_mt5_report(30), "ReportTester.html")
    assert report.trades.trades
    assert len(calls) == 1


def test_upload_that_goes_below_zero_is_a_clear_400(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/a.db", bootstrap_samples=100)
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    bad = _curve([100.0 - i for i in range(150)])
    for lang, words in (("es", "saldo de la cuenta"), ("en", "account balance")):
        response = client.post(
            "/audits",
            files={"equity": ("equity.csv", bad, "text/csv")},
            data={"consent": "on", "locale": lang},
            headers={"accept": "application/json"},
        )
        assert response.status_code == 400
        assert words in response.json()["error"]
    good = client.post(
        "/audits",
        files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert good.status_code == 201


def test_infinite_values_are_dropped_as_unreadable() -> None:
    values: list[float | str] = [100.0 + i for i in range(40)]
    values[5], values[9] = "inf", "1e400"
    series = parse_equity_csv(_curve(values))  # type: ignore[arg-type]
    assert series.unparseable_rows == 2
    assert np.isfinite(series.frame["equity"]).all()


def test_head_is_answered_like_get_without_a_body(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/a.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    for path, status in (("/", 200), ("/ejemplo", 200), ("/static/app.js", 200), ("/nope", 404)):
        head = client.head(path)
        get = client.get(path)
        assert head.status_code == get.status_code == status
        assert head.content == b""
        assert head.headers["content-length"] == get.headers["content-length"]
        assert "content-security-policy" in head.headers


# --- curves as Excel saves them ---------------------------------------------


HEADER_CELLS = (
    "<row><c t='inlineStr'><is><t>{0}</t></is></c><c t='inlineStr'><is><t>{1}</t></is></c></row>"
)


def _daily(n: int = 120) -> pd.DataFrame:
    return positive_drift(n)


def test_curve_saved_by_excel_as_unicode_text_is_read() -> None:
    frame = _daily()
    text = frame.to_csv(sep="\t", index=False)
    reference = parse_equity_csv(csv_bytes(frame))
    for data in (b"\xff\xfe" + text.encode("utf-16-le"), text.encode("utf-16")):
        series = parse_equity_csv(data)
        assert len(series.frame) == len(reference.frame)
        assert series.frame["equity"].iloc[-1] == pytest.approx(reference.frame["equity"].iloc[-1])


def test_curve_in_a_windows_code_page_is_read() -> None:
    data = "fecha;equity\n" + "\n".join(f"2021-01-{d:02d};{100 + d}" for d in range(1, 29))
    series = parse_equity_csv(data.replace("equity", "capital").encode("cp1252"))
    assert len(series.frame) == 28


def test_curve_uploaded_as_a_workbook_is_read_with_excel_dates() -> None:
    days = pd.bdate_range("2022-01-03", periods=60)
    serial = [(d - pd.Timestamp("1899-12-30")).days for d in days]
    cells = HEADER_CELLS.format("Date", "Equity")
    cells += "".join(
        f"<row><c><v>{s}</v></c><c><v>{10000 + 7 * i}</v></c></row>" for i, s in enumerate(serial)
    )
    series = parse_equity_csv(_workbook(cells))
    assert len(series.frame) == 60
    assert series.frame["timestamp"].iloc[0] == pd.Timestamp("2022-01-03", tz="UTC")
    assert series.frame["equity"].iloc[-1] == 10000 + 7 * 59


def test_empty_workbook_is_an_empty_file() -> None:
    with pytest.raises(ParseError) as info:
        parse_equity_csv(_workbook(""))
    assert info.value.code == "empty"


def _app_client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/a.db", bootstrap_samples=100)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_workbook_curve_in_the_main_box_is_audited_as_a_curve(tmp_path: Path) -> None:
    from quant_trade.audit.web import looks_like_platform_report

    days = pd.bdate_range("2022-01-03", periods=300)
    rng = np.random.default_rng(4)
    equity = 10_000 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300))
    cells = HEADER_CELLS.format("date", "equity")
    cells += "".join(
        f"<row><c><v>{(d - pd.Timestamp('1899-12-30')).days}</v></c><c><v>{e}</v></c></row>"
        for d, e in zip(days, equity, strict=True)
    )
    book = _workbook(cells)
    assert not looks_like_platform_report("curva.xlsx", book)
    response = _app_client(tmp_path).post(
        "/audits",
        files={"equity": ("curva.xlsx", book, "application/octet-stream")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 201, response.text


def test_report_over_the_old_5_mb_limit_is_accepted(tmp_path: Path) -> None:
    from quant_trade.audit.schema import MAX_REPORT_BYTES, MAX_UPLOAD_BYTES

    report = synthetic_mt5_report(6_500)  # UTF-16, like the terminal writes it
    assert MAX_UPLOAD_BYTES < len(report) < MAX_REPORT_BYTES
    assert len(import_report(report, "ReportTester.html").trades.trades) == 6_500
    response = _app_client(tmp_path).post(
        "/audits",
        files={"report": ("ReportTester.html", report, "text/html")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 201, response.text


def test_report_past_the_new_limit_is_refused(tmp_path: Path) -> None:
    from quant_trade.audit.schema import MAX_REPORT_BYTES

    too_big = b"\xff\xfe" + b"<\x00" * (MAX_REPORT_BYTES // 2 + 10)
    with pytest.raises(ReportFormatError) as info:
        import_report(too_big, "r.html")
    assert info.value.code == "file_too_large"
    response = _app_client(tmp_path).post(
        "/audits",
        files={"report": ("r.html", too_big, "text/html")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 413


# --- live account statements --------------------------------------------------


def test_a_live_statement_error_names_the_live_file() -> None:
    blown = synthetic_mt5_report(60, edge_pips=-60, lots=5)
    with pytest.raises(ParseError) as info:
        build_inputs(
            None,
            DeclaredMetadata(),
            report_bytes=synthetic_mt5_report(200),
            report_filename="ReportTester.html",
            live_bytes=blown,
            live_filename="cuenta.html",
        )
    assert info.value.message_es.startswith("Estado de cuenta real: ")
    assert str(info.value).startswith("the live account statement: ")
    assert info.value.code == "balance_not_positive"


def test_thousands_of_trades_in_one_hour_pair_quickly() -> None:
    from quant_trade.audit.live import compare_live
    from quant_trade.audit.schema import ParsedTrades

    def parsed(n: int) -> ParsedTrades:
        trades = [
            Trade(
                entry_time=T0,
                exit_time=T0 + timedelta(minutes=30),
                quantity=1.0,
                entry_price=100.0,
                exit_price=100.0 + (i % 5 - 2) * 0.1,
                pnl=(i % 5 - 2) * 0.1,
                return_pct=0.0,
            )
            for i in range(n)
        ]
        return ParsedTrades(
            trades=trades, sides=["long"] * n, client_pnl=[None] * n, invalid_rows=0
        )

    # All entries share one timestamp: scanning every paired candidate again
    # took ~80 s for 12,000 trades.
    result = compare_live(parsed(12_000), parsed(12_000), samples=200)
    assert result["pairing"]["matched"]["value"] == 12_000


def test_an_mql5_signal_header_without_a_closing_price_is_not_a_crash() -> None:
    from quant_trade.audit.importers import ReportFormatError, import_report

    data = (
        b"Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Close;Commission;Swap;Profit\n"
        b"2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.04 15:00:00;1.08150;0;0;15.00\n"
    )
    with pytest.raises(ReportFormatError) as caught:
        import_report(data, "history.csv")
    assert caught.value.code == "unknown_format"


def test_a_trade_that_closes_before_it_opens_is_dropped() -> None:
    from quant_trade.audit.importers import import_report

    data = (
        b"Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit\n"
        b"2024.03.01 08:00:00;Balance;;;;;;;;;;1000.00\n"
        b"2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2020.03.04 15:00:00;1.08150;0;0;15.00\n"
        b"2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;;;2024.03.05 11:00:00;1.08400;0;0;10.00\n"
        b"2024.03.06 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.06 15:00:00;1.08100;0;0;10.00\n"
    )
    report = import_report(data, "history.csv")
    assert all(t.exit_time >= t.entry_time for t in report.trades.trades)
    assert len(report.trades.trades) == 2
    assert any("1 row(s)" in warning for warning in report.warnings)


def test_a_trades_csv_row_that_closes_before_it_opens_is_dropped() -> None:
    from quant_trade.audit.schema import parse_trades_csv

    data = (
        b"entry_time,exit_time,quantity,entry_price,exit_price\n"
        b"2024-01-02,2024-01-03,1,100,101\n"
        b"2024-01-05,2024-01-04,1,100,99\n"
        b"2024-01-06,2024-01-08,1,100,102\n"
    )
    parsed = parse_trades_csv(data)
    assert len(parsed.trades) == 2
    assert parsed.invalid_rows == 1


def test_damaged_tester_header_values_are_not_declared() -> None:
    from quant_trade.audit.testdata import data_quality, review_test_data

    assert data_quality("-5%") is None
    for raw in ("-7", "1e300"):
        review, _ = review_test_data(
            source_format=importers.MT4_TESTER_HTML,
            metadata={"mismatched_chart_errors": raw},
            trades=None,
        )
        assert review["mismatched_chart_errors"]["evidence"] == "NOT_MEASURED", raw


def _tiny_fall_history(loss: float) -> bytes:
    start = datetime(2024, 1, 1)
    rows = [
        "Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit",
        "2023.12.31 08:00:00;Balance;;;;;;;;;;10000",
    ]
    for i in range(60):
        opened = start + timedelta(days=i * 2)
        closed = opened + timedelta(hours=1)
        profit = loss if i == 5 else 1.0
        rows.append(
            f"{opened:%Y.%m.%d %H:%M:%S};Buy;0.10;EURUSD;1.10000;;;"
            f"{closed:%Y.%m.%d %H:%M:%S};{1.1 + profit / 10_000:.5f};0;0;{profit:.4f}"
        )
    return "\n".join(rows).encode()


@pytest.mark.parametrize("locale", ["es", "en"])
def test_an_almost_flat_history_gets_no_capital_figures(locale: str) -> None:
    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.i18n import localize
    from quant_trade.audit.report import render_html
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=_tiny_fall_history(-0.0001),
        report_filename="history.csv",
    )
    result = run_audit(inputs, bootstrap_samples=30, risk_samples=200, challenge_samples=30)
    data = result.model_dump() if hasattr(result, "model_dump") else result.to_dict()
    assert data["capital"]["status"] == "NOT_MEASURED"
    page = render_html(result, watermark=False, locale=locale)
    assert "000000.0x" not in page
    assert localize(data["capital"]["reason"], locale) != data["capital"]["reason"] or (
        locale == "en"
    )


def test_a_size_share_above_ten_prints_as_more_than_ten() -> None:
    from quant_trade.audit.sizing import scale_text

    assert scale_text(0.35, "es") == "0.35x"
    assert scale_text(9.96, "es") == "10.0x"
    assert scale_text(124.2, "es") == "más de 10x"
    assert scale_text(124.2, "en") == "more than 10x"


_OPT_HEAD = (
    '<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
    'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet '
    'ss:Name="Tester Optimizator Results"><Table>'
)


def _opt_row(*values: object) -> str:
    return "<Row>" + "".join(f"<Cell><Data>{value}</Data></Cell>" for value in values) + "</Row>"


def test_a_crafted_optimization_cell_index_does_not_pad_millions_of_cells() -> None:
    import time

    header = _opt_row("Pass", "Result", "Profit", "Trades", "FastMA")
    rows = "".join(_opt_row(i, 10_000 + i, i, 100, 5 + i) for i in range(12))
    crafted = '<Row><Cell ss:Index="200000000"><Data>1</Data></Cell></Row>'
    data = (_OPT_HEAD + header + rows + crafted + "</Table></Worksheet></Workbook>").encode()
    started = time.perf_counter()
    summary = importers.parse_optimization(data)
    assert time.perf_counter() - started < 2
    assert summary.passes == 12


def test_the_best_pass_with_a_blank_parameter_is_not_a_crash() -> None:
    from quant_trade.audit.plateau import parameter_stability

    table = [{"Profit": float(i), "FastMA": 5.0 + i, "SlowMA": 50.0 + i % 3} for i in range(19)]
    table.append({"Profit": 999.0, "SlowMA": 51.0})  # the best pass left FastMA blank
    review, _ = parameter_stability(table, ["FastMA", "SlowMA"], report_inputs=None)
    assert review["status"] == "MEASURED"
    assert review["chosen"] == {"SlowMA": 51.0}


_FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"


@pytest.mark.parametrize(
    ("old", "new", "what"),
    [
        ("<Title>FixtureEA ", "<Title>OtherEA ", "robot"),
        ("EURUSD,H1", "GBPJPY,H1", "símbolo"),
        ("EURUSD,H1", "EURUSD,M15", "marco temporal"),
        (">FastMA<", ">TakeProfit<", "parámetros"),
    ],
)
def test_an_optimization_file_from_another_test_is_refused(old: str, new: str, what: str) -> None:
    from quant_trade.audit.schema import DeclaredMetadata, ParseError, build_inputs

    report = (_FIXTURES / "mt5_tester.html").read_bytes()
    optimization = (_FIXTURES / "mt5_optimization.xml").read_text(encoding="utf-8")
    assert old in optimization
    with pytest.raises(ParseError) as caught:
        build_inputs(
            None,
            DeclaredMetadata(),
            report_bytes=report,
            report_filename="report.html",
            optimization_bytes=optimization.replace(old, new).encode(),
        )
    assert caught.value.code == "optimization_mismatch"
    assert what in caught.value.message_es


def test_the_matching_optimization_file_and_a_broker_suffix_are_accepted() -> None:
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    report = (_FIXTURES / "mt5_tester.html").read_bytes()
    optimization = (_FIXTURES / "mt5_optimization.xml").read_text(encoding="utf-8")
    for text in (optimization, optimization.replace("EURUSD,H1", "EURUSD.m,H1")):
        inputs = build_inputs(
            None,
            DeclaredMetadata(),
            report_bytes=report,
            report_filename="report.html",
            optimization_bytes=text.encode(),
        )
        assert inputs.optimization_passes


def _nul_client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/a.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        admin_key="k" * 40,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store


def test_a_nul_byte_in_a_report_never_reaches_the_database(tmp_path: Path) -> None:
    # PostgreSQL refuses text holding a NUL: a stray one in the robot's name
    # failed the whole upload with a server error.
    from quant_trade.audit.importers import decode_text

    report = (_FIXTURES / "mt5_tester.html").read_bytes().replace(b"FixtureEA", b"Fix\x00tureEA")
    assert "\x00" not in decode_text(report)
    client, store = _nul_client(tmp_path)
    response = client.post(
        "/audits",
        data={"consent": "on"},
        files={"report": ("report.html", report, "text/html")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    audit_id = response.headers["location"].split("/")[2].split("?")[0]
    record = store.get_audit(audit_id)
    assert record is not None and record.report_html
    assert "\x00" not in record.report_html and "FixtureEA" in record.report_html


@pytest.mark.parametrize("email", ["a\x00@b.co", "a@b.co\r\nBcc: c@d.co", "a b@c.co"])
def test_a_waitlist_address_with_control_characters_is_refused(
    tmp_path: Path, email: str
) -> None:
    client, store = _nul_client(tmp_path)
    response = client.post("/waitlist", data={"email": email}, follow_redirects=False)
    assert response.status_code == 303 and "error=email" in response.headers["location"]
    assert store.waitlist_emails() == []


def test_a_panel_note_with_a_nul_creates_no_code(tmp_path: Path) -> None:
    client, store = _nul_client(tmp_path)
    page = client.post(
        "/panel", data={"key": "k" * 40, "action": "create", "credits": "1", "note": "a\x00b"}
    )
    assert page.status_code == 200
    assert store.list_access_codes() == []


def test_an_id_holding_a_nul_is_not_found_without_asking_the_database(tmp_path: Path) -> None:
    # "/v/%00" was a server error on PostgreSQL, which refuses text holding a NUL.
    client, store = _nul_client(tmp_path)
    for path in ("/v/%00", "/v/%00/badge.svg", "/audits/%00?token=a", "/audits/%00/pdf?token=a"):
        assert client.get(path).status_code == 404
    store.engine = None  # any query would now fail
    at = datetime(2026, 1, 1, tzinfo=UTC)
    assert store.get_audit("a\x00") is None
    assert store.get_publication("a\x00") is None
    assert store.publication_for_audit("a\x00") is None
    assert store.publication_view("a\x00") is None
    assert store.mark_paid("a\x00", stripe_session_id="s", at=at) is False
    assert store.redeem_for_audit("a\x00", "AUD-2222-2222-2222", at=at) is False
    assert store.disable_access_code("a\x00") is False
    assert store.unpublish("a\x00") is False
    assert store.delete_audit("a\x00") is False


def _signal_csv(profits: list[float]) -> bytes:
    """An MQL5 signal history: a 10,000 deposit, then one trade a day."""
    rows = [
        "Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit",
        "2023.12.31 08:00:00;Balance;;;;;;;;;;10000",
    ]
    for i, profit in enumerate(profits):
        entry = datetime(2024, 1, 1) + timedelta(days=i)
        leave = entry + timedelta(hours=1)
        rows.append(
            f"{entry:%Y.%m.%d %H:%M:%S};Buy;0.10;EURUSD;1.10000;;;"
            f"{leave:%Y.%m.%d %H:%M:%S};1.10010;0;0;{profit}"
        )
    return "\n".join(rows).encode()


def test_an_absurd_trade_profit_is_refused_not_a_blank_report() -> None:
    # A 1e308 profit overflowed every later sum: the capital section had no
    # fall to print and the report page failed with a server error.
    data = _signal_csv([1e308 if i == 10 else 1.0 for i in range(60)])
    with pytest.raises(ParseError) as caught:
        build_inputs(None, DeclaredMetadata(), report_bytes=data, report_filename="h.csv")
    assert caught.value.code == "value_too_large"
    assert "demasiado grande" in caught.value.message_es


@pytest.mark.parametrize(("value", "refused"), [(1e200, True), (9e14, False)])
def test_an_equity_value_beyond_any_account_is_refused(value: float, refused: bool) -> None:
    curve = positive_drift(300)
    curve.loc[100, "equity"] = value
    if refused:
        with pytest.raises(ParseError) as caught:
            parse_equity_csv(csv_bytes(curve))
        assert caught.value.code == "value_too_large"
    else:
        assert len(parse_equity_csv(csv_bytes(curve)).frame) == 300


def test_a_return_beyond_any_account_is_refused() -> None:
    curve = positive_drift(300)
    returns = pd.DataFrame({"timestamp": curve["timestamp"], "return": 0.001})
    returns.loc[50, "return"] = 1e300
    with pytest.raises(ParseError) as caught:
        parse_equity_csv(csv_bytes(returns))
    assert caught.value.code == "value_too_large"


def test_capital_is_not_measured_when_the_fall_overflows() -> None:
    from quant_trade.audit.sizing import capital_review

    start = datetime(2024, 1, 1, tzinfo=UTC)
    trades = [
        Trade(
            entry_time=start + timedelta(days=4 * i),
            exit_time=start + timedelta(days=4 * i, hours=4),
            quantity=1.0,
            entry_price=1.0,
            exit_price=1.0,
            pnl=-1e308 if i % 2 else 1e308,
            return_pct=0.0,
        )
        for i in range(60)
    ]
    review = capital_review(trades, fees=None, starting_balance=10_000.0, samples=50)
    assert review["status"] == "NOT_MEASURED"
