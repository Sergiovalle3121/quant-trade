"""Offline tests for the live paper loop (fake provider, no network)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.live.loop import LoopConfig, PaperLoopRunner
from quant_trade.paper.models import PaperRiskLimits


class GrowingFeed:
    """Serves a fixed panel truncated at a movable 'now' — each advance()
    reveals one more bar, simulating live time passing between cycles."""

    name = "fake-feed"

    def __init__(self, n: int = 80, seed: int = 3):
        rng = np.random.default_rng(seed)
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
        self.visible = 40  # bars visible initially

    def advance(self, bars: int = 1) -> None:
        self.visible = min(self.visible + bars, len(self.panel["timestamp"].unique()))

    def now(self) -> datetime:
        dates = sorted(self.panel["timestamp"].unique())
        return pd.Timestamp(dates[self.visible - 1]).to_pydatetime() + timedelta(hours=1)

    def supports_interval(self, interval: str) -> bool:
        return interval == "1d"

    def fetch_ohlcv(self, request):
        dates = sorted(self.panel["timestamp"].unique())
        cutoff = dates[self.visible - 1]
        return self.panel[self.panel["timestamp"] <= cutoff].copy()


def _config(tmp_path, **overrides) -> LoopConfig:
    defaults = dict(
        session_name="loop_test",
        strategy="time_series_momentum",
        strategy_params={"lookback_days": 10, "rebalance_frequency": "daily"},
        symbols=["AAA-USD", "BBB-USD"],
        initial_cash=100_000.0,
        costs={"percentage_commission": 0.0005},
        risk_limits=PaperRiskLimits(max_weight_per_asset=0.6, max_turnover_per_rebalance=2.0),
        provider="synthetic",
        interval="1d",
        history_bars=60,
        state_dir=str(tmp_path / "state"),
    )
    defaults.update(overrides)
    return LoopConfig(**defaults)


def _runner(tmp_path, feed, **overrides) -> PaperLoopRunner:
    return PaperLoopRunner(_config(tmp_path, **overrides), provider=feed, now_fn=feed.now)


def test_pending_target_executes_next_bar_across_process_restarts(tmp_path):
    feed = GrowingFeed()
    # cycle 1: decides a target, nothing to execute yet
    r1 = _runner(tmp_path, feed)
    s1 = r1.run_cycle()
    assert s1["orders"] == 0
    loop_state = json.loads((r1.loop_state_path).read_text())
    assert loop_state["pending_target"] is not None
    decided_at = loop_state["pending_decided_at"]

    # a NEW runner instance (fresh process) picks up the persisted target and
    # executes it at the NEXT bar's open
    feed.advance()
    r2 = _runner(tmp_path, feed)
    s2 = r2.run_cycle()
    assert s2["filled"] >= 1
    assert s2["bar"] > decided_at  # fills happen strictly after the decision bar
    session = json.loads(r2.session_state_path.read_text())
    assert session["positions"]  # holding now


def test_cycle_without_new_bar_is_a_heartbeat_noop(tmp_path):
    feed = GrowingFeed()
    runner = _runner(tmp_path, feed)
    runner.run_cycle()
    before = json.loads(runner.session_state_path.read_text())
    result = runner.run_cycle()  # no advance(): same newest bar
    assert result["action"] == "noop"
    after = json.loads(runner.session_state_path.read_text())
    assert after == before
    heartbeat = json.loads((tmp_path / "state/loop_test/heartbeat.json").read_text())
    assert heartbeat["mode"] == "paper_loop"


def test_kill_switch_file_halts_loop_and_fails_closed(tmp_path):
    feed = GrowingFeed()
    ks = tmp_path / "kill.json"
    runner = _runner(tmp_path, feed, kill_switch_uri=str(ks))
    runner.run_cycle()  # fine: no kill file
    ks.write_text(json.dumps({"active": True, "reason": "manual halt"}))
    feed.advance()
    with pytest.raises(SafetyGateError):
        runner.run_cycle()
    # corrupted kill-switch storage also halts (fail closed)
    ks.write_text("{not json")
    with pytest.raises(SafetyGateError):
        runner.run_cycle()


def test_halted_session_requires_operator_intervention(tmp_path):
    feed = GrowingFeed()
    ks = tmp_path / "kill.json"
    runner = _runner(tmp_path, feed, kill_switch_uri=str(ks))
    runner.run_cycle()
    ks.write_text(json.dumps({"active": True, "reason": "halt"}))
    feed.advance()
    with pytest.raises(SafetyGateError):
        runner.run_cycle()
    # even after the kill file clears, the persisted session stays paused
    ks.unlink()
    feed.advance()
    result = runner.run_cycle()
    assert result["action"] == "paused"


def test_daily_loss_breaker_halts(tmp_path):
    feed = GrowingFeed()
    runner = _runner(
        tmp_path,
        feed,
        risk_limits=PaperRiskLimits(
            max_weight_per_asset=0.6,
            max_turnover_per_rebalance=2.0,
            max_daily_loss_pct=0.000001,  # any loss trips it
            max_total_drawdown_pct=0.9,
        ),
    )
    runner.run_cycle()
    for _ in range(30):
        feed.advance()
        result = runner.run_cycle()
        if result["action"] in ("halted", "paused"):
            break
    session = json.loads(runner.session_state_path.read_text())
    assert session["kill_switch_active"] or session["status"] == "paused"


def test_run_forever_bounded_by_max_cycles(tmp_path):
    feed = GrowingFeed()
    runner = _runner(tmp_path, feed)
    results = runner.run_forever(interval_seconds=0.0, max_cycles=2)
    assert len(results) == 2
