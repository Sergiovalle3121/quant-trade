from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from quant_trade.research.prospective_weekly_momentum import (
    FINAL_LAST_DECISION,
    FINAL_OBSERVATION_END,
    PRIMARY_LAST_DECISION,
    PRIMARY_OBSERVATION_END,
    PROSPECTIVE_FIRST_DECISION,
    PROSPECTIVE_FIRST_EXECUTION,
    REVEAL_NOT_BEFORE,
    STRATEGY_ID,
    WeeklyMomentumError,
    WeeklyMomentumSpec,
    development_weekly_momentum_targets,
    load_weekly_momentum_spec,
    prospective_weekly_momentum_targets,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "experiments" / "binance_btc_weekly_momentum_1w_long_cash_v1.yaml"


def _spec() -> WeeklyMomentumSpec:
    return load_weekly_momentum_spec(CONFIG)


def _row(timestamp: str | pd.Timestamp, close: float, symbol: str = "BTCUSDT") -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000.0,
    }


def _panel(prices: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([_row(timestamp, close) for timestamp, close in prices.items()])


def _development_transitions() -> pd.DataFrame:
    return _panel(
        {
            "2023-01-01": 100.0,
            "2023-01-08": 110.0,
            "2023-01-15": 120.0,
            "2023-01-22": 100.0,
            "2023-01-29": 100.0,
        }
    )


def test_yaml_loads_exact_isolated_research_only_campaign() -> None:
    spec = _spec()

    assert spec.strategy_id == STRATEGY_ID
    assert spec.symbol == "BTCUSDT"
    assert spec.trial_budget == 1
    assert spec.source_hypothesis["exact_replication"] is False
    assert spec.signal_policy["lookback_calendar_days"] == 7
    assert spec.development_window["evidence_end"] == "2023-11-28"
    assert spec.development_window["request_side_end_time_required"] is True
    assert spec.prospective_window["primary_decision_count"] == 104
    assert spec.prospective_window["total_decision_count"] == 156
    assert spec.prospective_window["interim_economic_reveal_allowed"] is False
    assert spec.promotion_blockers["pbo"] == "NOT_IDENTIFIABLE_SINGLE_TRIAL"
    assert spec.promotion_blockers["maximum_verdict_without_new_governance"] == (
        "INSUFFICIENT_EVIDENCE"
    )
    assert spec.authorization["generic_runner_enabled"] is False
    assert spec.authorization["strategy_registry_enabled"] is False
    assert spec.authorization["live_execution_enabled"] is False
    assert spec.authorization["real_money_authorized"] is False
    assert spec.seal() == "a1a896f4609e4c8283b114404f415d29f97404ed4a50e27cc8393029db8df910"


def test_dates_encode_104_plus_52_decisions_and_complete_outcome_weeks() -> None:
    spec = _spec()
    window = spec.prospective_window

    first = pd.Timestamp(PROSPECTIVE_FIRST_DECISION)
    primary_last = pd.Timestamp(PRIMARY_LAST_DECISION)
    final_last = pd.Timestamp(FINAL_LAST_DECISION)
    assert (primary_last - first).days // 7 + 1 == 104
    assert (final_last - first).days // 7 + 1 == 156
    assert pd.Timestamp(PROSPECTIVE_FIRST_EXECUTION) == first + pd.Timedelta(days=1)
    assert pd.Timestamp(PRIMARY_OBSERVATION_END) == primary_last + pd.Timedelta(days=7)
    assert pd.Timestamp(FINAL_OBSERVATION_END) == final_last + pd.Timedelta(days=7)
    assert pd.Timestamp(REVEAL_NOT_BEFORE) == pd.Timestamp(FINAL_OBSERVATION_END) + pd.Timedelta(
        days=1
    )
    assert window["extension_decision_count"] == 52


def test_spec_is_deeply_immutable_and_byte_tamper_is_rejected(tmp_path: Path) -> None:
    spec = _spec()
    with pytest.raises(TypeError):
        spec.signal_policy["lookback_calendar_days"] = 26  # type: ignore[index]

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["signal_policy"]["lookback_calendar_days"] = 26
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(WeeklyMomentumError, match="sealed weekly campaign"):
        load_weekly_momentum_spec(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trial_budget", 2),
        ("symbol", "ETHUSDT"),
        ("campaign_mode", "BACKTEST"),
    ],
)
def test_resealed_scalar_policy_changes_are_rejected(field: str, value: Any) -> None:
    payload = _spec().canonical_payload()
    payload[field] = value
    with pytest.raises(WeeklyMomentumError, match="sealed weekly campaign"):
        WeeklyMomentumSpec(**payload)


def test_weekly_return_is_exact_sunday_to_sunday_and_targets_are_sparse() -> None:
    targets = development_weekly_momentum_targets(
        _development_transitions(),
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-01-29",
    )

    assert list(targets["decision_timestamp"].dt.strftime("%Y-%m-%d")) == [
        "2023-01-08",
        "2023-01-22",
    ]
    assert list(targets["signal_state"]) == ["LONG", "CASH"]
    assert list(targets["target_weight"]) == [1.0, 0.0]
    assert targets.loc[0, "weekly_return"] == pytest.approx(0.10)
    assert targets.loc[1, "weekly_return"] == pytest.approx(100.0 / 120.0 - 1.0)
    assert list(targets["reference_timestamp"].dt.strftime("%Y-%m-%d")) == [
        "2023-01-01",
        "2023-01-15",
    ]


def test_zero_return_is_cash_and_missing_exact_week_never_falls_back() -> None:
    tie = development_weekly_momentum_targets(
        _panel({"2023-01-01": 100.0, "2023-01-08": 100.0}),
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-01-08",
    )
    assert list(tie["signal_state"]) == ["CASH"]

    missing = development_weekly_momentum_targets(
        _panel({"2023-01-01": 100.0, "2023-01-15": 200.0}),
        _spec(),
        decision_start="2023-01-15",
        decision_end="2023-01-15",
    )
    assert missing.empty


def test_non_sunday_bar_cannot_become_a_decision() -> None:
    targets = development_weekly_momentum_targets(
        _panel(
            {
                "2023-01-01": 100.0,
                "2023-01-08": 110.0,
                "2023-01-09": 1_000.0,
            }
        ),
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-01-15",
    )
    assert list(targets["decision_timestamp"].dt.strftime("%Y-%m-%d")) == ["2023-01-08"]


def test_every_intention_is_next_bar_non_executable_and_non_authorizing() -> None:
    targets = development_weekly_momentum_targets(
        _development_transitions(),
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-01-29",
    )

    assert bool(
        (
            targets["earliest_execution_timestamp"]
            == targets["decision_timestamp"] + pd.Timedelta(days=1)
        ).all()
    )
    assert bool((targets["earliest_execution_timestamp"] > targets["decision_timestamp"]).all())
    assert set(targets["execution_timing"]) == {"NEXT_DAILY_OPEN"}
    assert set(targets["order_intent"]) == {"SPARSE_TARGET_ONLY"}
    assert set(targets["strategy_spec_seal"]) == {_spec().seal()}
    assert set(targets["trial_number"]) == {1}
    assert not bool(targets["real_money_authorized"].any())
    assert "execution_price" not in targets


def test_targets_are_prefix_invariant_when_future_prices_are_appended() -> None:
    prefix = _development_transitions()
    extended = pd.concat(
        [prefix, _panel({"2023-02-05": 1_000.0, "2023-02-12": 1.0})],
        ignore_index=True,
    )
    before = development_weekly_momentum_targets(
        prefix,
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-01-29",
    )
    after = development_weekly_momentum_targets(
        extended,
        _spec(),
        decision_start="2023-01-08",
        decision_end="2023-02-12",
    )
    cutoff = pd.Timestamp("2023-01-29", tz="UTC")
    pd.testing.assert_frame_equal(
        before,
        after[after["decision_timestamp"] <= cutoff].reset_index(drop=True),
    )


def test_development_rejects_ranges_or_rows_beyond_2023_11_28() -> None:
    panel = _panel({"2023-11-19": 100.0, "2023-11-26": 110.0})
    with pytest.raises(WeeklyMomentumError, match="sealed window"):
        development_weekly_momentum_targets(
            panel,
            _spec(),
            decision_start="2023-11-26",
            decision_end="2023-12-03",
        )

    contaminated = pd.concat([panel, _panel({"2023-11-29": 120.0})], ignore_index=True)
    with pytest.raises(WeeklyMomentumError, match="evidence window"):
        development_weekly_momentum_targets(
            contaminated,
            _spec(),
            decision_start="2023-11-26",
            decision_end="2023-11-26",
        )


def test_prospective_campaign_starts_from_2026_observations_only() -> None:
    targets = prospective_weekly_momentum_targets(
        _panel({"2026-08-23": 100.0, "2026-08-30": 110.0}),
        _spec(),
    )
    assert list(targets["decision_timestamp"].dt.strftime("%Y-%m-%d")) == ["2026-08-30"]
    assert list(targets["earliest_execution_timestamp"].dt.strftime("%Y-%m-%d")) == ["2026-08-31"]

    with pytest.raises(WeeklyMomentumError, match="observation window"):
        prospective_weekly_momentum_targets(
            _panel(
                {
                    "2026-08-16": 90.0,
                    "2026-08-23": 100.0,
                    "2026-08-30": 110.0,
                }
            ),
            _spec(),
        )


def test_wrong_symbol_intraday_data_and_enabled_live_use_fail_closed() -> None:
    with pytest.raises(WeeklyMomentumError, match="symbol must be exactly"):
        development_weekly_momentum_targets(
            pd.DataFrame([_row("2023-01-01", 100.0, "ETHUSDT")]),
            _spec(),
            decision_start="2023-01-01",
            decision_end="2023-01-01",
        )
    with pytest.raises(WeeklyMomentumError, match="UTC daily bars"):
        development_weekly_momentum_targets(
            _panel({"2023-01-01T12:00:00Z": 100.0}),
            _spec(),
            decision_start="2023-01-01",
            decision_end="2023-01-01",
        )

    authorization = dict(_spec().authorization)
    authorization["live_execution_enabled"] = True
    with pytest.raises(WeeklyMomentumError, match="sealed weekly campaign"):
        replace(_spec(), authorization=authorization)
