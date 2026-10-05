from __future__ import annotations

import json
import math
import sqlite3
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.actions import signal_panel
from quant_trade.personal_paper.cli import app
from quant_trade.personal_paper.config import PersonalPaperError
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.store import PaperStore


@pytest.fixture
def inputs(tmp_path: Path):
    paths = create_demo(tmp_path / "data", sessions=100)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "experiment_id": "offline_test",
                "capital_mxn": 20000,
                "monthly_host_budget_mxn": 500,
                "data_kind": "synthetic",
                "price_basis": "adjusted_total_return",
                "max_drawdown": 0.05,
                "max_daily_loss": 0.02,
                "costs": {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2},
            }
        ),
        encoding="utf-8",
    )
    return config, paths["data"], paths["fx"], tmp_path / "paper.sqlite"


def event_values(database, kind):
    with sqlite3.connect(database) as connection:
        return [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT value FROM events WHERE kind=? ORDER BY sequence", (kind,)
            )
        ]


def test_equity_is_exactly_independent_of_position_insertion_and_json_order():
    prices = dict.fromkeys(engine.UNIVERSE, 1.0)
    quantities = dict(zip(engine.UNIVERSE, [0.1, 0.2, 0.3, 0.4, 0.5], strict=True))
    for symbols in permutations(engine.UNIVERSE):
        book = {"cash_usd": 0.0, "positions": {symbol: quantities[symbol] for symbol in symbols}}
        assert engine._equity(book, prices) == 1.5
        restarted = json.loads(json.dumps(book, sort_keys=True))
        assert engine._equity(restarted, prices) == engine._equity(book, prices)


def test_equity_preserves_cash_and_position_fractions_in_one_sum():
    half_ulp = math.ulp(1000.0) / 2
    book = {"cash_usd": half_ulp, "positions": {"GLD": 1000.0, "IWM": half_ulp}}
    assert engine._equity(book, {"GLD": 1.0, "IWM": 1.0}) == math.nextafter(1000.0, math.inf)


@pytest.mark.parametrize("dirty", [False, True])
def test_registration_records_git_worktree_dirty_without_rewriting_metadata(
    inputs, monkeypatch, dirty
):
    def git_result(command, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="observed-commit\n")
        assert command == ["git", "status", "--porcelain", "--untracked-files=normal"]
        return SimpleNamespace(stdout=" M source.py\n" if dirty else "")

    monkeypatch.setattr(engine.subprocess, "run", git_result)
    result = engine.run(*inputs)
    assert result["manifest"]["git_commit"] == "observed-commit"
    assert result["manifest"]["git_worktree_dirty"] is dirty

    def unavailable(*args, **kwargs):
        raise OSError("Git became unavailable after registration")

    monkeypatch.setattr(engine.subprocess, "run", unavailable)
    assert engine.run(*inputs)["manifest"]["git_worktree_dirty"] is dirty


def test_replay_fractional_causal_fills_reconciles_and_is_idempotent(inputs, tmp_path):
    result = engine.run(*inputs)
    fills = event_values(inputs[3], "fill")
    assert len(fills) >= 45
    assert all(not row["real_money_approved"] for row in fills)
    assert any(row["quantity"] % 1 != 0 for row in fills)
    dates = pd.read_csv(inputs[1]).timestamp.unique()
    assert len([f for f in fills if f["timestamp"] == pd.Timestamp(dates[64]).isoformat()]) == 45
    assert all(pd.Timestamp(f["timestamp"]) >= pd.Timestamp(dates[64]) for f in fills)
    assert all(
        book["cash_usd"] > 0 and min(book["positions"].values()) > 0
        for book in result["books"].values()
    )
    again = engine.run(*inputs)
    assert again["books"] == result["books"]
    assert event_values(inputs[3], "fill") == fills
    assert not again["paper_90d_3rebals_complete"]
    assert again["manifest"]["evidence_kind"] == "SYNTHETIC"
    exported = engine.export(inputs[3], tmp_path / "export")
    assert len(pd.read_csv(exported["curves"])) == 36 * 9
    assert len(result["manifest"]["historical_trial_ids"]) >= 109


@pytest.mark.parametrize("sessions", [66, 67])
def test_open_fill_never_uses_that_sessions_future_full_day_volume(inputs, tmp_path, sessions):
    panel = pd.read_csv(inputs[1])
    dates = panel.timestamp.unique()[:sessions]
    panel = panel[panel.timestamp.isin(dates)].copy()
    panel.to_csv(inputs[1], index=False)
    before = engine.run(*inputs)
    first_fill_time = pd.Timestamp(dates[64]).isoformat()
    baseline_fills = [
        f for f in event_values(inputs[3], "fill") if f["timestamp"] == first_fill_time
    ]
    assert len(baseline_fills) == 45
    panel.loc[panel.timestamp == dates[64], "volume"] = 0
    altered_data = tmp_path / "changed_future_full_day_volume.csv"
    panel.to_csv(altered_data, index=False)
    alternate_database = tmp_path / "alternate.sqlite"
    after = engine.run(inputs[0], altered_data, inputs[2], alternate_database)
    alternate_fills = [
        f for f in event_values(alternate_database, "fill") if f["timestamp"] == first_fill_time
    ]
    assert alternate_fills == baseline_fills
    assert after["books"] == before["books"]
    assert before["manifest"]["development_liquidity_basis"] == (
        "previous_closed_session_volume_proxy"
    )


@pytest.mark.parametrize("sessions", [66, 67])
def test_zero_previous_closed_session_volume_prevents_open_fill(inputs, sessions):
    panel = pd.read_csv(inputs[1])
    dates = panel.timestamp.unique()[:sessions]
    panel = panel[panel.timestamp.isin(dates)].copy()
    panel.loc[panel.timestamp == dates[63], "volume"] = 0
    panel.to_csv(inputs[1], index=False)
    engine.run(*inputs)
    first_fill_time = pd.Timestamp(dates[64]).isoformat()
    assert not any(
        event["timestamp"] == first_fill_time for event in event_values(inputs[3], "fill")
    )
    initial_orders = [
        event for event in event_values(inputs[3], "order") if event["timestamp"] == first_fill_time
    ]
    assert len(initial_orders) == 45
    assert all(event["status"] == "expired" for event in initial_orders)
    with sqlite3.connect(inputs[3]) as connection:
        initial_curves = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT value FROM curves WHERE timestamp=?", (first_fill_time,)
            )
        ]
    assert len(initial_curves) == 9
    assert all(
        curve["costs_usd"] == 0
        and curve["cash_usd"] == curve["equity_usd"] == 1000
        and curve["rebalance_count"] == 0
        for curve in initial_curves
    )


def test_transaction_crash_rolls_back_orders_cash_and_bars(inputs, monkeypatch):
    original = engine._snapshot

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated process failure")

    monkeypatch.setattr(engine, "_snapshot", crash)
    with pytest.raises(RuntimeError, match="process failure"):
        engine.run(*inputs)
    with sqlite3.connect(inputs[3]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0
    monkeypatch.setattr(engine, "_snapshot", original)
    engine.run(*inputs)
    fills = event_values(inputs[3], "fill")
    assert len({row["order_id"] for row in fills}) == len(fills)


def test_single_writer_and_manual_pause_review(inputs):
    engine.run(*inputs)
    first, second = PaperStore(inputs[3]), PaperStore(inputs[3])
    try:
        with (
            first.writing(),
            pytest.raises(PersonalPaperError, match="another writer"),
            second.writing(),
        ):
            pass
    finally:
        first.close()
        second.close()
    engine.pause(inputs[3], "manual inspection")
    assert engine.status(inputs[3])["status"] == "PAUSED"
    with pytest.raises(PersonalPaperError, match="written review"):
        engine.resume(inputs[3], "ok")
    engine.resume(inputs[3], "Reviewed positions, data and risk; resume simulated observations.")
    assert not any(b["paused"] for b in engine.status(inputs[3])["books"].values())


@pytest.mark.parametrize("fault", ["nonfinite", "missing_symbol", "changed_prefix", "deleted_date"])
def test_bad_market_or_revised_prefix_is_refused_without_state_change(inputs, fault):
    before = engine.run(*inputs)
    panel = pd.read_csv(inputs[1])
    if fault == "nonfinite":
        panel.loc[0, "high"] = np.inf
    elif fault == "missing_symbol":
        panel = panel.iloc[1:]
    elif fault == "changed_prefix":
        panel.loc[0, ["open", "high", "low", "close"]] *= 1.001
    else:
        panel = panel[panel.timestamp != panel.timestamp.unique()[10]]
    panel.to_csv(inputs[1], index=False)
    with pytest.raises((PersonalPaperError, ValueError)):
        engine.run(*inputs)
    assert engine.status(inputs[3])["books"] == before["books"]


def test_metadata_refresh_does_not_change_observed_prices(inputs):
    before = engine.run(*inputs)
    panel = pd.read_csv(inputs[1])
    panel["observed_at_utc"] = "2026-01-01T00:00:00Z"
    panel.to_csv(inputs[1], index=False)
    assert engine.run(*inputs)["books"] == before["books"]


@pytest.mark.parametrize("table", ["books", "curves", "bars", "manifest"])
def test_persisted_tampering_is_detected(inputs, table):
    engine.run(*inputs)
    with sqlite3.connect(inputs[3]) as connection:
        if table == "manifest":
            connection.execute("UPDATE meta SET value='{}' WHERE key='manifest'")
        else:
            connection.execute(f"DELETE FROM {table} WHERE rowid=(SELECT MIN(rowid) FROM {table})")
    with pytest.raises(PersonalPaperError):
        engine.status(inputs[3])


def test_five_percent_drawdown_pauses_buys_persists_and_keeps_valuing(inputs):
    panel = pd.read_csv(inputs[1])
    dates = panel.timestamp.unique()
    mask = panel.timestamp.isin(dates[75:])
    panel.loc[mask, ["open", "high", "low", "close"]] *= 0.90
    panel.to_csv(inputs[1], index=False)
    result = engine.run(*inputs)
    assert result["status"] == "PAUSED"
    assert all(b["drawdown"] > 0.05 for b in result["books"].values())
    assert all(
        b["last_timestamp"] == pd.Timestamp(dates[-1]).isoformat() for b in result["books"].values()
    )
    assert not any(
        f["side"] == "buy" and pd.Timestamp(f["timestamp"]) >= pd.Timestamp(dates[75])
        for f in event_values(inputs[3], "fill")
    )
    assert engine.run(*inputs)["status"] == "PAUSED"
    with pytest.raises(PersonalPaperError, match="drawdown still breached"):
        engine.resume(inputs[3], "Review completed and trading should be permitted again.")


def test_raw_split_dividend_apply_once_and_signal_is_causal(inputs):
    config = yaml.safe_load(inputs[0].read_text())
    config["price_basis"] = "raw_with_actions"
    inputs[0].write_text(yaml.safe_dump(config), encoding="utf-8")
    panel = pd.read_csv(inputs[1])
    dates = panel.timestamp.unique()
    panel["dividend"], panel["split_ratio"] = 0.0, 1.0
    splitdate, dividenddate = dates[80], dates[85]
    later = (panel.symbol == "SPY") & (panel.timestamp >= splitdate)
    panel.loc[later, ["open", "high", "low", "close"]] /= 2
    panel.loc[(panel.symbol == "SPY") & (panel.timestamp == splitdate), "split_ratio"] = 2
    panel.loc[(panel.symbol == "SPY") & (panel.timestamp == dividenddate), "dividend"] = 1.25
    panel.to_csv(inputs[1], index=False)
    validated = engine.validate_panel_schema(panel)
    full = signal_panel(validated, "raw_with_actions")
    prefix = validated[validated.timestamp < pd.Timestamp(splitdate)]
    pd.testing.assert_frame_equal(full.loc[prefix.index], signal_panel(prefix, "raw_with_actions"))
    result = engine.run(*inputs)
    actions = event_values(inputs[3], "corporate_action")
    assert len(actions) == 18
    assert all(a["cash_credit_usd"] > 0 for a in actions if a["dividend_per_share"])
    assert not any(b["paused"] for b in result["books"].values())
    assert engine.run(*inputs)["books"] == result["books"]
    assert event_values(inputs[3], "corporate_action") == actions


def prospective_fixture(inputs):
    panel = pd.read_csv(inputs[1])
    dates = pd.to_datetime(panel.timestamp.unique(), utc=True)
    # A full fictional session calendar with one future session for quotes.
    all_dates = dates.append(pd.DatetimeIndex([dates[-1] + pd.offsets.BDay()]))
    calendar = inputs[1].parent / "calendar.csv"
    pd.DataFrame(
        {
            "session_open_utc": all_dates + pd.Timedelta(hours=14),
            "session_close_utc": all_dates + pd.Timedelta(hours=21),
        }
    ).to_csv(calendar, index=False)
    nextdate = all_dates[-1]
    rows = []
    for r in panel[panel.timestamp == panel.timestamp.iloc[-1]].itertuples():
        rows.append(
            {
                "symbol": r.symbol,
                "price": r.close,
                "observed_at_utc": (nextdate + pd.Timedelta(hours=14, minutes=1)).isoformat(),
                "received_at_utc": (nextdate + pd.Timedelta(hours=14, minutes=1)).isoformat(),
                "session_open_utc": (nextdate + pd.Timedelta(hours=14)).isoformat(),
                "session_close_utc": (nextdate + pd.Timedelta(hours=21)).isoformat(),
                "previous_session_date": str(dates[-1].date()),
                "source": "SYNTHETIC_FIXTURE",
                "available_volume": 1_000_000,
            }
        )
    quotes = inputs[1].parent / "quotes.csv"
    pd.DataFrame(rows).to_csv(quotes, index=False)
    return calendar, quotes, dates[-1], nextdate


def test_prospective_no_retrospective_fills_then_fresh_next_open_once(inputs):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    initial = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    assert not event_values(inputs[3], "fill")
    assert initial["manifest"]["closed_sessions"] == 0
    assert all(not b["positions"] for b in initial["books"].values())
    assert all(b["pending"] is None for b in initial["books"].values())
    closed = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    assert closed["manifest"]["closed_sessions"] == 1
    assert not event_values(inputs[3], "fill")
    result = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
    )
    assert len(event_values(inputs[3], "fill")) == 45
    assert all(b["positions"] for b in result["books"].values())
    assert not result["paper_90d_3rebals_complete"]
    assert result["manifest"]["clock_source"] == "INJECTED_TEST_CLOCK"
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=14, minutes=3)).isoformat(),
    )
    assert len(event_values(inputs[3], "fill")) == 45


def test_missed_open_expires_instead_of_filling_old_price(inputs):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    frame = pd.read_csv(quotes)
    frame.observed_at_utc = (nextdate + pd.Timedelta(hours=15)).isoformat()
    frame.received_at_utc = frame.observed_at_utc
    frame.to_csv(quotes, index=False)
    result = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=15)).isoformat(),
    )
    assert not event_values(inputs[3], "fill")
    assert all(b["pending"] is None for b in result["books"].values())
    assert len(event_values(inputs[3], "missed_execution_window")) == 9


def test_stale_quote_or_unknown_actions_never_fill(inputs):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    with pytest.raises(PersonalPaperError, match="stale"):
        engine.run(
            *inputs,
            mode="prospective",
            calendar_path=calendar,
            quotes_path=quotes,
            now_utc=(nextdate + pd.Timedelta(hours=15)).isoformat(),
        )
    assert not event_values(inputs[3], "fill")


@pytest.mark.parametrize(
    "strategy,cap",
    [
        ("inverse_volatility", 0.35),
        ("vol_targeted_equal_weight", 0.25),
        ("equal_weight_quarterly", 0.25),
    ],
)
@pytest.mark.parametrize("multiplier", [1, 2, 3])
def test_post_fee_position_gross_cash_caps_hold(strategy, cap, multiplier, tmp_path):
    book = {
        "portfolio": strategy,
        "cost_multiplier": multiplier,
        "cash_usd": 1000.0,
        "initial_cash_usd": 1000.0,
        "positions": {},
        "rebalance_count": 0,
        "paused": False,
        "costs_usd": 0.0,
        "pending_decided_at": "2020-01-01T21:00:00Z",
    }
    prices = {s: 100.0 for s in ("GLD", "IWM", "QQQ", "SPY", "TLT")}
    targets = dict(zip(prices, [0.35, 0.30, 0.10, 0.10, 0.10], strict=True))
    store = PaperStore(tmp_path / "caps.sqlite")
    try:
        with store.writing():
            engine._fill_target(
                store,
                "test",
                book,
                targets,
                prices,
                {s: 1_000_000 for s in prices},
                "2020-01-02T14:01:00Z",
                {"costs": {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2}},
            )
        equity = engine._equity(book, prices)
        values = [q * prices[s] for s, q in book["positions"].items()]
        assert max(values) / equity <= cap + 1e-9
        assert sum(values) / equity <= 0.95 + 1e-9
        assert book["cash_usd"] / equity >= 0.05 - 1e-9
    finally:
        store.close()


def test_partial_risk_reduction_blocks_new_buys_even_with_five_point_band(tmp_path):
    book = {
        "portfolio": "inverse_volatility",
        "cost_multiplier": 3,
        "cash_usd": 550.0,
        "initial_cash_usd": 1000.0,
        "positions": {"GLD": 4.5},
        "rebalance_count": 1,
        "paused": False,
        "costs_usd": 0.0,
        "pending_decided_at": "2020-01-01T21:00:00Z",
    }
    prices = {s: 100.0 for s in ("GLD", "IWM", "QQQ", "SPY", "TLT")}
    store = PaperStore(tmp_path / "risk_caps.sqlite")
    try:
        with store.writing():
            engine._fill_target(
                store,
                "test",
                book,
                dict.fromkeys(prices, 0.19),
                prices,
                {s: 1 if s == "GLD" else 1_000_000 for s in prices},
                "2020-01-02T14:01:00Z",
                {"costs": {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2}},
            )
        fills = event_values(tmp_path / "risk_caps.sqlite", "fill")
        assert fills and all(f["side"] == "sell" for f in fills)
        assert book["positions"]["GLD"] < 4.5
        assert set(book["positions"]) == {"GLD"}
    finally:
        store.close()


def test_missing_quotes_expire_without_quote_file(inputs):
    calendar, _, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    result = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(nextdate + pd.Timedelta(hours=15)).isoformat(),
    )
    assert not event_values(inputs[3], "fill")
    assert all(b["pending"] is None for b in result["books"].values())
    assert len(event_values(inputs[3], "missed_execution_window")) == 9


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_signal_nonfinite_is_rejected_before_clamp(inputs, monkeypatch, weight):
    class BrokenSignal:
        def generate(self, panel, params):
            timestamp = panel.timestamp.max()
            return pd.DataFrame(
                {
                    "timestamp": [timestamp] * 5,
                    "symbol": ["GLD", "IWM", "QQQ", "SPY", "TLT"],
                    "target_weight": [weight] * 5,
                }
            )

    monkeypatch.setattr(engine, "get_research_signal_model", lambda _: BrokenSignal())
    with pytest.raises(PersonalPaperError, match="non-finite"):
        engine.run(*inputs)


def test_signal_missing_member_is_rejected(inputs, monkeypatch):
    class BrokenSignal:
        def generate(self, panel, params):
            return pd.DataFrame(
                {"timestamp": [panel.timestamp.max()], "symbol": ["SPY"], "target_weight": [0.2]}
            )

    monkeypatch.setattr(engine, "get_research_signal_model", lambda _: BrokenSignal())
    with pytest.raises(PersonalPaperError, match="complete frozen universe"):
        engine.run(*inputs)


def test_real_system_registration_cannot_be_advanced_with_test_clock(inputs):
    before = engine.run(*inputs)
    with pytest.raises(PersonalPaperError, match="changed after sealing"):
        engine.run(*inputs, now_utc="2027-10-05T00:00:00Z")
    assert engine.status(inputs[3])["books"] == before["books"]


def test_config_and_code_changes_require_new_registration(inputs, monkeypatch):
    engine.run(*inputs)
    monkeypatch.setattr(engine, "execution_code_hash", lambda: "changed-code")
    with pytest.raises(PersonalPaperError, match="changed after sealing"):
        engine.run(*inputs)


def test_adjusted_prices_do_not_double_credit_dividends(inputs):
    panel = pd.read_csv(inputs[1])
    panel["dividend"], panel["split_ratio"] = 1.0, 1.0
    panel.to_csv(inputs[1], index=False)
    engine.run(*inputs)
    assert not event_values(inputs[3], "corporate_action")


def test_fx_loss_triggers_mxn_drawdown_even_without_usd_price_shock(inputs):
    fx = pd.read_csv(inputs[2])
    fx.loc[fx.index >= 75, "usd_mxn"] = 18.0
    fx.to_csv(inputs[2], index=False)
    result = engine.run(*inputs)
    assert result["status"] == "PAUSED"
    assert all(b["drawdown"] > 0.05 for b in result["books"].values())


def test_direct_quotes_run_catches_up_and_expires_an_obsolete_initial_decision(inputs):
    calendar, quotes, _, nextdate = prospective_fixture(inputs)
    complete = pd.read_csv(inputs[1])
    dates = pd.to_datetime(complete.timestamp.unique(), utc=True)
    complete[pd.to_datetime(complete.timestamp, utc=True) <= dates[-2]].to_csv(
        inputs[1], index=False
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(dates[-2] + pd.Timedelta(hours=10)).isoformat(),
    )
    complete.to_csv(inputs[1], index=False)
    result = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
    )
    assert result["manifest"]["closed_sessions"] == 2
    assert not event_values(inputs[3], "fill")
    assert len(event_values(inputs[3], "missed_execution_window")) == 9


def test_verify_reads_one_snapshot_while_another_writer_commits(inputs, monkeypatch):
    engine.run(*inputs)
    reader, writer = PaperStore(inputs[3]), PaperStore(inputs[3])
    original_books = reader.books

    def interleaved_books():
        with writer.writing():
            for key, book in writer.books().items():
                book["paused"] = True
                book["pause_reason"] = "concurrent valid update"
                writer.seal_book(key, book)
        return original_books()

    monkeypatch.setattr(reader, "books", interleaved_books)
    try:
        reader.verify()
    finally:
        reader.close()
        writer.close()
    assert engine.status(inputs[3])["status"] == "PAUSED"


def test_new_prospective_economic_review_with_zero_curves_is_inconclusive(inputs, tmp_path):
    calendar, _, last, _ = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    output = tmp_path / "review"
    result = CliRunner().invoke(
        app, ["economic-review", "--database", str(inputs[3]), "--output", str(output)]
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "INCONCLUSIVE"
    assert {"timestamp", "equity_mxn", "evidence_kind"} <= set(pd.read_csv(output / "curves.csv"))
    assert pd.read_csv(output / "curves.csv").empty


def market_fixture(inputs):
    xcals = pytest.importorskip("exchange_calendars")

    config = yaml.safe_load(inputs[0].read_text())
    config["data_kind"], config["price_basis"] = "market", "raw_with_actions"
    inputs[0].write_text(yaml.safe_dump(config), encoding="utf-8")
    panel = pd.read_csv(inputs[1])
    old_dates = panel.timestamp.unique()
    schedule = xcals.get_calendar("XNYS", start="2020-01-02", end="2020-06-30").schedule
    schedule = schedule.iloc[: len(old_dates) + 1]
    dates = pd.DatetimeIndex(pd.to_datetime(schedule.index, utc=True))
    date_map = dict(zip(old_dates, dates[:-1], strict=True))
    close_map = dict(zip(dates, pd.to_datetime(schedule["close"], utc=True), strict=True))
    panel.timestamp = panel.timestamp.map(date_map)
    panel["bar_end_utc"] = panel.timestamp.map(close_map)
    panel["observed_at_utc"] = panel.bar_end_utc + pd.Timedelta(minutes=1)
    panel["dividend"], panel["split_ratio"] = 0.0, 1.0
    panel.to_csv(inputs[1], index=False)
    fx = pd.read_csv(inputs[2])
    fx.timestamp = pd.to_datetime(dates[:-1], utc=True)
    fx.to_csv(inputs[2], index=False)
    calendar = inputs[1].parent / "official_calendar.csv"
    pd.DataFrame(
        {
            "session_open_utc": pd.to_datetime(schedule["open"], utc=True).to_numpy(),
            "session_close_utc": pd.to_datetime(schedule["close"], utc=True).to_numpy(),
        }
    ).to_csv(calendar, index=False)
    return calendar, close_map[dates[-2]] + pd.Timedelta(hours=1)


def test_market_calendar_is_mandatory_for_registration_and_every_resume(inputs):
    calendar, now = market_fixture(inputs)
    with pytest.raises(PersonalPaperError, match="require the official exchange calendar"):
        engine.run(*inputs, mode="prospective", now_utc=now.isoformat())
    assert not inputs[3].exists()
    before = engine.run(
        *inputs, mode="prospective", calendar_path=calendar, now_utc=now.isoformat()
    )
    assert before["manifest"]["calendar_verified"]
    assert before["manifest"]["calendar_name"] == "XNYS"
    assert len(before["manifest"]["calendar_versions"]) == 1
    with pytest.raises(PersonalPaperError, match="require the official exchange calendar"):
        engine.run(*inputs, mode="prospective", now_utc=now.isoformat())
    assert engine.status(inputs[3])["manifest"] == before["manifest"]


@pytest.mark.parametrize("fault", ["missing", "wrong_close", "weekend"])
def test_market_calendar_must_match_official_sessions_and_closes(inputs, fault):
    calendar, now = market_fixture(inputs)
    rows = pd.read_csv(calendar)
    if fault == "missing":
        rows = rows.drop(index=10)
    elif fault == "wrong_close":
        rows.loc[10, "session_close_utc"] = (
            pd.Timestamp(rows.loc[10, "session_close_utc"]) + pd.Timedelta(minutes=1)
        ).isoformat()
    else:
        rows.loc[2, "session_open_utc"] = "2020-01-04T14:30:00Z"
        rows.loc[2, "session_close_utc"] = "2020-01-04T21:00:00Z"
        rows = rows.sort_values("session_open_utc")
    rows.to_csv(calendar, index=False)
    with pytest.raises(PersonalPaperError, match="official XNYS"):
        engine.run(*inputs, mode="prospective", calendar_path=calendar, now_utc=now.isoformat())
    assert not inputs[3].exists()


def test_market_runtime_is_exact_and_recorded(inputs, monkeypatch):
    from quant_trade.personal_paper import config

    calendar, now = market_fixture(inputs)
    before = engine.run(
        *inputs, mode="prospective", calendar_path=calendar, now_utc=now.isoformat()
    )
    assert before["manifest"]["runtime_versions"] == config.runtime_versions()
    assert all(
        before["manifest"]["runtime_versions"][name] == expected
        for name, expected in config.PROSPECTIVE_RUNTIME.items()
    )
    changed = {**config.runtime_versions(), "numpy": "future-version"}
    monkeypatch.setattr(config, "runtime_versions", lambda: changed)
    with pytest.raises(PersonalPaperError, match="runtime differs from frozen protocol"):
        engine.run(*inputs, mode="prospective", calendar_path=calendar, now_utc=now.isoformat())
    assert engine.status(inputs[3])["manifest"] == before["manifest"]


@pytest.mark.parametrize("dependency", ["numpy", "exchange_calendars", "tzdata"])
def test_wrong_market_runtime_is_rejected_before_reading_or_creating_state(
    inputs, monkeypatch, dependency
):
    from quant_trade.personal_paper import config

    frozen = yaml.safe_load(inputs[0].read_text())
    frozen["data_kind"], frozen["price_basis"] = "market", "raw_with_actions"
    inputs[0].write_text(yaml.safe_dump(frozen), encoding="utf-8")
    changed = {**config.PROSPECTIVE_RUNTIME, dependency: "future-version"}
    monkeypatch.setattr(config, "runtime_versions", lambda: changed)
    with pytest.raises(PersonalPaperError, match="runtime differs from frozen protocol"):
        engine.run(*inputs, mode="prospective", now_utc="2026-10-05T00:00:00Z")
    assert not inputs[3].exists()


def test_python_version_is_observed_and_cannot_change_after_registration(inputs, monkeypatch):
    from quant_trade.personal_paper import config

    before = engine.run(*inputs)
    assert before["manifest"]["runtime_versions"]["python"] == config.runtime_versions()["python"]
    monkeypatch.setattr(
        config,
        "runtime_versions",
        lambda: {**before["manifest"]["runtime_versions"], "python": "3.99"},
    )
    with pytest.raises(PersonalPaperError, match="changed after sealing"):
        engine.run(*inputs)
    assert engine.status(inputs[3])["books"] == before["books"]


def test_changed_economic_protocol_requires_new_database(inputs, monkeypatch):
    before = engine.run(*inputs)
    original = engine.economic_protocol()
    assert before["manifest"]["economic_protocol"] == original
    monkeypatch.setattr(engine, "economic_protocol", lambda: {**original, "seed": 123})
    with pytest.raises(PersonalPaperError, match="changed after sealing"):
        engine.run(*inputs)
    assert engine.status(inputs[3])["books"] == before["books"]


def test_conservative_fee_reserve_does_not_trigger_unnecessary_sells(tmp_path):
    book = {
        "portfolio": "inverse_volatility",
        "cost_multiplier": 3,
        "cash_usd": 50.0,
        "initial_cash_usd": 1000.0,
        "positions": dict.fromkeys(engine.UNIVERSE, 1.9),
        "rebalance_count": 1,
        "paused": False,
        "costs_usd": 0.0,
        "pending_decided_at": "2020-01-01T21:00:00Z",
    }
    prices = dict.fromkeys(engine.UNIVERSE, 100.0)
    store = PaperStore(tmp_path / "unnecessary_sells.sqlite")
    try:
        with store.writing():
            engine._fill_target(
                store,
                "test",
                book,
                dict.fromkeys(prices, 0.19),
                prices,
                dict.fromkeys(prices, 1_000_000),
                "2020-01-02T14:31:00Z",
                {"costs": {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2}},
            )
        assert not event_values(tmp_path / "unnecessary_sells.sqlite", "order")
        assert book["cash_usd"] == 50.0 and book["costs_usd"] == 0
        assert book["positions"] == dict.fromkeys(engine.UNIVERSE, 1.9)
    finally:
        store.close()


@pytest.mark.parametrize("with_quotes", [False, True])
def test_decision_uses_actual_calculation_finish_and_late_open_keeps_valuation(
    inputs, monkeypatch, with_quotes
):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    wall_clock = {"now": last + pd.Timedelta(hours=10)}
    monkeypatch.setattr(engine, "clock", lambda: wall_clock["now"].isoformat())
    engine.run(*inputs, mode="prospective", calendar_path=calendar)
    wall_clock["now"] = nextdate + pd.Timedelta(hours=13, minutes=59)
    original = engine.target_at

    def slow_initial_calculation(*args, **kwargs):
        target = original(*args, **kwargs)
        wall_clock["now"] = nextdate + pd.Timedelta(hours=14, minutes=2)
        return target

    monkeypatch.setattr(engine, "target_at", slow_initial_calculation)
    result = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes if with_quotes else None,
    )
    assert not event_values(inputs[3], "fill")
    assert len(event_values(inputs[3], "missed_execution_window")) == 9
    for book in result["books"].values():
        assert book["pending_decided_at"] == wall_clock["now"].isoformat()
        assert book["last_timestamp"] == last.isoformat()
        assert book["pending"] is None
    assert result["manifest"]["closed_sessions"] == 1


@pytest.mark.parametrize("receipt_fault", ["before_bar_end", "future"])
def test_quotes_cannot_claim_impossible_receipt_timestamps(inputs, receipt_fault):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    frame = pd.read_csv(quotes)
    minutes = 0 if receipt_fault == "before_bar_end" else 3
    frame.received_at_utc = (nextdate + pd.Timedelta(hours=14, minutes=minutes)).isoformat()
    frame.to_csv(quotes, index=False)
    before = engine.status(inputs[3])["books"]
    with pytest.raises(PersonalPaperError, match="stale or invalid"):
        engine.run(
            *inputs,
            mode="prospective",
            calendar_path=calendar,
            quotes_path=quotes,
            now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
        )
    assert engine.status(inputs[3])["books"] == before
    assert not event_values(inputs[3], "fill")


def test_market_quotes_require_actual_receipt_timestamp(inputs):
    _, quotes, _, nextdate = prospective_fixture(inputs)
    frame = pd.read_csv(quotes).drop(columns="received_at_utc")
    frame.to_csv(quotes, index=False)
    store = PaperStore(inputs[3])
    try:
        with pytest.raises(PersonalPaperError, match="quotes require"):
            engine._execute_quotes(
                store,
                {},
                quotes,
                {"data_kind": "market"},
                pd.DataFrame(),
                nextdate + pd.Timedelta(hours=14, minutes=2),
                None,
            )
    finally:
        store.close()


@pytest.mark.parametrize(
    "source_fault", ["missing_column", "null", "empty", "whitespace", "numeric"]
)
def test_invalid_quote_source_never_fills_or_persists_partial_batch(inputs, source_fault):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    before = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    frame = pd.read_csv(quotes)
    if source_fault == "missing_column":
        frame = frame.drop(columns="source")
    elif source_fault == "numeric":
        frame["source"] = 123
    else:
        frame.loc[frame.index[-1], "source"] = {
            "null": np.nan,
            "empty": "",
            "whitespace": "   ",
        }[source_fault]
    frame.to_csv(quotes, index=False)
    with pytest.raises(PersonalPaperError, match="quote source|quotes require"):
        engine.run(
            *inputs,
            mode="prospective",
            calendar_path=calendar,
            quotes_path=quotes,
            now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
        )
    assert not event_values(inputs[3], "fill")
    assert not event_values(inputs[3], "quote_observation")
    after = engine.status(inputs[3])
    assert after["books"] == before["books"]
    assert after["manifest"] == before["manifest"]


@pytest.mark.parametrize("raw_actions", [False, True])
def test_quote_inputs_are_anchored_allowlisted_and_idempotent(inputs, raw_actions):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    if raw_actions:
        config = yaml.safe_load(inputs[0].read_text())
        config["price_basis"] = "raw_with_actions"
        inputs[0].write_text(yaml.safe_dump(config), encoding="utf-8")
        for path in (inputs[1], quotes):
            frame = pd.read_csv(path)
            frame["dividend"], frame["split_ratio"] = 0.0, 1.0
            frame.to_csv(path, index=False)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    frame = pd.read_csv(quotes)
    frame["irrelevant_note"] = "excluded from execution provenance"
    frame.to_csv(quotes, index=False)
    before = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
    )
    observations = event_values(inputs[3], "quote_observation")
    assert len(observations) == 1
    evidence = observations[0]
    assert evidence["quote_input_sha256"] == engine.digest(evidence["inputs"])
    expected_fields = {
        "symbol",
        "price_usd",
        "available_volume",
        "source",
        "observed_at_utc",
        "received_at_utc",
        "session_open_utc",
        "session_close_utc",
        "previous_session_date",
    }
    if raw_actions:
        expected_fields |= {"dividend", "split_ratio"}
    observed_quotes = evidence["inputs"]["quotes"]
    assert [quote["symbol"] for quote in observed_quotes] == sorted(engine.UNIVERSE)
    assert all(set(quote) == expected_fields for quote in observed_quotes)
    assert all(
        quote["price_usd"] > 0
        and quote["available_volume"] == 1_000_000
        and quote["source"] == "SYNTHETIC_FIXTURE"
        and quote["observed_at_utc"] == quote["received_at_utc"]
        for quote in observed_quotes
    )
    if raw_actions:
        assert all(
            quote["dividend"] == 0 and quote["split_ratio"] == 1 for quote in observed_quotes
        )
    assert evidence["inputs"]["fx"]["usd_mxn"] == 20
    assert set(evidence["inputs"]["fx"]) == {"usd_mxn", "source", "timestamp"}
    fills = event_values(inputs[3], "fill")
    assert len(fills) == 45
    assert all(fill["quote_input_sha256"] == evidence["quote_input_sha256"] for fill in fills)
    frame.iloc[::-1].to_csv(quotes, index=False)
    after = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        quotes_path=quotes,
        now_utc=(nextdate + pd.Timedelta(hours=14, minutes=3)).isoformat(),
    )
    assert event_values(inputs[3], "quote_observation") == observations
    assert event_values(inputs[3], "fill") == fills
    assert after["books"] == before["books"]


def test_quote_observation_rolls_back_together_with_failed_execution(inputs, monkeypatch):
    calendar, quotes, last, nextdate = prospective_fixture(inputs)
    engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=10)).isoformat(),
    )
    before = engine.run(
        *inputs,
        mode="prospective",
        calendar_path=calendar,
        now_utc=(last + pd.Timedelta(hours=22)).isoformat(),
    )
    original = engine._fill_target

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated failure after quote and first fills")

    monkeypatch.setattr(engine, "_fill_target", crash)
    with pytest.raises(RuntimeError, match="simulated failure"):
        engine.run(
            *inputs,
            mode="prospective",
            calendar_path=calendar,
            quotes_path=quotes,
            now_utc=(nextdate + pd.Timedelta(hours=14, minutes=2)).isoformat(),
        )
    assert not event_values(inputs[3], "fill")
    assert not event_values(inputs[3], "order")
    assert not event_values(inputs[3], "quote_observation")
    assert engine.status(inputs[3])["books"] == before["books"]
