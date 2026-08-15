"""Offline feasibility contract for a prospective BTC cash-and-carry study.

This module is intentionally *before* an ExperimentSpec.  It never calculates
profit or loss, reads market-history/holdout files, accesses the network, writes
artifacts, routes orders, or authorizes money movement.  Its most positive
state only says that an independently reviewed evidence pack is sufficient to
start a separate development-data collection.

The contemplated structure is one-venue, exactly matched BTC exposure: fully
funded long spot BTC/USDT plus an isolated, linear BTC/USDT perpetual short at
no more than 1x leverage.  This is not treated as risk-free arbitrage.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    sha256_of_bytes,
    sha256_of_text,
)

SCHEMA_VERSION = 1
SEALED_VENUE = "bybit"
SEALED_COUNTRY = "MX"
SEALED_BASE_ASSET = "BTC"
SEALED_QUOTE_ASSET = "USDT"
SEALED_BUDGET_USD = Decimal("200")
MAX_PERP_LEVERAGE = Decimal("1")
MIN_LIQUIDITY_RESERVE_FRACTION = Decimal("0.20")
MIN_LIQUIDATION_DISTANCE_FRACTION = Decimal("0.50")
MIN_DEPTH_MULTIPLE = Decimal("2")
MAX_ABS_FX_DEPEG_FRACTION = Decimal("0.05")
MAX_ABS_SNAPSHOT_BASIS_FRACTION = Decimal("0.10")
MAX_DYNAMIC_EVIDENCE_STALENESS_SECONDS = 300
MAX_SERVER_CLOCK_SKEW_SECONDS = 300

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BLOCKER_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")


class CarryFeasibilityError(ValueError):
    """The feasibility contract or its evidence envelope is malformed."""


class CarryFeasibilityStatus(StrEnum):
    """The only legal outcomes; none authorizes execution or promotion."""

    FEASIBLE_FOR_DEVELOPMENT_COLLECTION = "FEASIBLE_FOR_DEVELOPMENT_COLLECTION"
    INSUFFICIENT = "INSUFFICIENT"
    NO_GO = "NO_GO"


class BlockerSeverity(StrEnum):
    """A contradiction is NO_GO; an absent or stale fact is insufficient."""

    HARD = "HARD"
    MISSING = "MISSING"


class ReviewOutcome(StrEnum):
    """Outcome of a human/account/product review."""

    ACCEPTABLE_FOR_COLLECTION = "ACCEPTABLE_FOR_COLLECTION"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class KYCStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class CommercialUseStatus(StrEnum):
    """Commercial-use status of the exact bytes, not a provider in general."""

    PERMITTED = "PERMITTED"
    NOT_APPLICABLE_REVIEWED = "NOT_APPLICABLE_REVIEWED"
    PROHIBITED = "PROHIBITED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNKNOWN = "UNKNOWN"


class EvidenceAuthority(StrEnum):
    """Who is responsible for the evidence assertion."""

    VENUE_PRIMARY = "VENUE_PRIMARY"
    INDEPENDENT_MX_LEGAL_REVIEW = "INDEPENDENT_MX_LEGAL_REVIEW"
    INDEPENDENT_MX_TAX_REVIEW = "INDEPENDENT_MX_TAX_REVIEW"
    INDEPENDENT_COUNTERPARTY_REVIEW = "INDEPENDENT_COUNTERPARTY_REVIEW"
    PRIMARY_FX_REFERENCE = "PRIMARY_FX_REFERENCE"
    OPERATOR_OFFLINE_STRESS = "OPERATOR_OFFLINE_STRESS"


class EvidenceKind(StrEnum):
    VENUE_TERMS = "VENUE_TERMS"
    COUNTRY_PRODUCT_ELIGIBILITY = "COUNTRY_PRODUCT_ELIGIBILITY"
    KYC_ACCOUNT_CAPABILITIES = "KYC_ACCOUNT_CAPABILITIES"
    SPOT_INSTRUMENT = "SPOT_INSTRUMENT"
    PERP_INSTRUMENT = "PERP_INSTRUMENT"
    ACCOUNT_FEE_SPOT = "ACCOUNT_FEE_SPOT"
    ACCOUNT_FEE_PERP = "ACCOUNT_FEE_PERP"
    FUNDING_HISTORY_SCHEMA = "FUNDING_HISTORY_SCHEMA"
    BASIS_SERIES_SCHEMA = "BASIS_SERIES_SCHEMA"
    SPOT_ORDER_BOOK = "SPOT_ORDER_BOOK"
    PERP_ORDER_BOOK = "PERP_ORDER_BOOK"
    SPREAD_IMPACT_MODEL = "SPREAD_IMPACT_MODEL"
    BORROW_COLLATERAL_TERMS = "BORROW_COLLATERAL_TERMS"
    LIQUIDATION_RISK_TERMS = "LIQUIDATION_RISK_TERMS"
    FX_USDT_USD = "FX_USDT_USD"
    MX_TAX_TREATMENT = "MX_TAX_TREATMENT"
    TRANSFER_STRESS = "TRANSFER_STRESS"
    WITHDRAWAL_STRESS = "WITHDRAWAL_STRESS"
    COUNTERPARTY_RISK = "COUNTERPARTY_RISK"


REQUIRED_EVIDENCE_KINDS = tuple(EvidenceKind)

_MANUAL_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY,
        EvidenceKind.MX_TAX_TREATMENT,
        EvidenceKind.TRANSFER_STRESS,
        EvidenceKind.WITHDRAWAL_STRESS,
        EvidenceKind.COUNTERPARTY_RISK,
    }
)

_DYNAMIC_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.KYC_ACCOUNT_CAPABILITIES,
        EvidenceKind.SPOT_INSTRUMENT,
        EvidenceKind.PERP_INSTRUMENT,
        EvidenceKind.ACCOUNT_FEE_SPOT,
        EvidenceKind.ACCOUNT_FEE_PERP,
        EvidenceKind.FUNDING_HISTORY_SCHEMA,
        EvidenceKind.BASIS_SERIES_SCHEMA,
        EvidenceKind.SPOT_ORDER_BOOK,
        EvidenceKind.PERP_ORDER_BOOK,
        EvidenceKind.SPREAD_IMPACT_MODEL,
        EvidenceKind.BORROW_COLLATERAL_TERMS,
        EvidenceKind.LIQUIDATION_RISK_TERMS,
        EvidenceKind.FX_USDT_USD,
    }
)

_EXPECTED_AUTHORITIES: dict[EvidenceKind, EvidenceAuthority] = {
    EvidenceKind.VENUE_TERMS: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY: (EvidenceAuthority.INDEPENDENT_MX_LEGAL_REVIEW),
    EvidenceKind.KYC_ACCOUNT_CAPABILITIES: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.SPOT_INSTRUMENT: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.PERP_INSTRUMENT: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.ACCOUNT_FEE_SPOT: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.ACCOUNT_FEE_PERP: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.FUNDING_HISTORY_SCHEMA: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.BASIS_SERIES_SCHEMA: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.SPOT_ORDER_BOOK: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.PERP_ORDER_BOOK: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.SPREAD_IMPACT_MODEL: EvidenceAuthority.OPERATOR_OFFLINE_STRESS,
    EvidenceKind.BORROW_COLLATERAL_TERMS: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.LIQUIDATION_RISK_TERMS: EvidenceAuthority.VENUE_PRIMARY,
    EvidenceKind.FX_USDT_USD: EvidenceAuthority.PRIMARY_FX_REFERENCE,
    EvidenceKind.MX_TAX_TREATMENT: EvidenceAuthority.INDEPENDENT_MX_TAX_REVIEW,
    EvidenceKind.TRANSFER_STRESS: EvidenceAuthority.OPERATOR_OFFLINE_STRESS,
    EvidenceKind.WITHDRAWAL_STRESS: EvidenceAuthority.OPERATOR_OFFLINE_STRESS,
    EvidenceKind.COUNTERPARTY_RISK: EvidenceAuthority.INDEPENDENT_COUNTERPARTY_REVIEW,
}


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CarryFeasibilityError("timestamps must be explicit UTC text ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CarryFeasibilityError(f"invalid UTC timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CarryFeasibilityError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _decimal(name: str, value: str | int | float | Decimal) -> Decimal:
    if isinstance(value, bool):
        raise CarryFeasibilityError(f"{name} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CarryFeasibilityError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise CarryFeasibilityError(f"{name} must be a finite decimal")
    return result


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CarryFeasibilityError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class EvidenceReceipt:
    """Metadata and digests for bytes captured outside this no-network gate."""

    kind: EvidenceKind
    scope: str
    source_locator: str
    authority: EvidenceAuthority
    commercial_use_status: CommercialUseStatus
    request_started_at_utc: str
    response_received_at_utc: str
    source_published_at_utc: str
    source_effective_at_utc: str
    request_side_cutoff_utc: str | None
    server_time_utc: str | None
    capture_tool_version: str
    reviewer_attestation_id: str
    raw_bytes_size: int
    raw_bytes_sha256: str
    transport_receipt_sha256: str
    reviewer_attestation_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise CarryFeasibilityError("kind must be an EvidenceKind")
        if not isinstance(self.authority, EvidenceAuthority):
            raise CarryFeasibilityError("authority must be an EvidenceAuthority")
        if not isinstance(self.commercial_use_status, CommercialUseStatus):
            raise CarryFeasibilityError("commercial_use_status must be a CommercialUseStatus")
        for name in (
            "scope",
            "source_locator",
            "capture_tool_version",
            "reviewer_attestation_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise CarryFeasibilityError(f"{name} is required")
        if type(self.raw_bytes_size) is not int or self.raw_bytes_size <= 0:
            raise CarryFeasibilityError("raw_bytes_size must be a positive integer")
        for name in (
            "raw_bytes_sha256",
            "transport_receipt_sha256",
            "reviewer_attestation_sha256",
        ):
            _sha256(name, getattr(self, name))
        for name in (
            "request_started_at_utc",
            "response_received_at_utc",
            "source_published_at_utc",
            "source_effective_at_utc",
        ):
            _utc(getattr(self, name))
        if self.request_side_cutoff_utc is not None:
            _utc(self.request_side_cutoff_utc)
        if self.server_time_utc is not None:
            _utc(self.server_time_utc)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["authority"] = self.authority.value
        payload["commercial_use_status"] = self.commercial_use_status.value
        return payload


@dataclass(frozen=True)
class EvidenceArtifact:
    """Receipt plus the exact offline bytes whose hashes it declares.

    The raw bytes are only used for verification and are never emitted by a
    verdict.  They may contain account metadata and must not be committed.
    """

    receipt: EvidenceReceipt
    raw_bytes: bytes = field(repr=False)
    transport_receipt_bytes: bytes = field(repr=False)
    reviewer_attestation_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, EvidenceReceipt):
            raise CarryFeasibilityError("receipt must be an EvidenceReceipt")
        for name in (
            "raw_bytes",
            "transport_receipt_bytes",
            "reviewer_attestation_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, bytes) or not value:
                raise CarryFeasibilityError(f"{name} must be non-empty bytes")
        if len(self.raw_bytes) != self.receipt.raw_bytes_size:
            raise CarryFeasibilityError("raw byte size does not match receipt")
        checks = (
            (self.raw_bytes, self.receipt.raw_bytes_sha256, "raw bytes"),
            (
                self.transport_receipt_bytes,
                self.receipt.transport_receipt_sha256,
                "transport receipt",
            ),
            (
                self.reviewer_attestation_bytes,
                self.receipt.reviewer_attestation_sha256,
                "reviewer attestation",
            ),
        )
        for payload, expected, label in checks:
            if sha256_of_bytes(payload) != expected:
                raise CarryFeasibilityError(f"{label} digest does not match receipt")

    @classmethod
    def from_bytes(
        cls,
        *,
        kind: EvidenceKind,
        scope: str,
        source_locator: str,
        authority: EvidenceAuthority,
        commercial_use_status: CommercialUseStatus,
        request_started_at_utc: str,
        response_received_at_utc: str,
        source_published_at_utc: str,
        source_effective_at_utc: str,
        request_side_cutoff_utc: str | None,
        server_time_utc: str | None,
        capture_tool_version: str,
        reviewer_attestation_id: str,
        raw_bytes: bytes,
        transport_receipt_bytes: bytes,
        reviewer_attestation_bytes: bytes,
    ) -> EvidenceArtifact:
        receipt = EvidenceReceipt(
            kind=kind,
            scope=scope,
            source_locator=source_locator,
            authority=authority,
            commercial_use_status=commercial_use_status,
            request_started_at_utc=request_started_at_utc,
            response_received_at_utc=response_received_at_utc,
            source_published_at_utc=source_published_at_utc,
            source_effective_at_utc=source_effective_at_utc,
            request_side_cutoff_utc=request_side_cutoff_utc,
            server_time_utc=server_time_utc,
            capture_tool_version=capture_tool_version,
            reviewer_attestation_id=reviewer_attestation_id,
            raw_bytes_size=len(raw_bytes),
            raw_bytes_sha256=sha256_of_bytes(raw_bytes),
            transport_receipt_sha256=sha256_of_bytes(transport_receipt_bytes),
            reviewer_attestation_sha256=sha256_of_bytes(reviewer_attestation_bytes),
        )
        return cls(
            receipt=receipt,
            raw_bytes=raw_bytes,
            transport_receipt_bytes=transport_receipt_bytes,
            reviewer_attestation_bytes=reviewer_attestation_bytes,
        )


@dataclass(frozen=True)
class VenueAccountAssessment:
    venue: str
    user_country_code: str
    contracting_legal_entity: str | None
    country_product_review: ReviewOutcome
    kyc_status: KYCStatus
    spot_enabled: bool | None
    linear_perpetual_enabled: bool | None
    isolated_margin_available: bool | None
    api_read_only: bool | None
    api_trade_permission: bool | None
    api_withdraw_permission: bool | None
    api_transfer_permission: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.country_product_review, ReviewOutcome):
            raise CarryFeasibilityError("country_product_review must be ReviewOutcome")
        if not isinstance(self.kyc_status, KYCStatus):
            raise CarryFeasibilityError("kyc_status must be KYCStatus")
        for name in (
            "spot_enabled",
            "linear_perpetual_enabled",
            "isolated_margin_available",
            "api_read_only",
            "api_trade_permission",
            "api_withdraw_permission",
            "api_transfer_permission",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise CarryFeasibilityError(f"{name} must be bool or None")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["country_product_review"] = self.country_product_review.value
        payload["kyc_status"] = self.kyc_status.value
        return payload


@dataclass(frozen=True)
class InstrumentPairAssessment:
    venue: str
    spot_symbol: str
    spot_product: str
    spot_base_asset: str
    spot_quote_asset: str
    spot_status: str
    perp_symbol: str
    perp_product: str
    perp_contract_type: str
    perp_base_asset: str
    perp_quote_asset: str
    perp_settlement_asset: str
    perp_status: str
    perp_is_prelisting: bool
    funding_interval_minutes: int

    def __post_init__(self) -> None:
        if type(self.perp_is_prelisting) is not bool:
            raise CarryFeasibilityError("perp_is_prelisting must be bool")
        if type(self.funding_interval_minutes) is not int:
            raise CarryFeasibilityError("funding_interval_minutes must be int")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapitalIntent:
    budget_usd: str = "200"
    perp_leverage: str = "1"
    liquidity_reserve_fraction: str = "0.20"
    spot_fully_funded: bool = True
    borrow_used: bool = False
    margin_mode: str = "ISOLATED"

    def __post_init__(self) -> None:
        for name in ("budget_usd", "perp_leverage", "liquidity_reserve_fraction"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise CarryFeasibilityError(f"{name} must be decimal text")
            _decimal(name, value)
        if type(self.spot_fully_funded) is not bool or type(self.borrow_used) is not bool:
            raise CarryFeasibilityError("capital funding/borrow flags must be bool")
        if not isinstance(self.margin_mode, str):
            raise CarryFeasibilityError("margin_mode must be text")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PointInTimeTerms:
    """Only technical sizing/risk inputs; no expected-return field exists."""

    observed_at_utc: str
    quote_usdt_per_usd: str
    spot_mid_usdt_per_btc: str
    perp_mark_usdt_per_btc: str
    perp_index_usdt_per_btc: str
    spot_qty_step_btc: str
    perp_qty_step_btc: str
    spot_min_notional_usdt: str
    perp_min_notional_usdt: str
    spot_executable_depth_usdt: str
    perp_executable_depth_usdt: str
    spot_account_fee_rate: str
    perp_account_fee_rate: str
    spot_p95_exit_friction_rate: str
    perp_p95_exit_friction_rate: str
    liquidation_distance_fraction: str
    settled_funding_rows_observed: int
    basis_snapshots_observed: int
    borrow_balance_usdt: str

    def __post_init__(self) -> None:
        _utc(self.observed_at_utc)
        decimal_fields = (
            "quote_usdt_per_usd",
            "spot_mid_usdt_per_btc",
            "perp_mark_usdt_per_btc",
            "perp_index_usdt_per_btc",
            "spot_qty_step_btc",
            "perp_qty_step_btc",
            "spot_min_notional_usdt",
            "perp_min_notional_usdt",
            "spot_executable_depth_usdt",
            "perp_executable_depth_usdt",
            "spot_account_fee_rate",
            "perp_account_fee_rate",
            "spot_p95_exit_friction_rate",
            "perp_p95_exit_friction_rate",
            "liquidation_distance_fraction",
            "borrow_balance_usdt",
        )
        for name in decimal_fields:
            value = getattr(self, name)
            if not isinstance(value, str):
                raise CarryFeasibilityError(f"{name} must be decimal text")
            _decimal(name, value)
        if type(self.settled_funding_rows_observed) is not int:
            raise CarryFeasibilityError("settled_funding_rows_observed must be an integer")
        if type(self.basis_snapshots_observed) is not int:
            raise CarryFeasibilityError("basis_snapshots_observed must be an integer")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationalStressAssessment:
    transfer_path_stress: CheckStatus
    withdrawal_path_stress: CheckStatus
    withdrawal_freeze_runbook: CheckStatus
    emergency_close_without_transfer: CheckStatus
    tax_review: CheckStatus
    counterparty_review: ReviewOutcome
    maximum_venue_balance_usd: str
    full_custody_loss_scenario_acknowledged: bool

    def __post_init__(self) -> None:
        for name in (
            "transfer_path_stress",
            "withdrawal_path_stress",
            "withdrawal_freeze_runbook",
            "emergency_close_without_transfer",
            "tax_review",
        ):
            if not isinstance(getattr(self, name), CheckStatus):
                raise CarryFeasibilityError(f"{name} must be CheckStatus")
        if not isinstance(self.counterparty_review, ReviewOutcome):
            raise CarryFeasibilityError("counterparty_review must be ReviewOutcome")
        if not isinstance(self.maximum_venue_balance_usd, str):
            raise CarryFeasibilityError("maximum_venue_balance_usd must be decimal text")
        _decimal("maximum_venue_balance_usd", self.maximum_venue_balance_usd)
        if type(self.full_custody_loss_scenario_acknowledged) is not bool:
            raise CarryFeasibilityError("full_custody_loss_scenario_acknowledged must be bool")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["transfer_path_stress"] = self.transfer_path_stress.value
        payload["withdrawal_path_stress"] = self.withdrawal_path_stress.value
        payload["withdrawal_freeze_runbook"] = self.withdrawal_freeze_runbook.value
        payload["emergency_close_without_transfer"] = self.emergency_close_without_transfer.value
        payload["tax_review"] = self.tax_review.value
        payload["counterparty_review"] = self.counterparty_review.value
        return payload


@dataclass(frozen=True)
class CarryFeasibilitySubmission:
    decision_at_utc: str
    capital: CapitalIntent = field(default_factory=CapitalIntent)
    venue_account: VenueAccountAssessment | None = None
    instrument_pair: InstrumentPairAssessment | None = None
    point_in_time_terms: PointInTimeTerms | None = None
    operations: OperationalStressAssessment | None = None
    evidence_artifacts: tuple[EvidenceArtifact, ...] = ()

    def __post_init__(self) -> None:
        _utc(self.decision_at_utc)
        if not isinstance(self.capital, CapitalIntent):
            raise CarryFeasibilityError("capital must be a CapitalIntent")
        optional_types = (
            ("venue_account", self.venue_account, VenueAccountAssessment),
            ("instrument_pair", self.instrument_pair, InstrumentPairAssessment),
            ("point_in_time_terms", self.point_in_time_terms, PointInTimeTerms),
            ("operations", self.operations, OperationalStressAssessment),
        )
        for name, value, expected in optional_types:
            if value is not None and not isinstance(value, expected):
                raise CarryFeasibilityError(f"{name} must be {expected.__name__} or None")
        if not isinstance(self.evidence_artifacts, tuple) or any(
            not isinstance(item, EvidenceArtifact) for item in self.evidence_artifacts
        ):
            raise CarryFeasibilityError("evidence_artifacts must be an immutable typed tuple")


@dataclass(frozen=True)
class FeasibilityBlocker:
    code: str
    severity: BlockerSeverity
    count: int = 1

    def __post_init__(self) -> None:
        if _BLOCKER_CODE_RE.fullmatch(self.code) is None:
            raise CarryFeasibilityError("blocker code must be canonical uppercase text")
        if not isinstance(self.severity, BlockerSeverity):
            raise CarryFeasibilityError("severity must be BlockerSeverity")
        if type(self.count) is not int or self.count <= 0:
            raise CarryFeasibilityError("blocker count must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity.value, "count": self.count}


@dataclass(frozen=True)
class CapitalEnvelope:
    budget_usd: str
    perp_leverage: str
    reserve_fraction: str
    capital_only_matched_notional_usd_per_leg: str
    matched_quantity_btc: str | None
    spot_notional_usdt: str | None
    perp_notional_usdt: str | None
    perp_initial_margin_usdt: str | None
    remaining_contingency_usdt: str | None
    four_fill_contingency_requirement_usdt: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_capital_envelope(capital: CapitalEnvelope) -> None:
    required = {
        "budget_usd": _decimal("capital.budget_usd", capital.budget_usd),
        "perp_leverage": _decimal("capital.perp_leverage", capital.perp_leverage),
        "reserve_fraction": _decimal("capital.reserve_fraction", capital.reserve_fraction),
        "capital_only_matched_notional_usd_per_leg": _decimal(
            "capital.capital_only_matched_notional_usd_per_leg",
            capital.capital_only_matched_notional_usd_per_leg,
        ),
    }
    if required["budget_usd"] <= 0 or required["perp_leverage"] <= 0:
        raise CarryFeasibilityError("capital budget and leverage must be positive")
    if not Decimal("0") <= required["reserve_fraction"] < Decimal("1"):
        raise CarryFeasibilityError("capital reserve_fraction must be in [0, 1)")
    if required["capital_only_matched_notional_usd_per_leg"] < 0:
        raise CarryFeasibilityError("capital-only matched notional cannot be negative")
    optional_names = (
        "matched_quantity_btc",
        "spot_notional_usdt",
        "perp_notional_usdt",
        "perp_initial_margin_usdt",
        "remaining_contingency_usdt",
        "four_fill_contingency_requirement_usdt",
    )
    present = tuple(getattr(capital, name) is not None for name in optional_names)
    if any(present) and not all(present):
        raise CarryFeasibilityError("sized capital fields must be all present or all absent")
    if all(present):
        for name in optional_names:
            raw = getattr(capital, name)
            assert raw is not None
            value = _decimal(f"capital.{name}", raw)
            if name == "four_fill_contingency_requirement_usdt":
                if value < 0:
                    raise CarryFeasibilityError(f"capital.{name} cannot be negative")
            elif value <= 0:
                raise CarryFeasibilityError(f"capital.{name} must be positive")


@dataclass(frozen=True)
class CarryFeasibilityVerdict:
    status: CarryFeasibilityStatus
    decision_at_utc: str
    venue: str
    country_code: str
    capital: CapitalEnvelope
    blockers: tuple[FeasibilityBlocker, ...]
    selected_evidence_sha256: str
    policy_sha256: str
    schema_version: int = SCHEMA_VERSION
    research_only: bool = field(default=True, init=False)
    separate_from_gate4_spot: bool = field(default=True, init=False)
    experiment_spec_authorized: bool = field(default=False, init=False)
    pnl_evaluation_authorized: bool = field(default=False, init=False)
    holdout_access_authorized: bool = field(default=False, init=False)
    promotion_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)
    derivatives_execution_authorized: bool = field(default=False, init=False)
    real_money_authorized: bool = field(default=False, init=False)
    money_movement_authorized: bool = field(default=False, init=False)
    profitability_evidence: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise CarryFeasibilityError("schema_version differs from frozen v1 policy")
        if not isinstance(self.status, CarryFeasibilityStatus):
            raise CarryFeasibilityError("status must be CarryFeasibilityStatus")
        _utc(self.decision_at_utc)
        if self.venue != SEALED_VENUE or self.country_code != SEALED_COUNTRY:
            raise CarryFeasibilityError("venue/country differ from frozen v1 policy")
        if not isinstance(self.capital, CapitalEnvelope):
            raise CarryFeasibilityError("capital must be a CapitalEnvelope")
        _validate_capital_envelope(self.capital)
        if not isinstance(self.blockers, tuple) or any(
            not isinstance(row, FeasibilityBlocker) for row in self.blockers
        ):
            raise CarryFeasibilityError("blockers must be an immutable typed tuple")
        expected = tuple(sorted(self.blockers, key=lambda row: (row.severity.value, row.code)))
        if self.blockers != expected:
            raise CarryFeasibilityError("blockers must have canonical order")
        keys = tuple((row.severity, row.code) for row in self.blockers)
        if len(keys) != len(set(keys)):
            raise CarryFeasibilityError("duplicate blockers must be combined")
        _sha256("selected_evidence_sha256", self.selected_evidence_sha256)
        _sha256("policy_sha256", self.policy_sha256)
        safety_flags = (
            self.experiment_spec_authorized,
            self.pnl_evaluation_authorized,
            self.holdout_access_authorized,
            self.promotion_authorized,
            self.network_access_authorized,
            self.derivatives_execution_authorized,
            self.real_money_authorized,
            self.money_movement_authorized,
            self.profitability_evidence,
        )
        if any(safety_flags):
            raise CarryFeasibilityError("a feasibility verdict cannot authorize downstream use")
        has_hard = any(row.severity is BlockerSeverity.HARD for row in self.blockers)
        if self.status is CarryFeasibilityStatus.FEASIBLE_FOR_DEVELOPMENT_COLLECTION:
            raise CarryFeasibilityError(
                "schema v1 cannot emit FEASIBLE_FOR_DEVELOPMENT_COLLECTION until "
                "trusted attestation and content-binding parsers exist"
            )
        if not self.blockers:
            raise CarryFeasibilityError("a non-feasible verdict requires blockers")
        if self.status is CarryFeasibilityStatus.NO_GO and not has_hard:
            raise CarryFeasibilityError("NO_GO requires at least one HARD blocker")
        if self.status is CarryFeasibilityStatus.INSUFFICIENT and has_hard:
            raise CarryFeasibilityError("INSUFFICIENT cannot contain a HARD blocker")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "decision_at_utc": self.decision_at_utc,
            "venue": self.venue,
            "country_code": self.country_code,
            "capital": self.capital.to_dict(),
            "blockers": [row.to_dict() for row in self.blockers],
            "selected_evidence_sha256": self.selected_evidence_sha256,
            "policy_sha256": self.policy_sha256,
            "research_only": self.research_only,
            "separate_from_gate4_spot": self.separate_from_gate4_spot,
            "experiment_spec_authorized": self.experiment_spec_authorized,
            "pnl_evaluation_authorized": self.pnl_evaluation_authorized,
            "holdout_access_authorized": self.holdout_access_authorized,
            "promotion_authorized": self.promotion_authorized,
            "network_access_authorized": self.network_access_authorized,
            "derivatives_execution_authorized": self.derivatives_execution_authorized,
            "real_money_authorized": self.real_money_authorized,
            "money_movement_authorized": self.money_movement_authorized,
            "profitability_evidence": self.profitability_evidence,
        }

    def report_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict()))


def expected_evidence_scope(kind: EvidenceKind) -> str:
    """Frozen scope for each required byte receipt."""

    scopes = {
        EvidenceKind.VENUE_TERMS: "bybit:contracting-entity:terms",
        EvidenceKind.COUNTRY_PRODUCT_ELIGIBILITY: "bybit:MX:spot+linear-perpetual",
        EvidenceKind.KYC_ACCOUNT_CAPABILITIES: "bybit:account:spot+linear-perpetual",
        EvidenceKind.SPOT_INSTRUMENT: "bybit:spot:BTCUSDT",
        EvidenceKind.PERP_INSTRUMENT: "bybit:linear:BTCUSDT",
        EvidenceKind.ACCOUNT_FEE_SPOT: "bybit:account-fee:spot:BTCUSDT",
        EvidenceKind.ACCOUNT_FEE_PERP: "bybit:account-fee:linear:BTCUSDT",
        EvidenceKind.FUNDING_HISTORY_SCHEMA: "bybit:funding:linear:BTCUSDT",
        EvidenceKind.BASIS_SERIES_SCHEMA: "bybit:basis:spot+mark+index:BTCUSDT",
        EvidenceKind.SPOT_ORDER_BOOK: "bybit:orderbook:spot:BTCUSDT",
        EvidenceKind.PERP_ORDER_BOOK: "bybit:orderbook:linear:BTCUSDT",
        EvidenceKind.SPREAD_IMPACT_MODEL: "bybit:spread-impact:spot+linear:BTCUSDT",
        EvidenceKind.BORROW_COLLATERAL_TERMS: "bybit:borrow-collateral:USDT",
        EvidenceKind.LIQUIDATION_RISK_TERMS: "bybit:isolated-liquidation:linear:BTCUSDT",
        EvidenceKind.FX_USDT_USD: "USDT:USD",
        EvidenceKind.MX_TAX_TREATMENT: "MX:BTC-USDT:spot+linear-perpetual",
        EvidenceKind.TRANSFER_STRESS: "bybit:offline-transfer-stress:USDT",
        EvidenceKind.WITHDRAWAL_STRESS: "bybit:offline-withdrawal-freeze-stress:USDT",
        EvidenceKind.COUNTERPARTY_RISK: "bybit:counterparty-risk:200USD",
    }
    return scopes[kind]


def _policy_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "venue": SEALED_VENUE,
        "country": SEALED_COUNTRY,
        "base_asset": SEALED_BASE_ASSET,
        "quote_asset": SEALED_QUOTE_ASSET,
        "budget_usd": _decimal_text(SEALED_BUDGET_USD),
        "max_perp_leverage": _decimal_text(MAX_PERP_LEVERAGE),
        "min_liquidity_reserve_fraction": _decimal_text(MIN_LIQUIDITY_RESERVE_FRACTION),
        "min_liquidation_distance_fraction": _decimal_text(MIN_LIQUIDATION_DISTANCE_FRACTION),
        "min_depth_multiple": _decimal_text(MIN_DEPTH_MULTIPLE),
        "max_abs_fx_depeg_fraction": _decimal_text(MAX_ABS_FX_DEPEG_FRACTION),
        "max_abs_snapshot_basis_fraction": _decimal_text(MAX_ABS_SNAPSHOT_BASIS_FRACTION),
        "required_evidence_kinds": [kind.value for kind in REQUIRED_EVIDENCE_KINDS],
        "outcomes": [status.value for status in CarryFeasibilityStatus],
        "v1_positive_state_implemented": False,
        "v1_immutable_missing_controls": [
            "EXTERNAL_ATTESTATION_TRUST_ROOT_NOT_IMPLEMENTED",
            "EVIDENCE_CONTENT_BINDING_PARSERS_NOT_IMPLEMENTED",
            "ACCOUNT_MANUAL_REVIEW_AUTHENTICITY_NOT_IMPLEMENTED",
        ],
        "no_pnl": True,
        "no_network": True,
        "no_execution": True,
    }


def carry_feasibility_policy_sha256() -> str:
    return sha256_of_text(canonical_dumps(_policy_payload()))


def _common_decimal_step(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        raise CarryFeasibilityError("quantity steps must be positive")
    left_exponent = left.as_tuple().exponent
    right_exponent = right.as_tuple().exponent
    if not isinstance(left_exponent, int) or not isinstance(right_exponent, int):
        raise CarryFeasibilityError("quantity steps must be finite decimals")
    scale = max(-left_exponent, -right_exponent, 0)
    multiplier = 10**scale
    left_int = int(left * multiplier)
    right_int = int(right * multiplier)
    if left_int <= 0 or right_int <= 0:
        raise CarryFeasibilityError("quantity steps cannot be represented exactly")
    return Decimal(math.lcm(left_int, right_int)) / Decimal(multiplier)


def _status_blockers(
    counter: Counter[tuple[BlockerSeverity, str]],
) -> tuple[FeasibilityBlocker, ...]:
    rows = (
        FeasibilityBlocker(code=code, severity=severity, count=count)
        for (severity, code), count in counter.items()
    )
    return tuple(sorted(rows, key=lambda row: (row.severity.value, row.code)))


def _add(
    blockers: Counter[tuple[BlockerSeverity, str]],
    severity: BlockerSeverity,
    code: str,
) -> None:
    blockers[(severity, code)] += 1


def _source_locator_is_accepted(receipt: EvidenceReceipt) -> bool:
    """Constrain authority labels to a sealed locator class.

    This is not cryptographic proof of origin. The transport receipt and
    independent attestation remain mandatory, but a caller also cannot label
    an arbitrary host as venue-primary or primary FX evidence.
    """

    if receipt.authority is EvidenceAuthority.VENUE_PRIMARY:
        parsed = urlparse(receipt.source_locator)
        return parsed.scheme == "https" and parsed.hostname in {
            "api.bybit.com",
            "www.bybit.com",
            "bybit-exchange.github.io",
        }
    if receipt.authority is EvidenceAuthority.PRIMARY_FX_REFERENCE:
        parsed = urlparse(receipt.source_locator)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "api.exchange.coinbase.com"
            and "/products/USDT-USD/" in parsed.path
        )
    if receipt.authority in {
        EvidenceAuthority.INDEPENDENT_MX_LEGAL_REVIEW,
        EvidenceAuthority.INDEPENDENT_MX_TAX_REVIEW,
        EvidenceAuthority.INDEPENDENT_COUNTERPARTY_REVIEW,
    }:
        return receipt.source_locator.startswith("review://independent/")
    if receipt.authority is EvidenceAuthority.OPERATOR_OFFLINE_STRESS:
        return receipt.source_locator.startswith("artifact://offline/")
    return False


def _select_causal_evidence(
    artifacts: tuple[EvidenceArtifact, ...],
    *,
    decision: datetime,
    blockers: Counter[tuple[BlockerSeverity, str]],
) -> dict[EvidenceKind, EvidenceReceipt]:
    causal: list[EvidenceReceipt] = []
    for artifact in artifacts:
        receipt = artifact.receipt
        received = _utc(receipt.response_received_at_utc)
        # Appending an observation captured after the cutoff cannot change any
        # byte of a past verdict.
        if received > decision:
            continue
        requested = _utc(receipt.request_started_at_utc)
        published = _utc(receipt.source_published_at_utc)
        effective = _utc(receipt.source_effective_at_utc)
        if requested > received:
            _add(blockers, BlockerSeverity.HARD, "RECEIPT_REQUEST_AFTER_RESPONSE")
            continue
        if published > decision or effective > decision:
            _add(blockers, BlockerSeverity.MISSING, "RECEIPT_NOT_AVAILABLE_AT_CUTOFF")
            continue
        if receipt.kind in _DYNAMIC_EVIDENCE_KINDS:
            if receipt.request_side_cutoff_utc is None:
                _add(blockers, BlockerSeverity.MISSING, "REQUEST_SIDE_CUTOFF_MISSING")
                continue
            requested_cutoff = _utc(receipt.request_side_cutoff_utc)
            if requested_cutoff > decision:
                _add(blockers, BlockerSeverity.HARD, "REQUEST_SIDE_CUTOFF_AFTER_DECISION")
                continue
            if requested_cutoff != decision:
                _add(blockers, BlockerSeverity.MISSING, "REQUEST_SIDE_CUTOFF_NOT_DECISION")
                continue
            if receipt.server_time_utc is None:
                _add(blockers, BlockerSeverity.MISSING, "VENUE_SERVER_TIME_MISSING")
                continue
            server_time = _utc(receipt.server_time_utc)
            if abs((server_time - received).total_seconds()) > MAX_SERVER_CLOCK_SKEW_SECONDS:
                _add(blockers, BlockerSeverity.MISSING, "VENUE_SERVER_CLOCK_SKEW")
                continue
        if receipt.scope != expected_evidence_scope(receipt.kind):
            _add(blockers, BlockerSeverity.HARD, "EVIDENCE_SCOPE_MISMATCH")
            continue
        if receipt.authority is not _EXPECTED_AUTHORITIES[receipt.kind]:
            _add(blockers, BlockerSeverity.MISSING, "EVIDENCE_AUTHORITY_NOT_ACCEPTED")
            continue
        if not _source_locator_is_accepted(receipt):
            _add(blockers, BlockerSeverity.MISSING, "EVIDENCE_SOURCE_LOCATOR_NOT_ACCEPTED")
            continue
        if receipt.commercial_use_status in {
            CommercialUseStatus.PROHIBITED,
            CommercialUseStatus.RESEARCH_ONLY,
        }:
            _add(blockers, BlockerSeverity.HARD, "COMMERCIAL_USE_NOT_PERMITTED")
            continue
        if receipt.commercial_use_status is CommercialUseStatus.UNKNOWN:
            _add(blockers, BlockerSeverity.MISSING, "COMMERCIAL_USE_STATUS_UNKNOWN")
            continue
        if (
            receipt.kind not in _MANUAL_EVIDENCE_KINDS
            and receipt.commercial_use_status is CommercialUseStatus.NOT_APPLICABLE_REVIEWED
        ):
            _add(blockers, BlockerSeverity.MISSING, "DATA_LICENSE_NOT_CONFIRMED")
            continue
        causal.append(receipt)

    by_kind: dict[EvidenceKind, list[EvidenceReceipt]] = {}
    for receipt in causal:
        by_kind.setdefault(receipt.kind, []).append(receipt)

    selected: dict[EvidenceKind, EvidenceReceipt] = {}
    for kind, rows in by_kind.items():
        rows.sort(
            key=lambda row: (
                _utc(row.response_received_at_utc),
                row.raw_bytes_sha256,
            )
        )
        latest_time = _utc(rows[-1].response_received_at_utc)
        latest = [row for row in rows if _utc(row.response_received_at_utc) == latest_time]
        if len({row.raw_bytes_sha256 for row in latest}) > 1:
            _add(blockers, BlockerSeverity.HARD, "CONFLICTING_RECEIPTS_AT_SAME_TIME")
            continue
        selected[kind] = latest[-1]

    for kind in REQUIRED_EVIDENCE_KINDS:
        if kind not in selected:
            _add(blockers, BlockerSeverity.MISSING, f"MISSING_EVIDENCE_{kind.value}")
    return selected


def _assess_venue_account(
    assessment: VenueAccountAssessment | None,
    blockers: Counter[tuple[BlockerSeverity, str]],
) -> None:
    if assessment is None:
        _add(blockers, BlockerSeverity.MISSING, "VENUE_ACCOUNT_ASSESSMENT_MISSING")
        return
    if assessment.venue.strip().lower() != SEALED_VENUE:
        _add(blockers, BlockerSeverity.HARD, "VENUE_DIFFERS_FROM_SEALED_POLICY")
    if assessment.user_country_code.strip().upper() != SEALED_COUNTRY:
        _add(blockers, BlockerSeverity.HARD, "COUNTRY_DIFFERS_FROM_SEALED_POLICY")
    if assessment.country_product_review is ReviewOutcome.REJECTED:
        _add(blockers, BlockerSeverity.HARD, "DERIVATIVES_NOT_LEGALLY_AVAILABLE")
    elif assessment.country_product_review is ReviewOutcome.UNKNOWN:
        _add(blockers, BlockerSeverity.MISSING, "LEGAL_PRODUCT_REVIEW_UNKNOWN")
    if assessment.kyc_status is KYCStatus.REJECTED:
        _add(blockers, BlockerSeverity.HARD, "KYC_REJECTED")
    elif assessment.kyc_status is KYCStatus.UNKNOWN:
        _add(blockers, BlockerSeverity.MISSING, "KYC_NOT_CONFIRMED")
    if not assessment.contracting_legal_entity:
        _add(blockers, BlockerSeverity.MISSING, "CONTRACTING_ENTITY_NOT_IDENTIFIED")
    for value, missing_code, hard_code in (
        (assessment.spot_enabled, "SPOT_ENABLEMENT_UNKNOWN", "SPOT_PRODUCT_DISABLED"),
        (
            assessment.linear_perpetual_enabled,
            "PERP_ENABLEMENT_UNKNOWN",
            "PERP_PRODUCT_DISABLED",
        ),
        (
            assessment.isolated_margin_available,
            "ISOLATED_MARGIN_UNKNOWN",
            "ISOLATED_MARGIN_UNAVAILABLE",
        ),
        (assessment.api_read_only, "READ_ONLY_API_UNKNOWN", "READ_ONLY_API_UNAVAILABLE"),
    ):
        if value is None:
            _add(blockers, BlockerSeverity.MISSING, missing_code)
        elif value is False:
            _add(blockers, BlockerSeverity.HARD, hard_code)
    for value, name in (
        (assessment.api_trade_permission, "TRADE"),
        (assessment.api_withdraw_permission, "WITHDRAW"),
        (assessment.api_transfer_permission, "TRANSFER"),
    ):
        if value is None:
            _add(blockers, BlockerSeverity.MISSING, f"API_{name}_PERMISSION_UNKNOWN")
        elif value is True:
            _add(blockers, BlockerSeverity.HARD, f"API_{name}_PERMISSION_MUST_BE_DISABLED")


def _assess_instrument_pair(
    pair: InstrumentPairAssessment | None,
    blockers: Counter[tuple[BlockerSeverity, str]],
) -> None:
    if pair is None:
        _add(blockers, BlockerSeverity.MISSING, "INSTRUMENT_PAIR_ASSESSMENT_MISSING")
        return
    exact = (
        pair.venue.strip().lower() == SEALED_VENUE
        and pair.spot_symbol.strip().upper() == "BTCUSDT"
        and pair.spot_product.strip().lower() == "spot"
        and pair.spot_base_asset.strip().upper() == SEALED_BASE_ASSET
        and pair.spot_quote_asset.strip().upper() == SEALED_QUOTE_ASSET
        and pair.perp_symbol.strip().upper() == "BTCUSDT"
        and pair.perp_product.strip().lower() == "linear"
        and pair.perp_contract_type.strip().lower() == "linear_perpetual"
        and pair.perp_base_asset.strip().upper() == SEALED_BASE_ASSET
        and pair.perp_quote_asset.strip().upper() == SEALED_QUOTE_ASSET
        and pair.perp_settlement_asset.strip().upper() == SEALED_QUOTE_ASSET
    )
    if not exact:
        _add(blockers, BlockerSeverity.HARD, "SPOT_PERP_IDENTITY_MISMATCH")
    if pair.spot_status.strip().upper() != "TRADING":
        _add(blockers, BlockerSeverity.HARD, "SPOT_NOT_TRADING")
    if pair.perp_status.strip().upper() != "TRADING":
        _add(blockers, BlockerSeverity.HARD, "PERP_NOT_TRADING")
    if pair.perp_is_prelisting:
        _add(blockers, BlockerSeverity.HARD, "PRELISTING_PERP_FORBIDDEN")
    if type(pair.funding_interval_minutes) is not int or pair.funding_interval_minutes <= 0:
        _add(blockers, BlockerSeverity.HARD, "FUNDING_INTERVAL_INVALID")


def _capital_only_envelope(capital: CapitalIntent) -> CapitalEnvelope:
    budget = _decimal("budget_usd", capital.budget_usd)
    leverage = _decimal("perp_leverage", capital.perp_leverage)
    reserve_fraction = _decimal("liquidity_reserve_fraction", capital.liquidity_reserve_fraction)
    if leverage <= 0:
        raise CarryFeasibilityError("perp_leverage must be positive")
    available = budget * (Decimal("1") - reserve_fraction)
    per_leg = available / (Decimal("1") + Decimal("1") / leverage)
    return CapitalEnvelope(
        budget_usd=_decimal_text(budget),
        perp_leverage=_decimal_text(leverage),
        reserve_fraction=_decimal_text(reserve_fraction),
        capital_only_matched_notional_usd_per_leg=_decimal_text(per_leg),
        matched_quantity_btc=None,
        spot_notional_usdt=None,
        perp_notional_usdt=None,
        perp_initial_margin_usdt=None,
        remaining_contingency_usdt=None,
        four_fill_contingency_requirement_usdt=None,
    )


def _assess_capital_and_terms(
    capital: CapitalIntent,
    terms: PointInTimeTerms | None,
    *,
    decision: datetime,
    blockers: Counter[tuple[BlockerSeverity, str]],
) -> CapitalEnvelope:
    envelope = _capital_only_envelope(capital)
    budget = _decimal("budget_usd", capital.budget_usd)
    leverage = _decimal("perp_leverage", capital.perp_leverage)
    reserve_fraction = _decimal("liquidity_reserve_fraction", capital.liquidity_reserve_fraction)
    if budget != SEALED_BUDGET_USD:
        _add(blockers, BlockerSeverity.HARD, "BUDGET_DIFFERS_FROM_200_USD_POLICY")
    if leverage > MAX_PERP_LEVERAGE:
        _add(blockers, BlockerSeverity.HARD, "PERP_LEVERAGE_ABOVE_1X")
    if not Decimal("0") <= reserve_fraction < Decimal("1"):
        _add(blockers, BlockerSeverity.HARD, "RESERVE_FRACTION_INVALID")
        return envelope
    if reserve_fraction < MIN_LIQUIDITY_RESERVE_FRACTION:
        _add(blockers, BlockerSeverity.HARD, "LIQUIDITY_RESERVE_BELOW_POLICY")
    if not capital.spot_fully_funded or capital.borrow_used:
        _add(blockers, BlockerSeverity.HARD, "BORROWED_OR_UNFUNDED_SPOT_FORBIDDEN")
    if capital.margin_mode.strip().upper() != "ISOLATED":
        _add(blockers, BlockerSeverity.HARD, "ISOLATED_MARGIN_REQUIRED")
    if terms is None:
        _add(blockers, BlockerSeverity.MISSING, "POINT_IN_TIME_TERMS_MISSING")
        return envelope

    observed = _utc(terms.observed_at_utc)
    age_seconds = (decision - observed).total_seconds()
    if age_seconds < 0:
        _add(blockers, BlockerSeverity.HARD, "TERMS_OBSERVED_AFTER_DECISION")
    elif age_seconds > MAX_DYNAMIC_EVIDENCE_STALENESS_SECONDS:
        _add(blockers, BlockerSeverity.MISSING, "POINT_IN_TIME_TERMS_STALE")

    try:
        fx = _decimal("quote_usdt_per_usd", terms.quote_usdt_per_usd)
        spot_price = _decimal("spot_mid_usdt_per_btc", terms.spot_mid_usdt_per_btc)
        perp_mark = _decimal("perp_mark_usdt_per_btc", terms.perp_mark_usdt_per_btc)
        perp_index = _decimal("perp_index_usdt_per_btc", terms.perp_index_usdt_per_btc)
        spot_step = _decimal("spot_qty_step_btc", terms.spot_qty_step_btc)
        perp_step = _decimal("perp_qty_step_btc", terms.perp_qty_step_btc)
        spot_min = _decimal("spot_min_notional_usdt", terms.spot_min_notional_usdt)
        perp_min = _decimal("perp_min_notional_usdt", terms.perp_min_notional_usdt)
        spot_depth = _decimal("spot_executable_depth_usdt", terms.spot_executable_depth_usdt)
        perp_depth = _decimal("perp_executable_depth_usdt", terms.perp_executable_depth_usdt)
        spot_fee = _decimal("spot_account_fee_rate", terms.spot_account_fee_rate)
        perp_fee = _decimal("perp_account_fee_rate", terms.perp_account_fee_rate)
        spot_exit = _decimal("spot_p95_exit_friction_rate", terms.spot_p95_exit_friction_rate)
        perp_exit = _decimal("perp_p95_exit_friction_rate", terms.perp_p95_exit_friction_rate)
        liquidation_distance = _decimal(
            "liquidation_distance_fraction", terms.liquidation_distance_fraction
        )
        borrow_balance = _decimal("borrow_balance_usdt", terms.borrow_balance_usdt)
    except CarryFeasibilityError:
        _add(blockers, BlockerSeverity.HARD, "POINT_IN_TIME_TERMS_MALFORMED")
        return envelope

    positive_values = (
        fx,
        spot_price,
        perp_mark,
        perp_index,
        spot_step,
        perp_step,
        spot_min,
        perp_min,
        spot_depth,
        perp_depth,
    )
    if any(value <= 0 for value in positive_values):
        _add(blockers, BlockerSeverity.HARD, "POINT_IN_TIME_TERMS_NON_POSITIVE")
        return envelope
    if any(value < 0 for value in (spot_fee, perp_fee, spot_exit, perp_exit, borrow_balance)):
        _add(blockers, BlockerSeverity.HARD, "COST_OR_BORROW_TERM_NEGATIVE")
        return envelope
    if any(value >= Decimal("1") for value in (spot_fee, perp_fee, spot_exit, perp_exit)):
        _add(blockers, BlockerSeverity.HARD, "COST_RATE_OUT_OF_RANGE")
        return envelope
    if borrow_balance != 0:
        _add(blockers, BlockerSeverity.HARD, "NONZERO_BORROW_BALANCE")
    if terms.settled_funding_rows_observed <= 0:
        _add(blockers, BlockerSeverity.MISSING, "SETTLED_FUNDING_SCHEMA_NOT_OBSERVED")
    if terms.basis_snapshots_observed <= 0:
        _add(blockers, BlockerSeverity.MISSING, "BASIS_SCHEMA_NOT_OBSERVED")
    if abs(fx - Decimal("1")) > MAX_ABS_FX_DEPEG_FRACTION:
        _add(blockers, BlockerSeverity.HARD, "USDT_USD_OUTSIDE_POLICY_BAND")
    spot_perp_basis = abs(perp_mark / spot_price - Decimal("1"))
    spot_index_basis = abs(perp_index / spot_price - Decimal("1"))
    if max(spot_perp_basis, spot_index_basis) > MAX_ABS_SNAPSHOT_BASIS_FRACTION:
        _add(blockers, BlockerSeverity.MISSING, "PRICE_IDENTITY_OR_STALENESS_UNRESOLVED")
    if liquidation_distance < MIN_LIQUIDATION_DISTANCE_FRACTION:
        _add(blockers, BlockerSeverity.HARD, "LIQUIDATION_BUFFER_BELOW_POLICY")

    budget_quote = budget * fx
    reserve_target = budget_quote * reserve_fraction
    allocatable = budget_quote - reserve_target
    quote_per_btc_capital = spot_price + perp_mark / leverage
    common_step = _common_decimal_step(spot_step, perp_step)
    raw_quantity = allocatable / quote_per_btc_capital
    step_count = (raw_quantity / common_step).to_integral_value(rounding=ROUND_DOWN)
    quantity = step_count * common_step
    if quantity <= 0:
        _add(blockers, BlockerSeverity.HARD, "BUDGET_CANNOT_PLACE_COMMON_QUANTITY_STEP")
        return envelope
    spot_notional = quantity * spot_price
    perp_notional = quantity * perp_mark
    perp_margin = perp_notional / leverage
    remaining = budget_quote - spot_notional - perp_margin
    four_fill_contingency = Decimal("2") * (
        spot_notional * (spot_fee + spot_exit) + perp_notional * (perp_fee + perp_exit)
    )
    if spot_notional < spot_min or perp_notional < perp_min:
        _add(blockers, BlockerSeverity.HARD, "BUDGET_BELOW_VENUE_MINIMUMS")
    if spot_depth < spot_notional * MIN_DEPTH_MULTIPLE:
        _add(blockers, BlockerSeverity.HARD, "SPOT_DEPTH_BELOW_2X_NOTIONAL")
    if perp_depth < perp_notional * MIN_DEPTH_MULTIPLE:
        _add(blockers, BlockerSeverity.HARD, "PERP_DEPTH_BELOW_2X_NOTIONAL")
    if remaining < reserve_target:
        _add(blockers, BlockerSeverity.HARD, "CAPITAL_RESERVE_NOT_PRESERVED")
    if four_fill_contingency > remaining:
        _add(blockers, BlockerSeverity.HARD, "FOUR_FILL_CONTINGENCY_EXCEEDS_RESERVE")

    return CapitalEnvelope(
        budget_usd=_decimal_text(budget),
        perp_leverage=_decimal_text(leverage),
        reserve_fraction=_decimal_text(reserve_fraction),
        capital_only_matched_notional_usd_per_leg=(
            envelope.capital_only_matched_notional_usd_per_leg
        ),
        matched_quantity_btc=_decimal_text(quantity),
        spot_notional_usdt=_decimal_text(spot_notional),
        perp_notional_usdt=_decimal_text(perp_notional),
        perp_initial_margin_usdt=_decimal_text(perp_margin),
        remaining_contingency_usdt=_decimal_text(remaining),
        four_fill_contingency_requirement_usdt=_decimal_text(four_fill_contingency),
    )


def _assess_operations(
    operations: OperationalStressAssessment | None,
    blockers: Counter[tuple[BlockerSeverity, str]],
) -> None:
    if operations is None:
        _add(blockers, BlockerSeverity.MISSING, "OPERATIONAL_STRESS_ASSESSMENT_MISSING")
        return
    for status, label in (
        (operations.transfer_path_stress, "TRANSFER_PATH_STRESS"),
        (operations.withdrawal_path_stress, "WITHDRAWAL_PATH_STRESS"),
        (operations.withdrawal_freeze_runbook, "WITHDRAWAL_FREEZE_RUNBOOK"),
        (operations.emergency_close_without_transfer, "EMERGENCY_CLOSE_WITHOUT_TRANSFER"),
        (operations.tax_review, "MX_TAX_REVIEW"),
    ):
        if status is CheckStatus.FAIL:
            _add(blockers, BlockerSeverity.HARD, f"{label}_FAILED")
        elif status is CheckStatus.NOT_RUN:
            _add(blockers, BlockerSeverity.MISSING, f"{label}_NOT_RUN")
    if operations.counterparty_review is ReviewOutcome.REJECTED:
        _add(blockers, BlockerSeverity.HARD, "COUNTERPARTY_REVIEW_REJECTED")
    elif operations.counterparty_review is ReviewOutcome.UNKNOWN:
        _add(blockers, BlockerSeverity.MISSING, "COUNTERPARTY_REVIEW_UNKNOWN")
    try:
        maximum_balance = _decimal(
            "maximum_venue_balance_usd", operations.maximum_venue_balance_usd
        )
    except CarryFeasibilityError:
        _add(blockers, BlockerSeverity.HARD, "MAXIMUM_VENUE_BALANCE_MALFORMED")
    else:
        if maximum_balance <= 0 or maximum_balance > SEALED_BUDGET_USD:
            _add(blockers, BlockerSeverity.HARD, "MAXIMUM_VENUE_BALANCE_EXCEEDS_POLICY")
    if not operations.full_custody_loss_scenario_acknowledged:
        _add(blockers, BlockerSeverity.MISSING, "FULL_CUSTODY_LOSS_NOT_ACKNOWLEDGED")


def evaluate_carry_feasibility(
    submission: CarryFeasibilitySubmission,
) -> CarryFeasibilityVerdict:
    """Evaluate an offline evidence pack without touching data, network or money."""

    if not isinstance(submission, CarryFeasibilitySubmission):
        raise CarryFeasibilityError("submission must be CarryFeasibilitySubmission")
    decision = _utc(submission.decision_at_utc)
    blockers: Counter[tuple[BlockerSeverity, str]] = Counter()

    # Schema v1 can verify only internal digest consistency. It cannot yet
    # authenticate who signed an attestation or derive the typed assessments
    # from the exact bytes. These blockers are immutable in v1: no caller-owned
    # payload can self-promote by inventing mutually consistent bytes/fields.
    _add(
        blockers,
        BlockerSeverity.MISSING,
        "EXTERNAL_ATTESTATION_TRUST_ROOT_NOT_IMPLEMENTED",
    )
    _add(
        blockers,
        BlockerSeverity.MISSING,
        "EVIDENCE_CONTENT_BINDING_PARSERS_NOT_IMPLEMENTED",
    )
    _add(
        blockers,
        BlockerSeverity.MISSING,
        "ACCOUNT_MANUAL_REVIEW_AUTHENTICITY_NOT_IMPLEMENTED",
    )

    selected = _select_causal_evidence(
        submission.evidence_artifacts,
        decision=decision,
        blockers=blockers,
    )
    _assess_venue_account(submission.venue_account, blockers)
    _assess_instrument_pair(submission.instrument_pair, blockers)
    capital = _assess_capital_and_terms(
        submission.capital,
        submission.point_in_time_terms,
        decision=decision,
        blockers=blockers,
    )
    _assess_operations(submission.operations, blockers)

    hard = any(severity is BlockerSeverity.HARD for severity, _ in blockers)
    if hard:
        status = CarryFeasibilityStatus.NO_GO
    elif blockers:
        status = CarryFeasibilityStatus.INSUFFICIENT
    else:
        status = CarryFeasibilityStatus.FEASIBLE_FOR_DEVELOPMENT_COLLECTION

    selected_payload = {
        "decision_at_utc": submission.decision_at_utc,
        "capital": submission.capital.to_dict(),
        "venue_account": (submission.venue_account.to_dict() if submission.venue_account else None),
        "instrument_pair": (
            submission.instrument_pair.to_dict() if submission.instrument_pair else None
        ),
        "point_in_time_terms": (
            submission.point_in_time_terms.to_dict() if submission.point_in_time_terms else None
        ),
        "operations": submission.operations.to_dict() if submission.operations else None,
        "receipts": [
            selected[kind].to_dict() for kind in sorted(selected, key=lambda row: row.value)
        ],
    }
    return CarryFeasibilityVerdict(
        status=status,
        decision_at_utc=submission.decision_at_utc,
        venue=SEALED_VENUE,
        country_code=SEALED_COUNTRY,
        capital=capital,
        blockers=_status_blockers(blockers),
        selected_evidence_sha256=sha256_of_text(canonical_dumps(selected_payload)),
        policy_sha256=carry_feasibility_policy_sha256(),
    )


__all__ = [
    "MAX_PERP_LEVERAGE",
    "MIN_LIQUIDATION_DISTANCE_FRACTION",
    "MIN_LIQUIDITY_RESERVE_FRACTION",
    "REQUIRED_EVIDENCE_KINDS",
    "BlockerSeverity",
    "CapitalEnvelope",
    "CapitalIntent",
    "CarryFeasibilityError",
    "CarryFeasibilityStatus",
    "CarryFeasibilitySubmission",
    "CarryFeasibilityVerdict",
    "CheckStatus",
    "CommercialUseStatus",
    "EvidenceArtifact",
    "EvidenceAuthority",
    "EvidenceKind",
    "EvidenceReceipt",
    "FeasibilityBlocker",
    "InstrumentPairAssessment",
    "KYCStatus",
    "OperationalStressAssessment",
    "PointInTimeTerms",
    "ReviewOutcome",
    "VenueAccountAssessment",
    "carry_feasibility_policy_sha256",
    "evaluate_carry_feasibility",
    "expected_evidence_scope",
]
