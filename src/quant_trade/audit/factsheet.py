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

Values are percentages when a cell carries ``%``; otherwise the year totals
decide (the reading under which the months add up to them), and without
totals the grid is read as percentages, as factsheets publish, with a note
saying so. A money-market fund's ``0.03`` is 0.03 %, not 3 %. Rows with no
readable month (a footnote, a separator, a year not yet started) are
skipped; a month cell that cannot be read is named in a warning.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

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
#: Longer headers of a year's total column, compared as letters and spaces.
TOTAL_PHRASES = (
    "full year",
    "yearly",
    "calendar year",
    "annual return",
    "total year",
    "total anual",
    "rentabilidad anual",
    "acumulado",
    "ytd return",
)
#: Cells that stand for "no value".
BLANKS = {"", "-", "--", "—", "n/a", "na", "nan", "none"}
#: The year totals settle the scale only when one reading misses them by less
#: than this share of the other's miss.
SCALE_MARGIN = 0.5
#: Unreadable months named in the warning before the rest are counted.
MAX_LISTED = 6
#: A year's total may differ from its months by this much (in return units)
#: before it is listed: factsheets round each month to two decimals.
TOTAL_TOLERANCE = 0.0015

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
    if text.lower() in BLANKS:
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


def _header(text: str) -> str:
    """A header in lower case with only its letters and single spaces."""
    letters = re.sub(r"[^a-zà-ÿ]+", " ", text.strip().lower())
    return " ".join(letters.split())


def _is_total(header: str) -> bool:
    text = _header(header)
    return text in TOTAL_HEADERS or text in TOTAL_PHRASES


def _year(cell: object) -> int | None:
    text = str(cell).strip()
    return int(float(text)) if _YEAR.match(text) else None


def _blank(cell: object) -> bool:
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return True
    return str(cell).strip().lower() in BLANKS


def _no_grid(message: str, message_es: str, code: str) -> Exception:
    # Imported here: ``schema`` reads this module lazily and owns ParseError.
    from quant_trade.audit.schema import ParseError

    return ParseError(message, message_es=message_es, code=code)


def _matches(cells: list[tuple[int, int, float]], totals: dict[int, float], scale: float) -> int:
    """Years whose stated total matches their months read at ``scale``."""
    hits = 0
    for year, stated in totals.items():
        months_of_year = [v / scale for y, _, v in cells if y == year]
        if not months_of_year:
            continue
        compounded = math.prod(1.0 + r for r in months_of_year) - 1.0
        summed = sum(months_of_year)
        target = stated / scale
        if min(abs(target - compounded), abs(target - summed)) <= TOTAL_TOLERANCE:
            hits += 1
    return hits


def _compounding_error(
    cells: list[tuple[int, int, float]], totals: dict[int, float], scale: float
) -> float:
    """How far the stated totals are from the months compounded at ``scale``,
    in the file's own units. Summing is blind to the scale, so only
    compounding tells percentages from fractions."""
    error = 0.0
    for year, stated in totals.items():
        months_of_year = [v / scale for y, _, v in cells if y == year]
        if months_of_year:
            error += abs((math.prod(1.0 + r for r in months_of_year) - 1.0) * scale - stated)
    return error


def monthly_grid(frame: pd.DataFrame) -> MonthlyGrid | None:
    """The grid's month-end returns (as fractions), or None when it is not one.

    Raises ``ParseError`` when the file has the twelve month columns of a
    grid but its years cannot be read, or a year appears twice.
    """
    headers = [str(c) for c in frame.columns]
    month_of = {i: m for i, h in enumerate(headers) if (m := _month(h)) is not None}
    if sorted(month_of.values()) != list(range(1, 13)):
        return None
    table = frame.to_numpy(dtype=object)

    # Footnotes, separators and years not yet started: no readable month.
    def has_month(row: Any) -> bool:
        return any(
            (value := _number(row[i])[0]) is not None and math.isfinite(value) for i in month_of
        )

    rows = [row for row in table if has_month(row)]
    if len(rows) < 1:
        return None
    others = [i for i in range(len(headers)) if i not in month_of]
    year_col = next(
        (i for i in others if all(_year(row[i]) is not None for row in rows)),
        None,
    )
    if year_col is None:
        raise _no_grid(
            "the file looks like a monthly returns table (one column per month) but not every "
            "row with returns has a year such as 2021 in its first column",
            "El archivo parece una tabla de rentabilidades mensuales (una columna por mes), "
            "pero no todas las filas con rentabilidades tienen un año como 2021 en su primera "
            "columna.",
            "grid_no_year",
        )
    years = [_year(row[year_col]) or 0 for row in rows]
    repeated = sorted({y for y in years if years.count(y) > 1})
    if repeated:
        listed = ", ".join(str(y) for y in repeated)
        raise _no_grid(
            f"the monthly returns table lists {listed} more than once; keep one row per year",
            f"La tabla de rentabilidades mensuales repite {listed}; deja una fila por año.",
            "grid_duplicate_year",
        )
    total_col = next((i for i in others if i != year_col and _is_total(headers[i])), None)

    cells: list[tuple[int, int, float]] = []
    totals: dict[int, float] = {}
    unreadable: list[str] = []
    any_percent = False
    for year, row in zip(years, rows, strict=True):
        for i, month in month_of.items():
            value, percent = _number(row[i])
            any_percent |= percent
            if value is not None and math.isfinite(value):
                cells.append((year, month, value))
            elif not _blank(row[i]):
                unreadable.append(f"{year}-{month:02d}")
        if total_col is not None:
            value, percent = _number(row[total_col])
            any_percent |= percent
            if value is not None and math.isfinite(value):
                totals[year] = value
    if len(cells) < 2:
        return None
    cells.sort()

    # The scale: a % sign settles it; otherwise the year totals, when the
    # file states them; otherwise percentages, as factsheets publish.
    if any_percent:
        scale, how = 100.0, "values taken as percentages"
    elif totals and (
        (as_fraction := _compounding_error(cells, totals, 1.0))
        < SCALE_MARGIN * (as_percent := _compounding_error(cells, totals, 100.0))
    ):
        scale, how = 1.0, "values taken as fractions, as the year totals confirm"
    elif totals and as_percent < SCALE_MARGIN * as_fraction:
        scale, how = 100.0, "values taken as percentages, as the year totals confirm"
    else:
        scale = 100.0
        how = (
            "values taken as percentages (the file shows no % sign: check one month "
            "against the factsheet)"
        )
    stamps = [
        pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.offsets.MonthEnd(0) for y, m, _ in cells
    ]
    out = pd.DataFrame({"timestamp": stamps, "ret": [v / scale for _, _, v in cells]})
    grid = MonthlyGrid(frame=out)
    grid.warnings.append(
        "read as a monthly returns table (one row per year, one column per month); " + how
    )
    if unreadable:
        shown = ", ".join(unreadable[:MAX_LISTED])
        if len(unreadable) > MAX_LISTED:
            shown += ", …"
        grid.warnings.append(
            f"{len(unreadable)} unreadable month(s) left out of the table: {shown}"
        )
    for year, stated in sorted(totals.items()):
        if _matches(cells, {year: stated}, scale) == 0 and any(y == year for y, _, _ in cells):
            grid.mismatched_years.append(year)
    if grid.mismatched_years:
        grid.warnings.append(
            "the stated year total does not match its months for "
            + ", ".join(str(y) for y in grid.mismatched_years)
        )
    return grid


__all__ = ["MONTH_PREFIXES", "MonthlyGrid", "monthly_grid"]
