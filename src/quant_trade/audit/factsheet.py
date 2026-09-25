"""A fund factsheet's monthly returns table: one row per year, one column per month.

Funds, managed accounts and track records are usually shared as a grid,
not as a dated series::

    Year, Jan, Feb, ..., Dec, YTD
    2021, 1.2%, -0.4%, ..., 0.9%, 8.1%

This module recognises that grid (month headers in English, Spanish,
Portuguese, French, German or Italian, or the numbers 1 to 12), and turns it
into month-end returns the rest of the audit reads like any return series.
A year's own total column, when present, is DECLARED: it is compared with
the year's months compounded, and a year whose total does not match either
the compounded or the summed months is listed as a warning, since an edited
month usually leaves its year total behind.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import pandas as pd

#: Month header prefixes, lower case without accents or dots, by month.
MONTH_PREFIXES: dict[int, tuple[str, ...]] = {
    1: ("jan", "ene", "gen", "jän"),
    2: ("feb", "fev", "fév"),
    3: ("mar", "mär", "mrz"),
    4: ("apr", "abr", "avr"),
    5: ("may", "mai", "mag"),
    6: ("jun", "juin", "giu"),
    7: ("jul", "juil", "lug"),
    8: ("aug", "ago", "aoû", "aou"),
    9: ("sep", "set"),
    10: ("oct", "okt", "out", "ott"),
    11: ("nov",),
    12: ("dec", "dic", "déc", "dez"),
}
#: Headers of a year's total column.
TOTAL_HEADERS = (
    "ytd",
    "total",
    "year",
    "annual",
    "anual",
    "año",
    "ano",
    "jahr",
    "année",
    "annee",
    "anno",
    "yr",
    "fy",
)
#: A year's total may differ from its months by this much (in return units)
#: before it is listed: factsheets round each month to two decimals.
TOTAL_TOLERANCE = 0.0015
#: Returns in a grid are percentages unless every value looks like a fraction.
PERCENT_MEDIAN = 0.2

_YEAR = re.compile(r"^(19|20|21)\d{2}(\.0+)?$")


@dataclass
class MonthlyGrid:
    """Month-end returns read from a grid, and what the reading assumed."""

    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    #: Years whose stated total matches neither the compounded nor the summed months.
    mismatched_years: list[int] = field(default_factory=list)


def _month(header: str) -> int | None:
    text = header.strip().lower().replace(".", "").replace("_", "")
    if text.isdigit() and 1 <= int(text) <= 12:
        return int(text)
    for month, prefixes in MONTH_PREFIXES.items():
        if any(text.startswith(prefix) for prefix in prefixes) and len(text) <= 10:
            return month
    return None


def _number(cell: object) -> tuple[float | None, bool]:
    """A cell as a float, and whether it carried a ``%``; blanks are None."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return None, False
    if isinstance(cell, int | float) and not isinstance(cell, bool):
        return float(cell), False
    text = str(cell).strip().replace("−", "-").replace(" ", "").replace(" ", "")
    if text in {"", "-", "--", "—", "n/a", "na", "nan"}:
        return None, False
    percent = "%" in text
    text = text.replace("%", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    # "1,25" is a decimal comma; "1,250.5" a thousands separator.
    decimal_comma = "," in text and "." not in text
    text = text.replace(",", "." if decimal_comma else "")
    try:
        value = float(text)
    except ValueError:
        return None, percent
    return (-value if negative else value), percent


def _year_column(frame: pd.DataFrame, skip: set[str]) -> str | None:
    for column in frame.columns:
        if column in skip:
            continue
        cells = [str(v).strip() for v in frame[column] if str(v).strip() not in {"", "nan"}]
        if cells and all(_YEAR.match(cell) for cell in cells):
            return str(column)
    return None


def monthly_grid(frame: pd.DataFrame) -> MonthlyGrid | None:
    """The grid's month-end returns (as fractions), or None when it is not one."""
    months = {str(c): m for c in frame.columns if (m := _month(str(c))) is not None}
    if sorted(months.values()) != list(range(1, 13)):
        return None
    year_col = _year_column(frame, set(months))
    if year_col is None:
        return None
    total_col = next(
        (str(c) for c in frame.columns if str(c) in TOTAL_HEADERS and str(c) != year_col),
        None,
    )
    cells: list[tuple[int, int, float]] = []
    totals: dict[int, float] = {}
    any_percent = False
    for _, row in frame.iterrows():
        year = int(float(str(row[year_col]).strip()))
        for column, month in months.items():
            value, percent = _number(row[column])
            any_percent |= percent
            if value is not None:
                cells.append((year, month, value))
        if total_col is not None:
            value, percent = _number(row[total_col])
            any_percent |= percent
            if value is not None:
                totals[year] = value
    if len(cells) < 2:
        return None
    magnitudes = sorted(abs(value) for _, _, value in cells)
    median = magnitudes[len(magnitudes) // 2]
    scale = 100.0 if any_percent or median > PERCENT_MEDIAN else 1.0
    cells.sort()
    if len({(y, m) for y, m, _ in cells}) != len(cells):
        return None
    stamps = [
        pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.offsets.MonthEnd(0) for y, m, _ in cells
    ]
    out = pd.DataFrame({"timestamp": stamps, "ret": [v / scale for _, _, v in cells]})
    grid = MonthlyGrid(frame=out)
    grid.warnings.append(
        "read as a monthly returns table (one row per year, one column per month)"
        + ("; values taken as percentages" if scale == 100.0 else "; values taken as fractions")
    )
    for year, stated in sorted(totals.items()):
        months_of_year = [v / scale for y, _, v in cells if y == year]
        if not months_of_year:
            continue
        compounded = math.prod(1.0 + r for r in months_of_year) - 1.0
        summed = sum(months_of_year)
        target = stated / scale
        if min(abs(target - compounded), abs(target - summed)) > TOTAL_TOLERANCE:
            grid.mismatched_years.append(year)
    if grid.mismatched_years:
        grid.warnings.append(
            "the stated year total does not match its months for "
            + ", ".join(str(y) for y in grid.mismatched_years)
        )
    return grid


__all__ = ["MONTH_PREFIXES", "MonthlyGrid", "monthly_grid"]
