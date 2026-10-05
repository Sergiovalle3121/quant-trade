"""Credential-free private paper worker; free, delayed quotes may mean WAITING."""

from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.personal_paper import engine, fetch
from quant_trade.personal_paper.config import (
    PersonalPaperError,
    file_hash,
    load_config,
    validate_runtime,
)


@contextmanager
def worker_lease(path: Path):
    """An OS-owned byte lock is released automatically on process death."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            msvcrt: Any = importlib.import_module("msvcrt")

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise PersonalPaperError("another private worker is running") from exc
        else:
            fcntl: Any = importlib.import_module("fcntl")

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise PersonalPaperError("another private worker is running") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def budget_review(path: Path | None, now: pd.Timestamp, ceiling: float) -> dict[str, Any]:
    if path is None:
        return {
            "status": "UNOBSERVED",
            "ceiling_mxn": ceiling,
            "note": "No paid services are provisioned; economic review needs expense coverage.",
        }
    rows = pd.read_csv(path)
    if not {"start", "end", "category", "amount_mxn"} <= set(rows):
        raise PersonalPaperError("expense CSV requires start,end,category,amount_mxn")
    rows["start"] = rows.start.map(engine.utc)
    rows["end"] = rows.end.map(engine.utc)
    rows["amount_mxn"] = pd.to_numeric(rows.amount_mxn, errors="coerce")
    if (
        not np.isfinite(rows.amount_mxn).all()
        or (rows.amount_mxn < 0).any()
        or (rows.end <= rows.start).any()
    ):
        raise PersonalPaperError(
            "observed expenses must have positive intervals and finite amounts"
        )
    month = now.normalize().replace(day=1)
    following = month + pd.offsets.MonthBegin(1)
    total = float(rows.loc[(rows.start < following) & (rows.end > month), "amount_mxn"].sum())
    return {
        "status": "OVER_BUDGET" if total > ceiling else "WITHIN_DECLARED_BUDGET",
        "observed_mxn": total,
        "ceiling_mxn": ceiling,
    }


def _cached_snapshot(cache: Path, now: pd.Timestamp) -> Path | None:
    pointer = cache / "latest.txt"
    if not pointer.exists():
        return None
    path = Path(pointer.read_text(encoding="utf-8").strip()).resolve()
    if not path.is_relative_to(cache.resolve()):
        raise PersonalPaperError("snapshot pointer escaped the private cache")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files_sha256"].items():
        target = (path / name).resolve()
        if not target.is_relative_to(path) or file_hash(target) != expected:
            raise PersonalPaperError("provider snapshot hash mismatch")
    retrieved = engine.utc(manifest["retrieved_at_utc"])
    if retrieved.date() != now.date():
        return None
    calendar = pd.read_csv(path / "calendar.csv")
    calendar["session_close_utc"] = calendar.session_close_utc.map(engine.utc)
    expected = calendar[calendar.session_close_utc <= now]
    panel = pd.read_csv(path / "panel.csv")
    if not expected.empty:
        latest = expected.session_close_utc.max()
        if latest > panel.bar_end_utc.map(engine.utc).max():
            return None
    return path


def run_once(
    config: Path,
    database: Path,
    cache: Path,
    *,
    start: str = "2020-01-02",
    expenses: Path | None = None,
) -> dict[str, Any]:
    frozen = load_config(config)
    if frozen["data_kind"] != "market" or frozen["price_basis"] != "raw_with_actions":
        raise PersonalPaperError("autonomous fetching requires a market/raw_with_actions config")
    validate_runtime(frozen, "prospective")
    now = pd.Timestamp(datetime.now(UTC))
    with worker_lease(database.with_suffix(".worker.lock")):
        budget = budget_review(expenses, now, frozen["monthly_host_budget_mxn"])
        if budget["status"] == "OVER_BUDGET":
            if database.exists():
                engine.pause(database, "observed monthly budget exceeded")
            return {"status": "BUDGET_PAUSED", "budget": budget, "real_money_approved": False}
        snapshot = _cached_snapshot(cache, now) or fetch.fetch_snapshot(start, cache)
        result = engine.run(
            config,
            snapshot / "panel.csv",
            snapshot / "fx.csv",
            database,
            mode="prospective",
            calendar_path=snapshot / "calendar.csv",
        )
        quotes = fetch.fetch_open_quotes(cache / "quotes")
        if quotes is not None:
            result = engine.run(
                config,
                snapshot / "panel.csv",
                snapshot / "fx.csv",
                database,
                mode="prospective",
                quotes_path=quotes,
                calendar_path=snapshot / "calendar.csv",
            )
        result["worker"] = {
            "quotes": "OBSERVED_SIMULATION" if quotes else "WAITING",
            "snapshot": str(snapshot),
            "budget": budget,
            "quote_limitations": "Delayed 1m prices; missed opening windows expire.",
        }
        cache.mkdir(parents=True, exist_ok=True)
        temporary = cache / "worker_status.tmp"
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(cache / "worker_status.json")
        return result
