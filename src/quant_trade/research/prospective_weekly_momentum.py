"""Sealed BTC weekly-momentum intentions for a research-only campaign.

The academic result motivating this campaign is a predictive relationship,
not this executable rule.  This module therefore describes the BTC-only,
binary LONG/CASH translation honestly and keeps it isolated from the retired
monthly TSMOM campaign and from H1-H4.  It has no data loader, backtest,
registry entry, network client, or order-routing path.
"""

from __future__ import annotations

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
STRATEGY_ID = "binance_btc_weekly_momentum_1w_long_cash_v1"
CAMPAIGN_MODE = "PROSPECTIVE_ONLY"
VENUE = "Binance"
MARKET = "Spot"
SYMBOL = "BTCUSDT"
POSITION_MODE = "long_cash"

DEVELOPMENT_DATA_START = "2017-08-17"
DEVELOPMENT_DECISION_START = "2017-08-27"
DEVELOPMENT_DECISION_END = "2023-11-26"
DEVELOPMENT_EVIDENCE_END = "2023-11-28"

PROSPECTIVE_OBSERVATION_START = "2026-08-17"
PROSPECTIVE_FIRST_REFERENCE = "2026-08-23"
PROSPECTIVE_FIRST_DECISION = "2026-08-30"
PROSPECTIVE_FIRST_EXECUTION = "2026-08-31"
PRIMARY_LAST_DECISION = "2028-08-20"
PRIMARY_OBSERVATION_END = "2028-08-27"
FINAL_LAST_DECISION = "2029-08-19"
FINAL_OBSERVATION_END = "2029-08-26"
REVEAL_NOT_BEFORE = "2029-08-27"

_EXPECTED_SOURCE_HYPOTHESIS = {
    "citation": "Liu and Tsyvinski (2021), Risks and Returns of Cryptocurrency",
    "doi": "10.1093/rfs/hhaa113",
    "external_result": "current coin-market weekly return predicts future coin-market returns",
    "translation": "BTCUSDT proxy; positive prior-week return means LONG, otherwise CASH",
    "exact_replication": False,
}
_EXPECTED_SIGNAL_POLICY = {
    "lookback_calendar_days": 7,
    "calendar_timezone": "UTC",
    "decision_frequency": "weekly",
    "decision_weekday": "SUNDAY",
    "decision_bar": "sunday_daily_utc_close",
    "execution_bar": "next_daily_utc_open",
    "decision_to_execution_bars": 1,
    "weekly_return_definition": "close_t_over_close_t_minus_7_calendar_days_minus_1",
    "long_condition": "weekly_return_strictly_positive",
    "cash_condition": "weekly_return_non_positive",
    "missing_reference_action": "NO_SIGNAL_NO_FALLBACK",
    "emit_only_on_state_change": True,
    "rebalance_drift": False,
    "tie_state": "CASH",
}
_EXPECTED_DEVELOPMENT_WINDOW = {
    "data_start": DEVELOPMENT_DATA_START,
    "decision_start": DEVELOPMENT_DECISION_START,
    "decision_end": DEVELOPMENT_DECISION_END,
    "evidence_end": DEVELOPMENT_EVIDENCE_END,
    "fresh_collection_required": True,
    "request_side_end_time_required": True,
}
_EXPECTED_PROSPECTIVE_WINDOW = {
    "observation_start": PROSPECTIVE_OBSERVATION_START,
    "first_reference_date": PROSPECTIVE_FIRST_REFERENCE,
    "first_decision_date": PROSPECTIVE_FIRST_DECISION,
    "first_execution_date": PROSPECTIVE_FIRST_EXECUTION,
    "primary_decision_count": 104,
    "primary_last_decision_date": PRIMARY_LAST_DECISION,
    "primary_observation_end": PRIMARY_OBSERVATION_END,
    "extension_decision_count": 52,
    "total_decision_count": 156,
    "final_last_decision_date": FINAL_LAST_DECISION,
    "final_observation_end": FINAL_OBSERVATION_END,
    "interim_economic_reveal_allowed": False,
    "reveal_not_before": REVEAL_NOT_BEFORE,
    "insufficient_evidence_action": "CONTINUE_EXTENSION_WITHOUT_REVEAL",
}
_EXPECTED_BENCHMARKS = (
    {
        "benchmark_id": "btc_usdt_buy_and_hold",
        "kind": "buy_and_hold",
        "symbol_weights": {SYMBOL: 1.0},
    },
    {
        "benchmark_id": "zero_yield_cash",
        "kind": "cash",
        "annual_return_fraction": 0.0,
    },
)
_EXPECTED_COST_POLICY = {
    "fee_floor_bps_per_side": 10.0,
    "friction_floor_bps_per_side": 5.0,
    "stress_cost_multiplier": 2.0,
    "stress_long_fill_fraction": 0.5,
    "stress_cash_exit_fill_fraction": 1.0,
}
_EXPECTED_DEVELOPMENT_FALSIFICATION_POLICY = {
    "net_total_return_positive": True,
    "outperform_each_benchmark": True,
    "required_benchmark_ids": ("btc_usdt_buy_and_hold", "zero_yield_cash"),
    "contiguous_blocks": 4,
    "minimum_outperforming_blocks": 3,
    "minimum_completed_decisions": 300,
    "minimum_independent_trades": 30,
    "max_drawdown_abs": 0.25,
    "stress_total_return_min": 0.0,
}
_EXPECTED_PROMOTION_BLOCKERS = {
    "gate0": "BINANCE_DEMO_VENUE_POLICY_NOT_IMPLEMENTED",
    "pbo": "NOT_IDENTIFIABLE_SINGLE_TRIAL",
    "pbo_is_mandatory": True,
    "gate4": "ONE_ASSET_100PCT_CONTRADICTS_5PCT_PER_ASSET_AND_20_ASSET_POLICY",
    "maximum_verdict_without_new_governance": "INSUFFICIENT_EVIDENCE",
}
_EXPECTED_SAFETY_POLICY = {
    "leverage_allowed": False,
    "shorts_allowed": False,
    "margin_allowed": False,
    "derivatives_allowed": False,
    "earn_allowed": False,
}
_EXPECTED_AUTHORIZATION = {
    "research_only": True,
    "generic_runner_enabled": False,
    "strategy_registry_enabled": False,
    "live_execution_enabled": False,
    "real_money_authorized": False,
    "external_action_authorized": False,
}


class WeeklyMomentumError(ValueError):
    """Raised when the declaration or supplied OHLCV violates the seal."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WeeklyMomentumError("weekly specs reject NaN and infinity")
        return value
    raise WeeklyMomentumError(f"weekly specs accept JSON-shaped values, got {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_exact(name: str, observed: Any, expected: Any) -> None:
    if canonical_dumps(_thaw(_freeze(observed))) != canonical_dumps(_thaw(_freeze(expected))):
        raise WeeklyMomentumError(f"{name} contradicts the sealed weekly campaign")


def _iso(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WeeklyMomentumError(f"{name} must be an ISO date") from exc


@dataclass(frozen=True)
class WeeklyMomentumSpec:
    """Deeply immutable, content-addressed declaration for exactly one trial."""

    schema_version: int
    strategy_id: str
    campaign_mode: str
    venue: str
    market: str
    symbol: str
    position_mode: str
    source_hypothesis: Mapping[str, Any]
    signal_policy: Mapping[str, Any]
    trial_budget: int
    development_window: Mapping[str, Any]
    prospective_window: Mapping[str, Any]
    benchmarks: Sequence[Mapping[str, Any]]
    cost_policy: Mapping[str, Any]
    development_falsification_policy: Mapping[str, Any]
    promotion_blockers: Mapping[str, Any]
    safety_policy: Mapping[str, Any]
    authorization: Mapping[str, Any]

    def __post_init__(self) -> None:
        mapping_fields = (
            "source_hypothesis",
            "signal_policy",
            "development_window",
            "prospective_window",
            "cost_policy",
            "development_falsification_policy",
            "promotion_blockers",
            "safety_policy",
            "authorization",
        )
        for name in mapping_fields:
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise WeeklyMomentumError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))
        if not isinstance(self.benchmarks, (list, tuple)):
            raise WeeklyMomentumError("benchmarks must be a sequence")
        object.__setattr__(self, "benchmarks", _freeze(self.benchmarks))

        expected_scalars = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": STRATEGY_ID,
            "campaign_mode": CAMPAIGN_MODE,
            "venue": VENUE,
            "market": MARKET,
            "symbol": SYMBOL,
            "position_mode": POSITION_MODE,
            "trial_budget": 1,
        }
        for name, expected in expected_scalars.items():
            _require_exact(name, getattr(self, name), expected)
        expected_structures = {
            "source_hypothesis": _EXPECTED_SOURCE_HYPOTHESIS,
            "signal_policy": _EXPECTED_SIGNAL_POLICY,
            "development_window": _EXPECTED_DEVELOPMENT_WINDOW,
            "prospective_window": _EXPECTED_PROSPECTIVE_WINDOW,
            "benchmarks": _EXPECTED_BENCHMARKS,
            "cost_policy": _EXPECTED_COST_POLICY,
            "development_falsification_policy": _EXPECTED_DEVELOPMENT_FALSIFICATION_POLICY,
            "promotion_blockers": _EXPECTED_PROMOTION_BLOCKERS,
            "safety_policy": _EXPECTED_SAFETY_POLICY,
            "authorization": _EXPECTED_AUTHORIZATION,
        }
        for name, expected in expected_structures.items():
            _require_exact(name, getattr(self, name), expected)
        self._validate_dates()

    def _validate_dates(self) -> None:
        dev_start = _iso("development decision start", DEVELOPMENT_DECISION_START)
        dev_end = _iso("development decision end", DEVELOPMENT_DECISION_END)
        if dev_start.weekday() != 6 or dev_end.weekday() != 6:
            raise WeeklyMomentumError("development decisions must be Sundays")
        observation_start = _iso("observation start", PROSPECTIVE_OBSERVATION_START)
        reference = _iso("first reference", PROSPECTIVE_FIRST_REFERENCE)
        first = _iso("first decision", PROSPECTIVE_FIRST_DECISION)
        execution = _iso("first execution", PROSPECTIVE_FIRST_EXECUTION)
        primary_last = _iso("primary last decision", PRIMARY_LAST_DECISION)
        primary_end = _iso("primary observation end", PRIMARY_OBSERVATION_END)
        final_last = _iso("final last decision", FINAL_LAST_DECISION)
        final_end = _iso("final observation end", FINAL_OBSERVATION_END)
        reveal = _iso("reveal not before", REVEAL_NOT_BEFORE)
        if reference != observation_start + timedelta(days=6):
            raise WeeklyMomentumError("the first reference must close the first observed week")
        if first != reference + timedelta(days=7) or execution != first + timedelta(days=1):
            raise WeeklyMomentumError("first weekly decision/execution dates are inconsistent")
        if primary_last != first + timedelta(weeks=103):
            raise WeeklyMomentumError("primary window must contain exactly 104 decisions")
        if final_last != first + timedelta(weeks=155):
            raise WeeklyMomentumError("full window must contain exactly 156 decisions")
        if primary_end != primary_last + timedelta(weeks=1):
            raise WeeklyMomentumError("primary outcome week is incomplete")
        if final_end != final_last + timedelta(weeks=1) or reveal != final_end + timedelta(days=1):
            raise WeeklyMomentumError("final outcome/reveal dates are inconsistent")

    def canonical_payload(self) -> dict[str, Any]:
        return {field.name: _thaw(getattr(self, field.name)) for field in fields(self)}

    def seal(self) -> str:
        return sha256_of_text(canonical_dumps(self.canonical_payload()))


def load_weekly_momentum_spec(path: str | Path) -> WeeklyMomentumSpec:
    """Load configuration bytes and verify their complete canonical seal."""

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WeeklyMomentumError("weekly config must contain a mapping")
    declared_seal = raw.pop("seal", None)
    if (
        not isinstance(declared_seal, str)
        or len(declared_seal) != 64
        or any(character not in "0123456789abcdef" for character in declared_seal)
    ):
        raise WeeklyMomentumError("weekly config requires a lowercase 64-character seal")
    expected_fields = {field.name for field in fields(WeeklyMomentumSpec)}
    missing = sorted(expected_fields - set(raw))
    unknown = sorted(set(raw) - expected_fields)
    if missing or unknown:
        raise WeeklyMomentumError(
            f"weekly config fields mismatch; missing={missing}, unknown={unknown}"
        )
    try:
        spec = WeeklyMomentumSpec(**raw)
    except TypeError as exc:
        raise WeeklyMomentumError(f"invalid weekly config: {exc}") from exc
    if spec.seal() != declared_seal:
        raise WeeklyMomentumError("weekly config seal mismatch")
    return spec


def _prepare_ohlcv(data: pd.DataFrame, spec: WeeklyMomentumSpec) -> pd.DataFrame:
    try:
        frame = validate_panel_schema(data)
    except MarketDataValidationError as exc:
        raise WeeklyMomentumError(f"invalid weekly OHLCV: {exc}") from exc
    if set(frame["symbol"]) != {spec.symbol}:
        raise WeeklyMomentumError(f"weekly OHLCV symbol must be exactly {spec.symbol}")
    timestamps = frame["timestamp"]
    midnight = (
        timestamps.dt.hour.eq(0)
        & timestamps.dt.minute.eq(0)
        & timestamps.dt.second.eq(0)
        & timestamps.dt.microsecond.eq(0)
    )
    if not bool(midnight.all()):
        raise WeeklyMomentumError("weekly inputs must be UTC daily bars labelled at 00:00")
    numeric = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not bool(pd.notna(numeric).all()) or not bool((abs(numeric) < float("inf")).all()):
        raise WeeklyMomentumError("weekly inputs require finite OHLCV values")
    return frame


def _parse_day(name: str, value: str) -> pd.Timestamp:
    return pd.Timestamp(_iso(name, value), tz="UTC")


def _weekly_targets(
    data: pd.DataFrame,
    spec: WeeklyMomentumSpec,
    *,
    decision_start: pd.Timestamp,
    decision_end: pd.Timestamp,
) -> pd.DataFrame:
    validated_spec = WeeklyMomentumSpec(**spec.canonical_payload())
    if validated_spec.seal() != spec.seal():
        raise WeeklyMomentumError("an invalid weekly strategy spec was supplied")
    frame = _prepare_ohlcv(data, spec)
    closes = {
        pd.Timestamp(row.timestamp): float(row.close) for row in frame.itertuples(index=False)
    }
    states: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    sundays = frame[
        frame["timestamp"].dt.dayofweek.eq(6)
        & frame["timestamp"].between(decision_start, decision_end, inclusive="both")
    ]
    for row in sundays.itertuples(index=False):
        decision_timestamp = pd.Timestamp(row.timestamp)
        reference_timestamp = decision_timestamp - pd.Timedelta(days=7)
        reference_close = closes.get(reference_timestamp)
        if reference_close is None:
            continue
        decision_close = float(row.close)
        weekly_return = decision_close / reference_close - 1.0
        next_state = "LONG" if weekly_return > 0.0 else "CASH"
        if states.get(spec.symbol) == next_state:
            continue
        states[spec.symbol] = next_state
        rows.append(
            {
                "strategy_id": spec.strategy_id,
                "strategy_spec_seal": spec.seal(),
                "trial_number": 1,
                "decision_timestamp": decision_timestamp,
                "earliest_execution_timestamp": decision_timestamp + pd.Timedelta(days=1),
                "execution_timing": "NEXT_DAILY_OPEN",
                "symbol": spec.symbol,
                "signal_state": next_state,
                "target_weight": 1.0 if next_state == "LONG" else 0.0,
                "reference_timestamp": reference_timestamp,
                "decision_close": decision_close,
                "reference_close": reference_close,
                "weekly_return": weekly_return,
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
        "reference_timestamp",
        "decision_close",
        "reference_close",
        "weekly_return",
        "order_intent",
        "real_money_authorized",
    ]
    return pd.DataFrame(rows, columns=columns)


def development_weekly_momentum_targets(
    data: pd.DataFrame,
    spec: WeeklyMomentumSpec,
    decision_start: str,
    decision_end: str,
) -> pd.DataFrame:
    """Emit development intentions without permitting a post-cutoff row."""

    start = _parse_day("decision_start", decision_start)
    end = _parse_day("decision_end", decision_end)
    allowed_start = _parse_day("development decision start", DEVELOPMENT_DECISION_START)
    allowed_end = _parse_day("development decision end", DEVELOPMENT_DECISION_END)
    if end < start:
        raise WeeklyMomentumError("decision_end must not precede decision_start")
    if start < allowed_start or end > allowed_end:
        raise WeeklyMomentumError("development decisions must stay inside the sealed window")
    frame = _prepare_ohlcv(data, spec)
    data_start = _parse_day("development data start", DEVELOPMENT_DATA_START)
    evidence_end = _parse_day("development evidence end", DEVELOPMENT_EVIDENCE_END)
    if bool((frame["timestamp"] < data_start).any()) or bool(
        (frame["timestamp"] > evidence_end).any()
    ):
        raise WeeklyMomentumError("development OHLCV leaves the sealed evidence window")
    return _weekly_targets(frame, spec, decision_start=start, decision_end=end)


def prospective_weekly_momentum_targets(
    data: pd.DataFrame,
    spec: WeeklyMomentumSpec,
) -> pd.DataFrame:
    """Emit only the 156 precommitted future decisions from observed prefixes."""

    frame = _prepare_ohlcv(data, spec)
    observation_start = _parse_day("observation start", PROSPECTIVE_OBSERVATION_START)
    observation_end = _parse_day("final observation end", FINAL_OBSERVATION_END)
    if bool((frame["timestamp"] < observation_start).any()) or bool(
        (frame["timestamp"] > observation_end).any()
    ):
        raise WeeklyMomentumError("prospective OHLCV leaves the sealed observation window")
    return _weekly_targets(
        frame,
        spec,
        decision_start=_parse_day("first decision", PROSPECTIVE_FIRST_DECISION),
        decision_end=_parse_day("final last decision", FINAL_LAST_DECISION),
    )


__all__ = [
    "CAMPAIGN_MODE",
    "DEVELOPMENT_DATA_START",
    "DEVELOPMENT_DECISION_END",
    "DEVELOPMENT_DECISION_START",
    "DEVELOPMENT_EVIDENCE_END",
    "FINAL_LAST_DECISION",
    "FINAL_OBSERVATION_END",
    "MARKET",
    "PRIMARY_LAST_DECISION",
    "PRIMARY_OBSERVATION_END",
    "PROSPECTIVE_FIRST_DECISION",
    "PROSPECTIVE_FIRST_EXECUTION",
    "PROSPECTIVE_FIRST_REFERENCE",
    "PROSPECTIVE_OBSERVATION_START",
    "REVEAL_NOT_BEFORE",
    "SCHEMA_VERSION",
    "STRATEGY_ID",
    "SYMBOL",
    "VENUE",
    "WeeklyMomentumError",
    "WeeklyMomentumSpec",
    "development_weekly_momentum_targets",
    "load_weekly_momentum_spec",
    "prospective_weekly_momentum_targets",
]
