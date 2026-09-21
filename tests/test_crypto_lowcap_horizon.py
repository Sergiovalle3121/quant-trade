"""Tests for the capital horizon: measured only from a revealed verdict, else declared."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from crypto_lowcap_fixture import AT, build_experiment

from quant_trade.research.bootstrap import stationary_bootstrap, stationary_bootstrap_indices
from quant_trade.research.crypto_lowcap.campaign import run_select
from quant_trade.research.crypto_lowcap.horizon import (
    HorizonError,
    capacity,
    constant_return_years,
    horizon_path,
    run_horizon,
    simulate_paths,
    summarise,
)
from quant_trade.research.crypto_lowcap.report import (
    assert_no_profit_claims,
    render_results_markdown,
)
from quant_trade.research.crypto_lowcap.reveal import run_reveal


def _revealed(tmp_path: Path) -> dict:
    fx = build_experiment(tmp_path)
    run_select(fx["experiment"], fx["trials"], fx["panel"], evaluated_at_utc=AT, code_sha="abc")
    run_reveal(fx["experiment"], fx["panel"], reason="fixture", evaluated_at_utc=AT, code_sha="abc")
    return fx


def test_public_indices_reproduce_the_private_sampler_byte_for_byte() -> None:
    returns = np.random.default_rng(3).normal(0.0005, 0.02, 400)
    summary = stationary_bootstrap(returns, samples=50, expected_block_size=10.0, seed=9)
    rng = np.random.default_rng(9)
    idx = stationary_bootstrap_indices(
        400, length=400, samples=50, expected_block_size=10.0, rng=rng
    )
    paths = returns[idx]
    equity = np.cumprod(1.0 + paths, axis=1)
    np.testing.assert_allclose(summary["total_return"].to_numpy(), equity[:, -1] - 1.0)
    longer = stationary_bootstrap_indices(
        400, length=1000, samples=3, expected_block_size=10.0, rng=rng
    )
    assert longer.shape == (3, 1000)
    assert longer.max() < 400
    with pytest.raises(ValueError):
        stationary_bootstrap_indices(400, length=0, samples=3, expected_block_size=10.0, rng=rng)


def test_simulate_paths_reaches_a_target_under_a_positive_drift() -> None:
    returns = np.full(365, 0.001)  # +44% a year, no noise
    stats = simulate_paths(
        returns, years=10, samples=20, seed=1, expected_block_size=20.0, capital=100.0, target=200.0
    )
    summary = summarise(stats, capital=100.0, years=10)
    assert summary["p_reached_within_horizon"] == 1.0
    assert 1.5 < summary["years_to_target"]["p50"] < 2.5
    assert summary["p_reach_by_years"]["5"] == 1.0
    assert summary["p_50pct_drawdown_before_target"] == 0.0
    assert constant_return_years(
        0.44, capital=100.0, target=200.0, monthly_contribution=0.0, years=10
    ) == pytest.approx(1.9, abs=0.1)
    assert (
        constant_return_years(0.0, capital=100.0, target=200.0, monthly_contribution=0.0, years=10)
        is None
    )
    assert constant_return_years(
        0.0, capital=100.0, target=200.0, monthly_contribution=10.0, years=10
    ) == pytest.approx(10 / 12, abs=0.01)


def test_not_revealed_is_not_measured_and_assumptions_are_labelled(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    payload = run_horizon(
        fx["experiment"], capital=10_000, target=1_000_000, at_utc=AT, code_sha="abc"
    )
    assert payload["state"] == "NOT_MEASURED"
    assert payload["rows"] == []
    assert horizon_path(fx["experiment"]).is_file()
    with pytest.raises(HorizonError, match="together"):
        run_horizon(
            fx["experiment"],
            capital=10_000,
            target=1_000_000,
            assume_annual_return=0.15,
            at_utc=AT,
            code_sha="abc",
        )
    assumed = run_horizon(
        fx["experiment"],
        capital=10_000,
        target=1_000_000,
        years=40,
        samples=200,
        assume_annual_return=0.15,
        assume_annual_volatility=0.30,
        at_utc=AT,
        code_sha="abc",
    )
    assert assumed["state"] == "ASSUMPTION"
    row = assumed["assumed"]["rows"][0]
    assert row["evidence_class"] == "ASSUMPTION"
    assert row["constant_return_years_to_target"] == pytest.approx(33.0, abs=0.5)
    assert assumed["rows"] == []


def test_revealed_horizon_has_measured_rows_and_capacity(tmp_path: Path) -> None:
    fx = _revealed(tmp_path)
    payload = run_horizon(
        fx["experiment"],
        capital=10_000,
        target=20_000,
        years=10,
        samples=300,
        at_utc=AT,
        code_sha="abc",
    )
    assert payload["state"] == "MEASURED"
    names = {(r["name"], r["recovery"]) for r in payload["rows"]}
    assert any(n.startswith("primary:") and rec == "0.0" for n, rec in names)
    assert any(n.startswith("primary:") and rec == "1.0" for n, rec in names)
    assert any(n == "benchmark:btc_buy_and_hold" for n, _ in names)
    for row in payload["rows"]:
        if row["evidence_class"] != "MEASURED":
            continue
        reach = [row["p_reach_by_years"][k] for k in ("5", "10")]
        assert reach == sorted(reach)
        assert 0.0 <= row["p_50pct_drawdown_before_target"] <= 1.0
    assert payload["capacity"]["status"] == "WITHIN_CALIBRATION"
    big = run_horizon(
        fx["experiment"],
        capital=1_000_000,
        target=2_000_000,
        years=5,
        samples=100,
        at_utc=AT,
        code_sha="abc",
    )
    assert big["capacity"]["status"] == "NOT_MEASURED"
    with pytest.raises(HorizonError, match="never mixed"):
        run_horizon(
            fx["experiment"],
            capital=1,
            target=2,
            assume_annual_return=0.1,
            assume_annual_volatility=0.1,
            at_utc=AT,
            code_sha="abc",
        )
    text = render_results_markdown(fx["experiment"])
    assert "## 8. What this implies for capital" in text
    assert "MEASURED" in text
    assert_no_profit_claims(text)


def test_horizon_is_deterministic_for_a_seed(tmp_path: Path) -> None:
    fx = _revealed(tmp_path)
    a = run_horizon(
        fx["experiment"],
        capital=5_000,
        target=10_000,
        years=5,
        samples=120,
        seed=7,
        at_utc=AT,
        code_sha="abc",
    )
    b = run_horizon(
        fx["experiment"],
        capital=5_000,
        target=10_000,
        years=5,
        samples=120,
        seed=7,
        at_utc=AT,
        code_sha="abc",
    )
    assert json.dumps(a["rows"], sort_keys=True) == json.dumps(b["rows"], sort_keys=True)


def test_capacity_without_top_n_is_not_measured() -> None:
    result = capacity(
        {"strategy_params": {}},
        capital=1000,
        quantile="p75",
        min_executable_fraction=1.0,
        campaign_legs=None,
    )
    assert result["status"] == "NOT_MEASURED"
    result = capacity(
        {"strategy_params": {"top_n": 10, "tier": "mid"}},
        capital=5_000,
        quantile="p75",
        min_executable_fraction=1.0,
        campaign_legs=None,
    )
    assert result["status"] == "WITHIN_CALIBRATION"
    assert result["tiers_considered"] == ["mid"]
