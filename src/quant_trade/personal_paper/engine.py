from __future__ import annotations

import csv
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.data.panel import validate_panel_schema
from quant_trade.execution.bar_model import (
    BarExecutionPolicy,
    BarOrderState,
    execute_market_order_on_bar,
)
from quant_trade.personal_paper.actions import apply_actions, signal_panel, validate_actions
from quant_trade.personal_paper.config import (
    PORTFOLIOS,
    UNIVERSE,
    PersonalPaperError,
    digest,
    execution_code_hash,
    file_hash,
    load_config,
    validate_runtime,
)
from quant_trade.personal_paper.economic import economic_protocol
from quant_trade.personal_paper.store import PaperStore
from quant_trade.research.strategy_registry import get_research_signal_model

COST_MULTIPLIERS = (1, 2, 3)
MAX_FX_AGE_DAYS = 7
OPEN_WINDOW_SECONDS = 300


def utc(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise PersonalPaperError("operational timestamps must include a timezone")
    return parsed.tz_convert("UTC")


def clock() -> str:
    return datetime.now(UTC).isoformat()


def _processing_time(initial: pd.Timestamp, test_clock: bool) -> pd.Timestamp:
    return initial if test_clock else max(initial, utc(clock()))


def _validate_calendar(calendar: pd.DataFrame, require_official: bool) -> None:
    if not {"session_open_utc", "session_close_utc"} <= set(calendar):
        raise PersonalPaperError("calendar needs session_open_utc and session_close_utc")
    opens = calendar.session_open_utc.map(utc)
    closes = calendar.session_close_utc.map(utc)
    if (
        calendar.empty
        or (closes <= opens).any()
        or opens.duplicated().any()
        or opens.dt.date.duplicated().any()
        or not opens.is_monotonic_increasing
    ):
        raise PersonalPaperError("invalid session calendar")
    if require_official:
        import exchange_calendars as xcals

        schedule = xcals.get_calendar(
            "XNYS", start=str(opens.iloc[0].date()), end=str(opens.iloc[-1].date())
        ).schedule
        expected_opens = pd.DatetimeIndex(pd.to_datetime(schedule["open"], utc=True))
        expected_closes = pd.DatetimeIndex(pd.to_datetime(schedule["close"], utc=True))
        if not pd.DatetimeIndex(opens).equals(expected_opens) or not pd.DatetimeIndex(
            closes
        ).equals(expected_closes):
            raise PersonalPaperError("calendar must match every official XNYS session exactly")


def load_inputs(
    data_path: Path,
    fx_path: Path,
    config: dict[str, Any],
    mode: str,
    now: pd.Timestamp,
    calendar_path: Path | None = None,
):
    if mode not in {"development", "prospective"}:
        raise PersonalPaperError("mode must be development or prospective")
    require_official = mode == "prospective" and config["data_kind"] == "market"
    if require_official and calendar_path is None:
        raise PersonalPaperError("market prospective runs require the official exchange calendar")
    if (
        mode == "prospective"
        and config["data_kind"] == "market"
        and config["price_basis"] != "raw_with_actions"
    ):
        raise PersonalPaperError("market prospective fills require raw prices and explicit actions")
    raw = pd.read_csv(data_path)
    panel = validate_panel_schema(raw)
    if (panel.timestamp != panel.timestamp.dt.normalize()).any():
        raise PersonalPaperError("daily session timestamps must be UTC midnight labels")
    if (panel.timestamp > now).any():
        raise PersonalPaperError("future sessions are not observable")
    if not np.isfinite(panel[["open", "high", "low", "close", "volume"]].to_numpy()).all():
        raise PersonalPaperError("market inputs must be finite")
    if config["price_basis"] == "raw_with_actions":
        validate_actions(panel)
        for column in ("dividend", "split_ratio"):
            panel[column] = pd.to_numeric(panel[column])
    if set(panel.symbol) != set(UNIVERSE):
        raise PersonalPaperError("the frozen universe must contain exactly GLD,IWM,QQQ,SPY,TLT")
    if (panel.groupby("timestamp").symbol.nunique() != len(UNIVERSE)).any():
        raise PersonalPaperError("a session is missing a universe member; no forward-filled bars")
    if mode == "prospective":
        required = {"bar_end_utc", "observed_at_utc"}
        if not required <= set(panel.columns):
            raise PersonalPaperError("prospective bars require close and observation timestamps")
        for key in required:
            panel[key] = panel[key].map(utc)
        if (
            (panel.observed_at_utc < panel.bar_end_utc) | (panel.bar_end_utc <= panel.timestamp)
        ).any():
            raise PersonalPaperError("a close cannot be known before its bar ends")
        panel = panel[(panel.bar_end_utc <= now) & (panel.observed_at_utc <= now)].copy()
        if (panel.groupby("timestamp").symbol.nunique() != len(UNIVERSE)).any():
            raise PersonalPaperError("not all universe closes are observable yet")
        if (panel.groupby("timestamp").bar_end_utc.nunique() != 1).any():
            raise PersonalPaperError("universe members disagree on session closing time")
    if panel.empty or panel.timestamp.nunique() < 65:
        raise PersonalPaperError("at least 65 complete sessions are required for warm-up")
    dates = pd.DatetimeIndex(sorted(panel.timestamp.unique()))
    if (dates.to_series().diff().dropna() > pd.Timedelta(days=7)).any():
        raise PersonalPaperError("a gap exceeds seven days; supply a verified session calendar")
    if calendar_path is not None:
        calendar = pd.read_csv(calendar_path)
        _validate_calendar(calendar, require_official)
        opens = calendar.session_open_utc.map(utc)
        closes = calendar.session_close_utc.map(utc)
        expected = set(opens.dt.date)
        expected = {d for d in expected if dates[0].date() <= d <= dates[-1].date()}
        if expected != set(dates.date):
            raise PersonalPaperError("dataset sessions do not match the supplied exchange calendar")
        if require_official and not (opens.dt.date > dates[-1].date()).any():
            raise PersonalPaperError("official calendar must include the next execution session")
        if mode == "prospective":
            calendar_closes = dict(zip(opens.dt.date, closes, strict=True))
            if any(
                utc(r.bar_end_utc) != calendar_closes[r.timestamp.date()]
                for r in panel.itertuples()
            ):
                raise PersonalPaperError(
                    "daily close timestamps disagree with the exchange calendar"
                )
    fx = pd.read_csv(fx_path)
    if not {"timestamp", "usd_mxn", "source"} <= set(fx):
        raise PersonalPaperError("FX requires timestamp, usd_mxn and source")
    fx["timestamp"] = fx.timestamp.map(utc)
    fx["usd_mxn"] = pd.to_numeric(fx.usd_mxn, errors="coerce")
    if (
        not np.isfinite(fx.usd_mxn.to_numpy()).all()
        or (fx.usd_mxn <= 0).any()
        or fx.timestamp.duplicated().any()
        or fx.source.isna().any()
        or (fx.source.astype(str).str.strip() == "").any()
    ):
        raise PersonalPaperError("FX must be positive, finite, sourced and non-duplicate")
    fx = fx.sort_values("timestamp")
    # Implausible raw splits cannot be smoothed into a convenient return series.
    returns = (
        signal_panel(panel, config["price_basis"])
        .pivot(index="timestamp", columns="symbol", values="close")
        .pct_change()
    )
    if (returns.abs() > 0.40).any().any():
        raise PersonalPaperError("price discontinuity needs corporate-action/data review")
    return panel, fx


def fx_at(fx: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, Any]:
    available = fx[fx.timestamp <= timestamp]
    if available.empty:
        raise PersonalPaperError(f"no observable USD/MXN source at {timestamp}")
    row = available.iloc[-1]
    if timestamp - row.timestamp > pd.Timedelta(days=MAX_FX_AGE_DAYS):
        raise PersonalPaperError("USD/MXN observation is stale")
    return {
        "usd_mxn": float(row.usd_mxn),
        "source": str(row.source),
        "timestamp": row.timestamp.isoformat(),
    }


def target_at(
    panel: pd.DataFrame, strategy: str, timestamp: pd.Timestamp, initialize: bool = False
) -> dict[str, float] | None:
    params = dict(PORTFOLIOS[strategy])
    if initialize:
        # Deployment is a declared initial investment, even mid-quarter, using
        # today's causal weights. Subsequent rebalances retain their actual cadence.
        params["rebalance_frequency"] = "daily"
    prefix = panel[panel.timestamp <= timestamp]
    signals = get_research_signal_model(strategy).generate(prefix, params)
    latest = signals[signals.timestamp == timestamp]
    if latest.empty:
        return None
    return _validated_weights(latest, strategy)


def _validated_weights(signals: pd.DataFrame, strategy: str) -> dict[str, float]:
    if len(signals) != len(UNIVERSE) or set(signals.symbol) != set(UNIVERSE):
        raise PersonalPaperError("a signal must contain the complete frozen universe exactly once")
    originals = {str(r.symbol): float(r.target_weight) for r in signals.itertuples()}
    if not all(math.isfinite(v) for v in originals.values()):
        raise PersonalPaperError("a signal generated non-finite weights")
    cap = float(PORTFOLIOS[strategy]["max_weight_per_asset"])
    values = {s: min(cap, max(0.0, v)) for s, v in originals.items()}
    gross = math.fsum(values[symbol] for symbol in sorted(values))
    scale = min(1.0, 0.95 / gross) if gross else 1.0
    return {s: w * scale for s, w in values.items()}


def _equity(book: dict[str, Any], prices: dict[str, float]) -> float:
    return math.fsum(
        [
            book["cash_usd"],
            *(book["positions"][symbol] * prices[symbol] for symbol in sorted(book["positions"])),
        ]
    )


def _risk(
    book: dict[str, Any],
    prices: dict[str, float],
    rate: float,
    config: dict[str, Any],
    store: PaperStore,
    key: str,
    timestamp: str,
) -> None:
    equity_mxn = _equity(book, prices) * rate
    book["high_water_mxn"] = max(book["high_water_mxn"], equity_mxn)
    book["drawdown"] = max(0.0, 1 - equity_mxn / book["high_water_mxn"])
    daily_loss = 1 - equity_mxn / max(book["day_start_mxn"], 1e-9)
    reason = None
    if book["drawdown"] >= config["max_drawdown"] - 1e-12:
        reason = "drawdown_limit_5pct"
    elif daily_loss >= config["max_daily_loss"]:
        reason = "daily_loss_limit"
    if reason and not book["paused"]:
        book["paused"], book["pause_reason"] = True, reason
        store.event("pause", {"book": key, "reason": reason, "timestamp": timestamp})
    book["last_prices"], book["last_fx"] = prices, rate


def _fill_target(
    store: PaperStore,
    key: str,
    book: dict[str, Any],
    target: dict[str, float],
    prices: dict[str, float],
    volumes: dict[str, float],
    when: str,
    config: dict[str, Any],
    quote_input_sha256: str | None = None,
) -> None:
    if set(target) != set(UNIVERSE) or not all(math.isfinite(float(v)) for v in target.values()):
        raise PersonalPaperError("execution target must be complete and finite")
    equity = _equity(book, prices)
    fee_fraction = sum(config["costs"].values()) * book["cost_multiplier"] / 10000
    # A full switch costs at most 2 * equity * fee_fraction. Size every target
    # against this lower bound so costs cannot push new holdings over their cap.
    equity_floor = equity * (1 - 2 * fee_fraction)
    cap = float(PORTFOLIOS[book["portfolio"]]["max_weight_per_asset"])
    current_gross = math.fsum(
        book["positions"][symbol] * prices[symbol] for symbol in sorted(book["positions"])
    )
    minimum = book["initial_cash_usd"] * 0.005
    weights = {
        s: min(
            float(PORTFOLIOS[book["portfolio"]]["max_weight_per_asset"]),
            max(0.0, target.get(s, 0.0)),
        )
        for s in UNIVERSE
    }
    gross = math.fsum(weights[symbol] for symbol in sorted(weights))
    if gross > 0.95:
        weights = {s: w * 0.95 / gross for s, w in weights.items()}
    orders = []
    for sym in UNIVERSE:
        held = book["positions"].get(sym, 0.0) * prices[sym]
        delta = weights[sym] * equity_floor - held
        risk_reduction = delta < 0 and (
            held > cap * equity + 1e-8 or current_gross > 0.95 * equity + 1e-8
        )
        if not risk_reduction and (
            abs(delta) < minimum
            or (book["rebalance_count"] and abs(delta) / max(equity, 1e-9) < 0.05)
        ):
            continue
        if delta > 0 and book["paused"]:
            continue
        orders.append((delta, sym, risk_reduction))
    filled_any = False
    for delta, sym, risk_reduction in sorted(orders):
        if delta > 0:
            current_equity = _equity(book, prices)
            held_values = {
                symbol: book["positions"][symbol] * prices[symbol]
                for symbol in sorted(book["positions"])
            }
            gross_value = math.fsum(held_values.values())
            if (
                any(v > cap * current_equity + 1e-8 for v in held_values.values())
                or gross_value > 0.95 * current_equity + 1e-8
            ):
                continue  # incomplete risk reductions must finish before additions
            allowed = max(0.0, book["cash_usd"] - 0.05 * current_equity) / (1 + 0.95 * fee_fraction)
            asset_room = max(0.0, cap * current_equity - held_values.get(sym, 0.0)) / (
                1 + cap * fee_fraction
            )
            gross_room = max(0.0, 0.95 * current_equity - gross_value) / (1 + 0.95 * fee_fraction)
            delta = min(delta, allowed, asset_room, gross_room)
        else:
            delta = max(delta, -book["positions"].get(sym, 0.0) * prices[sym])
        if abs(delta) < minimum and not risk_reduction:
            continue
        order_id = digest(
            {
                "book": key,
                "decision": book["pending_decided_at"],
                "execution": when,
                "symbol": sym,
                "side": "buy" if delta > 0 else "sell",
            }
        )
        order = BarOrderState(order_id, sym, delta / prices[sym], 0, 1)
        decision = execute_market_order_on_bar(
            order,
            bar_index=1,
            open_price=prices[sym],
            volume=volumes.get(sym),
            policy=BarExecutionPolicy(
                max_volume_participation_rate=0.0001, lot_size=0.000001, max_order_age_bars=0
            ),
        )
        store.event(
            "order",
            {
                "book": key,
                "order_id": order_id,
                "status": order.status,
                "quantity": abs(delta / prices[sym]),
                "timestamp": when,
            },
        )
        if decision is None:
            continue
        fee = decision.quantity * decision.price * fee_fraction
        signed = decision.quantity * (1 if delta > 0 else -1)
        book["positions"][sym] = book["positions"].get(sym, 0.0) + signed
        book["cash_usd"] -= signed * decision.price + fee
        if book["cash_usd"] < -1e-8 or book["positions"][sym] < -1e-8:
            raise PersonalPaperError("fill would create borrowing or shorting")
        store.event(
            "fill",
            {
                "book": key,
                "order_id": order_id,
                "timestamp": when,
                "symbol": sym,
                "side": decision.side,
                "quantity": decision.quantity,
                "price": decision.price,
                "fee_usd": fee,
                "cost_evidence": "ASSUMPTION",
                "real_money_approved": False,
                **({"quote_input_sha256": quote_input_sha256} if quote_input_sha256 else {}),
            },
        )
        book["costs_usd"] += fee
        filled_any = True
    if filled_any:
        book["rebalance_count"] += 1


def _snapshot(
    store: PaperStore,
    key: str,
    book: dict[str, Any],
    timestamp: str,
    observation: dict[str, Any],
    evidence_kind: str,
) -> None:
    equity = _equity(book, book["last_prices"])
    payload = {
        "timestamp": timestamp,
        "portfolio": book["portfolio"],
        "cost_multiplier": book["cost_multiplier"],
        "equity_usd": equity,
        "equity_mxn": equity * observation["usd_mxn"],
        "cash_usd": book["cash_usd"],
        "drawdown": book["drawdown"],
        "status": "PAUSED" if book["paused"] else "OBSERVING",
        "rebalance_count": book["rebalance_count"],
        "costs_usd": book["costs_usd"],
        "cost_evidence": "ASSUMPTION",
        "fx_source": observation["source"],
        "fx_timestamp": observation["timestamp"],
        "usd_mxn": observation["usd_mxn"],
        "evidence_kind": evidence_kind,
        "real_money_approved": False,
    }
    store.db.execute(
        "INSERT OR REPLACE INTO curves VALUES (?,?,?)",
        (timestamp, key, json.dumps(payload, allow_nan=False)),
    )
    store.event("curve", {"timestamp": timestamp, "book": key, "sha": digest(payload)})
    store.seal_book(key, book)


def _register(
    store: PaperStore,
    config: dict[str, Any],
    data_path: Path,
    fx_path: Path,
    config_path: Path,
    panel: pd.DataFrame,
    fx: pd.DataFrame,
    mode: str,
    now: pd.Timestamp,
    test_clock: bool,
    runtime: dict[str, str],
    calendar_path: Path | None,
) -> dict[str, Any]:
    manifest = store.get("manifest")
    config_sha = digest(config)
    code_sha = execution_code_hash()
    protocol = economic_protocol()
    protocol_sha = digest(protocol)
    if manifest:
        if (
            manifest["config_sha256"] != config_sha
            or manifest["code_sha256"] != code_sha
            or manifest["mode"] != mode
            or manifest["clock_source"] != ("INJECTED_TEST_CLOCK" if test_clock else "SYSTEM_UTC")
            or manifest.get("runtime_versions") != runtime
            or manifest.get("economic_protocol") != protocol
            or manifest.get("economic_protocol_sha256") != protocol_sha
        ):
            raise PersonalPaperError(
                "config/code/runtime/economic protocol/mode changed after sealing; "
                "use a new database"
            )
        return manifest
    ledger = Path(__file__).resolve().parents[3] / "docs/real_data_evidence/trial_ledger.jsonl"
    trials = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    git_worktree_dirty: bool | None = None
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ledger.parents[2],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_worktree_dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=ledger.parents[2],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        git_commit = "UNAVAILABLE"
    manifest = {
        "schema_version": 1,
        "experiment_id": config["experiment_id"],
        "mode": mode,
        "registered_at": now.isoformat(),
        "clock_source": "INJECTED_TEST_CLOCK" if test_clock else "SYSTEM_UTC",
        "prospective_started_at": now.isoformat() if mode == "prospective" else None,
        "config_sha256": config_sha,
        "config_file_sha256": file_hash(config_path),
        "code_sha256": code_sha,
        "runtime_versions": runtime,
        "economic_protocol": protocol,
        "economic_protocol_sha256": protocol_sha,
        "git_commit": git_commit,
        "git_worktree_dirty": git_worktree_dirty,
        "dataset_sha256": file_hash(data_path),
        "fx_sha256": file_hash(fx_path),
        "dataset_versions": [file_hash(data_path)],
        "evidence_kind": (
            "SYNTHETIC"
            if config["data_kind"] == "synthetic"
            else "TEST_CLOCK_SIMULATION"
            if test_clock
            else "PROSPECTIVE_SIMULATION"
            if mode == "prospective"
            else "DEVELOPMENT_REPLAY"
        ),
        "price_basis": config["price_basis"],
        "data_kind": config["data_kind"],
        "capital_mxn": config["capital_mxn"],
        "risk_limits": {
            "max_drawdown": config["max_drawdown"],
            "max_daily_loss": config["max_daily_loss"],
        },
        "capital_policy": (
            "Each portfolio is an independent hypothetical alternative, not pooled capital"
        ),
        "historical_trial_ids": [digest(t) for t in trials],
        "historical_trials": trials,
        "historical_ledger_sha256": file_hash(ledger),
        "trial_ids": [
            digest({"config": config_sha, "strategy": s, "params": PORTFOLIOS[s]})
            for s in PORTFOLIOS
            if s != "equal_weight_quarterly"
        ],
        "portfolios": PORTFOLIOS,
        "cost_multipliers": list(COST_MULTIPLIERS),
        "cost_evidence": "ASSUMPTION",
        "development_liquidity_basis": "previous_closed_session_volume_proxy"
        if mode == "development"
        else None,
        "real_money_approved": False,
        "closed_sessions": 0,
        "calendar_checked": False,
        "calendar_verified": mode == "prospective" and config["data_kind"] == "market",
        "calendar_name": "XNYS"
        if mode == "prospective" and config["data_kind"] == "market"
        else None,
        "calendar_versions": [file_hash(calendar_path)] if calendar_path is not None else [],
        "startup_policy": (
            "First new closed session after sealing; one initial decision opportunity"
        ),
    }
    first = sorted(panel.timestamp.unique())[64] if mode == "development" else panel.timestamp.max()
    observation = fx_at(fx, now if mode == "prospective" else first)
    initial = config["capital_mxn"] / observation["usd_mxn"]
    prices = {str(r.symbol): float(r.close) for r in panel[panel.timestamp == first].itertuples()}
    previous = sorted(panel.timestamp.unique())[63]
    for strategy in PORTFOLIOS:
        for mult in COST_MULTIPLIERS:
            key = f"{strategy}@{mult}x"
            decision_date = first if mode == "prospective" else previous
            book = {
                "portfolio": strategy,
                "cost_multiplier": mult,
                "initial_cash_usd": initial,
                "cash_usd": initial,
                "positions": {},
                "actions_seen": {},
                "last_prices": prices,
                "last_fx": observation["usd_mxn"],
                "costs_usd": 0.0,
                "high_water_mxn": config["capital_mxn"],
                "day_start_mxn": config["capital_mxn"],
                "day_date": None,
                "drawdown": 0.0,
                "paused": False,
                "pause_reason": None,
                "rebalance_count": 0,
                "last_timestamp": None,
                "initial_decision_created": mode == "development",
                "pending": None
                if mode == "prospective"
                else target_at(
                    signal_panel(panel, config["price_basis"]),
                    strategy,
                    decision_date,
                    initialize=True,
                ),
                "pending_decided_at": (now if mode == "prospective" else decision_date).isoformat(),
                "pending_session_date": str(pd.Timestamp(decision_date).date()),
            }
            store.seal_book(key, book)
    store.seal_manifest(manifest)
    store.event("registration", {**manifest, "historical_trials": None})
    return manifest


def _expire_missed_decisions(
    store: PaperStore,
    books: dict[str, dict[str, Any]],
    calendar_path: Path | None,
    now: pd.Timestamp,
) -> None:
    if calendar_path is None:
        return
    calendar = pd.read_csv(calendar_path)
    openings = calendar.session_open_utc.map(utc).sort_values()
    for key, book in books.items():
        if book["pending"] is None:
            continue
        following = openings[openings.dt.date > pd.Timestamp(book["pending_session_date"]).date()]
        if following.empty:
            continue
        opened = following.iloc[0]
        created_after_open = now >= opened and utc(book["pending_decided_at"]) >= opened
        if created_after_open or now > opened + pd.Timedelta(seconds=OPEN_WINDOW_SECONDS):
            store.event(
                "missed_execution_window",
                {
                    "book": key,
                    "timestamp": now.isoformat(),
                    "reason": "decision was computed after the next session had opened"
                    if created_after_open
                    else "no fresh observable quote arrived before deadline",
                },
            )
            book["pending"] = None


def run(
    config_path: Path,
    data_path: Path,
    fx_path: Path,
    database: Path,
    *,
    mode: str = "development",
    now_utc: str | None = None,
    quotes_path: Path | None = None,
    calendar_path: Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    runtime = validate_runtime(config, mode)
    now = utc(now_utc or clock())
    panel, fx = load_inputs(data_path, fx_path, config, mode, now, calendar_path)
    store = PaperStore(database)
    signal_data = signal_panel(panel, config["price_basis"])
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for strategy, params in PORTFOLIOS.items():
        signals = get_research_signal_model(strategy).generate(signal_data, params)
        targets[strategy] = {}
        for timestamp, group in signals.groupby("timestamp"):
            targets[strategy][pd.Timestamp(timestamp)] = _validated_weights(group, strategy)
    try:
        with store.writing():
            store.verify()
            now = _processing_time(now, now_utc is not None)
            manifest = _register(
                store,
                config,
                data_path,
                fx_path,
                config_path,
                panel,
                fx,
                mode,
                now,
                now_utc is not None,
                runtime,
                calendar_path,
            )
            books = store.books()
            if mode == "prospective":
                _expire_missed_decisions(store, books, calendar_path, now)
            dates = sorted(panel.timestamp.unique())
            # Previously consumed observations must be a byte-stable prefix.
            stored_dates = {r[0] for r in store.db.execute("SELECT timestamp FROM bars")}
            if not stored_dates <= {pd.Timestamp(d).isoformat() for d in dates}:
                raise PersonalPaperError("previously observed sessions were removed")
            for session_index, date in enumerate(dates):
                stamp = pd.Timestamp(date)
                observation = fx_at(fx, stamp)
                frame = panel[panel.timestamp == date]
                stable_columns = [c for c in frame if c != "observed_at_utc"]
                sha = digest(
                    {"bar": frame[stable_columns].astype(str).to_dict("records"), "fx": observation}
                )
                old = store.db.execute(
                    "SELECT sha FROM bars WHERE timestamp=?", (stamp.isoformat(),)
                ).fetchone()
                if old and old[0] != sha:
                    raise PersonalPaperError("previously observed market/FX bytes changed")
                if old:
                    continue
                store.db.execute("INSERT INTO bars VALUES (?,?)", (stamp.isoformat(), sha))
                store.event("bar", {"timestamp": stamp.isoformat(), "sha": sha})
                if mode == "development" and date < dates[64]:
                    continue
                close_at = utc(frame.bar_end_utc.iloc[0]) if mode == "prospective" else stamp
                if mode == "prospective" and close_at <= utc(manifest["registered_at"]):
                    continue
                prices = {str(r.symbol): float(r.close) for r in frame.itertuples()}
                opens = {str(r.symbol): float(r.open) for r in frame.itertuples()}
                # Today's full-day volume is unknown at its opening. This is a
                # declared sizing proxy from the immediately preceding closed
                # session, not observed executable opening liquidity.
                previous_frame = (
                    panel[panel.timestamp == dates[session_index - 1]]
                    if mode == "development"
                    else frame
                )
                volumes = {str(r.symbol): float(r.volume) for r in previous_frame.itertuples()}
                for key, book in books.items():
                    if book["day_date"] != str(stamp.date()):
                        book["day_start_mxn"] = _equity(book, book["last_prices"]) * book["last_fx"]
                        book["day_date"] = str(stamp.date())
                    if config["price_basis"] == "raw_with_actions":
                        apply_actions(store, key, book, frame, str(stamp.date()))
                    # prospective warm-up is observation-only: fills must use current quotes.
                    if mode == "development":
                        _risk(
                            book,
                            opens,
                            observation["usd_mxn"],
                            config,
                            store,
                            key,
                            stamp.isoformat(),
                        )
                        if book["pending"] is not None:
                            _fill_target(
                                store,
                                key,
                                book,
                                book["pending"],
                                opens,
                                volumes,
                                stamp.isoformat(),
                                config,
                            )
                            book["pending"] = None
                    _risk(
                        book, prices, observation["usd_mxn"], config, store, key, stamp.isoformat()
                    )
                    target = targets[book["portfolio"]].get(stamp)
                    if mode == "prospective" and not book["initial_decision_created"]:
                        target = target_at(signal_data, book["portfolio"], stamp, initialize=True)
                        book["initial_decision_created"] = True
                    if target is not None:
                        book["pending"] = target
                        book["pending_decided_at"] = (
                            _processing_time(now, now_utc is not None).isoformat()
                            if mode == "prospective"
                            else close_at.isoformat()
                        )
                        book["pending_session_date"] = str(stamp.date())
                    book["last_timestamp"] = stamp.isoformat()
                    _snapshot(
                        store,
                        key,
                        book,
                        close_at.isoformat(),
                        observation,
                        manifest["evidence_kind"],
                    )
                manifest["closed_sessions"] += 1
            if mode == "prospective":
                # Catch-up may have created an initial/monthly decision whose
                # opening window is already past. Expire it before current quotes.
                now = _processing_time(now, now_utc is not None)
                _expire_missed_decisions(store, books, calendar_path, now)
                if quotes_path is not None:
                    _execute_quotes(store, books, quotes_path, config, fx, now, calendar_path)
            for key, book in books.items():
                store.seal_book(key, book)
            version = file_hash(data_path)
            if version not in manifest["dataset_versions"]:
                manifest["dataset_versions"].append(version)
            manifest["latest_dataset_sha256"] = version
            manifest["calendar_checked"] = manifest["calendar_checked"] or calendar_path is not None
            if calendar_path is not None:
                calendar_sha = file_hash(calendar_path)
                if calendar_sha not in manifest["calendar_versions"]:
                    manifest["calendar_versions"].append(calendar_sha)
                manifest["latest_calendar_sha256"] = calendar_sha
            manifest["last_checked_at"] = now.isoformat()
            store.seal_manifest(manifest)
            store.verify()
        return status(database, now_utc=now.isoformat())
    finally:
        store.close()


def _execute_quotes(
    store: PaperStore,
    books: dict[str, dict[str, Any]],
    path: Path,
    config: dict[str, Any],
    fx: pd.DataFrame,
    now: pd.Timestamp,
    calendar_path: Path | None,
) -> None:
    quotes = pd.read_csv(path)
    required = {
        "symbol",
        "price",
        "observed_at_utc",
        "session_open_utc",
        "session_close_utc",
        "previous_session_date",
        "source",
        "available_volume",
    }
    if config["data_kind"] == "market":
        required.add("received_at_utc")
    if not required <= set(quotes) or set(quotes.symbol) != set(UNIVERSE) or len(quotes) != 5:
        raise PersonalPaperError("quotes require one complete universe and observable liquidity")
    prices, volumes = {}, {}
    quote_rows: list[dict[str, Any]] = []
    for row in quotes.itertuples():
        if not isinstance(row.source, str) or not row.source.strip():
            raise PersonalPaperError("quote source must be a non-empty string")
        for name in ("price", "available_volume"):
            value = float(getattr(row, name))
            if not math.isfinite(value) or value <= 0:
                raise PersonalPaperError("quote prices/liquidity must be finite and positive")
        opened, closed, observed = (
            utc(row.session_open_utc),
            utc(row.session_close_utc),
            utc(row.observed_at_utc),
        )
        received = utc(row.received_at_utc) if "received_at_utc" in quotes else observed
        if (
            closed <= opened
            or not opened <= observed <= received <= now < closed
            or (now - observed).total_seconds() > OPEN_WINDOW_SECONDS
        ):
            raise PersonalPaperError("quote/session observation is stale or invalid")
        prices[str(row.symbol)], volumes[str(row.symbol)] = (
            float(row.price),
            float(row.available_volume),
        )
        quote_rows.append(
            {
                "symbol": str(row.symbol),
                "price_usd": float(row.price),
                "available_volume": float(row.available_volume),
                "source": row.source.strip(),
                "observed_at_utc": observed.isoformat(),
                "received_at_utc": received.isoformat(),
                "session_open_utc": opened.isoformat(),
                "session_close_utc": closed.isoformat(),
                "previous_session_date": str(row.previous_session_date),
            }
        )
    if any(
        quotes[c].nunique() != 1
        for c in ("session_open_utc", "session_close_utc", "previous_session_date")
    ):
        raise PersonalPaperError("quotes disagree on the session")
    opened = utc(quotes.iloc[0].session_open_utc)
    previous_date = str(quotes.iloc[0].previous_session_date)
    if calendar_path is None:
        raise PersonalPaperError("prospective fills require the exchange session calendar")
    calendar = pd.read_csv(calendar_path)
    calendar["session_open_utc"] = calendar.session_open_utc.map(utc)
    calendar["session_close_utc"] = calendar.session_close_utc.map(utc)
    session = calendar[calendar.session_open_utc == opened]
    prior = calendar[calendar.session_close_utc < opened]
    if (
        len(session) != 1
        or prior.empty
        or session.iloc[0].session_close_utc != utc(quotes.iloc[0].session_close_utc)
        or str(prior.iloc[-1].session_open_utc.date()) != previous_date
    ):
        raise PersonalPaperError("quote session is not confirmed by the exchange calendar")
    if config["price_basis"] == "raw_with_actions":
        validate_actions(quotes)
        actions = {
            str(row.symbol): {
                "dividend": float(row.dividend),
                "split_ratio": float(row.split_ratio),
            }
            for row in quotes.itertuples()
        }
        for quote in quote_rows:
            quote.update(actions[quote["symbol"]])
    observation = fx_at(fx, now)
    quote_inputs = {
        "quotes": sorted(quote_rows, key=lambda row: row["symbol"]),
        "fx": observation,
    }
    quote_input_sha = digest(quote_inputs)
    if not any(
        json.loads(row[0]).get("quote_input_sha256") == quote_input_sha
        for row in store.db.execute("SELECT value FROM events WHERE kind='quote_observation'")
    ):
        store.event(
            "quote_observation",
            {
                "quote_input_sha256": quote_input_sha,
                "inputs": quote_inputs,
                "recorded_at_utc": now.isoformat(),
            },
        )
    for key, book in books.items():
        if book["day_date"] != str(opened.date()):
            book["day_start_mxn"] = _equity(book, book["last_prices"]) * book["last_fx"]
            book["day_date"] = str(opened.date())
        if config["price_basis"] == "raw_with_actions":
            apply_actions(store, key, book, quotes, str(opened.date()))
        _risk(book, prices, observation["usd_mxn"], config, store, key, now.isoformat())
        if book["pending"] is None:
            continue
        if (now - opened).total_seconds() > OPEN_WINDOW_SECONDS:
            store.event("missed_execution_window", {"book": key, "timestamp": now.isoformat()})
            book["pending"] = None
            continue
        if (
            utc(book["pending_decided_at"]) >= opened
            or utc(book["pending_decided_at"]) >= quotes.observed_at_utc.map(utc).min()
        ):
            store.event(
                "missed_execution_window",
                {
                    "book": key,
                    "timestamp": now.isoformat(),
                    "reason": "decision was computed after the next session had opened",
                },
            )
            book["pending"] = None
            continue
        if book["pending_session_date"] != previous_date:
            raise PersonalPaperError("quote is not the next session of the frozen decision")
        _fill_target(
            store,
            key,
            book,
            book["pending"],
            prices,
            volumes,
            now.isoformat(),
            config,
            quote_input_sha,
        )
        book["pending"] = None
        _risk(book, prices, observation["usd_mxn"], config, store, key, now.isoformat())
        store.seal_book(key, book)


def status(database: Path, *, now_utc: str | None = None) -> dict[str, Any]:
    if not database.exists():
        raise PersonalPaperError("paper database does not exist; run initializes it")
    store = PaperStore(database, read_only=True)
    try:
        with store.reading():
            store.verify()
            manifest = store.get("manifest")
            books = store.books()
        if manifest is None:
            raise PersonalPaperError("paper registration is absent")
        started = manifest["prospective_started_at"]
        observed_now = utc(now_utc or clock())
        if manifest["clock_source"] == "SYSTEM_UTC":
            observed_now = min(observed_now, utc(clock()))
        days = max(0, (observed_now - utc(started)).days) if started else 0
        observations = manifest["closed_sessions"]
        return {
            "manifest": manifest,
            "books": books,
            "observation_days": days,
            "paper_90d_3rebals_complete": bool(
                started
                and manifest["clock_source"] == "SYSTEM_UTC"
                and manifest["evidence_kind"] == "PROSPECTIVE_SIMULATION"
                and manifest["calendar_checked"]
                and days >= 90
                and observations >= 60
                and all(
                    b["rebalance_count"] >= 3
                    for k, b in books.items()
                    if b["portfolio"] != "equal_weight_quarterly"
                )
            ),
            "economic_evidence": "NOT_EVALUATED",
            "real_money_approved": False,
            "status": "PAUSED"
            if any(b["paused"] for b in books.values())
            else "DEVELOPMENT_REPLAY"
            if not started
            else "WAITING_NEXT_SESSION",
            "warning": (
                "Simulated observations only. Completion does not establish an economic edge."
            ),
        }
    finally:
        store.close()


def pause(database: Path, reason: str, *, now_utc: str | None = None) -> None:
    if not reason.strip() or not database.exists():
        raise PersonalPaperError("pause requires an existing database and reason")
    store = PaperStore(database, require_registration=True)
    try:
        with store.writing():
            store.verify()
            books = store.books()
            last_control = store.db.execute(
                "SELECT kind,value FROM events "
                "WHERE kind IN ('manual_pause','reviewed_resume') "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if (
                books
                and all(book["paused"] for book in books.values())
                and last_control is not None
                and last_control["kind"] == "manual_pause"
                and json.loads(last_control["value"])["reason"] == reason
            ):
                return
            for key, book in books.items():
                if book["paused"]:
                    continue  # preserve the first cause until a reviewed resume
                book["paused"], book["pause_reason"] = True, reason
                store.seal_book(key, book)
            store.event("manual_pause", {"reason": reason, "timestamp": now_utc or clock()})
    finally:
        store.close()


def resume(database: Path, review: str, *, now_utc: str | None = None) -> None:
    if len(review.strip()) < 20 or not database.exists():
        raise PersonalPaperError("resume requires a written review of at least 20 characters")
    store = PaperStore(database, require_registration=True)
    try:
        with store.writing():
            store.verify()
            books = store.books()
            limit = store.get("manifest")["risk_limits"]["max_drawdown"]
            if any(b["drawdown"] >= limit - 1e-12 for b in books.values()):
                raise PersonalPaperError(
                    "5% drawdown still breached; valuation must recover before resume"
                )
            for key, book in books.items():
                book["paused"], book["pause_reason"] = False, None
                book["pending"] = None  # an old paused decision cannot become a delayed fill
                store.seal_book(key, book)
            store.event(
                "reviewed_resume",
                {"review": review, "timestamp": now_utc or clock(), "real_money_approved": False},
            )
    finally:
        store.close()


def export(database: Path, output_dir: Path) -> dict[str, str]:
    if not database.exists():
        raise PersonalPaperError("paper database does not exist")
    store = PaperStore(database, read_only=True)
    try:
        with store.reading():
            store.verify()
            manifest = store.get("manifest")
            rows = [
                json.loads(r[0])
                for r in store.db.execute("SELECT value FROM curves ORDER BY timestamp,book")
            ]
        if manifest is None:
            raise PersonalPaperError("paper registration is absent")
        output_dir.mkdir(parents=True, exist_ok=True)
        curve_path, manifest_path = output_dir / "curves.csv", output_dir / "manifest.json"
        with curve_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(rows[0])
                if rows
                else [
                    "timestamp",
                    "portfolio",
                    "cost_multiplier",
                    "equity_usd",
                    "equity_mxn",
                    "cash_usd",
                    "drawdown",
                    "status",
                    "rebalance_count",
                    "costs_usd",
                    "cost_evidence",
                    "fx_source",
                    "fx_timestamp",
                    "usd_mxn",
                    "evidence_kind",
                    "real_money_approved",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
        return {"curves": str(curve_path), "manifest": str(manifest_path)}
    finally:
        store.close()
