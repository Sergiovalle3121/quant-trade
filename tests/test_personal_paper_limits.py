"""Frozen owner ceilings and the cash/position guard of every simulated fill."""

from __future__ import annotations

import dataclasses
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
import yaml

from quant_trade.personal_paper import engine
from quant_trade.personal_paper.config import UNIVERSE, PersonalPaperError, load_config
from quant_trade.personal_paper.store import PaperStore

FROZEN = {
    "schema_version": 1,
    "experiment_id": "synthetic_limits",
    "capital_mxn": 20000,
    "monthly_host_budget_mxn": 500,
    "data_kind": "synthetic",
    "price_basis": "adjusted_total_return",
    "max_drawdown": 0.05,
    "max_daily_loss": 0.02,
    "costs": {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2},
}


def _load(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    path = tmp_path / "limits.yaml"
    path.write_text(yaml.safe_dump({**FROZEN, **changes}), encoding="utf-8")
    return load_config(path)


def test_frozen_ceilings_are_accepted_exactly(tmp_path: Path):
    assert _load(tmp_path) == FROZEN
    for name in ("etf_private_v1.yaml", "synthetic_demo.yaml"):
        config = load_config(Path("configs/personal") / name)
        assert config["capital_mxn"] == 20000 and config["monthly_host_budget_mxn"] == 500
        assert config["max_drawdown"] == 0.05 and config["max_daily_loss"] == 0.02
        assert config["costs"] == FROZEN["costs"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capital_mxn", 20000.01, "ceilings are 20,000/500 MXN"),
        ("capital_mxn", 25000, "ceilings are 20,000/500 MXN"),
        ("monthly_host_budget_mxn", 500.01, "ceilings are 20,000/500 MXN"),
        ("monthly_host_budget_mxn", 1000, "ceilings are 20,000/500 MXN"),
        ("max_drawdown", 0.0501, "ceilings are 5%/2%"),
        ("max_drawdown", 0.10, "ceilings are 5%/2%"),
        ("max_daily_loss", 0.0201, "ceilings are 5%/2%"),
        ("max_daily_loss", 0.05, "ceilings are 5%/2%"),
        ("capital_mxn", 0, "must be finite and positive"),
        ("max_drawdown", -0.01, "must be finite and positive"),
        ("max_daily_loss", float("nan"), "must be finite and positive"),
        ("monthly_host_budget_mxn", float("inf"), "must be finite and positive"),
        ("capital_mxn", True, "must be finite and positive"),
    ],
)
def test_values_above_the_owner_ceilings_are_refused(
    tmp_path: Path, field: str, value: Any, message: str
):
    with pytest.raises(PersonalPaperError, match=message):
        _load(tmp_path, **{field: value})


@pytest.mark.parametrize(
    "costs",
    [
        {"commission_bps": 4, "slippage_bps": 5, "spread_bps": 2},
        {"commission_bps": 5, "slippage_bps": 6, "spread_bps": 2},
        {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 1},
        {"commission_bps": 0, "slippage_bps": 0, "spread_bps": 0},
        {"commission_bps": 5, "slippage_bps": 5},
        {"commission_bps": 5, "slippage_bps": 5, "spread_bps": 2, "borrow_bps": 0},
    ],
)
def test_declared_costs_are_fixed_to_5_5_2_bps(tmp_path: Path, costs: dict[str, int]):
    with pytest.raises(PersonalPaperError, match="5/5/2 bps"):
        _load(tmp_path, costs=costs)


@pytest.mark.parametrize("extra", [{"leverage": 2}, {"allow_short": True}])
def test_unknown_keys_cannot_widen_the_frozen_config(tmp_path: Path, extra: dict[str, Any]):
    with pytest.raises(PersonalPaperError, match="config must contain exactly"):
        _load(tmp_path, **extra)


def _book(cash: float, positions: dict[str, float]) -> dict[str, Any]:
    return {
        "portfolio": "equal_weight_quarterly",
        "cost_multiplier": 1,
        "initial_cash_usd": 1000.0,
        "cash_usd": cash,
        "positions": positions,
        "rebalance_count": 0,
        "costs_usd": 0.0,
        "paused": False,
        "pending_decided_at": "2026-10-05T20:00:00+00:00",
    }


def _events(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as db:
        return [row[0] for row in db.execute("SELECT kind FROM events ORDER BY sequence")]


@pytest.mark.parametrize(
    ("cash", "positions", "weight", "symbol"),
    [(1000.0, {}, 0.19, None), (500.0, {"SPY": 5.0}, 0.0, "SPY")],
    ids=["buy-would-borrow", "sell-would-short"],
)
def test_overfilled_executor_cannot_create_borrowing_or_shorting(
    tmp_path: Path,
    monkeypatch,
    cash: float,
    positions: dict[str, float],
    weight: float,
    symbol: str | None,
):
    """A defective fill larger than the sized order is refused and rolled back."""
    original = engine.execute_market_order_on_bar
    decisions = []

    def overfilled(*args, **kwargs):
        decision = original(*args, **kwargs)
        if decision is not None:
            decision = dataclasses.replace(decision, quantity=decision.quantity * 10)
            decisions.append(decision)
        return decision

    monkeypatch.setattr(engine, "execute_market_order_on_bar", overfilled)
    database = tmp_path / "guard.sqlite"
    book = _book(cash, dict(positions))
    store = PaperStore(database)
    try:
        with pytest.raises(PersonalPaperError, match="borrowing or shorting"), store.writing():
            engine._fill_target(
                store,
                "equal_weight_quarterly:1",
                book,
                dict.fromkeys(UNIVERSE, weight),
                dict.fromkeys(UNIVERSE, 100.0),
                dict.fromkeys(UNIVERSE, 1e9),
                "2026-10-06T13:30:00+00:00",
                FROZEN,
            )
    finally:
        store.close()
    assert len(decisions) == 1
    if symbol is None:
        assert decisions[0].side == "buy" and book["cash_usd"] < 0
    else:
        assert decisions[0].side == "sell" and book["positions"][symbol] < 0
    assert "fill" not in _events(database)  # the rolled-back transaction persisted no fill


def test_correctly_sized_fills_keep_cash_and_positions_nonnegative(tmp_path: Path):
    store = PaperStore(tmp_path / "sized.sqlite")
    book = _book(1000.0, {})
    try:
        with store.writing():
            engine._fill_target(
                store,
                "equal_weight_quarterly:1",
                book,
                dict.fromkeys(UNIVERSE, 0.25),
                dict.fromkeys(UNIVERSE, 100.0),
                dict.fromkeys(UNIVERSE, 1e9),
                "2026-10-06T13:30:00+00:00",
                FROZEN,
            )
    finally:
        store.close()
    assert book["rebalance_count"] == 1
    assert book["cash_usd"] >= 0.05 * 1000.0 - 1e-6
    assert all(quantity >= 0 for quantity in book["positions"].values())
    assert _events(tmp_path / "sized.sqlite").count("fill") == len(UNIVERSE)
