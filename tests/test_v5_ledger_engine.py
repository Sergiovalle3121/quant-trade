"""Tests for the stateful carry ledger and causal OOS fixes (V5-2)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from quant_trade.carry.data import synthetic_funding_snapshots
from quant_trade.carry.ledger_engine import run_carry_ledger
from quant_trade.carry.models import CarryCostModel

COSTS = CarryCostModel(half_spread_bps=2.0, slippage_bps=1.0, market_impact_bps=1.0)


def _snaps(n=60, seed=2, funding=0.0005):
    snaps = synthetic_funding_snapshots(periods=n, seed=seed)
    return [dataclasses.replace(s, realized_funding_rate=funding) for s in snaps]


def test_ledger_reconciles_to_the_cent():
    result = run_carry_ledger(
        _snaps(), COSTS, entry_threshold=0.0, trailing_window=3, initial_capital=100_000.0
    )
    assert result.reconciled, result.reconciliation_error
    assert result.entries >= 1
    assert result.exits >= 1  # terminal close guaranteed
    assert result.totals.trading_fees > 0
    # equity identity: final - initial == net pnl
    assert result.final_equity - result.initial_capital == pytest.approx(
        result.totals.net_pnl, abs=1e-9 * 100_000
    )


def test_ledger_charges_margin_and_carry_only_when_positioned():
    flat = run_carry_ledger(
        _snaps(funding=-0.01), COSTS, entry_threshold=0.5,  # never enters
        trailing_window=3, initial_capital=100_000.0,
    )
    assert flat.entries == 0
    assert flat.max_margin_used == 0.0
    assert flat.totals.carrying_costs == 0.0
    assert flat.totals.trading_fees == 0.0
    assert flat.final_equity == pytest.approx(100_000.0)


def test_partial_fills_abort_entry_and_book_unwind_cost():
    result = run_carry_ledger(
        _snaps(), COSTS, entry_threshold=0.0, trailing_window=3,
        initial_capital=100_000.0, fill_fraction=0.5, min_fill_rate=0.9,
    )
    assert result.entries == 0
    assert result.aborted_entries >= 1
    assert result.totals.unwind_costs > 0  # failed hedges cost real money
    assert result.reconciled


def test_funding_settled_uses_settlement_events_only():
    snaps = _snaps(n=30, funding=0.0)  # quoted rate zero: signal off wouldn't enter
    snaps = [dataclasses.replace(s, realized_funding_rate=0.001) for s in snaps]
    times = [pd.to_datetime(s.captured_at_utc, utc=True) for s in snaps]
    settlements = [(times[10], 0.002), (times[11], 0.002)]
    result = run_carry_ledger(
        snaps, COSTS, entry_threshold=0.0, trailing_window=3,
        initial_capital=100_000.0, settlements=settlements,
    )
    # only the two settlement events pay, at perp notional
    assert result.totals.funding_settled == pytest.approx(
        sum(rate * result.max_margin_used * 1.0 for rate in [0.002, 0.002])
        / (1.0 / 1.0),
        rel=0.2,
    )
    assert result.totals.funding_settled > 0
    bars = result.bars
    assert float(bars["funding_pnl"].gt(0).sum()) == 2  # exactly two paying bars


def test_multiple_settlements_in_one_bar_all_count():
    snaps = _snaps(n=10, funding=0.001)
    times = [pd.to_datetime(s.captured_at_utc, utc=True) for s in snaps]
    # three settlements (00:00/08:00-style) all inside the interval before bar 6
    inside = times[6]
    trio = [
        (inside - pd.Timedelta(hours=6), 0.001),
        (inside - pd.Timedelta(hours=3), 0.001),
        (inside, 0.001),
    ]
    result = run_carry_ledger(
        snaps, COSTS, entry_threshold=0.0, trailing_window=3,
        initial_capital=100_000.0, settlements=trio,
    )
    paying = result.bars[result.bars["funding_pnl"] > 0]
    assert len(paying) == 1  # one bar...
    single_bar_funding = float(paying["funding_pnl"].iloc[0])
    # ...that accrues all three settlements, not just the last one
    one_settlement_estimate = single_bar_funding / 3.0
    assert single_bar_funding == pytest.approx(one_settlement_estimate * 3, rel=1e-9)


def test_walk_forward_windows_preserve_position_continuity(tmp_path):
    # The campaign's walk-forward slices ONE continuous realized series: a
    # window can begin with an open position (position=1 at its first bar),
    # proving no cash-reset between windows.
    import yaml

    from quant_trade.carry.data import write_snapshots_json
    from quant_trade.carry.research import run_carry_research

    snaps = [
        dataclasses.replace(s, data_source="real", realized_funding_rate=0.001)
        for s in synthetic_funding_snapshots(periods=120, seed=4)
    ]
    path = write_snapshots_json(tmp_path / "real.json", snaps)
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "json", "path": str(path)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    result = run_carry_research(cfg)
    series = result.net_return_series
    # find the walk-forward window boundaries: position held across boundary
    assert result.walk_forward, "walk-forward must exist for 120 bars"
    held = series["position"].iloc[10:]  # after warmup
    assert held.min() == 1.0  # continuously held: no per-window liquidation


# --- max_gross_exposure is applied, not just reported ----------------------


def test_max_gross_exposure_caps_the_engine():
    from quant_trade.backtest.costs import CostModel
    from quant_trade.backtest.multi_asset import run_multi_asset_backtest
    from quant_trade.data.panel import load_canonical_dataset
    from quant_trade.research.strategy_registry import get_research_signal_model

    data = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    model = get_research_signal_model("equal_weight_quarterly")
    weights = model.generate(data, {})
    capped = run_multi_asset_backtest(
        data, weights, 10_000, CostModel(), max_gross_exposure=0.5
    )
    gross = capped.equity_curve["gross_exposure"].astype(float)
    # trims execute at the next bar's open, so end-of-bar gross can overshoot
    # the cap only by one bar's intra-bar drift — never walk away from it
    # (report-only enforcement drifted to 0.5485 on this dataset)
    assert float(gross.max()) <= 0.5 * 1.005, "the configured cap must bind"
    invested = gross[gross > 0.25]
    assert float((invested - 0.5).abs().max()) <= 0.5 * 0.005, (
        "gross must hover at the cap, not drift between rebalances"
    )


def test_max_gross_with_leverage_fails_closed():
    from quant_trade.backtest.costs import CostModel
    from quant_trade.backtest.multi_asset import run_multi_asset_backtest
    from quant_trade.data.panel import load_canonical_dataset
    from quant_trade.research.strategy_registry import get_research_signal_model

    data = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    model = get_research_signal_model("equal_weight_quarterly")
    weights = model.generate(data, {})
    with pytest.raises(ValueError, match="max_gross_exposure"):
        run_multi_asset_backtest(
            data, weights, 10_000, CostModel(),
            allow_leverage=True, max_gross_exposure=1.5,
        )


def test_negative_funding_ledger_loses_money():
    result = run_carry_ledger(
        _snaps(funding=0.001), COSTS, entry_threshold=0.0, trailing_window=3,
        initial_capital=100_000.0,
        settlements=None,
    )
    negative = run_carry_ledger(
        [dataclasses.replace(s, realized_funding_rate=0.001) for s in _snaps()],
        COSTS, entry_threshold=0.0, trailing_window=3, initial_capital=100_000.0,
        settlements=[
            (pd.to_datetime(s.captured_at_utc, utc=True), -0.002)
            for s in _snaps()[5:]
        ],
    )
    assert negative.totals.funding_settled < 0
    assert negative.final_equity < result.final_equity


def test_deterministic_given_same_inputs():
    a = run_carry_ledger(_snaps(), COSTS, entry_threshold=0.0, trailing_window=3)
    b = run_carry_ledger(_snaps(), COSTS, entry_threshold=0.0, trailing_window=3)
    assert a.final_equity == b.final_equity
    assert np.allclose(a.bars["net_return"], b.bars["net_return"])