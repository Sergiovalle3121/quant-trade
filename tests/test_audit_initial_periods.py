"""Opening observations are a base, not a zero-return year or month."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.engine import _subperiods
from quant_trade.audit.ride import ride_review


def _frame(stamps: pd.DatetimeIndex, equity: list[float] | np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": stamps, "equity": equity})


def test_december_opening_value_is_not_a_zero_return_year() -> None:
    stamps = pd.date_range("2019-12-31", periods=25, freq="ME", tz="UTC")
    equity = 100.0 * 1.01 ** np.arange(len(stamps))
    rows = _subperiods(_frame(stamps, equity))

    assert [row["year"] for row in rows] == [2020, 2021]
    assert rows[0]["return"]["value"] == pytest.approx(equity[12] / equity[0] - 1)
    compounded = np.prod([1 + row["return"]["value"] for row in rows]) - 1
    assert compounded == pytest.approx(equity[-1] / equity[0] - 1)


def test_first_year_with_a_return_keeps_its_row() -> None:
    stamps = pd.DatetimeIndex(
        [pd.Timestamp("2019-12-30", tz="UTC"), pd.Timestamp("2019-12-31", tz="UTC")]
    ).append(pd.date_range("2020-01-31", periods=12, freq="ME", tz="UTC"))
    rows = _subperiods(_frame(stamps, 100.0 + np.arange(len(stamps))))

    assert [row["year"] for row in rows] == [2019, 2020]
    assert rows[0]["return"]["value"] == pytest.approx(0.01)


def test_one_year_with_only_a_starting_point_keeps_its_single_row() -> None:
    rows = _subperiods(_frame(pd.DatetimeIndex([pd.Timestamp("2019-12-31", tz="UTC")]), [100.0]))
    assert len(rows) == 1 and rows[0]["year"] == 2019


def test_december_opening_value_is_not_a_zero_return_month() -> None:
    stamps = pd.date_range("2019-12-31", periods=20, freq="ME", tz="UTC")
    review = ride_review(_frame(stamps, 100.0 + np.arange(len(stamps))))

    assert review["months"]["value"] == 19
    assert review["positive_months"]["value"] == 1.0
    assert review["worst_month"]["value"] > 0
    assert review["worst_month_in"] == stamps[-1].strftime("%Y-%m")


def test_first_month_with_a_return_keeps_its_month_and_date() -> None:
    stamps = pd.DatetimeIndex(
        [pd.Timestamp("2019-12-30", tz="UTC"), pd.Timestamp("2019-12-31", tz="UTC")]
    ).append(pd.date_range("2020-01-31", periods=19, freq="ME", tz="UTC"))
    equity = [100.0, 95.0, *[96.0 + i for i in range(19)]]
    review = ride_review(_frame(stamps, equity))

    assert review["months"]["value"] == 20
    assert review["worst_month"]["value"] == pytest.approx(-0.05)
    assert review["worst_month_in"] == "2019-12"
