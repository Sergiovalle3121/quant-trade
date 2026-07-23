import pytest

from quant_trade.execution.bar_model import (
    BarExecutionPolicy,
    BarOrderState,
    ExecutionStatus,
    cancel_order,
    execute_market_order_on_bar,
)


def _order(**overrides) -> BarOrderState:
    values = {
        "order_id": "o-1",
        "symbol": "SPY",
        "signed_quantity": 100.0,
        "submitted_bar_index": 4,
        "eligible_bar_index": 5,
    }
    values.update(overrides)
    return BarOrderState(**values)


def test_default_policy_preserves_full_next_open_fill():
    order = _order()
    fill = execute_market_order_on_bar(
        order,
        bar_index=5,
        open_price=100,
        volume=1,
        policy=BarExecutionPolicy(),
    )
    assert fill is not None
    assert fill.quantity == 100
    assert fill.price == 100
    assert order.status == ExecutionStatus.FILLED
    assert order.remaining_quantity == 0


def test_latency_defers_without_using_early_bar():
    order = _order(eligible_bar_index=7)
    early = execute_market_order_on_bar(
        order,
        bar_index=6,
        open_price=100,
        volume=1000,
        policy=BarExecutionPolicy(additional_latency_bars=2),
    )
    assert early is None
    assert order.status == ExecutionStatus.DEFERRED
    fill = execute_market_order_on_bar(
        order,
        bar_index=7,
        open_price=101,
        volume=1000,
        policy=BarExecutionPolicy(additional_latency_bars=2),
    )
    assert fill is not None and fill.price == 101


def test_participation_lot_and_impact_create_partial_fills():
    policy = BarExecutionPolicy(
        max_volume_participation_rate=0.10,
        lot_size=5,
        max_order_age_bars=2,
        market_impact_bps_at_full_participation=100,
    )
    order = _order()
    first = execute_market_order_on_bar(
        order,
        bar_index=5,
        open_price=100,
        volume=240,
        policy=policy,
    )
    assert first is not None
    assert first.quantity == 20
    assert first.participation_rate == pytest.approx(0.10)
    assert first.price_impact_bps == pytest.approx(10)
    assert first.price == pytest.approx(100.1)
    assert order.status == ExecutionStatus.PARTIALLY_FILLED
    assert order.remaining_quantity == 80

    second = execute_market_order_on_bar(
        order,
        bar_index=6,
        open_price=101,
        volume=300,
        policy=policy,
    )
    assert second is not None and second.quantity == 30
    assert order.cumulative_filled_quantity == 50
    assert order.remaining_quantity == 50


def test_remainder_expires_at_configured_age_after_partial_fill():
    policy = BarExecutionPolicy(
        max_volume_participation_rate=0.10,
        max_order_age_bars=1,
    )
    order = _order()
    execute_market_order_on_bar(
        order,
        bar_index=5,
        open_price=100,
        volume=100,
        policy=policy,
    )
    final = execute_market_order_on_bar(
        order,
        bar_index=6,
        open_price=100,
        volume=100,
        policy=policy,
    )
    assert final is not None
    assert order.status == ExecutionStatus.EXPIRED
    assert order.cumulative_filled_quantity == 20
    assert order.remaining_quantity == 80
    assert "remainder expired" in order.reason


def test_missing_open_and_zero_liquidity_fail_closed():
    missing = _order()
    assert (
        execute_market_order_on_bar(
            missing,
            bar_index=5,
            open_price=None,
            volume=100,
            policy=BarExecutionPolicy(),
        )
        is None
    )
    assert missing.status == ExecutionStatus.EXPIRED

    zero = _order()
    assert (
        execute_market_order_on_bar(
            zero,
            bar_index=5,
            open_price=100,
            volume=0,
            policy=BarExecutionPolicy(max_volume_participation_rate=0.10),
        )
        is None
    )
    assert zero.status == ExecutionStatus.EXPIRED


def test_sell_impact_is_adverse_and_cancellation_is_terminal():
    order = _order(signed_quantity=-10.0)
    fill = execute_market_order_on_bar(
        order,
        bar_index=5,
        open_price=100,
        volume=100,
        policy=BarExecutionPolicy(
            max_volume_participation_rate=0.10,
            market_impact_bps_at_full_participation=100,
        ),
    )
    assert fill is not None
    assert fill.side == "sell"
    assert fill.price == pytest.approx(99.9)

    pending = _order(order_id="o-2")
    cancel_order(pending, "superseded")
    assert pending.status == ExecutionStatus.CANCELLED
    assert (
        execute_market_order_on_bar(
            pending,
            bar_index=5,
            open_price=100,
            volume=100,
            policy=BarExecutionPolicy(),
        )
        is None
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"additional_latency_bars": -1}, "additional_latency_bars"),
        ({"max_volume_participation_rate": 0}, "max_volume"),
        ({"max_volume_participation_rate": 1.01}, "max_volume"),
        ({"lot_size": 0}, "lot_size"),
        ({"max_order_age_bars": -1}, "max_order_age"),
        ({"market_impact_bps_at_full_participation": -1}, "market_impact"),
    ],
)
def test_execution_policy_rejects_invalid_inputs(kwargs, message):
    with pytest.raises(ValueError, match=message):
        BarExecutionPolicy(**kwargs)

