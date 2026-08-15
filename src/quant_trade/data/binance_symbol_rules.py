"""Causal, locally integrity-checked Binance Spot symbol-rule observations.

``/api/v3/exchangeInfo`` is a current snapshot, not a historical API.  Its
receipt capture time is therefore the earliest instant at which its contents
may be inspected.  A local SHA chain proves consistency, not authenticity:
even a receipt self-labelled ``live`` remains UNATTESTED until an independent
external attestation mechanism exists.

This module is offline and cannot fetch data, evaluate P&L, submit orders, or
authorize real money.  Complete filters here are evidence, not a claim that an
order is executable.
"""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    sha256_of_bytes,
    sha256_of_text,
)
from quant_trade.evidence.receipts import (
    REAL_SOURCE_KINDS,
    TEST_ONLY_SOURCE_KINDS,
    load_receipts,
    normalized_rows_sha256,
    verify_receipt_chain,
)

BINANCE_SYMBOL_RULES_SCHEMA_VERSION = 2
BINANCE_EXCHANGE_INFO_ENDPOINT = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_SYMBOL_RULES_ADAPTER = "data.binance_spot_symbol_rules.exchange_info"
BINANCE_SYMBOL_RULES_ADAPTER_VERSION = "2"
BINANCE_SPOT_VENUE = "binance"
BINANCE_SPOT_QUOTE_ASSET = "USDT"
BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS = 300

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ASSET_RE = re.compile(r"[A-Z0-9]+")
_STATUS_RE = re.compile(r"[A-Z][A-Z0-9_]*")


class BinanceSymbolRulesError(ValueError):
    """Raised when symbol-rule evidence is ambiguous, non-causal, or tampered."""


class SymbolRuleAvailability(StrEnum):
    """Fail-closed result of a point-in-time rule lookup."""

    # Reserved for a future independently attested source.  V2 has no code
    # path capable of constructing this state.
    AVAILABLE_REAL = "AVAILABLE_REAL"
    NOT_YET_OBSERVED = "NOT_YET_OBSERVED"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    TEST_ONLY_PROVENANCE = "TEST_ONLY_PROVENANCE"
    UNATTESTED_SOURCE = "UNATTESTED_SOURCE"
    SYMBOL_ABSENT_FROM_LATEST_SNAPSHOT = "SYMBOL_ABSENT_FROM_LATEST_SNAPSHOT"
    SPOT_TRADING_DISABLED = "SPOT_TRADING_DISABLED"
    SYMBOL_NOT_TRADING = "SYMBOL_NOT_TRADING"


def _utc_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BinanceSymbolRulesError(f"{field_name} must be an explicit UTC timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise BinanceSymbolRulesError(f"{field_name} must be an explicit UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise BinanceSymbolRulesError(f"{field_name} must be an explicit UTC timestamp")
    return parsed.astimezone(UTC)


def _utc_text(value: Any, field_name: str) -> str:
    parsed = _utc_datetime(value, field_name)
    timespec = "microseconds" if parsed.microsecond else "seconds"
    return parsed.isoformat(timespec=timespec).replace("+00:00", "Z")


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise BinanceSymbolRulesError(f"{field_name} must be a lower-case SHA-256")
    return value


def _decimal_text(value: Any, field_name: str, *, allow_zero: bool = False) -> str:
    # Binance publishes exact rule quantities as JSON strings.  JSON floats
    # would silently bind the ledger to a lossy representation.
    qualifier = "non-negative" if allow_zero else "positive"
    if not isinstance(value, str) or not value.strip():
        raise BinanceSymbolRulesError(f"{field_name} must be a {qualifier} decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise BinanceSymbolRulesError(f"{field_name} must be a {qualifier} decimal string") from exc
    if (
        not parsed.is_finite()
        or parsed.is_signed()
        or parsed < 0
        or (not allow_zero and parsed == 0)
    ):
        raise BinanceSymbolRulesError(f"{field_name} must be a {qualifier} decimal string")
    rendered = format(parsed, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _non_negative_int(value: Any, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise BinanceSymbolRulesError(f"{field_name} must be a non-negative integer")
    return value


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise BinanceSymbolRulesError(f"{field_name} must be an explicit boolean")
    return value


def _canonical_symbol(value: Any, field_name: str = "venue_symbol") -> str:
    if not isinstance(value, str) or _ASSET_RE.fullmatch(value) is None:
        raise BinanceSymbolRulesError(f"{field_name} must be canonical upper-case alphanumeric")
    return value


def _optional_group_all_or_none(values: tuple[Any, ...], field_name: str) -> None:
    present = tuple(value is not None for value in values)
    if any(present) and not all(present):
        raise BinanceSymbolRulesError(f"{field_name} fields must be all present or all absent")


@dataclass(frozen=True)
class BinanceSpotSymbolRule:
    """Exact Spot-USDT filters plus locally verifiable observation metadata."""

    venue_symbol: str
    base_asset: str
    quote_asset: str
    exchange_status: str
    spot_trading_allowed: bool

    tick_size: str
    tick_size_enabled: bool
    quantity_step: str
    min_quantity: str
    max_quantity: str

    market_quantity_step: str
    market_quantity_step_enabled: bool
    market_min_quantity: str
    market_min_quantity_enabled: bool
    market_max_quantity: str
    market_max_quantity_enabled: bool

    min_notional_quote: str | None
    min_notional_apply_to_market: bool | None
    min_notional_avg_price_mins: int | None

    notional_min_quote: str | None
    notional_apply_min_to_market: bool | None
    notional_max_quote: str | None
    notional_apply_max_to_market: bool | None
    notional_avg_price_mins: int | None

    observed_at_utc: str
    source_raw_sha256: str
    source_receipt_sha256: str
    receipt_declared_source_kind: str

    def __post_init__(self) -> None:
        _canonical_symbol(self.venue_symbol)
        _canonical_symbol(self.base_asset, "base_asset")
        if self.quote_asset != BINANCE_SPOT_QUOTE_ASSET:
            raise BinanceSymbolRulesError("quote_asset must be USDT")
        if self.venue_symbol != f"{self.base_asset}{self.quote_asset}":
            raise BinanceSymbolRulesError("venue_symbol must equal base_asset + quote_asset")
        if (
            not isinstance(self.exchange_status, str)
            or _STATUS_RE.fullmatch(self.exchange_status) is None
        ):
            raise BinanceSymbolRulesError("exchange_status must be canonical upper-case text")
        _required_bool(self.spot_trading_allowed, "spot_trading_allowed")

        tick = _decimal_text(self.tick_size, "tick_size", allow_zero=True)
        if tick != self.tick_size:
            raise BinanceSymbolRulesError("tick_size must use canonical decimal text")
        _required_bool(self.tick_size_enabled, "tick_size_enabled")
        if self.tick_size_enabled != (Decimal(self.tick_size) > 0):
            raise BinanceSymbolRulesError("tick_size_enabled must equal tick_size > 0")
        for field_name in ("quantity_step", "min_quantity", "max_quantity"):
            canonical = _decimal_text(getattr(self, field_name), field_name)
            if canonical != getattr(self, field_name):
                raise BinanceSymbolRulesError(f"{field_name} must use canonical decimal text")
        if Decimal(self.max_quantity) < Decimal(self.min_quantity):
            raise BinanceSymbolRulesError("max_quantity must be no smaller than min_quantity")

        market_fields = (
            ("market_quantity_step", "market_quantity_step_enabled"),
            ("market_min_quantity", "market_min_quantity_enabled"),
            ("market_max_quantity", "market_max_quantity_enabled"),
        )
        for value_name, enabled_name in market_fields:
            value = getattr(self, value_name)
            canonical = _decimal_text(value, value_name, allow_zero=True)
            if canonical != value:
                raise BinanceSymbolRulesError(f"{value_name} must use canonical decimal text")
            enabled = _required_bool(getattr(self, enabled_name), enabled_name)
            if enabled != (Decimal(value) > 0):
                raise BinanceSymbolRulesError(f"{enabled_name} must equal {value_name} > 0")
        if (
            self.market_min_quantity_enabled
            and self.market_max_quantity_enabled
            and Decimal(self.market_max_quantity) < Decimal(self.market_min_quantity)
        ):
            raise BinanceSymbolRulesError(
                "enabled market_max_quantity must be no smaller than market_min_quantity"
            )

        min_notional_group = (
            self.min_notional_quote,
            self.min_notional_apply_to_market,
            self.min_notional_avg_price_mins,
        )
        _optional_group_all_or_none(min_notional_group, "MIN_NOTIONAL")
        if self.min_notional_quote is not None:
            if (
                _decimal_text(self.min_notional_quote, "min_notional_quote")
                != self.min_notional_quote
            ):
                raise BinanceSymbolRulesError("min_notional_quote must use canonical decimal text")
            _required_bool(
                self.min_notional_apply_to_market,
                "min_notional_apply_to_market",
            )
            _non_negative_int(
                self.min_notional_avg_price_mins,
                "min_notional_avg_price_mins",
            )

        notional_group = (
            self.notional_min_quote,
            self.notional_apply_min_to_market,
            self.notional_max_quote,
            self.notional_apply_max_to_market,
            self.notional_avg_price_mins,
        )
        _optional_group_all_or_none(notional_group, "NOTIONAL")
        if self.notional_min_quote is not None:
            assert self.notional_max_quote is not None
            assert self.notional_apply_min_to_market is not None
            assert self.notional_apply_max_to_market is not None
            assert self.notional_avg_price_mins is not None
            for field_name in ("notional_min_quote", "notional_max_quote"):
                value = getattr(self, field_name)
                if _decimal_text(value, field_name) != value:
                    raise BinanceSymbolRulesError(f"{field_name} must use canonical decimal text")
            if Decimal(self.notional_max_quote) < Decimal(self.notional_min_quote):
                raise BinanceSymbolRulesError(
                    "notional_max_quote must be no smaller than notional_min_quote"
                )
            _required_bool(
                self.notional_apply_min_to_market,
                "notional_apply_min_to_market",
            )
            _required_bool(
                self.notional_apply_max_to_market,
                "notional_apply_max_to_market",
            )
            _non_negative_int(self.notional_avg_price_mins, "notional_avg_price_mins")
        if self.min_notional_quote is None and self.notional_min_quote is None:
            raise BinanceSymbolRulesError(
                "at least one complete MIN_NOTIONAL or NOTIONAL filter is required"
            )

        if _utc_text(self.observed_at_utc, "observed_at_utc") != self.observed_at_utc:
            raise BinanceSymbolRulesError("observed_at_utc must use canonical UTC text")
        _sha256(self.source_raw_sha256, "source_raw_sha256")
        _sha256(self.source_receipt_sha256, "source_receipt_sha256")
        if self.receipt_declared_source_kind not in REAL_SOURCE_KINDS + TEST_ONLY_SOURCE_KINDS:
            raise BinanceSymbolRulesError(
                "receipt_declared_source_kind is not a supported receipt label"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BinanceSpotSymbolRulesSnapshot:
    """One full-USDT observation; its local hashes do not attest external origin."""

    observed_at_utc: str
    server_time_utc: str
    source_endpoint: str
    source_adapter: str
    source_adapter_version: str
    source_raw_sha256: str
    source_receipt_sha256: str
    receipt_declared_source_kind: str
    rules: tuple[BinanceSpotSymbolRule, ...]

    def __post_init__(self) -> None:
        if _utc_text(self.observed_at_utc, "observed_at_utc") != self.observed_at_utc:
            raise BinanceSymbolRulesError("observed_at_utc must use canonical UTC text")
        if _utc_text(self.server_time_utc, "server_time_utc") != self.server_time_utc:
            raise BinanceSymbolRulesError("server_time_utc must use canonical UTC text")
        observed = _utc_datetime(self.observed_at_utc, "observed_at_utc")
        server = _utc_datetime(self.server_time_utc, "server_time_utc")
        skew = observed - server
        if skew < timedelta(0):
            raise BinanceSymbolRulesError("observed_at_utc cannot precede Binance server_time_utc")
        if skew > timedelta(seconds=BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS):
            raise BinanceSymbolRulesError("capture/server skew exceeds the sealed maximum")
        if self.source_endpoint != BINANCE_EXCHANGE_INFO_ENDPOINT:
            raise BinanceSymbolRulesError("source_endpoint is not the sealed Binance endpoint")
        if self.source_adapter != BINANCE_SYMBOL_RULES_ADAPTER:
            raise BinanceSymbolRulesError("source_adapter is not the sealed rules adapter")
        if self.source_adapter_version != BINANCE_SYMBOL_RULES_ADAPTER_VERSION:
            raise BinanceSymbolRulesError("source_adapter_version is unsupported")
        _sha256(self.source_raw_sha256, "source_raw_sha256")
        _sha256(self.source_receipt_sha256, "source_receipt_sha256")
        if self.receipt_declared_source_kind not in REAL_SOURCE_KINDS + TEST_ONLY_SOURCE_KINDS:
            raise BinanceSymbolRulesError(
                "receipt_declared_source_kind is not a supported receipt label"
            )
        if not isinstance(self.rules, tuple) or not self.rules:
            raise BinanceSymbolRulesError("rules must be a non-empty immutable tuple")
        if tuple(sorted(self.rules, key=lambda item: item.venue_symbol)) != self.rules:
            raise BinanceSymbolRulesError("rules must be sorted by venue_symbol")
        symbols = [rule.venue_symbol for rule in self.rules]
        if len(symbols) != len(set(symbols)):
            raise BinanceSymbolRulesError("duplicate venue_symbol rules are ambiguous")
        for rule in self.rules:
            if (
                rule.observed_at_utc != self.observed_at_utc
                or rule.source_raw_sha256 != self.source_raw_sha256
                or rule.source_receipt_sha256 != self.source_receipt_sha256
                or rule.receipt_declared_source_kind != self.receipt_declared_source_kind
            ):
                raise BinanceSymbolRulesError(
                    "every rule must carry the snapshot's exact local provenance"
                )

    def sealed_content(self) -> dict[str, Any]:
        return {
            "observed_at_utc": self.observed_at_utc,
            "server_time_utc": self.server_time_utc,
            "source_endpoint": self.source_endpoint,
            "source_adapter": self.source_adapter,
            "source_adapter_version": self.source_adapter_version,
            "source_raw_sha256": self.source_raw_sha256,
            "source_receipt_sha256": self.source_receipt_sha256,
            "receipt_declared_source_kind": self.receipt_declared_source_kind,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "digest": self.digest()}


@dataclass(frozen=True)
class SymbolRuleLookup:
    """Availability result only; V2 cannot create an externally attested pass."""

    availability: SymbolRuleAvailability
    venue_symbol: str
    as_of_utc: str
    snapshot_observed_at_utc: str | None = None
    rule: BinanceSpotSymbolRule | None = None
    reason: str = ""
    real_money_authorized: bool = field(default=False, init=False)
    pnl_evaluation_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.availability, SymbolRuleAvailability):
            raise BinanceSymbolRulesError("availability must be a closed SymbolRuleAvailability")
        if self.availability is SymbolRuleAvailability.AVAILABLE_REAL:
            raise BinanceSymbolRulesError(
                "AVAILABLE_REAL requires external attestation, which schema v2 does not support"
            )
        _canonical_symbol(self.venue_symbol)
        if _utc_text(self.as_of_utc, "as_of_utc") != self.as_of_utc:
            raise BinanceSymbolRulesError("as_of_utc must use canonical UTC text")
        if self.snapshot_observed_at_utc is not None and (
            _utc_text(self.snapshot_observed_at_utc, "snapshot_observed_at_utc")
            != self.snapshot_observed_at_utc
        ):
            raise BinanceSymbolRulesError("snapshot_observed_at_utc must use canonical UTC text")
        if self.rule is not None:
            raise BinanceSymbolRulesError(
                "unattested or unavailable lookups must not expose a usable rule"
            )

    @property
    def available(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceSpotSymbolRulesLedger:
    """Immutable observations ordered by when their bytes became locally knowable."""

    snapshots: tuple[BinanceSpotSymbolRulesSnapshot, ...]
    schema_version: int = BINANCE_SYMBOL_RULES_SCHEMA_VERSION
    venue: str = BINANCE_SPOT_VENUE
    market: str = "spot"
    quote_asset: str = BINANCE_SPOT_QUOTE_ASSET
    max_capture_server_skew_seconds: int = BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS
    attestation_status: str = "UNAVAILABLE"

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != BINANCE_SYMBOL_RULES_SCHEMA_VERSION
        ):
            raise BinanceSymbolRulesError(
                f"schema_version must be {BINANCE_SYMBOL_RULES_SCHEMA_VERSION}"
            )
        if self.venue != BINANCE_SPOT_VENUE or self.market != "spot":
            raise BinanceSymbolRulesError("ledger venue/market must be binance/spot")
        if self.quote_asset != BINANCE_SPOT_QUOTE_ASSET:
            raise BinanceSymbolRulesError("ledger quote_asset must be USDT")
        if self.max_capture_server_skew_seconds != BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS:
            raise BinanceSymbolRulesError("max_capture_server_skew_seconds is sealed")
        if self.attestation_status != "UNAVAILABLE":
            raise BinanceSymbolRulesError("schema v2 cannot claim external attestation")
        if not isinstance(self.snapshots, tuple) or not self.snapshots:
            raise BinanceSymbolRulesError("snapshots must be a non-empty immutable tuple")
        receipt_hashes = [snapshot.source_receipt_sha256 for snapshot in self.snapshots]
        raw_hashes = [snapshot.source_raw_sha256 for snapshot in self.snapshots]
        if len(receipt_hashes) != len(set(receipt_hashes)):
            raise BinanceSymbolRulesError("duplicate source receipts are not observations")
        if len(raw_hashes) != len(set(raw_hashes)):
            raise BinanceSymbolRulesError(
                "replayed source bytes are not a new symbol-rule observation"
            )
        observations = [
            _utc_datetime(snapshot.observed_at_utc, "observed_at_utc")
            for snapshot in self.snapshots
        ]
        server_times = [
            _utc_datetime(snapshot.server_time_utc, "server_time_utc")
            for snapshot in self.snapshots
        ]
        if any(right <= left for left, right in zip(observations, observations[1:], strict=False)):
            raise BinanceSymbolRulesError(
                "snapshot observed_at_utc values must be strictly increasing in receipt order"
            )
        if any(right <= left for left, right in zip(server_times, server_times[1:], strict=False)):
            raise BinanceSymbolRulesError(
                "Binance server_time_utc values must be strictly increasing in receipt order"
            )

    def sealed_content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "market": self.market,
            "quote_asset": self.quote_asset,
            "max_capture_server_skew_seconds": self.max_capture_server_skew_seconds,
            "attestation_status": self.attestation_status,
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
        }

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "digest": self.digest()}

    def prefix_bytes(self, as_of_utc: str) -> bytes:
        """Canonical local evidence known by ``as_of_utc``; future-safe by construction."""
        cutoff = _utc_datetime(as_of_utc, "as_of_utc")
        snapshots = [
            snapshot.to_dict()
            for snapshot in self.snapshots
            if _utc_datetime(snapshot.observed_at_utc, "observed_at_utc") <= cutoff
        ]
        return canonical_dumps(
            {
                "schema_version": self.schema_version,
                "venue": self.venue,
                "market": self.market,
                "quote_asset": self.quote_asset,
                "max_capture_server_skew_seconds": self.max_capture_server_skew_seconds,
                "attestation_status": self.attestation_status,
                "snapshots": snapshots,
            }
        ).encode("utf-8")

    def lookup(
        self,
        venue_symbol: str,
        *,
        as_of_utc: str,
        max_age: timedelta,
    ) -> SymbolRuleLookup:
        """Classify local availability without exposing an unattested usable rule."""
        symbol = _canonical_symbol(venue_symbol)
        cutoff = _utc_datetime(as_of_utc, "as_of_utc")
        canonical_cutoff = _utc_text(as_of_utc, "as_of_utc")
        if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
            raise BinanceSymbolRulesError("max_age must be a positive timedelta")
        latest: BinanceSpotSymbolRulesSnapshot | None = None
        for snapshot in self.snapshots:
            if _utc_datetime(snapshot.observed_at_utc, "observed_at_utc") <= cutoff:
                latest = snapshot
            else:
                break
        if latest is None:
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.NOT_YET_OBSERVED,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                reason="no exchangeInfo source bytes had been captured by as_of_utc",
            )
        observed = _utc_datetime(latest.observed_at_utc, "observed_at_utc")
        if cutoff - observed > max_age:
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.STALE_SNAPSHOT,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                snapshot_observed_at_utc=latest.observed_at_utc,
                reason="latest causally available exchangeInfo snapshot exceeds max_age",
            )
        if latest.receipt_declared_source_kind not in REAL_SOURCE_KINDS:
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.TEST_ONLY_PROVENANCE,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                snapshot_observed_at_utc=latest.observed_at_utc,
                reason="receipt source label is test-only",
            )
        rule = next((item for item in latest.rules if item.venue_symbol == symbol), None)
        if rule is None:
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.SYMBOL_ABSENT_FROM_LATEST_SNAPSHOT,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                snapshot_observed_at_utc=latest.observed_at_utc,
                reason="symbol is absent from the latest full USDT snapshot; no fallback",
            )
        if not rule.spot_trading_allowed:
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.SPOT_TRADING_DISABLED,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                snapshot_observed_at_utc=latest.observed_at_utc,
                reason="latest source row explicitly disables Spot trading",
            )
        if rule.exchange_status != "TRADING":
            return SymbolRuleLookup(
                availability=SymbolRuleAvailability.SYMBOL_NOT_TRADING,
                venue_symbol=symbol,
                as_of_utc=canonical_cutoff,
                snapshot_observed_at_utc=latest.observed_at_utc,
                reason=f"latest exchange status is {rule.exchange_status}, not TRADING",
            )
        return SymbolRuleLookup(
            availability=SymbolRuleAvailability.UNATTESTED_SOURCE,
            venue_symbol=symbol,
            as_of_utc=canonical_cutoff,
            snapshot_observed_at_utc=latest.observed_at_utc,
            reason=(
                "local hashes are internally consistent but no independent external "
                "attestation exists"
            ),
        )


def _parse_exchange_info(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BinanceSymbolRulesError("exchangeInfo raw bytes must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise BinanceSymbolRulesError("exchangeInfo payload must be a JSON object")
    if payload.get("timezone") != "UTC":
        raise BinanceSymbolRulesError("exchangeInfo timezone must explicitly be UTC")
    server_ms = payload.get("serverTime")
    if type(server_ms) is not int or server_ms <= 0:
        raise BinanceSymbolRulesError(
            "exchangeInfo serverTime must be a positive epoch millisecond"
        )
    try:
        server_time = datetime.fromtimestamp(server_ms / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise BinanceSymbolRulesError(
            "exchangeInfo serverTime is outside the supported range"
        ) from exc
    server_text = _utc_text(server_time.isoformat(), "server_time_utc")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise BinanceSymbolRulesError("exchangeInfo symbols must be a JSON array")

    normalized: list[dict[str, Any]] = []
    seen_usdt: set[str] = set()
    for index, item in enumerate(symbols):
        if not isinstance(item, dict):
            raise BinanceSymbolRulesError(f"symbols[{index}] must be a JSON object")
        if item.get("quoteAsset") != BINANCE_SPOT_QUOTE_ASSET:
            continue
        symbol = _canonical_symbol(item.get("symbol"), f"symbols[{index}].symbol")
        if symbol in seen_usdt:
            raise BinanceSymbolRulesError(f"duplicate venue_symbol {symbol} in exchangeInfo")
        seen_usdt.add(symbol)
        spot_allowed = _required_bool(
            item.get("isSpotTradingAllowed"),
            f"{symbol}.isSpotTradingAllowed",
        )
        base = _canonical_symbol(item.get("baseAsset"), f"{symbol}.baseAsset")
        if symbol != f"{base}{BINANCE_SPOT_QUOTE_ASSET}":
            raise BinanceSymbolRulesError(f"{symbol} does not equal baseAsset + USDT")
        status = item.get("status")
        if not isinstance(status, str) or _STATUS_RE.fullmatch(status) is None:
            raise BinanceSymbolRulesError(f"{symbol}.status must be canonical upper-case text")
        filters = item.get("filters")
        if not isinstance(filters, list):
            raise BinanceSymbolRulesError(f"{symbol}.filters must be a JSON array")
        by_type: dict[str, dict[str, Any]] = {}
        for filter_index, rule_filter in enumerate(filters):
            if not isinstance(rule_filter, dict):
                raise BinanceSymbolRulesError(
                    f"{symbol}.filters[{filter_index}] must be a JSON object"
                )
            filter_type = rule_filter.get("filterType")
            if not isinstance(filter_type, str) or not filter_type:
                raise BinanceSymbolRulesError(f"{symbol} filterType is required")
            if filter_type in by_type:
                raise BinanceSymbolRulesError(
                    f"duplicate {filter_type} filters for {symbol} are ambiguous"
                )
            by_type[filter_type] = rule_filter
        try:
            price_filter = by_type["PRICE_FILTER"]
            lot_filter = by_type["LOT_SIZE"]
            market_lot_filter = by_type["MARKET_LOT_SIZE"]
        except KeyError as exc:
            raise BinanceSymbolRulesError(
                f"{symbol} requires PRICE_FILTER, LOT_SIZE, and MARKET_LOT_SIZE"
            ) from exc
        min_notional_filter = by_type.get("MIN_NOTIONAL")
        notional_filter = by_type.get("NOTIONAL")
        if min_notional_filter is None and notional_filter is None:
            raise BinanceSymbolRulesError(f"{symbol} requires MIN_NOTIONAL or NOTIONAL evidence")

        tick_size = _decimal_text(
            price_filter.get("tickSize"),
            f"{symbol}.PRICE_FILTER.tickSize",
            allow_zero=True,
        )
        min_quantity = _decimal_text(lot_filter.get("minQty"), f"{symbol}.LOT_SIZE.minQty")
        max_quantity = _decimal_text(lot_filter.get("maxQty"), f"{symbol}.LOT_SIZE.maxQty")
        quantity_step = _decimal_text(lot_filter.get("stepSize"), f"{symbol}.LOT_SIZE.stepSize")
        if Decimal(max_quantity) < Decimal(min_quantity):
            raise BinanceSymbolRulesError(f"{symbol}.LOT_SIZE.maxQty is smaller than minQty")

        market_min = _decimal_text(
            market_lot_filter.get("minQty"),
            f"{symbol}.MARKET_LOT_SIZE.minQty",
            allow_zero=True,
        )
        market_max = _decimal_text(
            market_lot_filter.get("maxQty"),
            f"{symbol}.MARKET_LOT_SIZE.maxQty",
            allow_zero=True,
        )
        market_step = _decimal_text(
            market_lot_filter.get("stepSize"),
            f"{symbol}.MARKET_LOT_SIZE.stepSize",
            allow_zero=True,
        )
        if (
            Decimal(market_min) > 0
            and Decimal(market_max) > 0
            and (Decimal(market_max) < Decimal(market_min))
        ):
            raise BinanceSymbolRulesError(
                f"{symbol}.MARKET_LOT_SIZE.maxQty is smaller than enabled minQty"
            )

        min_notional_values: dict[str, Any] = {
            "min_notional_quote": None,
            "min_notional_apply_to_market": None,
            "min_notional_avg_price_mins": None,
        }
        if min_notional_filter is not None:
            min_notional_values = {
                "min_notional_quote": _decimal_text(
                    min_notional_filter.get("minNotional"),
                    f"{symbol}.MIN_NOTIONAL.minNotional",
                ),
                "min_notional_apply_to_market": _required_bool(
                    min_notional_filter.get("applyToMarket"),
                    f"{symbol}.MIN_NOTIONAL.applyToMarket",
                ),
                "min_notional_avg_price_mins": _non_negative_int(
                    min_notional_filter.get("avgPriceMins"),
                    f"{symbol}.MIN_NOTIONAL.avgPriceMins",
                ),
            }
        notional_values: dict[str, Any] = {
            "notional_min_quote": None,
            "notional_apply_min_to_market": None,
            "notional_max_quote": None,
            "notional_apply_max_to_market": None,
            "notional_avg_price_mins": None,
        }
        if notional_filter is not None:
            notional_min = _decimal_text(
                notional_filter.get("minNotional"),
                f"{symbol}.NOTIONAL.minNotional",
            )
            notional_max = _decimal_text(
                notional_filter.get("maxNotional"),
                f"{symbol}.NOTIONAL.maxNotional",
            )
            if Decimal(notional_max) < Decimal(notional_min):
                raise BinanceSymbolRulesError(
                    f"{symbol}.NOTIONAL.maxNotional is smaller than minNotional"
                )
            notional_values = {
                "notional_min_quote": notional_min,
                "notional_apply_min_to_market": _required_bool(
                    notional_filter.get("applyMinToMarket"),
                    f"{symbol}.NOTIONAL.applyMinToMarket",
                ),
                "notional_max_quote": notional_max,
                "notional_apply_max_to_market": _required_bool(
                    notional_filter.get("applyMaxToMarket"),
                    f"{symbol}.NOTIONAL.applyMaxToMarket",
                ),
                "notional_avg_price_mins": _non_negative_int(
                    notional_filter.get("avgPriceMins"),
                    f"{symbol}.NOTIONAL.avgPriceMins",
                ),
            }
        normalized.append(
            {
                "venue_symbol": symbol,
                "base_asset": base,
                "quote_asset": BINANCE_SPOT_QUOTE_ASSET,
                "exchange_status": status,
                "spot_trading_allowed": spot_allowed,
                "tick_size": tick_size,
                "tick_size_enabled": Decimal(tick_size) > 0,
                "quantity_step": quantity_step,
                "min_quantity": min_quantity,
                "max_quantity": max_quantity,
                "market_quantity_step": market_step,
                "market_quantity_step_enabled": Decimal(market_step) > 0,
                "market_min_quantity": market_min,
                "market_min_quantity_enabled": Decimal(market_min) > 0,
                "market_max_quantity": market_max,
                "market_max_quantity_enabled": Decimal(market_max) > 0,
                **min_notional_values,
                **notional_values,
            }
        )
    if not normalized:
        raise BinanceSymbolRulesError("exchangeInfo contains no USDT symbol rows")
    normalized.sort(key=lambda row: str(row["venue_symbol"]))
    return server_text, normalized


def normalize_binance_spot_symbol_rules(raw: bytes) -> list[dict[str, Any]]:
    """Pure V2 normalization used to bind a receipt to exact source bytes."""
    _, rows = _parse_exchange_info(raw)
    return rows


def _snapshot_from_receipt(
    receipt: dict[str, Any],
    *,
    receipts_dir: Path,
) -> BinanceSpotSymbolRulesSnapshot:
    if receipt.get("provider_or_venue") != BINANCE_SPOT_VENUE:
        raise BinanceSymbolRulesError("receipt provider_or_venue must be binance")
    if receipt.get("endpoint") != BINANCE_EXCHANGE_INFO_ENDPOINT:
        raise BinanceSymbolRulesError("receipt endpoint is not the sealed exchangeInfo endpoint")
    if receipt.get("request_parameters") != {}:
        raise BinanceSymbolRulesError(
            "receipt request_parameters must be empty for a full-universe snapshot"
        )
    http_status = receipt.get("http_status")
    if type(http_status) is not int or http_status != 200:
        raise BinanceSymbolRulesError("receipt http_status must be integer 200")
    if receipt.get("adapter_name") != BINANCE_SYMBOL_RULES_ADAPTER:
        raise BinanceSymbolRulesError("receipt adapter_name is not the sealed rules adapter")
    if receipt.get("adapter_version") != BINANCE_SYMBOL_RULES_ADAPTER_VERSION:
        raise BinanceSymbolRulesError("receipt adapter_version is unsupported")
    receipt_schema_version = receipt.get("schema_version")
    if type(receipt_schema_version) is not int or receipt_schema_version != 1:
        raise BinanceSymbolRulesError("receipt schema_version must be integer 1")
    observed_at = _utc_text(receipt.get("captured_at_utc"), "receipt captured_at_utc")
    declared_source_kind = receipt.get("source_kind")
    if declared_source_kind not in REAL_SOURCE_KINDS + TEST_ONLY_SOURCE_KINDS:
        raise BinanceSymbolRulesError("receipt source_kind label is unsupported")
    raw_sha = _sha256(receipt.get("raw_sha256"), "receipt raw_sha256")
    receipt_sha = _sha256(receipt.get("receipt_sha256"), "receipt receipt_sha256")
    expected_normalized = _sha256(
        receipt.get("normalized_rows_sha256"), "receipt normalized_rows_sha256"
    )
    raw_path_text = receipt.get("raw_path")
    if not isinstance(raw_path_text, str) or not raw_path_text:
        raise BinanceSymbolRulesError("receipt raw_path is required")
    raw_path = Path(raw_path_text)
    if raw_path.is_absolute():
        raise BinanceSymbolRulesError("receipt raw_path must be relative")
    root = receipts_dir.resolve()
    resolved = (root / raw_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BinanceSymbolRulesError("receipt raw_path escapes its evidence directory") from exc
    if not resolved.is_file():
        raise BinanceSymbolRulesError("receipt raw source bytes are missing")
    raw = resolved.read_bytes()
    if not hmac.compare_digest(sha256_of_bytes(raw), raw_sha):
        raise BinanceSymbolRulesError("raw source bytes do not match receipt raw_sha256")
    server_time, rows = _parse_exchange_info(raw)
    if not hmac.compare_digest(normalized_rows_sha256(rows), expected_normalized):
        raise BinanceSymbolRulesError(
            "normalized symbol rules do not match receipt normalized_rows_sha256"
        )
    recorded_server_time = receipt.get("server_timestamp_utc", "")
    if recorded_server_time:
        canonical_recorded = _utc_text(recorded_server_time, "receipt server_timestamp_utc")
        if canonical_recorded != server_time:
            raise BinanceSymbolRulesError(
                "receipt server_timestamp_utc disagrees with exchangeInfo serverTime"
            )
    rules = tuple(
        BinanceSpotSymbolRule(
            **row,
            observed_at_utc=observed_at,
            source_raw_sha256=raw_sha,
            source_receipt_sha256=receipt_sha,
            receipt_declared_source_kind=declared_source_kind,
        )
        for row in rows
    )
    return BinanceSpotSymbolRulesSnapshot(
        observed_at_utc=observed_at,
        server_time_utc=server_time,
        source_endpoint=BINANCE_EXCHANGE_INFO_ENDPOINT,
        source_adapter=BINANCE_SYMBOL_RULES_ADAPTER,
        source_adapter_version=BINANCE_SYMBOL_RULES_ADAPTER_VERSION,
        source_raw_sha256=raw_sha,
        source_receipt_sha256=receipt_sha,
        receipt_declared_source_kind=declared_source_kind,
        rules=rules,
    )


def load_binance_spot_symbol_rules_ledger(
    receipts_path: str | Path,
) -> BinanceSpotSymbolRulesLedger:
    """Rebuild V2 after verifying local receipt-chain and raw-byte integrity."""
    source = Path(receipts_path)
    records = load_receipts(source)
    if not records:
        raise BinanceSymbolRulesError("symbol-rule receipt chain is missing or empty")
    chain_problems = verify_receipt_chain(records)
    if chain_problems:
        raise BinanceSymbolRulesError(
            "symbol-rule receipt chain is invalid: " + "; ".join(chain_problems)
        )
    matching = [
        receipt
        for receipt in records
        if receipt.get("adapter_name") == BINANCE_SYMBOL_RULES_ADAPTER
    ]
    if not matching:
        raise BinanceSymbolRulesError("receipt chain has no Binance symbol-rule snapshots")
    snapshots = tuple(
        _snapshot_from_receipt(receipt, receipts_dir=source.parent) for receipt in matching
    )
    return BinanceSpotSymbolRulesLedger(snapshots=snapshots)


__all__ = [
    "BINANCE_EXCHANGE_INFO_ENDPOINT",
    "BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS",
    "BINANCE_SYMBOL_RULES_ADAPTER",
    "BINANCE_SYMBOL_RULES_ADAPTER_VERSION",
    "BINANCE_SYMBOL_RULES_SCHEMA_VERSION",
    "BinanceSpotSymbolRule",
    "BinanceSpotSymbolRulesLedger",
    "BinanceSpotSymbolRulesSnapshot",
    "BinanceSymbolRulesError",
    "SymbolRuleAvailability",
    "SymbolRuleLookup",
    "load_binance_spot_symbol_rules_ledger",
    "normalize_binance_spot_symbol_rules",
]
