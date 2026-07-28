"""Small-capital feasibility, bar observability, and the acquisition handoff."""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.v9.acquisition import (
    ACQUISITION_NOT_MEASURED,
    DEFAULT_SAFETY_LAG_MS,
    StampedBar,
    TimingError,
    bar_is_complete,
    discard_incomplete_bars,
    evaluate_acquisition,
    operator_runbook,
    value_settlements_at_observation,
)
from quant_trade.v9.margin import InstrumentRisk, RiskTier
from quant_trade.v9.small_capital import (
    DEFAULT_CAPITAL_LADDER,
    RUIN_DRAWDOWN,
    STATUS_INSUFFICIENT,
    build_feasibility_curve,
    evaluate_capital_scenario,
)

HOUR_MS = 3_600_000
BASE_MS = 1_700_000_000_000


# --- bar observability ----------------------------------------------------------------


def test_a_bar_observed_before_its_close_is_rejected() -> None:
    with pytest.raises(TimingError, match="its close has not happened yet"):
        StampedBar(
            bar_start_ms=BASE_MS,
            bar_end_ms=BASE_MS + HOUR_MS,
            observed_at_ms=BASE_MS + 60_000,
            close=100.0,
            high=101.0,
            low=99.0,
        )


def test_an_incomplete_bar_is_discarded_with_its_reason() -> None:
    """Venues publish the forming candle on the same endpoint as closed ones."""
    server_time = BASE_MS + 3 * HOUR_MS
    bars = [
        StampedBar(BASE_MS, BASE_MS + HOUR_MS, BASE_MS + HOUR_MS, 100.0, 101.0, 99.0),
        StampedBar(
            BASE_MS + 2 * HOUR_MS,
            BASE_MS + 3 * HOUR_MS,
            BASE_MS + 3 * HOUR_MS,
            100.0,
            101.0,
            99.0,
        ),
    ]
    result = discard_incomplete_bars(bars, server_time_ms=server_time)
    assert len(result.kept) == 1
    assert len(result.discarded) == 1
    assert "may still be forming" in result.discarded[0]["reason"]


def test_a_bar_well_inside_the_safety_lag_is_kept() -> None:
    assert bar_is_complete(
        BASE_MS, server_time_ms=BASE_MS + 10 * HOUR_MS, safety_lag_ms=DEFAULT_SAFETY_LAG_MS
    )
    assert not bar_is_complete(BASE_MS, server_time_ms=BASE_MS + 1_000)


def test_funding_is_valued_at_the_mark_observable_when_it_settled() -> None:
    """Reaching forward to the next hour's close is the leak this prevents."""
    marks = [
        StampedBar(
            BASE_MS + i * HOUR_MS,
            BASE_MS + (i + 1) * HOUR_MS,
            BASE_MS + (i + 1) * HOUR_MS,
            close=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
        )
        for i in range(5)
    ]
    # Settlement lands 30 minutes into the third bar.
    settled_at = BASE_MS + 2 * HOUR_MS + 1_800_000
    valued, problems = value_settlements_at_observation([(settled_at, 0.0003)], marks)
    assert problems == []
    assert len(valued) == 1
    # The mark used must have been observable BEFORE the settlement.
    assert valued[0].mark_observed_at_ms <= settled_at
    assert valued[0].mark == 101.0  # the bar that closed at T+2h, not T+3h


def test_a_settlement_before_any_observable_mark_is_reported_not_guessed() -> None:
    marks = [
        StampedBar(
            BASE_MS + 5 * HOUR_MS,
            BASE_MS + 6 * HOUR_MS,
            BASE_MS + 6 * HOUR_MS,
            100.0,
            101.0,
            99.0,
        )
    ]
    valued, problems = value_settlements_at_observation([(BASE_MS, 0.0003)], marks)
    assert valued == []
    assert any("cannot be valued without reaching forward" in p for p in problems)


# --- acquisition handoff ----------------------------------------------------------------


def test_a_missing_dataset_is_not_measured_not_no_edge(tmp_path: Path) -> None:
    status = evaluate_acquisition(
        evidence_root=tmp_path,
        since_utc="2024-07-28",
        until_utc="2026-07-27",
        min_days=730.0,
        min_settlements=1_000,
    )
    assert status.state == ACQUISITION_NOT_MEASURED
    assert not status.to_dict()["measured"]
    assert any("NOT_MEASURED, never NO_EDGE_FOUND" in n for n in status.notes)


def test_the_handoff_carries_runnable_commands(tmp_path: Path) -> None:
    status = evaluate_acquisition(
        evidence_root=tmp_path,
        since_utc="2024-07-28",
        until_utc="2026-07-27",
        min_days=730.0,
        min_settlements=1_000,
    )
    joined = "\n".join(status.operator_commands)
    assert "quant-trade v8 evidence-backfill --venue bybit" in joined
    assert "quant-trade v8 evidence-backfill --venue okx" in joined
    assert "quant-trade v8 evidence-pack" in joined
    assert status.import_command.startswith("quant-trade v8 evidence-verify")


def test_the_runbook_never_asks_for_a_secret() -> None:
    joined = "\n".join(operator_runbook(since_utc="2024-01-01", until_utc="2026-01-01"))
    assert "NO withdraw" in joined
    assert "keep only the response bytes" in joined
    for banned in ("api_secret", "passphrase=", "--key", "--secret"):
        assert banned not in joined


# --- capital feasibility -------------------------------------------------------------------


def _risk(**overrides) -> InstrumentRisk:
    payload = {
        "venue": "bybit",
        "instrument": "BTCUSDT",
        "tiers": (RiskTier(1_000_000.0, 0.10, 0.005),),
        "min_order_qty": 0.001,
        "qty_step": 0.001,
        "tick_size": 0.1,
        "min_notional_usd": 5.0,
    }
    payload.update(overrides)
    return InstrumentRisk(**payload)


def _scenario(capital: float, **overrides):
    payload = {
        "risk": _risk(),
        "price": 64_000.0,
        "spot_taker_bps": 10.0,
        "perp_taker_bps": 5.5,
    }
    payload.update(overrides)
    return evaluate_capital_scenario(capital, **payload)


def test_capital_too_small_for_the_lot_step_is_refused() -> None:
    scenario = _scenario(5.0)
    assert scenario.status == STATUS_INSUFFICIENT
    assert scenario.binding_constraint == "lot_step"
    assert "below the venue lot step" in scenario.problems[0]


def test_capital_below_the_minimum_notional_is_refused() -> None:
    # $200 clears the lot step (0.002 BTC) but buys only ~$128 of notional.
    scenario = _scenario(200.0, risk=_risk(min_notional_usd=500.0))
    assert scenario.status == STATUS_INSUFFICIENT
    assert scenario.binding_constraint == "min_notional"


def test_a_fee_floor_that_eats_the_capital_is_refused() -> None:
    scenario = _scenario(100.0, fee_floor_usd=5.0)
    assert scenario.status == STATUS_INSUFFICIENT
    assert scenario.binding_constraint == "fee_floor"
    assert "cannot recover its own frictions" in scenario.problems[0]


def test_a_workable_balance_reports_the_executable_size() -> None:
    scenario = _scenario(1_000.0)
    assert scenario.executable
    assert scenario.binding_constraint == "none"
    assert scenario.quantity > 0
    assert scenario.quantity == pytest.approx(_risk().round_quantity(scenario.quantity))
    assert scenario.executable_notional_usd > 0
    assert scenario.total_capital_committed_usd <= 1_000.0


def test_committed_capital_exceeds_the_notional_for_a_spot_carry() -> None:
    """Spot inventory plus margin plus buffer is more than the notional."""
    scenario = _scenario(10_000.0)
    assert scenario.total_capital_committed_usd > scenario.executable_notional_usd
    assert 0 < scenario.capital_efficiency < 1


def test_return_is_reported_on_committed_capital_not_notional() -> None:
    import numpy as np

    rng = np.random.default_rng(11)
    oos = list(rng.normal(0.0001, 0.001, 400))
    curve = build_feasibility_curve(
        risk=_risk(),
        price=64_000.0,
        spot_taker_bps=10.0,
        perp_taker_bps=5.5,
        ladder=(10_000.0,),
        oos_returns=oos,
    )
    scenario = curve.scenarios[0]
    assert scenario.executable
    # Leverage below 1 means the reported return is scaled DOWN from notional.
    leverage = scenario.executable_notional_usd / scenario.total_capital_committed_usd
    assert leverage < 1.0
    assert scenario.p50_return_on_capital is not None


def test_the_fee_floor_raises_break_even_for_the_smallest_balance() -> None:
    """The economic point of the whole analysis."""
    small = _scenario(100.0, fee_floor_usd=0.10)
    large = _scenario(10_000.0, fee_floor_usd=0.10)
    assert small.executable and large.executable
    assert small.break_even_funding_per_interval is not None
    assert large.break_even_funding_per_interval is not None
    assert small.break_even_funding_per_interval > large.break_even_funding_per_interval


def test_the_curve_reports_the_minimum_executable_capital() -> None:
    curve = build_feasibility_curve(
        risk=_risk(min_notional_usd=500.0),
        price=64_000.0,
        spot_taker_bps=10.0,
        perp_taker_bps=5.5,
    )
    minimum = curve.minimum_executable_capital_usd
    assert minimum is not None
    assert minimum in DEFAULT_CAPITAL_LADDER
    for scenario in curve.scenarios:
        if scenario.starting_capital_usd < minimum:
            assert not scenario.executable


def test_a_curve_with_no_executable_rung_says_so() -> None:
    curve = build_feasibility_curve(
        risk=_risk(min_notional_usd=1_000_000.0),
        price=64_000.0,
        spot_taker_bps=10.0,
        perp_taker_bps=5.5,
    )
    assert curve.minimum_executable_capital_usd is None
    assert all(not s.executable for s in curve.scenarios)


def test_the_distribution_is_a_spread_not_a_projection() -> None:
    import numpy as np

    rng = np.random.default_rng(5)
    oos = list(rng.normal(0.0, 0.004, 600))
    curve = build_feasibility_curve(
        risk=_risk(),
        price=64_000.0,
        spot_taker_bps=10.0,
        perp_taker_bps=5.5,
        ladder=(5_000.0,),
        oos_returns=oos,
    )
    scenario = curve.scenarios[0]
    assert scenario.p05_return_on_capital is not None
    assert (
        scenario.p05_return_on_capital
        <= scenario.p50_return_on_capital
        <= scenario.p95_return_on_capital
    )
    assert 0.0 <= scenario.probability_of_loss <= 1.0
    assert 0.0 <= scenario.probability_of_ruin <= 1.0
    assert scenario.max_drawdown <= 0.0


def test_the_distribution_is_deterministic_for_a_fixed_series() -> None:
    import numpy as np

    rng = np.random.default_rng(9)
    oos = list(rng.normal(0.0001, 0.002, 300))
    first, second = (
        build_feasibility_curve(
            risk=_risk(),
            price=64_000.0,
            spot_taker_bps=10.0,
            perp_taker_bps=5.5,
            ladder=(1_000.0,),
            oos_returns=oos,
        ).scenarios[0]
        for _ in range(2)
    )
    assert first.p05_return_on_capital == second.p05_return_on_capital
    assert first.probability_of_ruin == second.probability_of_ruin


def test_a_ruinous_series_produces_a_ruin_probability() -> None:
    losing = [-0.02] * 200
    curve = build_feasibility_curve(
        risk=_risk(),
        price=64_000.0,
        spot_taker_bps=10.0,
        perp_taker_bps=5.5,
        ladder=(5_000.0,),
        oos_returns=losing,
    )
    scenario = curve.scenarios[0]
    assert scenario.probability_of_loss == pytest.approx(1.0)
    assert scenario.max_drawdown <= -RUIN_DRAWDOWN


def test_zero_capital_is_refused() -> None:
    scenario = _scenario(0.0)
    assert scenario.status == STATUS_INSUFFICIENT
    assert "must be > 0" in scenario.problems[0]


def test_the_artifact_states_the_return_denominator() -> None:
    curve = build_feasibility_curve(
        risk=_risk(), price=64_000.0, spot_taker_bps=10.0, perp_taker_bps=5.5
    )
    payload = curve.to_dict()
    assert payload["artifact"] == "SMALL_CAPITAL_FEASIBILITY"
    assert "TOTAL immobilised capital" in payload["note"]
    assert "no deterministic projection" in payload["note"]
    assert "ruin_definition" in payload
