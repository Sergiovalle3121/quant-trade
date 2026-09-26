"""The year-by-year table never shows a year that holds only the starting point."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import _subperiods


def _curve(stamps: pd.DatetimeIndex, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.006, 0.03, len(stamps) - 1)
    equity = 100.0 * np.cumprod(np.r_[1.0, 1.0 + returns])
    return pd.DataFrame({"timestamp": stamps.tz_localize("UTC"), "equity": equity})


def _years(rows: list[dict]) -> list[int]:
    return [row["year"] for row in rows]


def _chained(rows: list[dict]) -> float:
    return float(np.prod([1.0 + row["return"]["value"] for row in rows]) - 1.0)


def test_a_fund_grid_opening_on_31_december_starts_with_its_first_full_year() -> None:
    frame = _curve(pd.date_range("2018-12-31", periods=73, freq="ME"))
    rows = _subperiods(frame)
    assert _years(rows) == [2019, 2020, 2021, 2022, 2023, 2024]
    total = frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1.0
    assert _chained(rows) == pytest.approx(total)
    # The first year is measured from the opening value, not from January.
    january_close = frame["equity"].iloc[12] / frame["equity"].iloc[0] - 1.0
    assert rows[0]["return"]["value"] == pytest.approx(january_close)


def test_a_daily_curve_starting_on_the_last_day_of_a_year_drops_that_day_only() -> None:
    stamps = pd.DatetimeIndex([pd.Timestamp("2020-12-31")]).append(
        pd.bdate_range("2021-01-04", periods=400)
    )
    frame = _curve(stamps, seed=1)
    rows = _subperiods(frame)
    assert _years(rows) == [2021, 2022]
    total = frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1.0
    assert _chained(rows) == pytest.approx(total)


def test_a_first_year_with_two_points_keeps_its_row() -> None:
    stamps = pd.DatetimeIndex([pd.Timestamp("2020-12-30"), pd.Timestamp("2020-12-31")]).append(
        pd.bdate_range("2021-01-04", periods=300)
    )
    rows = _subperiods(_curve(stamps, seed=2))
    assert _years(rows)[0] == 2020


def test_a_curve_inside_one_year_keeps_its_single_row() -> None:
    frame = _curve(pd.bdate_range("2021-02-01", periods=120), seed=3)
    rows = _subperiods(frame)
    assert _years(rows) == [2021]


def test_a_single_point_file_is_left_as_the_table_gives_it() -> None:
    frame = _curve(pd.DatetimeIndex([pd.Timestamp("2021-12-31"), pd.Timestamp("2021-12-31")]))
    frame = frame.iloc[:1]
    assert len(_subperiods(frame)) == 1
