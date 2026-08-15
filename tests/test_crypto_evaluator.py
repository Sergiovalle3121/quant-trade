"""Causal execution and explicit market-event tests for the crypto evaluator."""

from __future__ import annotations

import pandas as pd
import pytest

from quant_trade.data.crypto_market_events import MarketEventEvidence, MarketEventLedger
from quant_trade.execution.bar_model import BarExecutionPolicy
from quant_trade.research.crypto_evaluator import (
    FORCED_EXIT,
    ExecutionLimits,
    btc_buy_and_hold_benchmark,
    evaluate,
)

MID_CAP = 500e6
DAYS = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]


def _panel(
    prices: dict[str, dict[str, float]],
    *,
    opens: dict[str, dict[str, float]] | None = None,
    events: dict[tuple[str, str], str] | None = None,
    tradable: dict[tuple[str, str], bool] | None = None,
    eligible: dict[tuple[str, str], bool] | None = None,
    volume: float = 10_000.0,
    market_cap: float = MID_CAP,
) -> pd.DataFrame:
    rows = []
    events = events or {}
    tradable = tradable or {}
    eligible = eligible or {}
    for symbol, series in prices.items():
        for day, price in series.items():
            rows.append(
                {
                    "timestamp": pd.Timestamp(day, tz="UTC"),
                    "symbol": symbol,
                    "venue": "bybit",
                    "open": (opens or {}).get(symbol, {}).get(day, price),
                    "high": price,
                    "low": price,
                    "close": price,
                    "mark_price": price,
                    "volume": volume,
                    "market_cap_usd": market_cap,
                    "eligible_to_open": eligible.get((day, symbol), True),
                    "tradable": tradable.get((day, symbol), True),
                    "data_status": "VALID",
                    "market_event": events.get((day, symbol), "NONE"),
                }
            )
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _weights(rows: list[tuple]) -> pd.DataFrame:
    records = []
    for row in rows:
        day, symbol, weight, *intent = row
        records.append(
            {
                "timestamp": pd.Timestamp(day, tz="UTC"),
                "symbol": symbol,
                "target_weight": weight,
                "order_intent": intent[0] if intent else "TARGET_PORTFOLIO",
            }
        )
    return pd.DataFrame(records)


def _market_event(
    *,
    timestamp: str,
    event: str,
    instrument_id: str = "CMC:7",
    recovery: float | None = None,
) -> MarketEventEvidence:
    return MarketEventEvidence(
        instrument_id=instrument_id,
        venue="bybit",
        event=event,
        effective_at_utc=timestamp,
        observed_at_utc=timestamp,
        source=f"Bybit explicit {event} evidence",
        source_sha256="b" * 64,
        terminal_recovery_price=recovery,
    )


def test_signal_at_t_cannot_fill_same_bar_and_uses_next_open() -> None:
    panel = _panel(
        {"CMC:7": {DAYS[0]: 10.0, DAYS[1]: 30.0, DAYS[2]: 30.0}},
        opens={"CMC:7": {DAYS[0]: 1.0, DAYS[1]: 20.0, DAYS[2]: 30.0}},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))

    execution = result.executions[0]
    assert execution.decision_timestamp.startswith(DAYS[0])
    assert execution.execution_timestamp.startswith(DAYS[1])
    assert execution.open_price == 20.0
    assert result.equity.iloc[0] == pytest.approx(1_000.0)


def test_empty_market_event_ledger_is_equivalent_to_no_events() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:3], [10.0, 11.0, 12.0], strict=True))})
    weights = _weights([(DAYS[0], "CMC:7", 1.0)])

    without_events = evaluate(panel, weights)
    empty_ledger = evaluate(panel, weights, market_events=MarketEventLedger.from_events([]))

    pd.testing.assert_series_equal(empty_ledger.equity, without_events.equity)
    assert [item.to_dict() for item in empty_ledger.executions] == [
        item.to_dict() for item in without_events.executions
    ]


def test_additional_latency_is_applied_after_the_mandatory_next_bar() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS, [10.0, 10.0, 10.0, 10.0], strict=True))})
    result = evaluate(
        panel,
        _weights([(DAYS[0], "CMC:7", 1.0)]),
        execution_policy=BarExecutionPolicy(additional_latency_bars=1),
    )
    assert result.executions[0].execution_timestamp.startswith(DAYS[2])


@pytest.mark.parametrize("event", ["GAP", "HALT", "RANK_EXIT", "RENAME", "NONE"])
def test_non_terminal_events_and_missing_rows_keep_position_and_last_mark(event: str) -> None:
    # Day 3 is absent entirely. Day 2 carries the tested non-terminal event.
    panel = _panel(
        {"CMC:7": {DAYS[0]: 10.0, DAYS[1]: 10.0, DAYS[3]: 12.0}},
        events={(DAYS[1], "CMC:7"): event},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))
    assert result.delisted_positions == 0
    assert result.delisting_losses_usd == 0
    assert result.equity.iloc[-1] > result.equity.iloc[1]


def test_only_explicit_terminal_event_writes_down_without_evidenced_exit() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0, 10.0, 10.0, 10.0], strict=True))},
        events={(DAYS[2], "CMC:7"): "DELISTING_CONFIRMED"},
    )
    result = evaluate(
        panel,
        _weights([(DAYS[0], "CMC:7", 1.0)]),
        delisting_recovery=1.0,
    )
    assert result.delisted_positions == 1
    assert result.delisting_losses_usd > 900
    assert result.executions[-1].status == "WRITTEN_DOWN"


def test_announced_delisting_forces_exit_at_next_open() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0, 10.0, 9.0, 8.0], strict=True))},
        events={(DAYS[1], "CMC:7"): "DELISTING_ANNOUNCED"},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))
    sells = [e for e in result.executions if e.side == "sell"]
    assert len(sells) == 1
    assert sells[0].order_intent == FORCED_EXIT
    assert sells[0].decision_timestamp.startswith(DAYS[1])
    assert sells[0].execution_timestamp.startswith(DAYS[2])


def test_sparse_announcement_waits_for_next_real_open_and_events_do_not_age_order() -> None:
    panel = _panel(
        {
            "CMC:7": {
                "2020-01-01": 10.0,
                "2020-01-02": 10.0,
                "2020-01-05": 9.0,
                "2020-01-06": 8.0,
            }
        }
    )
    ledger = MarketEventLedger.from_events(
        [
            _market_event(timestamp="2020-01-03T00:00:00Z", event="DELISTING_ANNOUNCED"),
            _market_event(timestamp="2020-01-04T00:00:00Z", event="HALT"),
        ]
    )
    result = evaluate(
        panel,
        _weights([("2020-01-01", "CMC:7", 1.0)]),
        market_events=ledger,
    )

    sells = [execution for execution in result.executions if execution.side == "sell"]
    assert len(sells) == 1
    assert sells[0].order_intent == FORCED_EXIT
    assert sells[0].execution_timestamp.startswith("2020-01-05")
    assert list(result.equity.index) == list(panel["timestamp"].drop_duplicates())


def test_sparse_confirmed_delisting_without_bar_uses_evidenced_recovery() -> None:
    panel = _panel({"CMC:7": {"2020-01-01": 10.0, "2020-01-02": 10.0, "2020-01-04": 10.0}})
    ledger = MarketEventLedger.from_events(
        [
            _market_event(
                timestamp="2020-01-03T00:00:00Z",
                event="DELISTING_CONFIRMED",
                recovery=8.0,
            )
        ]
    )
    result = evaluate(
        panel,
        _weights([("2020-01-01", "CMC:7", 1.0)]),
        market_events=ledger,
        delisting_recovery=1.0,
    )

    terminal = result.executions[-1]
    assert terminal.execution_timestamp.startswith("2020-01-03")
    assert terminal.status == "TERMINAL_RECOVERY"
    assert terminal.fill_price == 8.0
    assert result.delisted_positions == 1
    assert list(result.equity.index) == list(panel["timestamp"].drop_duplicates())


def test_sparse_halt_without_bar_keeps_position_and_last_mark() -> None:
    panel = _panel({"CMC:7": {"2020-01-01": 10.0, "2020-01-02": 10.0, "2020-01-04": 12.0}})
    ledger = MarketEventLedger.from_events(
        [_market_event(timestamp="2020-01-03T00:00:00Z", event="HALT")]
    )
    result = evaluate(
        panel,
        _weights([("2020-01-01", "CMC:7", 1.0)]),
        market_events=ledger,
    )

    assert result.delisted_positions == 0
    assert result.equity.iloc[-1] > result.equity.iloc[1]


def test_announced_delisting_blocks_same_decision_repurchase() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0, 10.0, 9.0, 20.0], strict=True))},
        events={(DAYS[1], "CMC:7"): "DELISTING_ANNOUNCED"},
    )
    result = evaluate(
        panel,
        _weights(
            [
                (DAYS[0], "CMC:7", 1.0),
                (DAYS[1], "CMC:7", 1.0),
            ]
        ),
    )

    at_day_3 = [
        execution
        for execution in result.executions
        if execution.execution_timestamp and DAYS[2] in execution.execution_timestamp
    ]
    assert any(
        execution.side == "sell"
        and execution.order_intent == FORCED_EXIT
        and execution.filled_quantity > 0
        for execution in at_day_3
    )
    blocked = [execution for execution in at_day_3 if execution.side == "buy"]
    assert len(blocked) == 1
    assert blocked[0].status == "REFUSED"
    assert blocked[0].filled_quantity == 0.0
    assert "delisting announcement" in blocked[0].reason


def test_announcement_blocks_first_purchase_even_without_an_existing_position() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS[:3], [10.0, 9.0, 8.0], strict=True))},
        events={(DAYS[0], "CMC:7"): "DELISTING_ANNOUNCED"},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))

    assert len(result.executions) == 1
    assert result.executions[0].status == "REFUSED"
    assert result.executions[0].filled_quantity == 0.0
    assert "delisting announcement" in result.executions[0].reason


def test_execution_day_rank_exit_cannot_retroactively_block_a_decision() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0, 10.0, 10.0, 10.0], strict=True))},
        eligible={(DAYS[2], "CMC:7"): False},
        events={(DAYS[2], "CMC:7"): "RANK_EXIT"},
    )
    weights = _weights(
        [
            (DAYS[0], "CMC:7", 1.0),
            (DAYS[1], "CMC:7", 0.0, FORCED_EXIT),
            (DAYS[1], "CMC:7", 1.0),
        ]
    )
    result = evaluate(panel, weights)
    at_day_3 = [
        e for e in result.executions if e.execution_timestamp and DAYS[2] in e.execution_timestamp
    ]
    assert any(e.side == "sell" and e.filled_quantity > 0 for e in at_day_3)
    assert any(e.side == "buy" and e.filled_quantity > 0 for e in at_day_3)


def test_partial_fill_and_limits_are_surfaced() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS[:3], [10.0, 10.0, 10.0], strict=True))},
        volume=10.0,
    )
    result = evaluate(
        panel,
        _weights([(DAYS[0], "CMC:7", 1.0)]),
        execution_policy=BarExecutionPolicy(max_volume_participation_rate=0.1),
        execution_limits={"CMC:7": ExecutionLimits(quantity_step=0.1, min_notional_usd=5)},
    )
    execution = result.executions[0]
    assert execution.status == "PARTIALLY_FILLED"
    assert execution.filled_quantity == pytest.approx(1.0)
    assert execution.refused_quantity > 0


def test_costs_are_charged_and_reduce_equity() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:3], [10.0, 10.0, 10.0], strict=True))})
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))
    assert result.total_cost_usd > 0
    assert result.equity.iloc[-1] < 1_000.0


def test_last_bar_decision_expires_instead_of_filling_same_bar() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    result = evaluate(panel, _weights([(DAYS[1], "CMC:7", 1.0)]))
    assert result.rebalances == []
    assert result.executions[0].status == "EXPIRED"
    assert result.executions[0].execution_timestamp is None
    assert result.summary()["refused_legs"] == 1
    assert result.summary()["expired_legs"] == 1


def test_turnover_accumulates_using_executed_notional() -> None:
    panel = _panel(
        {
            "CMC:7": dict(zip(DAYS, [10.0] * 4, strict=True)),
            "CMC:8": dict(zip(DAYS, [10.0] * 4, strict=True)),
        }
    )
    weights = _weights(
        [
            (DAYS[0], "CMC:7", 1.0),
            (DAYS[1], "CMC:8", 1.0),
            (DAYS[2], "CMC:7", 1.0),
        ]
    )
    result = evaluate(panel, weights)
    assert len(result.rebalances) == 3
    assert result.total_turnover == pytest.approx(2.5, rel=0.02)


def test_mixed_venue_panel_is_rejected() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    panel.loc[0, "venue"] = "binance"
    with pytest.raises(ValueError, match="exactly venue"):
        evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))


def test_btc_benchmark_is_one_decision_and_still_fills_t_plus_one() -> None:
    panel = _panel({"CMC:1": dict(zip(DAYS[:3], [10.0, 11.0, 12.0], strict=True))})
    weights = btc_buy_and_hold_benchmark(panel)
    result = evaluate(panel, weights)
    assert len(weights) == 1
    assert result.executions[0].execution_timestamp.startswith(DAYS[1])


def test_invalid_recovery_is_refused() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    with pytest.raises(ValueError, match="delisting_recovery"):
        evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]), delisting_recovery=1.5)


def test_t_plus_one_close_facts_cannot_change_the_open_fill() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS[:3], [10.0, 10.0, 10.0], strict=True))},
        volume=10_000.0,
    )
    changed = panel.copy()
    next_day = changed["timestamp"].eq(pd.Timestamp(DAYS[1], tz="UTC"))
    changed.loc[next_day, "close"] = 999.0
    changed.loc[next_day, "mark_price"] = 999.0
    changed.loc[next_day, "volume"] = 0.001
    changed.loc[next_day, "market_cap_usd"] = 1.0
    changed.loc[next_day, "eligible_to_open"] = False
    policy = BarExecutionPolicy(
        max_volume_participation_rate=0.1,
        market_impact_bps_at_full_participation=100.0,
    )

    baseline = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]), execution_policy=policy)
    mutated = evaluate(changed, _weights([(DAYS[0], "CMC:7", 1.0)]), execution_policy=policy)

    assert baseline.executions[0].to_dict() == mutated.executions[0].to_dict()


def test_decision_day_ineligibility_is_counted_as_a_refusal() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS[:3], [10.0, 10.0, 10.0], strict=True))},
        eligible={(DAYS[0], "CMC:7"): False},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))

    assert result.executions[0].status == "REFUSED"
    assert result.rebalances[0].names_targeted == 1
    assert result.rebalances[0].refused_legs == 1
    assert result.summary()["refused_legs"] == 1


def test_forced_exit_retries_a_missing_next_open_within_order_age() -> None:
    panel = _panel(
        {
            "CMC:7": {DAYS[0]: 10.0, DAYS[1]: 10.0, DAYS[3]: 10.0},
            "CMC:8": dict(zip(DAYS, [10.0] * 4, strict=True)),
        }
    )
    weights = _weights(
        [
            (DAYS[0], "CMC:7", 1.0),
            (DAYS[1], "CMC:7", 0.0, FORCED_EXIT),
        ]
    )
    result = evaluate(
        panel,
        weights,
        execution_policy=BarExecutionPolicy(max_order_age_bars=1),
    )

    sells = [execution for execution in result.executions if execution.side == "sell"]
    assert [execution.status for execution in sells] == ["REFUSED", "FILLED"]
    assert sells[0].execution_timestamp.startswith(DAYS[2])
    assert sells[1].execution_timestamp.startswith(DAYS[3])


def test_forced_exit_retries_residual_then_expires_at_max_age() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0] * 4, strict=True))},
        volume=1_000.0,
    )
    decision_day = panel["timestamp"].eq(pd.Timestamp(DAYS[1], tz="UTC"))
    panel.loc[decision_day, "volume"] = 5.0
    weights = _weights(
        [
            (DAYS[0], "CMC:7", 1.0),
            (DAYS[1], "CMC:7", 0.0, FORCED_EXIT),
        ]
    )
    result = evaluate(
        panel,
        weights,
        execution_policy=BarExecutionPolicy(
            max_volume_participation_rate=0.1,
            max_order_age_bars=1,
        ),
    )

    forced = [execution for execution in result.executions if execution.order_intent == FORCED_EXIT]
    assert [execution.status for execution in forced] == [
        "PARTIALLY_FILLED",
        "PARTIALLY_FILLED",
        "EXPIRED",
    ]
    forced_rebalances = [
        rebalance
        for rebalance in result.rebalances
        if rebalance.decision_timestamp.startswith(DAYS[1])
    ]
    assert [rebalance.capped_legs for rebalance in forced_rebalances] == [1, 1]
    assert result.summary()["expired_legs"] == 1


def test_same_day_target_does_not_duplicate_a_forced_exit_leg() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0] * 4, strict=True))},
        volume=1_000.0,
    )
    decision_day = panel["timestamp"].eq(pd.Timestamp(DAYS[1], tz="UTC"))
    panel.loc[decision_day, "volume"] = 5.0
    weights = _weights(
        [
            (DAYS[0], "CMC:7", 1.0),
            (DAYS[1], "CMC:7", 0.0),
            (DAYS[1], "CMC:7", 0.0, FORCED_EXIT),
        ]
    )
    result = evaluate(
        panel,
        weights,
        execution_policy=BarExecutionPolicy(
            max_volume_participation_rate=0.1,
            max_order_age_bars=1,
        ),
    )

    sells_on_first_open = [
        execution
        for execution in result.executions
        if execution.side == "sell"
        and execution.execution_timestamp
        and DAYS[2] in execution.execution_timestamp
    ]
    assert len(sells_on_first_open) == 1
    assert sells_on_first_open[0].order_intent == FORCED_EXIT


def test_affordability_is_rechecked_against_min_notional() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:3], [10.0] * 3, strict=True))})
    result = evaluate(
        panel,
        _weights([(DAYS[0], "CMC:7", 1.0)]),
        execution_limits={"CMC:7": ExecutionLimits(min_notional_usd=999.9)},
    )

    assert result.executions[0].status == "REFUSED"
    assert result.executions[0].filled_notional_usd == 0.0
    assert "cash/min-notional" in result.executions[0].reason


def test_one_capacity_capped_leg_is_not_counted_twice() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS[:3], [10.0] * 3, strict=True))},
        market_cap=5_000_000.0,
    )
    result = evaluate(
        panel,
        _weights([(DAYS[0], "CMC:7", 1.0)]),
        initial_capital_usd=10_000.0,
    )

    assert result.executions[0].status == "PARTIALLY_FILLED"
    assert result.rebalances[0].capped_legs == 1


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("eligible_to_open", "False", "actual booleans"),
        ("tradable", None, "actual booleans"),
        ("data_status", "PHANTOM", "invalid data_status"),
        ("market_event", "NONE|HALT", "NONE cannot be combined"),
    ],
)
def test_panel_execution_contract_fails_closed(column: str, value, message: str) -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    panel[column] = panel[column].astype(object)
    panel.loc[0, column] = value
    with pytest.raises(ValueError, match=message):
        evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))


def test_composite_terminal_event_is_not_hidden_by_a_rename() -> None:
    panel = _panel(
        {"CMC:7": dict(zip(DAYS, [10.0] * 4, strict=True))},
        events={(DAYS[2], "CMC:7"): "RENAME|DELISTING_CONFIRMED"},
    )
    result = evaluate(panel, _weights([(DAYS[0], "CMC:7", 1.0)]))
    assert result.delisted_positions == 1
    assert result.executions[-1].status == "WRITTEN_DOWN"


def test_btc_benchmark_bypasses_only_the_strategy_cap_band() -> None:
    panel = _panel(
        {"CMC:1": dict(zip(DAYS[:3], [10.0, 11.0, 12.0], strict=True))},
        eligible={(day, "CMC:1"): False for day in DAYS[:3]},
        market_cap=2_000_000_000_000.0,
    )
    weights = btc_buy_and_hold_benchmark(panel)
    result = evaluate(panel, weights)

    assert len(weights) == 1
    assert bool(weights.iloc[0]["open_eligibility_exempt"])
    assert result.executions[0].status in {"FILLED", "PARTIALLY_FILLED"}


def test_candidate_cannot_claim_the_btc_benchmark_exemption() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    weights = _weights([(DAYS[0], "CMC:7", 1.0)])
    weights["open_eligibility_exempt"] = True
    with pytest.raises(ValueError, match="reserved for the single CMC:1"):
        evaluate(panel, weights)


def test_stress_multipliers_change_the_actual_fill_and_cost_profile() -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:3], [10.0, 10.0, 10.0], strict=True))})
    weights = _weights([(DAYS[0], "CMC:7", 0.5)])

    baseline = evaluate(panel, weights)
    stressed = evaluate(
        panel,
        weights,
        cost_multiplier=2.0,
        fill_fraction_multiplier=0.5,
    )

    baseline_fill = next(item for item in baseline.executions if item.status != "EXPIRED")
    stressed_fill = next(item for item in stressed.executions if item.status != "EXPIRED")
    assert stressed_fill.filled_quantity == pytest.approx(baseline_fill.filled_quantity * 0.5)
    # Half the notional at twice the fee rate leaves the same absolute fee,
    # proving that both stress controls affected accounting rather than only
    # decorating an output payload.
    assert stressed_fill.fee_usd == pytest.approx(baseline_fill.fee_usd)
    assert stressed.cost_multiplier == 2.0
    assert stressed.fill_fraction_multiplier == 0.5
    assert stressed.summary()["cost_multiplier"] == 2.0


@pytest.mark.parametrize(
    ("cost_multiplier", "fill_fraction"),
    [(0.99, 1.0), (float("nan"), 1.0), (1.0, 0.0), (1.0, 1.01)],
)
def test_stress_multipliers_fail_closed(cost_multiplier: float, fill_fraction: float) -> None:
    panel = _panel({"CMC:7": dict(zip(DAYS[:2], [10.0, 10.0], strict=True))})
    with pytest.raises(ValueError, match="multiplier"):
        evaluate(
            panel,
            _weights([(DAYS[0], "CMC:7", 1.0)]),
            cost_multiplier=cost_multiplier,
            fill_fraction_multiplier=fill_fraction,
        )
