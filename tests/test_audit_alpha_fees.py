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


def test_misaligned_series_are_not_measured_never_an_error() -> None:
    out = jensen_alpha(np.zeros(30), np.ones(31), 252.0)
    assert out["status"] == "NOT_MEASURED"
    from quant_trade.audit.i18n import spanish

    assert spanish(out["reason"])


def test_cash_subtracted_removes_the_alpha_a_low_beta_strategy_gets_from_cash() -> None:
    rng = np.random.default_rng(30)
    cash = np.full(60, 0.004)
    index = rng.normal(0.008, 0.045, 60)
    # Mostly bills: 0.1 of the index's return over cash, and no skill at all.
    fund = cash + 0.1 * (index - cash) + rng.normal(0, 0.001, 60)
    plain = jensen_alpha(fund, index, 12.0)
    over_cash = jensen_alpha(fund, index, 12.0, cash)
    assert plain["alpha"]["value"] == pytest.approx(0.9 * 0.004 * 12, abs=0.004)
    assert abs(over_cash["alpha"]["value"]) < 0.004
    assert over_cash["cash_subtracted"] is True and plain["cash_subtracted"] is False
    from quant_trade.audit.alpha import CASH_NOTE, NOTE

    assert over_cash["alpha"]["note"] == CASH_NOTE and plain["alpha"]["note"] == NOTE


def test_cash_of_another_length_is_not_aligned() -> None:
    out = jensen_alpha(np.zeros(30), np.linspace(-0.01, 0.01, 30), 12.0, np.zeros(29))
    assert out["status"] == "NOT_MEASURED"


def test_span_cash_leaves_the_cash_rate_sharpe_as_it_was() -> None:
    from quant_trade.audit.cashrate import excess_sharpe

    rng = np.random.default_rng(0)
    days = pd.bdate_range("2021-03-01", periods=300, tz="UTC") + pd.Timedelta(hours=21)
    frame = pd.DataFrame(
        {"timestamp": days, "equity": 10000 * np.cumprod(1 + rng.normal(0.0004, 0.01, 300))}
    )
    rates = pd.Series(np.linspace(0.05, 5.2, 320), index=pd.bdate_range("2021-02-01", periods=320))
    out = excess_sharpe(frame, rates, 252.0)
    # Values from the implementation before span_cash was split out.
    assert out["sharpe_excess"]["value"] == -0.1114406105769542
    assert out["mean_rate"]["value"] == 0.028801429573778403
    gap = rates.drop(rates.index[100:120])
    assert excess_sharpe(frame, gap, 252.0)["status"] == "NOT_MEASURED"


def test_span_cash_matches_the_bills_yield_over_each_span() -> None:
    from quant_trade.audit.cashrate import annual_yield, span_cash

    stamps = pd.Series(pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-06"], utc=True))
    rates = pd.Series(
        [5.0, 5.0, 5.0], index=pd.to_datetime(["2022-12-30", "2023-01-02", "2023-01-03"])
    )
    cash = span_cash(stamps, rates)
    yearly = float(annual_yield(np.array([0.05]))[0])
    assert cash == pytest.approx([(1 + yearly) ** (1 / 365) - 1, (1 + yearly) ** (3 / 365) - 1])
    assert span_cash(stamps, None) is None
    assert span_cash(stamps, rates.iloc[:0]) is None


def test_the_benchmark_section_subtracts_cash_when_rates_cover_it() -> None:
    from audit_fixtures import csv_bytes, positive_drift

    from quant_trade.audit.engine import _benchmark
    from quant_trade.audit.schema import parse_equity_csv

    strategy = parse_equity_csv(csv_bytes(positive_drift(n=400, seed=3)), what="equity")
    bench = parse_equity_csv(csv_bytes(positive_drift(n=400, seed=4)), what="benchmark")
    stamps = pd.DatetimeIndex(strategy.frame["timestamp"])
    rates = pd.Series(
        4.0,
        index=pd.date_range(
            stamps.min().tz_localize(None) - pd.Timedelta(days=15),
            stamps.max().tz_localize(None),
            freq="D",
        ),
    )
    with_cash, _, _ = _benchmark(strategy, bench, rates)
    without, _, _ = _benchmark(strategy, bench, None)
    assert with_cash["jensen"]["cash_subtracted"] is True
    assert without["jensen"]["cash_subtracted"] is False
    assert with_cash["jensen"]["alpha"]["value"] != without["jensen"]["alpha"]["value"]
