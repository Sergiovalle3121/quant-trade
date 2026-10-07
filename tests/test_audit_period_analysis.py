"""Period-level cost and benchmark arithmetic keeps the supplied first return."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.period_analysis import REASONS, period_benchmark, period_costs
from quant_trade.audit.return_series import import_return_series
from quant_trade.audit.schema import IngestedSeries


def _series(
    returns: list[float],
    *,
    frequency: str = "monthly",
    gross: list[float] | None = None,
) -> IngestedSeries:
    dates = pd.date_range(
        "2023-01-31", periods=len(returns), freq="ME" if frequency == "monthly" else "7D"
    )
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "return": returns})
    if gross is not None:
        frame["net_return"] = returns
        frame["gross_return"] = gross
    return import_return_series(
        frame.to_csv(index=False).encode(), frequency=frequency, unit="fraction"
    )


@pytest.mark.parametrize("frequency,ppy", [("monthly", 12), ("weekly", 52)])
def test_costs_use_declared_differences_and_sample_annualisation(frequency: str, ppy: int) -> None:
    net = np.array([-0.03, 0.04, 0.015, 0.07])
    gross = net + np.array([0.002, 0.003, 0.001, 0.005])
    section = period_costs(_series(net.tolist(), frequency=frequency, gross=gross.tolist()), ppy)
    assert section["status"] == "MEASURED"
    assert section["kind"] == "period_returns"
    assert section["reference_basis"]["evidence"] == "DECLARED"
    assert section["periods_per_year"] == {"value": ppy, "evidence": "DECLARED", "note": ""}
    for k, row in enumerate(section["rows"], 1):
        stressed = gross - k * (gross - net)
        assert row["multiplier"]["value"] == k
        assert row["multiplier"]["evidence"] == "DECLARED"
        assert row["total_return"]["value"] == pytest.approx(np.prod(1 + stressed) - 1)
        assert row["sharpe_annualised"]["value"] == pytest.approx(
            stressed.mean() / stressed.std(ddof=1) * math.sqrt(ppy)
        )
        assert row["total_return"]["evidence"] == row["sharpe_annualised"]["evidence"] == "MEASURED"
        assert set(row) == {"multiplier", "total_return", "sharpe_annualised"}


def test_negative_declared_cost_is_not_clamped_to_zero() -> None:
    section = period_costs(_series([0.02, 0.03, -0.01], gross=[0.01, 0.04, 0]), 12)
    assert section["status"] == "NOT_MEASURED"
    assert section["reason"] == REASONS["negative_cost"]["en"]
    assert section["rows"] == []


def test_cost_stress_does_not_compound_a_return_below_complete_loss() -> None:
    section = period_costs(_series([-0.5, 0.1, 0.2], gross=[0, 0.11, 0.21]), 12)
    first, second, third = section["rows"]
    assert first["total_return"]["evidence"] == "MEASURED"
    assert second["total_return"]["value"] == -1
    for key in ("total_return", "sharpe_annualised"):
        assert third[key]["evidence"] == "NOT_MEASURED"
        assert third[key]["value"] is None


def test_missing_cost_series_does_not_invent_a_cost() -> None:
    section = period_costs(_series([0.01, 0.02, -0.03]), 12)
    assert section["status"] == "NOT_MEASURED"
    assert section["rows"] == []


@pytest.mark.parametrize("frequency,ppy", [("monthly", 12), ("weekly", 52)])
def test_benchmark_keeps_first_returns_and_declared_frequency(frequency: str, ppy: int) -> None:
    strategy = np.array([-0.2, 0.1, 0.05, -0.02])
    benchmark = np.array([-0.1, 0.04, 0.01, 0.02])
    section, values, reason = period_benchmark(
        _series(strategy.tolist(), frequency=frequency),
        _series(benchmark.tolist(), frequency=frequency),
        ppy,
    )
    assert reason is None
    assert section["status"] == "MEASURED"
    assert section["observations"]["value"] == 4
    assert section["strategy_total_return"]["value"] == pytest.approx(np.prod(1 + strategy) - 1)
    assert section["benchmark_total_return"]["value"] == pytest.approx(np.prod(1 + benchmark) - 1)
    assert section["strategy_max_drawdown"]["value"] == pytest.approx(-0.2)
    assert values["drawdown_ratio"] == pytest.approx(2)
    assert section["strategy_sharpe"]["value"] == pytest.approx(
        strategy.mean() / strategy.std(ddof=1) * math.sqrt(ppy)
    )
    difference = strategy - benchmark
    assert section["tracking_error"]["value"] == pytest.approx(
        difference.std(ddof=1) * math.sqrt(ppy)
    )
    assert values["information_ratio"] == pytest.approx(
        difference.mean() / difference.std(ddof=1) * math.sqrt(ppy)
    )
    assert section["source"]["evidence"] == "DECLARED"
    assert section["strategy_frequency"]["evidence"] == "DECLARED"
    assert section["jensen"]["status"] == "NOT_MEASURED"


def test_frequency_mismatch_is_detected_before_a_join(monkeypatch: pytest.MonkeyPatch) -> None:
    strategy = _series([0.01, -0.02, 0.03])
    benchmark = _series([0.01, -0.02, 0.03], frequency="weekly")

    def forbidden_merge(*args: object, **kwargs: object) -> None:
        raise AssertionError("different frequencies must not be aligned")

    monkeypatch.setattr(pd.DataFrame, "merge", forbidden_merge)
    section, values, reason = period_benchmark(strategy, benchmark, 12)
    assert section["status"] == "NOT_MEASURED"
    assert reason == REASONS["frequency_mismatch"]["en"]
    assert all(value is None for value in values.values())


def test_benchmark_frequency_can_be_inferred_without_explicit_metadata() -> None:
    strategy = _series([0.01, -0.02, 0.03])
    benchmark = replace(_series([0.01, -0.02, 0.03], frequency="weekly"), return_metadata={})
    assert period_benchmark(strategy, benchmark, 12)[2] == REASONS["frequency_mismatch"]["en"]


def test_benchmark_overlap_retains_existing_threshold_and_never_fills_dates() -> None:
    strategy = _series([0.01, -0.02, 0.03, 0.015] * 5)
    benchmark = _series([0.005, -0.01, 0.02, 0.025] * 5)
    enough = replace(benchmark, frame=benchmark.frame.iloc[2:].copy())
    section, _, reason = period_benchmark(strategy, enough, 12)
    assert reason is None
    assert section["overlap_share"]["value"] == 0.9
    assert section["observations"]["value"] == 18
    insufficient = replace(benchmark, frame=benchmark.frame.iloc[3:].copy())
    section, _, reason = period_benchmark(strategy, insufficient, 12)
    assert section["status"] == "NOT_MEASURED"
    assert section["overlap_share"]["value"] == 0.85
    assert reason == REASONS["overlap"]["en"]


def test_undefined_ratios_are_not_reported_as_zero() -> None:
    strategy = _series([0.01, 0.01, 0.01], gross=[0.01, 0.01, 0.01])
    costs = period_costs(strategy, 12)
    assert all(row["sharpe_annualised"]["evidence"] == "NOT_MEASURED" for row in costs["rows"])
    section, values, _ = period_benchmark(strategy, strategy, 12)
    assert section["tracking_error"]["value"] == 0
    assert section["information_ratio"]["evidence"] == "NOT_MEASURED"
    assert section["drawdown_ratio"]["evidence"] == "NOT_MEASURED"
    assert values["information_ratio"] is None


def test_benchmark_rejects_nonfinite_returns_and_duplicate_dates() -> None:
    strategy = _series([0.01, -0.02, 0.03])
    frame = strategy.frame.copy()
    frame.loc[0, "ret"] = math.nan
    assert (
        period_benchmark(strategy, replace(strategy, frame=frame), 12)[2]
        == REASONS["invalid_returns"]["en"]
    )
    frame = strategy.frame.copy()
    frame.loc[0, "timestamp"] = frame.loc[1, "timestamp"]
    assert (
        period_benchmark(strategy, replace(strategy, frame=frame), 12)[2]
        == REASONS["invalid_returns"]["en"]
    )


def test_legacy_benchmark_opening_balance_is_not_a_return_period() -> None:
    strategy = _series([0.01, -0.02, 0.03, 0.005])
    base = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2023-01-01", tz="UTC")],
            "equity": [1.0],
            "ret": [math.nan],
        }
    )
    legacy = replace(
        strategy,
        frame=pd.concat([base, strategy.frame], ignore_index=True),
        return_metadata={},
    )
    section, values, reason = period_benchmark(strategy, legacy, 12)
    assert reason is None
    assert section["observations"]["value"] == 4
    assert section["benchmark_frequency"]["value"] == "monthly"
    assert values["excess_return"] == pytest.approx(0)


def test_copy_and_payload_pass_the_guard_in_all_languages() -> None:
    for translations in REASONS.values():
        for text in translations.values():
            assert find_claims(text) == []
    strategy = _series([0.01, -0.02, 0.03], gross=[0.02, -0.01, 0.04])
    for payload in (period_costs(strategy, 12), period_benchmark(strategy, strategy, 12)[0]):
        assert find_claims(json.dumps(payload)) == []
