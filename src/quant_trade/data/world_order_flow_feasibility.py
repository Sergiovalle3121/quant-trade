"""Fail-closed data-feasibility gate for world-order-flow research.

This module implements no signal, model, sort, backtest, trial, P&L, holdout
read, network access, or order path.  Its only positive state means that a
causal, commercially usable input panel is sufficiently evidenced to draft a
*separate* preregistration.

The paper definition frozen here is the Anastasopoulos et al. (2026) measure::

    raw_world_flow[i, t] =
        log(sum_c buyer_initiated_volume[i, c, t])
        - log(sum_c seller_initiated_volume[i, c, t])

    world_flow[i, t] =
        raw_world_flow[i, t]
        / stdev(raw_world_flow[i, t-29:t])

where ``c`` is exactly the 11 fiat currencies below.  Binance USDT klines are
not an equivalent input, even when a raw kline happens to carry taker-buy
volume: one venue and one stablecoin cannot replace a global, 11-fiat signed
volume aggregate.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

WORLD_ORDER_FLOW_WINDOW_DAYS = 30
MINIMUM_CROSS_SECTION_ASSETS = 84
REQUIRED_FIAT_CURRENCIES = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "NZD",
    "NOK",
    "SEK",
    "KRW",
)
PAPER_DAILY_CALENDAR = "WEEKDAYS_EXCLUDING_US_HOLIDAYS"
WORLD_ORDER_FLOW_FORMULA = (
    "(log(sum_G11_buyer_initiated_volume)-log(sum_G11_seller_initiated_volume))"
    "/sample_stdev_30_paper_calendar_raw_world_flows"
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


class WorldOrderFlowFeasibilityError(ValueError):
    """The feasibility cutoff itself is invalid or ambiguous."""


class WorldOrderFlowFeasibilityStatus(StrEnum):
    """Data-only tri-state.  None of these values approves trading."""

    FEASIBLE_FOR_PREREGISTRATION = "FEASIBLE_FOR_PREREGISTRATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_GO = "NO_GO"


class CommercialLicenseStatus(StrEnum):
    """Commercial rights for the exact provider bytes and intended use."""

    COMMERCIAL_USE_PERMITTED = "COMMERCIAL_USE_PERMITTED"
    NON_COMMERCIAL_ONLY = "NON_COMMERCIAL_ONLY"
    COMMERCIAL_USE_PROHIBITED = "COMMERCIAL_USE_PROHIBITED"
    UNKNOWN = "UNKNOWN"


class SignedVolumeDefinition(StrEnum):
    """Trade classification used by the source observation."""

    BUYER_AND_SELLER_INITIATED = "BUYER_AND_SELLER_INITIATED"
    TAKER_BUY_ONLY_DERIVED_COMPLEMENT = "TAKER_BUY_ONLY_DERIVED_COMPLEMENT"
    UNSIGNED_TOTAL_VOLUME = "UNSIGNED_TOTAL_VOLUME"
    UNKNOWN = "UNKNOWN"


class SourceScope(StrEnum):
    """Scope of the signed-volume aggregation delivered by the source."""

    MULTI_VENUE_FIAT = "MULTI_VENUE_FIAT"
    SINGLE_VENUE = "SINGLE_VENUE"
    UNKNOWN = "UNKNOWN"


class BlockerSeverity(StrEnum):
    """Contradictions are NO_GO; missing proof is insufficient evidence."""

    HARD = "HARD"
    MISSING = "MISSING"


@dataclass(frozen=True)
class WorldOrderFlowIdentity:
    """Stable identity independent of ticker or venue symbol."""

    cmc_id: int | None
    chain_id: str | None
    contract_or_native_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldOrderFlowCalendarEvidence:
    """The exact 30 observation dates on the paper's daily sample calendar.

    The article excludes weekends and U.S. holidays from its daily sample.
    Consequently, 30 observations are not 30 consecutive calendar days.
    """

    measurement_dates: tuple[str, ...]
    calendar_name: str | None
    method_version: str | None
    source_name: str | None
    source_bytes_sha256: str | None
    observed_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldOrderFlowObservation:
    """One asset/fiat/day signed-volume observation with PIT provenance."""

    identity: WorldOrderFlowIdentity
    measurement_date: str | None
    fiat_currency: str | None
    buyer_initiated_volume: str | None
    seller_initiated_volume: str | None
    contributing_venues: tuple[str, ...]
    signed_volume_definition: SignedVolumeDefinition | str | None
    source_scope: SourceScope | str | None
    observed_at_utc: str | None
    computed_at_utc: str | None
    published_at_utc: str | None
    provider_name: str | None
    source_contract: str | None
    method_name: str | None
    method_version: str | None
    source_bytes_sha256: str | None
    license_status: CommercialLicenseStatus | str | None
    license_terms_sha256: str | None
    license_verified_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("signed_volume_definition", "source_scope", "license_status"):
            value = getattr(self, key)
            payload[key] = value.value if isinstance(value, StrEnum) else value
        return payload


@dataclass(frozen=True)
class WorldOrderFlowBlocker:
    code: str
    severity: BlockerSeverity
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.severity, BlockerSeverity):
            raise WorldOrderFlowFeasibilityError("blocker severity must be typed")
        if not self.code or not self.code.isupper():
            raise WorldOrderFlowFeasibilityError("blocker code must be non-empty uppercase text")
        if type(self.count) is not int or self.count <= 0:
            raise WorldOrderFlowFeasibilityError("blocker count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity.value, "count": self.count}


@dataclass(frozen=True)
class WorldOrderFlowFeasibilityVerdict:
    """Hash-stable data verdict with every expansive permission locked false."""

    status: WorldOrderFlowFeasibilityStatus
    decision_at_utc: str
    expected_first_measurement_date: str
    expected_last_measurement_date: str
    assets_evaluated: int
    eligible_assets: int
    minimum_cross_section_assets: int
    required_fiat_currencies: tuple[str, ...]
    calendar_name: str
    calendar_evidence_sha256: str
    formula: str
    blockers: tuple[WorldOrderFlowBlocker, ...]
    causal_evidence_sha256: str
    structural_feasibility_only: bool = field(default=True, init=False)
    preregistration_authorized: bool = field(default=False, init=False)
    signal_generation_authorized: bool = field(default=False, init=False)
    model_training_authorized: bool = field(default=False, init=False)
    portfolio_sort_authorized: bool = field(default=False, init=False)
    backtest_authorized: bool = field(default=False, init=False)
    pnl_evaluation_authorized: bool = field(default=False, init=False)
    holdout_access_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)
    real_money_authorized: bool = field(default=False, init=False)
    profitability_evidence: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorldOrderFlowFeasibilityStatus):
            raise WorldOrderFlowFeasibilityError("status must be a WorldOrderFlowFeasibilityStatus")
        decision = _parse_utc(self.decision_at_utc)
        if decision is None or decision.strftime("%Y-%m-%dT%H:%M:%SZ") != self.decision_at_utc:
            raise WorldOrderFlowFeasibilityError("decision_at_utc must be canonical UTC text")
        for field_name in (
            "assets_evaluated",
            "eligible_assets",
            "minimum_cross_section_assets",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise WorldOrderFlowFeasibilityError(f"{field_name} must be a non-negative integer")
        if self.assets_evaluated < self.eligible_assets:
            raise WorldOrderFlowFeasibilityError(
                "assets_evaluated must be no smaller than eligible_assets"
            )
        if self.minimum_cross_section_assets != MINIMUM_CROSS_SECTION_ASSETS:
            raise WorldOrderFlowFeasibilityError(
                "minimum_cross_section_assets differs from frozen policy"
            )
        if self.required_fiat_currencies != REQUIRED_FIAT_CURRENCIES:
            raise WorldOrderFlowFeasibilityError(
                "required_fiat_currencies differs from the frozen G11 set"
            )
        if self.calendar_name not in {"", PAPER_DAILY_CALENDAR}:
            raise WorldOrderFlowFeasibilityError("calendar_name differs from frozen policy")
        if self.formula != WORLD_ORDER_FLOW_FORMULA:
            raise WorldOrderFlowFeasibilityError(
                "formula differs from the frozen world-order-flow definition"
            )
        if not isinstance(self.blockers, tuple) or any(
            not isinstance(blocker, WorldOrderFlowBlocker) for blocker in self.blockers
        ):
            raise WorldOrderFlowFeasibilityError("blockers must be a typed immutable tuple")
        expected_order = tuple(
            sorted(self.blockers, key=lambda blocker: (blocker.severity.value, blocker.code))
        )
        if self.blockers != expected_order:
            raise WorldOrderFlowFeasibilityError("blockers must use canonical severity/code order")
        blocker_keys = [(blocker.severity, blocker.code) for blocker in self.blockers]
        if len(blocker_keys) != len(set(blocker_keys)):
            raise WorldOrderFlowFeasibilityError(
                "duplicate blockers must be combined into one count"
            )
        for field_name in ("calendar_evidence_sha256", "causal_evidence_sha256"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise WorldOrderFlowFeasibilityError(
                    f"{field_name} must be a lowercase SHA-256 digest"
                )

        first = _measurement_date(self.expected_first_measurement_date)
        last = _measurement_date(self.expected_last_measurement_date)
        if bool(first) != bool(last):
            raise WorldOrderFlowFeasibilityError(
                "expected measurement boundaries must both be present or absent"
            )
        if first is not None and last is not None and not first <= last < decision.date():
            raise WorldOrderFlowFeasibilityError(
                "expected measurement boundaries must precede the decision"
            )

        has_hard = any(blocker.severity is BlockerSeverity.HARD for blocker in self.blockers)
        has_missing = any(blocker.severity is BlockerSeverity.MISSING for blocker in self.blockers)
        if has_hard:
            expected_status = WorldOrderFlowFeasibilityStatus.NO_GO
        elif has_missing:
            expected_status = WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
        else:
            expected_status = WorldOrderFlowFeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION
        if self.status is not expected_status:
            raise WorldOrderFlowFeasibilityError("status does not match the blocker severities")
        if self.status is WorldOrderFlowFeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION:
            raise WorldOrderFlowFeasibilityError(
                "v1 cannot construct FEASIBLE_FOR_PREREGISTRATION without an "
                "independent byte, license, and vintage attestation loader"
            )

    def sealed_content(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "decision_at_utc": self.decision_at_utc,
            "expected_first_measurement_date": self.expected_first_measurement_date,
            "expected_last_measurement_date": self.expected_last_measurement_date,
            "assets_evaluated": self.assets_evaluated,
            "eligible_assets": self.eligible_assets,
            "minimum_cross_section_assets": self.minimum_cross_section_assets,
            "required_fiat_currencies": list(self.required_fiat_currencies),
            "calendar_name": self.calendar_name,
            "calendar_evidence_sha256": self.calendar_evidence_sha256,
            "formula": self.formula,
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "causal_evidence_sha256": self.causal_evidence_sha256,
            "structural_feasibility_only": self.structural_feasibility_only,
            "preregistration_authorized": self.preregistration_authorized,
            "signal_generation_authorized": self.signal_generation_authorized,
            "model_training_authorized": self.model_training_authorized,
            "portfolio_sort_authorized": self.portfolio_sort_authorized,
            "backtest_authorized": self.backtest_authorized,
            "pnl_evaluation_authorized": self.pnl_evaluation_authorized,
            "holdout_access_authorized": self.holdout_access_authorized,
            "network_access_authorized": self.network_access_authorized,
            "real_money_authorized": self.real_money_authorized,
            "profitability_evidence": self.profitability_evidence,
        }

    @property
    def seal(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        payload = self.sealed_content()
        payload["seal"] = self.seal
        return payload


def _parse_utc(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _measurement_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _decision(value: str) -> datetime:
    parsed = _parse_utc(value)
    if parsed is None or parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise WorldOrderFlowFeasibilityError(
            "decision_at_utc must be an exact ISO-8601 UTC instant ending in Z"
        )
    return parsed


def _enum(value: Any, expected: type[StrEnum]) -> StrEnum | None:
    try:
        return expected(value)
    except (TypeError, ValueError):
        return None


def _positive_number(value: str | None) -> bool:
    try:
        parsed = float(value) if value is not None else math.nan
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed > 0


def _valid_identity(identity: WorldOrderFlowIdentity) -> bool:
    return (
        type(identity.cmc_id) is int
        and identity.cmc_id > 0
        and isinstance(identity.chain_id, str)
        and bool(_IDENTIFIER_RE.fullmatch(identity.chain_id))
        and isinstance(identity.contract_or_native_id, str)
        and bool(_IDENTIFIER_RE.fullmatch(identity.contract_or_native_id))
    )


def _identity_key(identity: WorldOrderFlowIdentity) -> tuple[int | None, str | None, str | None]:
    return identity.cmc_id, identity.chain_id, identity.contract_or_native_id


def _record(
    counter: Counter[tuple[str, BlockerSeverity]], code: str, severity: BlockerSeverity
) -> None:
    counter[(code, severity)] += 1


def _row_blockers(
    row: WorldOrderFlowObservation,
    *,
    decision_at: datetime,
    expected_dates: set[str],
) -> Counter[tuple[str, BlockerSeverity]]:
    blockers: Counter[tuple[str, BlockerSeverity]] = Counter()
    if not _valid_identity(row.identity):
        _record(blockers, "UNSTABLE_OR_MISSING_IDENTITY", BlockerSeverity.MISSING)
    if row.measurement_date not in expected_dates:
        _record(blockers, "WRONG_MEASUREMENT_WINDOW", BlockerSeverity.HARD)
    if row.fiat_currency not in REQUIRED_FIAT_CURRENCIES:
        _record(blockers, "NON_G11_OR_MISSING_FIAT", BlockerSeverity.HARD)
    if not _positive_number(row.buyer_initiated_volume):
        _record(blockers, "MISSING_OR_NONPOSITIVE_BUY_VOLUME", BlockerSeverity.MISSING)
    if not _positive_number(row.seller_initiated_volume):
        _record(blockers, "MISSING_OR_NONPOSITIVE_SELL_VOLUME", BlockerSeverity.MISSING)

    definition = _enum(row.signed_volume_definition, SignedVolumeDefinition)
    if definition is not SignedVolumeDefinition.BUYER_AND_SELLER_INITIATED:
        severity = (
            BlockerSeverity.HARD
            if definition
            in {
                SignedVolumeDefinition.TAKER_BUY_ONLY_DERIVED_COMPLEMENT,
                SignedVolumeDefinition.UNSIGNED_TOTAL_VOLUME,
            }
            else BlockerSeverity.MISSING
        )
        _record(blockers, "SIGNED_BUY_SELL_VOLUME_NOT_PROVEN", severity)

    scope = _enum(row.source_scope, SourceScope)
    if scope is not SourceScope.MULTI_VENUE_FIAT:
        severity = (
            BlockerSeverity.HARD if scope is SourceScope.SINGLE_VENUE else BlockerSeverity.MISSING
        )
        _record(blockers, "MULTI_VENUE_FIAT_SCOPE_NOT_PROVEN", severity)

    venues = tuple(row.contributing_venues)
    if (
        not venues
        or len(venues) != len(set(venues))
        or any(not _IDENTIFIER_RE.fullmatch(item) for item in venues)
    ):
        _record(blockers, "SOURCE_VENUE_COVERAGE_INSUFFICIENT", BlockerSeverity.MISSING)

    for label, value in (
        ("OBSERVED", row.observed_at_utc),
        ("COMPUTED", row.computed_at_utc),
        ("PUBLISHED", row.published_at_utc),
    ):
        timestamp = _parse_utc(value)
        if timestamp is None:
            _record(blockers, f"{label}_AT_INVALID_OR_MISSING", BlockerSeverity.MISSING)
        elif timestamp > decision_at:
            _record(blockers, f"{label}_AFTER_DECISION", BlockerSeverity.HARD)

    measurement_day: date | None = None
    if isinstance(row.measurement_date, str):
        try:
            measurement_day = date.fromisoformat(row.measurement_date)
        except ValueError:
            measurement_day = None
    timestamps = (
        _parse_utc(row.observed_at_utc),
        _parse_utc(row.computed_at_utc),
        _parse_utc(row.published_at_utc),
    )
    if measurement_day is not None and all(timestamp is not None for timestamp in timestamps):
        observed_at, computed_at, published_at = timestamps
        assert observed_at is not None
        assert computed_at is not None
        assert published_at is not None
        complete_at = datetime.combine(measurement_day + timedelta(days=1), time.min, UTC)
        if min(observed_at, computed_at, published_at) < complete_at:
            _record(
                blockers,
                "VINTAGE_PRECEDES_COMPLETE_DAILY_MEASUREMENT",
                BlockerSeverity.HARD,
            )
        if not computed_at <= published_at <= observed_at:
            _record(blockers, "VINTAGE_ORDER_INCONSISTENT", BlockerSeverity.HARD)

    for label, value in (
        ("METHOD_NAME", row.method_name),
        ("METHOD_VERSION", row.method_version),
    ):
        if not isinstance(value, str) or not value.strip():
            _record(blockers, f"{label}_MISSING", BlockerSeverity.MISSING)

    provider = row.provider_name.strip().lower() if isinstance(row.provider_name, str) else ""
    if provider not in {"cryptocompare", "ccdata"}:
        severity = BlockerSeverity.HARD if provider else BlockerSeverity.MISSING
        _record(blockers, "PAPER_SOURCE_PROVIDER_NOT_PROVEN", severity)
    contract = row.source_contract.strip().lower() if isinstance(row.source_contract, str) else ""
    if contract != "cryptocompare_signed_volume_g11_multi_exchange":
        severity = BlockerSeverity.HARD if contract else BlockerSeverity.MISSING
        _record(blockers, "PAPER_SIGNED_VOLUME_CONTRACT_NOT_PROVEN", severity)

    if not isinstance(row.source_bytes_sha256, str) or not _SHA256_RE.fullmatch(
        row.source_bytes_sha256
    ):
        _record(blockers, "SOURCE_BYTES_HASH_INVALID_OR_MISSING", BlockerSeverity.MISSING)

    license_status = _enum(row.license_status, CommercialLicenseStatus)
    if license_status is not CommercialLicenseStatus.COMMERCIAL_USE_PERMITTED:
        severity = (
            BlockerSeverity.HARD
            if license_status
            in {
                CommercialLicenseStatus.NON_COMMERCIAL_ONLY,
                CommercialLicenseStatus.COMMERCIAL_USE_PROHIBITED,
            }
            else BlockerSeverity.MISSING
        )
        _record(blockers, "COMMERCIAL_LICENSE_NOT_PROVEN", severity)
    if not isinstance(row.license_terms_sha256, str) or not _SHA256_RE.fullmatch(
        row.license_terms_sha256
    ):
        _record(blockers, "LICENSE_TERMS_HASH_INVALID_OR_MISSING", BlockerSeverity.MISSING)
    verified_at = _parse_utc(row.license_verified_at_utc)
    if verified_at is None:
        _record(blockers, "LICENSE_VERIFIED_AT_INVALID_OR_MISSING", BlockerSeverity.MISSING)
    elif verified_at > decision_at:
        _record(blockers, "LICENSE_VERIFIED_AFTER_DECISION", BlockerSeverity.HARD)
    return blockers


def _calendar_blockers(
    calendar: WorldOrderFlowCalendarEvidence | None, *, decision_at: datetime
) -> tuple[set[str], Counter[tuple[str, BlockerSeverity]]]:
    blockers: Counter[tuple[str, BlockerSeverity]] = Counter()
    if calendar is None:
        _record(blockers, "PAPER_SAMPLE_CALENDAR_MISSING", BlockerSeverity.MISSING)
        return set(), blockers

    if calendar.calendar_name != PAPER_DAILY_CALENDAR:
        severity = (
            BlockerSeverity.HARD
            if isinstance(calendar.calendar_name, str) and calendar.calendar_name
            else BlockerSeverity.MISSING
        )
        _record(blockers, "PAPER_SAMPLE_CALENDAR_NOT_PROVEN", severity)
    for label, value in (
        ("CALENDAR_METHOD_VERSION", calendar.method_version),
        ("CALENDAR_SOURCE_NAME", calendar.source_name),
    ):
        if not isinstance(value, str) or not value.strip():
            _record(blockers, f"{label}_MISSING", BlockerSeverity.MISSING)
    if not isinstance(calendar.source_bytes_sha256, str) or not _SHA256_RE.fullmatch(
        calendar.source_bytes_sha256
    ):
        _record(blockers, "CALENDAR_SOURCE_HASH_INVALID_OR_MISSING", BlockerSeverity.MISSING)
    observed_at = _parse_utc(calendar.observed_at_utc)
    if observed_at is None:
        _record(blockers, "CALENDAR_OBSERVED_AT_INVALID_OR_MISSING", BlockerSeverity.MISSING)
    elif observed_at > decision_at:
        _record(blockers, "CALENDAR_OBSERVED_AFTER_DECISION", BlockerSeverity.HARD)

    dates: list[date] = []
    for value in calendar.measurement_dates:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            _record(blockers, "CALENDAR_DATE_INVALID", BlockerSeverity.HARD)
            continue
        dates.append(parsed)
        if parsed.weekday() >= 5:
            _record(blockers, "WEEKEND_IN_PAPER_DAILY_CALENDAR", BlockerSeverity.HARD)
        if parsed >= decision_at.date():
            _record(blockers, "CALENDAR_DATE_NOT_BEFORE_DECISION", BlockerSeverity.HARD)
    if len(calendar.measurement_dates) != WORLD_ORDER_FLOW_WINDOW_DAYS:
        _record(blockers, "CALENDAR_DOES_NOT_HAVE_30_OBSERVATIONS", BlockerSeverity.MISSING)
    if len(calendar.measurement_dates) != len(set(calendar.measurement_dates)):
        _record(blockers, "DUPLICATE_CALENDAR_DATE", BlockerSeverity.HARD)
    if dates != sorted(dates):
        _record(blockers, "CALENDAR_DATES_NOT_STRICTLY_INCREASING", BlockerSeverity.HARD)
    return {value.isoformat() for value in dates}, blockers


def _decision_slice(
    observations: tuple[WorldOrderFlowObservation, ...],
    *,
    decision_at: datetime,
    expected_dates: set[str],
) -> tuple[WorldOrderFlowObservation, ...]:
    rows: list[WorldOrderFlowObservation] = []
    for row in observations:
        if isinstance(row.measurement_date, str):
            try:
                parsed_date = date.fromisoformat(row.measurement_date)
            except ValueError:
                parsed_date = None
            if parsed_date is not None and row.measurement_date not in expected_dates:
                # A full append-only dataset may be supplied.  Rows outside the
                # exact decision window are irrelevant and must not change the
                # prefix verdict or digest.
                continue
        timestamps = (
            _parse_utc(row.observed_at_utc),
            _parse_utc(row.computed_at_utc),
            _parse_utc(row.published_at_utc),
        )
        if all(timestamp is not None for timestamp in timestamps) and any(
            timestamp > decision_at for timestamp in timestamps if timestamp is not None
        ):
            # A later vintage is not evidence available at the cutoff.  Ignore
            # it byte-for-byte; an invalid timestamp, by contrast, is retained
            # so the row cannot disappear instead of failing closed.
            continue
        rows.append(row)
    return tuple(rows)


def evaluate_world_order_flow_data_feasibility(
    observations: tuple[WorldOrderFlowObservation, ...],
    *,
    calendar: WorldOrderFlowCalendarEvidence | None,
    decision_at_utc: str,
) -> WorldOrderFlowFeasibilityVerdict:
    """Evaluate only whether a future preregistration may be drafted.

    Evidence observed, computed, or published after ``decision_at_utc`` is
    excluded from the digest and therefore cannot alter a prefix verdict.  A
    contradictory substitute such as single-venue Binance/USDT input produces
    ``NO_GO``; absent proof produces ``INSUFFICIENT_EVIDENCE``.
    """

    decision_at = _decision(decision_at_utc)
    expected_dates, calendar_issues = _calendar_blockers(calendar, decision_at=decision_at)
    ordered_expected_dates = sorted(expected_dates)
    first_date = ordered_expected_dates[0] if ordered_expected_dates else ""
    last_date = ordered_expected_dates[-1] if ordered_expected_dates else ""

    causal = _decision_slice(
        tuple(observations), decision_at=decision_at, expected_dates=expected_dates
    )
    sorted_rows = tuple(
        sorted(
            causal,
            key=lambda row: (
                canonical_dumps(row.identity.to_dict()),
                row.measurement_date or "",
                row.fiat_currency or "",
                canonical_dumps(row.to_dict()),
            ),
        )
    )
    calendar_payload = calendar.to_dict() if calendar is not None else None
    calendar_sha = sha256_of_text(canonical_dumps(calendar_payload))
    evidence_sha = sha256_of_text(
        canonical_dumps(
            {"calendar": calendar_payload, "observations": [row.to_dict() for row in sorted_rows]}
        )
    )
    blockers: Counter[tuple[str, BlockerSeverity]] = Counter(calendar_issues)
    if not causal:
        _record(blockers, "NO_EVIDENCE_ROWS", BlockerSeverity.MISSING)

    rows_by_asset: defaultdict[
        tuple[int | None, str | None, str | None], list[WorldOrderFlowObservation]
    ] = defaultdict(list)
    for row in sorted_rows:
        rows_by_asset[_identity_key(row.identity)].append(row)
        blockers.update(_row_blockers(row, decision_at=decision_at, expected_dates=expected_dates))

    eligible_assets = 0
    seen_cmc: dict[int, tuple[int | None, str | None, str | None]] = {}
    seen_chain_asset: dict[tuple[str, str], tuple[int | None, str | None, str | None]] = {}
    for key, rows in rows_by_asset.items():
        cmc_id, chain_id, contract_id = key
        if type(cmc_id) is int:
            prior = seen_cmc.setdefault(cmc_id, key)
            if prior != key:
                _record(blockers, "CMC_IDENTITY_COLLISION", BlockerSeverity.HARD)
        if isinstance(chain_id, str) and isinstance(contract_id, str):
            prior = seen_chain_asset.setdefault((chain_id, contract_id), key)
            if prior != key:
                _record(blockers, "CHAIN_IDENTITY_COLLISION", BlockerSeverity.HARD)

        cells = [(row.measurement_date, row.fiat_currency) for row in rows]
        expected_cells = {
            (measurement_date, currency)
            for measurement_date in expected_dates
            for currency in REQUIRED_FIAT_CURRENCIES
        }
        if len(cells) != len(set(cells)):
            _record(blockers, "DUPLICATE_ASSET_DAY_FIAT_CELL", BlockerSeverity.HARD)
        actual_cells = set(cells)
        if actual_cells != expected_cells:
            missing = len(expected_cells - actual_cells)
            extra = len(actual_cells - expected_cells)
            _record(
                blockers,
                "INCOMPLETE_30_DAY_G11_PANEL",
                BlockerSeverity.MISSING if missing else BlockerSeverity.HARD,
            )
            if extra:
                _record(blockers, "UNEXPECTED_ASSET_DAY_FIAT_CELLS", BlockerSeverity.HARD)

        rows_by_date: defaultdict[str | None, list[WorldOrderFlowObservation]] = defaultdict(list)
        for row in rows:
            rows_by_date[row.measurement_date].append(row)
        for date_rows in rows_by_date.values():
            venue_union = {venue for row in date_rows for venue in row.contributing_venues}
            if not venue_union:
                _record(
                    blockers,
                    "SOURCE_VENUE_COVERAGE_INSUFFICIENT",
                    BlockerSeverity.MISSING,
                )

        row_has_blocker = any(
            _row_blockers(row, decision_at=decision_at, expected_dates=expected_dates)
            for row in rows
        )
        if (
            _valid_identity(rows[0].identity)
            and actual_cells == expected_cells
            and len(cells) == len(expected_cells)
            and not row_has_blocker
        ):
            eligible_assets += 1

    if eligible_assets < MINIMUM_CROSS_SECTION_ASSETS:
        _record(blockers, "CROSS_SECTION_COVERAGE_BELOW_84_ASSETS", BlockerSeverity.MISSING)

    # v1 validates immutable metadata claims, but cannot authenticate them: it
    # does not open/re-hash provider or license bytes and has no independent
    # vintage attestor.  Structural completeness can therefore never promote
    # this family on its own.
    _record(
        blockers,
        "EXTERNAL_SOURCE_LICENSE_VINTAGE_ATTESTATION_NOT_IMPLEMENTED",
        BlockerSeverity.MISSING,
    )

    blocker_tuple = tuple(
        WorldOrderFlowBlocker(code=code, severity=severity, count=count)
        for (code, severity), count in sorted(
            blockers.items(), key=lambda item: (item[0][1].value, item[0][0])
        )
    )
    if any(blocker.severity is BlockerSeverity.HARD for blocker in blocker_tuple):
        status = WorldOrderFlowFeasibilityStatus.NO_GO
    elif blocker_tuple:
        status = WorldOrderFlowFeasibilityStatus.INSUFFICIENT_EVIDENCE
    else:
        status = WorldOrderFlowFeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION

    return WorldOrderFlowFeasibilityVerdict(
        status=status,
        decision_at_utc=decision_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expected_first_measurement_date=first_date,
        expected_last_measurement_date=last_date,
        assets_evaluated=len(rows_by_asset),
        eligible_assets=eligible_assets,
        minimum_cross_section_assets=MINIMUM_CROSS_SECTION_ASSETS,
        required_fiat_currencies=REQUIRED_FIAT_CURRENCIES,
        calendar_name=calendar.calendar_name if calendar and calendar.calendar_name else "",
        calendar_evidence_sha256=calendar_sha,
        formula=WORLD_ORDER_FLOW_FORMULA,
        blockers=blocker_tuple,
        causal_evidence_sha256=evidence_sha,
    )


__all__ = [
    "BlockerSeverity",
    "CommercialLicenseStatus",
    "MINIMUM_CROSS_SECTION_ASSETS",
    "PAPER_DAILY_CALENDAR",
    "REQUIRED_FIAT_CURRENCIES",
    "SignedVolumeDefinition",
    "SourceScope",
    "WORLD_ORDER_FLOW_FORMULA",
    "WORLD_ORDER_FLOW_WINDOW_DAYS",
    "WorldOrderFlowBlocker",
    "WorldOrderFlowFeasibilityError",
    "WorldOrderFlowFeasibilityStatus",
    "WorldOrderFlowFeasibilityVerdict",
    "WorldOrderFlowIdentity",
    "WorldOrderFlowCalendarEvidence",
    "WorldOrderFlowObservation",
    "evaluate_world_order_flow_data_feasibility",
]
