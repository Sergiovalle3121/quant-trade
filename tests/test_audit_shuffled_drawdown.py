"""The uploaded maximum drawdown against the same returns in random order."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import analytics
from quant_trade.audit.analytics import SHUFFLE_TAIL, shuffled_drawdown
from quant_trade.audit.engine import _risk


def test_the_same_seed_gives_the_same_answer() -> None:
    returns = np.random.default_rng(1).normal(0.0005, 0.01, 400)
    assert shuffled_drawdown(returns) == shuffled_drawdown(returns)


def test_the_uploaded_fall_counts_a_loss_on_the_first_period() -> None:
    returns = np.r_[-0.2, np.full(60, 0.01), np.tile([0.01, -0.005], 20)]
    out = shuffled_drawdown(returns)
    assert out["observed"]["value"] == pytest.approx(-0.2)


def test_alternating_small_losses_read_shallower_than_random_orders() -> None:
    # Every loss is followed by a gain: no losing streak can form.
    out = shuffled_drawdown(np.tile([0.01, -0.009], 250))
    assert out["position"] == "SHALLOWER"
    assert out["share_at_most_as_deep"]["value"] <= SHUFFLE_TAIL


def test_losses_in_one_block_read_deeper_than_random_orders() -> None:
    returns = np.r_[np.full(100, 0.004), np.full(100, -0.005), np.full(300, 0.004)]
    out = shuffled_drawdown(returns)
    assert out["position"] == "DEEPER"
    assert out["observed"]["value"] < out["shuffled"]["p95"]["value"]


def test_shuffles_keep_every_return_so_the_final_result_is_unchanged() -> None:
    returns = np.random.default_rng(3).normal(0.0, 0.01, 300)
    out = shuffled_drawdown(returns)
    shuffled = out["shuffled"]
    assert shuffled["p95"]["value"] <= shuffled["p50"]["value"] <= shuffled["p5"]["value"] <= 0


def test_independent_returns_seldom_read_as_unusual() -> None:
    unusual = 0
    for seed in range(120):
        returns = np.random.default_rng(seed).normal(0.0003, 0.01, 250)
        out = shuffled_drawdown(returns, samples=300, seed=seed)
        unusual += out["position"] != "TYPICAL"
    # Two tails of 5 %: about 10 % by chance, far from every file.
    assert unusual / 120 < 0.2


@pytest.mark.parametrize(
    ("returns", "reason"),
    [
        (np.full(10, 0.01), "needs at least"),
        (np.random.default_rng(4).uniform(0.001, 0.01, 200), "no losing period"),
    ],
)
def test_short_or_lossless_histories_are_not_measured(returns: np.ndarray, reason: str) -> None:
    out = shuffled_drawdown(returns)
    assert out["status"] == "NOT_MEASURED"
    assert out["reason"].startswith(reason)


def test_a_minute_curve_is_compounded_so_the_work_stays_bounded() -> None:
    returns = np.random.default_rng(5).normal(0.0, 0.001, 200_000)
    out = shuffled_drawdown(returns)
    method = out["method"]
    blocks = 200_000 // method["periods_per_step"]
    assert blocks <= analytics.MAX_RISK_PATH_PERIODS
    assert method["samples"] * blocks <= max(
        analytics.MAX_RESAMPLED_CELLS, analytics.SHUFFLE_MIN_SAMPLES * blocks
    )


def test_the_audit_carries_the_comparison_beside_the_risk_section() -> None:
    returns = np.random.default_rng(6).normal(0.0005, 0.01, 300)
    risk = _risk(pd.Series(returns), 252.0, samples=200, seed=1)
    assert risk["versus_shuffle"]["status"] == "MEASURED"
    assert risk["versus_shuffle"]["position"] in {"SHALLOWER", "TYPICAL", "DEEPER"}
