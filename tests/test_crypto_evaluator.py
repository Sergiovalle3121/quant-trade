"""Tests for the annual-rebalance evaluator.

The delisting assumption is the study's most consequential modelling choice, so
it gets the most tests: a position whose series ends must not silently survive,
must not silently vanish, and must produce visibly different results at the two
declared extremes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quant_trade.research.crypto_evaluator import evaluate

MID_CAP = 500e6


def _panel(prices: dict[str, dict[str, float]], market_cap: float = MID_CAP) -> pd.DataFrame:
    rows = []
    for symbol, series in prices.items():
        for day, price in series.items():
            rows.append(
                {
                    "timestamp": pd.Timestamp(day, tz="UTC"),
                    "symbol": symbol,
                    "close": price,
                    "market_cap_usd": market_cap,
                }
            )
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _weights(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"timestamp": pd.Timestamp(d, tz="UTC"), "symbol": s, "target_weight": w}
            for d, s, w in rows
        ]
    )


DAYS = ["2020-01-01", "2020-01-02", "2020-01-03"]


def test_a_flat_hold_tracks_the_price() -> None:
    panel = _panel({"A": dict(zip(DAYS, [10.0, 11.0, 12.0], strict=True))})
    result = evaluate(panel, _weights([(DAYS[0], "A", 1.0)]), initial_capital_usd=1_000.0)
    # entry cost is paid once; after that the position simply tracks the price
    assert result.equity.iloc[-1] / result.equity.iloc[1] == pytest.approx(12.0 / 11.0)
    assert len(result.rebalances) == 1


def test_costs_are_charged_and_reduce_equity() -> None:
    panel = _panel({"A": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True))})
    result = evaluate(panel, _weights([(DAYS[0], "A", 1.0)]), initial_capital_usd=1_000.0)
    assert result.total_cost_usd > 0
    assert result.equity.iloc[-1] < 1_000.0
    assert result.equity.iloc[-1] == pytest.approx(1_000.0 - result.total_cost_usd)


def test_delisting_recovery_extremes_bracket_the_result() -> None:
    """The same panel, the same weights, two declared assumptions."""
    panel = _panel(
        {
            "A": {DAYS[0]: 10.0, DAYS[1]: 10.0},  # series ends after day 2
            "B": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True)),
        }
    )
    weights = _weights([(DAYS[0], "A", 0.5), (DAYS[0], "B", 0.5)])
    full = evaluate(panel, weights, initial_capital_usd=1_000.0, delisting_recovery=1.0)
    zero = evaluate(panel, weights, initial_capital_usd=1_000.0, delisting_recovery=0.0)

    assert full.delisted_positions == 1
    assert zero.delisted_positions == 1
    assert zero.equity.iloc[-1] < full.equity.iloc[-1]
    assert zero.delisting_losses_usd > 0
    assert full.delisting_losses_usd == pytest.approx(0.0)
    # the whole A position is what separates them
    assert full.equity.iloc[-1] - zero.equity.iloc[-1] == pytest.approx(
        zero.delisting_losses_usd
    )


def test_a_dead_position_is_never_carried_at_its_last_price() -> None:
    """The forward-fill failure the anti-bias plan names explicitly."""
    panel = _panel(
        {
            "A": {DAYS[0]: 10.0},  # dies immediately
            "B": dict(zip(DAYS, [10.0, 20.0, 40.0], strict=True)),
        }
    )
    weights = _weights([(DAYS[0], "A", 0.5), (DAYS[0], "B", 0.5)])
    result = evaluate(panel, weights, initial_capital_usd=1_000.0, delisting_recovery=0.0)
    # B quadrupled; if A had been forward-filled the portfolio would be worth
    # ~2.5x. With A written off it is ~2x of the surviving half.
    assert result.equity.iloc[-1] < 2_100.0
    assert result.delisted_positions == 1


def test_turnover_accumulates_across_rebalances() -> None:
    panel = _panel(
        {
            "A": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True)),
            "B": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True)),
        }
    )
    weights = _weights(
        [(DAYS[0], "A", 1.0), (DAYS[1], "B", 1.0), (DAYS[2], "A", 1.0)]
    )
    result = evaluate(panel, weights, initial_capital_usd=1_000.0)
    assert len(result.rebalances) == 3
    # entry (0.5) + full swap (1.0) + full swap (1.0)
    assert result.total_turnover == pytest.approx(2.5, rel=0.01)


def test_capacity_and_calibration_refusals_are_surfaced_separately() -> None:
    """Both refusals must reach the record, and they are not the same event.

    Micro capacity is $1,000 (the largest size every sampled micro book
    filled) and the calibrated domain ends at $10,000. A $4,000 order is a
    capacity cap; a $50,000 order is off the measured map entirely.
    """
    panel = _panel(
        {"A": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True))}, market_cap=5e6
    )
    capped = evaluate(
        panel, _weights([(DAYS[0], "A", 1.0)]), initial_capital_usd=4_000.0
    )
    assert capped.rebalances[0].capped_legs == 1
    assert capped.rebalances[0].unpriceable_legs == 0
    assert capped.summary()["capped_legs"] == 1

    beyond = evaluate(
        panel, _weights([(DAYS[0], "A", 1.0)]), initial_capital_usd=50_000.0
    )
    assert beyond.rebalances[0].unpriceable_legs == 1
    assert beyond.rebalances[0].capped_legs == 0
    assert beyond.rebalances[0].names_held == 0  # nothing was bought


def test_invalid_recovery_is_refused() -> None:
    panel = _panel({"A": dict(zip(DAYS, [10.0, 10.0, 10.0], strict=True))})
    with pytest.raises(ValueError, match="delisting_recovery"):
        evaluate(panel, _weights([(DAYS[0], "A", 1.0)]), delisting_recovery=1.5)


def test_summary_reports_annual_turnover_against_the_gate() -> None:
    days = pd.date_range("2020-01-01", periods=731, freq="D", tz="UTC")
    panel = _panel({"A": {str(d.date()): 10.0 for d in days}})
    weights = _weights([(str(days[0].date()), "A", 1.0)])
    result = evaluate(panel, weights, initial_capital_usd=1_000.0)
    summary = result.summary()
    assert summary["years"] == pytest.approx(2.0, abs=0.01)
    assert summary["annual_turnover"] == pytest.approx(result.total_turnover / 2.0, rel=0.01)
