import json

import pandas as pd
import pytest

from quant_trade.paper.simulator import PaperTradingSimulator


def test_paper_simulator_persists_partial_fills_and_cancels_stale_remainders(
    tmp_path,
):
    data_path = tmp_path / "bars.csv"
    pd.DataFrame(
        [
            {
                "timestamp": f"2026-01-0{day}T00:00:00Z",
                "symbol": "SPY",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 100,
            }
            for day in range(1, 6)
        ]
    ).to_csv(data_path, index=False)
    config = tmp_path / "paper.yaml"
    config.write_text(
        f"""
paper_session_name: partial-fill-test
mode: simulated
data_path: {data_path.as_posix()}
strategy: equal_weight_buy_and_hold
strategy_params: {{max_weight_per_asset: 0.50}}
universe: {{symbols: [SPY]}}
initial_cash: 10000
costs: {{fixed_commission: 0, percentage_commission: 0}}
risk_limits:
  max_gross_exposure: 1
  max_weight_per_asset: 0.50
  max_turnover_per_rebalance: 1
  min_cash_pct: 0.01
  max_orders_per_day: 50
  allow_short: false
  allow_leverage: false
  kill_switch_enabled: true
execution:
  execution_price: next_open
  fractional_shares: true
  max_volume_participation_rate: 0.10
  max_order_age_bars: 3
  market_impact_bps_at_full_participation: 100
state_dir: {(tmp_path / "state").as_posix()}
output_dir: {(tmp_path / "out").as_posix()}
""",
        encoding="utf-8",
    )

    out = PaperTradingSimulator(config).run()
    fills = pd.read_csv(out / "fills.csv")
    orders = pd.read_csv(out / "orders.csv")
    events = pd.read_csv(out / "events.csv")
    final_state = json.loads((out / "final_state.json").read_text(encoding="utf-8"))
    metrics = json.loads((out / "paper_metrics.json").read_text(encoding="utf-8"))

    assert len(fills) == 4
    assert (fills["quantity"] == 10).all()
    assert (fills["participation_rate"] == 0.10).all()
    assert (fills["price"] > 100).all()
    assert (orders["filled_quantity"] == 10).all()
    assert set(orders["status"]) == {"cancelled"}
    assert "order_partially_filled" in set(events["event_type"])
    assert "order_cancelled" in set(events["event_type"])
    assert metrics["partial_fill_orders"] == 4
    assert metrics["cancelled_orders"] == 4
    assert metrics["quantity_fill_rate"] == pytest.approx(
        fills["quantity"].sum() / orders["quantity"].sum()
    )
    assert metrics["average_participation_rate"] == pytest.approx(0.10)
    assert metrics["average_price_impact_bps"] == pytest.approx(10)
    assert final_state["open_orders"] == []


def test_price_impact_cash_breach_rejects_without_phantom_fill(tmp_path):
    data_path = tmp_path / "bars.csv"
    pd.DataFrame(
        [
            {
                "timestamp": f"2026-02-0{day}T00:00:00Z",
                "symbol": "SPY",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
            }
            for day in range(1, 4)
        ]
    ).to_csv(data_path, index=False)
    config = tmp_path / "paper.yaml"
    config.write_text(
        f"""
paper_session_name: cash-impact-test
mode: simulated
data_path: {data_path.as_posix()}
strategy: equal_weight_buy_and_hold
strategy_params: {{max_weight_per_asset: 0.50}}
universe: {{symbols: [SPY]}}
initial_cash: 1000
costs: {{fixed_commission: 0, percentage_commission: 0}}
risk_limits:
  max_gross_exposure: 1
  max_weight_per_asset: 0.50
  max_turnover_per_rebalance: 1
  min_cash_pct: 0.50
  max_orders_per_day: 50
  allow_short: false
  allow_leverage: false
  kill_switch_enabled: true
execution:
  execution_price: next_open
  max_volume_participation_rate: 0.50
  market_impact_bps_at_full_participation: 10000
state_dir: {(tmp_path / "state").as_posix()}
output_dir: {(tmp_path / "out").as_posix()}
""",
        encoding="utf-8",
    )

    out = PaperTradingSimulator(config).run()
    orders = pd.read_csv(out / "orders.csv")
    final_state = json.loads((out / "final_state.json").read_text(encoding="utf-8"))

    assert not (out / "fills.csv").read_text(encoding="utf-8").strip()
    assert set(orders["status"]) == {"rejected"}
    assert (orders["filled_quantity"] == 0).all()
    assert (orders["remaining_quantity"] == orders["quantity"]).all()
    assert final_state["cash"] == 1000

