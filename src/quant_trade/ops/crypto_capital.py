"""Fail-closed capital feasibility for the crypto canary.

This module performs arithmetic over operator-supplied snapshots only.  It has
no network client, credential lookup, exchange endpoint, or order-construction
path.  A ``PASS`` only proves that the supplied sleeve can be split across
enough instruments under the sealed sizing constraints; it never authorises
trading.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

CapitalFeasibilityStatus = Literal["PASS", "NO_GO", "INSUFFICIENT_EVIDENCE"]
InstrumentFeasibilityStatus = Literal[
    "FEASIBLE",
    "INFEASIBLE",
    "INVALID_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
]

MAXIMUM_ASSET_FRACTION = 0.05
MAXIMUM_EVIDENCE_AGE = timedelta(hours=24)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_CURRENCY_PATTERN = re.compile(r"[A-Z0-9]{2,10}")
_INSTRUMENT_ID_PATTERN = re.compile(r"CMC:[1-9][0-9]*")
_VENUE_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{3,30}")
_FEE_MODES = frozenset({"QUOTE_ON_TOP", "RECEIVED_ASSET_DEDUCTION"})
_SENSITIVE_SOURCE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "secret",
        "signature",
        "token",
    }
)


@dataclass(frozen=True)
class FxEvidence:
    """A locally supplied, byte-bound conversion snapshot."""

    base_currency: str | None = None
    quote_currency: str | None = None
    quote_per_base: float | None = None
    captured_at_utc: str | None = None
    source: str | None = None
    source_payload: Mapping[str, Any] | None = None
    raw_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitalInstrumentEvidence:
    """Execution limits, price, and fee facts for one possible canary asset."""

    instrument_id: str
    venue_symbol: str | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    reference_ask_quote: float | None = None
    tick_size_quote: float | None = None
    quantity_step: float | None = None
    min_notional_quote: float | None = None
    taker_fee_bps: float | None = None
    fee_currency: str | None = None
    fee_charging_mode: str | None = None
    minimum_fee_amount: float | None = None
    captured_at_utc: str | None = None
    source: str | None = None
    source_payload: Mapping[str, Any] | None = None
    raw_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitalFeasibilityRequest:
    """All bytes needed to reproduce a capital-feasibility decision."""

    sleeve_amount: float
    sleeve_currency: str
    as_of_utc: str
    fx: FxEvidence
    instruments: tuple[CapitalInstrumentEvidence, ...]
    venue: str
    market: str
    environment: str
    account_scope: str
    quote_to_usd_fx: FxEvidence | None
    maximum_asset_fraction: float = MAXIMUM_ASSET_FRACTION

    def to_dict(self) -> dict[str, Any]:
        fx_payload: Any = (
            self.fx.to_dict()
            if isinstance(self.fx, FxEvidence)
            else {"__invalid_type__": type(self.fx).__qualname__}
        )
        instrument_values: Any = self.instruments
        if not isinstance(instrument_values, tuple):
            instrument_values = ({"__invalid_type__": type(instrument_values).__qualname__},)
        return {
            "sleeve_amount": self.sleeve_amount,
            "sleeve_currency": self.sleeve_currency,
            "as_of_utc": self.as_of_utc,
            "fx": fx_payload,
            "instruments": [
                item.to_dict()
                if isinstance(item, CapitalInstrumentEvidence)
                else {"__invalid_type__": type(item).__qualname__}
                for item in instrument_values
            ],
            "venue": self.venue,
            "market": self.market,
            "environment": self.environment,
            "account_scope": self.account_scope,
            "quote_to_usd_fx": (
                self.quote_to_usd_fx.to_dict()
                if isinstance(self.quote_to_usd_fx, FxEvidence)
                else None
                if self.quote_to_usd_fx is None
                else {"__invalid_type__": type(self.quote_to_usd_fx).__qualname__}
            ),
            "maximum_asset_fraction": self.maximum_asset_fraction,
        }


@dataclass(frozen=True)
class CapitalInstrumentAssessment:
    instrument_id: str
    venue_symbol: str | None
    status: InstrumentFeasibilityStatus
    minimum_executable_notional_quote: float | None
    estimated_fee_quote: float | None
    minimum_total_outlay_quote: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitalFeasibility:
    """A byte-bound verdict that can be independently recomputed by Gate 4."""

    request: CapitalFeasibilityRequest
    status: CapitalFeasibilityStatus
    minimum_distinct_assets: int
    maximum_asset_fraction: float
    per_asset_cap_sleeve: float | None
    per_asset_cap_quote: float | None
    sleeve_amount_quote: float | None
    sleeve_amount_usd: float | None
    feasible_symbols: tuple[str, ...]
    assessments: tuple[CapitalInstrumentAssessment, ...]
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    evidence_digest: str
    evaluation_digest: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def is_verified(self) -> bool:
        """Return true only when every output matches a fresh recomputation."""
        try:
            return self == evaluate_capital_feasibility(self.request)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": "CAPITAL_FEASIBILITY",
            "schema_version": 1,
            "status": self.status,
            "passed": self.passed,
            "venue": self.request.venue,
            "market": self.request.market,
            "environment": self.request.environment,
            "account_scope": self.request.account_scope,
            "sleeve_currency": self.request.sleeve_currency,
            "minimum_distinct_assets": self.minimum_distinct_assets,
            "maximum_asset_fraction": self.maximum_asset_fraction,
            "per_asset_cap_sleeve": self.per_asset_cap_sleeve,
            "per_asset_cap_quote": self.per_asset_cap_quote,
            "sleeve_amount_quote": self.sleeve_amount_quote,
            "sleeve_amount_usd": self.sleeve_amount_usd,
            "feasible_symbols": list(self.feasible_symbols),
            "assessments": [item.to_dict() for item in self.assessments],
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "evidence_digest": self.evidence_digest,
            "evaluation_digest": self.evaluation_digest,
            "automatic_transition_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
        }


def _parse_utc(value: Any, name: str, missing: list[str], blockers: list[str]) -> datetime | None:
    if value is None or not isinstance(value, str) or not value.strip():
        missing.append(name)
        return None
    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(
            normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        )
    except ValueError:
        blockers.append(f"{name} must be an explicit UTC timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        blockers.append(f"{name} must be an explicit UTC timestamp")
        return None
    return parsed.astimezone(UTC)


def _currency(value: Any, name: str, missing: list[str], blockers: list[str]) -> str | None:
    if value is None or not isinstance(value, str) or not value.strip():
        missing.append(name)
        return None
    if not _CURRENCY_PATTERN.fullmatch(value):
        blockers.append(f"{name} must be a canonical upper-case currency code")
        return None
    return value


def _number(
    value: Any,
    name: str,
    missing: list[str],
    blockers: list[str],
    *,
    allow_zero: bool = False,
) -> float | None:
    if value is None:
        missing.append(name)
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        blockers.append(f"{name} must be a finite number")
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        blockers.append(f"{name} must be finite and {qualifier}")
        return None
    return number


def _source_fields(
    *,
    prefix: str,
    source: Any,
    source_payload: Any,
    raw_sha256: Any,
    missing: list[str],
    blockers: list[str],
) -> Mapping[str, Any] | None:
    if source is None or not isinstance(source, str) or not source.strip():
        missing.append(f"{prefix}.source")
    payload_digest: str | None = None
    canonical_payload: Mapping[str, Any] | None = None
    if source_payload is None:
        missing.append(f"{prefix}.source_payload")
    elif not isinstance(source_payload, Mapping):
        missing.append(f"{prefix}.source_payload.mapping")
    else:
        canonical_payload = source_payload
        sensitive_keys: set[str] = set()

        def inspect(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    normalized = str(key).strip().lower().replace("-", "_")
                    if normalized in _SENSITIVE_SOURCE_KEYS:
                        sensitive_keys.add(str(key))
                    inspect(child)
            elif isinstance(value, list | tuple):
                for child in value:
                    inspect(child)

        inspect(source_payload)
        if sensitive_keys:
            blockers.append(
                f"{prefix}.source_payload contains prohibited sensitive-looking keys: "
                f"{sorted(sensitive_keys)}"
            )
        try:
            payload_digest = sha256_of_text(canonical_dumps(source_payload))
        except (TypeError, ValueError):
            blockers.append(f"{prefix}.source_payload is not canonical JSON")
    if raw_sha256 is None or not isinstance(raw_sha256, str) or not raw_sha256.strip():
        missing.append(f"{prefix}.raw_sha256")
    elif not _SHA256_PATTERN.fullmatch(raw_sha256):
        blockers.append(f"{prefix}.raw_sha256 must be a lower-case SHA-256")
    elif payload_digest is not None and raw_sha256 != payload_digest:
        blockers.append(f"{prefix}.raw_sha256 contradicts canonical source_payload bytes")
    return canonical_payload


def _crosscheck_payload(
    payload: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    *,
    prefix: str,
    missing: list[str],
    blockers: list[str],
) -> None:
    if payload is None:
        return
    for field_name, expected_value in expected.items():
        path = f"{prefix}.source_payload.{field_name}"
        if field_name not in payload:
            missing.append(path)
            continue
        observed = payload[field_name]
        if expected_value is None:
            continue
        if isinstance(expected_value, int | float) and not isinstance(expected_value, bool):
            if (
                isinstance(observed, bool)
                or not isinstance(observed, int | float)
                or not math.isfinite(float(observed))
                or not math.isclose(
                    float(observed),
                    float(expected_value),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                blockers.append(f"{path} contradicts normalized evidence")
        elif field_name == "captured_at_utc":
            observed_missing: list[str] = []
            observed_blockers: list[str] = []
            expected_missing: list[str] = []
            expected_blockers: list[str] = []
            observed_time = _parse_utc(observed, path, observed_missing, observed_blockers)
            expected_time = _parse_utc(
                expected_value,
                f"{prefix}.captured_at_utc",
                expected_missing,
                expected_blockers,
            )
            if observed_time is None or expected_time is None or observed_time != expected_time:
                blockers.append(f"{path} contradicts normalized evidence")
        elif observed != expected_value:
            blockers.append(f"{path} contradicts normalized evidence")


def _validated_fx(
    fx: FxEvidence,
    *,
    prefix: str,
    as_of: datetime | None,
    missing: list[str],
    blockers: list[str],
) -> tuple[str | None, str | None, float | None]:
    base = _currency(fx.base_currency, f"{prefix}.base_currency", missing, blockers)
    quote = _currency(fx.quote_currency, f"{prefix}.quote_currency", missing, blockers)
    rate = _number(fx.quote_per_base, f"{prefix}.quote_per_base", missing, blockers)
    captured = _parse_utc(
        fx.captured_at_utc,
        f"{prefix}.captured_at_utc",
        missing,
        blockers,
    )
    source_payload = _source_fields(
        prefix=prefix,
        source=fx.source,
        source_payload=fx.source_payload,
        raw_sha256=fx.raw_sha256,
        missing=missing,
        blockers=blockers,
    )
    _crosscheck_payload(
        source_payload,
        {
            "base_currency": fx.base_currency,
            "quote_currency": fx.quote_currency,
            "quote_per_base": fx.quote_per_base,
            "captured_at_utc": fx.captured_at_utc,
        },
        prefix=prefix,
        missing=missing,
        blockers=blockers,
    )
    if captured is not None and as_of is not None:
        age = as_of - captured
        if age < timedelta(0):
            blockers.append(f"{prefix}.captured_at_utc is after as_of_utc")
        elif age > MAXIMUM_EVIDENCE_AGE:
            missing.append(f"{prefix}.current_snapshot")
    return base, quote, rate


def _ceil_to_step(value: float, step: float) -> float:
    decimal_value = Decimal(str(value))
    decimal_step = Decimal(str(step))
    units = (decimal_value / decimal_step).to_integral_value(rounding=ROUND_CEILING)
    return float(units * decimal_step)


def _digest_invalid_safe(value: Any) -> str:
    """Hash even rejected input without allowing NaN or arbitrary objects into JSON."""

    def normalize(item: Any) -> Any:
        if isinstance(item, float) and not math.isfinite(item):
            label = "NaN" if math.isnan(item) else "Infinity" if item > 0 else "-Infinity"
            return {"__invalid_float__": label}
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, list | tuple):
            return [normalize(child) for child in item]
        if item is None or isinstance(item, str | int | float | bool):
            return item
        return {
            "__invalid_type__": f"{type(item).__module__}.{type(item).__qualname__}",
        }

    return sha256_of_text(canonical_dumps(normalize(value)))


def _assessment(
    instrument: CapitalInstrumentEvidence,
    *,
    venue: str,
    market: str,
    environment: str,
    account_scope: str,
    quote_currency: str | None,
    per_asset_cap_quote: float | None,
    as_of: datetime | None,
) -> tuple[CapitalInstrumentAssessment, list[str], list[str]]:
    prefix = f"instruments.{instrument.instrument_id or '<missing>'}"
    missing: list[str] = []
    blockers: list[str] = []
    if not isinstance(instrument.instrument_id, str) or not _INSTRUMENT_ID_PATTERN.fullmatch(
        instrument.instrument_id
    ):
        blockers.append(f"{prefix}.instrument_id must be a canonical CMC:<positive-id>")
    venue_symbol = instrument.venue_symbol
    if venue_symbol is None or not isinstance(venue_symbol, str) or not venue_symbol.strip():
        missing.append(f"{prefix}.venue_symbol")
    elif not _VENUE_SYMBOL_PATTERN.fullmatch(venue_symbol):
        blockers.append(f"{prefix}.venue_symbol must be canonical upper-case Bybit format")
    base = _currency(instrument.base_currency, f"{prefix}.base_currency", missing, blockers)
    quote = _currency(instrument.quote_currency, f"{prefix}.quote_currency", missing, blockers)
    fee_currency = _currency(
        instrument.fee_currency,
        f"{prefix}.fee_currency",
        missing,
        blockers,
    )
    price = _number(
        instrument.reference_ask_quote,
        f"{prefix}.reference_ask_quote",
        missing,
        blockers,
    )
    tick = _number(
        instrument.tick_size_quote,
        f"{prefix}.tick_size_quote",
        missing,
        blockers,
    )
    step = _number(
        instrument.quantity_step,
        f"{prefix}.quantity_step",
        missing,
        blockers,
    )
    minimum = _number(
        instrument.min_notional_quote,
        f"{prefix}.min_notional_quote",
        missing,
        blockers,
    )
    fee_bps = _number(
        instrument.taker_fee_bps,
        f"{prefix}.taker_fee_bps",
        missing,
        blockers,
        allow_zero=True,
    )
    minimum_fee = _number(
        instrument.minimum_fee_amount,
        f"{prefix}.minimum_fee_amount",
        missing,
        blockers,
        allow_zero=True,
    )
    captured = _parse_utc(
        instrument.captured_at_utc,
        f"{prefix}.captured_at_utc",
        missing,
        blockers,
    )
    source_payload = _source_fields(
        prefix=prefix,
        source=instrument.source,
        source_payload=instrument.source_payload,
        raw_sha256=instrument.raw_sha256,
        missing=missing,
        blockers=blockers,
    )
    _crosscheck_payload(
        source_payload,
        {
            "venue": venue,
            "market": market,
            "environment": environment,
            "account_scope": account_scope,
            "instrument_id": instrument.instrument_id,
            "venue_symbol": instrument.venue_symbol,
            "base_currency": instrument.base_currency,
            "quote_currency": instrument.quote_currency,
            "reference_ask_quote": instrument.reference_ask_quote,
            "tick_size_quote": instrument.tick_size_quote,
            "quantity_step": instrument.quantity_step,
            "min_notional_quote": instrument.min_notional_quote,
            "taker_fee_bps": instrument.taker_fee_bps,
            "fee_currency": instrument.fee_currency,
            "fee_charging_mode": instrument.fee_charging_mode,
            "minimum_fee_amount": instrument.minimum_fee_amount,
            "captured_at_utc": instrument.captured_at_utc,
        },
        prefix=prefix,
        missing=missing,
        blockers=blockers,
    )
    if quote is not None and quote_currency is not None and quote != quote_currency:
        blockers.append(f"{prefix}.quote_currency does not match FX quote currency")
    mode = instrument.fee_charging_mode
    if mode is None or not isinstance(mode, str) or not mode.strip():
        missing.append(f"{prefix}.fee_charging_mode")
    elif mode not in _FEE_MODES:
        blockers.append(f"{prefix}.fee_charging_mode is unsupported")
    elif mode == "QUOTE_ON_TOP" and fee_currency is not None and fee_currency != quote:
        blockers.append(f"{prefix}.fee_currency must equal quote currency for QUOTE_ON_TOP")
    elif mode == "RECEIVED_ASSET_DEDUCTION" and fee_currency is not None and fee_currency != base:
        blockers.append(
            f"{prefix}.fee_currency must equal base currency for RECEIVED_ASSET_DEDUCTION"
        )
    if captured is not None and as_of is not None:
        age = as_of - captured
        if age < timedelta(0):
            blockers.append(f"{prefix}.captured_at_utc is after as_of_utc")
        elif age > MAXIMUM_EVIDENCE_AGE:
            missing.append(f"{prefix}.current_snapshot")

    if blockers or missing or per_asset_cap_quote is None:
        status: InstrumentFeasibilityStatus = (
            "INVALID_EVIDENCE" if blockers else "INSUFFICIENT_EVIDENCE"
        )
        return (
            CapitalInstrumentAssessment(
                instrument.instrument_id,
                instrument.venue_symbol,
                status,
                None,
                None,
                None,
                "; ".join(blockers or missing),
            ),
            missing,
            blockers,
        )

    assert price is not None
    assert tick is not None
    assert step is not None
    assert minimum is not None
    assert fee_bps is not None
    assert minimum_fee is not None
    rounded_price = _ceil_to_step(price, tick)
    minimum_quantity = _ceil_to_step(minimum / rounded_price, step)
    executable_notional = rounded_price * minimum_quantity
    proportional_fee_quote = executable_notional * fee_bps / 10_000.0
    if mode == "QUOTE_ON_TOP":
        fee_quote = max(proportional_fee_quote, minimum_fee)
        total_outlay = executable_notional + fee_quote
    else:
        proportional_fee_base = minimum_quantity * fee_bps / 10_000.0
        fee_base = max(proportional_fee_base, minimum_fee)
        if fee_base >= minimum_quantity:
            return (
                CapitalInstrumentAssessment(
                    instrument.instrument_id,
                    instrument.venue_symbol,
                    "INFEASIBLE",
                    executable_notional,
                    fee_base * rounded_price,
                    executable_notional,
                    "minimum base-currency fee consumes the entire executable quantity",
                ),
                missing,
                blockers,
            )
        fee_quote = fee_base * rounded_price
        total_outlay = executable_notional
    feasible = total_outlay <= per_asset_cap_quote + 1e-12
    status = "FEASIBLE" if feasible else "INFEASIBLE"
    reason = (
        "minimum executable buy including fee fits the per-asset cap"
        if feasible
        else "minimum executable buy including fee exceeds the per-asset cap"
    )
    return (
        CapitalInstrumentAssessment(
            instrument.instrument_id,
            instrument.venue_symbol,
            status,
            executable_notional,
            fee_quote,
            total_outlay,
            reason,
        ),
        missing,
        blockers,
    )


def _evaluation_digest_payload(
    *,
    status: CapitalFeasibilityStatus,
    minimum_distinct_assets: int,
    maximum_asset_fraction: float,
    per_asset_cap_sleeve: float | None,
    per_asset_cap_quote: float | None,
    sleeve_amount_quote: float | None,
    sleeve_amount_usd: float | None,
    feasible_symbols: tuple[str, ...],
    assessments: tuple[CapitalInstrumentAssessment, ...],
    blockers: tuple[str, ...],
    missing: tuple[str, ...],
    evidence_digest: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "minimum_distinct_assets": minimum_distinct_assets,
        "maximum_asset_fraction": maximum_asset_fraction,
        "per_asset_cap_sleeve": per_asset_cap_sleeve,
        "per_asset_cap_quote": per_asset_cap_quote,
        "sleeve_amount_quote": sleeve_amount_quote,
        "sleeve_amount_usd": sleeve_amount_usd,
        "feasible_symbols": list(feasible_symbols),
        "assessments": [item.to_dict() for item in assessments],
        "blocking_conditions": list(blockers),
        "missing_conditions": list(missing),
        "evidence_digest": evidence_digest,
    }


def evaluate_capital_feasibility(request: CapitalFeasibilityRequest) -> CapitalFeasibility:
    """Determine whether a sleeve can support twenty capped Spot positions."""
    blockers: list[str] = []
    missing: list[str] = []
    expected_context = {
        "venue": "bybit",
        "market": "spot",
        "environment": "demo",
        "account_scope": "dedicated_subaccount",
    }
    for field_name, expected in expected_context.items():
        observed = getattr(request, field_name)
        if not isinstance(observed, str) or not observed.strip():
            missing.append(field_name)
        elif observed != expected:
            blockers.append(f"{field_name} must be {expected!r} for the Bybit canary")
    sleeve = _number(request.sleeve_amount, "sleeve_amount", missing, blockers)
    requested_fraction = _number(
        request.maximum_asset_fraction,
        "maximum_asset_fraction",
        missing,
        blockers,
    )
    if requested_fraction is not None and requested_fraction > MAXIMUM_ASSET_FRACTION:
        blockers.append(
            f"maximum_asset_fraction cannot exceed the hard ceiling {MAXIMUM_ASSET_FRACTION}"
        )
    effective_fraction = (
        requested_fraction
        if requested_fraction is not None and requested_fraction <= MAXIMUM_ASSET_FRACTION
        else MAXIMUM_ASSET_FRACTION
    )
    sleeve_currency = _currency(
        request.sleeve_currency,
        "sleeve_currency",
        missing,
        blockers,
    )
    as_of = _parse_utc(request.as_of_utc, "as_of_utc", missing, blockers)
    fx_evidence = request.fx
    if not isinstance(fx_evidence, FxEvidence):
        blockers.append("fx must be FxEvidence")
        fx_evidence = FxEvidence()
    fx_base, fx_quote, fx_rate = _validated_fx(
        fx_evidence,
        prefix="fx",
        as_of=as_of,
        missing=missing,
        blockers=blockers,
    )
    if sleeve_currency is not None and fx_base is not None and sleeve_currency != fx_base:
        blockers.append("sleeve_currency does not match FX base currency")

    quote_to_usd_rate: float | None
    if fx_quote == "USD":
        if request.quote_to_usd_fx is not None:
            blockers.append("quote_to_usd_fx must be omitted when the execution quote is USD")
        quote_to_usd_rate = 1.0
    elif request.quote_to_usd_fx is None:
        missing.append("quote_to_usd_fx")
        quote_to_usd_rate = None
    elif not isinstance(request.quote_to_usd_fx, FxEvidence):
        blockers.append("quote_to_usd_fx must be FxEvidence")
        quote_to_usd_rate = None
    else:
        usd_base, usd_quote, quote_to_usd_rate = _validated_fx(
            request.quote_to_usd_fx,
            prefix="quote_to_usd_fx",
            as_of=as_of,
            missing=missing,
            blockers=blockers,
        )
        if fx_quote is not None and usd_base is not None and usd_base != fx_quote:
            blockers.append("quote_to_usd_fx base currency must match execution quote currency")
        if usd_quote is not None and usd_quote != "USD":
            blockers.append("quote_to_usd_fx quote currency must be USD")

    per_asset_cap_sleeve = sleeve * effective_fraction if sleeve is not None else None
    per_asset_cap_quote = (
        per_asset_cap_sleeve * fx_rate
        if per_asset_cap_sleeve is not None and fx_rate is not None
        else None
    )
    sleeve_amount_quote = sleeve * fx_rate if sleeve is not None and fx_rate is not None else None
    sleeve_amount_usd = (
        sleeve_amount_quote * quote_to_usd_rate
        if sleeve_amount_quote is not None and quote_to_usd_rate is not None
        else None
    )
    minimum_distinct_assets = math.ceil(1.0 / effective_fraction)
    instruments = request.instruments
    if not isinstance(instruments, tuple) or not instruments:
        missing.append("instruments")
        instruments = ()
    ids = [
        item.instrument_id for item in instruments if isinstance(item, CapitalInstrumentEvidence)
    ]
    if len(ids) != len(instruments):
        blockers.append("instruments must contain CapitalInstrumentEvidence values")
    if len(ids) != len(set(ids)):
        blockers.append("instrument_id values must be unique")
    venue_symbols = [
        item.venue_symbol
        for item in instruments
        if isinstance(item, CapitalInstrumentEvidence) and item.venue_symbol is not None
    ]
    if len(venue_symbols) != len(set(venue_symbols)):
        blockers.append("venue_symbol values must be unique")
    base_currencies = [
        item.base_currency
        for item in instruments
        if isinstance(item, CapitalInstrumentEvidence) and item.base_currency is not None
    ]
    if len(base_currencies) != len(set(base_currencies)):
        blockers.append("base_currency values must be unique")

    assessments: list[CapitalInstrumentAssessment] = []
    for instrument in instruments:
        if not isinstance(instrument, CapitalInstrumentEvidence):
            continue
        assessment, item_missing, item_blockers = _assessment(
            instrument,
            venue=request.venue,
            market=request.market,
            environment=request.environment,
            account_scope=request.account_scope,
            quote_currency=fx_quote,
            per_asset_cap_quote=per_asset_cap_quote,
            as_of=as_of,
        )
        assessments.append(assessment)
        missing.extend(item_missing)
        blockers.extend(item_blockers)

    feasible_symbols = tuple(
        sorted(
            item.venue_symbol
            for item in assessments
            if item.status == "FEASIBLE" and item.venue_symbol is not None
        )
    )
    if blockers:
        status: CapitalFeasibilityStatus = "NO_GO"
    elif missing:
        status = "INSUFFICIENT_EVIDENCE"
    elif len(feasible_symbols) < minimum_distinct_assets:
        status = "NO_GO"
        blockers.append(
            f"only {len(feasible_symbols)} instruments fit; {minimum_distinct_assets} are required"
        )
    else:
        status = "PASS"

    blockers_tuple = tuple(sorted(set(blockers)))
    missing_tuple = tuple(sorted(set(missing)))
    assessments_tuple = tuple(assessments)
    evidence_digest = _digest_invalid_safe(request.to_dict())
    digest_payload = _evaluation_digest_payload(
        status=status,
        minimum_distinct_assets=minimum_distinct_assets,
        maximum_asset_fraction=effective_fraction,
        per_asset_cap_sleeve=per_asset_cap_sleeve,
        per_asset_cap_quote=per_asset_cap_quote,
        sleeve_amount_quote=sleeve_amount_quote,
        sleeve_amount_usd=sleeve_amount_usd,
        feasible_symbols=feasible_symbols,
        assessments=assessments_tuple,
        blockers=blockers_tuple,
        missing=missing_tuple,
        evidence_digest=evidence_digest,
    )
    evaluation_digest = sha256_of_text(canonical_dumps(digest_payload))
    return CapitalFeasibility(
        request=request,
        status=status,
        minimum_distinct_assets=minimum_distinct_assets,
        maximum_asset_fraction=effective_fraction,
        per_asset_cap_sleeve=per_asset_cap_sleeve,
        per_asset_cap_quote=per_asset_cap_quote,
        sleeve_amount_quote=sleeve_amount_quote,
        sleeve_amount_usd=sleeve_amount_usd,
        feasible_symbols=feasible_symbols,
        assessments=assessments_tuple,
        blocking_conditions=blockers_tuple,
        missing_conditions=missing_tuple,
        evidence_digest=evidence_digest,
        evaluation_digest=evaluation_digest,
    )


__all__ = [
    "CapitalFeasibility",
    "CapitalFeasibilityRequest",
    "CapitalFeasibilityStatus",
    "CapitalInstrumentAssessment",
    "CapitalInstrumentEvidence",
    "FxEvidence",
    "MAXIMUM_ASSET_FRACTION",
    "MAXIMUM_EVIDENCE_AGE",
    "evaluate_capital_feasibility",
]
