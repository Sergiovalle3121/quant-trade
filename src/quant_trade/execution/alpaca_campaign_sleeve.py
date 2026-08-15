"""Fail-closed, paper-only capital sleeve for small Alpaca campaigns.

This module deliberately does not import an HTTP client or the Alpaca broker
adapter.  It freezes a USD 200 *virtual* sleeve, performs a conservative
portfolio preflight, and consumes a plan exactly once in a durable local
ledger.  A caller may hand a validated order to a paper adapter afterwards,
but nothing here can reach an endpoint or enable real-money trading.

The ledger records the plan as consumed *before* any caller submits it.  That
means an ambiguous restart never authorizes a second submission.  Partial,
rejected, over-filled, or otherwise non-exact outcomes are recorded as one
``FAILED_CLOSED`` campaign result and require reconciliation; fills are never
pretended away to manufacture atomic execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USD_200: Final = Decimal("200")
_ZERO: Final = Decimal("0")
_CAMPAIGN_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_PLAN_TOKEN: Final = object()
_PREFLIGHT_TOKEN: Final = object()
_RECEIPT_TOKEN: Final = object()


class AlpacaCampaignSleeveError(RuntimeError):
    """The USD 200 paper sleeve could not prove an operation safe."""


def _canonical_bytes(value: Mapping[str, Any] | list[Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _decimal(value: Decimal | int | float | str, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AlpacaCampaignSleeveError(f"{name} must be a decimal number") from exc
    if not result.is_finite():
        raise AlpacaCampaignSleeveError(f"{name} must be finite")
    return result


def _decimal_text(value: Decimal | int | float | str, name: str) -> str:
    number = _decimal(value, name)
    if number == _ZERO:
        return "0"
    return format(number.normalize(), "f")


def _decimal_places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -int(exponent))


def _validate_alpaca_order_numbers(quantity: Decimal, limit_price: Decimal, *, side: str) -> None:
    if _decimal_places(quantity) > 9:
        raise AlpacaCampaignSleeveError("Alpaca quantity precision exceeds 9 decimal places")
    maximum_price_decimals = 2 if limit_price >= Decimal("1") else 4
    if _decimal_places(limit_price) > maximum_price_decimals:
        raise AlpacaCampaignSleeveError(
            "Alpaca limit_price precision exceeds the permitted price increment"
        )
    if side == "buy" and quantity * limit_price < Decimal("1"):
        raise AlpacaCampaignSleeveError("paper buy notional is below the USD 1 minimum")


def _utc(value: str, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AlpacaCampaignSleeveError(f"{name} must be a non-empty UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlpacaCampaignSleeveError(f"{name} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise AlpacaCampaignSleeveError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _utc_text(value: str, name: str) -> str:
    return _utc(value, name).isoformat().replace("+00:00", "Z")


def _new_york_date(value: datetime) -> str:
    try:
        timezone = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError as exc:
        raise AlpacaCampaignSleeveError(
            "America/New_York timezone data is required for the Alpaca trading date"
        ) from exc
    return value.astimezone(timezone).date().isoformat()


def _campaign_id(value: str) -> str:
    if not isinstance(value, str) or not _CAMPAIGN_RE.fullmatch(value):
        raise AlpacaCampaignSleeveError(
            "campaign_id must be 1-80 safe ASCII characters and may not be a path"
        )
    return value


def _symbol(value: str) -> str:
    if not isinstance(value, str):
        raise AlpacaCampaignSleeveError("symbol must be text")
    normalized = value.strip().upper()
    if value != normalized or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", value):
        raise AlpacaCampaignSleeveError("symbol must be an uppercase Alpaca symbol")
    return value


def _require_exact_keys(payload: Mapping[str, Any], keys: set[str], name: str) -> None:
    if set(payload) != keys:
        missing = sorted(keys - set(payload))
        extra = sorted(set(payload) - keys)
        raise AlpacaCampaignSleeveError(f"{name} fields mismatch: missing={missing}, extra={extra}")


def _strict_bool(value: object, expected: bool, name: str) -> None:
    if value is not expected:
        raise AlpacaCampaignSleeveError(f"{name} must be {expected}")


@dataclass(frozen=True)
class SleevePolicy:
    """Frozen risk budget for one isolated virtual campaign sleeve."""

    campaign_id: str
    initial_cash: Decimal = USD_200
    fee_reserve: Decimal = Decimal("5")
    max_gross_notional: Decimal = Decimal("195")
    max_symbol_notional: Decimal = Decimal("195")
    max_orders_per_day: int = 2
    max_quote_age_seconds: int = 60
    max_snapshot_age_seconds: int = 60
    max_plan_ttl_seconds: int = 300
    currency: str = "USD"
    paper_only: bool = True
    real_money_enabled: bool = False
    allow_leverage: bool = False
    allow_short: bool = False

    def validate(self) -> None:
        _campaign_id(self.campaign_id)
        initial = _decimal(self.initial_cash, "initial_cash")
        reserve = _decimal(self.fee_reserve, "fee_reserve")
        gross = _decimal(self.max_gross_notional, "max_gross_notional")
        per_symbol = _decimal(self.max_symbol_notional, "max_symbol_notional")
        if initial != USD_200:
            raise AlpacaCampaignSleeveError("initial_cash is sealed at exactly USD 200")
        if reserve < Decimal("5") or reserve >= initial:
            raise AlpacaCampaignSleeveError("fee_reserve must be at least USD 5 and below USD 200")
        if gross <= _ZERO or gross > Decimal("195") or gross > initial - reserve:
            raise AlpacaCampaignSleeveError(
                "max_gross_notional may not spend the sealed fee reserve"
            )
        if per_symbol <= _ZERO or per_symbol > gross:
            raise AlpacaCampaignSleeveError(
                "max_symbol_notional must be positive and no greater than gross exposure"
            )
        if (
            isinstance(self.max_orders_per_day, bool)
            or not isinstance(self.max_orders_per_day, int)
            or not 1 <= self.max_orders_per_day <= 2
        ):
            raise AlpacaCampaignSleeveError("max_orders_per_day must be 1 or 2")
        for field_name, value, maximum in (
            ("max_quote_age_seconds", self.max_quote_age_seconds, 60),
            ("max_snapshot_age_seconds", self.max_snapshot_age_seconds, 60),
            ("max_plan_ttl_seconds", self.max_plan_ttl_seconds, 300),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise AlpacaCampaignSleeveError(
                    f"{field_name} must be an integer between 1 and {maximum}"
                )
        if self.currency != "USD":
            raise AlpacaCampaignSleeveError("the sleeve currency is sealed to USD")
        _strict_bool(self.paper_only, True, "paper_only")
        _strict_bool(self.real_money_enabled, False, "real_money_enabled")
        _strict_bool(self.allow_leverage, False, "allow_leverage")
        _strict_bool(self.allow_short, False, "allow_short")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "allow_leverage": self.allow_leverage,
            "allow_short": self.allow_short,
            "campaign_id": self.campaign_id,
            "currency": self.currency,
            "fee_reserve": _decimal_text(self.fee_reserve, "fee_reserve"),
            "initial_cash": _decimal_text(self.initial_cash, "initial_cash"),
            "max_gross_notional": _decimal_text(self.max_gross_notional, "max_gross_notional"),
            "max_orders_per_day": self.max_orders_per_day,
            "max_plan_ttl_seconds": self.max_plan_ttl_seconds,
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_snapshot_age_seconds": self.max_snapshot_age_seconds,
            "max_symbol_notional": _decimal_text(self.max_symbol_notional, "max_symbol_notional"),
            "paper_only": self.paper_only,
            "real_money_enabled": self.real_money_enabled,
            "schema_version": 1,
        }

    def digest(self) -> str:
        return _sha256(self.sealed_content())


@dataclass(frozen=True)
class SleevePosition:
    symbol: str
    quantity: Decimal

    def validate(self) -> None:
        _symbol(self.symbol)
        if _decimal(self.quantity, "position.quantity") <= _ZERO:
            raise AlpacaCampaignSleeveError("positions must be strictly long")

    def sealed_content(self) -> dict[str, str]:
        self.validate()
        return {
            "quantity": _decimal_text(self.quantity, "position.quantity"),
            "symbol": self.symbol,
        }


@dataclass(frozen=True)
class SleeveOpenOrder:
    """Unfilled remainder of an already accepted paper limit order."""

    client_order_id: str
    symbol: str
    side: str
    remaining_quantity: Decimal
    limit_price: Decimal
    status: str = "accepted"
    paper_only: bool = True
    real_money_enabled: bool = False

    def validate(self) -> None:
        if not self.client_order_id or len(self.client_order_id) > 128:
            raise AlpacaCampaignSleeveError("open order client_order_id is invalid")
        _symbol(self.symbol)
        if self.side not in {"buy", "sell"}:
            raise AlpacaCampaignSleeveError("open order side must be buy or sell")
        quantity = _decimal(self.remaining_quantity, "remaining_quantity")
        if quantity <= _ZERO:
            raise AlpacaCampaignSleeveError("open order remainder must be positive")
        price = _decimal(self.limit_price, "limit_price")
        if price <= _ZERO:
            raise AlpacaCampaignSleeveError("open order limit_price must be positive")
        _validate_alpaca_order_numbers(quantity, price, side=self.side)
        if self.status not in {"new", "accepted", "pending_new", "partially_filled"}:
            raise AlpacaCampaignSleeveError("open order status is not open")
        _strict_bool(self.paper_only, True, "open_order.paper_only")
        _strict_bool(self.real_money_enabled, False, "open_order.real_money_enabled")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "client_order_id": self.client_order_id,
            "limit_price": _decimal_text(self.limit_price, "limit_price"),
            "paper_only": self.paper_only,
            "real_money_enabled": self.real_money_enabled,
            "remaining_quantity": _decimal_text(self.remaining_quantity, "remaining_quantity"),
            "side": self.side,
            "status": self.status,
            "symbol": self.symbol,
        }


@dataclass(frozen=True)
class SleeveSnapshot:
    """Virtual sleeve state; never the broker account's unrestricted buying power."""

    campaign_id: str
    captured_at_utc: str
    trading_date: str
    cash: Decimal
    positions: tuple[SleevePosition, ...] = ()
    open_orders: tuple[SleeveOpenOrder, ...] = ()
    orders_submitted_today: int = 0
    initial_cash: Decimal = USD_200
    paper_only: bool = True
    real_money_enabled: bool = False

    def validate(self) -> None:
        _campaign_id(self.campaign_id)
        _utc(self.captured_at_utc, "captured_at_utc")
        try:
            datetime.strptime(self.trading_date, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise AlpacaCampaignSleeveError("trading_date must be YYYY-MM-DD") from exc
        if self.trading_date != _new_york_date(_utc(self.captured_at_utc, "captured_at_utc")):
            raise AlpacaCampaignSleeveError(
                "trading_date must match captured_at_utc in America/New_York"
            )
        if _decimal(self.cash, "cash") < _ZERO:
            raise AlpacaCampaignSleeveError("sleeve cash may not be negative")
        if _decimal(self.initial_cash, "initial_cash") != USD_200:
            raise AlpacaCampaignSleeveError("snapshot initial_cash must remain USD 200")
        if (
            isinstance(self.orders_submitted_today, bool)
            or not isinstance(self.orders_submitted_today, int)
            or self.orders_submitted_today < 0
        ):
            raise AlpacaCampaignSleeveError("orders_submitted_today must be a non-negative integer")
        if self.orders_submitted_today < len(self.open_orders):
            raise AlpacaCampaignSleeveError(
                "orders_submitted_today may not be less than current open orders"
            )
        symbols: set[str] = set()
        for position in self.positions:
            position.validate()
            if position.symbol in symbols:
                raise AlpacaCampaignSleeveError("snapshot positions contain a duplicate symbol")
            symbols.add(position.symbol)
        order_ids: set[str] = set()
        for order in self.open_orders:
            order.validate()
            if order.client_order_id in order_ids:
                raise AlpacaCampaignSleeveError("snapshot contains duplicate open order IDs")
            order_ids.add(order.client_order_id)
        _strict_bool(self.paper_only, True, "snapshot.paper_only")
        _strict_bool(self.real_money_enabled, False, "snapshot.real_money_enabled")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "campaign_id": self.campaign_id,
            "captured_at_utc": _utc_text(self.captured_at_utc, "captured_at_utc"),
            "cash": _decimal_text(self.cash, "cash"),
            "initial_cash": _decimal_text(self.initial_cash, "initial_cash"),
            "open_orders": [
                order.sealed_content()
                for order in sorted(self.open_orders, key=lambda item: item.client_order_id)
            ],
            "orders_submitted_today": self.orders_submitted_today,
            "paper_only": self.paper_only,
            "positions": [
                position.sealed_content()
                for position in sorted(self.positions, key=lambda item: item.symbol)
            ],
            "real_money_enabled": self.real_money_enabled,
            "schema_version": 1,
            "trading_date": self.trading_date,
        }

    def digest(self) -> str:
        return _sha256(self.sealed_content())


@dataclass(frozen=True)
class AlpacaAssetEvidence:
    """Point-in-time asset eligibility and quote evidence used by preflight."""

    symbol: str
    quote_price: Decimal
    quote_at_utc: str
    tradable: bool
    fractionable: bool
    source: str = "alpaca_market_data"

    def validate(self) -> None:
        _symbol(self.symbol)
        if _decimal(self.quote_price, "quote_price") <= _ZERO:
            raise AlpacaCampaignSleeveError("quote_price must be positive")
        _utc(self.quote_at_utc, "quote_at_utc")
        if not isinstance(self.tradable, bool) or not isinstance(self.fractionable, bool):
            raise AlpacaCampaignSleeveError("asset flags must be booleans")
        if self.source != "alpaca_market_data":
            raise AlpacaCampaignSleeveError("asset evidence source must be alpaca_market_data")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "fractionable": self.fractionable,
            "quote_at_utc": _utc_text(self.quote_at_utc, "quote_at_utc"),
            "quote_price": _decimal_text(self.quote_price, "quote_price"),
            "source": self.source,
            "symbol": self.symbol,
            "tradable": self.tradable,
        }


def asset_evidence_digest(evidence: Sequence[AlpacaAssetEvidence]) -> str:
    rows = sorted((row.sealed_content() for row in evidence), key=lambda row: row["symbol"])
    if len({str(row["symbol"]) for row in rows}) != len(rows):
        raise AlpacaCampaignSleeveError("asset evidence contains duplicate symbols")
    return _sha256(rows)


def _state_claim_digest(snapshot: SleeveSnapshot) -> str:
    """Identify the pre-order campaign state without trusting capture-time variation."""

    snapshot.validate()
    return _sha256(
        {
            "campaign_id": snapshot.campaign_id,
            "orders_submitted_today": snapshot.orders_submitted_today,
            "schema_version": 1,
            "trading_date": snapshot.trading_date,
        }
    )


@dataclass(frozen=True)
class PaperPlannedOrder:
    client_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    order_type: str = "limit"
    time_in_force: str = "day"
    paper_only: bool = True
    real_money_enabled: bool = False

    def validate(self) -> None:
        if not self.client_order_id or len(self.client_order_id) > 128:
            raise AlpacaCampaignSleeveError("client_order_id is invalid")
        _symbol(self.symbol)
        if self.side not in {"buy", "sell"}:
            raise AlpacaCampaignSleeveError("planned order side must be buy or sell")
        quantity = _decimal(self.quantity, "quantity")
        if quantity <= _ZERO:
            raise AlpacaCampaignSleeveError("planned order quantity must be positive")
        price = _decimal(self.limit_price, "limit_price")
        if price <= _ZERO:
            raise AlpacaCampaignSleeveError("planned order limit_price must be positive")
        _validate_alpaca_order_numbers(quantity, price, side=self.side)
        if self.order_type != "limit":
            raise AlpacaCampaignSleeveError("the sleeve authorizes bounded limit orders only")
        if self.time_in_force != "day":
            raise AlpacaCampaignSleeveError("the sleeve authorizes day orders only")
        _strict_bool(self.paper_only, True, "planned_order.paper_only")
        _strict_bool(self.real_money_enabled, False, "planned_order.real_money_enabled")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "client_order_id": self.client_order_id,
            "limit_price": _decimal_text(self.limit_price, "limit_price"),
            "order_type": self.order_type,
            "paper_only": self.paper_only,
            "quantity": _decimal_text(self.quantity, "quantity"),
            "real_money_enabled": self.real_money_enabled,
            "side": self.side,
            "symbol": self.symbol,
            "time_in_force": self.time_in_force,
        }


@dataclass(frozen=True)
class SealedPaperPlan:
    campaign_id: str
    initial_cash: Decimal
    policy_sha256: str
    snapshot_sha256: str
    state_claim_sha256: str
    asset_evidence_sha256: str
    trading_date: str
    orders_submitted_before: int
    planned_order_count: int
    orders: tuple[PaperPlannedOrder, ...]
    created_at_utc: str
    expires_at_utc: str
    paper_only: bool
    real_money_enabled: bool
    plan_sha256: str
    _construction_token: InitVar[object]

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _PLAN_TOKEN:
            raise AlpacaCampaignSleeveError(
                "SealedPaperPlan cannot be constructed directly; use seal_paper_plan"
            )

    def sealed_content(self) -> dict[str, Any]:
        return {
            "asset_evidence_sha256": self.asset_evidence_sha256,
            "campaign_id": self.campaign_id,
            "created_at_utc": self.created_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "initial_cash": _decimal_text(self.initial_cash, "initial_cash"),
            "orders": [order.sealed_content() for order in self.orders],
            "orders_submitted_before": self.orders_submitted_before,
            "paper_only": self.paper_only,
            "planned_order_count": self.planned_order_count,
            "policy_sha256": self.policy_sha256,
            "real_money_enabled": self.real_money_enabled,
            "schema_version": 1,
            "snapshot_sha256": self.snapshot_sha256,
            "state_claim_sha256": self.state_claim_sha256,
            "trading_date": self.trading_date,
        }

    def verify(self) -> None:
        _campaign_id(self.campaign_id)
        if _decimal(self.initial_cash, "initial_cash") != USD_200:
            raise AlpacaCampaignSleeveError("plan initial_cash is not USD 200")
        for name, digest in (
            ("policy_sha256", self.policy_sha256),
            ("snapshot_sha256", self.snapshot_sha256),
            ("state_claim_sha256", self.state_claim_sha256),
            ("asset_evidence_sha256", self.asset_evidence_sha256),
            ("plan_sha256", self.plan_sha256),
        ):
            if not _SHA256_RE.fullmatch(digest):
                raise AlpacaCampaignSleeveError(f"{name} is not a lowercase SHA-256")
        created = _utc(self.created_at_utc, "created_at_utc")
        expires = _utc(self.expires_at_utc, "expires_at_utc")
        if expires <= created:
            raise AlpacaCampaignSleeveError("plan expiry must be after creation")
        if not self.orders:
            raise AlpacaCampaignSleeveError("a sealed plan must contain at least one order")
        try:
            datetime.strptime(self.trading_date, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise AlpacaCampaignSleeveError("plan trading_date must be YYYY-MM-DD") from exc
        if (
            isinstance(self.orders_submitted_before, bool)
            or not isinstance(self.orders_submitted_before, int)
            or self.orders_submitted_before < 0
        ):
            raise AlpacaCampaignSleeveError("plan orders_submitted_before is invalid")
        if (
            isinstance(self.planned_order_count, bool)
            or not isinstance(self.planned_order_count, int)
            or self.planned_order_count != len(self.orders)
        ):
            raise AlpacaCampaignSleeveError("plan order count does not match its sealed orders")
        order_ids: set[str] = set()
        for order in self.orders:
            order.validate()
            if order.client_order_id in order_ids:
                raise AlpacaCampaignSleeveError("plan contains duplicate client_order_id values")
            order_ids.add(order.client_order_id)
        _strict_bool(self.paper_only, True, "plan.paper_only")
        _strict_bool(self.real_money_enabled, False, "plan.real_money_enabled")
        expected = _sha256(self.sealed_content())
        if not hmac.compare_digest(expected, self.plan_sha256):
            raise AlpacaCampaignSleeveError("sealed plan digest mismatch")

    def to_dict(self) -> dict[str, Any]:
        self.verify()
        return {**self.sealed_content(), "plan_sha256": self.plan_sha256}


def _plan_from_payload(payload: Mapping[str, Any]) -> SealedPaperPlan:
    keys = {
        "asset_evidence_sha256",
        "campaign_id",
        "created_at_utc",
        "expires_at_utc",
        "initial_cash",
        "orders",
        "orders_submitted_before",
        "paper_only",
        "plan_sha256",
        "planned_order_count",
        "policy_sha256",
        "real_money_enabled",
        "schema_version",
        "snapshot_sha256",
        "state_claim_sha256",
        "trading_date",
    }
    _require_exact_keys(payload, keys, "sealed plan")
    if payload["schema_version"] != 1:
        raise AlpacaCampaignSleeveError("unsupported sealed plan schema")
    raw_orders = payload["orders"]
    if not isinstance(raw_orders, list):
        raise AlpacaCampaignSleeveError("orders must be a list")
    orders: list[PaperPlannedOrder] = []
    order_keys = {
        "client_order_id",
        "limit_price",
        "order_type",
        "paper_only",
        "quantity",
        "real_money_enabled",
        "side",
        "symbol",
        "time_in_force",
    }
    for raw in raw_orders:
        if not isinstance(raw, Mapping):
            raise AlpacaCampaignSleeveError("each order must be an object")
        _require_exact_keys(raw, order_keys, "planned order")
        orders.append(
            PaperPlannedOrder(
                client_order_id=str(raw["client_order_id"]),
                symbol=str(raw["symbol"]),
                side=str(raw["side"]),
                quantity=_decimal(raw["quantity"], "quantity"),
                limit_price=_decimal(raw["limit_price"], "limit_price"),
                order_type=str(raw["order_type"]),
                time_in_force=str(raw["time_in_force"]),
                paper_only=raw["paper_only"],
                real_money_enabled=raw["real_money_enabled"],
            )
        )
    plan = SealedPaperPlan(
        campaign_id=str(payload["campaign_id"]),
        initial_cash=_decimal(payload["initial_cash"], "initial_cash"),
        policy_sha256=str(payload["policy_sha256"]),
        snapshot_sha256=str(payload["snapshot_sha256"]),
        state_claim_sha256=str(payload["state_claim_sha256"]),
        asset_evidence_sha256=str(payload["asset_evidence_sha256"]),
        trading_date=str(payload["trading_date"]),
        orders_submitted_before=payload["orders_submitted_before"],
        planned_order_count=payload["planned_order_count"],
        orders=tuple(orders),
        created_at_utc=str(payload["created_at_utc"]),
        expires_at_utc=str(payload["expires_at_utc"]),
        paper_only=payload["paper_only"],
        real_money_enabled=payload["real_money_enabled"],
        plan_sha256=str(payload["plan_sha256"]),
        _construction_token=_PLAN_TOKEN,
    )
    plan.verify()
    return plan


def load_sealed_paper_plan(payload: Mapping[str, Any] | bytes | str) -> SealedPaperPlan:
    """Load a serialized plan and reject missing, extra, or tampered fields."""

    if isinstance(payload, bytes | str):
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AlpacaCampaignSleeveError("sealed plan is not valid JSON") from exc
    else:
        decoded = payload
    if not isinstance(decoded, Mapping):
        raise AlpacaCampaignSleeveError("sealed plan must be an object")
    return _plan_from_payload(decoded)


@dataclass(frozen=True)
class ProjectedSleevePosition:
    symbol: str
    quantity: Decimal
    mark_price: Decimal
    marked_notional: Decimal

    def sealed_content(self) -> dict[str, str]:
        return {
            "mark_price": _decimal_text(self.mark_price, "mark_price"),
            "marked_notional": _decimal_text(self.marked_notional, "marked_notional"),
            "quantity": _decimal_text(self.quantity, "quantity"),
            "symbol": self.symbol,
        }


@dataclass(frozen=True)
class SleevePreflight:
    plan_sha256: str
    evaluated_at_utc: str
    conservative_cash_after_buys: Decimal
    cash_if_all_orders_fill_before_fees: Decimal
    gross_marked_notional_if_all_fill: Decimal
    worst_case_gross_notional: Decimal
    projected_positions: tuple[ProjectedSleevePosition, ...]
    total_orders_today_after_plan: int
    passed: bool
    paper_only: bool
    real_money_enabled: bool
    preflight_sha256: str
    _construction_token: InitVar[object]

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _PREFLIGHT_TOKEN:
            raise AlpacaCampaignSleeveError("SleevePreflight cannot be constructed directly")

    def sealed_content(self) -> dict[str, Any]:
        return {
            "cash_if_all_orders_fill_before_fees": _decimal_text(
                self.cash_if_all_orders_fill_before_fees,
                "cash_if_all_orders_fill_before_fees",
            ),
            "conservative_cash_after_buys": _decimal_text(
                self.conservative_cash_after_buys, "conservative_cash_after_buys"
            ),
            "evaluated_at_utc": self.evaluated_at_utc,
            "gross_marked_notional_if_all_fill": _decimal_text(
                self.gross_marked_notional_if_all_fill,
                "gross_marked_notional_if_all_fill",
            ),
            "paper_only": self.paper_only,
            "passed": self.passed,
            "plan_sha256": self.plan_sha256,
            "projected_positions": [row.sealed_content() for row in self.projected_positions],
            "real_money_enabled": self.real_money_enabled,
            "schema_version": 1,
            "total_orders_today_after_plan": self.total_orders_today_after_plan,
            "worst_case_gross_notional": _decimal_text(
                self.worst_case_gross_notional, "worst_case_gross_notional"
            ),
        }

    def verify(self) -> None:
        _strict_bool(self.passed, True, "preflight.passed")
        _strict_bool(self.paper_only, True, "preflight.paper_only")
        _strict_bool(self.real_money_enabled, False, "preflight.real_money_enabled")
        if _sha256(self.sealed_content()) != self.preflight_sha256:
            raise AlpacaCampaignSleeveError("preflight digest mismatch")


def _age_seconds(observed: datetime, evaluated: datetime, name: str) -> float:
    age = (evaluated - observed).total_seconds()
    if age < 0:
        raise AlpacaCampaignSleeveError(f"{name} is from the future")
    return age


def _validate_bindings(
    plan: SealedPaperPlan,
    policy: SleevePolicy,
    snapshot: SleeveSnapshot,
    evidence: Sequence[AlpacaAssetEvidence],
) -> None:
    plan.verify()
    policy.validate()
    snapshot.validate()
    if plan.campaign_id != policy.campaign_id or plan.campaign_id != snapshot.campaign_id:
        raise AlpacaCampaignSleeveError("campaign_id differs across plan, policy, and snapshot")
    if plan.policy_sha256 != policy.digest():
        raise AlpacaCampaignSleeveError("plan is not bound to this policy")
    if plan.snapshot_sha256 != snapshot.digest():
        raise AlpacaCampaignSleeveError("plan is not bound to this sleeve snapshot")
    if plan.state_claim_sha256 != _state_claim_digest(snapshot):
        raise AlpacaCampaignSleeveError("plan is not bound to this campaign state sequence")
    if plan.trading_date != snapshot.trading_date:
        raise AlpacaCampaignSleeveError("plan trading_date differs from its bound snapshot")
    if plan.orders_submitted_before != snapshot.orders_submitted_today:
        raise AlpacaCampaignSleeveError("plan order sequence differs from its bound snapshot")
    if plan.asset_evidence_sha256 != asset_evidence_digest(evidence):
        raise AlpacaCampaignSleeveError("plan is not bound to this asset evidence")


def preflight_paper_plan(
    plan: SealedPaperPlan,
    policy: SleevePolicy,
    snapshot: SleeveSnapshot,
    evidence: Sequence[AlpacaAssetEvidence],
    *,
    evaluated_at_utc: str,
) -> SleevePreflight:
    """Project all current and planned risk under conservative fill assumptions."""

    _validate_bindings(plan, policy, snapshot, evidence)
    evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
    created = _utc(plan.created_at_utc, "created_at_utc")
    expires = _utc(plan.expires_at_utc, "expires_at_utc")
    if evaluated < created:
        raise AlpacaCampaignSleeveError("plan cannot be consumed before it was created")
    if evaluated > expires:
        raise AlpacaCampaignSleeveError("sealed plan has expired")
    if (expires - created).total_seconds() > policy.max_plan_ttl_seconds:
        raise AlpacaCampaignSleeveError("plan lifetime exceeds the sealed policy")
    snapshot_at = _utc(snapshot.captured_at_utc, "captured_at_utc")
    if _age_seconds(snapshot_at, evaluated, "snapshot") > policy.max_snapshot_age_seconds:
        raise AlpacaCampaignSleeveError("sleeve snapshot is stale")
    if snapshot.trading_date != _new_york_date(evaluated):
        raise AlpacaCampaignSleeveError("sleeve snapshot belongs to a different trading date")

    evidence_by_symbol: dict[str, AlpacaAssetEvidence] = {}
    for row in evidence:
        row.validate()
        if row.symbol in evidence_by_symbol:
            raise AlpacaCampaignSleeveError("asset evidence contains duplicate symbols")
        evidence_by_symbol[row.symbol] = row
    relevant_symbols = {
        *(position.symbol for position in snapshot.positions),
        *(order.symbol for order in snapshot.open_orders),
        *(order.symbol for order in plan.orders),
    }
    if set(evidence_by_symbol) != relevant_symbols:
        raise AlpacaCampaignSleeveError(
            "asset evidence must contain exactly every position and order symbol"
        )
    for row in evidence_by_symbol.values():
        quote_at = _utc(row.quote_at_utc, "quote_at_utc")
        if _age_seconds(quote_at, evaluated, f"{row.symbol} quote") > policy.max_quote_age_seconds:
            raise AlpacaCampaignSleeveError(f"quote for {row.symbol} is stale")

    if snapshot.orders_submitted_today + len(plan.orders) > policy.max_orders_per_day:
        raise AlpacaCampaignSleeveError("daily paper order count would exceed policy")
    open_ids = {order.client_order_id for order in snapshot.open_orders}
    planned_ids = [order.client_order_id for order in plan.orders]
    if len(set(planned_ids)) != len(planned_ids) or open_ids.intersection(planned_ids):
        raise AlpacaCampaignSleeveError("client_order_id was duplicated or reused")

    positions = {
        position.symbol: _decimal(position.quantity, "position.quantity")
        for position in snapshot.positions
    }
    current_marked = {
        symbol: quantity * _decimal(evidence_by_symbol[symbol].quote_price, f"{symbol}.quote_price")
        for symbol, quantity in positions.items()
    }
    open_and_planned: tuple[SleeveOpenOrder | PaperPlannedOrder, ...] = (
        *snapshot.open_orders,
        *plan.orders,
    )
    cumulative_sells: dict[str, Decimal] = {}
    buy_risk_by_symbol: dict[str, Decimal] = {}
    total_buy_cash_obligation = _ZERO
    total_buy_risk_notional = _ZERO
    total_sell_notional = _ZERO
    for order in open_and_planned:
        order.validate()
        asset = evidence_by_symbol[order.symbol]
        if not asset.tradable:
            raise AlpacaCampaignSleeveError(f"{order.symbol} is not proven tradable")
        quantity = _decimal(
            order.remaining_quantity if isinstance(order, SleeveOpenOrder) else order.quantity,
            "order.quantity",
        )
        if quantity != quantity.to_integral_value() and not asset.fractionable:
            raise AlpacaCampaignSleeveError(f"{order.symbol} is not proven fractionable")
        price = _decimal(order.limit_price, "order.limit_price")
        notional = quantity * price
        if order.side == "sell":
            cumulative_sells[order.symbol] = cumulative_sells.get(order.symbol, _ZERO) + quantity
            if cumulative_sells[order.symbol] > positions.get(order.symbol, _ZERO):
                raise AlpacaCampaignSleeveError(
                    f"sell quantity for {order.symbol} exceeds the sleeve position"
                )
            total_sell_notional += notional
        else:
            quote = _decimal(asset.quote_price, f"{order.symbol}.quote_price")
            risk_notional = quantity * max(price, quote)
            total_buy_cash_obligation += notional
            total_buy_risk_notional += risk_notional
            buy_risk_by_symbol[order.symbol] = (
                buy_risk_by_symbol.get(order.symbol, _ZERO) + risk_notional
            )

    cash = _decimal(snapshot.cash, "cash")
    conservative_cash = cash - total_buy_cash_obligation
    if conservative_cash < _decimal(policy.fee_reserve, "fee_reserve"):
        raise AlpacaCampaignSleeveError("buy obligations would spend the sealed fee reserve")
    worst_gross = sum(current_marked.values(), _ZERO) + total_buy_risk_notional
    if total_buy_risk_notional > _ZERO and worst_gross > _decimal(
        policy.max_gross_notional, "max_gross_notional"
    ):
        raise AlpacaCampaignSleeveError("worst-case gross exposure exceeds the sleeve cap")
    for symbol, buy_notional in buy_risk_by_symbol.items():
        if current_marked.get(symbol, _ZERO) + buy_notional > _decimal(
            policy.max_symbol_notional, "max_symbol_notional"
        ):
            raise AlpacaCampaignSleeveError(f"{symbol} exceeds the per-symbol exposure cap")

    projected_quantities = dict(positions)
    for order in open_and_planned:
        quantity = _decimal(
            order.remaining_quantity if isinstance(order, SleeveOpenOrder) else order.quantity,
            "order.quantity",
        )
        signed = quantity if order.side == "buy" else -quantity
        projected_quantities[order.symbol] = projected_quantities.get(order.symbol, _ZERO) + signed
        if projected_quantities[order.symbol] < _ZERO:
            raise AlpacaCampaignSleeveError("projected portfolio contains a short position")
    projected_rows: list[ProjectedSleevePosition] = []
    for symbol, quantity in sorted(projected_quantities.items()):
        if quantity == _ZERO:
            continue
        mark = _decimal(evidence_by_symbol[symbol].quote_price, "quote_price")
        projected_rows.append(
            ProjectedSleevePosition(
                symbol=symbol,
                quantity=quantity,
                mark_price=mark,
                marked_notional=quantity * mark,
            )
        )
    gross_if_all_fill = sum((row.marked_notional for row in projected_rows), _ZERO)
    content: dict[str, Any] = {
        "cash_if_all_orders_fill_before_fees": _decimal_text(
            cash - total_buy_cash_obligation + total_sell_notional,
            "cash_if_all_orders_fill_before_fees",
        ),
        "conservative_cash_after_buys": _decimal_text(
            conservative_cash, "conservative_cash_after_buys"
        ),
        "evaluated_at_utc": _utc_text(evaluated_at_utc, "evaluated_at_utc"),
        "gross_marked_notional_if_all_fill": _decimal_text(
            gross_if_all_fill, "gross_marked_notional_if_all_fill"
        ),
        "paper_only": True,
        "passed": True,
        "plan_sha256": plan.plan_sha256,
        "projected_positions": [row.sealed_content() for row in projected_rows],
        "real_money_enabled": False,
        "schema_version": 1,
        "total_orders_today_after_plan": snapshot.orders_submitted_today + len(plan.orders),
        "worst_case_gross_notional": _decimal_text(worst_gross, "worst_case_gross_notional"),
    }
    result = SleevePreflight(
        plan_sha256=plan.plan_sha256,
        evaluated_at_utc=str(content["evaluated_at_utc"]),
        conservative_cash_after_buys=conservative_cash,
        cash_if_all_orders_fill_before_fees=(
            cash - total_buy_cash_obligation + total_sell_notional
        ),
        gross_marked_notional_if_all_fill=gross_if_all_fill,
        worst_case_gross_notional=worst_gross,
        projected_positions=tuple(projected_rows),
        total_orders_today_after_plan=snapshot.orders_submitted_today + len(plan.orders),
        passed=True,
        paper_only=True,
        real_money_enabled=False,
        preflight_sha256=_sha256(content),
        _construction_token=_PREFLIGHT_TOKEN,
    )
    result.verify()
    return result


def seal_paper_plan(
    policy: SleevePolicy,
    snapshot: SleeveSnapshot,
    evidence: Sequence[AlpacaAssetEvidence],
    orders: Sequence[PaperPlannedOrder],
    *,
    created_at_utc: str,
    expires_at_utc: str,
) -> SealedPaperPlan:
    """Seal and preflight a plan; unsafe plans are never returned."""

    policy.validate()
    snapshot.validate()
    if policy.campaign_id != snapshot.campaign_id:
        raise AlpacaCampaignSleeveError("policy and snapshot campaign_id differ")
    created_text = _utc_text(created_at_utc, "created_at_utc")
    expires_text = _utc_text(expires_at_utc, "expires_at_utc")
    order_tuple = tuple(orders)
    content: dict[str, Any] = {
        "asset_evidence_sha256": asset_evidence_digest(evidence),
        "campaign_id": policy.campaign_id,
        "created_at_utc": created_text,
        "expires_at_utc": expires_text,
        "initial_cash": "200",
        "orders": [order.sealed_content() for order in order_tuple],
        "orders_submitted_before": snapshot.orders_submitted_today,
        "paper_only": True,
        "planned_order_count": len(order_tuple),
        "policy_sha256": policy.digest(),
        "real_money_enabled": False,
        "schema_version": 1,
        "snapshot_sha256": snapshot.digest(),
        "state_claim_sha256": _state_claim_digest(snapshot),
        "trading_date": snapshot.trading_date,
    }
    plan = SealedPaperPlan(
        campaign_id=policy.campaign_id,
        initial_cash=USD_200,
        policy_sha256=policy.digest(),
        snapshot_sha256=snapshot.digest(),
        state_claim_sha256=_state_claim_digest(snapshot),
        asset_evidence_sha256=asset_evidence_digest(evidence),
        trading_date=snapshot.trading_date,
        orders_submitted_before=snapshot.orders_submitted_today,
        planned_order_count=len(order_tuple),
        orders=order_tuple,
        created_at_utc=created_text,
        expires_at_utc=expires_text,
        paper_only=True,
        real_money_enabled=False,
        plan_sha256=_sha256(content),
        _construction_token=_PLAN_TOKEN,
    )
    plan.verify()
    preflight_paper_plan(
        plan,
        policy,
        snapshot,
        evidence,
        evaluated_at_utc=created_text,
    )
    return plan


@dataclass(frozen=True)
class PaperOrderOutcome:
    client_order_id: str
    status: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None = None
    paper_only: bool = True
    real_money_enabled: bool = False

    def validate(self) -> None:
        if not self.client_order_id or len(self.client_order_id) > 128:
            raise AlpacaCampaignSleeveError("outcome client_order_id is invalid")
        if self.status not in {
            "filled",
            "partially_filled",
            "rejected",
            "canceled",
            "expired",
            "unknown",
        }:
            raise AlpacaCampaignSleeveError("outcome status is unsupported")
        requested = _decimal(self.requested_quantity, "requested_quantity")
        filled = _decimal(self.filled_quantity, "filled_quantity")
        if requested <= _ZERO or filled < _ZERO:
            raise AlpacaCampaignSleeveError("outcome quantities are invalid")
        if self.average_fill_price is None:
            if filled > _ZERO:
                raise AlpacaCampaignSleeveError("a non-zero fill requires average_fill_price")
        elif _decimal(self.average_fill_price, "average_fill_price") <= _ZERO:
            raise AlpacaCampaignSleeveError("average_fill_price must be positive")
        _strict_bool(self.paper_only, True, "outcome.paper_only")
        _strict_bool(self.real_money_enabled, False, "outcome.real_money_enabled")

    def sealed_content(self) -> dict[str, Any]:
        self.validate()
        return {
            "average_fill_price": None
            if self.average_fill_price is None
            else _decimal_text(self.average_fill_price, "average_fill_price"),
            "client_order_id": self.client_order_id,
            "filled_quantity": _decimal_text(self.filled_quantity, "filled_quantity"),
            "paper_only": self.paper_only,
            "real_money_enabled": self.real_money_enabled,
            "requested_quantity": _decimal_text(self.requested_quantity, "requested_quantity"),
            "status": self.status,
        }


@dataclass(frozen=True)
class CampaignOutcomeReceipt:
    campaign_id: str
    plan_sha256: str
    state: str
    outcomes: tuple[PaperOrderOutcome, ...]
    outcomes_sha256: str
    finalized_at_utc: str
    reason: str
    campaign_halted: bool
    requires_manual_reconciliation: bool
    paper_only: bool
    real_money_enabled: bool
    receipt_sha256: str
    _construction_token: InitVar[object]

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _RECEIPT_TOKEN:
            raise AlpacaCampaignSleeveError("CampaignOutcomeReceipt cannot be constructed directly")

    def sealed_content(self) -> dict[str, Any]:
        return {
            "campaign_halted": self.campaign_halted,
            "campaign_id": self.campaign_id,
            "finalized_at_utc": self.finalized_at_utc,
            "outcomes": [outcome.sealed_content() for outcome in self.outcomes],
            "outcomes_sha256": self.outcomes_sha256,
            "paper_only": self.paper_only,
            "plan_sha256": self.plan_sha256,
            "real_money_enabled": self.real_money_enabled,
            "reason": self.reason,
            "requires_manual_reconciliation": self.requires_manual_reconciliation,
            "schema_version": 1,
            "state": self.state,
        }

    def verify(self) -> None:
        if self.state not in {"COMMITTED", "FAILED_CLOSED"}:
            raise AlpacaCampaignSleeveError("receipt state is invalid")
        _strict_bool(self.paper_only, True, "receipt.paper_only")
        _strict_bool(self.real_money_enabled, False, "receipt.real_money_enabled")
        if not isinstance(self.campaign_halted, bool) or not isinstance(
            self.requires_manual_reconciliation, bool
        ):
            raise AlpacaCampaignSleeveError("receipt failure flags must be booleans")
        if self.outcomes_sha256 != _sha256([outcome.sealed_content() for outcome in self.outcomes]):
            raise AlpacaCampaignSleeveError("receipt outcome digest mismatch")
        if self.receipt_sha256 != _sha256(self.sealed_content()):
            raise AlpacaCampaignSleeveError("receipt digest mismatch")
        if self.state == "COMMITTED":
            if self.campaign_halted or self.requires_manual_reconciliation:
                raise AlpacaCampaignSleeveError("committed receipt carries failure flags")
        elif not self.campaign_halted or not self.requires_manual_reconciliation:
            raise AlpacaCampaignSleeveError("failed receipt must halt and require reconciliation")

    def to_dict(self) -> dict[str, Any]:
        self.verify()
        return {**self.sealed_content(), "receipt_sha256": self.receipt_sha256}


@dataclass(frozen=True)
class ConsumptionDecision:
    should_submit: bool
    state: str
    reason: str
    plan_sha256: str
    preflight: SleevePreflight | None
    paper_only: bool = True
    real_money_enabled: bool = False


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> bool:
    data = _canonical_bytes(payload) + b"\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise AlpacaCampaignSleeveError("could not persist the consumption ledger")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def _read_json_object(path: Path, name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlpacaCampaignSleeveError(f"{name} is unreadable or corrupt") from exc
    if not isinstance(value, Mapping):
        raise AlpacaCampaignSleeveError(f"{name} must be a JSON object")
    return value


def _replace_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    if not _write_exclusive(temporary, payload):  # pragma: no cover - UUID collision
        raise AlpacaCampaignSleeveError("could not create a unique ledger update")
    try:
        os.replace(temporary, path)
    except OSError as exc:
        raise AlpacaCampaignSleeveError("could not atomically update campaign state") from exc


class PaperPlanConsumptionLedger:
    """Restart-safe local authorization ledger with immutable plan receipts.

    A plan gets one immutable consumption marker and, later, at most one
    immutable outcome receipt.  A hash-chained campaign head serializes plans
    and persists a failure halt.  Files are addressed only by verified digests;
    ``O_EXCL`` claims and a campaign mutex prevent concurrent authorization.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise AlpacaCampaignSleeveError("ledger root is not a directory")

    @staticmethod
    def _campaign_key(plan: SealedPaperPlan) -> str:
        plan.verify()
        return _sha256({"campaign_id": plan.campaign_id, "schema_version": 1})

    def _campaign_head_path(self, plan: SealedPaperPlan) -> Path:
        return self.root / f"{self._campaign_key(plan)}.campaign-head.json"

    def _campaign_lock_path(self, plan: SealedPaperPlan) -> Path:
        return self.root / f"{self._campaign_key(plan)}.campaign-lock.json"

    def _acquire_campaign_lock(self, plan: SealedPaperPlan, at_utc: str) -> bool:
        record = {
            "acquired_at_utc": _utc_text(at_utc, "campaign_lock_at_utc"),
            "campaign_id": plan.campaign_id,
            "paper_only": True,
            "plan_sha256": plan.plan_sha256,
            "real_money_enabled": False,
            "schema_version": 1,
        }
        return _write_exclusive(
            self._campaign_lock_path(plan),
            {"record": record, "record_sha256": _sha256(record)},
        )

    def _release_campaign_lock(self, plan: SealedPaperPlan) -> None:
        try:
            self._campaign_lock_path(plan).unlink()
        except OSError as exc:
            raise AlpacaCampaignSleeveError(
                "campaign mutex could not be released; campaign remains fail-closed"
            ) from exc

    def _read_campaign_head(self, plan: SealedPaperPlan) -> tuple[Mapping[str, Any], str] | None:
        path = self._campaign_head_path(plan)
        if not path.exists():
            return None
        envelope = _read_json_object(path, "campaign head")
        _require_exact_keys(envelope, {"record", "record_sha256"}, "campaign head envelope")
        record = envelope["record"]
        if not isinstance(record, Mapping):
            raise AlpacaCampaignSleeveError("campaign head is corrupt")
        head_sha = str(envelope["record_sha256"])
        if head_sha != _sha256(record):
            raise AlpacaCampaignSleeveError("campaign head digest mismatch")
        keys = {
            "active_plan_sha256",
            "campaign_id",
            "canonical_cash_ceiling",
            "canonical_positions",
            "generation",
            "halted",
            "last_terminal_state",
            "next_orders_submitted_today",
            "paper_only",
            "previous_head_sha256",
            "real_money_enabled",
            "schema_version",
            "state_phase",
            "trading_date",
        }
        _require_exact_keys(record, keys, "campaign head record")
        if record["schema_version"] != 1 or record["campaign_id"] != plan.campaign_id:
            raise AlpacaCampaignSleeveError("campaign head is not bound to this campaign")
        if (
            isinstance(record["generation"], bool)
            or not isinstance(record["generation"], int)
            or record["generation"] < 1
        ):
            raise AlpacaCampaignSleeveError("campaign head generation is invalid")
        next_count = record["next_orders_submitted_today"]
        if isinstance(next_count, bool) or not isinstance(next_count, int) or next_count < 0:
            raise AlpacaCampaignSleeveError("campaign head order count is invalid")
        active = record["active_plan_sha256"]
        if active is not None and not _SHA256_RE.fullmatch(str(active)):
            raise AlpacaCampaignSleeveError("campaign head active plan digest is invalid")
        previous = record["previous_head_sha256"]
        if previous is not None and not _SHA256_RE.fullmatch(str(previous)):
            raise AlpacaCampaignSleeveError("campaign head previous digest is invalid")
        if record["last_terminal_state"] not in {None, "COMMITTED", "FAILED_CLOSED"}:
            raise AlpacaCampaignSleeveError("campaign head terminal state is invalid")
        cash_ceiling = _decimal(record["canonical_cash_ceiling"], "canonical_cash_ceiling")
        if cash_ceiling < _ZERO:
            raise AlpacaCampaignSleeveError("campaign head cash ceiling is invalid")
        raw_positions = record["canonical_positions"]
        if not isinstance(raw_positions, list):
            raise AlpacaCampaignSleeveError("campaign head positions must be a list")
        seen_symbols: set[str] = set()
        for row in raw_positions:
            if not isinstance(row, Mapping):
                raise AlpacaCampaignSleeveError("campaign head position is not an object")
            _require_exact_keys(row, {"quantity", "symbol"}, "campaign head position")
            symbol = _symbol(str(row["symbol"]))
            if symbol in seen_symbols or _decimal(row["quantity"], "position.quantity") <= _ZERO:
                raise AlpacaCampaignSleeveError("campaign head positions are invalid")
            seen_symbols.add(symbol)
        if record["state_phase"] not in {"PRE_ORDER", "POST_COMMITTED", "HALTED"}:
            raise AlpacaCampaignSleeveError("campaign head state phase is invalid")
        try:
            datetime.strptime(str(record["trading_date"]), "%Y-%m-%d")
        except ValueError as exc:
            raise AlpacaCampaignSleeveError("campaign head trading date is invalid") from exc
        _strict_bool(record["halted"], False, "campaign_head.halted") if not record[
            "halted"
        ] else _strict_bool(record["halted"], True, "campaign_head.halted")
        phase = record["state_phase"]
        if active is not None and phase != "PRE_ORDER":
            raise AlpacaCampaignSleeveError("active campaign head is not PRE_ORDER")
        if active is None and record["halted"] is True and phase != "HALTED":
            raise AlpacaCampaignSleeveError("halted campaign head is inconsistent")
        if active is None and record["halted"] is False and phase != "POST_COMMITTED":
            raise AlpacaCampaignSleeveError("committed campaign head is inconsistent")
        _strict_bool(record["paper_only"], True, "campaign_head.paper_only")
        _strict_bool(record["real_money_enabled"], False, "campaign_head.real_money_enabled")
        return record, head_sha

    @staticmethod
    def _position_rows(positions: Sequence[SleevePosition]) -> list[dict[str, str]]:
        return [
            position.sealed_content()
            for position in sorted(positions, key=lambda item: item.symbol)
        ]

    @staticmethod
    def _position_map(rows: object) -> dict[str, Decimal]:
        if not isinstance(rows, list):
            raise AlpacaCampaignSleeveError("campaign positions are corrupt")
        return {
            str(row["symbol"]): _decimal(row["quantity"], "position.quantity")
            for row in rows
            if isinstance(row, Mapping)
        }

    def _write_campaign_head(self, plan: SealedPaperPlan, record: Mapping[str, Any]) -> None:
        head_path = self._campaign_head_path(plan)
        if head_path.exists():
            prior_result = self._read_campaign_head(plan)
            if prior_result is None:  # pragma: no cover - path was just observed
                raise AlpacaCampaignSleeveError("campaign head disappeared during update")
            _, prior_sha = prior_result
            prior_envelope = _read_json_object(head_path, "campaign head")
            history_path = self.root / (
                f"{self._campaign_key(plan)}.{prior_sha}.campaign-head-history.json"
            )
            if not _write_exclusive(history_path, prior_envelope):
                existing = _read_json_object(history_path, "campaign head history")
                if existing != prior_envelope:
                    raise AlpacaCampaignSleeveError("campaign head history conflicts")
        _replace_atomically(
            head_path,
            {"record": record, "record_sha256": _sha256(record)},
        )

    def _consumption_path(self, plan: SealedPaperPlan) -> Path:
        plan.verify()
        return self.root / f"{plan.plan_sha256}.consumption.json"

    def _outcome_path(self, plan: SealedPaperPlan) -> Path:
        plan.verify()
        return self.root / f"{plan.plan_sha256}.outcome.json"

    def _state_claim_path(self, plan: SealedPaperPlan) -> Path:
        plan.verify()
        return self.root / f"{plan.state_claim_sha256}.state-claim.json"

    def _read_state_claim(self, plan: SealedPaperPlan) -> Mapping[str, Any]:
        envelope = _read_json_object(self._state_claim_path(plan), "campaign state claim")
        _require_exact_keys(envelope, {"record", "record_sha256"}, "state claim envelope")
        record = envelope["record"]
        if not isinstance(record, Mapping):
            raise AlpacaCampaignSleeveError("campaign state claim is corrupt")
        if str(envelope["record_sha256"]) != _sha256(record):
            raise AlpacaCampaignSleeveError("campaign state claim digest mismatch")
        keys = {
            "campaign_id",
            "claimed_at_utc",
            "paper_only",
            "plan_sha256",
            "real_money_enabled",
            "schema_version",
            "snapshot_sha256",
            "state_claim_sha256",
        }
        _require_exact_keys(record, keys, "state claim record")
        if (
            record["schema_version"] != 1
            or record["campaign_id"] != plan.campaign_id
            or record["plan_sha256"] != plan.plan_sha256
            or record["snapshot_sha256"] != plan.snapshot_sha256
            or record["state_claim_sha256"] != plan.state_claim_sha256
        ):
            raise AlpacaCampaignSleeveError("campaign state was claimed by a different plan")
        _utc(str(record["claimed_at_utc"]), "claimed_at_utc")
        _strict_bool(record["paper_only"], True, "state_claim.paper_only")
        _strict_bool(record["real_money_enabled"], False, "state_claim.real_money_enabled")
        return record

    def _read_consumption(self, plan: SealedPaperPlan) -> Mapping[str, Any]:
        envelope = _read_json_object(self._consumption_path(plan), "consumption marker")
        _require_exact_keys(envelope, {"record", "record_sha256"}, "consumption envelope")
        record = envelope["record"]
        if not isinstance(record, Mapping):
            raise AlpacaCampaignSleeveError("consumption record is corrupt")
        if str(envelope["record_sha256"]) != _sha256(record):
            raise AlpacaCampaignSleeveError("consumption marker digest mismatch")
        keys = {
            "campaign_id",
            "consumed_at_utc",
            "paper_only",
            "plan_sha256",
            "preflight_sha256",
            "real_money_enabled",
            "schema_version",
            "state",
        }
        _require_exact_keys(record, keys, "consumption record")
        if (
            record["schema_version"] != 1
            or record["state"] != "PENDING"
            or record["campaign_id"] != plan.campaign_id
            or record["plan_sha256"] != plan.plan_sha256
        ):
            raise AlpacaCampaignSleeveError("consumption marker is not bound to this plan")
        if not _SHA256_RE.fullmatch(str(record["preflight_sha256"])):
            raise AlpacaCampaignSleeveError("consumption preflight digest is invalid")
        _utc(str(record["consumed_at_utc"]), "consumed_at_utc")
        _strict_bool(record["paper_only"], True, "consumption.paper_only")
        _strict_bool(record["real_money_enabled"], False, "consumption.real_money_enabled")
        return record

    def consume_once(
        self,
        plan: SealedPaperPlan,
        policy: SleevePolicy,
        snapshot: SleeveSnapshot,
        evidence: Sequence[AlpacaAssetEvidence],
        *,
        evaluated_at_utc: str,
    ) -> ConsumptionDecision:
        """Authorize one paper submission, or return a non-submitting duplicate decision."""

        plan.verify()
        marker_path = self._consumption_path(plan)
        claim_path = self._state_claim_path(plan)
        if marker_path.exists():
            self._read_state_claim(plan)
            self._read_consumption(plan)
            state = "PENDING_RECONCILIATION"
            if self._outcome_path(plan).exists():
                state = self.read_outcome(plan).state
            return ConsumptionDecision(
                should_submit=False,
                state=state,
                reason="sealed plan was already consumed; resubmission is forbidden",
                plan_sha256=plan.plan_sha256,
                preflight=None,
            )
        if self._outcome_path(plan).exists():
            raise AlpacaCampaignSleeveError(
                "orphaned outcome exists without a consumption marker; submission is blocked"
            )
        preflight = preflight_paper_plan(
            plan,
            policy,
            snapshot,
            evidence,
            evaluated_at_utc=evaluated_at_utc,
        )
        if not self._acquire_campaign_lock(plan, evaluated_at_utc):
            return ConsumptionDecision(
                should_submit=False,
                state="REFUSED_CAMPAIGN_LOCKED",
                reason="another process is changing this campaign; retry cannot submit",
                plan_sha256=plan.plan_sha256,
                preflight=None,
            )
        try:
            if marker_path.exists():
                self._read_state_claim(plan)
                self._read_consumption(plan)
                return ConsumptionDecision(
                    should_submit=False,
                    state="PENDING_RECONCILIATION",
                    reason="another process already consumed the sealed plan",
                    plan_sha256=plan.plan_sha256,
                    preflight=None,
                )
            if snapshot.open_orders:
                return ConsumptionDecision(
                    should_submit=False,
                    state="REFUSED_OPEN_ORDERS",
                    reason="existing open orders require reconciliation before plan consumption",
                    plan_sha256=plan.plan_sha256,
                    preflight=None,
                )
            head_result = self._read_campaign_head(plan)
            prior_head: Mapping[str, Any] | None = None
            prior_head_sha: str | None = None
            if head_result is not None:
                prior_head, prior_head_sha = head_result
                if prior_head["halted"] is True:
                    return ConsumptionDecision(
                        should_submit=False,
                        state="REFUSED_CAMPAIGN_HALTED",
                        reason="a prior non-exact outcome permanently halted this campaign",
                        plan_sha256=plan.plan_sha256,
                        preflight=None,
                    )
                active = prior_head["active_plan_sha256"]
                if active is not None:
                    return ConsumptionDecision(
                        should_submit=False,
                        state="REFUSED_CAMPAIGN_PENDING",
                        reason="another plan in this campaign still requires reconciliation",
                        plan_sha256=plan.plan_sha256,
                        preflight=None,
                    )
                prior_date = str(prior_head["trading_date"])
                if plan.trading_date < prior_date:
                    return ConsumptionDecision(
                        should_submit=False,
                        state="REFUSED_STATE_REGRESSION",
                        reason="campaign trading date moved backwards",
                        plan_sha256=plan.plan_sha256,
                        preflight=None,
                    )
                if (
                    plan.trading_date == prior_date
                    and plan.orders_submitted_before != prior_head["next_orders_submitted_today"]
                ):
                    return ConsumptionDecision(
                        should_submit=False,
                        state="REFUSED_STATE_REGRESSION",
                        reason="daily order sequence does not follow the committed campaign head",
                        plan_sha256=plan.plan_sha256,
                        preflight=None,
                    )
                expected_positions = self._position_map(prior_head["canonical_positions"])
                observed_positions = {
                    position.symbol: _decimal(position.quantity, "position.quantity")
                    for position in snapshot.positions
                }
                cash_ceiling = _decimal(
                    prior_head["canonical_cash_ceiling"], "canonical_cash_ceiling"
                )
                if (
                    prior_head["state_phase"] != "POST_COMMITTED"
                    or observed_positions != expected_positions
                    or _decimal(snapshot.cash, "cash") > cash_ceiling
                ):
                    return ConsumptionDecision(
                        should_submit=False,
                        state="REFUSED_STATE_DISCONTINUITY",
                        reason="cash/positions do not reconcile to the prior committed outcome",
                        plan_sha256=plan.plan_sha256,
                        preflight=None,
                    )
            if claim_path.exists():
                return ConsumptionDecision(
                    should_submit=False,
                    state="REFUSED_STATE_ALREADY_CLAIMED",
                    reason="this campaign state was already claimed by a sealed plan",
                    plan_sha256=plan.plan_sha256,
                    preflight=None,
                )
            state_record: dict[str, Any] = {
                "campaign_id": plan.campaign_id,
                "claimed_at_utc": _utc_text(evaluated_at_utc, "evaluated_at_utc"),
                "paper_only": True,
                "plan_sha256": plan.plan_sha256,
                "real_money_enabled": False,
                "schema_version": 1,
                "snapshot_sha256": plan.snapshot_sha256,
                "state_claim_sha256": plan.state_claim_sha256,
            }
            state_envelope = {
                "record": state_record,
                "record_sha256": _sha256(state_record),
            }
            if not _write_exclusive(claim_path, state_envelope):
                return ConsumptionDecision(
                    should_submit=False,
                    state="REFUSED_STATE_ALREADY_CLAIMED",
                    reason="another process claimed this campaign state",
                    plan_sha256=plan.plan_sha256,
                    preflight=None,
                )
            next_count = plan.orders_submitted_before + plan.planned_order_count
            head_record: dict[str, Any] = {
                "active_plan_sha256": plan.plan_sha256,
                "campaign_id": plan.campaign_id,
                "canonical_cash_ceiling": _decimal_text(snapshot.cash, "cash"),
                "canonical_positions": self._position_rows(snapshot.positions),
                "generation": 1 if prior_head is None else int(prior_head["generation"]) + 1,
                "halted": False,
                "last_terminal_state": None
                if prior_head is None
                else prior_head["last_terminal_state"],
                "next_orders_submitted_today": next_count,
                "paper_only": True,
                "previous_head_sha256": prior_head_sha,
                "real_money_enabled": False,
                "schema_version": 1,
                "state_phase": "PRE_ORDER",
                "trading_date": plan.trading_date,
            }
            self._write_campaign_head(plan, head_record)
            record: dict[str, Any] = {
                "campaign_id": plan.campaign_id,
                "consumed_at_utc": _utc_text(evaluated_at_utc, "evaluated_at_utc"),
                "paper_only": True,
                "plan_sha256": plan.plan_sha256,
                "preflight_sha256": preflight.preflight_sha256,
                "real_money_enabled": False,
                "schema_version": 1,
                "state": "PENDING",
            }
            envelope = {"record": record, "record_sha256": _sha256(record)}
            if not _write_exclusive(marker_path, envelope):
                self._read_consumption(plan)
                return ConsumptionDecision(
                    should_submit=False,
                    state="PENDING_RECONCILIATION",
                    reason="another process already consumed the sealed plan",
                    plan_sha256=plan.plan_sha256,
                    preflight=None,
                )
            return ConsumptionDecision(
                should_submit=True,
                state="PENDING_RECONCILIATION",
                reason="paper-only sealed plan consumed exactly once",
                plan_sha256=plan.plan_sha256,
                preflight=preflight,
            )
        finally:
            self._release_campaign_lock(plan)

    def finalize(
        self,
        plan: SealedPaperPlan,
        outcomes: Sequence[PaperOrderOutcome],
        *,
        finalized_at_utc: str,
    ) -> CampaignOutcomeReceipt:
        """Persist one campaign-wide terminal result without hiding partial fills."""

        plan.verify()
        if not self._consumption_path(plan).exists():
            raise AlpacaCampaignSleeveError("plan was never consumed")
        self._read_state_claim(plan)
        self._read_consumption(plan)
        outcome_by_id: dict[str, PaperOrderOutcome] = {}
        for outcome in outcomes:
            outcome.validate()
            if outcome.client_order_id in outcome_by_id:
                raise AlpacaCampaignSleeveError("duplicate order outcome")
            outcome_by_id[outcome.client_order_id] = outcome
        expected_ids = [order.client_order_id for order in plan.orders]
        if set(outcome_by_id) != set(expected_ids):
            raise AlpacaCampaignSleeveError(
                "outcomes do not exactly cover the sealed plan; plan remains consumed"
            )
        ordered_outcomes = tuple(outcome_by_id[client_id] for client_id in expected_ids)
        exact = True
        failure_reasons: list[str] = []
        for order, outcome in zip(plan.orders, ordered_outcomes, strict=True):
            requested = _decimal(outcome.requested_quantity, "requested_quantity")
            filled = _decimal(outcome.filled_quantity, "filled_quantity")
            sealed_quantity = _decimal(order.quantity, "order.quantity")
            if requested != sealed_quantity:
                exact = False
                failure_reasons.append(f"{order.client_order_id}: requested quantity changed")
            if outcome.status != "filled" or filled != sealed_quantity:
                exact = False
                failure_reasons.append(
                    f"{order.client_order_id}: status={outcome.status}, filled={filled}"
                )
            average_price = (
                None
                if outcome.average_fill_price is None
                else _decimal(outcome.average_fill_price, "average_fill_price")
            )
            limit_price = _decimal(order.limit_price, "order.limit_price")
            price_breached = average_price is not None and (
                (order.side == "buy" and average_price > limit_price)
                or (order.side == "sell" and average_price < limit_price)
            )
            if price_breached:
                exact = False
                failure_reasons.append(
                    f"{order.client_order_id}: average fill price breached the sealed limit price"
                )
        state = "COMMITTED" if exact else "FAILED_CLOSED"
        reason = (
            "every paper order filled at exactly the sealed quantity"
            if exact
            else "; ".join(failure_reasons)
        )
        outcome_rows = [outcome.sealed_content() for outcome in ordered_outcomes]
        outcomes_sha = _sha256(outcome_rows)
        content: dict[str, Any] = {
            "campaign_halted": not exact,
            "campaign_id": plan.campaign_id,
            "finalized_at_utc": _utc_text(finalized_at_utc, "finalized_at_utc"),
            "outcomes": outcome_rows,
            "outcomes_sha256": outcomes_sha,
            "paper_only": True,
            "plan_sha256": plan.plan_sha256,
            "real_money_enabled": False,
            "reason": reason,
            "requires_manual_reconciliation": not exact,
            "schema_version": 1,
            "state": state,
        }
        receipt = CampaignOutcomeReceipt(
            campaign_id=plan.campaign_id,
            plan_sha256=plan.plan_sha256,
            state=state,
            outcomes=ordered_outcomes,
            outcomes_sha256=outcomes_sha,
            finalized_at_utc=str(content["finalized_at_utc"]),
            reason=reason,
            campaign_halted=not exact,
            requires_manual_reconciliation=not exact,
            paper_only=True,
            real_money_enabled=False,
            receipt_sha256=_sha256(content),
            _construction_token=_RECEIPT_TOKEN,
        )
        receipt.verify()
        envelope = {"receipt": receipt.to_dict(), "receipt_sha256": receipt.receipt_sha256}
        outcome_path = self._outcome_path(plan)
        if not self._acquire_campaign_lock(plan, finalized_at_utc):
            raise AlpacaCampaignSleeveError(
                "campaign is being changed elsewhere; outcome remains fail-closed"
            )
        try:
            head_result = self._read_campaign_head(plan)
            if head_result is None:
                raise AlpacaCampaignSleeveError("campaign head is missing")
            head, head_sha = head_result
            active = head["active_plan_sha256"]
            if active not in {plan.plan_sha256, None}:
                raise AlpacaCampaignSleeveError("a different campaign plan is active")
            terminal_receipt = receipt
            if not _write_exclusive(outcome_path, envelope):
                prior = self.read_outcome(plan)
                if prior.outcomes_sha256 != receipt.outcomes_sha256:
                    raise AlpacaCampaignSleeveError(
                        "a different immutable outcome already exists for this plan"
                    )
                terminal_receipt = prior
            if active is None:
                if head["last_terminal_state"] != terminal_receipt.state:
                    raise AlpacaCampaignSleeveError("campaign head and immutable outcome disagree")
                return terminal_receipt
            canonical_cash = _decimal(head["canonical_cash_ceiling"], "canonical_cash_ceiling")
            canonical_positions = self._position_map(head["canonical_positions"])
            if terminal_receipt.state == "COMMITTED":
                for order, outcome in zip(plan.orders, terminal_receipt.outcomes, strict=True):
                    quantity = _decimal(order.quantity, "order.quantity")
                    if outcome.average_fill_price is None:  # guarded by outcome validation
                        raise AlpacaCampaignSleeveError("committed fill has no price")
                    price = _decimal(outcome.average_fill_price, "average_fill_price")
                    if order.side == "buy":
                        canonical_cash -= quantity * price
                        canonical_positions[order.symbol] = (
                            canonical_positions.get(order.symbol, _ZERO) + quantity
                        )
                    else:
                        canonical_cash += quantity * price
                        canonical_positions[order.symbol] = (
                            canonical_positions.get(order.symbol, _ZERO) - quantity
                        )
                canonical_positions = {
                    symbol: quantity
                    for symbol, quantity in canonical_positions.items()
                    if quantity != _ZERO
                }
                if canonical_cash < _ZERO or any(
                    quantity < _ZERO for quantity in canonical_positions.values()
                ):
                    raise AlpacaCampaignSleeveError(
                        "committed outcome produced an impossible canonical sleeve state"
                    )
            canonical_rows = [
                {
                    "quantity": _decimal_text(quantity, "position.quantity"),
                    "symbol": symbol,
                }
                for symbol, quantity in sorted(canonical_positions.items())
            ]
            next_head: dict[str, Any] = {
                "active_plan_sha256": None,
                "campaign_id": plan.campaign_id,
                "canonical_cash_ceiling": _decimal_text(canonical_cash, "canonical_cash_ceiling"),
                "canonical_positions": canonical_rows,
                "generation": int(head["generation"]) + 1,
                "halted": terminal_receipt.state == "FAILED_CLOSED",
                "last_terminal_state": terminal_receipt.state,
                "next_orders_submitted_today": head["next_orders_submitted_today"],
                "paper_only": True,
                "previous_head_sha256": head_sha,
                "real_money_enabled": False,
                "schema_version": 1,
                "state_phase": "HALTED"
                if terminal_receipt.state == "FAILED_CLOSED"
                else "POST_COMMITTED",
                "trading_date": head["trading_date"],
            }
            self._write_campaign_head(plan, next_head)
            return terminal_receipt
        finally:
            self._release_campaign_lock(plan)

    def read_outcome(self, plan: SealedPaperPlan) -> CampaignOutcomeReceipt:
        plan.verify()
        envelope = _read_json_object(self._outcome_path(plan), "outcome receipt")
        _require_exact_keys(envelope, {"receipt", "receipt_sha256"}, "outcome envelope")
        raw = envelope["receipt"]
        if not isinstance(raw, Mapping):
            raise AlpacaCampaignSleeveError("outcome receipt is corrupt")
        receipt_keys = {
            "campaign_halted",
            "campaign_id",
            "finalized_at_utc",
            "outcomes",
            "outcomes_sha256",
            "paper_only",
            "plan_sha256",
            "real_money_enabled",
            "reason",
            "receipt_sha256",
            "requires_manual_reconciliation",
            "schema_version",
            "state",
        }
        _require_exact_keys(raw, receipt_keys, "outcome receipt")
        if raw["schema_version"] != 1:
            raise AlpacaCampaignSleeveError("unsupported outcome receipt schema")
        raw_outcomes = raw["outcomes"]
        if not isinstance(raw_outcomes, list):
            raise AlpacaCampaignSleeveError("receipt outcomes must be a list")
        outcome_keys = {
            "average_fill_price",
            "client_order_id",
            "filled_quantity",
            "paper_only",
            "real_money_enabled",
            "requested_quantity",
            "status",
        }
        parsed_outcomes: list[PaperOrderOutcome] = []
        for row in raw_outcomes:
            if not isinstance(row, Mapping):
                raise AlpacaCampaignSleeveError("receipt outcome is not an object")
            _require_exact_keys(row, outcome_keys, "receipt order outcome")
            average = row["average_fill_price"]
            parsed_outcomes.append(
                PaperOrderOutcome(
                    client_order_id=str(row["client_order_id"]),
                    status=str(row["status"]),
                    requested_quantity=_decimal(row["requested_quantity"], "requested_quantity"),
                    filled_quantity=_decimal(row["filled_quantity"], "filled_quantity"),
                    average_fill_price=None
                    if average is None
                    else _decimal(average, "average_fill_price"),
                    paper_only=row["paper_only"],
                    real_money_enabled=row["real_money_enabled"],
                )
            )
        receipt = CampaignOutcomeReceipt(
            campaign_id=str(raw["campaign_id"]),
            plan_sha256=str(raw["plan_sha256"]),
            state=str(raw["state"]),
            outcomes=tuple(parsed_outcomes),
            outcomes_sha256=str(raw["outcomes_sha256"]),
            finalized_at_utc=str(raw["finalized_at_utc"]),
            reason=str(raw["reason"]),
            campaign_halted=raw["campaign_halted"],
            requires_manual_reconciliation=raw["requires_manual_reconciliation"],
            paper_only=raw["paper_only"],
            real_money_enabled=raw["real_money_enabled"],
            receipt_sha256=str(raw["receipt_sha256"]),
            _construction_token=_RECEIPT_TOKEN,
        )
        if receipt.campaign_id != plan.campaign_id or receipt.plan_sha256 != plan.plan_sha256:
            raise AlpacaCampaignSleeveError("outcome receipt is not bound to this plan")
        if str(envelope["receipt_sha256"]) != receipt.receipt_sha256:
            raise AlpacaCampaignSleeveError("outcome envelope digest mismatch")
        receipt.verify()
        return receipt


def plan_json(plan: SealedPaperPlan) -> str:
    """Return stable JSON suitable for a durable plan artifact."""

    return _canonical_bytes(plan.to_dict()).decode("utf-8") + "\n"


__all__ = [
    "USD_200",
    "AlpacaAssetEvidence",
    "AlpacaCampaignSleeveError",
    "CampaignOutcomeReceipt",
    "ConsumptionDecision",
    "PaperOrderOutcome",
    "PaperPlanConsumptionLedger",
    "PaperPlannedOrder",
    "ProjectedSleevePosition",
    "SealedPaperPlan",
    "SleeveOpenOrder",
    "SleevePolicy",
    "SleevePosition",
    "SleevePreflight",
    "SleeveSnapshot",
    "asset_evidence_digest",
    "load_sealed_paper_plan",
    "plan_json",
    "preflight_paper_plan",
    "seal_paper_plan",
]
