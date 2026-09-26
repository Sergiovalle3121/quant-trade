"""The math review of 2026-09-25: each test pins one figure that was wrong.

Every case is small enough to check by hand; the expected value is computed
independently of the code under test.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, positive_drift

from quant_trade.audit.engine import autocorrelation_adjusted_sharpe, run_audit
from quant_trade.audit.redflags import annualised_sharpe
from quant_trade.audit.ride import ride_review
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.robustness import subperiod_analysis


def test_yearly_returns_include_the_move_across_the_turn_of_the_year() -> None:
    stamps = pd.date_range("2020-12-31", periods=37, freq="ME", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "equity": 100.0 * 1.01 ** np.arange(37)})
    table = subperiod_analysis(frame)
    by_year = dict(zip(table["year"], table["return"], strict=True))
    for year in (2021, 2022, 2023):
        assert by_year[year] == pytest.approx(1.01**12 - 1)
    chained = float(np.prod([1 + value for value in table["return"]]) - 1)
    assert chained == pytest.approx(frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1)


def test_a_fall_at_the_turn_of_the_year_shows_in_the_new_year() -> None:
    stamps = pd.to_datetime(["2021-12-30", "2021-12-31", "2022-01-03", "2022-01-04"], utc=True)
    frame = pd.DataFrame({"timestamp": stamps, "equity": [100.0, 100.0, 80.0, 81.0]})
    table = subperiod_analysis(frame).set_index("year")
    assert table.loc[2022, "return"] == pytest.approx(0.81 - 1)
    assert table.loc[2022, "max_drawdown"] == pytest.approx(-0.2)


def test_the_out_of_sample_side_counts_the_move_onto_its_first_row() -> None:
    n = 80
    returns = np.full(n, 0.001)
    returns[40] = -0.10  # the first out-of-sample day
    equity = 100.0 * np.cumprod(1.0 + np.concatenate([[0.0], returns]))
    stamps = business_days(n + 1)
    frame = pd.DataFrame({"timestamp": stamps, "equity": equity})
    oos_start = str(stamps[41].date())
    result = run_audit(build_inputs(csv_bytes(frame), DeclaredMetadata(oos_start=oos_start)))
    holdout = result.holdout
    assert holdout["status"] == "MEASURED"
    oos = holdout["out_of_sample"]
    expected = float(equity[-1] / equity[40] - 1)
    assert oos["total_return"]["value"] == pytest.approx(expected)
    assert oos["total_return"]["value"] < 0
    in_sample = holdout["in_sample"]["observations"]["value"]
    assert in_sample + oos["observations"]["value"] == n


def test_the_headline_volatility_is_the_one_the_sharpe_divides_by() -> None:
    frame = positive_drift(300)
    result = run_audit(build_inputs(csv_bytes(frame), DeclaredMetadata()))
    returns = frame["equity"].pct_change().dropna()
    ppy = periods_per_year(frame["timestamp"])
    perf = result.performance
    assert perf["volatility"]["value"] == pytest.approx(returns.std(ddof=1) * np.sqrt(ppy))
    assert perf["sharpe"]["value"] == pytest.approx(
        returns.mean() * ppy / perf["volatility"]["value"]
    )


def test_the_benchmark_section_prints_the_headline_sharpe() -> None:
    strategy = positive_drift(300, seed=3)
    bench = positive_drift(300, mean=0.0003, seed=8)
    inputs = build_inputs(csv_bytes(strategy), DeclaredMetadata(), benchmark_bytes=csv_bytes(bench))
    result = run_audit(inputs)
    assert result.benchmark["status"] == "MEASURED"
    assert result.benchmark["strategy_sharpe"]["value"] == pytest.approx(
        result.performance["sharpe"]["value"]
    )


def test_a_curve_that_never_loses_has_no_sortino() -> None:
    rng = np.random.default_rng(1)
    equity = 100.0 * np.cumprod(1.0 + rng.uniform(0.0001, 0.002, 300))
    frame = pd.DataFrame({"timestamp": business_days(300), "equity": equity})
    result = run_audit(build_inputs(csv_bytes(frame), DeclaredMetadata()))
    assert result.performance["sortino"]["evidence"] == "NOT_MEASURED"


def test_the_deepest_fall_starts_at_the_last_day_at_the_high() -> None:
    stamps = pd.date_range("2020-01-01", periods=40, freq="D", tz="UTC")
    equity = [100.0] * 30 + [90.0] + [95.0] * 9
    review = ride_review(pd.DataFrame({"timestamp": stamps, "equity": equity}))
    assert review["fall_days"]["value"] == 1
    assert review["deepest_from"] == "2020-01-30"


def test_a_curve_that_only_rises_spends_no_time_under_water() -> None:
    stamps = pd.date_range("2020-01-03", periods=30, freq="W-FRI", tz="UTC")
    equity = 100.0 * 1.01 ** np.arange(30)
    review = ride_review(pd.DataFrame({"timestamp": stamps, "equity": equity}))
    assert review["longest_under"]["value"] == 0


def test_weekends_between_rising_days_are_not_under_water() -> None:
    stamps = business_days(60)
    equity = 100.0 * 1.001 ** np.arange(60)
    equity[30] = equity[29] * 0.99  # one dip, regained two rows later
    review = ride_review(pd.DataFrame({"timestamp": stamps, "equity": equity}))
    regained = (stamps[31] - stamps[29]).days
    assert review["longest_under"]["value"] == regained


def test_the_headline_sharpe_uses_the_sample_deviation() -> None:
    returns = pd.Series([0.01, -0.005, 0.02, 0.0, 0.015])
    expected = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    assert annualised_sharpe(returns, 252) == pytest.approx(expected)


def _ar1(returns: np.ndarray, phi: float) -> np.ndarray:
    out = np.zeros_like(returns)
    for index, value in enumerate(returns):
        out[index] = (phi * out[index - 1] if index else 0.0) + value
    return out * (1 - phi)


def test_independent_returns_keep_their_sharpe_after_lo() -> None:
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0005, 0.01, 3000))
    adjusted = autocorrelation_adjusted_sharpe(returns, 252)
    assert adjusted["sharpe"]["value"] == pytest.approx(annualised_sharpe(returns, 252), rel=0.05)


def test_smoothed_returns_lose_the_inflation_after_lo() -> None:
    rng = np.random.default_rng(0)
    raw = rng.normal(0.0005, 0.01, 3000)
    smoothed = pd.Series(_ar1(raw, 0.5))
    plain = annualised_sharpe(smoothed, 252)
    adjusted = autocorrelation_adjusted_sharpe(smoothed, 252)
    assert adjusted["lag1"]["value"] == pytest.approx(0.5, abs=0.05)
    # Smoothing inflates the plain figure by about sqrt((1 + phi) / (1 - phi)) = 1.73.
    assert plain / adjusted["sharpe"]["value"] == pytest.approx(math.sqrt(3.0), rel=0.15)
    assert adjusted["sharpe"]["value"] == pytest.approx(
        annualised_sharpe(pd.Series(raw), 252), rel=0.15
    )


def test_a_short_series_has_no_lo_sharpe() -> None:
    adjusted = autocorrelation_adjusted_sharpe(pd.Series(np.linspace(-0.01, 0.01, 30)), 252)
    assert adjusted["sharpe"]["evidence"] == "NOT_MEASURED"


def test_the_audit_carries_the_lo_sharpe() -> None:
    result = run_audit(build_inputs(csv_bytes(positive_drift(300)), DeclaredMetadata()))
    assert result.significance["autocorrelation_adjusted"]["sharpe"]["evidence"] == "MEASURED"
