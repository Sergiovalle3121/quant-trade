"""Fund-record math from the 2026-09-25 review: quarterly files, missing
months, a partial benchmark month and the calibration of the small-loss test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.fund import (
    _bin_share,
    _binomial_cdf,
    fund_review,
    monthly_returns,
)


def _monthly(r: np.ndarray, start: str = "2015-12-31") -> pd.DataFrame:
    stamps = pd.date_range(start, periods=len(r) + 1, freq="ME", tz="UTC")
    return pd.DataFrame({"timestamp": stamps, "equity": np.concatenate([[1.0], np.cumprod(1 + r)])})


def test_a_quarterly_record_is_not_read_as_monthly() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(0.03, 0.02, 28)
    stamps = pd.date_range("2015-12-31", periods=29, freq="QE", tz="UTC")
    frame = pd.DataFrame(
        {"timestamp": stamps, "equity": np.concatenate([[1.0], np.cumprod(1 + r)])}
    )
    review = fund_review(frame, 4.0)
    assert review["status"] == "NOT_MEASURED"


def test_a_missing_month_is_a_hole_not_a_longer_month() -> None:
    r = np.tile([0.02, 0.0], 18)
    frame = _monthly(r).drop(index=[10, 11, 12]).reset_index(drop=True)
    returns = monthly_returns(frame)
    # Rows 10-12 are gone: the returns into months 10-13 are holes, none merged.
    assert len(returns) == 32
    assert set(np.round(returns.to_numpy(), 12)) <= {0.02, 0.0}
    review = fund_review(frame, 12.0)
    assert review["status"] == "MEASURED"
    kept = np.delete(r, [9, 10, 11, 12])
    assert review["cagr"]["value"] == pytest.approx(np.prod(1 + kept) ** (12 / 32) - 1)
    assert review["missing_months"]["value"] == 4


def test_a_complete_record_has_no_missing_month() -> None:
    rng = np.random.default_rng(2)
    review = fund_review(_monthly(rng.normal(0.01, 0.03, 36)), 12.0)
    assert review["missing_months"]["value"] == 0


def test_a_daily_benchmark_ending_mid_month_drops_that_month() -> None:
    stamps = pd.bdate_range("2021-01-01", "2021-12-10", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "equity": np.linspace(100, 120, len(stamps))})
    returns = monthly_returns(frame)
    assert returns.index[-1].month == 11


def test_a_monthly_record_dated_on_the_first_keeps_its_last_month() -> None:
    stamps = pd.date_range("2020-01-01", periods=30, freq="MS", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "equity": 1.01 ** np.arange(30)})
    assert len(monthly_returns(frame)) == 29


def test_the_binomial_cdf_matches_the_sum_of_the_terms() -> None:
    from math import comb

    n, p = 20, 0.3
    for k in (0, 3, 6, 20):
        expected = sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))
        assert _binomial_cdf(k, n, p) == pytest.approx(expected)


def test_the_bin_share_is_a_third_for_a_flat_curve() -> None:
    assert _bin_share(0.0, 1e6, 1.0) == pytest.approx(1 / 3, abs=1e-6)


def test_steady_honest_funds_rarely_show_missing_small_losses() -> None:
    """Normal months with a high mean: the old neighbour-average test fired
    about 5.7 % of the time at 240 months; the finding is meant for 1 %."""
    rng = np.random.default_rng(7)
    fired = 0
    runs = 400
    for _ in range(runs):
        review = fund_review(_monthly(rng.normal(0.03, 0.02, 240), "1990-12-31"), 12.0)
        fired += "few_small_losses" in review["findings"]
    assert fired / runs <= 0.02
