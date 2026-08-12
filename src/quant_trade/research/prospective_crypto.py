"""Sealed, prospective-only BTC/ETH time-series momentum declaration.

This module intentionally has no data loader, backtest, registry entry, order
router, or live adapter.  It can validate the pre-registered YAML declaration
and transform an OHLCV frame supplied by the caller into sparse target
*intentions*.  An intention is never an order and carries an earliest allowed
execution bar so a same-bar fill cannot be inferred from this API.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import yaml

from quant_trade.data.panel import validate_panel_schema
from quant_trade.data.validation import MarketDataValidationError
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

SCHEMA_VERSION = 1
STRATEGY_ID = "binance_btc_eth_tsmom_long_cash_v1"
CAMPAIGN_MODE = "PROSPECTIVE_ONLY"
VENUE = "Binance"
MARKET = "Spot"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
POSITION_MODE = "long_cash"
DEVELOPMENT_EVIDENCE_START = "2018-08-31"
DEVELOPMENT_EVIDENCE_END = "2023-11-28"
DEVELOPMENT_END = "2026-08-31"
HOLDOUT_START = "2026-09-01"
PRIMARY_HOLDOUT_END = "2028-08-31"
HOLDOUT_END = "2029-08-31"

_EXPECTED_SLEEVES = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
_EXPECTED_SIGNAL_POLICY = {
    "momentum_lookback_calendar_months": 12,
    "decision_frequency": "monthly",
    "decision_bar": "last_daily_utc_close_of_calendar_month",
    "execution_bar": "next_daily_utc_open",
    "decision_to_execution_bars": 1,
    "emit_only_on_state_change": True,
    "rebalance_drift": False,
    "tie_state": "CASH",
}
_EXPECTED_REVEAL_POLICY = {
    "primary_holdout_months": 24,
    "default_extension_months": 12,
    "default_extension_without_interim_reveal": True,
    "interim_economic_reveal_at_primary_end": False,
    "reveal_not_before": "2029-09-01",
    "insufficient_evidence_action": "EXTEND_WITHOUT_REVEAL",
}
_EXPECTED_BENCHMARKS = (
    {"benchmark_id": "btc_usdt_buy_and_hold", "symbol_weights": {"BTCUSDT": 1.0}},
    {"benchmark_id": "eth_usdt_buy_and_hold", "symbol_weights": {"ETHUSDT": 1.0}},
    {
        "benchmark_id": "btc_eth_50_50_buy_and_hold",
        "symbol_weights": {"BTCUSDT": 0.5, "ETHUSDT": 0.5},
    },
)
_EXPECTED_COST_POLICY = {
    "fee_floor_bps_per_side": 10.0,
    "friction_floor_bps_per_side": 5.0,
    "stress_cost_multiplier": 2.0,
}
_EXPECTED_DEVELOPMENT_FALSIFICATION_POLICY = {
    "net_total_return_positive": True,
    "outperform_each_benchmark": True,
    "required_benchmark_ids": (
        "btc_usdt_buy_and_hold",
        "eth_usdt_buy_and_hold",
        "btc_eth_50_50_buy_and_hold",
    ),
    "contiguous_blocks": 4,
    "block_partition_method": "EQUAL_CONTIGUOUS_DAILY_OBSERVATIONS",
    "minimum_outperforming_blocks": 3,
    "block_outperformance_benchmark_ids": (
        "btc_usdt_buy_and_hold",
        "btc_eth_50_50_buy_and_hold",
    ),
    "max_drawdown_abs": 0.25,
    "stress_cost_multiplier": 2.0,
    "stress_fill_fraction": 0.5,
    "stress_total_return_min": 0.0,
}
_EXPECTED_PROMOTION_POLICY = {
    "excess_net_return_positive_each_benchmark": True,
    "psr_min": 0.95,
    "dsr_min": 0.95,
    "pbo_policy": "NOT_IDENTIFIABLE_SINGLE_TRIAL",
    "mandatory_pbo_means_insufficient_evidence": True,
    "one_sided_excess_confidence_level": 0.95,
    "one_sided_excess_confidence_interval_lower_bound_min_exclusive": 0.0,
    "max_drawdown_abs": 0.25,
    "max_drawdown_not_worse_than_each_benchmark": True,
    "stress_cost_multiplier": 2.0,
    "stress_fill_fraction": 0.5,
    "stress_total_return_min": 0.0,
    "both_sleeves_positive_pnl": True,
    "max_positive_pnl_share_per_sleeve": 0.75,
    "capacity_multiple_of_proposed_capital_min": 2.0,
    "real_money_authorized": False,
}
_EXPECTED_SAFETY_POLICY = {
    "leverage_allowed": False,
    "shorts_allowed": False,
    "margin_allowed": False,
    "earn_allowed": False,
}
_EXPECTED_AUTHORIZATION = {
    "research_only": True,
    "live_execution_enabled": False,
    "real_money_authorized": False,
    "external_action_authorized": False,
}


class ProspectiveCryptoError(ValueError):
    """Raised when the prospective declaration or OHLCV contract is invalid."""


def _freeze(value: Any) -> Any:
    """Defensively copy and recursively freeze a JSON-shaped value."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProspectiveCryptoError("prospective specs reject NaN and infinity")
        return value
    raise ProspectiveCryptoError(
        f"prospective specs accept JSON-shaped values only, got {type(value).__name__}"
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _plain(value: Any) -> Any:
    """Return a recursively mutable value for exact policy comparisons."""

    return _thaw(_freeze(value))


def _require_exact(name: str, observed: Any, expected: Any) -> None:
    if canonical_dumps(_plain(observed)) != canonical_dumps(_plain(expected)):
        raise ProspectiveCryptoError(f"{name} contradicts the sealed prospective campaign")


@dataclass(frozen=True)
class ProspectiveStrategySpec:
    """Deeply immutable declaration for one never-retuned prospective trial."""

    schema_version: int
    strategy_id: str
    campaign_mode: str
    venue: str
    market: str
    symbols: Sequence[str]
    sleeves: Mapping[str, float]
    position_mode: str
    signal_policy: Mapping[str, Any]
    trial_budget: int
    development_evidence_start: str
    development_evidence_end: str
    development_end: str
    holdout_start: str
    primary_holdout_end: str
    holdout_end: str
    reveal_policy: Mapping[str, Any]
    benchmarks: Sequence[Mapping[str, Any]]
    cost_policy: Mapping[str, Any]
    development_falsification_policy: Mapping[str, Any]
    promotion_policy: Mapping[str, Any]
    safety_policy: Mapping[str, Any]
    authorization: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "sleeves",
            "signal_policy",
            "reveal_policy",
            "cost_policy",
            "development_falsification_policy",
            "promotion_policy",
            "safety_policy",
            "authorization",
        ):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ProspectiveCryptoError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))
        if not isinstance(self.symbols, (list, tuple)):
            raise ProspectiveCryptoError("symbols must be a sequence")
        if not isinstance(self.benchmarks, (list, tuple)):
            raise ProspectiveCryptoError("benchmarks must be a sequence")
        object.__setattr__(self, "symbols", _freeze(self.symbols))
        object.__setattr__(self, "benchmarks", _freeze(self.benchmarks))

        _require_exact("schema_version", self.schema_version, SCHEMA_VERSION)
        _require_exact("strategy_id", self.strategy_id, STRATEGY_ID)
        _require_exact("campaign_mode", self.campaign_mode, CAMPAIGN_MODE)
        _require_exact("venue", self.venue, VENUE)
        _require_exact("market", self.market, MARKET)
        _require_exact("symbols", self.symbols, SYMBOLS)
        _require_exact("sleeves", self.sleeves, _EXPECTED_SLEEVES)
        _require_exact("position_mode", self.position_mode, POSITION_MODE)
        _require_exact("signal_policy", self.signal_policy, _EXPECTED_SIGNAL_POLICY)
        _require_exact("trial_budget", self.trial_budget, 1)
        _require_exact(
            "development_evidence_start",
            self.development_evidence_start,
            DEVELOPMENT_EVIDENCE_START,
        )
        _require_exact(
            "development_evidence_end",
            self.development_evidence_end,
            DEVELOPMENT_EVIDENCE_END,
        )
        _require_exact("development_end", self.development_end, DEVELOPMENT_END)
        _require_exact("holdout_start", self.holdout_start, HOLDOUT_START)
        _require_exact("primary_holdout_end", self.primary_holdout_end, PRIMARY_HOLDOUT_END)
        _require_exact("holdout_end", self.holdout_end, HOLDOUT_END)
        _require_exact("reveal_policy", self.reveal_policy, _EXPECTED_REVEAL_POLICY)
        _require_exact("benchmarks", self.benchmarks, _EXPECTED_BENCHMARKS)
        _require_exact("cost_policy", self.cost_policy, _EXPECTED_COST_POLICY)
        _require_exact(
            "development_falsification_policy",
            self.development_falsification_policy,
            _EXPECTED_DEVELOPMENT_FALSIFICATION_POLICY,
        )
        _require_exact("promotion_policy", self.promotion_policy, _EXPECTED_PROMOTION_POLICY)
        _require_exact("safety_policy", self.safety_policy, _EXPECTED_SAFETY_POLICY)
        _require_exact("authorization", self.authorization, _EXPECTED_AUTHORIZATION)

        development_end = date.fromisoformat(self.development_end)
        holdout_start = date.fromisoformat(self.holdout_start)
        if holdout_start != development_end + timedelta(days=1):
            raise ProspectiveCryptoError("holdout must start the day after development ends")
        if not (
            development_end
            < date.fromisoformat(self.primary_holdout_end)
            < date.fromisoformat(self.holdout_end)
            < date.fromisoformat(str(self.reveal_policy["reveal_not_before"]))
        ):
            raise ProspectiveCryptoError("prospective holdout and reveal dates are inconsistent")

    def canonical_payload(self) -> dict[str, Any]:
        """Return every strategy-relevant field in canonical JSON shape."""

        return {field.name: _thaw(getattr(self, field.name)) for field in fields(self)}

    def seal(self) -> str:
        """SHA-256 content seal over the complete immutable declaration."""

        return sha256_of_text(canonical_dumps(self.canonical_payload()))


def load_prospective_strategy_spec(path: str | Path) -> ProspectiveStrategySpec:
    """Load a YAML declaration and verify its embedded canonical seal.

    This reads configuration bytes only.  It never opens market data, evaluates
    returns, or consults a venue.
    """

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProspectiveCryptoError("prospective config must contain a mapping")
    declared_seal = raw.pop("seal", None)
    if not isinstance(declared_seal, str) or len(declared_seal) != 64:
        raise ProspectiveCryptoError("prospective config requires a 64-character seal")
    if any(character not in "0123456789abcdef" for character in declared_seal):
        raise ProspectiveCryptoError("prospective config seal must be lowercase hexadecimal")

    expected_fields = {field.name for field in fields(ProspectiveStrategySpec)}
    observed_fields = set(raw)
    missing = sorted(expected_fields - observed_fields)
    unknown = sorted(observed_fields - expected_fields)
    if missing or unknown:
        raise ProspectiveCryptoError(
            f"prospective config fields mismatch; missing={missing}, unknown={unknown}"
        )
    try:
        spec = ProspectiveStrategySpec(**raw)
    except TypeError as exc:
        raise ProspectiveCryptoError(f"invalid prospective config: {exc}") from exc
    if spec.seal() != declared_seal:
        raise ProspectiveCryptoError("prospective config seal mismatch")
    return spec


def _is_month_end(timestamp: pd.Timestamp) -> bool:
    return timestamp.day == calendar.monthrange(timestamp.year, timestamp.month)[1]


def _reference_month(year: int, month: int, lookback_months: int) -> tuple[int, int]:
    zero_based = year * 12 + month - 1 - lookback_months
    return zero_based // 12, zero_based % 12 + 1


def _prepare_ohlcv(data: pd.DataFrame, spec: ProspectiveStrategySpec) -> pd.DataFrame:
    try:
        frame = validate_panel_schema(data)
    except MarketDataValidationError as exc:
        raise ProspectiveCryptoError(f"invalid prospective OHLCV: {exc}") from exc
    observed_symbols = set(frame["symbol"])
    if observed_symbols != set(spec.symbols):
        expected = tuple(spec.symbols)
        observed = tuple(sorted(observed_symbols))
        raise ProspectiveCryptoError(f"OHLCV symbols must be exactly {expected}, got {observed}")
    timestamps = frame["timestamp"]
    midnight = (
        (timestamps.dt.hour == 0)
        & (timestamps.dt.minute == 0)
        & (timestamps.dt.second == 0)
        & (timestamps.dt.microsecond == 0)
    )
    if not bool(midnight.all()):
        raise ProspectiveCryptoError("prospective inputs must be UTC daily bars labelled at 00:00")
    numeric = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not bool(pd.notna(numeric).all()) or not bool((abs(numeric) < float("inf")).all()):
        raise ProspectiveCryptoError("prospective inputs require finite OHLCV values")
    return frame


def _tsmom_targets(
    data: pd.DataFrame,
    spec: ProspectiveStrategySpec,
    *,
    decision_start: pd.Timestamp,
    decision_end: pd.Timestamp,
) -> pd.DataFrame:
    """Shared signal implementation for development and sealed holdout use.

    At the final UTC daily bar of a calendar month, each symbol's close is
    compared with the last observed daily close *inside the calendar month 12
    months earlier*.  The function never uses a 365-row shift and never falls
    back to an older month when that reference month is absent.  Positive
    momentum targets the symbol's fixed 50% sleeve; zero/negative momentum
    targets cash for that sleeve.

    Only initialization and LONG/CASH state transitions are emitted.  A sleeve
    that remains LONG is not reset to 50%, so price drift cannot manufacture a
    rebalance.  Every row declares the next daily open as its earliest possible
    execution; this module contains no facility capable of filling it.
    """

    if not isinstance(spec, ProspectiveStrategySpec):
        raise ProspectiveCryptoError("a ProspectiveStrategySpec is required")
    # ``frozen=True`` prevents ordinary mutation; reconstruction repeats every
    # fixed-policy check in case a caller deliberately bypassed dataclass
    # protections with low-level object mutation.
    validated_spec = ProspectiveStrategySpec(**spec.canonical_payload())
    if validated_spec.seal() != spec.seal():
        raise ProspectiveCryptoError("an invalid prospective strategy spec was supplied")
    frame = _prepare_ohlcv(data, spec)
    lookback = int(spec.signal_policy["momentum_lookback_calendar_months"])
    month_closes: dict[tuple[str, int, int], tuple[pd.Timestamp, float]] = {}
    for row in frame.itertuples(index=False):
        timestamp = pd.Timestamp(row.timestamp)
        month_closes[(str(row.symbol), timestamp.year, timestamp.month)] = (
            timestamp,
            float(row.close),
        )

    month_end_rows = frame[
        frame["timestamp"].map(_is_month_end)
        & frame["timestamp"].between(decision_start, decision_end, inclusive="both")
    ]
    decision_dates = sorted(set(month_end_rows["timestamp"]))
    states: dict[str, str] = {}
    targets: list[dict[str, Any]] = []
    for decision_timestamp in decision_dates:
        current = month_end_rows[month_end_rows["timestamp"] == decision_timestamp]
        current_by_symbol = {str(row.symbol): row for row in current.itertuples(index=False)}
        # A portfolio decision needs a contemporaneous close for both sleeves.
        # Partial month-end data cannot silently become a one-asset decision.
        if set(current_by_symbol) != set(spec.symbols):
            continue
        reference_year, reference_month = _reference_month(
            decision_timestamp.year, decision_timestamp.month, lookback
        )
        for symbol in spec.symbols:
            reference = month_closes.get((symbol, reference_year, reference_month))
            if reference is None:
                # Absence is not permission to use a stale close from month -13.
                continue
            reference_timestamp, reference_close = reference
            decision_close = float(current_by_symbol[symbol].close)
            next_state = "LONG" if decision_close > reference_close else "CASH"
            if states.get(symbol) == next_state:
                continue
            states[symbol] = next_state
            targets.append(
                {
                    "strategy_id": spec.strategy_id,
                    "strategy_spec_seal": spec.seal(),
                    "trial_number": 1,
                    "decision_timestamp": decision_timestamp,
                    "earliest_execution_timestamp": decision_timestamp + pd.Timedelta(days=1),
                    "execution_timing": "NEXT_DAILY_OPEN",
                    "symbol": symbol,
                    "signal_state": next_state,
                    "target_weight": (float(spec.sleeves[symbol]) if next_state == "LONG" else 0.0),
                    "reference_month": f"{reference_year:04d}-{reference_month:02d}",
                    "reference_timestamp": reference_timestamp,
                    "decision_close": decision_close,
                    "reference_close": reference_close,
                    "order_intent": "SPARSE_TARGET_ONLY",
                    "real_money_authorized": False,
                }
            )

    columns = [
        "strategy_id",
        "strategy_spec_seal",
        "trial_number",
        "decision_timestamp",
        "earliest_execution_timestamp",
        "execution_timing",
        "symbol",
        "signal_state",
        "target_weight",
        "reference_month",
        "reference_timestamp",
        "decision_close",
        "reference_close",
        "order_intent",
        "real_money_authorized",
    ]
    return pd.DataFrame(targets, columns=columns)


def _parse_decision_day(name: str, value: str) -> pd.Timestamp:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ProspectiveCryptoError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc
    return pd.Timestamp(parsed, tz="UTC")


def development_tsmom_targets(
    data: pd.DataFrame,
    spec: ProspectiveStrategySpec,
    decision_start: str,
    decision_end: str,
) -> pd.DataFrame:
    """Run the frozen signal rule only inside a pre-holdout falsification window.

    This is a pure target generator, not a return evaluator or backtest.  Its
    requested range must stay inside the exact sealed development-evidence
    window; ``development_end`` is the prospective warm-up/first-decision date,
    not permission to inspect later development data under this function name.
    """

    start = _parse_decision_day("decision_start", decision_start)
    end = _parse_decision_day("decision_end", decision_end)
    evidence_start = _parse_decision_day(
        "development_evidence_start", spec.development_evidence_start
    )
    evidence_end = _parse_decision_day("development_evidence_end", spec.development_evidence_end)
    if end < start:
        raise ProspectiveCryptoError("decision_end must not precede decision_start")
    if start < evidence_start or end > evidence_end:
        raise ProspectiveCryptoError(
            "development decisions must stay inside the sealed evidence window"
        )
    return _tsmom_targets(
        data,
        spec,
        decision_start=start,
        decision_end=end,
    )


def prospective_tsmom_targets(
    data: pd.DataFrame,
    spec: ProspectiveStrategySpec,
) -> pd.DataFrame:
    """Emit targets only for the ex-ante prospective campaign window.

    The first decision is the final development close on 2026-08-31 and can be
    executed no earlier than the first holdout open on 2026-09-01.  The same
    private core used by :func:`development_tsmom_targets` is frozen through
    the final 2029-08-31 decision; no holdout-only signal implementation exists.
    """

    return _tsmom_targets(
        data,
        spec,
        decision_start=_parse_decision_day("development_end", spec.development_end),
        decision_end=_parse_decision_day("holdout_end", spec.holdout_end),
    )


__all__ = [
    "CAMPAIGN_MODE",
    "DEVELOPMENT_EVIDENCE_END",
    "DEVELOPMENT_EVIDENCE_START",
    "DEVELOPMENT_END",
    "HOLDOUT_END",
    "HOLDOUT_START",
    "MARKET",
    "POSITION_MODE",
    "PRIMARY_HOLDOUT_END",
    "ProspectiveCryptoError",
    "ProspectiveStrategySpec",
    "SCHEMA_VERSION",
    "STRATEGY_ID",
    "SYMBOLS",
    "VENUE",
    "development_tsmom_targets",
    "load_prospective_strategy_spec",
    "prospective_tsmom_targets",
]
