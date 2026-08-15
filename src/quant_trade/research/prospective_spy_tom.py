"""Sealed SPY turn-of-month intentions for one research-only campaign.

This module deliberately has no data loader, price input, backtest, registry
entry, network client, credential field, or order-routing path.  It converts a
caller-supplied, explicit XNYS calendar plus timestamps already observable by
the caller into non-executable target intentions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

SCHEMA_VERSION = 1
STRATEGY_ID = "SPY_TOM_Dm1_P3_v1"
CAMPAIGN_MODE = "PAPER_RESEARCH_ONLY"
CALENDAR_ID = "XNYS"
SYMBOL = "SPY"
MARKET_TIMEZONE = "America/New_York"
SPEC_SEAL = "5d2c57f22a4437b3064a596b3dd804c7e1e683b3228d4a5d6901e73f1053c540"

_NY = ZoneInfo(MARKET_TIMEZONE)
_UTC = UTC
_TARGET_CONSTRUCTION_TOKEN = object()

_EXPECTED_SOURCE_HYPOTHESIS = {
    "citation": "McConnell and Xu (2008), Equity Returns at the Turn of the Month",
    "doi": "10.2469/faj.v64.n2.11",
    "published_result": (
        "a four-day U.S. equity turn-of-month return concentration over 1926-2005"
    ),
    "translation": (
        "SPY fractional target from the penultimate session close window through "
        "the third session of the next month"
    ),
    "exact_replication": False,
}
_EXPECTED_CAPITAL_POLICY = {
    "paper_starting_capital_cents": 20_000,
    "maximum_gross_exposure_cents": 19_500,
    "minimum_cash_reserve_cents": 500,
    "entry_target_exposure_cents": 19_500,
    "fractional_shares_required": True,
    "allow_exposure_above_capital": False,
}
_EXPECTED_CALENDAR_POLICY = {
    "calendar_id": CALENDAR_ID,
    "timezone": MARKET_TIMEZONE,
    "calendar_must_be_explicit": True,
    "calendar_months_must_be_declared_complete": True,
    "per_session_open_close_required": True,
    "authoritative_source_receipt_and_hash_required": True,
    "shortened_required_session_action": "EXCLUDE_ENTIRE_PAIR_NO_FALLBACK",
    "market_open_local": "09:30:00",
    "market_close_local": "16:00:00",
}
_EXPECTED_WINDOW_POLICY = {
    "decision_local_time": "15:55:00",
    "earliest_execution_local_offset_minutes": 1,
    "expiry_local_time": "15:58:00",
    "primary_entry_session": "PENULTIMATE_SESSION_OF_MONTH",
    "primary_exit_session_next_month": 3,
    "control_entry_session_next_month": 8,
    "control_exit_session_next_month": 12,
    "primary_holding_intervals": 4,
    "control_holding_intervals": 4,
    "missing_observation_action": "NO_INTENTION_NO_FALLBACK",
    "same_bar_execution_allowed": False,
    "price_input_allowed": False,
}
_EXPECTED_SAMPLE_POLICY = {
    "minimum_paired_months": 120,
    "comparison": "PRIMARY_MINUS_SAME_MONTH_DAY8_TO_DAY12_CONTROL",
    "all_historical_data_classification": "DEVELOPMENT_ONLY",
    "historical_result_may_be_called_holdout": False,
    "parameter_search_allowed": False,
    "interim_rule_change_allowed": False,
}
_EXPECTED_RETURN_ACCOUNTING = {
    "total_return_required": True,
    "price_return_only_allowed": False,
    "point_in_time_corporate_action_receipts_required": True,
    "cash_dividend_policy": "CREDIT_IF_HELD_AT_EX_DATE_OPEN",
    "split_policy": "ADJUST_QUANTITY_AT_EFFECTIVE_SESSION_OPEN",
    "missing_dividend_or_split_evidence_action": "INSUFFICIENT_EVIDENCE",
}
_EXPECTED_INSTRUMENT_POLICY = {
    "allowed_symbols": (SYMBOL,),
    "position_mode": "LONG_OR_CASH",
    "fractional": True,
    "leverage_allowed": False,
    "shorts_allowed": False,
    "options_allowed": False,
    "stops_allowed": False,
    "dynamic_parameters_allowed": False,
}
_EXPECTED_VERDICT_POLICY = {
    "allowed_verdicts": ("NO_GO", "INSUFFICIENT_EVIDENCE"),
    "pass_verdict_allowed": False,
    "maximum_verdict": "INSUFFICIENT_EVIDENCE",
    "minimum_paired_months_before_evaluation": 120,
    "paper_profit_is_live_evidence": False,
}
_EXPECTED_AUTHORIZATION = {
    "research_only": True,
    "paper_observation_only": True,
    "paper_order_routing_enabled": False,
    "strategy_registry_enabled": False,
    "network_enabled": False,
    "credential_access_enabled": False,
    "live_execution_enabled": False,
    "real_money_authorized": False,
    "bank_transfer_authorized": False,
}


class SpyTomError(ValueError):
    """Raised when the sealed campaign or supplied calendar violates policy."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpyTomError("SPY TOM specs reject NaN and infinity")
        return value
    raise SpyTomError(f"SPY TOM specs accept JSON-shaped values, got {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_exact(name: str, observed: Any, expected: Any) -> None:
    observed_json = canonical_dumps(_thaw(_freeze(observed)))
    expected_json = canonical_dumps(_thaw(_freeze(expected)))
    if observed_json != expected_json:
        raise SpyTomError(f"{name} contradicts the sealed SPY TOM campaign")


@dataclass(frozen=True)
class SpyTomSpec:
    """Deeply immutable, content-addressed declaration for exactly one trial."""

    schema_version: int
    strategy_id: str
    campaign_mode: str
    symbol: str
    trial_budget: int
    source_hypothesis: Mapping[str, Any]
    capital_policy: Mapping[str, Any]
    calendar_policy: Mapping[str, Any]
    window_policy: Mapping[str, Any]
    sample_policy: Mapping[str, Any]
    return_accounting: Mapping[str, Any]
    instrument_policy: Mapping[str, Any]
    verdict_policy: Mapping[str, Any]
    authorization: Mapping[str, Any]

    def __post_init__(self) -> None:
        mapping_fields = (
            "source_hypothesis",
            "capital_policy",
            "calendar_policy",
            "window_policy",
            "sample_policy",
            "return_accounting",
            "instrument_policy",
            "verdict_policy",
            "authorization",
        )
        for name in mapping_fields:
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise SpyTomError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))

        expected_scalars = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": STRATEGY_ID,
            "campaign_mode": CAMPAIGN_MODE,
            "symbol": SYMBOL,
            "trial_budget": 1,
        }
        for name, expected in expected_scalars.items():
            _require_exact(name, getattr(self, name), expected)
        expected_structures = {
            "source_hypothesis": _EXPECTED_SOURCE_HYPOTHESIS,
            "capital_policy": _EXPECTED_CAPITAL_POLICY,
            "calendar_policy": _EXPECTED_CALENDAR_POLICY,
            "window_policy": _EXPECTED_WINDOW_POLICY,
            "sample_policy": _EXPECTED_SAMPLE_POLICY,
            "return_accounting": _EXPECTED_RETURN_ACCOUNTING,
            "instrument_policy": _EXPECTED_INSTRUMENT_POLICY,
            "verdict_policy": _EXPECTED_VERDICT_POLICY,
            "authorization": _EXPECTED_AUTHORIZATION,
        }
        for name, expected in expected_structures.items():
            _require_exact(name, getattr(self, name), expected)

    def canonical_payload(self) -> dict[str, Any]:
        """Return the complete declaration as mutable JSON-shaped data."""

        return {field.name: _thaw(getattr(self, field.name)) for field in fields(self)}

    def seal(self) -> str:
        """Return the SHA-256 content address of the complete declaration."""

        return sha256_of_text(canonical_dumps(self.canonical_payload()))


def load_spy_tom_spec(path: str | Path) -> SpyTomSpec:
    """Load a YAML declaration and verify every field against its canonical seal."""

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpyTomError(f"invalid SPY TOM YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SpyTomError("SPY TOM config must contain a mapping")
    declared_seal = raw.pop("seal", None)
    if (
        not isinstance(declared_seal, str)
        or len(declared_seal) != 64
        or any(character not in "0123456789abcdef" for character in declared_seal)
    ):
        raise SpyTomError("SPY TOM config requires a lowercase 64-character seal")
    expected_fields = {field.name for field in fields(SpyTomSpec)}
    missing = sorted(expected_fields - set(raw))
    unknown = sorted(set(raw) - expected_fields)
    if missing or unknown:
        raise SpyTomError(f"SPY TOM config fields mismatch; missing={missing}, unknown={unknown}")
    try:
        spec = SpyTomSpec(**raw)
    except TypeError as exc:
        raise SpyTomError(f"invalid SPY TOM config: {exc}") from exc
    if spec.seal() != declared_seal:
        raise SpyTomError("SPY TOM config seal mismatch")
    if declared_seal != SPEC_SEAL:
        raise SpyTomError("SPY TOM config does not match the committed campaign seal")
    return spec


def _month_index(value: str) -> int:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except (TypeError, ValueError) as exc:
        raise SpyTomError("complete calendar months must use YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise SpyTomError("complete calendar months must use zero-padded YYYY-MM")
    return parsed.year * 12 + parsed.month - 1


@dataclass(frozen=True)
class ExchangeSession:
    """One explicit XNYS session with DST-aware official-style hours."""

    session_date: date
    open_timestamp: datetime
    close_timestamp: datetime

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise SpyTomError("session_date must be a date, not a datetime")
        if self.session_date.weekday() >= 5:
            raise SpyTomError("XNYS sessions cannot be Saturdays or Sundays")
        values = (self.open_timestamp, self.close_timestamp)
        if any(
            type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
            for value in values
        ):
            raise SpyTomError("session open and close must be timezone-aware datetimes")
        opened = self.open_timestamp.astimezone(_NY)
        closed = self.close_timestamp.astimezone(_NY)
        if opened.date() != self.session_date or closed.date() != self.session_date:
            raise SpyTomError("session open and close must match session_date in New York")
        if opened.time().replace(tzinfo=None) != time(9, 30):
            raise SpyTomError("XNYS session open must be exactly 09:30 New York time")
        if closed.time().replace(tzinfo=None) not in {time(13, 0), time(16, 0)}:
            raise SpyTomError("XNYS session close must be 13:00 or 16:00 New York time")
        if not opened < closed:
            raise SpyTomError("session open must precede session close")
        object.__setattr__(self, "open_timestamp", opened)
        object.__setattr__(self, "close_timestamp", closed)


@dataclass(frozen=True)
class ExplicitExchangeCalendar:
    """Structurally validated, caller-attested complete XNYS session months.

    The class does not invent holidays.  The caller must obtain and freeze the
    authoritative session list separately, then explicitly declare each month
    complete.  This module only validates structure and uses the supplied
    dates; it never fetches or repairs a calendar.
    """

    calendar_id: str
    complete_months: Sequence[str]
    sessions: Sequence[ExchangeSession]

    def __post_init__(self) -> None:
        if self.calendar_id != CALENDAR_ID:
            raise SpyTomError(f"calendar_id must be exactly {CALENDAR_ID}")
        if isinstance(self.complete_months, (str, bytes)) or not isinstance(
            self.complete_months, (list, tuple)
        ):
            raise SpyTomError("complete_months must be an ordered sequence")
        months = tuple(self.complete_months)
        if len(months) < 2:
            raise SpyTomError("calendar requires at least two complete adjacent months")
        month_indices = tuple(_month_index(month) for month in months)
        if any(
            right != left + 1 for left, right in zip(month_indices, month_indices[1:], strict=False)
        ):
            raise SpyTomError("complete calendar months must be unique, ordered, and adjacent")

        if isinstance(self.sessions, (str, bytes)) or not isinstance(self.sessions, (list, tuple)):
            raise SpyTomError("sessions must be an ordered sequence")
        sessions = tuple(self.sessions)
        if not sessions:
            raise SpyTomError("sessions must not be empty")
        for session in sessions:
            if type(session) is not ExchangeSession:
                raise SpyTomError("sessions must contain exact ExchangeSession values")
            # Rebuild to detect object.__new__ or post-construction forgery.
            try:
                ExchangeSession(
                    session_date=session.session_date,
                    open_timestamp=session.open_timestamp,
                    close_timestamp=session.close_timestamp,
                )
            except (AttributeError, TypeError, SpyTomError) as exc:
                raise SpyTomError("a forged or invalid exchange session was supplied") from exc
        if any(
            right.session_date <= left.session_date
            for left, right in zip(sessions, sessions[1:], strict=False)
        ):
            raise SpyTomError("sessions must be unique and strictly increasing")

        grouped: dict[str, list[date]] = defaultdict(list)
        for session in sessions:
            grouped[session.session_date.strftime("%Y-%m")].append(session.session_date)
        if set(grouped) != set(months):
            raise SpyTomError("session_dates must belong exactly to the declared complete months")
        for month in months:
            month_sessions = grouped[month]
            if len(month_sessions) < 12:
                raise SpyTomError("each complete month needs at least 12 explicit XNYS sessions")
            if month_sessions[0].day > 7 or month_sessions[-1].day < 22:
                raise SpyTomError("a declared complete month appears truncated")

        object.__setattr__(self, "complete_months", months)
        object.__setattr__(self, "sessions", sessions)

    @property
    def session_dates(self) -> tuple[date, ...]:
        return tuple(session.session_date for session in self.sessions)

    def sessions_by_month(self) -> Mapping[str, tuple[date, ...]]:
        grouped: dict[str, list[date]] = defaultdict(list)
        for session in self.sessions:
            grouped[session.session_date.strftime("%Y-%m")].append(session.session_date)
        return MappingProxyType({month: tuple(grouped[month]) for month in self.complete_months})

    def session_by_date(self) -> Mapping[date, ExchangeSession]:
        return MappingProxyType({session.session_date: session for session in self.sessions})


@dataclass(frozen=True)
class TargetIntention:
    """A deterministic research target, never an executable order."""

    strategy_id: str
    strategy_spec_seal: str
    pair_id: str
    leg: str
    action: str
    symbol: str
    decision_timestamp: datetime
    earliest_execution_timestamp: datetime
    expires_at: datetime
    target_exposure_cents: int
    maximum_gross_exposure_cents: int
    minimum_cash_reserve_cents: int
    fractional_shares_required: bool
    order_intent: str
    verdict_ceiling: str
    real_money_authorized: bool
    _construction_token: InitVar[object] = None

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _TARGET_CONSTRUCTION_TOKEN:
            raise SpyTomError("TargetIntention may only be constructed by the sealed generator")
        exact_values = {
            "strategy_id": STRATEGY_ID,
            "strategy_spec_seal": SPEC_SEAL,
            "symbol": SYMBOL,
            "maximum_gross_exposure_cents": 19_500,
            "minimum_cash_reserve_cents": 500,
            "fractional_shares_required": True,
            "order_intent": "RESEARCH_TARGET_ONLY",
            "verdict_ceiling": "INSUFFICIENT_EVIDENCE",
            "real_money_authorized": False,
        }
        for name, expected in exact_values.items():
            if getattr(self, name) != expected or type(getattr(self, name)) is not type(expected):
                raise SpyTomError(f"target {name} contradicts the sealed campaign")
        if self.leg not in {"PRIMARY", "CONTROL"}:
            raise SpyTomError("target leg must be PRIMARY or CONTROL")
        if self.action not in {"ENTRY", "EXIT"}:
            raise SpyTomError("target action must be ENTRY or EXIT")
        expected_exposure = 19_500 if self.action == "ENTRY" else 0
        if type(self.target_exposure_cents) is not int or (
            self.target_exposure_cents != expected_exposure
        ):
            raise SpyTomError("target exposure contradicts the sealed action")
        if self.target_exposure_cents + self.minimum_cash_reserve_cents > 20_000:
            raise SpyTomError("target exposure and reserve exceed the paper capital")

        timestamps = (
            self.decision_timestamp,
            self.earliest_execution_timestamp,
            self.expires_at,
        )
        if any(
            type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
            for value in timestamps
        ):
            raise SpyTomError("target timestamps must be timezone-aware datetimes")
        decision_local = self.decision_timestamp.astimezone(_NY)
        earliest_local = self.earliest_execution_timestamp.astimezone(_NY)
        expiry_local = self.expires_at.astimezone(_NY)
        if decision_local.time().replace(tzinfo=None) != time(15, 55):
            raise SpyTomError("target decision must be exactly 15:55 New York time")
        if earliest_local != decision_local + timedelta(minutes=1):
            raise SpyTomError("target earliest execution must be t+1 minute")
        if expiry_local != _local_timestamp(decision_local.date(), 15, 58):
            raise SpyTomError("target expiry must be 15:58 New York time on the decision date")

        parts = self.pair_id.split("_TO_")
        if len(parts) != 2:
            raise SpyTomError("target pair_id must bind adjacent YYYY-MM months")
        anchor_index = _month_index(parts[0])
        following_index = _month_index(parts[1])
        if following_index != anchor_index + 1:
            raise SpyTomError("target pair_id must bind adjacent YYYY-MM months")
        expected_month = parts[0] if self.leg == "PRIMARY" and self.action == "ENTRY" else parts[1]
        if decision_local.strftime("%Y-%m") != expected_month:
            raise SpyTomError("target decision month contradicts its pair and leg")


def _validated_spec(spec: SpyTomSpec) -> SpyTomSpec:
    if type(spec) is not SpyTomSpec:
        raise SpyTomError("an exact SpyTomSpec instance is required")
    try:
        candidate = SpyTomSpec(**spec.canonical_payload())
    except (AttributeError, TypeError, SpyTomError) as exc:
        raise SpyTomError("a forged or invalid SPY TOM spec was supplied") from exc
    if candidate.seal() != spec.seal():
        raise SpyTomError("a forged or invalid SPY TOM spec was supplied")
    return candidate


def _local_timestamp(session_date: date, hour: int, minute: int) -> datetime:
    return datetime.combine(session_date, time(hour, minute), tzinfo=_NY)


def _normalize_as_of(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SpyTomError("as_of must be a timezone-aware datetime")
    return value.astimezone(_UTC)


def _observable_instants(
    values: Sequence[datetime],
    *,
    calendar: ExplicitExchangeCalendar,
    as_of_utc: datetime,
) -> frozenset[datetime]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise SpyTomError("observable_timestamps must be an ordered sequence")
    sessions = set(calendar.session_dates)
    normalized: list[datetime] = []
    previous: datetime | None = None
    for value in values:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise SpyTomError("observable timestamps must be timezone-aware datetimes")
        instant = value.astimezone(_UTC)
        local = instant.astimezone(_NY)
        if local.date() not in sessions:
            raise SpyTomError("an observable timestamp falls outside an explicit XNYS session")
        if local.time().replace(tzinfo=None) != time(15, 55):
            raise SpyTomError("observable timestamps must be exactly 15:55:00 New York time")
        if instant > as_of_utc:
            raise SpyTomError("observable timestamps cannot be later than as_of")
        if previous is not None and instant <= previous:
            raise SpyTomError("observable timestamps must be unique and strictly increasing")
        normalized.append(instant)
        previous = instant
    return frozenset(normalized)


def _scheduled_events(
    calendar: ExplicitExchangeCalendar,
) -> list[tuple[datetime, str, str, str]]:
    grouped = calendar.sessions_by_month()
    events: list[tuple[datetime, str, str, str]] = []
    for anchor, following in zip(
        calendar.complete_months,
        calendar.complete_months[1:],
        strict=False,
    ):
        anchor_sessions = grouped[anchor]
        following_sessions = grouped[following]
        pair_id = f"{anchor}_TO_{following}"
        events.extend(
            (
                (_local_timestamp(anchor_sessions[-2], 15, 55), pair_id, "PRIMARY", "ENTRY"),
                (_local_timestamp(following_sessions[2], 15, 55), pair_id, "PRIMARY", "EXIT"),
                (_local_timestamp(following_sessions[7], 15, 55), pair_id, "CONTROL", "ENTRY"),
                (_local_timestamp(following_sessions[11], 15, 55), pair_id, "CONTROL", "EXIT"),
            )
        )
    return sorted(events, key=lambda item: item[0].astimezone(_UTC))


def generate_spy_tom_targets(
    spec: SpyTomSpec,
    calendar: ExplicitExchangeCalendar,
    observable_timestamps: Sequence[datetime],
    *,
    as_of: datetime,
) -> tuple[TargetIntention, ...]:
    """Generate prefix-causal target intentions from explicit observations.

    A scheduled event is emitted only when its exact 15:55 New York timestamp
    is present in ``observable_timestamps`` and no later than ``as_of``.  The
    earliest possible execution is the following minute and the intention
    expires at 15:58.  Missing timestamps are never shifted or filled.
    """

    validated_spec = _validated_spec(spec)
    if type(calendar) is not ExplicitExchangeCalendar:
        raise SpyTomError("an exact ExplicitExchangeCalendar instance is required")
    # Rebuild to detect post-construction mutation or object.__new__ forgery.
    try:
        validated_calendar = ExplicitExchangeCalendar(
            calendar_id=calendar.calendar_id,
            complete_months=calendar.complete_months,
            sessions=calendar.sessions,
        )
    except (AttributeError, TypeError, SpyTomError) as exc:
        raise SpyTomError("a forged or invalid explicit calendar was supplied") from exc

    as_of_utc = _normalize_as_of(as_of)
    observed = _observable_instants(
        observable_timestamps,
        calendar=validated_calendar,
        as_of_utc=as_of_utc,
    )
    capital = validated_spec.capital_policy
    seal = validated_spec.seal()
    intentions: list[TargetIntention] = []
    schedule = validated_calendar.session_by_date()
    events = _scheduled_events(validated_calendar)
    shortened_pairs = {
        pair_id
        for decision, pair_id, _leg, _action in events
        if schedule[decision.date()].close_timestamp < _local_timestamp(decision.date(), 15, 58)
    }
    for decision, pair_id, leg, action in events:
        if pair_id in shortened_pairs:
            continue
        decision_utc = decision.astimezone(_UTC)
        if decision_utc not in observed or decision_utc > as_of_utc:
            continue
        intentions.append(
            TargetIntention(
                strategy_id=validated_spec.strategy_id,
                strategy_spec_seal=seal,
                pair_id=pair_id,
                leg=leg,
                action=action,
                symbol=validated_spec.symbol,
                decision_timestamp=decision,
                earliest_execution_timestamp=decision + timedelta(minutes=1),
                expires_at=_local_timestamp(decision.date(), 15, 58),
                target_exposure_cents=(
                    int(capital["entry_target_exposure_cents"]) if action == "ENTRY" else 0
                ),
                maximum_gross_exposure_cents=int(capital["maximum_gross_exposure_cents"]),
                minimum_cash_reserve_cents=int(capital["minimum_cash_reserve_cents"]),
                fractional_shares_required=True,
                order_intent="RESEARCH_TARGET_ONLY",
                verdict_ceiling="INSUFFICIENT_EVIDENCE",
                real_money_authorized=False,
                _construction_token=_TARGET_CONSTRUCTION_TOKEN,
            )
        )
    return tuple(intentions)


__all__ = [
    "CALENDAR_ID",
    "CAMPAIGN_MODE",
    "MARKET_TIMEZONE",
    "SCHEMA_VERSION",
    "SPEC_SEAL",
    "STRATEGY_ID",
    "SYMBOL",
    "ExplicitExchangeCalendar",
    "ExchangeSession",
    "SpyTomError",
    "SpyTomSpec",
    "TargetIntention",
    "generate_spy_tom_targets",
    "load_spy_tom_spec",
]
