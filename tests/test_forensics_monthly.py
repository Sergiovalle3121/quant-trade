"""``MONTHLY_DIGITS``: digit statistics of a factsheet's monthly returns
table (spec §3.23). Offline; the grids are built inline from tiny CSV text
because the fixtures hold no factsheet."""

from __future__ import annotations

import io
import math
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest

from quant_trade.audit import factsheet, importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.checks import Context, monthly
from quant_trade.audit.forensics.header import Header, read_header
from quant_trade.audit.forensics.results import (
    EVIDENCE,
    MEASURED,
    NOT_MEASURED,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    RawOutcome,
)
from quant_trade.audit.forensics.review import REASONS, review
from quant_trade.audit.forensics.thresholds import MONTHLY_MIN_VALUES, MONTHLY_REPEAT_MIN
from quant_trade.evidence.canonical_json import canonical_dumps

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
PRIVATE_TEXT = ("12345678", "Demo Trader", "Synthetic Broker", "SyntheticBroker-Demo", "FixtureEA")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#: 96 distinct two-decimal months, -0.48 to 0.47 points, one of them zero.
BASE = [f"{(i - 48) / 100:.2f}" for i in range(96)]
#: 96 distinct one-decimal months: a rounded factsheet.
ROUNDED = [f"{(i - 48) / 10:.1f}" for i in range(96)]


def _grid_csv(
    values: list[str], *, total: bool = True, decimals: int = 2, fractions: bool = False
) -> bytes:
    """A year-by-month table of the printed ``values`` (percentage points)."""
    lines = [",".join(["Year", *MONTHS] + (["YTD"] if total else []))]
    for offset in range(0, len(values), 12):
        chunk = values[offset : offset + 12]
        cells = [f"{Decimal(v) / 100:.4f}" if fractions else f"{v}%" for v in chunk]
        cells += [""] * (12 - len(chunk))
        line = [str(2016 + offset // 12), *cells]
        if total:
            compounded = (math.prod(1 + float(v) / 100 for v in chunk) - 1) * 100
            line.append(f"{compounded:.{decimals}f}%")
        lines.append(",".join(line))
    return ("\n".join(lines) + "\n").encode()


def _grid(data: bytes) -> factsheet.MonthlyGrid:
    grid = factsheet.monthly_grid(pd.read_csv(io.BytesIO(data)))
    assert grid is not None
    return grid


def _table() -> rows.RawTable:
    return rows.RawTable("monthly", families.MONTHLY, (), (), "none", "none", "none", 0, False)


def _ctx(grid: object) -> Context:
    return Context(family=families.MONTHLY, header=Header(), monthly=grid)


def _run(grid: object) -> RawOutcome:
    return monthly.run_MONTHLY_DIGITS(_table(), _ctx(grid))


def _figure(outcome: RawOutcome, key: str) -> str | None:
    for name, value, _evidence in outcome.figures:
        if name == key:
            return value
    return None


def _serialised(outcome: RawOutcome) -> str:
    return canonical_dumps(
        {
            "hits": outcome.hits,
            "figures": [list(figure) for figure in outcome.figures],
            "examples": list(outcome.examples),
            "reason": outcome.reason,
        }
    )


def _chi_square(values: list[str]) -> str:
    """The test's own chi-square of the last digit, from the printed strings."""
    counts = Counter(text[-1] for text in values)
    total = len(values)
    chi2 = sum(Fraction((10 * counts.get(str(d), 0) - total) ** 2, 10 * total) for d in range(10))
    return str((Decimal(chi2.numerator) / Decimal(chi2.denominator)).quantize(Decimal("0.001")))


def _edit(data: bytes, year: str, month_index: int, text: str) -> bytes:
    """One cell of the CSV replaced, the year's total left as it was."""
    lines = data.decode().splitlines()
    for position, line in enumerate(lines):
        cells = line.split(",")
        if cells[0] == year:
            cells[month_index + 1] = text
            lines[position] = ",".join(cells)
            return ("\n".join(lines) + "\n").encode()
    raise AssertionError(year)


# ---------------------------------------------------------------------------
# Skips
# ---------------------------------------------------------------------------


def test_without_a_grid_the_format_is_not_covered() -> None:
    outcome = _run(None)
    assert outcome.not_measured and outcome.reason == "format_not_covered"
    data = (FIXTURES / "mt4_statement.htm").read_bytes()
    table = rows.load(data, importers.detect_format(data))
    ctx = Context(family=table.family, header=read_header(table))
    assert monthly.run_MONTHLY_DIGITS(table, ctx).reason == "format_not_covered"


def test_a_short_grid_has_too_few_values() -> None:
    outcome = _run(_grid(_grid_csv(BASE[: MONTHLY_MIN_VALUES - 1])))
    assert outcome.not_measured and outcome.reason == "too_few_values"
    assert _figure(outcome, "n_rows") == str(MONTHLY_MIN_VALUES - 1)
    assert not _run(_grid(_grid_csv(BASE[:MONTHLY_MIN_VALUES]))).not_measured


def test_skip_reasons_are_on_the_closed_list() -> None:
    for grid in (None, _grid(_grid_csv(BASE[:12]))):
        outcome = _run(grid)
        assert outcome.not_measured and outcome.reason in REASONS
        assert _figure(outcome, "n_hits") == "0"
        assert [e for k, _v, e in outcome.figures if k == "n_hits"] == [NOT_MEASURED]


# ---------------------------------------------------------------------------
# A two-decimal factsheet
# ---------------------------------------------------------------------------


def test_a_two_decimal_factsheet_without_findings() -> None:
    outcome = _run(_grid(_grid_csv(BASE)))
    assert outcome.hits == 0 and outcome.examples == ()
    assert _figure(outcome, "n_rows") == "96"
    assert _figure(outcome, "n_hits") == "0"
    assert _figure(outcome, "decimals") == "2"
    assert _figure(outcome, "rounding_grid") == "0"
    assert _figure(outcome, "values_repeated_3plus") == "0"
    assert _figure(outcome, "max_multiplicity") == "1"
    assert _figure(outcome, "zero_months") == "1"
    assert _figure(outcome, "year_mismatch") == "0"
    # Digits 1..7 appear ten times, 0 and 8 nine times, 9 eight times: 440 / 960.
    assert _figure(outcome, "last_digit_chi2") == "0.458" == _chi_square(BASE)


def test_an_edited_month_leaves_its_year_total_behind() -> None:
    edited = _edit(_grid_csv(BASE), "2017", 2, "9.99%")
    grid = _grid(edited)
    assert grid.mismatched_years == [2017]
    outcome = _run(grid)
    assert outcome.hits == 1 and outcome.examples == ()
    assert _figure(outcome, "year_mismatch") == "1"
    assert _figure(outcome, "n_hits") == "1"
    assert _figure(outcome, "values_repeated_3plus") == "0"


def test_repeated_values_count_off_the_rounding_grid() -> None:
    values = list(BASE)
    for position in (3, 17, 31):
        values[position] = "1.23"
    for position in (5, 40, 77):
        values[position] = "0.00"
    outcome = _run(_grid(_grid_csv(values)))
    assert _figure(outcome, "values_repeated_3plus") == "2"
    assert _figure(outcome, "max_multiplicity") == "4"
    assert _figure(outcome, "zero_months") == "4"
    assert _figure(outcome, "year_mismatch") == "0"
    # The zero is counted apart; the value printed three times is the hit.
    assert outcome.hits == 1 and _figure(outcome, "n_hits") == "1"
    assert _figure(outcome, "last_digit_chi2") == _chi_square(values)


def test_a_value_below_the_repeat_minimum_is_not_counted() -> None:
    values = list(BASE)
    for position in range(MONTHLY_REPEAT_MIN - 1):
        values[position] = "1.23"
    outcome = _run(_grid(_grid_csv(values)))
    assert outcome.hits == 0
    assert _figure(outcome, "values_repeated_3plus") == "0"
    assert _figure(outcome, "max_multiplicity") == str(MONTHLY_REPEAT_MIN - 1)


# ---------------------------------------------------------------------------
# Scoping: a rounded factsheet
# ---------------------------------------------------------------------------


def test_a_rounding_grid_is_scoped_out() -> None:
    values = list(ROUNDED)
    for position in (3, 17, 31):
        values[position] = "1.2"
    edited = _edit(_grid_csv(values, decimals=1), "2018", 4, "9.9%")
    grid = _grid(edited)
    assert grid.mismatched_years == [2018]
    outcome = _run(grid)
    assert not outcome.not_measured
    assert outcome.hits == 0 and _figure(outcome, "n_hits") == "0"
    assert _figure(outcome, "decimals") == "1"
    assert _figure(outcome, "rounding_grid") == "1"
    assert _figure(outcome, "values_repeated_3plus") == "1"
    assert _figure(outcome, "year_mismatch") == "1"
    # 2018 is the third year: its May sits at position 24 + 4 of the values.
    assert _figure(outcome, "last_digit_chi2") == _chi_square(values[:28] + ["9.9"] + values[29:])


def test_one_two_decimal_month_takes_the_grid_off_the_rounding_grid() -> None:
    values = list(ROUNDED)
    values[10] = "0.25"
    outcome = _run(_grid(_grid_csv(values)))
    assert _figure(outcome, "decimals") == "2"
    assert _figure(outcome, "rounding_grid") == "0"
    # Every other month now reads with a trailing zero: the grid keeps no cell text.
    assert _figure(outcome, "last_digit_chi2") == _chi_square([f"{Decimal(v):.2f}" for v in values])
    assert _figure(outcome, "last_digit_chi2") != _chi_square(values)


# ---------------------------------------------------------------------------
# Reading the grid's floats
# ---------------------------------------------------------------------------


def test_fraction_and_percent_grids_give_the_same_digits() -> None:
    as_percent = _run(_grid(_grid_csv(BASE, total=False)))
    as_fraction = _run(_grid(_grid_csv(BASE, total=False, fractions=True)))
    assert as_fraction.figures == as_percent.figures
    assert _figure(as_fraction, "decimals") == "2"


def test_division_noise_does_not_change_the_precision() -> None:
    stamps = pd.date_range("2015-12-31", periods=97, freq="ME", tz="UTC")
    returns = [float(v) / 100 for v in ROUNDED] + [float("nan")]
    assert repr(1.1 / 100) == "0.011000000000000001"
    grid = factsheet.MonthlyGrid(frame=pd.DataFrame({"timestamp": stamps, "ret": returns}))
    outcome = _run(grid)
    assert _figure(outcome, "n_rows") == "96"
    assert _figure(outcome, "decimals") == "1"
    assert _figure(outcome, "rounding_grid") == "1"
    assert _figure(outcome, "year_mismatch") == "0"


def test_negative_zero_and_integers_read_as_digits() -> None:
    values = [f"{i - 48}" for i in range(96)]
    values[48] = "-0"
    stamps = pd.date_range("2015-12-31", periods=96, freq="ME", tz="UTC")
    returns = [float(v) / 100 for v in values]
    grid = factsheet.MonthlyGrid(frame=pd.DataFrame({"timestamp": stamps, "ret": returns}))
    outcome = _run(grid)
    assert _figure(outcome, "decimals") == "0"
    assert _figure(outcome, "zero_months") == "1"
    assert _figure(outcome, "last_digit_chi2") == "0.458"


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def _samples() -> list[tuple[str, object]]:
    repeated = list(BASE)
    for position in (3, 17, 31):
        repeated[position] = "1.23"
    return [
        ("none", None),
        ("short", _grid(_grid_csv(BASE[:24]))),
        ("plain", _grid(_grid_csv(BASE))),
        ("edited", _grid(_edit(_grid_csv(BASE), "2017", 2, "9.99%"))),
        ("repeated", _grid(_grid_csv(repeated))),
        ("rounded", _grid(_grid_csv(ROUNDED, decimals=1))),
    ]


@pytest.mark.parametrize("name,grid", _samples(), ids=[name for name, _ in _samples()])
def test_figures_are_text_with_evidence_and_no_private_text(name: str, grid: object) -> None:
    outcome = _run(grid)
    keys = [key for key, _value, _evidence in outcome.figures]
    assert len(keys) == len(set(keys)), keys
    assert {"n_rows", "n_hits"} <= set(keys)
    if not outcome.not_measured:
        assert _figure(outcome, "n_hits") == str(outcome.hits)
        assert all(evidence == MEASURED for _k, _v, evidence in outcome.figures)
    for key, value, evidence in outcome.figures:
        assert key == key.lower() and isinstance(value, str) and value
        assert evidence in EVIDENCE, key
        assert "%" not in value and "e" not in value.lower(), (key, value)
    assert outcome.examples == ()
    serialised = _serialised(outcome)
    for private in PRIVATE_TEXT:
        assert private not in serialised


@pytest.mark.parametrize("name,grid", _samples(), ids=[name for name, _ in _samples()])
def test_outcomes_are_deterministic(name: str, grid: object) -> None:
    assert _run(grid) == _run(grid)


def test_review_applies_the_status_rule() -> None:
    plain = review(b"", source_format=None, monthly=_grid(_grid_csv(BASE)))
    assert plain.family == families.MONTHLY and plain.rows_read == 0
    check = plain.check("MONTHLY_DIGITS")
    assert check.status == STATUS_CLEAN and check.applies and check.examples == ()
    edited = review(
        b"", source_format=None, monthly=_grid(_edit(_grid_csv(BASE), "2017", 2, "9.99%"))
    )
    check = edited.check("MONTHLY_DIGITS")
    assert check.status == STATUS_INFO and check.figure("year_mismatch") == "1"
    assert check.calibration == ()
    short = review(b"", source_format=None, monthly=_grid(_grid_csv(BASE[:24])))
    check = short.check("MONTHLY_DIGITS")
    assert check.status == STATUS_NOT_MEASURED and check.reason == "too_few_values"
    again = review(b"", source_format=None, monthly=_grid(_grid_csv(BASE)))
    assert plain.as_dict() == again.as_dict()
