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
