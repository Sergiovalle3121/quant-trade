"""Economic gates retain sealed capital, expenses, cadence and adverse evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_trade.metrics import statistics
from quant_trade.personal_paper import economic
from quant_trade.personal_paper.economic import (
    CANDIDATES,
    CONTROL,
    _bootstrap_pair,
    _cost_paths,
    _trial_history,
    economic_protocol,
    economic_protocol_hash,
    evaluate_economic,
)


def _inputs(tmp_path, count=270):
    # Official calendar is computed offline, including holidays and half-days.
    import exchange_calendars as xcals

    schedule = xcals.get_calendar("XNYS", start="2023-01-03", end="2025-01-02").schedule
    dates = pd.DatetimeIndex(pd.to_datetime(schedule["close"], utc=True))[:count]
    start = (dates[0] - pd.Timedelta(hours=1)).isoformat()
    rng = np.random.default_rng(20)
    control = rng.normal(0.0004, 0.012, count - 1)
    rows = []
    for name in (*CANDIDATES, CONTROL):
        returns = control if name == CONTROL else control * 0.4 + 0.0003
        for stress in (1, 2, 3):
            path = 20_000 * np.concatenate(([1], np.cumprod(1 + returns - stress * 0.00001)))
            rows.extend(
                {
                    "timestamp": date.isoformat(),
                    "portfolio": name,
                    "cost_multiplier": stress,
                    "equity_mxn": float(value),
                }
                for date, value in zip(dates, path, strict=True)
            )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps({"test_sharpe_per_period": value}) for value in [0.02, 0.04, -0.01, 0.01]
        ),
        encoding="utf-8",
    )
    costs = pd.DataFrame(
        [
            {
                "start": start,
                "end": dates[-1].isoformat(),
                "category": category,
                "amount_mxn": 0.0,
            }
            for category in ("infrastructure", "data", "fx_transfer")
        ]
    )
    return pd.DataFrame(rows), ledger, costs, start


def _review(curves, ledger, start, costs=None, **kwargs):
    options = {
        "evidence_kind": "PROSPECTIVE_SIMULATION",
        "baseline_capital_mxn": 20_000,
        "calendar_verified": True,
        "frozen_economic_protocol_sha256": economic_protocol_hash(),
        **kwargs,
    }
    return evaluate_economic(
        curves,
        prospective_started_at=start,
        ledger_path=ledger,
        observed_costs=costs,
        **options,
    )


def _all_reasons(result, reason):
    return all(reason in row["missing_evidence"] for row in result["candidates"].values())


def test_development_cannot_be_promoted_even_with_good_curves(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    result = _review(curves, ledger, start, costs, evidence_kind="DEVELOPMENT")
    assert result["status"] == "INCONCLUSIVE"
    assert result["real_money_approved"] is False
    assert _all_reasons(result, "independent_prospective_evidence_required")


def test_zero_expenses_need_explicit_full_coverage(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    assert _review(curves, ledger, start)["status"] == "INCONCLUSIVE"
    incomplete = costs[costs.category != "data"]
    result = _review(curves, ledger, start, incomplete)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "observed_operating_cost_coverage_required")


def test_expenses_can_eliminate_positive_simulated_returns(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    costs.loc[costs.category == "infrastructure", "amount_mxn"] = 40_000
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "REJECTED"
    assert all(
        row["failed_criteria"] == ["expense_exceeds_simulated_equity"]
        for row in result["candidates"].values()
    )


def test_new_closes_count_sessions_but_partial_baseline_is_not_daily_return(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 64)
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    for row in result["candidates"].values():
        assert row["observations"] == 64
        assert row["complete_close_to_close_return_observations"] == 63
        assert row["initial_partial_interval_counted_as_daily_return"] is False


@pytest.mark.parametrize("count,ready", [(252, False), (253, True)])
def test_252_complete_intervals_require_253_new_closes(tmp_path, count, ready):
    curves, ledger, costs, start = _inputs(tmp_path, count)
    result = _review(curves, ledger, start, costs)
    for row in result["candidates"].values():
        assert row["complete_close_to_close_return_observations"] == count - 1
        missing = "at_least_252_complete_close_to_close_returns_required" in row["missing_evidence"]
        assert missing is not ready


def test_baseline_row_is_not_counted_as_new_session(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 64)
    baseline = curves.groupby(["portfolio", "cost_multiplier"]).head(1).copy()
    baseline["timestamp"] = start
    result = _review(pd.concat([baseline, curves]), ledger, start, costs)
    assert all(row["observations"] == 64 for row in result["candidates"].values())


def test_new_registration_without_closed_observations_is_inconclusive(tmp_path):
    curves, ledger, _, start = _inputs(tmp_path, 64)
    result = _review(curves.iloc[:0], ledger, start)
    assert result["status"] == "INCONCLUSIVE"
    assert all(row["observations"] == 0 for row in result["candidates"].values())
    assert result["real_money_approved"] is False


def test_single_first_close_can_be_reviewed_without_calendar_factory_failure(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 1)
    costs.loc[costs.category == "fx_transfer", "amount_mxn"] = 100
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    for row in result["candidates"].values():
        assert row["observations"] == 1
        assert row["complete_close_to_close_return_observations"] == 0
        assert row["net_1x"]["initial_partial_return"] == pytest.approx(-0.005)
        assert row["net_1x"]["net_return"] == pytest.approx(-0.005)
        assert row["net_1x"]["sharpe"] == 0.0
        assert "verified_official_session_calendar_required" not in row["missing_evidence"]


def test_missing_trial_moments_cannot_fall_back_to_uncorrected_psr(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write('\n{"strategy":"unknown_prior_test"}')
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert result["historical_trials"] == 5
    assert _all_reasons(result, "complete_historical_trial_moments_required")
    assert all("dsr" not in row for row in result["candidates"].values())


@pytest.mark.parametrize("sharpes", [[0.04], [0.04, 0.04, 0.04]])
def test_unestimable_trial_dispersion_cannot_fall_back_to_psr(tmp_path, sharpes):
    curves, ledger, costs, start = _inputs(tmp_path)
    ledger.write_text(
        "\n".join(json.dumps({"test_sharpe_per_period": value}) for value in sharpes),
        encoding="utf-8",
    )
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "complete_historical_trial_moments_required")
    assert all("dsr" not in row for row in result["candidates"].values())


def test_selected_only_window_history_cannot_invent_unrecorded_alternatives(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    records = [
        {
            "source": "multi_asset_walk_forward",
            "experiment_name": "old_experiment",
            "strategy": "inverse_volatility",
            "window": 1,
            "data_sha256": "same_dataset",
            "strategy_params": {"volatility_window": 63},
            "trials_in_window": 3,
            "test_sharpe_per_period": value,
        }
        for value in [0.02, 0.03]
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "complete_historical_selection_trials_required")
    assert all("dsr" not in row for row in result["candidates"].values())
    group = result["historical_trial_evidence"]["incomplete_window_groups"][0]
    assert group["recorded_unique_configurations"] == 1
    assert group["declared_trials"] == [3]


def test_complete_window_keeps_all_parameter_alternatives(tmp_path):
    _, ledger, _, _ = _inputs(tmp_path, 20)
    records = [
        {
            "source": "multi_asset_walk_forward",
            "experiment_name": "new_complete_experiment",
            "strategy": "inverse_volatility",
            "window": 1,
            "data_sha256": "same_dataset",
            "strategy_params": {"volatility_window": window},
            "trials_in_window": 3,
            "test_sharpe_per_period": value,
        }
        for window, value in [(42, 0.02), (63, 0.03), (126, -0.01)]
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    trials, variance, evidence = _trial_history(ledger)
    assert trials == 3
    assert variance is not None
    assert evidence["selection_history_complete"] is True


def test_frozen_repository_history_is_reported_incomplete_without_rewriting():
    path = Path(__file__).resolve().parents[1] / "docs/real_data_evidence/trial_ledger.jsonl"
    original = path.read_bytes()
    trials, variance, evidence = _trial_history(path)
    assert trials == 109
    assert variance is None
    assert evidence["window_group_count"] == 96
    assert evidence["incomplete_window_group_count"] == 48
    assert all(
        row["recorded_unique_configurations"] == 1 and row["declared_trials"] == [3]
        for row in evidence["incomplete_window_groups"]
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 0.0])
def test_invalid_equity_is_rejected(tmp_path, value):
    curves, ledger, _, start = _inputs(tmp_path, 20)
    curves.loc[0, "equity_mxn"] = value
    with pytest.raises(ValueError):
        _review(curves, ledger, start)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 0.0, True])
def test_invalid_sealed_capital_is_rejected(tmp_path, value):
    curves, ledger, _, start = _inputs(tmp_path, 20)
    with pytest.raises(ValueError):
        _review(curves, ledger, start, baseline_capital_mxn=value)


def test_missing_sealed_capital_cannot_use_first_close_as_initial_wealth(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    result = _review(curves, ledger, start, costs, baseline_capital_mxn=None)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "sealed_initial_capital_required")


def test_pre_first_close_expense_and_fx_loss_remain_in_net_return_and_drawdown(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    dates = pd.DatetimeIndex(pd.to_datetime(sorted(curves.timestamp.unique()), utc=True))
    curves["equity_mxn"] *= 0.98  # MXN valuation change after seal, before first close.
    costs.loc[costs.category == "fx_transfer", "end"] = dates[0].isoformat()
    costs.loc[costs.category == "fx_transfer", "amount_mxn"] = 400
    costs = pd.concat(
        [
            costs,
            pd.DataFrame(
                [
                    {
                        "start": dates[0].isoformat(),
                        "end": dates[-1].isoformat(),
                        "category": "fx_transfer",
                        "amount_mxn": 0.0,
                    }
                ]
            ),
        ]
    )
    result = _review(curves, ledger, start, costs)
    for row in result["candidates"].values():
        assert row["operating_costs_mxn"]["fx_transfer"] == pytest.approx(400)
        assert row["net_1x"]["initial_partial_return"] == pytest.approx(-0.04)
        assert row["net_1x"]["max_drawdown"] >= 0.04 - 1e-12
        assert row["control"]["initial_partial_return"] == pytest.approx(-0.04)
        assert row["cost_coverage_end"] == dates[-1].isoformat()
        last = curves[(curves.portfolio == CANDIDATES[0]) & (curves.cost_multiplier == 1)].iloc[-1]
        assert row["net_1x"]["net_return"] == pytest.approx((last.equity_mxn - 400) / 20_000 - 1)


def test_pre_first_close_infrastructure_cost_is_candidate_only(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    first = min(curves.timestamp)
    costs.loc[costs.category == "infrastructure", "end"] = first
    costs.loc[costs.category == "infrastructure", "amount_mxn"] = 100
    costs = pd.concat(
        [
            costs,
            pd.DataFrame(
                [
                    {
                        "start": first,
                        "end": max(curves.timestamp),
                        "category": "infrastructure",
                        "amount_mxn": 0.0,
                    }
                ]
            ),
        ]
    )
    result = _review(curves, ledger, start, costs)
    for row in result["candidates"].values():
        assert row["net_1x"]["initial_partial_return"] == pytest.approx(-0.005)
        assert row["control"]["initial_partial_return"] == pytest.approx(0.0)


def test_cost_coverage_ends_at_last_close_without_an_extra_day(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    result = _review(curves, ledger, start, costs)
    assert not _all_reasons(result, "observed_operating_cost_coverage_required")
    paths = _cost_paths(
        costs,
        pd.DatetimeIndex(pd.to_datetime(sorted(curves.timestamp.unique()), utc=True)),
        prospective_started_at=pd.Timestamp(start),
    )
    assert all(np.array_equal(values, np.zeros(20)) for values in paths.values())


@pytest.mark.parametrize("offset", [pd.Timedelta(seconds=1), -pd.Timedelta(seconds=1)])
def test_gaps_and_overlaps_in_cost_intervals_are_inconclusive(tmp_path, offset):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    boundary = pd.Timestamp(curves.timestamp.iloc[10])
    costs.loc[costs.category == "infrastructure", "end"] = boundary.isoformat()
    costs = pd.concat(
        [
            costs,
            pd.DataFrame(
                [
                    {
                        "start": (boundary + offset).isoformat(),
                        "end": max(curves.timestamp),
                        "category": "infrastructure",
                        "amount_mxn": 0.0,
                    }
                ]
            ),
        ]
    )
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "observed_operating_cost_coverage_required")


def test_cost_missing_before_first_close_is_inconclusive(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    costs["start"] = min(curves.timestamp)
    result = _review(curves, ledger, start, costs)
    assert _all_reasons(result, "observed_operating_cost_coverage_required")


def test_cost_intervals_clipped_to_seal_and_last_close(tmp_path):
    curves, _, costs, start = _inputs(tmp_path, 20)
    dates = pd.DatetimeIndex(pd.to_datetime(sorted(curves.timestamp.unique()), utc=True))
    original_start, original_end = pd.Timestamp(start), dates[-1]
    costs["start"] = (original_start - pd.Timedelta(days=1)).isoformat()
    costs["end"] = (original_end + pd.Timedelta(days=1)).isoformat()
    costs["amount_mxn"] = 100
    paths = _cost_paths(costs, dates, prospective_started_at=original_start)
    fraction = (original_end - original_start) / (
        original_end - original_start + pd.Timedelta(days=2)
    )
    assert all(values[-1] == pytest.approx(100 * fraction) for values in paths.values())
    assert all(values[0] > 0 for values in paths.values())


def test_sharpe_excludes_the_initial_partial_hours(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    curves["equity_mxn"] *= 0.5
    result = _review(curves, ledger, start, costs)
    row = result["candidates"][CANDIDATES[0]]["net_1x"]
    closes = curves[(curves.portfolio == CANDIDATES[0]) & (curves.cost_multiplier == 1)].equity_mxn
    returns = closes.to_numpy()[1:] / closes.to_numpy()[:-1] - 1
    assert row["sharpe"] == pytest.approx(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
    assert row["max_drawdown"] >= 0.5


def test_paired_resampling_keeps_identical_strategies_identical():
    returns = np.random.default_rng(4).normal(0.0003, 0.01, 252)
    intervals = _bootstrap_pair(returns, returns, samples=100)
    assert intervals["sharpe_gap_interval"] == [0.0, 0.0]
    assert intervals == _bootstrap_pair(returns, returns, samples=100)


def test_bootstrap_holds_initial_partial_loss_fixed_without_annualizing():
    returns = np.tile([0.001, 0.002], 126)
    intervals = _bootstrap_pair(
        returns,
        returns,
        samples=100,
        initial_candidate_return=-0.10,
        initial_control_return=0.0,
    )
    assert intervals["sharpe_gap_interval"] == [0.0, 0.0]
    assert intervals["drawdown_advantage_interval"] == pytest.approx([-0.10, -0.10])


def test_mismatched_sessions_are_not_silently_intersected(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    curves = curves.drop(
        curves[(curves.portfolio == CONTROL) & (curves.cost_multiplier == 1)].index[10]
    )
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "identical_session_coverage_required")


def test_calendar_verification_is_required_even_for_official_close_timestamps(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    result = _review(curves, ledger, start, costs, calendar_verified=False)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "verified_official_session_calendar_required")


def test_shared_missing_session_cannot_hide_behind_equal_coverage(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    missing = sorted(curves.timestamp.unique())[10]
    result = _review(curves[curves.timestamp != missing], ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "verified_official_session_calendar_required")


def test_weekday_midnight_labels_are_not_official_closes(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    curves["timestamp"] = (pd.to_datetime(curves.timestamp) - pd.Timedelta(minutes=1)).astype(str)
    result = _review(curves, ledger, start, costs)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "verified_official_session_calendar_required")


@pytest.mark.parametrize("frozen", [None, "wrong-seal"])
def test_missing_or_changed_economic_protocol_is_inconclusive(tmp_path, frozen):
    curves, ledger, costs, start = _inputs(tmp_path)
    result = _review(curves, ledger, start, costs, frozen_economic_protocol_sha256=frozen)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "frozen_economic_protocol_match_required")


def test_protocol_freezes_criteria_bootstrap_and_implementation():
    protocol = economic_protocol()
    assert protocol["schema_version"] == 2
    assert protocol["minimum_complete_close_to_close_returns"] == 252
    assert protocol["minimum_closed_sessions"] == 253
    assert protocol["criteria"]["minimum_annualized_sharpe_gap"] == 0.10
    assert protocol["criteria"]["maximum_drawdown_fraction_of_control"] == 0.90
    assert protocol["bootstrap"]["samples"] == 10_000
    assert protocol["bootstrap"]["block_sessions"] == 20
    assert protocol["code_sha256"] == {
        "personal_paper/economic.py": hashlib.sha256(
            Path(economic.__file__).read_bytes()
        ).hexdigest(),
        "metrics/statistics.py": hashlib.sha256(Path(statistics.__file__).read_bytes()).hexdigest(),
    }
    expected = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert economic_protocol_hash() == expected


def test_changing_bootstrap_sample_count_cannot_change_the_frozen_decision(tmp_path):
    curves, ledger, costs, start = _inputs(tmp_path)
    result = _review(curves, ledger, start, costs, bootstrap_samples=100)
    assert result["status"] == "INCONCLUSIVE"
    assert _all_reasons(result, "frozen_bootstrap_sample_count_required")


def test_changed_statistics_implementation_invalidates_frozen_protocol(tmp_path, monkeypatch):
    curves, ledger, costs, start = _inputs(tmp_path, 20)
    frozen = economic_protocol_hash()
    read_bytes = Path.read_bytes

    def changed_statistics(path):
        content = read_bytes(path)
        return content + b"changed implementation" if path == Path(statistics.__file__) else content

    monkeypatch.setattr(Path, "read_bytes", changed_statistics)
    result = _review(curves, ledger, start, costs, frozen_economic_protocol_sha256=frozen)
    assert result["status"] == "INCONCLUSIVE"
    assert economic_protocol_hash() != frozen
    assert _all_reasons(result, "frozen_economic_protocol_match_required")


def test_cli_passes_verified_manifest_baseline_calendar_and_frozen_protocol(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from quant_trade.personal_paper import cli

    curves, _, costs, start = _inputs(tmp_path, 20)
    output = tmp_path / "review"
    output.mkdir()
    curves_path = output / "curves.csv"
    curves.to_csv(curves_path, index=False)
    costs_path = tmp_path / "costs.csv"
    costs.to_csv(costs_path, index=False)
    manifest_path = output / "manifest.json"
    frozen_hash = economic_protocol_hash()
    manifest_path.write_text(
        json.dumps(
            {
                "clock_source": "SYSTEM_UTC",
                "data_kind": "market",
                "prospective_started_at": start,
                "evidence_kind": "PROSPECTIVE_SIMULATION",
                "capital_mxn": 20_000,
                "calendar_verified": True,
                "economic_protocol_sha256": frozen_hash,
                "historical_trials": [{"test_sharpe_per_period": 0.04}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli.engine,
        "export",
        lambda *_: {"manifest": str(manifest_path), "curves": str(curves_path)},
    )
    received = {}

    def review(_curves, **kwargs):
        received.update(kwargs)
        return {"status": "INCONCLUSIVE", "real_money_approved": False}

    monkeypatch.setattr(economic, "evaluate_economic", review)
    result = CliRunner().invoke(
        cli.app,
        [
            "economic-review",
            "--database",
            str(tmp_path / "fake.db"),
            "--output",
            str(output),
            "--costs",
            str(costs_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert received["baseline_capital_mxn"] == 20_000
    assert received["calendar_verified"] is True
    assert received["frozen_economic_protocol_sha256"] == frozen_hash
    assert received["prospective_started_at"] == start
    assert len(received["observed_costs"]) == 3
    saved = json.loads((output / "economic_review.json").read_text())
    assert saved["real_money_approved"] is False
