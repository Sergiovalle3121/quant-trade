"""Golden regression tests locking core evidence numerics against silent drift.

These pin exact outputs of the statistical and economic calculators for fixed
inputs and seeds. If a refactor changes an evidence number, it must change these
constants deliberately — evidence must never move by accident.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.carry.economics import evaluate_carry
from quant_trade.carry.models import CarryCostModel, CarryPolicy, CarryPosition, CarrySnapshot
from quant_trade.metrics.statistics import expected_max_sharpe, psr_from_moments
from quant_trade.research.bootstrap import bootstrap_confidence_intervals


def _ar1(n: int, phi: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, 0.01, n)
    x = np.empty(n)
    x[0] = eps[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def test_golden_bootstrap_confidence_intervals():
    ci = bootstrap_confidence_intervals(
        pd.Series(_ar1(400, 0.5, seed=123)),
        method="stationary", samples=500, seed=42, block_size=20,
    )
    assert ci.loc["total_return", "p2.5"] == pytest.approx(-0.30829271, abs=1e-6)
    assert ci.loc["total_return", "p97.5"] == pytest.approx(1.33940845, abs=1e-6)
    assert ci.loc["sharpe", "p2.5"] == pytest.approx(-0.07349689, abs=1e-6)
    assert ci.loc["sharpe", "p97.5"] == pytest.approx(0.18649481, abs=1e-6)


def test_golden_deflated_sharpe():
    threshold = expected_max_sharpe(50, 0.02)
    dsr = psr_from_moments(0.15, 250, 0.1, 3.5, benchmark_sharpe=threshold)
    assert threshold == pytest.approx(0.32191787, abs=1e-6)
    assert dsr == pytest.approx(0.00332290, abs=1e-6)


def test_golden_carry_net_annual_carry():
    snap = CarrySnapshot(
        symbol="BTC", exchange="v", captured_at_utc="2024-01-01T00:00:00Z", spot_price=30000.0,
        perp_mark_price=30030.0, perp_index_price=30000.0, realized_funding_rate=0.0005,
        taker_fee_bps=5.0, borrow_available=True, borrow_rate_annual=0.02, data_source="real",
    )
    ev = evaluate_carry(
        snap, CarryPosition(notional_usd=100000.0, holding_days=30.0),
        CarryCostModel(), CarryPolicy(),
    )
    assert ev.gross_annual_carry == pytest.approx(0.54750000, abs=1e-8)
    assert ev.net_annual_carry == pytest.approx(0.20995000, abs=1e-8)
