"""Trade statistics, resampled drawdown risk, the challenge simulator and
the vendor questions: hand-checked values, invariants and determinism."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import positive_drift

from quant_trade.audit import analytics
from quant_trade.audit.guard import find_claims
from quant_trade.audit.prop_presets import PRESETS, ChallengeRules, get_preset
from quant_trade.core.models import Trade

T0 = datetime(2024, 1, 1, 9, tzinfo=UTC)

#: Words thread A adds to the guard; checked here too so these texts keep
#: passing once the guard is extended.
EXTRA_BANNED = (r"\bverificad", r"\bcertificad", r"\baprobad", r"\bpasar[áa]s\b", r"\bguarantee")


def _trade(i: int, pnl: float, *, hours: float = 2.0, qty: float = 1.0) -> Trade:
    entry = T0 + timedelta(days=i)
    return Trade(
        entry_time=entry,
        exit_time=entry + timedelta(hours=hours),
        quantity=qty,
        entry_price=100.0,
        exit_price=100.0 + pnl / qty if 100.0 + pnl / qty > 0 else 1.0,
        pnl=pnl,
        return_pct=pnl / (100.0 * qty),
    )


def _value(entry: dict) -> float:
    assert entry["evidence"] == "MEASURED", entry
    return entry["value"]


def _texts(obj: object) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [text for value in obj.values() for text in _texts(value)]
    if isinstance(obj, list | tuple):
        return [text for value in obj for text in _texts(value)]
    return []


def _assert_clean(obj: object) -> None:
    for text in _texts(obj):
        assert find_claims(text) == [], text
        for pattern in EXTRA_BANNED:
            assert not re.search(pattern, text.lower()), text


# --- trade statistics ------------------------------------------------------


def test_trade_statistics_hand_checked() -> None:
    pnls = [10.0, -5.0, 20.0, -5.0, -5.0, 15.0]
    trades = [_trade(i, p, hours=float(i + 1)) for i, p in enumerate(pnls)]
    sides = ["long", "short", "long", "long", "short", "long"]
    stats = analytics.trade_statistics(trades, sides, fees_total=6.0)

    assert _value(stats["trade_count"]) == 6
    assert _value(stats["win_rate"]) == pytest.approx(0.5)
    assert _value(stats["gross_profit"]) == pytest.approx(45.0)
    assert _value(stats["gross_loss"]) == pytest.approx(-15.0)
    assert _value(stats["net_pnl"]) == pytest.approx(24.0)
    assert _value(stats["expectancy"]) == pytest.approx(4.0)
    assert _value(stats["profit_factor"]) == pytest.approx(3.0)
    assert _value(stats["average_win"]) == pytest.approx(15.0)
    assert _value(stats["average_loss"]) == pytest.approx(-5.0)
    assert _value(stats["payoff_ratio"]) == pytest.approx(3.0)
    assert _value(stats["largest_win_share"]) == pytest.approx(20.0 / 45.0)
    assert _value(stats["max_consecutive_wins"]) == 1
    assert _value(stats["max_consecutive_losses"]) == 2
    assert _value(stats["mean_holding_hours"]) == pytest.approx(3.5)
    assert _value(stats["median_holding_hours"]) == pytest.approx(3.5)
    expected_sqn = math.sqrt(6) * np.mean(pnls) / np.std(pnls, ddof=1)
    assert _value(stats["sqn"]) == pytest.approx(expected_sqn)
    assert _value(stats["long"]["trade_count"]) == 4
    assert _value(stats["long"]["win_rate"]) == pytest.approx(0.75)
    assert _value(stats["short"]["net_pnl"]) == pytest.approx(-10.0)
    span_days = (trades[-1].exit_time - trades[0].entry_time).total_seconds() / 86400
    assert _value(stats["trades_per_month"]) == pytest.approx(6 / (span_days / (365.25 / 12)))


def test_trade_statistics_orders_by_exit_time() -> None:
    late_loss = _trade(0, -5.0, hours=200.0)
    trades = [late_loss, _trade(1, -5.0), _trade(2, 5.0), _trade(3, 5.0)]
    stats = analytics.trade_statistics(trades, ["long"] * 4)
    # By exit: -5 (day 1), +5, +5, -5 (late) -> longest loss run is 1.
    assert _value(stats["max_consecutive_losses"]) == 1
    assert _value(stats["max_consecutive_wins"]) == 2


def test_trade_statistics_without_trades_is_not_measured() -> None:
    stats = analytics.trade_statistics([], [])
    assert stats["win_rate"]["evidence"] == "NOT_MEASURED"
    assert stats["sqn"]["note"] == "no trades uploaded"


def test_trade_statistics_undefined_ratios() -> None:
    stats = analytics.trade_statistics([_trade(0, 3.0), _trade(1, 4.0)], ["long", "long"])
    assert stats["profit_factor"]["evidence"] == "NOT_MEASURED"
    assert stats["payoff_ratio"]["evidence"] == "NOT_MEASURED"
    assert stats["short"]["win_rate"]["evidence"] == "NOT_MEASURED"
    assert stats["fees_total"]["evidence"] == "NOT_MEASURED"
    with pytest.raises(ValueError):
        analytics.trade_statistics([_trade(0, 1.0)], [])


def test_trade_statistics_is_json_serialisable() -> None:
    trades = [_trade(i, float((-1) ** i) * (i + 1)) for i in range(20)]
    json.dumps(analytics.trade_statistics(trades, ["long"] * 20), allow_nan=False)


# --- drawdown risk -------------------------------------------------------------


def _daily_returns(n: int = 750, *, seed: int = 3) -> pd.Series:
    frame = positive_drift(n, seed=seed)
    return frame["equity"].pct_change().dropna()


def test_drawdown_risk_invariants_and_determinism() -> None:
    returns = _daily_returns()
    risk = analytics.drawdown_risk(returns, periods_per_year=252, samples=800, seed=7)
    again = analytics.drawdown_risk(returns, periods_per_year=252, samples=800, seed=7)
    assert json.dumps(risk, allow_nan=False) == json.dumps(again, allow_nan=False)

    p50, p95, p99 = (_value(risk["max_drawdown"][k]) for k in ("p50", "p95", "p99"))
    assert 0.0 < p50 <= p95 <= p99 < 1.0
    probabilities = [_value(v) for v in risk["probability_drawdown_at_least"].values()]
    assert list(risk["probability_drawdown_at_least"]) == ["0.10", "0.20", "0.30", "0.50"]
    assert all(0.0 <= p <= 1.0 for p in probabilities)
    assert probabilities == sorted(probabilities, reverse=True)
    uw = risk["longest_underwater_periods"]
    assert 0 < _value(uw["p50"]) <= _value(uw["p95"]) <= 252

    fan = risk["fan"]
    assert fan["evidence"] == "MEASURED"
    assert len(fan["period"]) <= analytics.MAX_FAN_POINTS
    assert fan["period"][0] == 0 and fan["period"][-1] == 252
    assert fan["p50"][0] == pytest.approx(1.0)
    for low, high in zip(("p5", "p25", "p50", "p75"), ("p25", "p50", "p75", "p95"), strict=True):
        assert all(a <= b + 1e-12 for a, b in zip(fan[low], fan[high], strict=True))
    assert risk["method"]["seed"] == 7
    assert "not a forecast" in risk["max_drawdown"]["p50"]["note"]


def test_drawdown_risk_riskier_series_draws_down_more() -> None:
    returns = _daily_returns()
    calm = analytics.drawdown_risk(returns, periods_per_year=252, samples=500, seed=1)
    wild = analytics.drawdown_risk(returns * 3, periods_per_year=252, samples=500, seed=1)
    assert _value(wild["max_drawdown"]["p95"]) > _value(calm["max_drawdown"]["p95"])


def test_drawdown_risk_hand_checked_constant_loss() -> None:
    # Every period loses 1 %, plus one flat period so the variance is not zero:
    # over 10 periods the drawdown is at least 1 - 0.99**9 and at most 1 - 0.99**10.
    values = [-0.01] * 40 + [0.0]
    risk = analytics.drawdown_risk(values, periods_per_year=10, samples=200, seed=0)
    p50 = _value(risk["max_drawdown"]["p50"])
    assert 1 - 0.99**9 - 1e-9 <= p50 <= 1 - 0.99**10 + 1e-9
    assert _value(risk["probability_drawdown_at_least"]["0.10"]) == 0.0


def test_drawdown_risk_caps_resampled_cells() -> None:
    returns = _daily_returns(200)
    risk = analytics.drawdown_risk(returns, periods_per_year=100_000, samples=5000, seed=0)
    assert risk["method"]["samples"] < 5000
    assert risk["method"]["samples_requested"] == 5000


def test_drawdown_risk_too_short_is_not_measured() -> None:
    risk = analytics.drawdown_risk([0.01, -0.01] * 5, periods_per_year=252)
    assert risk["max_drawdown"]["p95"]["evidence"] == "NOT_MEASURED"
    assert risk["fan"] is None
    json.dumps(risk, allow_nan=False)


# --- challenge simulator -------------------------------------------------------


def _rules(**overrides: object) -> ChallengeRules:
    base = get_preset("generic-2step-phase1").to_dict()
    base.update({"key": "test", "notes": ("test",)})
    base.update(overrides)
    base["notes"] = tuple(base["notes"])
    return ChallengeRules(**base)


def _probabilities(result: dict) -> dict[str, float]:
    return {key: _value(entry) for key, entry in result["probability"].items()}


def test_challenge_probabilities_sum_to_one_and_are_deterministic() -> None:
    returns = _daily_returns(500)
    result = analytics.simulate_challenge(returns, PRESETS["ftmo-2step-phase1"], seed=3)
    again = analytics.simulate_challenge(returns, PRESETS["ftmo-2step-phase1"], seed=3)
    assert json.dumps(result, allow_nan=False) == json.dumps(again, allow_nan=False)
    probabilities = _probabilities(result)
    assert set(probabilities) == {"pass", "fail_daily_loss", "fail_total_loss", "unfinished"}
    assert sum(probabilities.values()) == pytest.approx(1.0)
    low = _value(result["pass_probability_ci95"]["low"])
    high = _value(result["pass_probability_ci95"]["high"])
    assert low <= probabilities["pass"] <= high
    days = [_value(result["days_to_target"][k]) for k in ("p25", "p50", "p75")]
    assert days == sorted(days) and days[0] >= 4
    assert result["rules"]["source_url"].startswith("https://ftmo.com/")


def test_challenge_steady_gain_reaches_target_on_the_right_day() -> None:
    # +1 % a day with one flat day in the pool: target 10 % needs 10 gaining days.
    values = [0.01] * 60 + [0.0]
    result = analytics.simulate_challenge(values, _rules(), samples=300, seed=0)
    assert _probabilities(result)["pass"] == pytest.approx(1.0)
    assert 10 <= _value(result["days_to_target"]["p50"]) <= 12


def test_challenge_minimum_days_delays_the_target() -> None:
    values = [0.2] * 40 + [0.0]
    result = analytics.simulate_challenge(values, _rules(min_trading_days=6), samples=200, seed=0)
    assert _probabilities(result)["pass"] == pytest.approx(1.0)
    assert _value(result["days_to_target"]["p25"]) >= 6


def test_challenge_daily_and_total_breaches() -> None:
    daily_crash = [0.001] * 40 + [-0.06]
    result = analytics.simulate_challenge(
        daily_crash, _rules(), samples=500, seed=1, block_size=1.0
    )
    probabilities = _probabilities(result)
    assert probabilities["fail_daily_loss"] > 0.5
    assert probabilities["fail_total_loss"] == 0.0

    slow_bleed = [-0.004] * 40 + [-0.003]
    result = analytics.simulate_challenge(slow_bleed, _rules(), samples=200, seed=1)
    probabilities = _probabilities(result)
    assert probabilities["fail_total_loss"] == pytest.approx(1.0)
    assert result["days_to_target"]["p50"]["evidence"] == "NOT_MEASURED"


def test_challenge_daily_basis_changes_the_floor() -> None:
    # After gaining, a 5 %-of-start-of-day floor is wider in money than 5 % of
    # the initial balance, so a -5.2 % day on a balance of 1.08 breaches the
    # initial-balance rule (loss 0.056 > 0.05) and the start-of-day rule too;
    # a -4.8 % day breaches only the initial-balance rule (0.0518 > 0.05).
    ramp = [0.02, 0.02, 0.02, 0.02]
    for crash, initial_breaches, start_breaches in ((-0.048, True, False), (-0.052, True, True)):
        path = ramp + [crash]
        for basis, expected in (
            ("initial_balance", initial_breaches),
            ("start_of_day", start_breaches),
        ):
            rules = _rules(daily_loss_basis=basis, profit_target=0.5, min_trading_days=0)
            result = analytics.simulate_challenge(
                path * 8, rules, samples=50, seed=0, block_size=10_000, max_days=5
            )
            fail = _probabilities(result)["fail_daily_loss"]
            assert (fail > 0) == expected, (crash, basis, fail)


def test_challenge_trailing_floor_is_stricter_than_static() -> None:
    returns = _daily_returns(500) * 2
    static = analytics.simulate_challenge(
        returns, _rules(max_daily_loss=None, daily_loss_basis="none"), seed=2
    )
    trailing = analytics.simulate_challenge(
        returns,
        _rules(max_daily_loss=None, daily_loss_basis="none", total_loss_type="trailing_eod"),
        seed=2,
    )
    locked = analytics.simulate_challenge(
        returns,
        _rules(max_daily_loss=None, daily_loss_basis="none", total_loss_type="trailing_eod_lock"),
        seed=2,
    )
    fail = {
        name: _probabilities(r)["fail_total_loss"]
        for name, r in (("static", static), ("trailing", trailing), ("locked", locked))
    }
    assert fail["static"] <= fail["locked"] <= fail["trailing"]
    assert fail["trailing"] > fail["static"]


def test_challenge_time_limit_leaves_paths_unfinished() -> None:
    values = [0.001] * 40 + [0.0]
    result = analytics.simulate_challenge(values, _rules(time_limit_days=30), samples=100, seed=0)
    assert _probabilities(result)["unfinished"] == pytest.approx(1.0)
    assert result["method"]["horizon_business_days"] == 21


def test_challenge_too_short_is_not_measured() -> None:
    result = analytics.simulate_challenge([0.01, -0.01], PRESETS["ftmo-1step"])
    assert result["probability"]["pass"]["evidence"] == "NOT_MEASURED"
    json.dumps(result, allow_nan=False)


def test_daily_returns_from_intraday_equity() -> None:
    stamps = pd.to_datetime(
        ["2024-01-01 10:00", "2024-01-01 20:00", "2024-01-02 09:00", "2024-01-03 23:00"], utc=True
    )
    frame = pd.DataFrame({"timestamp": stamps, "equity": [100.0, 110.0, 99.0, 121.0]})
    daily = analytics.daily_returns_from_equity(frame)
    assert list(daily.round(6)) == [round(99 / 110 - 1, 6), round(121 / 99 - 1, 6)]


# --- wording ---------------------------------------------------------------------


def test_assumptions_and_questions_pass_the_guard_in_both_languages() -> None:
    _assert_clean(analytics.RISK_ASSUMPTIONS)
    _assert_clean(analytics.CHALLENGE_ASSUMPTIONS)
    every_flag = [
        "MARTINGALE_SIZING",
        "GRID_AVERAGING",
        "NO_STOP_EVIDENCE",
        "NEGATIVE_PAYOFF_HIGH_WINRATE",
        "MAD_SPIKES",
        "ZERO_DECLARED_COSTS",
    ]
    questions = analytics.vendor_questions(
        every_flag,
        has_trades=False,
        trials_measured=False,
        has_out_of_sample=False,
        has_costs=False,
        balance_only=True,
    )
    assert len(questions) == 12
    _assert_clean(questions)
    for preset in PRESETS.values():
        _assert_clean(preset.to_dict())


def test_vendor_questions_follow_flags_and_missing_inputs() -> None:
    minimal = analytics.vendor_questions(
        [],
        has_trades=True,
        trials_measured=True,
        has_out_of_sample=True,
        has_costs=True,
        balance_only=False,
    )
    assert [q["code"] for q in minimal] == ["live_record", "modelling"]
    assert "6" in minimal[0]["es"]

    flagged = analytics.vendor_questions(
        ["MARTINGALE_SIZING", "UNKNOWN_CODE"],
        has_trades=True,
        trials_measured=False,
        has_out_of_sample=True,
        has_costs=True,
        balance_only=False,
        min_track_record_months=17.2,
    )
    assert [q["code"] for q in flagged] == ["live_record", "modelling", "trials", "martingale"]
    assert "18" in flagged[0]["en"]
    assert all(q["es"] and q["en"] for q in flagged)
