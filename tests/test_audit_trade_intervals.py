"""95 % ranges for the win rate, the average per trade and the profit factor."""

from __future__ import annotations

import math

import numpy as np
import pytest

from quant_trade.audit.analytics import _t_quantile, trade_intervals


def _ranges(pnl: np.ndarray) -> dict:
    return trade_intervals(pnl, wins=int((pnl > 0).sum()), per_trade=pnl, expectancy=pnl.mean())


@pytest.mark.parametrize(("dof", "exact"), [(5, 2.5706), (9, 2.2622), (30, 2.0423)])
def test_the_t_quantile_matches_the_table(dof: int, exact: float) -> None:
    assert _t_quantile(0.975, dof) == pytest.approx(exact, abs=5e-4)


def test_the_ranges_hold_the_figures_they_describe() -> None:
    rng = np.random.default_rng(0)
    pnl = rng.normal(5.0, 50.0, 200)
    out = _ranges(pnl)
    assert out["status"] == "MEASURED"
    win = (pnl > 0).mean()
    assert out["win_rate"]["low"]["value"] < win < out["win_rate"]["high"]["value"]
    assert out["expectancy"]["low"]["value"] < pnl.mean() < out["expectancy"]["high"]["value"]
    pf = pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()
    assert out["profit_factor"]["low"]["value"] < pf < out["profit_factor"]["high"]["value"]
    half = out["expectancy"]["high"]["value"] - pnl.mean()
    assert half == pytest.approx(_t_quantile(0.975, 199) * pnl.std(ddof=1) / math.sqrt(200))


def test_the_ranges_cover_the_true_value_about_95_percent_of_the_time() -> None:
    rng = np.random.default_rng(1)
    true_mean, true_win = 2.0, 0.5 + 0.5 * math.erf(2.0 / 20.0 / math.sqrt(2.0))
    covered_mean = covered_win = 0
    runs = 400
    for _ in range(runs):
        pnl = rng.normal(true_mean, 20.0, 60)
        out = _ranges(pnl)
        covered_mean += (
            out["expectancy"]["low"]["value"] <= true_mean <= out["expectancy"]["high"]["value"]
        )
        covered_win += (
            out["win_rate"]["low"]["value"] <= true_win <= out["win_rate"]["high"]["value"]
        )
    assert 0.92 <= covered_mean / runs <= 0.98
    assert 0.91 <= covered_win / runs <= 0.99


def test_few_trades_have_no_range() -> None:
    out = _ranges(np.array([1.0, -1.0, 2.0]))
    assert out["status"] == "NOT_MEASURED"


def test_no_losing_trade_leaves_the_profit_factor_range_unmeasured() -> None:
    out = _ranges(np.arange(1.0, 21.0))
    assert out["profit_factor"]["low"]["evidence"] == "NOT_MEASURED"


def test_the_same_trades_give_the_same_ranges() -> None:
    pnl = np.random.default_rng(2).normal(1.0, 10.0, 80)
    assert _ranges(pnl) == _ranges(pnl.copy())


def test_a_range_that_reaches_infinity_is_unbounded_not_nan() -> None:
    # One loss in ten: about a third of the resamples have no loss at all.
    pnl = np.array([5.0, 3.0, 4.0, 2.0, 6.0, 1.0, 3.0, 2.0, 4.0, -3.0])
    pf = _ranges(pnl)["profit_factor"]
    assert pf["high"]["evidence"] == "NOT_MEASURED"
    assert math.isfinite(pf["low"]["value"])
