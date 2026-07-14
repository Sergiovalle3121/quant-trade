"""Tests for the paper-phase wiring (W1-W4): quarterly cadence parameter,
dead-man EMF heartbeat, loop session export, and the strategy-aware broker
rebalance plan. All offline; no network."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.live.loop import LoopConfig, PaperLoopRunner
from quant_trade.paper.models import PaperRiskLimits, PaperSessionState
from quant_trade.paper.state import save_state
from quant_trade.research.signals.allocation import equal_weight_quarterly
from quant_trade.research.signals.base import rebalance_mask

# ----------------------------------------------------------------- W1: cadence


def test_rebalance_mask_quarterly_marks_first_trading_day_of_quarters():
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="B", tz="UTC")
    mask = rebalance_mask(idx, "quarterly")
    marked = list(idx[mask])
    assert len(marked) == 4
    assert all(ts.month in (1, 4, 7, 10) for ts in marked)
    for ts in marked:
        month_days = idx[(idx.year == ts.year) & (idx.month == ts.month)]
        assert ts == month_days.min()


def test_rebalance_mask_quarterly_mid_quarter_start_waits_for_boundary():
    idx = pd.date_range("2024-02-05", "2024-05-31", freq="B", tz="UTC")
    mask = rebalance_mask(idx, "quarterly")
    marked = list(idx[mask])
    assert len(marked) == 1  # only 2024-04-01; no first-bar fallback
    assert marked[0].month == 4


def test_rebalance_mask_rejects_unknown_frequency():
    idx = pd.date_range("2024-01-01", periods=10, freq="B", tz="UTC")
    with pytest.raises(ValueError):
        rebalance_mask(idx, "hourly")


def _ew_panel(n: int = 260) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    frames = []
    for symbol in ("AAA", "BBB", "CCC"):
        close = np.linspace(100.0, 120.0, n)
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": ts,
                    "symbol": symbol,
                    "open": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 1_000_000.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_equal_weight_quarterly_accepts_accelerated_cadence():
    data = _ew_panel()
    quarterly = equal_weight_quarterly(data, {})
    weekly = equal_weight_quarterly(data, {"rebalance_frequency": "weekly"})
    q_dates = quarterly["timestamp"].nunique()
    w_dates = weekly["timestamp"].nunique()
    assert q_dates == 4  # default cadence unchanged
    assert w_dates > 40  # ~52 weekly emissions in a year
    assert np.allclose(weekly["target_weight"].to_numpy(), 1.0 / 3.0)


# ------------------------------------------- shared fake feed for loop tests


class GrowingFeed:
    """Fixed panel truncated at a movable 'now'; advance() reveals bars."""

    name = "fake-feed"

    def __init__(self, n: int = 60, visible: int = 30):
        rng = np.random.default_rng(11)
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        rows = []
        for sym, drift in [("AAA-USD", 0.002), ("BBB-USD", 0.001)]:
            close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
            open_ = np.concatenate([[100.0], close[:-1]])
            for i, ts in enumerate(dates):
                o, c = open_[i], close[i]
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": sym,
                        "open": o,
                        "high": max(o, c) * 1.001,
                        "low": min(o, c) * 0.999,
                        "close": c,
                        "volume": 1000.0,
                    }
                )
        self.panel = pd.DataFrame(rows)
        self.visible = visible

    def advance(self, bars: int = 1) -> None:
        self.visible = min(self.visible + bars, self.panel["timestamp"].nunique())

    def now(self) -> datetime:
        dates = sorted(self.panel["timestamp"].unique())
        return pd.Timestamp(dates[self.visible - 1]).to_pydatetime() + timedelta(hours=1)

    def supports_interval(self, interval: str) -> bool:
        return interval == "1d"

    def fetch_ohlcv(self, request):
        dates = sorted(self.panel["timestamp"].unique())
        cutoff = dates[self.visible - 1]
        return self.panel[self.panel["timestamp"] <= cutoff].copy()


def _loop_config(tmp_path, **overrides) -> LoopConfig:
    defaults = dict(
        session_name="wiring_test",
        strategy="time_series_momentum",
        strategy_params={"lookback_days": 10, "rebalance_frequency": "daily"},
        symbols=["AAA-USD", "BBB-USD"],
        initial_cash=100_000.0,
        costs={"percentage_commission": 0.0005},
        risk_limits=PaperRiskLimits(max_weight_per_asset=0.6, max_turnover_per_rebalance=2.0),
        provider="synthetic",
        interval="1d",
        history_bars=40,
        state_dir=str(tmp_path / "state"),
    )
    defaults.update(overrides)
    return LoopConfig(**defaults)


def _run_cycles(tmp_path, cycles: int = 3, **overrides) -> tuple[GrowingFeed, PaperLoopRunner]:
    feed = GrowingFeed()
    runner = PaperLoopRunner(_loop_config(tmp_path, **overrides), provider=feed, now_fn=feed.now)
    for _ in range(cycles):
        runner.run_cycle()
        feed.advance()
    return feed, runner


# --------------------------------------------------------- W2: dead-man EMF


def test_loop_emits_heartbeat_emf_when_enabled(tmp_path, capsys):
    _run_cycles(tmp_path, cycles=1, emit_cloudwatch_metrics=True)
    out = capsys.readouterr().out
    emf_lines = [ln for ln in out.splitlines() if "heartbeat_age_seconds" in ln]
    assert emf_lines, "expected an EMF heartbeat metric line on stdout"
    payload = json.loads(emf_lines[-1])
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "QuantTrade/CloudPaper"
    assert payload["job"] == "heartbeat"
    assert payload["heartbeat_age_seconds"] == 0.0


def test_loop_emits_no_metrics_by_default(tmp_path, capsys):
    _run_cycles(tmp_path, cycles=1)
    assert "heartbeat_age_seconds" not in capsys.readouterr().out


# ------------------------------------------------- W3: history + export CLI


def test_loop_persists_per_cycle_history(tmp_path):
    _, runner = _run_cycles(tmp_path, cycles=3)
    root = Path(runner.session_state_path).parent
    snapshots = (root / "snapshots.jsonl").read_text().splitlines()
    assert len(snapshots) >= 2  # one per acting cycle
    row = json.loads(snapshots[-1])
    assert {"timestamp", "cash", "equity", "gross_exposure", "drawdown"} <= set(row)
    orders = (root / "orders.jsonl").read_text().splitlines()
    assert orders, "at least one executed order should be recorded"
    assert json.loads(orders[0])["status"] in {"filled", "rejected"}


def test_paper_export_session_materializes_standard_artifacts(tmp_path):
    _run_cycles(tmp_path, cycles=3)
    cfg_path = tmp_path / "loop.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "mode": "paper_loop",
                "session_name": "wiring_test",
                "strategy": "time_series_momentum",
                "strategy_params": {"lookback_days": 10, "rebalance_frequency": "daily"},
                "universe": {"symbols": ["AAA-USD", "BBB-USD"]},
                "initial_cash": 100000.0,
                "costs": {"percentage_commission": 0.0005},
                "risk_limits": {"kill_switch_enabled": True},
                "state_dir": str(tmp_path / "state"),
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        ["paper", "export-session", "--config", str(cfg_path),
         "--output-dir", str(tmp_path / "exports")],
    )
    assert result.exit_code == 0, result.output
    runs = list((tmp_path / "exports" / "wiring_test").iterdir())
    assert len(runs) == 1
    out = runs[0]
    for name in [
        "account_snapshots.csv", "orders.csv", "fills.csv", "positions.csv",
        "events.csv", "risk_events.csv", "paper_metrics.json",
        "paper_summary.md", "final_state.json",
    ]:
        assert (out / name).exists(), name
    snapshots = pd.read_csv(out / "account_snapshots.csv")
    assert len(snapshots) >= 2
    metrics = json.loads((out / "paper_metrics.json").read_text())
    assert metrics["number_of_fills"] >= 1


# -------------------------------------------- W4: strategy-aware broker plan


def _panel_csv(tmp_path, end: str) -> Path:
    ts = pd.date_range(end=end, periods=70, freq="B", tz="UTC")
    frames = []
    for symbol in ("AAA", "BBB", "CCC"):
        close = np.linspace(95.0, 105.0, len(ts))
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": [t.isoformat() for t in ts],
                    "symbol": symbol,
                    "open": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 1_000_000.0,
                }
            )
        )
    path = tmp_path / "panel.csv"
    pd.concat(frames, ignore_index=True).to_csv(path, index=False)
    return path


def _w4_setup(tmp_path, max_notional: float = 50_000.0) -> tuple[Path, Path, Path]:
    state_dir = tmp_path / "state" / "ew_session"
    state_dir.mkdir(parents=True)
    save_state(
        state_dir / "latest_state.json",
        PaperSessionState(
            cash=100_000.0, equity=100_000.0, high_water_mark=100_000.0, status="running"
        ),
    )
    loop_cfg = tmp_path / "loop_ew.yaml"
    loop_cfg.write_text(
        yaml.safe_dump(
            {
                "mode": "paper_loop",
                "session_name": "ew_session",
                "strategy": "equal_weight_quarterly",
                "strategy_params": {"max_weight_per_asset": 0.30},
                "universe": {"symbols": ["AAA", "BBB", "CCC"]},
                "initial_cash": 100000.0,
                "costs": {"percentage_commission": 0.0005},
                "risk_limits": {
                    "kill_switch_enabled": True,
                    "max_weight_per_asset": 0.4,
                    "max_turnover_per_rebalance": 2.0,
                    "min_cash_pct": 0.01,
                },
                "state_dir": str(tmp_path / "state"),
            }
        ),
        encoding="utf-8",
    )
    broker_cfg = tmp_path / "broker.yaml"
    broker_cfg.write_text(
        yaml.safe_dump(
            {
                "provider": "simulated",
                "mode": "simulated",
                "dry_run_default": True,
                "universe": ["AAA", "BBB", "CCC"],
                "allow_fractional": True,
                "max_notional_per_order": max_notional,
                "max_symbol_weight": 0.4,
                "min_cash_pct": 0.0,
            }
        ),
        encoding="utf-8",
    )
    return loop_cfg, broker_cfg, state_dir


def test_rebalance_plan_creates_orders_on_quarter_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loop_cfg, broker_cfg, _ = _w4_setup(tmp_path)
    data = _panel_csv(tmp_path, end="2024-04-01")  # first trading day of Q2
    result = CliRunner().invoke(
        app,
        ["broker", "rebalance-plan", "--loop-config", str(loop_cfg),
         "--broker-config", str(broker_cfg), "--data", str(data)],
    )
    assert result.exit_code == 0, result.output
    plan_dir = Path(result.output.strip().split(": ")[-1].split(" (")[0])
    orders = json.loads((plan_dir / "proposed_orders.json").read_text())
    assert len(orders) == 3
    assert all(o["side"] == "buy" and o["dry_run"] for o in orders)
    checks = json.loads((plan_dir / "risk_checks.json").read_text())
    assert all(c["passed"] and c["planned_notional"] > 0 for c in checks)
    target = json.loads((plan_dir / "target_weights.json").read_text())
    assert target == {"AAA": 0.30, "BBB": 0.30, "CCC": 0.30}
    assert (plan_dir / "proposed_orders.csv").exists()
    assert (plan_dir / "plan_summary.md").exists()


def test_rebalance_plan_noop_when_no_rebalance_due(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loop_cfg, broker_cfg, _ = _w4_setup(tmp_path)
    data = _panel_csv(tmp_path, end="2024-05-15")  # mid-quarter bar
    result = CliRunner().invoke(
        app,
        ["broker", "rebalance-plan", "--loop-config", str(loop_cfg),
         "--broker-config", str(broker_cfg), "--data", str(data)],
    )
    assert result.exit_code == 0, result.output
    assert "No rebalance due" in result.output
    plan_dir = Path(result.output.strip().split(": ")[-1])
    assert json.loads((plan_dir / "proposed_orders.json").read_text()) == []


def test_rebalance_plan_fails_whole_plan_on_safety_violation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Market-order safety notional is qty * 1.0, so ~300 planned shares exceed
    # a 10-notional cap and must fail the ENTIRE plan, not emit a partial one.
    loop_cfg, broker_cfg, _ = _w4_setup(tmp_path, max_notional=10.0)
    data = _panel_csv(tmp_path, end="2024-04-01")
    result = CliRunner().invoke(
        app,
        ["broker", "rebalance-plan", "--loop-config", str(loop_cfg),
         "--broker-config", str(broker_cfg), "--data", str(data)],
    )
    assert result.exit_code == 1
    plans = list((tmp_path / "outputs" / "broker_plans" / "ew_session").iterdir())
    assert len(plans) == 1
    assert (plans[0] / "plan_failure.json").exists()
    assert not (plans[0] / "proposed_orders.json").exists()
