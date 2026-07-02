import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.backtest.costs import CostModel
from quant_trade.cli import app
from quant_trade.execution.simulated_broker import SimulatedBroker
from quant_trade.paper.config import load_paper_config
from quant_trade.paper.events import create_event, event_to_json
from quant_trade.paper.models import PaperOrder, PaperRiskLimits, PaperSessionState
from quant_trade.paper.rebalancer import target_weights_to_orders
from quant_trade.paper.risk import should_trigger_kill_switch, validate_order
from quant_trade.paper.simulator import PaperTradingSimulator
from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.selection import select_candidates_from_outputs


def test_candidate_selection_pass_and_fail(tmp_path: Path):
    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"
    bad.mkdir()
    base = {
        "strategy": "time_series_momentum",
        "strategy_params": {"max_weight_per_asset": 0.25},
        "symbols": ["SPY"],
        "test_metrics": {"sharpe": 0.8, "max_drawdown": -0.1, "turnover": 1.0},
        "train_metrics": {"sharpe": 1.0},
        "comparison_test": {"excess_return": 0.03},
        "test_months": 13,
        "robustness": {"cost_sensitivity_pass": True},
    }
    (good / "results.json").write_text(json.dumps(base))
    bad_payload = base.copy()
    bad_payload.pop("test_metrics")
    (bad / "results.json").write_text(json.dumps(bad_payload))
    items = select_candidates_from_outputs(tmp_path, SelectionCriteria())
    assert len(items) == 1 and items[0].status == "candidate"


def test_rebalancer_buy_and_tiny_order_ignored():
    st = PaperSessionState(cash=1000, equity=1000, last_processed_timestamp="t")
    orders = target_weights_to_orders(
        st, {"SPY": 0.5}, {"SPY": 100}, PaperRiskLimits(max_weight_per_asset=0.6), CostModel()
    )
    assert orders[0].side == "buy" and orders[0].quantity == pytest.approx(5)
    none = target_weights_to_orders(
        st, {"SPY": 0.0001}, {"SPY": 100}, PaperRiskLimits(minimum_order_notional=10), CostModel()
    )
    assert none == []


def test_risk_rejects_leverage_short_and_kill_switch():
    st = PaperSessionState(cash=10, equity=100, high_water_mark=100, max_drawdown=0.2)
    ok, reason = validate_order(
        PaperOrder("1", "t", "SPY", "buy", 2), st, PaperRiskLimits(), {"SPY": 100}
    )
    assert not ok and "leverage" in reason
    ok, reason = validate_order(
        PaperOrder("2", "t", "SPY", "sell", 1), st, PaperRiskLimits(), {"SPY": 100}
    )
    assert not ok and "short" in reason
    assert should_trigger_kill_switch(st, PaperRiskLimits(max_total_drawdown_pct=0.1))


def test_events_serialize():
    ev = create_event("t", "session_started", "started")
    assert "session_started" in event_to_json(ev)


def test_simulated_broker_accepts_and_rejects():
    broker = SimulatedBroker()
    order = broker.submit_order(PaperOrder("1", "t", "SPY", "buy", 1))
    assert order.status == "pending"
    bad = broker.submit_order(PaperOrder("2", "t", "SPY", "buy", 0))
    assert bad.status == "rejected"


def test_simulator_outputs(tmp_path: Path):
    cfg = tmp_path / "paper.yaml"
    cfg.write_text(
        Path("configs/paper/equal_weight_synthetic_paper.yaml")
        .read_text()
        .replace("outputs/paper", str(tmp_path / "out"))
        .replace("state/paper", str(tmp_path / "state"))
    )
    out = PaperTradingSimulator(cfg).run()
    for name in [
        "account_snapshots.csv",
        "orders.csv",
        "fills.csv",
        "positions.csv",
        "events.csv",
        "risk_events.csv",
        "final_state.json",
        "paper_metrics.json",
        "paper_summary.md",
    ]:
        assert (out / name).exists()


def test_paper_cli_init_run_status(tmp_path: Path):
    cfg = tmp_path / "paper.yaml"
    cfg.write_text(
        Path("configs/paper/equal_weight_synthetic_paper.yaml")
        .read_text()
        .replace("outputs/paper", str(tmp_path / "out"))
        .replace("state/paper", str(tmp_path / "state"))
    )
    runner = CliRunner()
    assert runner.invoke(app, ["paper", "init", "--config", str(cfg)]).exit_code == 0
    res = runner.invoke(app, ["paper", "run", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "Final equity" in res.output


def test_config_rejects_broker(tmp_path: Path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(
        Path("configs/paper/equal_weight_synthetic_paper.yaml").read_text() + "\nbroker: live\n"
    )
    with pytest.raises(ValueError):
        load_paper_config(cfg)
