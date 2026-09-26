"""Jensen's alpha with a Newey-West t-statistic, and the 2 and 20 fee row."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.alpha import jensen_alpha, newey_west_lags
from quant_trade.audit.fund import _two_and_twenty, fee_drag


def test_alpha_and_beta_match_least_squares() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(0.0004, 0.01, 500)
    y = 0.0002 + 1.2 * x + rng.normal(0, 0.004, 500)
    out = jensen_alpha(y, x, 252.0)
    slope, intercept = np.polyfit(x, y, 1)
    assert out["alpha"]["value"] == pytest.approx(intercept * 252)
    assert out["beta"]["value"] == pytest.approx(slope)
    assert out["r_squared"]["value"] == pytest.approx(np.corrcoef(x, y)[0, 1] ** 2)
    assert out["lags"] == newey_west_lags(500) == 5


def test_the_t_stat_is_near_the_plain_one_for_independent_errors() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(0.0, 0.01, 2000)
    y = 0.0005 + 0.8 * x + rng.normal(0, 0.005, 2000)
    out = jensen_alpha(y, x, 252.0)
    resid = y - np.polyval(np.polyfit(x, y, 1), x)
    design = np.column_stack([np.ones_like(x), x])
    plain_se = np.sqrt((resid @ resid) / (len(x) - 2) * np.linalg.inv(design.T @ design)[0, 0])
    assert out["alpha_t_stat"]["value"] == pytest.approx(0.0005 / plain_se, rel=0.3)


def test_no_alpha_is_rarely_called_significant() -> None:
    rng = np.random.default_rng(2)
    big = 0
    for _ in range(300):
        x = rng.normal(0.0005, 0.01, 250)
        y = 1.0 * x + rng.normal(0, 0.005, 250)
        big += abs(jensen_alpha(y, x, 252.0)["alpha_t_stat"]["value"]) > 1.96
    assert big / 300 <= 0.09


def test_short_overlaps_have_no_alpha() -> None:
    assert jensen_alpha(np.zeros(10), np.ones(10), 12.0)["status"] == "NOT_MEASURED"


def test_two_and_twenty_by_hand() -> None:
    # 24 months of +1 %: each year gross 12.68 %, 2 % management month by month,
    # 20 % of the gain over the previous high at each year end.
    r = np.full(24, 0.01)
    monthly = 1.02 ** (1 / 12) - 1
    value = high = 1.0
    for _year in range(2):
        value *= (1.01 / (1 + monthly)) ** 12
        value -= 0.2 * (value - high)
        high = value
    assert _two_and_twenty(r) == pytest.approx(value)


def test_no_performance_fee_below_the_high_water_mark() -> None:
    r = np.concatenate([np.full(12, -0.02), np.full(12, 0.01)])
    monthly = 1.02 ** (1 / 12) - 1
    assert _two_and_twenty(r) == pytest.approx(np.prod((1 + r) / (1 + monthly)))


def test_the_fee_table_carries_the_two_and_twenty_row() -> None:
    r = pd.Series(np.full(36, 0.01))
    out = fee_drag(r)
    row = out["two_and_twenty"]
    assert row["management"] == 0.02 and row["performance"] == 0.2
    two_only = next(item for item in out["rows"] if item["rate"] == 0.02)
    assert row["cagr"]["value"] < two_only["cagr"]["value"]


def test_the_benchmark_section_carries_the_alpha() -> None:
    from audit_fixtures import csv_bytes, positive_drift

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        csv_bytes(positive_drift(300, seed=3)),
        DeclaredMetadata(),
        benchmark_bytes=csv_bytes(positive_drift(300, mean=0.0003, seed=8)),
    )
    jensen = run_audit(inputs).benchmark["jensen"]
    assert jensen["status"] == "MEASURED"
    assert jensen["alpha"]["evidence"] == "MEASURED"


def test_a_level_at_zero_does_not_poison_the_alpha() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(0.0, 0.01, 60)
    y = 0.5 * x + rng.normal(0, 0.002, 60)
    y[10] = np.inf
    out = jensen_alpha(y, x, 252.0)
    assert out["status"] == "MEASURED"
    assert np.isfinite(out["alpha"]["value"]) and out["periods"] == 59


def test_the_performance_fee_is_taken_in_december() -> None:
    # A record starting in July: fees fall in December, six months in, then
    # every twelve months, and at the last month (itself a December here).
    stamps = pd.date_range("2020-07-31", periods=30, freq="ME")
    r = pd.Series(np.full(30, 0.01), index=stamps)
    monthly = 1.02 ** (1 / 12) - 1
    step = 1.01 / (1 + monthly)
    value = high = 1.0
    for months in (6, 12, 12):
        value *= step**months
        value -= 0.2 * (value - high)
        high = value
    growth = fee_drag(r)["two_and_twenty"]["growth"]["value"]
    assert growth == pytest.approx(value - 1.0)
