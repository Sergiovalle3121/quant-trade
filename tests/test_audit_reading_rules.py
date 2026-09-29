"""How a customer's file is read: the order of day and month, the decimal
mark of a semicolon file, and a Sharpe that could not be computed.

The last test is the proof that nothing else moved: every file the
repository holds is audited and compared with the figures the code read
before these rules existed (frozen from origin/main at c6ce500).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_following

from quant_trade.audit import errors_pt, universal
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.importers import ReportFormatError, import_report
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import (
    DAY_FIRST_NOTE,
    MONTH_FIRST_NOTE,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    parse_equity_csv,
    parse_trades_csv,
)

ROOT = Path(__file__).resolve().parents[1]


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rigor_reading_regression", ROOT / "tools" / "rigor_reading_regression.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _tool()
CURVE = positive_drift(400)
ISO = parse_equity_csv(csv_bytes(CURVE))


# --- Dates -----------------------------------------------------------------


@pytest.mark.parametrize("style", ["/", ".", "-", "time", "fecha"])
def test_day_month_year_reads_like_the_same_curve_in_iso(style: str) -> None:
    series = parse_equity_csv(TOOL.day_month_curve(CURVE, style))
    assert list(series.frame["timestamp"]) == list(ISO.frame["timestamp"])
    assert series.frame["equity"].round(2).tolist() == ISO.frame["equity"].round(2).tolist()
    assert not series.non_monotonic
    assert series.unparseable_rows == 0
    assert series.warnings == [DAY_FIRST_NOTE]


def test_month_day_year_keeps_its_reading_and_says_so() -> None:
    series = parse_equity_csv(TOOL.day_month_curve(CURVE, "us"))
    assert list(series.frame["timestamp"]) == list(ISO.frame["timestamp"])
    assert series.warnings == [MONTH_FIRST_NOTE]


def test_year_first_dates_carry_no_note() -> None:
    assert ISO.warnings == []
    assert parse_equity_csv(TOOL.day_month_curve(CURVE, "iso")).warnings == []
    named = b"date,equity\n15 Mar 2024,100\n16 Mar 2024,101\n17 Mar 2024,102\n"
    assert parse_equity_csv(named).warnings == []


def test_two_digit_years_follow_the_same_rule() -> None:
    data = b"date,equity\n30/01/24,100\n31/01/24,101\n01/02/24,102\n"
    series = parse_equity_csv(data)
    assert [stamp.strftime("%Y-%m-%d") for stamp in series.frame["timestamp"]] == [
        "2024-01-30",
        "2024-01-31",
        "2024-02-01",
    ]


def test_a_file_mixing_both_orders_is_refused() -> None:
    data = b"date,equity\n13/01/2024,100\n01/14/2024,101\n01/15/2024,102\n"
    with pytest.raises(ParseError) as info:
        parse_equity_csv(data)
    assert info.value.code == "mixed_date_order"
    assert "13/01/2024 and 01/14/2024" in str(info.value)
    assert "mezcla fechas día/mes/año y mes/día/año" in info.value.localized("es")
    portuguese = errors_pt.portuguese(str(info.value))
    assert portuguese is not None and "mistura datas dia/mês/ano" in portuguese
    assert "da curva de equity" in portuguese


def test_dates_that_read_both_ways_are_refused_not_guessed() -> None:
    data = b"date,equity\n01/02/2024,100\n01/03/2024,101\n01/04/2024,102\n01/05/2024,103\n"
    with pytest.raises(ParseError) as info:
        parse_equity_csv(data)
    assert info.value.code == "ambiguous_date_order"
    assert "01/02/2024" in str(info.value)
    assert "año-mes-día" in info.value.localized("es")
    portuguese = errors_pt.portuguese(str(info.value))
    assert portuguese is not None and "ano-mês-dia" in portuguese


def test_two_ambiguous_rows_are_refused() -> None:
    with pytest.raises(ParseError) as info:
        parse_equity_csv(b"date,equity\n01/02/2024,100\n02/03/2024,101\n")
    assert info.value.code == "ambiguous_date_order"


def test_a_monthly_series_on_the_first_is_settled_by_its_order() -> None:
    rows = [
        f"01/{month:02d}/{year},{10_000 + 50 * index}"
        for index, (year, month) in enumerate(
            (year, month) for year in (2022, 2023) for month in range(1, 13)
        )
    ]
    series = parse_equity_csv(("date,equity\n" + "\n".join(rows) + "\n").encode())
    stamps = series.frame["timestamp"]
    assert series.warnings == [DAY_FIRST_NOTE]
    assert stamps.iloc[0] == pd.Timestamp("2022-01-01", tz="UTC")
    assert stamps.iloc[-1] == pd.Timestamp("2023-12-01", tz="UTC")
    assert not series.non_monotonic


def test_a_daily_us_series_in_one_month_is_settled_by_its_order() -> None:
    # Month first: twelve days in a row, then the next months' first days.
    days = [f"{month:02d}/{day:02d}/2024" for month in (1, 2, 3) for day in range(1, 13)]
    rows = [f"{day},{10_000 + index}" for index, day in enumerate(days)]
    with pytest.raises(ParseError) as info:
        parse_equity_csv(("date,equity\n" + "\n".join(rows) + "\n").encode())
    # Both orders leave gaps of the same kind: nothing settles it.
    assert info.value.code == "ambiguous_date_order"


def test_trades_written_day_first_lose_no_row() -> None:
    frame = trades_following(positive_drift(1500))
    iso = parse_trades_csv(csv_bytes(frame))
    read = parse_trades_csv(TOOL.day_month_trades(frame))
    assert read.invalid_rows == 0
    assert len(read.trades) == len(iso.trades)
    assert [trade.entry_time for trade in read.trades] == [t.entry_time for t in iso.trades]
    assert [trade.exit_time for trade in read.trades] == [t.exit_time for t in iso.trades]
    assert DAY_FIRST_NOTE in read.warnings
    assert DAY_FIRST_NOTE not in iso.warnings and MONTH_FIRST_NOTE not in iso.warnings


def test_trades_take_the_order_in_which_no_trade_closes_before_it_opens() -> None:
    data = (
        b"entry_time,exit_time,quantity,entry_price,exit_price\n"
        b"05/01/2024,02/02/2024,1,100,101\n"
        b"05/02/2024,02/03/2024,1,100,102\n"
        b"05/03/2024,02/04/2024,1,100,99\n"
        b"05/04/2024,02/05/2024,1,100,103\n"
    )
    read = parse_trades_csv(data)
    assert DAY_FIRST_NOTE in read.warnings
    assert read.trades[0].entry_time.strftime("%Y-%m-%d") == "2024-01-05"
    assert read.trades[0].exit_time.strftime("%Y-%m-%d") == "2024-02-02"


def test_one_column_day_first_and_the_other_month_first_is_refused() -> None:
    data = (
        b"entry_time,exit_time,quantity,entry_price,exit_price\n13/01/2024,01/14/2024,1,100,101\n"
    )
    with pytest.raises(ParseError) as info:
        parse_trades_csv(data)
    assert info.value.code == "mixed_date_order"
    assert "de operaciones" in info.value.localized("es")


def test_the_date_notes_read_in_three_languages_and_pass_the_guard() -> None:
    wanted = {
        DAY_FIRST_NOTE: ("fechas leídas como día/mes/año", "datas lidas como dia/mês/ano"),
        MONTH_FIRST_NOTE: ("fechas leídas como mes/día/año", "datas lidas como mês/dia/ano"),
    }
    for note, (spanish, portuguese) in wanted.items():
        line = f"equity: {note}"
        assert localize(line, "es") == f"curva de equity: {spanish}"
        assert localize(line, "pt").endswith(portuguese)
        assert localize(line, "en") == line
        for locale in ("es", "en", "pt"):
            assert find_claims(localize(line, locale)) == []


def test_the_report_states_the_order_the_dates_were_read_in() -> None:
    inputs = build_inputs(TOOL.day_month_curve(CURVE, "/"), DeclaredMetadata())
    result = run_audit(inputs, now=TOOL.NOW, audit_id="fixed", bootstrap_samples=100)
    data = result.model_dump(mode="json")
    assert f"equity: {DAY_FIRST_NOTE}" in data["inputs"]["parse_warnings"]
    assert untranslated(data) == []
    assert "echas leídas como día/mes/año" in render_html(result, watermark=False, locale="es")
    assert "ates read as day/month/year" in render_html(result, watermark=False, locale="en")
    assert "atas lidas como dia/mês/ano" in render_html(result, watermark=False, locale="pt")


# --- Decimal mark of a semicolon file ---------------------------------------


def _first_prices(data: bytes) -> tuple[float, float]:
    report = import_report(data, "operacoes.csv", initial_balance=1_000_000.0,
                           columns=TOOL.COLUMNS)  # fmt: skip
    trade = report.trades.trades[0]
    return trade.entry_price, trade.exit_price


@pytest.mark.parametrize(
    ("delimiter", "decimal", "thousands", "entry"),
    [
        (";", ".", False, 109.48),
        (";", ",", False, 109.48),
        (",", ".", False, 109.48),
        (";", ",", True, 1309.48),
        (";", ".", True, 1309.48),
        (",", ".", True, 1309.48),
    ],
)
def test_prices_are_read_at_their_size(
    delimiter: str, decimal: str, thousands: bool, entry: float
) -> None:
    data = TOOL.generic_trades(delimiter, decimal, thousands=thousands)
    price_in, price_out = _first_prices(data)
    assert price_in == pytest.approx(entry)
    assert price_out == pytest.approx(entry - 2.4)


def test_a_semicolon_file_gives_the_same_trades_as_its_comma_twin() -> None:
    kwargs = {"initial_balance": 100_000.0, "columns": TOOL.COLUMNS}
    comma = import_report(TOOL.generic_trades(",", "."), "a.csv", **kwargs)
    for decimal in (".", ","):
        semicolon = import_report(TOOL.generic_trades(";", decimal), "a.csv", **kwargs)
        assert [t.pnl for t in semicolon.trades.trades] == pytest.approx(
            [t.pnl for t in comma.trades.trades]
        )


def test_numbers_that_read_both_ways_are_refused() -> None:
    data = TOOL.generic_trades(";", ".").replace(b".", b".1")
    with pytest.raises(ReportFormatError) as info:
        import_report(data, "a.csv", initial_balance=100_000.0, columns=TOOL.COLUMNS)
    assert info.value.code == "ambiguous_decimal_mark"
    assert "109.148" in str(info.value)
    assert "punto decimal o coma decimal" in info.value.localized("es")
    portuguese = errors_pt.portuguese(str(info.value))
    assert portuguese is not None and "ponto decimal ou vírgula decimal" in portuguese
    # The cell is quoted as the customer wrote it, never reformatted.
    assert "109.148" in portuguese


def test_a_file_mixing_both_marks_is_refused() -> None:
    lines = TOOL.generic_trades(";", ".").decode().splitlines()
    lines[2] = lines[2].replace(".", ",")
    with pytest.raises(ReportFormatError) as info:
        import_report(("\n".join(lines) + "\n").encode(), "a.csv",
                      initial_balance=100_000.0, columns=TOOL.COLUMNS)  # fmt: skip
    assert info.value.code == "mixed_decimal_marks"
    assert "mezcla números con punto decimal y con coma decimal" in info.value.localized("es")
    portuguese = errors_pt.portuguese(str(info.value))
    assert portuguese is not None and "mistura números" in portuguese


def test_whole_numbers_need_no_mark() -> None:
    lines = [line.split(";") for line in TOOL.generic_trades(";", ".").decode().splitlines()]
    for cells in lines[1:]:
        cells[3], cells[4] = str(round(float(cells[3]))), str(round(float(cells[4])))
    data = ("\n".join(";".join(cells) for cells in lines) + "\n").encode()
    price_in, _ = _first_prices(data)
    assert price_in == 109.0


@pytest.mark.parametrize(
    ("text", "mark"),
    [
        ("109.48", "."),
        ("0.5", "."),
        ("1.23456", "."),
        ("109,48", ","),
        ("1.234,56", ","),
        ("1,234.56", "."),
        ("1.234.567", ","),
        ("1,234,567", "."),
        ("0,001", ","),
        ("0.001", "."),
        ("1234,567", ","),
        ("1.234", None),
        ("1,234", None),
        ("12.345", None),
        ("100", None),
    ],
)
def test_the_mark_one_number_settles(text: str, mark: str | None) -> None:
    assert universal._own_decimal(text) == mark


def test_the_new_refusals_pass_the_guard_in_three_languages() -> None:
    refusals: list[ParseError | ReportFormatError] = []
    for data in (
        b"date,equity\n13/01/2024,100\n01/14/2024,101\n01/15/2024,102\n",
        b"date,equity\n01/02/2024,100\n01/03/2024,101\n01/04/2024,102\n",
    ):
        with pytest.raises(ParseError) as info:
            parse_equity_csv(data)
        refusals.append(info.value)
    with pytest.raises(ReportFormatError) as found:
        import_report(TOOL.generic_trades(";", ".").replace(b".", b".1"), "a.csv",
                      initial_balance=100_000.0, columns=TOOL.COLUMNS)  # fmt: skip
    refusals.append(found.value)
    for refusal in refusals:
        portuguese = errors_pt.portuguese(str(refusal))
        assert portuguese is not None
        for text in (str(refusal), refusal.localized("es"), portuguese):
            assert find_claims(text) == []


# --- A Sharpe that could not be computed -------------------------------------


def _audit(data: bytes) -> Any:
    inputs = build_inputs(data, DeclaredMetadata())
    return run_audit(inputs, now=TOOL.NOW, audit_id="fixed", bootstrap_samples=100)


@pytest.mark.parametrize("rows", [2, 3])
def test_fewer_than_three_returns_leave_the_sharpe_not_measured(rows: int) -> None:
    result = _audit(TOOL.short_curve(rows))
    for key in ("sharpe", "sortino"):
        figure = result.performance[key]
        assert figure["evidence"] == "NOT_MEASURED"
        assert figure["value"] is None
        assert figure["note"] == "fewer than three returns"
    assert result.significance["psr"]["note"] == "fewer than three returns"
    assert result.verdict.overall == "D"
    assert untranslated(result.model_dump(mode="json")) == []
    for locale, words in (("es", "menos de tres retornos"), ("en", "fewer than three returns"),
                          ("pt", "menos de três retornos")):  # fmt: skip
        page = render_html(result, watermark=False, locale=locale)
        for ratio in ("Sharpe", "Sortino"):
            row = page.split(f"<tr><td>{ratio}</td>")[1].split("</tr>")[0]
            assert "badge NOT_MEASURED" in row and words in row
            assert "<td class='val'>—</td>" in row
        assert find_claims(words) == []


def test_three_returns_keep_a_measured_sharpe() -> None:
    result = _audit(TOOL.short_curve(4))
    assert result.performance["sharpe"]["evidence"] == "MEASURED"
    assert result.performance["sharpe"]["value"] != 0.0


def test_a_flat_curve_has_no_sharpe_to_report() -> None:
    rows = "".join(f"2024-01-{day:02d},10000\n" for day in range(1, 11))
    result = _audit(("date,equity\n" + rows).encode())
    assert result.performance["sharpe"]["evidence"] == "NOT_MEASURED"
    assert result.performance["sharpe"]["note"] == "zero variance"


# --- Nothing else moved ------------------------------------------------------

#: Statuses of the six dimensions, in the verdict's order.
STATUS = {"PS": "PASS", "WK": "WEAK", "FL": "FAIL", "ND": "NOT_MEASURED", "NE": "NOT_APPLICABLE"}

#: What origin/main (c6ce500) read from every file of the repository: class,
#: first and last date, rows, total return, maximum drawdown, annualised
#: Sharpe, annual volatility, the dimensions and the red flags. A Sharpe of
#: ``None`` is a history with fewer than three returns, which main printed as
#: a measured 0.0: the one intended difference.
FROZEN: dict[str, tuple[Any, ...]] = {
    "fixtures/backtestingpy_trades.csv": (
        "D", "2024-12-05", "2024-12-23", 13, -0.01326, -0.027584, -1.785416, 0.146085,
        "FL/FL/FL/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/backtestingpy_v03.csv": (
        "C", "2006-02-09", "2006-04-24", 53, 0.20716, 0.0, 2.221668, 0.460242,
        "WK/PS/PS/ND/WK/ND", "MAD_SPIKES,TOO_FEW_OBSERVATIONS,ZERO_DECLARED_COSTS"),
    "fixtures/mt4_statement.htm": (
        "D", "2024-03-01", "2024-03-06", 4, -0.01943, -0.02285, -4.202717, 0.331243,
        "FL/FL/FL/ND/FL/ND", "HIDDEN_FLOATING_DRAWDOWN,TOO_FEW_OBSERVATIONS"),
    "fixtures/mt4_tester.htm": (
        "D", "2024-01-01", "2024-01-05", 5, 0.00951, -4e-05, 13.697651, 0.063281,
        "WK/WK/WK/ND/FL/ND", "IMPLAUSIBLE_SHARPE,TOO_FEW_OBSERVATIONS,ZERO_DECLARED_COSTS"),
    "fixtures/mt5_history.html": (
        "D", "2024-03-01", "2024-03-05", 3, 0.0094, -0.00963, None, 0.275636,
        "ND/ND/PS/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/mt5_tester.html": (
        "D", "2024-01-01", "2024-01-08", 6, 0.006305, -0.002181, 6.646419, 0.049521,
        "WK/WK/PS/ND/FL/ND",
        "HIDDEN_FLOATING_DRAWDOWN,IMPLAUSIBLE_SHARPE,TOO_FEW_OBSERVATIONS"),
    "fixtures/ninjatrader.csv": (
        "D", "2026-01-05", "2026-01-07", 3, -0.010274, -0.039793, None, 0.953198,
        "ND/ND/FL/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/quantconnect_trades.csv": (
        "D", "2024-03-01", "2024-03-05", 3, 0.0053, -0.012378, None, 0.289333,
        "ND/ND/PS/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/tradingview_g1.csv": (
        "D", "2024-11-01", "2024-11-05", 3, 0.00085, -0.00409, None, 0.086477,
        "ND/ND/FL/ND/FL/ND", "TOO_FEW_OBSERVATIONS,TRADE_PNL_MISMATCH,ZERO_DECLARED_COSTS"),
    "fixtures/tradingview_g3b.csv": (
        "D", "2026-02-27", "2026-03-03", 3, 0.00085, -0.00409, None, 0.086477,
        "ND/ND/PS/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/vectorbt_trades.csv": (
        "D", "2024-01-01", "2024-01-20", 20, 0.051097, -0.03612, 2.40107, 0.435265,
        "FL/WK/PS/ND/FL/ND", "TOO_FEW_OBSERVATIONS"),
    "fixtures/mt5_tester.html+mt5_optimization.xml": (
        "D", "2024-01-01", "2024-01-08", 6, 0.006305, -0.002181, 6.646419, 0.049521,
        "WK/WK/PS/ND/FL/ND",
        "HIDDEN_FLOATING_DRAWDOWN,IMPLAUSIBLE_SHARPE,TOO_FEW_OBSERVATIONS"),
    "examples/sample_equity.csv": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/ND/ND/WK/ND", "ZERO_DECLARED_COSTS"),
    "examples/sample_equity.csv+sample_trades.csv": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/PS/ND/WK/ND", "TRADES_EQUITY_UNRELATED,ZERO_DECLARED_COSTS"),
    "examples/sample_equity.csv+trades declared": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/PS/PS/WK/ND", "TRADES_EQUITY_UNRELATED"),
    "synthetic/positive_drift": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/ND/ND/WK/ND", "ZERO_DECLARED_COSTS"),
    "synthetic/positive_drift;semicolon": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/ND/ND/WK/ND", "ZERO_DECLARED_COSTS"),
    "synthetic/returns_frame": (
        "C", "2019-01-01", "2021-04-20", 601, 0.369762, -0.151795, 0.94576, 0.157846,
        "WK/WK/ND/ND/WK/ND", "ZERO_DECLARED_COSTS"),
    "synthetic/best_of_n_walks+variants": (
        "C", "2019-01-02", "2020-12-17", 512, 0.83313, -0.148953, 2.038054, 0.158117,
        "PS/WK/ND/ND/PS/ND", ""),
    "synthetic/stale_marks": (
        "D", "2019-01-02", "2020-07-14", 400, 0.121278, -0.179453, 0.55181, 0.158179,
        "FL/WK/ND/ND/FL/ND", "STALE_MARKS,ZERO_DECLARED_COSTS"),
    "synthetic/spiked": (
        "D", "2019-01-02", "2020-07-14", 400, 6.945676, -0.133111, 1.977528, 0.818733,
        "PS/PS/ND/ND/FL/ND", "MAD_SPIKES,ZERO_DECLARED_COSTS"),
    "synthetic/positive_drift+trades_frame": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/PS/ND/WK/ND", "TRADES_EQUITY_UNRELATED,ZERO_DECLARED_COSTS"),
    "synthetic/positive_drift+trades_frame short": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/PS/ND/WK/ND", "TRADES_EQUITY_UNRELATED,ZERO_DECLARED_COSTS"),
    "synthetic/positive_drift+trades_following": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/PS/ND/PS/ND", ""),
    "synthetic/positive_drift+benchmark_lower_drift": (
        "B", "2019-01-02", "2024-10-01", 1500, 4.89628, -0.131589, 2.035296, 0.157907,
        "PS/PS/ND/ND/WK/PS", "ZERO_DECLARED_COSTS"),
    "synthetic/mt5_report": (
        "D", "2022-12-30", "2024-07-12", 401, -0.138444, -0.288694, -0.334162, 0.219121,
        "FL/FL/FL/ND/PS/ND", ""),
    "synthetic/mt5_report+optimization": (
        "D", "2022-12-30", "2024-07-12", 401, -0.138444, -0.288694, -0.334162, 0.219121,
        "FL/FL/FL/ND/WK/ND", "TRIALS_BELOW_VARIANTS"),
    "synthetic/mt5_report tampered fixture": (
        "D", "2024-01-01", "2024-01-08", 6, 0.006305, -0.002181, 6.646419, 0.049521,
        "WK/WK/PS/ND/FL/ND",
        "FORENSIC_BALANCE_CHAIN_SIGNAL,HIDDEN_FLOATING_DRAWDOWN,IMPLAUSIBLE_SHARPE,"
        "MONETARY_RECONCILIATION_MISMATCH,TOO_FEW_OBSERVATIONS"),
}  # fmt: skip

CASES = {
    case["name"]: case
    for case in TOOL.cases(None)
    if case["name"].startswith(("fixtures/", "examples/", "synthetic/"))
}


def test_every_file_of_the_repository_is_frozen() -> None:
    assert sorted(CASES) == sorted(FROZEN)


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_files_already_read_correctly_read_the_same(name: str) -> None:
    klass, first, last, rows, total, drawdown, sharpe, volatility, statuses, flags = FROZEN[name]
    record = TOOL.run_case(CASES[name])
    assert record["outcome"] == "audited"
    head, result = record["headline"], record["result"]
    assert head["class"] == klass
    assert (head["first"][:10], head["last"][:10], head["observations"]) == (first, last, rows)
    performance = result["performance"]
    for key, wanted in (("total_return", total), ("max_drawdown", drawdown),
                        ("volatility", volatility)):  # fmt: skip
        assert performance[key]["evidence"] == "MEASURED"
        assert performance[key]["value"] == pytest.approx(wanted, abs=1e-6)
    if sharpe is None:
        assert rows - 1 < 3
        assert performance["sharpe"]["evidence"] == "NOT_MEASURED"
    else:
        assert performance["sharpe"]["evidence"] == "MEASURED"
        assert performance["sharpe"]["value"] == pytest.approx(sharpe, abs=1e-6)
    assert list(head["dimensions"].values()) == [STATUS[code] for code in statuses.split("/")]
    assert ",".join(flag.split(":")[0] for flag in head["red_flags"]) == flags
    # No file of the repository writes its dates with numbers only, day or month first.
    assert not any(TOOL.DATE_NOTE in warning for warning in head["warnings"])


def test_the_comparison_tells_intended_changes_from_the_rest() -> None:
    before = TOOL.run_case(CASES["fixtures/ninjatrader.csv"])
    base = {"cases": [before]}
    assert [row["paths"] for row in TOOL.differences(base, {"cases": [before]})] == [[]]
    moved = {**before, "headline": {**before["headline"], "class": "A"}}
    (row,) = TOOL.differences(base, {"cases": [moved]})
    assert row["paths"] == ['.headline.class: "D" -> "A"']
    assert not TOOL.intended(row)
