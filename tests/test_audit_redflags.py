"""One positive and one negative case per red-flag code."""

from __future__ import annotations

import numpy as np
import pandas as pd
from audit_fixtures import business_days, csv_bytes, positive_drift, spiked, stale_marks

from quant_trade.audit import redflags
from quant_trade.audit.schema import DeclaredMetadata, parse_equity_csv, parse_trades_csv
from quant_trade.data.quality.report import _detect_spikes

DECLARED = DeclaredMetadata(cost_bps_per_side=5.0)


def _codes(frame: pd.DataFrame, *, declared: DeclaredMetadata = DECLARED, **kw) -> dict[str, str]:
    series = parse_equity_csv(csv_bytes(frame))
    flags = redflags.scan(series, periods_per_year=252.0, declared=declared, **kw)
    return {flag.code: flag.severity for flag in flags}


def test_clean_series_has_no_flags() -> None:
    assert _codes(positive_drift(600)) == {}


def test_too_few_observations_fail_and_warn() -> None:
    assert _codes(positive_drift(20))["TOO_FEW_OBSERVATIONS"] == "FAIL"
    assert _codes(positive_drift(60))["TOO_FEW_OBSERVATIONS"] == "WARN"


def test_non_positive_equity() -> None:
    # An upload with such a row is refused before the audit
    # (``equity_not_positive``); the flag still guards a series built directly.
    series = parse_equity_csv(csv_bytes(positive_drift(200)))
    series.frame.loc[50, "equity"] = 0.0
    flags = redflags.scan(series, periods_per_year=252.0, declared=DECLARED)
    assert {flag.code: flag.severity for flag in flags}["NON_POSITIVE_EQUITY"] == "FAIL"


def test_duplicates_and_order() -> None:
    frame = positive_drift(200)
    dup = pd.concat([frame, frame.iloc[[10]]], ignore_index=True)
    codes = _codes(dup)
    assert codes["DUPLICATE_TIMESTAMPS"] == "FAIL"
    assert codes["NON_MONOTONIC_TIMESTAMPS"] == "WARN"


def test_unparseable_rows_warn_then_fail() -> None:
    frame = positive_drift(200).astype({"equity": object})
    frame.loc[3, "equity"] = "x"
    assert _codes(frame)["UNPARSEABLE_ROWS"] == "WARN"
    frame.loc[4:20, "equity"] = "x"
    assert _codes(frame)["UNPARSEABLE_ROWS"] == "FAIL"


def test_zero_variance() -> None:
    frame = pd.DataFrame({"timestamp": business_days(200), "equity": 100.0})
    assert _codes(frame)["ZERO_VARIANCE"] == "FAIL"


def test_stale_marks_ignores_zero_returns() -> None:
    assert _codes(stale_marks(run=25))["STALE_MARKS"] == "FAIL"
    assert _codes(stale_marks(run=7))["STALE_MARKS"] == "WARN"
    frame = positive_drift(300)
    frame.loc[100:160, "equity"] = frame.loc[100, "equity"]  # flat in cash: zero returns
    assert "STALE_MARKS" not in _codes(frame)
    assert redflags.longest_stale_run(pd.Series([0.0, 0.0, 0.0, 0.01, 0.01])) == 2


def test_mad_spikes_matches_the_quality_report_port() -> None:
    frame = spiked(spikes=5)
    codes = _codes(frame)
    assert codes["MAD_SPIKES"] == "FAIL"
    assert _codes(spiked(spikes=1))["MAD_SPIKES"] == "WARN"
    closes = frame.rename(columns={"equity": "close"}).assign(symbol="X")
    returns = frame["equity"].pct_change().dropna()
    assert redflags.detect_mad_spikes(returns) == _detect_spikes(closes)


def test_implausible_sharpe_thresholds_depend_on_frequency() -> None:
    rng = np.random.default_rng(1)
    daily = pd.DataFrame(
        {
            "timestamp": business_days(400),
            "equity": 100 * np.cumprod(1 + rng.normal(0.006, 0.01, 400)),
        }
    )
    assert _codes(daily)["IMPLAUSIBLE_SHARPE"] == "FAIL"
    series = parse_equity_csv(csv_bytes(daily))
    intraday = {
        f.code: f.severity
        for f in redflags.scan(series, periods_per_year=6000.0, declared=DECLARED)
    }
    # the same per-period Sharpe annualises much higher intraday, yet the bar is higher too
    assert intraday["IMPLAUSIBLE_SHARPE"] == "FAIL"
    milder = daily.copy()
    milder["equity"] = 100 * np.cumprod(1 + rng.normal(0.0025, 0.01, 400))
    assert _codes(milder)["IMPLAUSIBLE_SHARPE"] == "WARN"


def test_large_gaps() -> None:
    frame = positive_drift(200)
    frame = pd.concat([frame.iloc[:100], frame.iloc[150:]], ignore_index=True)
    assert _codes(frame)["LARGE_GAPS"] == "WARN"


def test_zero_declared_costs_and_trials_below_variants() -> None:
    codes = _codes(positive_drift(300), declared=DeclaredMetadata(trials=2), variants_columns=10)
    assert codes["ZERO_DECLARED_COSTS"] == "WARN"
    assert codes["TRIALS_BELOW_VARIANTS"] == "WARN"


def test_trade_flags() -> None:
    from audit_fixtures import trades_frame

    frame = trades_frame(10)
    frame["pnl"] = 0.0  # client claims zero pnl on every trade
    frame.loc[0, "entry_price"] = -5
    parsed = parse_trades_csv(csv_bytes(frame))
    from quant_trade.audit.costs import gross_pnls

    recomputed = gross_pnls(parsed.trades, parsed.sides)
    codes = _codes(positive_drift(300), trades=parsed, recomputed_pnl=recomputed)
    assert codes["INVALID_TRADE_ROWS"] == "WARN"
    assert codes["TRADE_PNL_MISMATCH"] == "WARN"
    honest = parse_trades_csv(csv_bytes(trades_frame(10)))
    codes = _codes(
        positive_drift(300), trades=honest, recomputed_pnl=gross_pnls(honest.trades, honest.sides)
    )
    assert "TRADE_PNL_MISMATCH" not in codes
    assert "INVALID_TRADE_ROWS" not in codes
