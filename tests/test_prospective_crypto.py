from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from quant_trade.research.prospective_crypto import (
    HOLDOUT_END,
    PRIMARY_HOLDOUT_END,
    ProspectiveCryptoError,
    ProspectiveStrategySpec,
    development_tsmom_targets,
    load_prospective_strategy_spec,
    prospective_tsmom_targets,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "experiments" / "binance_btc_eth_tsmom_long_cash_v1.yaml"


def _spec() -> ProspectiveStrategySpec:
    return load_prospective_strategy_spec(CONFIG)


def _row(timestamp: str | pd.Timestamp, symbol: str, close: float) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000.0,
    }


def _monthly_panel(
    prices: dict[str, dict[str, float]],
    *,
    extra_dates: tuple[str, ...] = (),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol, monthly_prices in prices.items():
        for timestamp, close in monthly_prices.items():
            rows.append(_row(timestamp, symbol, close))
        for timestamp in extra_dates:
            rows.append(_row(timestamp, symbol, monthly_prices[max(monthly_prices)]))
    return pd.DataFrame(rows)


def _transition_panel() -> pd.DataFrame:
    return _monthly_panel(
        {
            "BTCUSDT": {
                "2025-08-31": 100.0,
                "2025-09-30": 100.0,
                "2025-10-31": 200.0,
                "2026-08-31": 110.0,
                "2026-09-30": 150.0,
                "2026-10-31": 100.0,
            },
            "ETHUSDT": {
                "2025-08-31": 50.0,
                "2025-09-30": 50.0,
                "2025-10-31": 50.0,
                "2026-08-31": 60.0,
                "2026-09-30": 70.0,
                "2026-10-31": 80.0,
            },
        }
    )


def _development_transition_panel() -> pd.DataFrame:
    panel = _transition_panel()
    panel["timestamp"] = (
        panel["timestamp"].str.replace("2025-", "2022-").str.replace("2026-", "2023-")
    )
    return panel


def test_yaml_loads_exact_sealed_prospective_campaign() -> None:
    spec = _spec()

    assert spec.strategy_id == "binance_btc_eth_tsmom_long_cash_v1"
    assert spec.venue == "Binance"
    assert spec.market == "Spot"
    assert tuple(spec.symbols) == ("BTCUSDT", "ETHUSDT")
    assert dict(spec.sleeves) == {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    assert spec.trial_budget == 1
    assert spec.development_evidence_start == "2018-08-31"
    assert spec.development_evidence_end == "2023-11-28"
    assert spec.primary_holdout_end == PRIMARY_HOLDOUT_END
    assert spec.holdout_end == HOLDOUT_END
    assert spec.reveal_policy["interim_economic_reveal_at_primary_end"] is False
    assert spec.reveal_policy["default_extension_without_interim_reveal"] is True
    assert spec.reveal_policy["reveal_not_before"] == "2029-09-01"
    assert len(spec.benchmarks) == 3
    assert spec.cost_policy["fee_floor_bps_per_side"] == 10.0
    assert spec.cost_policy["friction_floor_bps_per_side"] == 5.0
    assert spec.cost_policy["stress_cost_multiplier"] == 2.0
    assert spec.development_falsification_policy == {
        "net_total_return_positive": True,
        "outperform_each_benchmark": True,
        "required_benchmark_ids": (
            "btc_usdt_buy_and_hold",
            "eth_usdt_buy_and_hold",
            "btc_eth_50_50_buy_and_hold",
        ),
        "contiguous_blocks": 4,
        "block_partition_method": "EQUAL_CONTIGUOUS_DAILY_OBSERVATIONS",
        "minimum_outperforming_blocks": 3,
        "block_outperformance_benchmark_ids": (
            "btc_usdt_buy_and_hold",
            "btc_eth_50_50_buy_and_hold",
        ),
        "max_drawdown_abs": 0.25,
        "stress_cost_multiplier": 2.0,
        "stress_fill_fraction": 0.5,
        "stress_total_return_min": 0.0,
    }
    assert spec.promotion_policy["psr_min"] == 0.95
    assert spec.promotion_policy["dsr_min"] == 0.95
    assert spec.promotion_policy["pbo_policy"] == "NOT_IDENTIFIABLE_SINGLE_TRIAL"
    assert spec.promotion_policy["mandatory_pbo_means_insufficient_evidence"] is True
    assert spec.promotion_policy["both_sleeves_positive_pnl"] is True
    assert spec.promotion_policy["max_positive_pnl_share_per_sleeve"] == 0.75
    assert spec.promotion_policy["capacity_multiple_of_proposed_capital_min"] == 2.0
    assert spec.promotion_policy["real_money_authorized"] is False
    assert spec.authorization["real_money_authorized"] is False
    assert spec.authorization["external_action_authorized"] is False
    assert len(spec.seal()) == 64


def test_spec_is_defensively_copied_deeply_immutable_and_fully_sealed() -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw.pop("seal")
    spec = ProspectiveStrategySpec(**raw)
    original_seal = spec.seal()

    raw["sleeves"]["BTCUSDT"] = 1.0
    raw["signal_policy"]["momentum_lookback_calendar_months"] = 1
    raw["benchmarks"][0]["symbol_weights"]["BTCUSDT"] = 0.0

    assert spec.sleeves["BTCUSDT"] == 0.5
    assert spec.signal_policy["momentum_lookback_calendar_months"] == 12
    assert spec.benchmarks[0]["symbol_weights"]["BTCUSDT"] == 1.0
    assert spec.seal() == original_seal
    with pytest.raises(TypeError):
        spec.sleeves["BTCUSDT"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.benchmarks[0]["symbol_weights"]["BTCUSDT"] = 0.0  # type: ignore[index]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("venue",), "Bybit"),
        (("symbols", 0), "BTCUSD"),
        (("signal_policy", "momentum_lookback_calendar_months"), 11),
        (("signal_policy", "rebalance_drift"), True),
        (("trial_budget",), 2),
        (("development_evidence_start",), "2018-09-01"),
        (("development_evidence_end",), "2023-11-29"),
        (("primary_holdout_end",), "2028-07-31"),
        (("reveal_policy", "interim_economic_reveal_at_primary_end"), True),
        (("cost_policy", "fee_floor_bps_per_side"), 9.99),
        (("cost_policy", "stress_cost_multiplier"), 1.0),
        (("development_falsification_policy", "net_total_return_positive"), False),
        (("development_falsification_policy", "stress_fill_fraction"), 0.75),
        (("development_falsification_policy", "contiguous_blocks"), 5),
        (("development_falsification_policy", "block_partition_method"), "CALENDAR_YEARS"),
        (("development_falsification_policy", "minimum_outperforming_blocks"), 2),
        (("promotion_policy", "psr_min"), 0.90),
        (("promotion_policy", "pbo_policy"), "IGNORE_SINGLE_TRIAL"),
        (("promotion_policy", "both_sleeves_positive_pnl"), False),
        (("promotion_policy", "real_money_authorized"), True),
        (("safety_policy", "leverage_allowed"), True),
        (("authorization", "real_money_authorized"), True),
    ],
)
def test_resealed_policy_tampering_is_rejected(path: tuple[Any, ...], value: Any) -> None:
    spec = _spec()
    payload = spec.canonical_payload()
    cursor: Any = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(ProspectiveCryptoError, match="sealed prospective campaign"):
        ProspectiveStrategySpec(**payload)


def test_loader_rejects_byte_level_tamper_with_old_seal(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["sleeves"]["BTCUSDT"] = 0.49
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    # The economic constraint fails even before a stale seal could be trusted.
    with pytest.raises(ProspectiveCryptoError):
        load_prospective_strategy_spec(path)


def test_loader_rejects_unknown_missing_or_malformed_seal(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["post_hoc_parameter"] = 7
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ProspectiveCryptoError, match="fields mismatch"):
        load_prospective_strategy_spec(unknown)

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw.pop("holdout_end")
    missing = tmp_path / "missing.yaml"
    missing.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ProspectiveCryptoError, match="fields mismatch"):
        load_prospective_strategy_spec(missing)

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw["seal"] = "A" * 64
    uppercase = tmp_path / "uppercase.yaml"
    uppercase.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ProspectiveCryptoError, match="lowercase hexadecimal"):
        load_prospective_strategy_spec(uppercase)


def test_signal_uses_twelve_calendar_months_not_365_rows() -> None:
    # Only thirteen sparse monthly observations per symbol are present.  A
    # 365-row shift cannot produce a signal; the calendar-month contract can.
    dates = pd.date_range("2025-08-31", "2026-08-31", freq="ME", tz="UTC")
    prices: dict[str, dict[str, float]] = {}
    for symbol, initial, final in (
        ("BTCUSDT", 100.0, 110.0),
        ("ETHUSDT", 50.0, 45.0),
    ):
        values = {timestamp.isoformat(): initial for timestamp in dates}
        values[dates[-1].isoformat()] = final
        prices[symbol] = values

    targets = prospective_tsmom_targets(_monthly_panel(prices), _spec())

    assert len(targets) == 2
    by_symbol = targets.set_index("symbol")
    assert by_symbol.loc["BTCUSDT", "signal_state"] == "LONG"
    assert by_symbol.loc["BTCUSDT", "target_weight"] == 0.5
    assert by_symbol.loc["ETHUSDT", "signal_state"] == "CASH"
    assert by_symbol.loc["ETHUSDT", "target_weight"] == 0.0
    assert set(targets["reference_month"]) == {"2025-08"}


def test_missing_reference_month_does_not_fall_back_to_stale_price() -> None:
    panel = _monthly_panel(
        {
            "BTCUSDT": {"2025-07-31": 100.0, "2026-08-31": 200.0},
            "ETHUSDT": {"2025-07-31": 50.0, "2026-08-31": 100.0},
        }
    )

    targets = prospective_tsmom_targets(panel, _spec())

    assert targets.empty


def test_only_state_changes_emit_and_long_sleeve_is_not_rebalanced_for_drift() -> None:
    targets = prospective_tsmom_targets(_transition_panel(), _spec())
    btc = targets[targets["symbol"] == "BTCUSDT"].reset_index(drop=True)
    eth = targets[targets["symbol"] == "ETHUSDT"].reset_index(drop=True)

    assert list(btc["decision_timestamp"].dt.strftime("%Y-%m-%d")) == [
        "2026-08-31",
        "2026-10-31",
    ]
    assert list(btc["signal_state"]) == ["LONG", "CASH"]
    assert list(btc["target_weight"]) == [0.5, 0.0]
    # ETH changed in price during September but stayed LONG: no target was
    # emitted to restore its drifted market weight to 50%.
    assert list(eth["decision_timestamp"].dt.strftime("%Y-%m-%d")) == ["2026-08-31"]


def test_current_partial_month_never_becomes_a_month_end_decision() -> None:
    panel = pd.concat(
        [
            _transition_panel(),
            pd.DataFrame(
                [
                    _row("2026-11-15", "BTCUSDT", 1_000.0),
                    _row("2026-11-15", "ETHUSDT", 1_000.0),
                ]
            ),
        ],
        ignore_index=True,
    )

    targets = prospective_tsmom_targets(panel, _spec())

    assert not bool((targets["decision_timestamp"] == pd.Timestamp("2026-11-15", tz="UTC")).any())


def test_targets_are_prefix_invariant_when_future_prices_are_appended() -> None:
    prefix = _transition_panel()
    future = pd.DataFrame(
        [
            _row("2026-11-30", "BTCUSDT", 10_000.0),
            _row("2026-11-30", "ETHUSDT", 1.0),
            _row("2027-08-31", "BTCUSDT", 1.0),
            _row("2027-08-31", "ETHUSDT", 10_000.0),
        ]
    )
    prefix_targets = prospective_tsmom_targets(prefix, _spec())
    extended_targets = prospective_tsmom_targets(
        pd.concat([prefix, future], ignore_index=True), _spec()
    )
    cutoff = pd.Timestamp("2026-10-31", tz="UTC")

    pd.testing.assert_frame_equal(
        prefix_targets,
        extended_targets[extended_targets["decision_timestamp"] <= cutoff].reset_index(drop=True),
    )


def test_development_and_prospective_apis_share_identical_signal_logic() -> None:
    development_panel = _development_transition_panel()
    development = development_tsmom_targets(
        development_panel,
        _spec(),
        decision_start="2023-08-31",
        decision_end="2023-10-31",
    )
    prospective = prospective_tsmom_targets(_transition_panel(), _spec())

    pd.testing.assert_frame_equal(
        development[["symbol", "signal_state", "target_weight"]].reset_index(drop=True),
        prospective[["symbol", "signal_state", "target_weight"]].reset_index(drop=True),
    )


def test_development_api_is_prefix_invariant_and_cannot_leave_evidence_window() -> None:
    prefix = _development_transition_panel()
    appended = pd.concat(
        [
            prefix,
            pd.DataFrame(
                [
                    _row("2027-08-31", "BTCUSDT", 1.0),
                    _row("2027-08-31", "ETHUSDT", 10_000.0),
                ]
            ),
        ],
        ignore_index=True,
    )
    before = development_tsmom_targets(
        prefix,
        _spec(),
        decision_start="2023-08-31",
        decision_end="2023-10-31",
    )
    after = development_tsmom_targets(
        appended,
        _spec(),
        decision_start="2023-08-31",
        decision_end="2023-10-31",
    )
    pd.testing.assert_frame_equal(before, after)

    with pytest.raises(ProspectiveCryptoError, match="sealed evidence window"):
        development_tsmom_targets(
            prefix,
            _spec(),
            decision_start="2018-08-31",
            decision_end="2023-11-29",
        )
    with pytest.raises(ProspectiveCryptoError, match="sealed evidence window"):
        development_tsmom_targets(
            prefix,
            _spec(),
            decision_start="2018-08-30",
            decision_end="2023-11-28",
        )


def test_same_bar_execution_is_impossible_in_the_signal_contract() -> None:
    targets = prospective_tsmom_targets(_transition_panel(), _spec())

    assert not targets.empty
    assert bool((targets["earliest_execution_timestamp"] > targets["decision_timestamp"]).all())
    assert bool(
        (
            targets["earliest_execution_timestamp"]
            == targets["decision_timestamp"] + pd.Timedelta(days=1)
        ).all()
    )
    assert set(targets["execution_timing"]) == {"NEXT_DAILY_OPEN"}
    assert set(targets["order_intent"]) == {"SPARSE_TARGET_ONLY"}
    assert set(targets["strategy_id"]) == {"binance_btc_eth_tsmom_long_cash_v1"}
    assert set(targets["strategy_spec_seal"]) == {_spec().seal()}
    assert set(targets["trial_number"]) == {1}
    assert not bool(targets["real_money_authorized"].any())
    assert "execution_price" not in targets


def test_partial_month_end_or_non_daily_utc_data_fails_closed() -> None:
    partial = _transition_panel()
    partial = partial[~((partial["timestamp"] == "2026-09-30") & (partial["symbol"] == "ETHUSDT"))]
    targets = prospective_tsmom_targets(partial, _spec())
    assert "2026-09-30" not in set(targets["decision_timestamp"].dt.strftime("%Y-%m-%d"))

    intraday = _transition_panel()
    intraday["timestamp"] = pd.to_datetime(intraday["timestamp"], utc=True)
    intraday.loc[0, "timestamp"] = intraday.loc[0, "timestamp"] + pd.Timedelta(hours=12)
    with pytest.raises(ProspectiveCryptoError, match="UTC daily bars"):
        prospective_tsmom_targets(intraday, _spec())


def test_campaign_cannot_be_relabeled_or_enabled_for_live_use() -> None:
    spec = _spec()
    with pytest.raises(ProspectiveCryptoError):
        replace(spec, campaign_mode="BACKTEST")
    authorization = dict(spec.authorization)
    authorization["live_execution_enabled"] = True
    with pytest.raises(ProspectiveCryptoError):
        replace(spec, authorization=authorization)
