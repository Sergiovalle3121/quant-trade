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
from quant_trade.mining.cashflow import ProjectionAssumptions, project_mining_cashflow
from quant_trade.mining.market import MiningMarketData
from quant_trade.mining.models import MiningRig
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


def test_golden_mining_npv_overstatement():
    rig = MiningRig(
        name="g", algorithm="sha256", hashrate_hs=2.0e14, power_watts=3500.0,
        hardware_cost_usd=5000.0, useful_life_days=1095.0, uptime_rate=0.95,
        residual_value_usd=200.0,
    )
    market = MiningMarketData(
        coin="BTC", algorithm="sha256", coin_price_usd=60000.0, network_hashrate_hs=6.0e20,
        difficulty=8.0e13, block_subsidy_coin=3.125, tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0, captured_at_utc="2024-05-01T00:00:00Z", source_name="g",
        pool_fee_rate=0.01,
    )
    proj = project_mining_cashflow(
        rig, market,
        ProjectionAssumptions(horizon_days=1095, monthly_difficulty_growth_rate=0.03,
                              halving_day_indices=(500,), electricity_usd_per_kwh=0.06),
    )
    assert proj.npv_usd == pytest.approx(-5029.125757, abs=1e-3)
    assert proj.constant_flow_npv_usd == pytest.approx(-1068.273963, abs=1e-3)
    assert proj.total_coin_mined == pytest.approx(0.0804800841, abs=1e-9)


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
