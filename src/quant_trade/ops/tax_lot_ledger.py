"""Offline, MXN-denominated tax-lot and transaction-cost measurement.

The module consumes already-normalized fills and explicit FX observations.  It
does not fetch prices, infer exchange rates, interpret tax law, construct an
order, or authorize money.  A tax number is produced only when the caller
supplies an explicitly hypothetical scenario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

Side = Literal["BUY", "SELL"]
LotMethod = Literal["FIFO"]
TaxableBaseMode = Literal["POSITIVE_NET_REALIZED_PNL_MXN"]
MeasurementStatus = Literal[
    "COMPLETE",
    "INCOMPLETE_MARKS",
    "INCOMPLETE_TCA",
    "INSUFFICIENT_FUNDING",
]

_CURRENCY_PATTERN = re.compile(r"[A-Z][A-Z0-9]{2,9}")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}")


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal, not bool")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not converted.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and converted <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return converted


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _require_text(value: Any, name: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty canonical string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")
    return value


def _utc_timestamp(value: Any, name: str) -> datetime:
    text = _require_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{name} must include a UTC offset")
    return parsed.astimezone(UTC)


def _fee_rate_mxn(fill: TaxLotFill) -> Decimal:
    if fill.fee_mxn_per_unit is not None:
        return fill.fee_mxn_per_unit
    if fill.fee_currency == "MXN":
        return Decimal(1)
    if fill.fee_currency == fill.quote_currency:
        return fill.mxn_per_quote
    if fill.fee_amount == 0:
        return Decimal(0)
    raise ValueError("non-quote fee currency requires explicit fee_mxn_per_unit")


@dataclass(frozen=True, slots=True)
class TaxLotLedgerConfig:
    """Accounting choices; only long-only FIFO is intentionally supported."""

    reporting_currency: str = "MXN"
    lot_method: LotMethod = "FIFO"
    allow_short_positions: bool = False

    def __post_init__(self) -> None:
        if self.reporting_currency != "MXN":
            raise ValueError("reporting_currency must be MXN")
        if self.lot_method != "FIFO":
            raise ValueError("only the explicitly configured FIFO lot method is supported")
        if self.allow_short_positions is not False:
            raise ValueError("short positions are outside this measurement component")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reporting_currency": self.reporting_currency,
            "lot_method": self.lot_method,
            "allow_short_positions": self.allow_short_positions,
        }


@dataclass(frozen=True, slots=True)
class TaxScenario:
    """User-declared hypothetical arithmetic, not a statement of tax liability."""

    label: str
    tax_rate_fraction: Decimal
    taxable_base_mode: TaxableBaseMode
    declared_by_user: bool
    assumption_source: str

    def __post_init__(self) -> None:
        _require_text(self.label, "tax_scenario.label")
        _require_text(self.assumption_source, "tax_scenario.assumption_source")
        rate = _decimal(self.tax_rate_fraction, "tax_scenario.tax_rate_fraction")
        if rate < 0 or rate > 1:
            raise ValueError("tax_scenario.tax_rate_fraction must be between zero and one")
        object.__setattr__(self, "tax_rate_fraction", rate)
        if self.taxable_base_mode != "POSITIVE_NET_REALIZED_PNL_MXN":
            raise ValueError("unsupported tax_scenario.taxable_base_mode")
        if self.declared_by_user is not True:
            raise ValueError("tax scenario must be explicitly declared by the user")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "tax_rate_fraction": _decimal_text(self.tax_rate_fraction),
            "taxable_base_mode": self.taxable_base_mode,
            "declared_by_user": self.declared_by_user,
            "assumption_source": self.assumption_source,
            "legal_or_tax_advice": False,
        }


@dataclass(frozen=True, slots=True)
class TaxLotFill:
    """One actual or paper fill with event-time conversion evidence.

    ``quantity`` is the inventory-changing base quantity after any base-asset
    fee deduction.  ``fee_amount`` is therefore a separate cash expense and
    must not encode another inventory deduction.
    """

    fill_id: str
    instrument_id: str
    executed_at_utc: str
    side: Side
    quantity: Decimal
    unit_price_quote: Decimal
    quote_currency: str
    mxn_per_quote: Decimal
    quote_fx_source: str
    fee_amount: Decimal
    fee_currency: str
    fee_mxn_per_unit: Decimal | None = None
    fee_fx_source: str | None = None
    reference_price_quote: Decimal | None = None
    reference_at_utc: str | None = None
    reference_source: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.fill_id, "fill_id", _IDENTIFIER_PATTERN)
        _require_text(self.instrument_id, "instrument_id", _IDENTIFIER_PATTERN)
        executed_at = _utc_timestamp(self.executed_at_utc, "executed_at_utc")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        quantity = _decimal(self.quantity, "quantity", positive=True)
        price = _decimal(self.unit_price_quote, "unit_price_quote", positive=True)
        quote_fx = _decimal(self.mxn_per_quote, "mxn_per_quote", positive=True)
        fee = _decimal(self.fee_amount, "fee_amount")
        if fee < 0:
            raise ValueError("fee_amount cannot be negative")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "unit_price_quote", price)
        object.__setattr__(self, "mxn_per_quote", quote_fx)
        object.__setattr__(self, "fee_amount", fee)

        _require_text(self.quote_currency, "quote_currency", _CURRENCY_PATTERN)
        _require_text(self.fee_currency, "fee_currency", _CURRENCY_PATTERN)
        _require_text(self.quote_fx_source, "quote_fx_source")
        if self.quote_currency == "MXN" and quote_fx != 1:
            raise ValueError("MXN quote currency requires mxn_per_quote=1")

        if self.fee_mxn_per_unit is not None:
            fee_fx = _decimal(self.fee_mxn_per_unit, "fee_mxn_per_unit", positive=True)
            object.__setattr__(self, "fee_mxn_per_unit", fee_fx)
            _require_text(self.fee_fx_source, "fee_fx_source")
            if self.fee_currency == "MXN" and fee_fx != 1:
                raise ValueError("MXN fee currency requires fee_mxn_per_unit=1")
            if self.fee_currency == self.quote_currency and fee_fx != quote_fx:
                raise ValueError(
                    "quote and fee currencies cannot use contradictory MXN conversion rates"
                )
        elif fee > 0 and self.fee_currency not in {"MXN", self.quote_currency}:
            raise ValueError("non-quote fee currency requires explicit fee FX evidence")

        reference_fields = (
            self.reference_price_quote,
            self.reference_at_utc,
            self.reference_source,
        )
        if any(value is not None for value in reference_fields) and not all(
            value is not None for value in reference_fields
        ):
            raise ValueError(
                "reference_price_quote, reference_at_utc, and reference_source "
                "must be supplied together"
            )
        if self.reference_price_quote is not None:
            reference = _decimal(
                self.reference_price_quote,
                "reference_price_quote",
                positive=True,
            )
            object.__setattr__(self, "reference_price_quote", reference)
            reference_at = _utc_timestamp(self.reference_at_utc, "reference_at_utc")
            _require_text(self.reference_source, "reference_source")
            if reference_at > executed_at:
                raise ValueError("reference_at_utc cannot be later than executed_at_utc")

    @property
    def notional_mxn(self) -> Decimal:
        return self.quantity * self.unit_price_quote * self.mxn_per_quote

    @property
    def fee_mxn(self) -> Decimal:
        return self.fee_amount * _fee_rate_mxn(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "instrument_id": self.instrument_id,
            "executed_at_utc": self.executed_at_utc,
            "side": self.side,
            "quantity": _decimal_text(self.quantity),
            "unit_price_quote": _decimal_text(self.unit_price_quote),
            "quote_currency": self.quote_currency,
            "mxn_per_quote": _decimal_text(self.mxn_per_quote),
            "quote_fx_source": self.quote_fx_source,
            "fee_amount": _decimal_text(self.fee_amount),
            "fee_currency": self.fee_currency,
            "fee_mxn_per_unit": _decimal_text(self.fee_mxn_per_unit),
            "fee_fx_source": self.fee_fx_source,
            "reference_price_quote": _decimal_text(self.reference_price_quote),
            "reference_at_utc": self.reference_at_utc,
            "reference_source": self.reference_source,
        }


@dataclass(frozen=True, slots=True)
class MarkEvidence:
    instrument_id: str
    as_of_utc: str
    unit_price_quote: Decimal
    quote_currency: str
    mxn_per_quote: Decimal
    quote_fx_source: str

    def __post_init__(self) -> None:
        _require_text(self.instrument_id, "mark.instrument_id", _IDENTIFIER_PATTERN)
        _utc_timestamp(self.as_of_utc, "mark.as_of_utc")
        price = _decimal(self.unit_price_quote, "mark.unit_price_quote", positive=True)
        fx = _decimal(self.mxn_per_quote, "mark.mxn_per_quote", positive=True)
        object.__setattr__(self, "unit_price_quote", price)
        object.__setattr__(self, "mxn_per_quote", fx)
        _require_text(self.quote_currency, "mark.quote_currency", _CURRENCY_PATTERN)
        _require_text(self.quote_fx_source, "mark.quote_fx_source")
        if self.quote_currency == "MXN" and fx != 1:
            raise ValueError("MXN mark currency requires mxn_per_quote=1")

    @property
    def unit_price_mxn(self) -> Decimal:
        return self.unit_price_quote * self.mxn_per_quote

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "as_of_utc": self.as_of_utc,
            "unit_price_quote": _decimal_text(self.unit_price_quote),
            "quote_currency": self.quote_currency,
            "mxn_per_quote": _decimal_text(self.mxn_per_quote),
            "quote_fx_source": self.quote_fx_source,
        }


@dataclass(frozen=True, slots=True)
class AfterTaxTcaRequest:
    initial_capital_mxn: Decimal
    config: TaxLotLedgerConfig
    fills: tuple[TaxLotFill, ...]
    marks: tuple[MarkEvidence, ...]
    valuation_as_of_utc: str
    tax_scenario: TaxScenario | None = None

    def __post_init__(self) -> None:
        capital = _decimal(self.initial_capital_mxn, "initial_capital_mxn", positive=True)
        object.__setattr__(self, "initial_capital_mxn", capital)
        if not isinstance(self.config, TaxLotLedgerConfig):
            raise ValueError("config must be TaxLotLedgerConfig")
        fills = tuple(self.fills)
        marks = tuple(self.marks)
        object.__setattr__(self, "fills", fills)
        object.__setattr__(self, "marks", marks)
        if not fills:
            raise ValueError("at least one fill is required")
        if any(not isinstance(fill, TaxLotFill) for fill in fills):
            raise ValueError("fills must contain only TaxLotFill values")
        if any(not isinstance(mark, MarkEvidence) for mark in marks):
            raise ValueError("marks must contain only MarkEvidence values")
        if self.tax_scenario is not None and not isinstance(self.tax_scenario, TaxScenario):
            raise ValueError("tax_scenario must be TaxScenario or None")

        fill_ids = [fill.fill_id for fill in fills]
        if len(fill_ids) != len(set(fill_ids)):
            raise ValueError("fill_id values must be unique")
        fill_times = [_utc_timestamp(fill.executed_at_utc, "executed_at_utc") for fill in fills]
        if fill_times != sorted(fill_times):
            raise ValueError("fills must be supplied in non-decreasing execution order")

        valuation_at = _utc_timestamp(self.valuation_as_of_utc, "valuation_as_of_utc")
        if valuation_at < fill_times[-1]:
            raise ValueError("valuation_as_of_utc cannot predate the latest fill")
        mark_ids = [mark.instrument_id for mark in marks]
        if len(mark_ids) != len(set(mark_ids)):
            raise ValueError("at most one mark is allowed per instrument")
        if any(mark.as_of_utc != self.valuation_as_of_utc for mark in marks):
            raise ValueError("every mark must use the exact valuation_as_of_utc timestamp")

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital_mxn": _decimal_text(self.initial_capital_mxn),
            "config": self.config.to_dict(),
            "fills": [fill.to_dict() for fill in self.fills],
            "marks": [mark.to_dict() for mark in self.marks],
            "valuation_as_of_utc": self.valuation_as_of_utc,
            "tax_scenario": self.tax_scenario.to_dict() if self.tax_scenario else None,
        }


@dataclass(frozen=True, slots=True)
class OpenTaxLot:
    source_fill_id: str
    instrument_id: str
    acquired_at_utc: str
    quantity_remaining: Decimal
    unit_cost_basis_mxn: Decimal
    cost_basis_remaining_mxn: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_fill_id": self.source_fill_id,
            "instrument_id": self.instrument_id,
            "acquired_at_utc": self.acquired_at_utc,
            "quantity_remaining": _decimal_text(self.quantity_remaining),
            "unit_cost_basis_mxn": _decimal_text(self.unit_cost_basis_mxn),
            "cost_basis_remaining_mxn": _decimal_text(self.cost_basis_remaining_mxn),
        }


@dataclass(frozen=True, slots=True)
class TaxLotRealization:
    sell_fill_id: str
    source_buy_fill_id: str
    instrument_id: str
    quantity: Decimal
    gross_proceeds_mxn: Decimal
    allocated_sell_fee_mxn: Decimal
    cost_basis_mxn: Decimal
    gross_pnl_mxn: Decimal
    realized_pre_tax_pnl_mxn: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "sell_fill_id": self.sell_fill_id,
            "source_buy_fill_id": self.source_buy_fill_id,
            "instrument_id": self.instrument_id,
            "quantity": _decimal_text(self.quantity),
            "gross_proceeds_mxn": _decimal_text(self.gross_proceeds_mxn),
            "allocated_sell_fee_mxn": _decimal_text(self.allocated_sell_fee_mxn),
            "cost_basis_mxn": _decimal_text(self.cost_basis_mxn),
            "gross_pnl_mxn": _decimal_text(self.gross_pnl_mxn),
            "realized_pre_tax_pnl_mxn": _decimal_text(self.realized_pre_tax_pnl_mxn),
        }


@dataclass(frozen=True, slots=True)
class AfterTaxTcaMeasurement:
    request: AfterTaxTcaRequest
    status: MeasurementStatus
    gross_buy_notional_mxn: Decimal
    gross_sell_notional_mxn: Decimal
    total_fees_mxn: Decimal
    signed_implementation_shortfall_mxn: Decimal | None
    adverse_slippage_mxn: Decimal | None
    transaction_cost_mxn: Decimal | None
    realized_gross_pnl_mxn: Decimal
    realized_pre_tax_pnl_mxn: Decimal
    mark_value_mxn: Decimal | None
    unrealized_pre_tax_pnl_mxn: Decimal | None
    equity_pnl_pre_tax_mxn: Decimal | None
    scenario_taxable_base_mxn: Decimal | None
    scenario_tax_mxn: Decimal | None
    realized_after_tax_scenario_pnl_mxn: Decimal | None
    equity_pnl_after_realized_tax_scenario_mxn: Decimal | None
    return_on_initial_capital_pre_tax: Decimal | None
    return_on_initial_capital_after_realized_tax_scenario: Decimal | None
    minimum_funding_required_mxn: Decimal
    capital_shortfall_mxn: Decimal
    open_lots: tuple[OpenTaxLot, ...]
    realizations: tuple[TaxLotRealization, ...]
    missing_reference_fill_ids: tuple[str, ...]
    missing_mark_instrument_ids: tuple[str, ...]
    request_digest: str
    measurement_digest: str

    def is_verified(self) -> bool:
        try:
            return self == evaluate_after_tax_tca(self.request)
        except (AttributeError, TypeError, ValueError, InvalidOperation):
            return False

    def _payload(self, *, include_digest: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "measurement": "OFFLINE_AFTER_TAX_TCA_MXN",
            "status": self.status,
            "request": self.request.to_dict(),
            "gross_buy_notional_mxn": _decimal_text(self.gross_buy_notional_mxn),
            "gross_sell_notional_mxn": _decimal_text(self.gross_sell_notional_mxn),
            "total_fees_mxn": _decimal_text(self.total_fees_mxn),
            "signed_implementation_shortfall_mxn": _decimal_text(
                self.signed_implementation_shortfall_mxn
            ),
            "adverse_slippage_mxn": _decimal_text(self.adverse_slippage_mxn),
            "transaction_cost_mxn": _decimal_text(self.transaction_cost_mxn),
            "realized_gross_pnl_mxn": _decimal_text(self.realized_gross_pnl_mxn),
            "realized_pre_tax_pnl_mxn": _decimal_text(self.realized_pre_tax_pnl_mxn),
            "mark_value_mxn": _decimal_text(self.mark_value_mxn),
            "unrealized_pre_tax_pnl_mxn": _decimal_text(self.unrealized_pre_tax_pnl_mxn),
            "equity_pnl_pre_tax_mxn": _decimal_text(self.equity_pnl_pre_tax_mxn),
            "scenario_taxable_base_mxn": _decimal_text(self.scenario_taxable_base_mxn),
            "scenario_tax_mxn": _decimal_text(self.scenario_tax_mxn),
            "realized_after_tax_scenario_pnl_mxn": _decimal_text(
                self.realized_after_tax_scenario_pnl_mxn
            ),
            "equity_pnl_after_realized_tax_scenario_mxn": _decimal_text(
                self.equity_pnl_after_realized_tax_scenario_mxn
            ),
            "return_on_initial_capital_pre_tax": _decimal_text(
                self.return_on_initial_capital_pre_tax
            ),
            "return_on_initial_capital_after_realized_tax_scenario": _decimal_text(
                self.return_on_initial_capital_after_realized_tax_scenario
            ),
            "minimum_funding_required_mxn": _decimal_text(self.minimum_funding_required_mxn),
            "capital_shortfall_mxn": _decimal_text(self.capital_shortfall_mxn),
            "open_lots": [lot.to_dict() for lot in self.open_lots],
            "realizations": [item.to_dict() for item in self.realizations],
            "missing_reference_fill_ids": list(self.missing_reference_fill_ids),
            "missing_mark_instrument_ids": list(self.missing_mark_instrument_ids),
            "request_digest": self.request_digest,
            "tax_is_user_scenario_only": True,
            "legal_or_tax_advice": False,
            "automatic_transition_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
            "profit_claim_authorized": False,
        }
        if include_digest:
            payload["measurement_digest"] = self.measurement_digest
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload(include_digest=True)


@dataclass(slots=True)
class _MutableLot:
    source_fill_id: str
    instrument_id: str
    acquired_at_utc: str
    quantity: Decimal
    unit_gross_cost_mxn: Decimal
    unit_cost_basis_mxn: Decimal


def evaluate_after_tax_tca(request: AfterTaxTcaRequest) -> AfterTaxTcaMeasurement:
    """Reconstruct long-only FIFO lots and MXN P&L from explicit evidence."""
    if not isinstance(request, AfterTaxTcaRequest):
        raise ValueError("request must be AfterTaxTcaRequest")

    lots: dict[str, list[_MutableLot]] = {}
    realizations: list[TaxLotRealization] = []
    gross_buys = Decimal(0)
    gross_sells = Decimal(0)
    fees = Decimal(0)
    realized_gross = Decimal(0)
    realized_pre_tax = Decimal(0)
    signed_implementation_shortfall = Decimal(0)
    missing_references: list[str] = []
    running_cash_flow = Decimal(0)
    funding_required = Decimal(0)

    for fill in request.fills:
        notional = fill.notional_mxn
        fee = fill.fee_mxn
        fees += fee
        if fill.reference_price_quote is None:
            missing_references.append(fill.fill_id)
        else:
            price_difference = (
                fill.unit_price_quote - fill.reference_price_quote
                if fill.side == "BUY"
                else fill.reference_price_quote - fill.unit_price_quote
            )
            signed_implementation_shortfall += price_difference * fill.quantity * fill.mxn_per_quote

        instrument_lots = lots.setdefault(fill.instrument_id, [])
        if fill.side == "BUY":
            gross_buys += notional
            running_cash_flow -= notional + fee
            funding_required = max(funding_required, -running_cash_flow)
            instrument_lots.append(
                _MutableLot(
                    source_fill_id=fill.fill_id,
                    instrument_id=fill.instrument_id,
                    acquired_at_utc=fill.executed_at_utc,
                    quantity=fill.quantity,
                    unit_gross_cost_mxn=notional / fill.quantity,
                    unit_cost_basis_mxn=(notional + fee) / fill.quantity,
                )
            )
            continue

        inventory = sum((lot.quantity for lot in instrument_lots), Decimal(0))
        if fill.quantity > inventory:
            raise ValueError(
                f"sell fill {fill.fill_id} exceeds long inventory for {fill.instrument_id}"
            )
        gross_sells += notional
        running_cash_flow += notional - fee
        funding_required = max(funding_required, -running_cash_flow)
        quantity_left = fill.quantity
        for lot in instrument_lots:
            if quantity_left == 0:
                break
            used = min(quantity_left, lot.quantity)
            gross_proceeds = used * fill.unit_price_quote * fill.mxn_per_quote
            allocated_sell_fee = fee * used / fill.quantity
            gross_cost = used * lot.unit_gross_cost_mxn
            cost_basis = used * lot.unit_cost_basis_mxn
            gross_pnl = gross_proceeds - gross_cost
            pre_tax_pnl = gross_proceeds - allocated_sell_fee - cost_basis
            realized_gross += gross_pnl
            realized_pre_tax += pre_tax_pnl
            realizations.append(
                TaxLotRealization(
                    sell_fill_id=fill.fill_id,
                    source_buy_fill_id=lot.source_fill_id,
                    instrument_id=fill.instrument_id,
                    quantity=used,
                    gross_proceeds_mxn=gross_proceeds,
                    allocated_sell_fee_mxn=allocated_sell_fee,
                    cost_basis_mxn=cost_basis,
                    gross_pnl_mxn=gross_pnl,
                    realized_pre_tax_pnl_mxn=pre_tax_pnl,
                )
            )
            lot.quantity -= used
            quantity_left -= used

    open_lots = tuple(
        OpenTaxLot(
            source_fill_id=lot.source_fill_id,
            instrument_id=lot.instrument_id,
            acquired_at_utc=lot.acquired_at_utc,
            quantity_remaining=lot.quantity,
            unit_cost_basis_mxn=lot.unit_cost_basis_mxn,
            cost_basis_remaining_mxn=lot.quantity * lot.unit_cost_basis_mxn,
        )
        for instrument_lots in lots.values()
        for lot in instrument_lots
        if lot.quantity > 0
    )

    marks = {mark.instrument_id: mark for mark in request.marks}
    missing_marks = tuple(
        sorted({lot.instrument_id for lot in open_lots if lot.instrument_id not in marks})
    )
    capital_shortfall = max(funding_required - request.initial_capital_mxn, Decimal(0))
    if missing_marks:
        mark_value = None
        unrealized_pre_tax = None
        equity_pre_tax = None
    else:
        mark_value = sum(
            (lot.quantity_remaining * marks[lot.instrument_id].unit_price_mxn for lot in open_lots),
            Decimal(0),
        )
        remaining_basis = sum(
            (lot.cost_basis_remaining_mxn for lot in open_lots),
            Decimal(0),
        )
        unrealized_pre_tax = mark_value - remaining_basis
        equity_pre_tax = realized_pre_tax + unrealized_pre_tax

    if capital_shortfall > 0:
        status: MeasurementStatus = "INSUFFICIENT_FUNDING"
    elif missing_marks:
        status = "INCOMPLETE_MARKS"
    elif missing_references:
        status = "INCOMPLETE_TCA"
    else:
        status = "COMPLETE"

    if request.tax_scenario is None:
        taxable_base = None
        scenario_tax = None
        realized_after_tax = None
        equity_after_tax = None
    else:
        taxable_base = max(realized_pre_tax, Decimal(0))
        scenario_tax = taxable_base * request.tax_scenario.tax_rate_fraction
        realized_after_tax = realized_pre_tax - scenario_tax
        equity_after_tax = equity_pre_tax - scenario_tax if equity_pre_tax is not None else None

    # A P&L can still be reconstructed when the declared capital could not
    # fund the cash-flow path.  Dividing that P&L by the underfunded amount
    # would manufacture leverage/capital that the request never supplied.
    returns_are_defined = capital_shortfall == 0
    pre_tax_return = (
        equity_pre_tax / request.initial_capital_mxn
        if returns_are_defined and equity_pre_tax is not None
        else None
    )
    after_tax_return = (
        equity_after_tax / request.initial_capital_mxn
        if returns_are_defined and equity_after_tax is not None
        else None
    )
    complete_signed_shortfall = None if missing_references else signed_implementation_shortfall
    adverse_slippage = (
        max(complete_signed_shortfall, Decimal(0))
        if complete_signed_shortfall is not None
        else None
    )
    transaction_cost = fees + adverse_slippage if adverse_slippage is not None else None
    request_digest = sha256_of_text(canonical_dumps(request.to_dict()))
    measurement = AfterTaxTcaMeasurement(
        request=request,
        status=status,
        gross_buy_notional_mxn=gross_buys,
        gross_sell_notional_mxn=gross_sells,
        total_fees_mxn=fees,
        signed_implementation_shortfall_mxn=complete_signed_shortfall,
        adverse_slippage_mxn=adverse_slippage,
        transaction_cost_mxn=transaction_cost,
        realized_gross_pnl_mxn=realized_gross,
        realized_pre_tax_pnl_mxn=realized_pre_tax,
        mark_value_mxn=mark_value,
        unrealized_pre_tax_pnl_mxn=unrealized_pre_tax,
        equity_pnl_pre_tax_mxn=equity_pre_tax,
        scenario_taxable_base_mxn=taxable_base,
        scenario_tax_mxn=scenario_tax,
        realized_after_tax_scenario_pnl_mxn=realized_after_tax,
        equity_pnl_after_realized_tax_scenario_mxn=equity_after_tax,
        return_on_initial_capital_pre_tax=pre_tax_return,
        return_on_initial_capital_after_realized_tax_scenario=after_tax_return,
        minimum_funding_required_mxn=funding_required,
        capital_shortfall_mxn=capital_shortfall,
        open_lots=open_lots,
        realizations=tuple(realizations),
        missing_reference_fill_ids=tuple(missing_references),
        missing_mark_instrument_ids=missing_marks,
        request_digest=request_digest,
        measurement_digest="",
    )
    digest = sha256_of_text(canonical_dumps(measurement._payload(include_digest=False)))
    return replace(measurement, measurement_digest=digest)


__all__ = [
    "AfterTaxTcaMeasurement",
    "AfterTaxTcaRequest",
    "MarkEvidence",
    "MeasurementStatus",
    "OpenTaxLot",
    "TaxLotFill",
    "TaxLotLedgerConfig",
    "TaxLotRealization",
    "TaxScenario",
    "evaluate_after_tax_tca",
]
