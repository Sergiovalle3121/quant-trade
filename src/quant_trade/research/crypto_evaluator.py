"""Causal, event-aware evaluator for the single-venue crypto study.

Signals are observations, not fills.  A target decided with the close of bar
``t`` is therefore eligible no earlier than the open of ``t + 1`` (plus any
declared latency).  Missing rows, a rank exit, and a halt are not delistings:
positions keep their last valid mark and can only be removed by an executable
sell or an explicit terminal market event.

This module deliberately contains no exchange client and no order-submission
path.  It is a deterministic research simulator whose execution records make
every refusal, partial fill, fee, and terminal write-down visible.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import pandas as pd
from pandas.api.types import is_bool

from quant_trade.costs.crypto_lowcap import (
    BYBIT_SPOT_TAKER_FEE,
    DEFAULT_TIER_PROFILES,
    CostInput,
    TierCostProfile,
)
from quant_trade.costs.rebalance import QUANTILE_P75, rebalance_cost
from quant_trade.data.crypto_panel import (
    DATA_STATUS_VALID,
    MARKET_EVENT_DELISTED,
    MARKET_EVENT_DELISTING_ANNOUNCED,
    MARKET_EVENT_DELISTING_CONFIRMED,
    MARKET_EVENT_LISTING_ENDED_CONFIRMED,
    normalise_data_status,
    normalise_market_event,
    parse_market_events,
)
from quant_trade.execution.bar_model import BarExecutionPolicy

DEFAULT_DELISTING_RECOVERY = 0.0
TARGET_PORTFOLIO = "TARGET_PORTFOLIO"
FORCED_EXIT = "FORCED_EXIT"
BTC_BENCHMARK_INSTRUMENT_ID = "CMC:1"

_TERMINAL_EVENTS = frozenset(
    {
        MARKET_EVENT_DELISTING_CONFIRMED,
        MARKET_EVENT_LISTING_ENDED_CONFIRMED,
        MARKET_EVENT_DELISTED,
    }
)
_ANNOUNCEMENT_EVENTS = frozenset({MARKET_EVENT_DELISTING_ANNOUNCED})


@dataclass(frozen=True)
class ExecutionLimits:
    """Point-in-time venue constraints for one instrument.

    A missing mapping means no extra rounding constraint was captured.  A
    present mapping is validated strictly and applied before a simulated fill.
    """

    tick_size: float | None = None
    quantity_step: float | None = None
    min_notional_usd: float | None = None

    def __post_init__(self) -> None:
        for name in ("tick_size", "quantity_step", "min_notional_usd"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True)
class ExecutionResult:
    """One attempted leg, including refusals and unfilled quantity."""

    decision_timestamp: str
    execution_timestamp: str | None
    instrument_id: str
    order_intent: str
    side: str
    requested_quantity: float
    filled_quantity: float
    refused_quantity: float
    requested_notional_usd: float
    filled_notional_usd: float
    open_price: float | None
    fill_price: float | None
    fee_usd: float
    impact_usd: float
    status: str
    reason: str
    reconciliation_status: str = "SIMULATED_RECONCILED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RebalanceRecord:
    decision_timestamp: str
    timestamp: str
    portfolio_value_usd: float
    turnover: float
    cost_usd: float
    names_targeted: int
    names_held: int
    refused_legs: int
    capped_legs: int
    unpriceable_legs: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    equity: Any  # pd.Series indexed by timestamp
    rebalances: list[RebalanceRecord] = field(default_factory=list)
    executions: list[ExecutionResult] = field(default_factory=list)
    total_turnover: float = 0.0
    total_cost_usd: float = 0.0
    delisting_losses_usd: float = 0.0
    delisted_positions: int = 0
    delisting_recovery: float = DEFAULT_DELISTING_RECOVERY
    initial_capital_usd: float = 0.0

    @property
    def annual_turnover(self) -> float:
        if self.equity is None or len(self.equity) < 2:
            return 0.0
        years = (self.equity.index[-1] - self.equity.index[0]).days / 365.25
        return self.total_turnover / years if years > 0 else 0.0

    def summary(self) -> dict[str, Any]:
        equity = self.equity
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0
        years = (equity.index[-1] - equity.index[0]).days / 365.25 if len(equity) > 1 else 0.0
        return {
            "initial_capital_usd": self.initial_capital_usd,
            "final_value_usd": float(equity.iloc[-1]) if len(equity) else 0.0,
            "total_return": total_return,
            "cagr": (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0,
            "years": years,
            "total_turnover": self.total_turnover,
            "annual_turnover": self.annual_turnover,
            "total_cost_usd": self.total_cost_usd,
            "cost_drag_bps_per_year": (
                self.total_cost_usd / self.initial_capital_usd * 10_000 / years
                if years > 0 and self.initial_capital_usd > 0
                else 0.0
            ),
            "rebalances": len(self.rebalances),
            "executions": len(self.executions),
            "delisted_positions": self.delisted_positions,
            "delisting_losses_usd": self.delisting_losses_usd,
            "delisting_recovery": self.delisting_recovery,
            "refused_legs": sum(r.refused_legs for r in self.rebalances),
            "capped_legs": sum(r.capped_legs for r in self.rebalances),
            "unpriceable_legs": sum(r.unpriceable_legs for r in self.rebalances),
        }


@dataclass(frozen=True)
class _PendingIntent:
    decision_timestamp: Any
    eligible_index: int
    expires_index: int
    order_intent: str
    target: dict[str, float]
    open_eligibility_exempt: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _DecisionFact:
    market_cap_usd: float | None
    volume: float | None


def _finite_positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _floor_to_step(quantity: float, step: float | None) -> float:
    if step is None:
        return quantity
    return math.floor((quantity + 1e-12) / step) * step


def _conservative_tick(price: float, side: str, tick: float | None) -> float:
    if tick is None:
        return price
    units = price / tick
    rounded = math.ceil(units - 1e-12) if side == "buy" else math.floor(units + 1e-12)
    return rounded * tick


def _normalise_panel(panel: pd.DataFrame, expected_venue: str) -> pd.DataFrame:
    required = {
        "timestamp",
        "symbol",
        "venue",
        "open",
        "close",
        "mark_price",
        "volume",
        "market_cap_usd",
        "eligible_to_open",
        "tradable",
        "data_status",
        "market_event",
    }
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"crypto panel missing causal execution columns: {missing}")
    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise ValueError("crypto panel contains invalid timestamps")
    if frame.duplicated(["timestamp", "symbol"]).any():
        raise ValueError("crypto panel contains duplicate timestamp/symbol rows")
    venues = {str(v).lower() for v in frame["venue"].dropna().unique()}
    if venues != {expected_venue.lower()}:
        raise ValueError(
            f"experiment requires exactly venue={expected_venue!r}; observed {sorted(venues)}"
        )
    for column in ("eligible_to_open", "tradable"):
        if not frame[column].map(is_bool).all():
            raise ValueError(f"{column} must contain actual booleans without nulls")
        frame[column] = frame[column].astype(bool)
    if (frame["eligible_to_open"] & ~frame["tradable"]).any():
        raise ValueError("eligible_to_open cannot be true when tradable is false")
    try:
        frame["data_status"] = frame["data_status"].map(normalise_data_status)
    except ValueError as exc:
        raise ValueError(f"crypto panel contains invalid data_status: {exc}") from exc
    if (frame["eligible_to_open"] & frame["data_status"].ne(DATA_STATUS_VALID)).any():
        raise ValueError("only VALID data can be eligible_to_open")
    try:
        frame["market_event"] = frame["market_event"].map(normalise_market_event)
    except ValueError as exc:
        raise ValueError(f"crypto panel contains invalid market_event: {exc}") from exc
    return frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _normalise_weights(weights: pd.DataFrame, symbols: set[str]) -> pd.DataFrame:
    required = {"timestamp", "symbol", "target_weight"}
    missing = sorted(required.difference(weights.columns))
    if missing:
        raise ValueError(f"weights missing required columns: {missing}")
    frame = weights.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce")
    if "order_intent" not in frame:
        frame["order_intent"] = TARGET_PORTFOLIO
    frame["order_intent"] = frame["order_intent"].fillna(TARGET_PORTFOLIO).astype(str)
    if "open_eligibility_exempt" not in frame:
        frame["open_eligibility_exempt"] = False
    if not frame["open_eligibility_exempt"].map(is_bool).all():
        raise ValueError("open_eligibility_exempt must contain actual booleans")
    frame["open_eligibility_exempt"] = frame["open_eligibility_exempt"].astype(bool)
    if frame[["timestamp", "symbol", "target_weight"]].isna().any().any():
        raise ValueError("weights contain missing or invalid values")
    if frame.duplicated(["timestamp", "symbol", "order_intent"]).any():
        raise ValueError("weights contain duplicate timestamp/symbol/intent rows")
    if not set(frame["symbol"]).issubset(symbols):
        unknown = sorted(set(frame["symbol"]).difference(symbols))
        raise ValueError(f"weights contain unknown instruments: {unknown}")
    if (~frame["order_intent"].isin({TARGET_PORTFOLIO, FORCED_EXIT})).any():
        raise ValueError("order_intent must be TARGET_PORTFOLIO or FORCED_EXIT")
    if (frame["target_weight"] < 0).any():
        raise ValueError("crypto spot targets must be long-only")
    forced = frame["order_intent"].eq(FORCED_EXIT)
    if (frame.loc[forced, "target_weight"] != 0).any():
        raise ValueError("FORCED_EXIT rows must target zero")
    if frame.loc[forced, "open_eligibility_exempt"].any():
        raise ValueError("FORCED_EXIT cannot carry a benchmark eligibility exemption")
    exempt = frame[frame["open_eligibility_exempt"]]
    if not exempt.empty and (
        len(exempt) != 1
        or str(exempt.iloc[0]["symbol"]) != BTC_BENCHMARK_INSTRUMENT_ID
        or float(exempt.iloc[0]["target_weight"]) != 1.0
        or str(exempt.iloc[0]["order_intent"]) != TARGET_PORTFOLIO
    ):
        raise ValueError(
            "the opening-eligibility exemption is reserved for the single "
            f"{BTC_BENCHMARK_INSTRUMENT_ID} buy-and-hold benchmark target"
        )
    portfolio = frame[~forced]
    totals = portfolio.groupby("timestamp")["target_weight"].sum()
    if (totals > 1.0 + 1e-9).any():
        raise ValueError("target weights imply leverage")
    return frame.sort_values(["timestamp", "order_intent", "symbol"]).reset_index(drop=True)


def evaluate(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    initial_capital_usd: float = 1_000.0,
    delisting_recovery: float = DEFAULT_DELISTING_RECOVERY,
    quantile: str = QUANTILE_P75,
    profiles: tuple[TierCostProfile, ...] = DEFAULT_TIER_PROFILES,
    min_executable_fraction: float = 1.0,
    execution_policy: BarExecutionPolicy | None = None,
    execution_limits: dict[str, ExecutionLimits] | None = None,
    taker_fees: dict[str, CostInput] | None = None,
    expected_venue: str = "bybit",
) -> EvaluationResult:
    """Evaluate long-format targets with mandatory next-open execution.

    ``FORCED_EXIT`` rows are sparse: they close only the named instrument and
    leave every other holding untouched.  Ordinary ``TARGET_PORTFOLIO`` rows
    replace the full target.  No missing bar is ever interpreted as a terminal
    event.
    """
    if not 0.0 <= delisting_recovery <= 1.0:
        raise ValueError("delisting_recovery must be in [0, 1]")
    if not math.isfinite(initial_capital_usd) or initial_capital_usd <= 0:
        raise ValueError("initial_capital_usd must be finite and positive")

    policy = execution_policy or BarExecutionPolicy()
    limits = execution_limits or {}
    fees = taker_fees or {}
    data = _normalise_panel(panel, expected_venue)
    symbols = set(data["symbol"].astype(str))
    targets = _normalise_weights(weights, symbols)
    dates = list(data["timestamp"].drop_duplicates().sort_values())
    date_index = {ts: i for i, ts in enumerate(dates)}
    rows = {(row.timestamp, str(row.symbol)): row for row in data.itertuples(index=False)}
    known_facts: dict[str, _DecisionFact] = {}
    decision_facts_by_day: dict[Any, dict[str, _DecisionFact]] = {}
    for day in dates:
        for symbol in symbols:
            row = rows.get((day, symbol))
            if row is None or row.data_status != DATA_STATUS_VALID:
                continue
            prior = known_facts.get(symbol, _DecisionFact(None, None))
            known_facts[symbol] = _DecisionFact(
                market_cap_usd=(_finite_positive(row.market_cap_usd) or prior.market_cap_usd),
                volume=_finite_positive(row.volume) or prior.volume,
            )
        decision_facts_by_day[day] = dict(known_facts)

    decisions: dict[Any, list[_PendingIntent]] = {}
    for (ts, intent), group in targets.groupby(["timestamp", "order_intent"], sort=True):
        if ts not in date_index:
            raise ValueError(f"weight decision {ts} is not a panel timestamp")
        target = {
            str(row.symbol): float(row.target_weight) for row in group.itertuples(index=False)
        }
        exempt = frozenset(
            str(row.symbol) for row in group.itertuples(index=False) if row.open_eligibility_exempt
        )
        intent_spec = _PendingIntent(
            decision_timestamp=ts,
            eligible_index=date_index[ts] + 1 + policy.additional_latency_bars,
            expires_index=(
                date_index[ts] + 1 + policy.additional_latency_bars + policy.max_order_age_bars
            ),
            order_intent=str(intent),
            target=target,
            open_eligibility_exempt=exempt,
        )
        decisions.setdefault(ts, []).append(intent_spec)

    cash = float(initial_capital_usd)
    units: dict[str, float] = {}
    last_mark: dict[str, float] = {}
    pending_intents: list[_PendingIntent] = []
    result = EvaluationResult(
        equity=None,
        delisting_recovery=delisting_recovery,
        initial_capital_usd=initial_capital_usd,
    )
    equity_points: list[float] = []
    announced: set[str] = set()

    def mark_for(ts: Any, symbol: str, *, at_open: bool) -> float | None:
        row = rows.get((ts, symbol))
        if row is not None and row.data_status == DATA_STATUS_VALID:
            candidate = _finite_positive(row.open if at_open else row.mark_price)
            if candidate is not None:
                return candidate
        return last_mark.get(symbol)

    def portfolio_value(ts: Any, *, at_open: bool) -> float:
        return cash + sum(
            quantity * price
            for symbol, quantity in units.items()
            if (price := mark_for(ts, symbol, at_open=at_open)) is not None
        )

    def record_refusal(
        intent: _PendingIntent,
        symbol: str,
        side: str,
        requested_qty: float,
        requested_notional: float,
        reason: str,
        execution_ts: Any | None,
        *,
        status: str = "REFUSED",
    ) -> None:
        result.executions.append(
            ExecutionResult(
                decision_timestamp=str(intent.decision_timestamp),
                execution_timestamp=str(execution_ts) if execution_ts is not None else None,
                instrument_id=symbol,
                order_intent=intent.order_intent,
                side=side,
                requested_quantity=requested_qty,
                filled_quantity=0.0,
                refused_quantity=requested_qty,
                requested_notional_usd=requested_notional,
                filled_notional_usd=0.0,
                open_price=None,
                fill_price=None,
                fee_usd=0.0,
                impact_usd=0.0,
                status=status,
                reason=reason,
            )
        )

    def execute_intent(ts: Any, intent: _PendingIntent) -> bool:
        nonlocal cash
        value = portfolio_value(ts, at_open=True)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("portfolio equity must remain finite and positive")

        desired = (
            dict(intent.target)
            if intent.order_intent == FORCED_EXIT
            else {**{symbol: 0.0 for symbol in units}, **intent.target}
        )
        requests: list[tuple[bool, str, float, float, float]] = []
        executed_notional_total = 0.0
        cost_total = 0.0
        refused = 0
        capped = 0
        unpriceable = 0
        targeted = 0
        for symbol in sorted(desired):
            current_price = mark_for(ts, symbol, at_open=True)
            current_value = units.get(symbol, 0.0) * (current_price or 0.0)
            desired_value = desired[symbol] * value
            delta_notional = desired_value - current_value
            if abs(delta_notional) <= 1e-9:
                continue
            targeted += 1
            side = "buy" if delta_notional > 0 else "sell"
            row = rows.get((ts, symbol))
            if row is None:
                refused += 1
                record_refusal(
                    intent,
                    symbol,
                    side,
                    abs(delta_notional) / current_price if current_price else 0.0,
                    abs(delta_notional),
                    "no venue bar at the eligible execution time",
                    ts,
                )
                continue
            open_price = _finite_positive(row.open)
            if open_price is None or row.data_status != DATA_STATUS_VALID or not row.tradable:
                refused += 1
                record_refusal(
                    intent,
                    symbol,
                    side,
                    0.0,
                    abs(delta_notional),
                    "instrument is not tradable at the eligible open",
                    ts,
                )
                continue
            decision_row = rows.get((intent.decision_timestamp, symbol))
            decision_eligible = (
                decision_row is not None
                and decision_row.data_status == DATA_STATUS_VALID
                and decision_row.eligible_to_open
                and decision_row.tradable
            )
            if (
                side == "buy"
                and not decision_eligible
                and symbol not in intent.open_eligibility_exempt
            ):
                refused += 1
                record_refusal(
                    intent,
                    symbol,
                    side,
                    abs(delta_notional) / open_price,
                    abs(delta_notional),
                    "instrument was not eligible_to_open at the decision close",
                    ts,
                )
                continue
            requests.append((side == "buy", symbol, delta_notional, current_value, open_price))

        # Exposure-reducing sells are processed before buys so long-only cash
        # accounting cannot create leverage merely because of iteration order.
        requests.sort(key=lambda item: (item[0], item[1]))

        for is_buy, symbol, delta_notional, current_value, open_price in requests:
            side = "buy" if is_buy else "sell"
            before_weight = current_value / value
            target_weight = before_weight + delta_notional / value
            decision_fact = decision_facts_by_day.get(intent.decision_timestamp, {}).get(
                symbol, _DecisionFact(None, None)
            )
            cap = decision_fact.market_cap_usd or 0.0
            fee = fees.get(symbol, BYBIT_SPOT_TAKER_FEE)
            priced = rebalance_cost(
                {symbol: before_weight} if before_weight else {},
                {symbol: target_weight} if target_weight else {},
                {symbol: cap},
                portfolio_value_usd=value,
                quantile=quantile,
                profiles=profiles,
                taker_fee=fee,
                min_executable_fraction=min_executable_fraction,
            )
            leg = priced.legs[0]
            raw_requested_qty = leg.requested_notional_usd / open_price
            if not leg.executable or leg.executed_notional_usd <= 0:
                refused += 1
                unpriceable += priced.unpriceable_legs
                record_refusal(
                    intent,
                    symbol,
                    side,
                    raw_requested_qty,
                    leg.requested_notional_usd,
                    leg.reason or "cost/capacity model refused the leg",
                    ts,
                )
                continue

            instrument_limits = limits.get(symbol, ExecutionLimits())
            executable_qty = leg.executed_notional_usd / open_price
            if policy.max_volume_participation_rate is not None:
                volume = decision_fact.volume
                if volume is None:
                    refused += 1
                    record_refusal(
                        intent,
                        symbol,
                        side,
                        raw_requested_qty,
                        leg.requested_notional_usd,
                        "volume is missing under a participation-limited policy",
                        ts,
                    )
                    continue
                executable_qty = min(executable_qty, volume * policy.max_volume_participation_rate)
            executable_qty = _floor_to_step(
                executable_qty,
                instrument_limits.quantity_step or policy.lot_size,
            )
            if not is_buy:
                executable_qty = min(executable_qty, units.get(symbol, 0.0))
            fill_price_raw = open_price
            participation = 0.0
            volume_value = decision_fact.volume
            if volume_value is not None:
                participation = executable_qty / volume_value
            impact_bps = policy.market_impact_bps_at_full_participation * participation
            fill_price_raw *= 1 + (1 if is_buy else -1) * impact_bps / 10_000
            fill_price = _conservative_tick(fill_price_raw, side, instrument_limits.tick_size)
            filled_notional = executable_qty * fill_price
            if (
                executable_qty <= 1e-12
                or instrument_limits.min_notional_usd is not None
                and filled_notional < instrument_limits.min_notional_usd
            ):
                refused += 1
                record_refusal(
                    intent,
                    symbol,
                    side,
                    raw_requested_qty,
                    leg.requested_notional_usd,
                    "rounded quantity does not satisfy step/min-notional limits",
                    ts,
                )
                continue

            cost_rate = leg.cost_usd / leg.executed_notional_usd
            cost = filled_notional * cost_rate
            if is_buy and filled_notional + cost > cash:
                affordable = _floor_to_step(
                    cash / (fill_price * (1 + cost_rate)),
                    instrument_limits.quantity_step or policy.lot_size,
                )
                executable_qty = max(0.0, affordable)
                filled_notional = executable_qty * fill_price
                cost = filled_notional * cost_rate
            if (
                executable_qty <= 1e-12
                or instrument_limits.min_notional_usd is not None
                and filled_notional < instrument_limits.min_notional_usd
            ):
                refused += 1
                record_refusal(
                    intent,
                    symbol,
                    side,
                    raw_requested_qty,
                    leg.requested_notional_usd,
                    "affordable quantity does not satisfy cash/min-notional limits",
                    ts,
                )
                continue

            signed_quantity = executable_qty if is_buy else -executable_qty
            cash -= signed_quantity * fill_price + cost
            units[symbol] = units.get(symbol, 0.0) + signed_quantity
            if abs(units[symbol]) <= 1e-12:
                units.pop(symbol, None)
            base_fee = filled_notional * fee.value_bps / 10_000
            model_impact = max(0.0, cost - base_fee)
            bar_impact = abs(fill_price - open_price) * executable_qty
            refused_qty = max(0.0, raw_requested_qty - executable_qty)
            status = "FILLED" if refused_qty <= 1e-9 else "PARTIALLY_FILLED"
            capped += int(status == "PARTIALLY_FILLED" or priced.capped_legs > 0)
            result.executions.append(
                ExecutionResult(
                    decision_timestamp=str(intent.decision_timestamp),
                    execution_timestamp=str(ts),
                    instrument_id=symbol,
                    order_intent=intent.order_intent,
                    side=side,
                    requested_quantity=raw_requested_qty,
                    filled_quantity=executable_qty,
                    refused_quantity=refused_qty,
                    requested_notional_usd=leg.requested_notional_usd,
                    filled_notional_usd=filled_notional,
                    open_price=open_price,
                    fill_price=fill_price,
                    fee_usd=base_fee,
                    impact_usd=model_impact + bar_impact,
                    status=status,
                    reason=leg.reason if refused_qty > 1e-9 else "",
                )
            )
            executed_notional_total += filled_notional
            cost_total += cost

        turnover = executed_notional_total / value / 2.0
        result.total_turnover += turnover
        result.total_cost_usd += cost_total
        result.rebalances.append(
            RebalanceRecord(
                decision_timestamp=str(intent.decision_timestamp),
                timestamp=str(ts),
                portfolio_value_usd=portfolio_value(ts, at_open=True),
                turnover=turnover,
                cost_usd=cost_total,
                names_targeted=targeted,
                names_held=len(units),
                refused_legs=refused,
                capped_legs=capped,
                unpriceable_legs=unpriceable,
            )
        )
        return intent.order_intent == FORCED_EXIT and any(
            target_weight == 0.0 and units.get(symbol, 0.0) > 1e-12
            for symbol, target_weight in intent.target.items()
        )

    for index, day in enumerate(dates):
        # Intents become executable before today's close is observable.
        eligible = [intent for intent in pending_intents if intent.eligible_index <= index]
        pending_intents = [intent for intent in pending_intents if intent.eligible_index > index]
        for intent in eligible:
            forced_residual = execute_intent(day, intent)
            if not forced_residual:
                continue
            if index < intent.expires_index:
                pending_intents.append(replace(intent, eligible_index=index + 1))
                continue
            for symbol, target_weight in intent.target.items():
                remaining = units.get(symbol, 0.0)
                if target_weight != 0.0 or remaining <= 1e-12:
                    continue
                price = mark_for(day, symbol, at_open=True)
                record_refusal(
                    intent,
                    symbol,
                    "sell",
                    remaining,
                    remaining * (price or 0.0),
                    "forced exit residual exceeded max_order_age_bars",
                    day,
                    status="EXPIRED",
                )

        # Today's marks/facts become known only after open execution.
        for symbol in symbols:
            row = rows.get((day, symbol))
            if row is None or row.data_status != DATA_STATUS_VALID:
                continue
            mark = _finite_positive(row.mark_price)
            if mark is not None:
                last_mark[symbol] = mark

        # Only explicit events have terminal semantics.  A prior close is not
        # retroactively declared executable by a later absence.
        for symbol in list(units):
            row = rows.get((day, symbol))
            events = (
                parse_market_events(row.market_event) if row is not None else frozenset({"NONE"})
            )
            terminal = bool(events & _TERMINAL_EVENTS)
            if events & _ANNOUNCEMENT_EVENTS and not terminal and symbol not in announced:
                announced.add(symbol)
                first_eligible = index + 1 + policy.additional_latency_bars
                pending_intents.append(
                    _PendingIntent(
                        decision_timestamp=day,
                        eligible_index=first_eligible,
                        expires_index=first_eligible + policy.max_order_age_bars,
                        order_intent=FORCED_EXIT,
                        target={symbol: 0.0},
                    )
                )
            if not terminal:
                continue
            pending_intents = [
                intent
                for intent in pending_intents
                if not (intent.order_intent == FORCED_EXIT and symbol in intent.target)
            ]
            quantity = units.pop(symbol)
            previous_value = quantity * last_mark.get(symbol, 0.0)
            recovery_price = (
                _finite_positive(getattr(row, "terminal_recovery_price", None))
                if row is not None
                else None
            )
            recovered = quantity * (recovery_price or 0.0) * delisting_recovery
            cash += recovered
            result.delisting_losses_usd += max(0.0, previous_value - recovered)
            result.delisted_positions += 1
            result.executions.append(
                ExecutionResult(
                    decision_timestamp=str(day),
                    execution_timestamp=str(day),
                    instrument_id=symbol,
                    order_intent=FORCED_EXIT,
                    side="sell",
                    requested_quantity=quantity,
                    filled_quantity=quantity if recovered > 0 else 0.0,
                    refused_quantity=0.0 if recovered > 0 else quantity,
                    requested_notional_usd=previous_value,
                    filled_notional_usd=recovered,
                    open_price=None,
                    fill_price=recovery_price if recovered > 0 else None,
                    fee_usd=0.0,
                    impact_usd=0.0,
                    status="TERMINAL_RECOVERY" if recovered > 0 else "WRITTEN_DOWN",
                    reason=(
                        "explicit terminal event with evidenced recovery price"
                        if recovered > 0
                        else "explicit terminal event had no demonstrated executable exit"
                    ),
                )
            )

        value = portfolio_value(day, at_open=False)
        if not math.isfinite(value) or value < 0:
            raise ValueError("portfolio accounting produced invalid equity")
        equity_points.append(value)

        # Decisions use today's completed bar and are queued only afterwards.
        for intent in decisions.get(day, []):
            if intent.eligible_index < len(dates):
                pending_intents.append(intent)
            else:
                for symbol in intent.target:
                    record_refusal(
                        intent,
                        symbol,
                        "sell" if intent.target[symbol] == 0 else "buy",
                        0.0,
                        0.0,
                        "backtest ended before the mandatory next-open execution",
                        None,
                        status="EXPIRED",
                    )

    for intent in pending_intents:
        for symbol in intent.target:
            remaining = units.get(symbol, 0.0) if intent.order_intent == FORCED_EXIT else 0.0
            record_refusal(
                intent,
                symbol,
                "sell" if intent.target[symbol] == 0 else "buy",
                remaining,
                remaining * (last_mark.get(symbol, 0.0)),
                "backtest ended before the delayed execution became eligible",
                None,
                status="EXPIRED",
            )

    result.equity = pd.Series(equity_points, index=dates, name="equity")
    return result


def equal_weight_benchmark(
    panel: pd.DataFrame, *, rebalance_frequency: str = "annual", top_n: int = 20
) -> pd.DataFrame:
    """Annual equal-weight eligible basket under the same panel rules."""
    from quant_trade.research.signals.crypto_lowcap import annual_equal_weight_rebalance

    return annual_equal_weight_rebalance(
        panel,
        {
            "top_n": top_n,
            "rebalance_frequency": rebalance_frequency,
            "freeze_cohort": False,
        },
    )


def btc_buy_and_hold_benchmark(
    panel: pd.DataFrame,
    *,
    instrument_id: str = BTC_BENCHMARK_INSTRUMENT_ID,
    expected_venue: str = "bybit",
    min_bound_bars: int = 20,
) -> pd.DataFrame:
    """One causal BTC target, independent of the low/mid-cap open band.

    BTC is intentionally outside the strategy's USD 10M--1B universe, so its
    benchmark eligibility is stable identity + valid Bybit history, not
    ``eligible_to_open``.  A real builder panel still observes the same causal
    identity warm-up through ``bound_bar_number``.
    """
    if min_bound_bars < 1:
        raise ValueError("min_bound_bars must be >= 1")
    if instrument_id != BTC_BENCHMARK_INSTRUMENT_ID:
        raise ValueError(f"BTC benchmark identity must be {BTC_BENCHMARK_INSTRUMENT_ID}")
    data = _normalise_panel(panel, expected_venue)
    rows = data[data["symbol"].astype(str) == instrument_id].sort_values("timestamp")
    eligible = rows[rows["tradable"] & rows["data_status"].eq(DATA_STATUS_VALID)]
    if "bound_bar_number" in eligible.columns:
        bar_number = pd.to_numeric(eligible["bound_bar_number"], errors="coerce")
        eligible = eligible[bar_number >= min_bound_bars]
    if eligible.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    return pd.DataFrame(
        [
            {
                "timestamp": eligible.iloc[0]["timestamp"],
                "symbol": instrument_id,
                "target_weight": 1.0,
                "order_intent": TARGET_PORTFOLIO,
                "open_eligibility_exempt": True,
            }
        ]
    )


__all__ = [
    "BTC_BENCHMARK_INSTRUMENT_ID",
    "DEFAULT_DELISTING_RECOVERY",
    "FORCED_EXIT",
    "TARGET_PORTFOLIO",
    "EvaluationResult",
    "ExecutionLimits",
    "ExecutionResult",
    "RebalanceRecord",
    "btc_buy_and_hold_benchmark",
    "equal_weight_benchmark",
    "evaluate",
]
