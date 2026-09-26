"""Return series and equity curves: percent-named return columns, the
Portuguese ``Data`` date column and decimal commas (``schema.parse_equity_csv``)."""

from __future__ import annotations

import pytest

from quant_trade.audit.schema import parse_equity_csv

PERCENT_WARNING = "returns were percent-formatted; divided by 100"


def _returns(text: str) -> list[float]:
    series = parse_equity_csv(text.encode(), what="returns")
    return [round(value, 6) for value in series.frame["ret"].dropna().tolist()]


@pytest.mark.parametrize(
    "header",
    ["Date,Return %", "Fecha,Rendimiento %", "Data,Retorno %", "date,% return", "Date,Return (%)"],
)
def test_a_percent_named_return_column_is_read_as_percentages(header: str) -> None:
    text = f"{header}\n2024-01-31,1.5\n2024-02-29,-0.5\n2024-03-31,2.0\n"
    series = parse_equity_csv(text.encode(), what="returns")
    assert series.source == "returns"
    assert _returns(text) == [0.015, -0.005, 0.02]
    assert PERCENT_WARNING in series.warnings


def test_a_small_value_in_a_percent_column_stays_a_percentage() -> None:
    # A money-market fund's 0.03 in a "Return %" column is 0.03 %, not 3 %,
    # as factsheet grids read it.
    assert _returns("Date,Return %\n2024-01-31,0.03\n2024-02-29,0.02\n") == [0.0003, 0.0002]


def test_a_plain_return_column_keeps_its_fractions() -> None:
    text = "date,return\n2024-01-31,0.015\n2024-02-29,-0.005\n"
    series = parse_equity_csv(text.encode(), what="returns")
    assert _returns(text) == [0.015, -0.005]
    assert PERCENT_WARNING not in series.warnings


def test_an_english_date_column_wins_over_a_data_column() -> None:
    text = "date,data,return\n2024-01-31,x,0.01\n2024-02-29,y,0.02\n"
    series = parse_equity_csv(text.encode(), what="returns")
    assert series.frame["timestamp"].dt.day.tolist()[-2:] == [31, 29]


def test_decimal_commas_in_a_semicolon_file_are_read_as_decimals() -> None:
    # A Portuguese or Spanish export: ";" between columns, "," as decimal point.
    assert _returns("Data;Retorno %\n2024-01-31;1,5\n2024-02-29;-0,5\n") == [0.015, -0.005]
    curve = parse_equity_csv(
        b"Fecha;Equity\n2024-01-31;10.000,50\n2024-02-29;10.100,25\n2024-03-31;10000,5\n",
        what="equity",
    )
    assert curve.frame["equity"].round(2).tolist() == [10000.5, 10100.25, 10000.5]


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (['"10,000.50"', '"10,100.25"'], [10000.5, 10100.25]),
        (['"10,000"', '"10,100"'], [10000.0, 10100.0]),
        (["10000.5", "10100.25"], [10000.5, 10100.25]),
    ],
)
def test_thousands_commas_and_decimal_dots_read_as_before(
    cells: list[str], expected: list[float]
) -> None:
    text = "date,equity\n" + "".join(
        f"2024-0{month},{cell}\n".replace(f"2024-0{month}", f"2024-0{month}-28")
        for month, cell in enumerate(cells, start=1)
    )
    curve = parse_equity_csv(text.encode(), what="equity")
    assert curve.frame["equity"].round(2).tolist() == expected


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        # In a decimal-comma column the dots group thousands.
        (["1.234", "1,5"], [1234.0, 1.5]),
        (["-1,5", "2,25"], [-1.5, 2.25]),
        (["(1,5)", "2,0"], [-1.5, 2.0]),
        (["(1,234.50)", "10"], [-1234.5, 10.0]),
        (["€1.234,50", "€10,5"], [1234.5, 10.5]),
        (["R$ 1.234,56", "R$ 10,00"], [1234.56, 10.0]),
        (["US$1,234.56", "5"], [1234.56, 5.0]),
        (["1,5%", "-0,5%"], [1.5, -0.5]),
        (["1,5"], [1.5]),
        (["1e-3", "2E2"], [0.001, 200.0]),
    ],
)
def test_mixed_number_formats(cells: list[str], expected: list[float]) -> None:
    import pandas as pd  # noqa: PLC0415

    from quant_trade.audit.schema import _to_numeric  # noqa: PLC0415

    assert _to_numeric(pd.Series(cells))[0].tolist() == expected
