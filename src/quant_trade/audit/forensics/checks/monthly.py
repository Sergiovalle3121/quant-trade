"""``MONTHLY_DIGITS``: digit statistics of a factsheet's monthly returns
table (spec §3.23), ``INFO`` by design in v1.

The upload is a ``factsheet.MonthlyGrid``: month-end returns as float
fractions (``value / scale``), the years whose stated total matches neither
the compounded nor the summed months, and nothing else. The grid keeps no
cell text, so the printed digits are reconstructed: every value is read in
percentage points from the float's shortest text with the division noise
dropped, and the grid's precision is the most decimals any value needs. A
factsheet printed at two decimals comes back exactly (``1.20`` is ``1.20``
when another month needs two decimals); a grid whose values all sit on a
0.1-point grid is reported as a rounding grid.

Figures (all ``MEASURED``): ``n_rows`` (monthly values), ``n_hits``,
``decimals`` (the reconstructed precision), ``last_digit_chi2`` (chi-square
of the last printed digit against a uniform spread, three decimals),
``values_repeated_3plus`` (distinct values printed at least
``MONTHLY_REPEAT_MIN`` times), ``max_multiplicity``, ``rounding_grid``,
``zero_months`` and ``year_mismatch`` (the grid's own count).

A hit is a year whose stated total fits neither reading, or a non-zero
value printed ``MONTHLY_REPEAT_MIN`` times or more. Scoping rule (D3): on a
rounding grid nothing counts as a hit. Rounding alone repeats values and
moves a year's total past the grid's fixed tolerance (about one genuine
year in six on a 0.1-point factsheet, none on a 0.01-point one); the
figures are still reported. Zero months are a flat or inactive period and
are counted apart. The last-digit chi-square is descriptive only (D17).

No text of the file reaches the result: the grid holds numbers only, and
the figures are counts and derived numbers. ``examples`` is empty: the
battery's table has no rows for a monthly upload.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.money import as_text
from quant_trade.audit.forensics.results import MEASURED, NOT_MEASURED, Figure, RawOutcome
from quant_trade.audit.forensics.rows import RawTable
from quant_trade.audit.forensics.thresholds import MONTHLY_MIN_VALUES, MONTHLY_REPEAT_MIN

_HUNDRED = Decimal(100)
#: The grid's floats are ``value / scale``; that division's noise sits far
#: below this many decimals of a percentage point, where it is dropped.
_NOISE_DECIMALS = 8
_NOISE_GRID = Decimal(1).scaleb(-_NOISE_DECIMALS)
#: Values that all need at most this many decimals sit on a 0.1-point grid.
_ROUNDING_GRID_DECIMALS = 1
#: Digits of the chi-square: the last printed digit is one of ten.
_DIGITS = 10


def _count(key: str, value: int) -> Figure:
    return (key, str(value), MEASURED)


def _flag(key: str, value: bool) -> Figure:
    return (key, "1" if value else "0", MEASURED)


def _unmeasured(key: str) -> Figure:
    return (key, "0", NOT_MEASURED)


def _percent_values(grid: Any) -> list[Decimal]:
    """The grid's monthly values in percentage points, division noise dropped."""
    frame = getattr(grid, "frame", None)
    if frame is None or "ret" not in getattr(frame, "columns", ()):
        return []
    values: list[Decimal] = []
    for ret in frame["ret"]:
        try:
            number = float(ret)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        values.append((Decimal(repr(number)) * _HUNDRED).quantize(_NOISE_GRID))
    return values


def _decimals(values: list[Decimal]) -> int:
    """The most decimals any value needs once trailing zeros are dropped."""
    most = 0
    for value in values:
        exponent = value.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < 0:
            most = max(most, -exponent)
    return most


def _chi_square(printed: list[str]) -> Decimal:
    """Chi-square of the last printed digit against a uniform spread, exact."""
    counts = [0] * _DIGITS
    for text in printed:
        counts[int(text[-1])] += 1
    total = len(printed)
    numerator = sum((_DIGITS * count - total) ** 2 for count in counts)
    return Decimal(numerator) / Decimal(_DIGITS * total)


def run_MONTHLY_DIGITS(table: RawTable, ctx: Context) -> RawOutcome:
    grid = ctx.monthly
    if grid is None:
        return RawOutcome.skip(
            "format_not_covered", figures=(_unmeasured("n_rows"), _unmeasured("n_hits"))
        )
    values = _percent_values(grid)
    if len(values) < MONTHLY_MIN_VALUES:
        return RawOutcome.skip(
            "too_few_values", figures=(_count("n_rows", len(values)), _unmeasured("n_hits"))
        )
    decimals = _decimals(values)
    printed = [as_text(value, decimals) for value in values]
    multiplicity: dict[str, int] = {}
    for text in printed:
        multiplicity[text] = multiplicity.get(text, 0) + 1
    repeated = sorted(text for text, count in multiplicity.items() if count >= MONTHLY_REPEAT_MIN)
    repeated_non_zero = [text for text in repeated if Decimal(text) != 0]
    zero_months = sum(1 for value in values if value == 0)
    rounding_grid = decimals <= _ROUNDING_GRID_DECIMALS
    year_mismatch = len(getattr(grid, "mismatched_years", None) or ())
    hits = 0 if rounding_grid else year_mismatch + len(repeated_non_zero)
    figures: tuple[Figure, ...] = (
        _count("n_rows", len(values)),
        _count("n_hits", hits),
        _count("decimals", decimals),
        ("last_digit_chi2", as_text(_chi_square(printed), 3), MEASURED),
        _count("values_repeated_3plus", len(repeated)),
        _count("max_multiplicity", max(multiplicity.values())),
        _flag("rounding_grid", rounding_grid),
        _count("zero_months", zero_months),
        _count("year_mismatch", year_mismatch),
    )
    return RawOutcome(hits=hits, figures=figures, examples=())


__all__ = ["run_MONTHLY_DIGITS"]
