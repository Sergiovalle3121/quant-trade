"""Pure, fail-closed producers for crypto Gate 3 economic evidence.

The functions in this module have no I/O and never authorize promotion.  They
turn already-produced simulator results into canonical, content-addressed
facts that a separate governance layer can verify against sealed inputs.
Incomplete or irreconcilable inputs raise :class:`CryptoEconomicEvidenceError`
instead of manufacturing a neutral value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.research.crypto_evaluator import EvaluationResult, ExecutionResult
from quant_trade.research.overfitting import (
    assess_walk_forward_overfitting,
    cscv_probability_of_backtest_overfitting,
)

REQUIRED_BENCHMARKS = frozenset({"btc_buy_and_hold", "eligible_equal_weight"})
_VENUE_FILL_STATUSES = frozenset({"FILLED", "PARTIALLY_FILLED"})
_TERMINAL_STATUSES = frozenset({"TERMINAL_RECOVERY", "WRITTEN_DOWN"})


class CryptoEconomicEvidenceError(ValueError):
    """Raised when Gate 3 evidence cannot be derived without an assumption."""


def canonical_evidence_digest(payload: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 for a JSON-canonical evidence payload."""
    try:
        return sha256_of_text(canonical_dumps(payload))
    except (TypeError, ValueError) as exc:
        raise CryptoEconomicEvidenceError("evidence payload is not canonical JSON") from exc


def _sealed(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["digest"] = canonical_evidence_digest(payload)
    return sealed


def _finite(value: Any, name: str, *, non_negative: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CryptoEconomicEvidenceError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise CryptoEconomicEvidenceError(f"{name} must be finite")
    if non_negative and number < 0:
        raise CryptoEconomicEvidenceError(f"{name} must be non-negative")
    return number


def _validated_equity(result: EvaluationResult, label: str) -> tuple[pd.Series, float, float]:
    if not isinstance(result, EvaluationResult):
        raise CryptoEconomicEvidenceError(f"{label} must be an EvaluationResult")
    equity = result.equity
    if not isinstance(equity, pd.Series) or len(equity) < 2:
        raise CryptoEconomicEvidenceError(f"{label}.equity must be a pd.Series with >= 2 rows")
    if not isinstance(equity.index, pd.DatetimeIndex):
        raise CryptoEconomicEvidenceError(f"{label}.equity must use a DatetimeIndex")
    if not equity.index.is_monotonic_increasing or not equity.index.is_unique:
        raise CryptoEconomicEvidenceError(f"{label}.equity index must be unique and chronological")
    values = pd.to_numeric(equity, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise CryptoEconomicEvidenceError(f"{label}.equity must contain finite non-negative values")
    initial_capital = _finite(result.initial_capital_usd, f"{label}.initial_capital_usd")
    if initial_capital <= 0:
        raise CryptoEconomicEvidenceError(f"{label}.initial_capital_usd must be > 0")
    initial_equity = float(values[0])
    if initial_equity <= 0:
        raise CryptoEconomicEvidenceError(f"{label}.initial equity must be > 0")
    tolerance = max(1e-8, initial_capital * 1e-9)
    if abs(initial_equity - initial_capital) > tolerance:
        raise CryptoEconomicEvidenceError(f"{label}.equity does not start at initial_capital_usd")
    return equity, initial_capital, float(values[-1] / values[0] - 1.0)


def _positive_venue_fills(
    result: EvaluationResult, label: str
) -> list[tuple[ExecutionResult, float, float]]:
    fills: list[tuple[ExecutionResult, float, float]] = []
    for index, execution in enumerate(result.executions):
        if not isinstance(execution, ExecutionResult):
            raise CryptoEconomicEvidenceError(
                f"{label}.executions[{index}] must be an ExecutionResult"
            )
        notional = _finite(
            execution.filled_notional_usd,
            f"{label}.executions[{index}].filled_notional_usd",
            non_negative=True,
        )
        fee = _finite(
            execution.fee_usd,
            f"{label}.executions[{index}].fee_usd",
            non_negative=True,
        )
        impact = _finite(
            execution.impact_usd,
            f"{label}.executions[{index}].impact_usd",
            non_negative=True,
        )
        if execution.status not in _VENUE_FILL_STATUSES or notional <= 0:
            continue
        quantity = _finite(
            execution.filled_quantity,
            f"{label}.executions[{index}].filled_quantity",
            non_negative=True,
        )
        if quantity <= 0:
            raise CryptoEconomicEvidenceError(f"{label} has positive notional without quantity")
        cost = fee + impact
        if cost <= 0:
            raise CryptoEconomicEvidenceError(
                f"{label} has a positive venue fill without measurable fee/impact"
            )
        fills.append((execution, notional, cost))
    if not fills:
        raise CryptoEconomicEvidenceError(f"{label} has no positive measurable venue fills")
    return fills


def _nearest_rank_p95(values: list[float]) -> float:
    if not values:
        raise CryptoEconomicEvidenceError("p95 requires at least one observation")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _run_economics(result: EvaluationResult, label: str) -> dict[str, Any]:
    equity, initial_capital, net_return = _validated_equity(result, label)
    total_cost = _finite(result.total_cost_usd, f"{label}.total_cost_usd", non_negative=True)
    fills = _positive_venue_fills(result, label)
    rates = [cost / notional for _, notional, cost in fills]
    if not all(math.isfinite(rate) and rate >= 0 for rate in rates):
        raise CryptoEconomicEvidenceError(f"{label} produced an invalid execution cost rate")
    total_filled = sum(notional for _, notional, _ in fills)
    p95_rate = _nearest_rank_p95(rates)
    return {
        "initial_capital_usd": initial_capital,
        "final_value_usd": float(equity.iloc[-1]),
        "net_return": net_return,
        "gross_return": net_return + total_cost / initial_capital,
        "total_cost_usd": total_cost,
        "cost_profile": {
            "method": "nearest_rank_p95_of_fee_plus_impact_over_filled_notional",
            "venue_fill_count": len(fills),
            "total_filled_notional_usd": total_filled,
            "fill_cost_rates": [
                {
                    "execution_timestamp": str(execution.execution_timestamp),
                    "instrument_id": execution.instrument_id,
                    "rate": cost / notional,
                }
                for execution, notional, cost in fills
            ],
            "p95_rate": p95_rate,
            "total_cost_p95_return": p95_rate * total_filled / initial_capital,
        },
    }


def derive_execution_economics(
    candidate: EvaluationResult,
    benchmarks: Mapping[str, EvaluationResult],
) -> dict[str, Any]:
    """Derive net/gross returns and a conservative observed p95 cost profile.

    ``fee_usd + impact_usd`` is intentionally used for the p95 execution rate,
    matching the sealed Gate 3 definition even though part of bar impact is
    also reflected in ``fill_price``.  Gross return uses the simulator's
    actual cash cost in ``total_cost_usd`` and therefore does not double count
    that price impact.
    """
    if not isinstance(benchmarks, Mapping):
        raise CryptoEconomicEvidenceError("benchmarks must be a mapping")
    keys = set(benchmarks)
    if keys != REQUIRED_BENCHMARKS:
        raise CryptoEconomicEvidenceError(
            "benchmarks must contain exactly btc_buy_and_hold and eligible_equal_weight"
        )
    candidate_economics = _run_economics(candidate, "candidate")
    benchmark_economics = {
        name: _run_economics(benchmarks[name], f"benchmarks[{name}]")
        for name in sorted(REQUIRED_BENCHMARKS)
    }
    best_name = max(
        benchmark_economics,
        key=lambda name: (benchmark_economics[name]["gross_return"], name),
    )
    best_gross = float(benchmark_economics[best_name]["gross_return"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": "equity_net_plus_simulator_cash_cost_with_observed_nearest_rank_p95",
        "candidate": candidate_economics,
        "benchmarks": benchmark_economics,
        "best_gross_benchmark": best_name,
        "gross_alpha_return": float(candidate_economics["gross_return"]) - best_gross,
        "total_cost_p95_return": candidate_economics["cost_profile"]["total_cost_p95_return"],
    }
    return _sealed(payload)


def _cash_cost_for_fill(execution: ExecutionResult, label: str) -> float:
    """Recover the cost charged to cash without double-counting bar impact."""
    quantity = _finite(execution.filled_quantity, f"{label}.filled_quantity", non_negative=True)
    notional = _finite(
        execution.filled_notional_usd, f"{label}.filled_notional_usd", non_negative=True
    )
    fee = _finite(execution.fee_usd, f"{label}.fee_usd", non_negative=True)
    impact = _finite(execution.impact_usd, f"{label}.impact_usd", non_negative=True)
    open_price = _finite(execution.open_price, f"{label}.open_price")
    fill_price = _finite(execution.fill_price, f"{label}.fill_price")
    if quantity <= 0 or notional <= 0 or open_price <= 0 or fill_price <= 0:
        raise CryptoEconomicEvidenceError(f"{label} has an incomplete positive fill")
    if abs(notional - quantity * fill_price) > max(1e-7, notional * 1e-9):
        raise CryptoEconomicEvidenceError(
            f"{label} filled notional does not match quantity * price"
        )
    embedded_bar_impact = abs(fill_price - open_price) * quantity
    if impact + max(1e-8, impact * 1e-9) < embedded_bar_impact:
        raise CryptoEconomicEvidenceError(
            f"{label}.impact_usd is smaller than price-embedded bar impact"
        )
    return fee + max(0.0, impact - embedded_bar_impact)


def _last_causal_marks(
    panel: pd.DataFrame, held: set[str], final_timestamp: pd.Timestamp
) -> dict[str, float]:
    if not held:
        return {}
    if not isinstance(panel, pd.DataFrame):
        raise CryptoEconomicEvidenceError("panel must be a pandas DataFrame")
    identity = "instrument_id" if "instrument_id" in panel else "symbol"
    required = {identity, "timestamp", "mark_price"}
    missing = required - set(panel.columns)
    if missing:
        raise CryptoEconomicEvidenceError(f"panel is missing columns: {sorted(missing)}")
    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise CryptoEconomicEvidenceError("panel timestamps must be parseable")
    frame[identity] = frame[identity].astype(str)
    if frame.duplicated(["timestamp", identity]).any():
        raise CryptoEconomicEvidenceError("panel contains duplicate timestamp/instrument rows")
    final_utc = pd.Timestamp(final_timestamp)
    if final_utc.tzinfo is None:
        final_utc = final_utc.tz_localize("UTC")
    else:
        final_utc = final_utc.tz_convert("UTC")
    frame = frame[(frame[identity].isin(held)) & (frame["timestamp"] <= final_utc)]
    if "data_status" in frame:
        frame = frame[frame["data_status"].astype(str).eq("VALID")]
    marks: dict[str, float] = {}
    for instrument_id in sorted(held):
        rows = frame[frame[identity].eq(instrument_id)].sort_values("timestamp")
        if rows.empty:
            raise CryptoEconomicEvidenceError(
                f"no causal mark exists for open position {instrument_id}"
            )
        mark = _finite(
            rows.iloc[-1]["mark_price"],
            f"panel final mark for {instrument_id}",
        )
        if mark <= 0:
            raise CryptoEconomicEvidenceError(f"panel final mark for {instrument_id} must be > 0")
        marks[instrument_id] = mark
    return marks


def derive_pnl_concentration(
    result: EvaluationResult,
    panel: pd.DataFrame,
) -> dict[str, Any]:
    """Reconstruct P&L by instrument and zero-to-zero holding episode.

    The evaluator records price impact both in ``fill_price`` and in
    ``impact_usd`` for reporting.  Cash, however, is charged only the model
    cost.  Attribution therefore subtracts the price-embedded component from
    ``impact_usd`` before applying the remaining cash cost.  A terminal
    recovery consumes the requested position for its evidenced settlement;
    ``WRITTEN_DOWN`` consumes it for zero.  Open positions use only the last
    valid panel mark at or before the result's final timestamp.
    """
    equity, initial_capital, _ = _validated_equity(result, "result")
    units: dict[str, float] = {}
    episode_number: dict[str, int] = {}
    open_episodes: dict[str, dict[str, Any]] = {}
    episodes: list[dict[str, Any]] = []
    venue_cash_cost = 0.0
    previous_execution_time: pd.Timestamp | None = None

    def close_episode(instrument_id: str, timestamp: str, closure: str) -> None:
        episode = open_episodes.pop(instrument_id, None)
        if episode is None:
            raise CryptoEconomicEvidenceError(f"cannot close a missing episode for {instrument_id}")
        episode["end_timestamp"] = timestamp
        episode["closure"] = closure
        episodes.append(episode)

    for index, execution in enumerate(result.executions):
        label = f"result.executions[{index}]"
        if not isinstance(execution, ExecutionResult):
            raise CryptoEconomicEvidenceError(f"{label} must be an ExecutionResult")
        if execution.status not in _VENUE_FILL_STATUSES | _TERMINAL_STATUSES:
            continue
        if execution.execution_timestamp is None:
            raise CryptoEconomicEvidenceError(f"{label} has economic effect without a timestamp")
        timestamp = pd.to_datetime(execution.execution_timestamp, utc=True, errors="coerce")
        if pd.isna(timestamp):
            raise CryptoEconomicEvidenceError(f"{label}.execution_timestamp is invalid")
        timestamp = pd.Timestamp(timestamp)
        if previous_execution_time is not None and timestamp < previous_execution_time:
            raise CryptoEconomicEvidenceError("economic executions are not chronological")
        previous_execution_time = timestamp
        instrument_id = str(execution.instrument_id)
        if not instrument_id:
            raise CryptoEconomicEvidenceError(f"{label}.instrument_id is empty")
        side = str(execution.side).lower()
        if side not in {"buy", "sell"}:
            raise CryptoEconomicEvidenceError(f"{label}.side must be buy or sell")

        if execution.status in _TERMINAL_STATUSES:
            if side != "sell":
                raise CryptoEconomicEvidenceError(f"{label} terminal settlement must be a sell")
            fee = _finite(execution.fee_usd, f"{label}.fee_usd", non_negative=True)
            impact = _finite(execution.impact_usd, f"{label}.impact_usd", non_negative=True)
            if fee != 0 or impact != 0:
                raise CryptoEconomicEvidenceError(
                    f"{label} terminal settlement cannot hide an unattributed cash cost"
                )
            removed = _finite(
                execution.requested_quantity,
                f"{label}.requested_quantity",
                non_negative=True,
            )
            settlement = _finite(
                execution.filled_notional_usd,
                f"{label}.filled_notional_usd",
                non_negative=True,
            )
            current = units.get(instrument_id, 0.0)
            if removed <= 0 or current <= 0 or removed > current + 1e-8:
                raise CryptoEconomicEvidenceError(f"{label} terminal quantity cannot reconcile")
            if execution.status == "WRITTEN_DOWN" and settlement != 0:
                raise CryptoEconomicEvidenceError(f"{label} write-down settlement must be zero")
            if execution.status == "TERMINAL_RECOVERY" and settlement <= 0:
                raise CryptoEconomicEvidenceError(f"{label} recovery settlement must be positive")
            units[instrument_id] = max(0.0, current - removed)
            episode = open_episodes.get(instrument_id)
            if episode is None:
                raise CryptoEconomicEvidenceError(f"{label} has no open episode")
            episode["pnl_usd"] += settlement
            if units[instrument_id] <= 1e-8:
                units.pop(instrument_id, None)
                close_episode(instrument_id, str(execution.execution_timestamp), execution.status)
            continue

        quantity = _finite(
            execution.filled_quantity,
            f"{label}.filled_quantity",
            non_negative=True,
        )
        notional = _finite(
            execution.filled_notional_usd,
            f"{label}.filled_notional_usd",
            non_negative=True,
        )
        if quantity <= 0 or notional <= 0:
            raise CryptoEconomicEvidenceError(f"{label} fill must have positive quantity/notional")
        cash_cost = _cash_cost_for_fill(execution, label)
        venue_cash_cost += cash_cost
        current = units.get(instrument_id, 0.0)
        if side == "buy":
            if current <= 1e-8:
                episode_number[instrument_id] = episode_number.get(instrument_id, 0) + 1
                open_episodes[instrument_id] = {
                    "episode_id": f"{instrument_id}#{episode_number[instrument_id]}",
                    "instrument_id": instrument_id,
                    "start_timestamp": str(execution.execution_timestamp),
                    "end_timestamp": None,
                    "closure": None,
                    "pnl_usd": 0.0,
                }
            units[instrument_id] = current + quantity
            open_episodes[instrument_id]["pnl_usd"] -= notional + cash_cost
        else:
            if current <= 0 or quantity > current + 1e-8:
                raise CryptoEconomicEvidenceError(f"{label} sell quantity exceeds the position")
            episode = open_episodes.get(instrument_id)
            if episode is None:
                raise CryptoEconomicEvidenceError(f"{label} has no open episode")
            units[instrument_id] = max(0.0, current - quantity)
            episode["pnl_usd"] += notional - cash_cost
            if units[instrument_id] <= 1e-8:
                units.pop(instrument_id, None)
                close_episode(instrument_id, str(execution.execution_timestamp), execution.status)

    reported_cost = _finite(result.total_cost_usd, "result.total_cost_usd", non_negative=True)
    cost_tolerance = max(1e-7, reported_cost * 1e-8)
    if abs(venue_cash_cost - reported_cost) > cost_tolerance:
        raise CryptoEconomicEvidenceError(
            "execution cash costs do not reconcile to result.total_cost_usd"
        )

    final_timestamp = pd.Timestamp(equity.index[-1])
    marks = _last_causal_marks(panel, set(units), final_timestamp)
    for instrument_id in sorted(units):
        episode = open_episodes.get(instrument_id)
        if episode is None:
            raise CryptoEconomicEvidenceError(f"open position {instrument_id} has no episode")
        episode["pnl_usd"] += units[instrument_id] * marks[instrument_id]
        close_episode(instrument_id, str(final_timestamp), "FINAL_CAUSAL_MARK")

    asset_pnl: dict[str, float] = {}
    for episode in episodes:
        pnl = _finite(episode["pnl_usd"], f"{episode['episode_id']}.pnl_usd")
        episode["pnl_usd"] = pnl
        instrument_id = str(episode["instrument_id"])
        asset_pnl[instrument_id] = asset_pnl.get(instrument_id, 0.0) + pnl
    if not episodes:
        raise CryptoEconomicEvidenceError("result has no attributable holding episodes")
    attributed = sum(asset_pnl.values())
    equity_pnl = float(equity.iloc[-1]) - initial_capital
    rounding_tolerance = max(
        1e-6,
        initial_capital * 1e-9,
        abs(float(equity.iloc[-1])) * 1e-9,
        sum(abs(float(episode["pnl_usd"])) for episode in episodes) * 1e-10,
    )
    reconciliation_error = attributed - equity_pnl
    if abs(reconciliation_error) > rounding_tolerance:
        raise CryptoEconomicEvidenceError(
            "P&L attribution does not reconcile to final_value - initial_capital"
        )
    positive_assets = [value for value in asset_pnl.values() if value > 0]
    positive_episodes = [float(item["pnl_usd"]) for item in episodes if item["pnl_usd"] > 0]
    positive_asset_total = sum(positive_assets)
    positive_episode_total = sum(positive_episodes)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": "execution_cashflows_plus_last_causal_mark_by_zero_to_zero_episode",
        "cost_reconstruction": (
            "fee_usd + impact_usd - abs(fill_price-open_price)*filled_quantity"
        ),
        "final_timestamp": str(final_timestamp),
        "final_marks_usd": {name: marks[name] for name in sorted(marks)},
        "asset_pnl_usd": {name: asset_pnl[name] for name in sorted(asset_pnl)},
        "episodes": sorted(episodes, key=lambda item: str(item["episode_id"])),
        "positive_asset_pnl_usd": positive_asset_total,
        "positive_episode_pnl_usd": positive_episode_total,
        # A losing portfolio has no positive contribution to concentrate.  The
        # explicit zero denominators distinguish this vacuous 0.0 from missing
        # evidence; profitability is evaluated by separate promotion gates.
        "max_asset_positive_pnl_share": (
            max(positive_assets) / positive_asset_total if positive_asset_total > 0 else 0.0
        ),
        "max_episode_positive_pnl_share": (
            max(positive_episodes) / positive_episode_total if positive_episode_total > 0 else 0.0
        ),
        "attributed_pnl_usd": attributed,
        "equity_pnl_usd": equity_pnl,
        "reconciliation_error_usd": reconciliation_error,
        "reconciliation_tolerance_usd": rounding_tolerance,
    }
    return _sealed(payload)


def _limit_value(limits: Any, field: str, instrument_id: str) -> float:
    value = limits.get(field) if isinstance(limits, Mapping) else getattr(limits, field, None)
    number = _finite(value, f"execution_limits[{instrument_id}].{field}")
    if number <= 0:
        raise CryptoEconomicEvidenceError(f"execution_limits[{instrument_id}].{field} must be > 0")
    return number


def derive_capacity(
    result: EvaluationResult,
    execution_limits: Mapping[str, Any],
    canary_capital_usd: float,
) -> dict[str, Any]:
    """Derive conservative NAV capacity from every requested buy leg."""
    _validated_equity(result, "result")
    if not isinstance(execution_limits, Mapping):
        raise CryptoEconomicEvidenceError("execution_limits must be an instrument mapping")
    canary = _finite(canary_capital_usd, "canary_capital_usd")
    if canary <= 0 or canary > 500:
        raise CryptoEconomicEvidenceError("canary_capital_usd must be in (0, 500]")
    rebalance_values: dict[tuple[str, str], float] = {}
    for index, rebalance in enumerate(result.rebalances):
        key = (str(rebalance.decision_timestamp), str(rebalance.timestamp))
        if key in rebalance_values:
            raise CryptoEconomicEvidenceError("duplicate rebalance decision/execution timestamps")
        value = _finite(
            rebalance.portfolio_value_usd,
            f"result.rebalances[{index}].portfolio_value_usd",
        )
        if value <= 0:
            raise CryptoEconomicEvidenceError("rebalance portfolio value must be > 0")
        rebalance_values[key] = value

    legs: list[dict[str, Any]] = []
    for index, execution in enumerate(result.executions):
        requested = _finite(
            execution.requested_notional_usd,
            f"result.executions[{index}].requested_notional_usd",
            non_negative=True,
        )
        if str(execution.side).lower() != "buy" or requested <= 0:
            continue
        if execution.execution_timestamp is None:
            raise CryptoEconomicEvidenceError("requested buy leg has no execution timestamp")
        key = (str(execution.decision_timestamp), str(execution.execution_timestamp))
        if key not in rebalance_values:
            raise CryptoEconomicEvidenceError(
                "requested buy leg cannot be matched to a rebalance portfolio value"
            )
        portfolio_value = rebalance_values[key]
        requested_fraction = requested / portfolio_value
        if not math.isfinite(requested_fraction) or requested_fraction <= 0:
            raise CryptoEconomicEvidenceError("requested buy fraction must be finite and positive")
        if requested_fraction > 1.0 + 1e-8:
            raise CryptoEconomicEvidenceError("requested buy fraction exceeds long-only NAV")
        instrument_id = str(execution.instrument_id)
        if instrument_id not in execution_limits:
            raise CryptoEconomicEvidenceError(
                f"execution limits are missing for requested buy {instrument_id}"
            )
        limits = execution_limits[instrument_id]
        adv20 = _limit_value(limits, "median_daily_notional_20d_usd", instrument_id)
        depth = _limit_value(limits, "executable_depth_usd", instrument_id)
        adv_limit = 0.01 * adv20
        depth_limit = 0.05 * depth
        order_limit = min(adv_limit, depth_limit)
        nav_capacity = order_limit / requested_fraction
        legs.append(
            {
                "decision_timestamp": str(execution.decision_timestamp),
                "execution_timestamp": str(execution.execution_timestamp),
                "instrument_id": instrument_id,
                "requested_notional_usd": requested,
                "portfolio_value_usd": portfolio_value,
                "requested_nav_fraction": requested_fraction,
                "median_daily_notional_20d_usd": adv20,
                "executable_depth_usd": depth,
                "adv20_one_percent_limit_usd": adv_limit,
                "depth_five_percent_limit_usd": depth_limit,
                "order_limit_usd": order_limit,
                "nav_capacity_usd": nav_capacity,
            }
        )
    if not legs:
        raise CryptoEconomicEvidenceError("capacity requires at least one requested buy leg")
    capacity = min(float(leg["nav_capacity_usd"]) for leg in legs)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": "minimum_over_buy_legs_of_min_1pct_adv20_5pct_depth_over_nav_fraction",
        "canary_capital_usd": canary,
        "capacity_usd": capacity,
        "capacity_multiple_of_canary": capacity / canary,
        "legs": legs,
    }
    return _sealed(payload)


def _evaluation_payload(result: EvaluationResult) -> dict[str, Any]:
    equity, initial_capital, total_return = _validated_equity(result, "stressed_result")
    total_cost = _finite(result.total_cost_usd, "stressed_result.total_cost_usd", non_negative=True)
    total_turnover = _finite(
        result.total_turnover, "stressed_result.total_turnover", non_negative=True
    )
    executions: list[dict[str, Any]] = []
    for index, execution in enumerate(result.executions):
        if not isinstance(execution, ExecutionResult):
            raise CryptoEconomicEvidenceError(
                f"stressed_result.executions[{index}] must be an ExecutionResult"
            )
        item = execution.to_dict()
        for name in (
            "requested_quantity",
            "filled_quantity",
            "refused_quantity",
            "requested_notional_usd",
            "filled_notional_usd",
            "fee_usd",
            "impact_usd",
        ):
            _finite(item[name], f"stressed_result.executions[{index}].{name}", non_negative=True)
        executions.append(item)
    if not executions:
        raise CryptoEconomicEvidenceError("stressed_result must contain execution evidence")
    _positive_venue_fills(result, "stressed_result")
    return {
        "initial_capital_usd": initial_capital,
        "final_value_usd": float(equity.iloc[-1]),
        "total_return": total_return,
        "total_cost_usd": total_cost,
        "total_turnover": total_turnover,
        "equity": [
            {"timestamp": str(timestamp), "value_usd": float(value)}
            for timestamp, value in equity.items()
        ],
        "executions": executions,
        "rebalances": [rebalance.to_dict() for rebalance in result.rebalances],
        "delisted_positions": int(result.delisted_positions),
        "delisting_losses_usd": _finite(
            result.delisting_losses_usd,
            "stressed_result.delisting_losses_usd",
            non_negative=True,
        ),
    }


def derive_stress_evidence(
    stressed_result: EvaluationResult,
    *,
    cost_multiplier: float = 2.0,
    fill_fraction: float = 0.5,
) -> dict[str, Any]:
    """Bind the exact required 2x-cost/50%-fill stress result to its payload."""
    if type(cost_multiplier) not in {int, float} or float(cost_multiplier) != 2.0:
        raise CryptoEconomicEvidenceError("cost_multiplier must be exactly 2.0")
    if type(fill_fraction) not in {int, float} or float(fill_fraction) != 0.5:
        raise CryptoEconomicEvidenceError("fill_fraction must be exactly 0.5")
    if float(stressed_result.cost_multiplier) != 2.0:
        raise CryptoEconomicEvidenceError(
            "stressed_result was not evaluated with cost_multiplier=2.0"
        )
    if float(stressed_result.fill_fraction_multiplier) != 0.5:
        raise CryptoEconomicEvidenceError(
            "stressed_result was not evaluated with fill_fraction_multiplier=0.5"
        )
    result_payload = _evaluation_payload(stressed_result)
    result_digest = canonical_evidence_digest(result_payload)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": "sealed_double_cost_half_fill_evaluation",
        "stress_profile": {
            "cost_multiplier": 2.0,
            "fill_fraction": 0.5,
        },
        "profile_binding_scope": "producer_arguments_and_evaluator_accounting_fields",
        "total_return": result_payload["total_return"],
        "double_cost_half_fill_total_return": result_payload["total_return"],
        "result_payload": result_payload,
        "result_payload_digest": result_digest,
    }
    return _sealed(payload)


def _selection_returns_matrix(
    trial_returns: Mapping[str, pd.Series],
) -> tuple[list[str], pd.DatetimeIndex, np.ndarray]:
    if not isinstance(trial_returns, Mapping):
        raise CryptoEconomicEvidenceError("trial_returns must be a mapping")
    if len(trial_returns) < 15:
        raise CryptoEconomicEvidenceError("overfitting evidence requires at least 15 trials")
    if any(not isinstance(key, str) for key in trial_returns):
        raise CryptoEconomicEvidenceError("trial identifiers must be strings")
    trial_ids = sorted(trial_returns)
    if len(set(trial_ids)) != len(trial_ids) or any(not key for key in trial_ids):
        raise CryptoEconomicEvidenceError("trial identifiers must be unique and non-empty")
    reference_index: pd.DatetimeIndex | None = None
    columns: list[np.ndarray] = []
    fingerprints: set[bytes] = set()
    for trial_id in trial_ids:
        series = trial_returns[trial_id]
        if not isinstance(series, pd.Series):
            raise CryptoEconomicEvidenceError(f"trial {trial_id} must be a pd.Series")
        if series.attrs.get("data_scope") != "selection":
            raise CryptoEconomicEvidenceError(
                f"trial {trial_id} must declare series.attrs['data_scope']='selection'"
            )
        if not isinstance(series.index, pd.DatetimeIndex):
            raise CryptoEconomicEvidenceError(f"trial {trial_id} must use a DatetimeIndex")
        if not series.index.is_monotonic_increasing or not series.index.is_unique:
            raise CryptoEconomicEvidenceError(
                f"trial {trial_id} index must be unique and chronological"
            )
        if reference_index is None:
            reference_index = series.index
        elif not series.index.equals(reference_index):
            raise CryptoEconomicEvidenceError("all trial returns must have exactly aligned indices")
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise CryptoEconomicEvidenceError(f"trial {trial_id} contains non-finite returns")
        if np.ptp(values) <= 0:
            raise CryptoEconomicEvidenceError(f"trial {trial_id} has constant returns")
        fingerprint = np.ascontiguousarray(values, dtype=np.float64).tobytes()
        if fingerprint in fingerprints:
            raise CryptoEconomicEvidenceError("duplicate trial return paths cannot pad the ledger")
        fingerprints.add(fingerprint)
        columns.append(values)
    if reference_index is None:
        raise CryptoEconomicEvidenceError("trial returns are empty")
    return trial_ids, reference_index, np.column_stack(columns)


def _average_rank_percentile(values: np.ndarray, selected: int) -> float:
    chosen = values[selected]
    lower = int(np.count_nonzero(values < chosen))
    equal = int(np.count_nonzero(values == chosen))
    rank = 1.0 + lower + (equal - 1) / 2.0
    return rank / (len(values) + 1.0)


def derive_overfitting_evidence(
    trial_returns: Mapping[str, pd.Series],
    *,
    partitions: int,
    min_windows: int = 4,
) -> dict[str, Any]:
    """Compute CSCV PBO plus anchored walk-forward winner ranks.

    Each series must carry ``attrs["data_scope"] == "selection"``.  This
    producer can enforce that declaration and chronology, but the governance
    consumer remains responsible for binding the series to verified selection
    artifacts and their dataset digests.
    """
    if type(partitions) is not int or partitions < 4 or partitions > 16 or partitions % 2:
        raise CryptoEconomicEvidenceError("partitions must be an even integer in [4, 16]")
    if type(min_windows) is not int or min_windows < 4:
        raise CryptoEconomicEvidenceError("min_windows must be an integer >= 4")
    trial_ids, index, matrix = _selection_returns_matrix(trial_returns)
    observations = matrix.shape[0]
    minimum_observations = max(partitions * 2, (min_windows + 1) * 2)
    if observations < minimum_observations:
        raise CryptoEconomicEvidenceError(
            f"overfitting evidence requires at least {minimum_observations} observations"
        )
    if observations % partitions:
        raise CryptoEconomicEvidenceError(
            "observations must divide exactly into the sealed CSCV partitions"
        )

    try:
        cscv = cscv_probability_of_backtest_overfitting(
            matrix,
            partitions=partitions,
            max_pbo=0.10,
        )
    except ValueError as exc:
        raise CryptoEconomicEvidenceError(str(exc)) from exc

    blocks = np.array_split(np.arange(observations), min_windows + 1)
    if any(len(block) < 2 for block in blocks):
        raise CryptoEconomicEvidenceError("walk-forward blocks require at least two observations")
    ranks: list[float] = []
    degradations: list[float] = []
    window_detail: list[dict[str, Any]] = []
    for window in range(min_windows):
        train_rows = np.concatenate(blocks[: window + 1])
        test_rows = blocks[window + 1]
        train_scores = matrix[train_rows].mean(axis=0)
        selected = int(np.argmax(train_scores))
        test_scores = matrix[test_rows].mean(axis=0)
        rank = _average_rank_percentile(test_scores, selected)
        degradation = float(train_scores[selected] - test_scores[selected])
        ranks.append(rank)
        degradations.append(degradation)
        window_detail.append(
            {
                "window": window + 1,
                "train_start": str(index[train_rows[0]]),
                "train_end": str(index[train_rows[-1]]),
                "test_start": str(index[test_rows[0]]),
                "test_end": str(index[test_rows[-1]]),
                "selected_trial_id": trial_ids[selected],
                "selected_train_mean_return": float(train_scores[selected]),
                "selected_test_mean_return": float(test_scores[selected]),
                "selected_oos_rank_percentile": rank,
                "train_test_mean_return_degradation": degradation,
            }
        )
    try:
        walk_forward = assess_walk_forward_overfitting(
            ranks,
            degradations,
            parameter_variants=len(trial_ids),
            max_walk_forward_pbo=0.10,
            min_windows=min_windows,
        )
    except ValueError as exc:
        raise CryptoEconomicEvidenceError(str(exc)) from exc

    payload: dict[str, Any] = {
        "schema_version": 1,
        "method": "cscv_rank_based_plus_anchored_walk_forward_train_winner_oos_rank",
        "data_scope": "selection",
        "scope_validation": "all_series_attrs_data_scope_equal_selection",
        "trial_ids": trial_ids,
        "trials": len(trial_ids),
        "observations": observations,
        "index_start": str(index[0]),
        "index_end": str(index[-1]),
        "partitions": partitions,
        "pbo": cscv.pbo,
        "windows": walk_forward.windows,
        "cscv": cscv.to_dict(),
        "walk_forward": walk_forward.to_dict(),
        "walk_forward_windows": window_detail,
    }
    return _sealed(payload)


__all__ = [
    "CryptoEconomicEvidenceError",
    "canonical_evidence_digest",
    "derive_capacity",
    "derive_execution_economics",
    "derive_overfitting_evidence",
    "derive_pnl_concentration",
    "derive_stress_evidence",
]
