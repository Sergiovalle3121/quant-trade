"""Offline, point-in-time data-feasibility gate for the AANV30 hypothesis.

This module deliberately stops before strategy design.  It does not calculate
an AANV30 score, form a portfolio, inspect a holdout, evaluate P&L, access the
network, or authorize orders.  Schema v1 cannot emit its positive state:
caller-supplied metadata cannot attest source bytes, historical vintages, or
commercial license terms.  A future receipt-bound loader must clear those
blockers in a new schema before preregistration can be considered.

AANV30 is frozen here as::

    mean(the 30 exact preceding UTC-day ActiveAddresses counts)
    / market capitalization observed at the decision instant

The numerator is a mean of 30 daily counts.  It is not the number of distinct
addresses seen across the whole 30-day window; an address active on multiple
days may contribute to multiple daily counts.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

AANV30_WINDOW_DAYS = 30
MINIMUM_ELIGIBLE_ASSETS = 100
FUTURE_TOP_QUINTILE_SIZE = 20
AANV30_FEASIBILITY_SCHEMA_VERSION = 1
AANV30_FORMULA = (
    "arithmetic_mean(30 exact preceding UTC-day DAILY_ACTIVE_ADDRESSES) "
    "/ market_cap_usd_at_decision"
)
V1_REQUIRED_ATTESTATION_BLOCKER_CODES = (
    "COMMERCIAL_LICENSE_ATTESTATION_MISSING",
    "HISTORICAL_VINTAGE_ATTESTATION_MISSING",
    "SOURCE_BYTES_REHASH_ATTESTATION_MISSING",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BLOCKER_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]*")


class AANV30FeasibilityError(ValueError):
    """The gate itself cannot be evaluated because its cutoff is ambiguous."""


class AANV30FeasibilityStatus(StrEnum):
    """A data-only tri-state; none of the states authorizes trading."""

    FEASIBLE_FOR_PREREGISTRATION = "FEASIBLE_FOR_PREREGISTRATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_GO = "NO_GO"


class ActiveAddressMetricDefinition(StrEnum):
    """Definitions must never be silently substituted for one another."""

    DAILY_ACTIVE_ADDRESSES = "DAILY_ACTIVE_ADDRESSES"
    WINDOW_UNIQUE_ACTIVE_ADDRESSES = "WINDOW_UNIQUE_ACTIVE_ADDRESSES"
    UNKNOWN = "UNKNOWN"


class CommercialLicenseStatus(StrEnum):
    """Commercial-use status of the exact source evidence."""

    COMMERCIAL_USE_PERMITTED = "COMMERCIAL_USE_PERMITTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    COMMERCIAL_USE_PROHIBITED = "COMMERCIAL_USE_PROHIBITED"
    UNKNOWN = "UNKNOWN"


class BlockerSeverity(StrEnum):
    """Hard contradictions are NO_GO; missing knowledge is insufficient."""

    HARD = "HARD"
    MISSING = "MISSING"


@dataclass(frozen=True)
class AANV30Identity:
    """Stable cross-source identity: chain + contract/native id + CMC id."""

    chain_id: str | None
    contract_or_native_id: str | None
    cmc_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailyActiveAddressesEvidence:
    """One provider-published daily ActiveAddresses observation."""

    identity: AANV30Identity
    measurement_date: str | None
    active_addresses: int | None
    metric_definition: ActiveAddressMetricDefinition | str | None
    observed_at_utc: str | None
    computed_at_utc: str | None
    published_at_utc: str | None
    method_name: str | None
    method_version: str | None
    source_name: str | None
    source_bytes_sha256: str | None
    license_status: CommercialLicenseStatus | str | None
    license_terms_sha256: str | None
    license_verified_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        metric = self.metric_definition
        license_status = self.license_status
        payload["metric_definition"] = metric.value if isinstance(metric, StrEnum) else metric
        payload["license_status"] = (
            license_status.value if isinstance(license_status, StrEnum) else license_status
        )
        return payload


@dataclass(frozen=True)
class MarketCapAtDecisionEvidence:
    """USD market capitalization effective at one exact decision instant."""

    identity: AANV30Identity
    effective_at_utc: str | None
    market_cap_usd: str | None
    observed_at_utc: str | None
    computed_at_utc: str | None
    published_at_utc: str | None
    method_name: str | None
    method_version: str | None
    source_name: str | None
    source_bytes_sha256: str | None
    license_status: CommercialLicenseStatus | str | None
    license_terms_sha256: str | None
    license_verified_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        license_status = self.license_status
        payload["license_status"] = (
            license_status.value if isinstance(license_status, StrEnum) else license_status
        )
        return payload


@dataclass(frozen=True)
class AANV30AssetEvidence:
    """All evidence offered for one prospective cross-sectional asset."""

    identity: AANV30Identity
    daily_active_addresses: tuple[DailyActiveAddressesEvidence, ...]
    market_cap_at_decision: MarketCapAtDecisionEvidence | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "daily_active_addresses": [row.to_dict() for row in self.daily_active_addresses],
            "market_cap_at_decision": (
                self.market_cap_at_decision.to_dict()
                if self.market_cap_at_decision is not None
                else None
            ),
        }


@dataclass(frozen=True)
class AANV30Blocker:
    code: str
    severity: BlockerSeverity
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _BLOCKER_CODE_RE.fullmatch(self.code) is None:
            raise AANV30FeasibilityError("blocker code must be canonical uppercase text")
        if not isinstance(self.severity, BlockerSeverity):
            raise AANV30FeasibilityError("blocker severity must be a BlockerSeverity")
        if type(self.count) is not int or self.count <= 0:
            raise AANV30FeasibilityError("blocker count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "count": self.count,
        }


@dataclass(frozen=True)
class AANV30FeasibilityVerdict:
    """Hash-stable result of the data gate, with safety flags locked false."""

    status: AANV30FeasibilityStatus
    decision_at_utc: str
    expected_first_measurement_date: str
    expected_last_measurement_date: str
    causal_assets_evaluated: int
    eligible_assets: int
    minimum_eligible_assets: int
    future_top_quintile_size: int
    formula: str
    blockers: tuple[AANV30Blocker, ...]
    causal_evidence_sha256: str
    schema_version: int = field(default=AANV30_FEASIBILITY_SCHEMA_VERSION, init=False)
    real_money_authorized: bool = field(default=False, init=False)
    signal_generation_authorized: bool = field(default=False, init=False)
    pnl_evaluation_authorized: bool = field(default=False, init=False)
    holdout_access_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)
    profitability_evidence: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, AANV30FeasibilityStatus):
            raise AANV30FeasibilityError("status must be an AANV30FeasibilityStatus")
        if self.schema_version != AANV30_FEASIBILITY_SCHEMA_VERSION:
            raise AANV30FeasibilityError("unsupported AANV30 feasibility schema_version")
        if self.status is AANV30FeasibilityStatus.FEASIBLE_FOR_PREREGISTRATION:
            raise AANV30FeasibilityError(
                "schema v1 cannot construct FEASIBLE_FOR_PREREGISTRATION without "
                "an external attestation loader"
            )
        decision = _canonical_utc(self.decision_at_utc)
        if decision is None:
            raise AANV30FeasibilityError("decision_at_utc must be canonical UTC text")
        expected_first = decision.date() - timedelta(days=AANV30_WINDOW_DAYS)
        expected_last = decision.date() - timedelta(days=1)
        if _measurement_date(self.expected_first_measurement_date) != expected_first:
            raise AANV30FeasibilityError(
                "expected_first_measurement_date must start the exact AANV30 window"
            )
        if _measurement_date(self.expected_last_measurement_date) != expected_last:
            raise AANV30FeasibilityError(
                "expected_last_measurement_date must end the exact AANV30 window"
            )
        for field_name in (
            "causal_assets_evaluated",
            "eligible_assets",
            "minimum_eligible_assets",
            "future_top_quintile_size",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise AANV30FeasibilityError(f"{field_name} must be a non-negative integer")
        if self.causal_assets_evaluated < self.eligible_assets:
            raise AANV30FeasibilityError(
                "causal_assets_evaluated must be no smaller than eligible_assets"
            )
        if self.minimum_eligible_assets != MINIMUM_ELIGIBLE_ASSETS:
            raise AANV30FeasibilityError("minimum_eligible_assets differs from frozen policy")
        if self.future_top_quintile_size != FUTURE_TOP_QUINTILE_SIZE:
            raise AANV30FeasibilityError("future_top_quintile_size differs from frozen policy")
        if self.formula != AANV30_FORMULA:
            raise AANV30FeasibilityError("formula differs from frozen AANV30 definition")
        if not isinstance(self.blockers, tuple) or any(
            not isinstance(blocker, AANV30Blocker) for blocker in self.blockers
        ):
            raise AANV30FeasibilityError("blockers must be a typed immutable tuple")
        expected_order = tuple(
            sorted(self.blockers, key=lambda blocker: (blocker.severity.value, blocker.code))
        )
        if self.blockers != expected_order:
            raise AANV30FeasibilityError("blockers must use canonical severity/code order")
        blocker_keys = [(blocker.severity, blocker.code) for blocker in self.blockers]
        if len(blocker_keys) != len(set(blocker_keys)):
            raise AANV30FeasibilityError("duplicate blockers must be combined into one count")
        blocker_by_code = {blocker.code: blocker for blocker in self.blockers}
        for code in V1_REQUIRED_ATTESTATION_BLOCKER_CODES:
            blocker = blocker_by_code.get(code)
            if (
                blocker is None
                or blocker.severity is not BlockerSeverity.MISSING
                or blocker.count != 1
            ):
                raise AANV30FeasibilityError(
                    "schema v1 requires every immutable external-attestation blocker"
                )
        coverage_blocker = blocker_by_code.get("FEWER_THAN_100_ELIGIBLE_ASSETS")
        if self.eligible_assets < self.minimum_eligible_assets:
            if (
                coverage_blocker is None
                or coverage_blocker.severity is not BlockerSeverity.MISSING
                or coverage_blocker.count != 1
            ):
                raise AANV30FeasibilityError(
                    "eligible_assets below the minimum requires the coverage blocker"
                )
        elif coverage_blocker is not None:
            raise AANV30FeasibilityError("coverage blocker is inconsistent with eligible_assets")
        if (
            not isinstance(self.causal_evidence_sha256, str)
            or _SHA256_RE.fullmatch(self.causal_evidence_sha256) is None
        ):
            raise AANV30FeasibilityError(
                "causal_evidence_sha256 must be a lowercase SHA-256 digest"
            )

        has_hard = any(blocker.severity is BlockerSeverity.HARD for blocker in self.blockers)
        if has_hard:
            expected_status = AANV30FeasibilityStatus.NO_GO
        else:
            expected_status = AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE
        if self.status is not expected_status:
            raise AANV30FeasibilityError("status does not match the blocker severities")

    def sealed_content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "decision_at_utc": self.decision_at_utc,
            "expected_first_measurement_date": self.expected_first_measurement_date,
            "expected_last_measurement_date": self.expected_last_measurement_date,
            "causal_assets_evaluated": self.causal_assets_evaluated,
            "eligible_assets": self.eligible_assets,
            "minimum_eligible_assets": self.minimum_eligible_assets,
            "future_top_quintile_size": self.future_top_quintile_size,
            "formula": self.formula,
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "causal_evidence_sha256": self.causal_evidence_sha256,
            "real_money_authorized": self.real_money_authorized,
            "signal_generation_authorized": self.signal_generation_authorized,
            "pnl_evaluation_authorized": self.pnl_evaluation_authorized,
            "holdout_access_authorized": self.holdout_access_authorized,
            "network_access_authorized": self.network_access_authorized,
            "profitability_evidence": self.profitability_evidence,
        }

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "verdict_sha256": self.digest()}


def _canonical_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    canonical = (
        parsed.astimezone(UTC)
        .isoformat(timespec="microseconds" if parsed.microsecond else "seconds")
        .replace("+00:00", "Z")
    )
    return parsed.astimezone(UTC) if canonical == value else None


def _decision(value: str) -> tuple[str, datetime]:
    parsed = _canonical_utc(value)
    if parsed is None:
        raise AANV30FeasibilityError("decision_at_utc must be canonical UTC text ending in Z")
    return value, parsed


def _identity_state(identity: object) -> tuple[BlockerSeverity, str] | None:
    if not isinstance(identity, AANV30Identity):
        return BlockerSeverity.HARD, "IDENTITY_INVALID"
    missing = (
        identity.chain_id is None
        or identity.contract_or_native_id is None
        or identity.cmc_id is None
    )
    if missing:
        return BlockerSeverity.MISSING, "IDENTITY_MISSING"
    if (
        not isinstance(identity.chain_id, str)
        or not identity.chain_id
        or identity.chain_id.strip() != identity.chain_id
        or not isinstance(identity.contract_or_native_id, str)
        or not identity.contract_or_native_id
        or identity.contract_or_native_id.strip() != identity.contract_or_native_id
        or type(identity.cmc_id) is not int
        or identity.cmc_id <= 0
    ):
        return BlockerSeverity.HARD, "IDENTITY_INVALID"
    return None


def _identity_key(identity: AANV30Identity) -> tuple[str, str, int] | None:
    if _identity_state(identity) is not None:
        return None
    assert identity.chain_id is not None
    assert identity.contract_or_native_id is not None
    assert identity.cmc_id is not None
    return identity.chain_id, identity.contract_or_native_id, identity.cmc_id


def _text_state(
    value: object, missing_code: str, invalid_code: str
) -> tuple[BlockerSeverity, str] | None:
    if value is None:
        return BlockerSeverity.MISSING, missing_code
    if not isinstance(value, str) or not value or value.strip() != value:
        return BlockerSeverity.HARD, invalid_code
    return None


def _sha_state(value: object, *, missing_code: str) -> tuple[BlockerSeverity, str] | None:
    if value is None:
        return BlockerSeverity.MISSING, missing_code
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        return BlockerSeverity.HARD, "SOURCE_SHA256_INVALID"
    return None


def _timestamp_state(
    value: object,
    *,
    missing_code: str = "PIT_TIMESTAMP_MISSING",
) -> tuple[BlockerSeverity, str] | None:
    if value is None:
        return BlockerSeverity.MISSING, missing_code
    if _canonical_utc(value) is None:
        return BlockerSeverity.HARD, "PIT_TIMESTAMP_INVALID"
    return None


def _license_states(
    *,
    status: object,
    terms_sha256: object,
    verified_at_utc: object,
    decision: datetime,
) -> list[tuple[BlockerSeverity, str]]:
    problems: list[tuple[BlockerSeverity, str]] = []
    if status is None or status == CommercialLicenseStatus.UNKNOWN:
        problems.append((BlockerSeverity.MISSING, "LICENSE_STATUS_UNKNOWN"))
    elif status in {
        CommercialLicenseStatus.RESEARCH_ONLY,
        CommercialLicenseStatus.COMMERCIAL_USE_PROHIBITED,
    }:
        problems.append((BlockerSeverity.HARD, "COMMERCIAL_USE_NOT_PERMITTED"))
    elif status != CommercialLicenseStatus.COMMERCIAL_USE_PERMITTED:
        problems.append((BlockerSeverity.HARD, "LICENSE_STATUS_INVALID"))

    terms_state = _sha_state(terms_sha256, missing_code="LICENSE_TERMS_SHA256_MISSING")
    if terms_state is not None:
        severity, code = terms_state
        if code == "SOURCE_SHA256_INVALID":
            code = "LICENSE_TERMS_SHA256_INVALID"
        problems.append((severity, code))
    verified_state = _timestamp_state(verified_at_utc, missing_code="LICENSE_VERIFIED_AT_MISSING")
    if verified_state is not None:
        severity, code = verified_state
        if code == "PIT_TIMESTAMP_INVALID":
            code = "LICENSE_VERIFIED_AT_INVALID"
        problems.append((severity, code))
    else:
        verified = _canonical_utc(verified_at_utc)
        assert verified is not None
        if verified > decision:
            problems.append((BlockerSeverity.MISSING, "LICENSE_NOT_VERIFIED_BY_DECISION"))
    return problems


def _availability(value: object, decision: datetime) -> bool | None:
    """True when published by decision, False when future, None when unknowable."""

    if value is None:
        return None
    published = _canonical_utc(value)
    if published is None:
        return None
    return published <= decision


def _measurement_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _relevant_daily_rows(
    rows: tuple[DailyActiveAddressesEvidence, ...],
    *,
    first_day: date,
    last_day: date,
    decision: datetime,
) -> tuple[DailyActiveAddressesEvidence, ...]:
    relevant: list[DailyActiveAddressesEvidence] = []
    for row in rows:
        measured = _measurement_date(row.measurement_date)
        if measured is not None and not (first_day <= measured <= last_day):
            continue
        availability = _availability(row.published_at_utc, decision)
        if availability is False:
            continue
        relevant.append(row)
    return tuple(sorted(relevant, key=lambda item: canonical_dumps(item.to_dict())))


def _causal_market_cap(
    evidence: MarketCapAtDecisionEvidence | None,
    *,
    decision: datetime,
) -> MarketCapAtDecisionEvidence | None:
    if evidence is None:
        return None
    return evidence if _availability(evidence.published_at_utc, decision) is not False else None


def _record_problem(
    counter: Counter[tuple[BlockerSeverity, str]],
    problem: tuple[BlockerSeverity, str] | None,
) -> None:
    if problem is not None:
        counter[problem] += 1


def _validate_pit_sequence(
    *,
    effective_not_before: datetime,
    observed_at_utc: object,
    computed_at_utc: object,
    published_at_utc: object,
    decision: datetime,
    counter: Counter[tuple[BlockerSeverity, str]],
) -> None:
    for value in (observed_at_utc, computed_at_utc, published_at_utc):
        _record_problem(counter, _timestamp_state(value))
    observed = _canonical_utc(observed_at_utc)
    computed = _canonical_utc(computed_at_utc)
    published = _canonical_utc(published_at_utc)
    if observed is None or computed is None or published is None:
        return
    if not (effective_not_before <= observed <= computed <= published <= decision):
        counter[(BlockerSeverity.HARD, "PIT_TIMESTAMP_ORDER_INVALID")] += 1


def _validate_provenance(
    *,
    method_name: object,
    method_version: object,
    source_name: object,
    source_bytes_sha256: object,
    counter: Counter[tuple[BlockerSeverity, str]],
) -> None:
    _record_problem(
        counter,
        _text_state(method_name, "METHOD_NAME_MISSING", "METHOD_NAME_INVALID"),
    )
    _record_problem(
        counter,
        _text_state(method_version, "METHOD_VERSION_MISSING", "METHOD_VERSION_INVALID"),
    )
    _record_problem(
        counter,
        _text_state(source_name, "SOURCE_NAME_MISSING", "SOURCE_NAME_INVALID"),
    )
    _record_problem(
        counter,
        _sha_state(source_bytes_sha256, missing_code="SOURCE_SHA256_MISSING"),
    )


def _validate_daily_row(
    row: DailyActiveAddressesEvidence,
    *,
    asset_identity: AANV30Identity,
    decision: datetime,
    counter: Counter[tuple[BlockerSeverity, str]],
) -> None:
    measured = _measurement_date(row.measurement_date)
    if row.measurement_date is None:
        counter[(BlockerSeverity.MISSING, "MEASUREMENT_DATE_MISSING")] += 1
    elif measured is None:
        counter[(BlockerSeverity.HARD, "MEASUREMENT_DATE_INVALID")] += 1

    if row.active_addresses is None:
        counter[(BlockerSeverity.MISSING, "ACTIVE_ADDRESSES_MISSING")] += 1
    elif type(row.active_addresses) is not int or row.active_addresses < 0:
        counter[(BlockerSeverity.HARD, "ACTIVE_ADDRESSES_INVALID")] += 1

    if (
        row.metric_definition is None
        or row.metric_definition == ActiveAddressMetricDefinition.UNKNOWN
    ):
        counter[(BlockerSeverity.MISSING, "ACTIVE_ADDRESS_DEFINITION_UNKNOWN")] += 1
    elif row.metric_definition == ActiveAddressMetricDefinition.WINDOW_UNIQUE_ACTIVE_ADDRESSES:
        counter[(BlockerSeverity.HARD, "WINDOW_UNIQUE_METRIC_REJECTED")] += 1
    elif row.metric_definition != ActiveAddressMetricDefinition.DAILY_ACTIVE_ADDRESSES:
        counter[(BlockerSeverity.HARD, "ACTIVE_ADDRESS_DEFINITION_INVALID")] += 1

    identity_problem = _identity_state(row.identity)
    _record_problem(counter, identity_problem)
    if (
        identity_problem is None
        and _identity_state(asset_identity) is None
        and row.identity != asset_identity
    ):
        counter[(BlockerSeverity.HARD, "IDENTITY_MISMATCH")] += 1

    if measured is not None:
        day_end = datetime.combine(measured + timedelta(days=1), time.min, tzinfo=UTC)
        _validate_pit_sequence(
            effective_not_before=day_end,
            observed_at_utc=row.observed_at_utc,
            computed_at_utc=row.computed_at_utc,
            published_at_utc=row.published_at_utc,
            decision=decision,
            counter=counter,
        )
    else:
        for value in (row.observed_at_utc, row.computed_at_utc, row.published_at_utc):
            _record_problem(counter, _timestamp_state(value))

    _validate_provenance(
        method_name=row.method_name,
        method_version=row.method_version,
        source_name=row.source_name,
        source_bytes_sha256=row.source_bytes_sha256,
        counter=counter,
    )
    for problem in _license_states(
        status=row.license_status,
        terms_sha256=row.license_terms_sha256,
        verified_at_utc=row.license_verified_at_utc,
        decision=decision,
    ):
        counter[problem] += 1


def _validate_market_cap(
    evidence: MarketCapAtDecisionEvidence | None,
    *,
    asset_identity: AANV30Identity,
    decision_text: str,
    decision: datetime,
    counter: Counter[tuple[BlockerSeverity, str]],
) -> None:
    if evidence is None:
        counter[(BlockerSeverity.MISSING, "MARKET_CAP_AT_DECISION_MISSING")] += 1
        return
    identity_problem = _identity_state(evidence.identity)
    _record_problem(counter, identity_problem)
    if (
        identity_problem is None
        and _identity_state(asset_identity) is None
        and evidence.identity != asset_identity
    ):
        counter[(BlockerSeverity.HARD, "IDENTITY_MISMATCH")] += 1

    if evidence.effective_at_utc is None:
        counter[(BlockerSeverity.MISSING, "MARKET_CAP_EFFECTIVE_AT_MISSING")] += 1
    elif _canonical_utc(evidence.effective_at_utc) is None:
        counter[(BlockerSeverity.HARD, "MARKET_CAP_EFFECTIVE_AT_INVALID")] += 1
    elif evidence.effective_at_utc != decision_text:
        counter[(BlockerSeverity.HARD, "MARKET_CAP_NOT_AT_DECISION")] += 1

    if evidence.market_cap_usd is None:
        counter[(BlockerSeverity.MISSING, "MARKET_CAP_VALUE_MISSING")] += 1
    elif not isinstance(evidence.market_cap_usd, str):
        counter[(BlockerSeverity.HARD, "MARKET_CAP_VALUE_INVALID")] += 1
    else:
        try:
            value = Decimal(evidence.market_cap_usd)
        except InvalidOperation:
            value = Decimal("NaN")
        rendered = ""
        if value.is_finite():
            rendered = format(value, "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
        if not value.is_finite() or value <= 0 or rendered != evidence.market_cap_usd:
            counter[(BlockerSeverity.HARD, "MARKET_CAP_VALUE_INVALID")] += 1

    _validate_pit_sequence(
        effective_not_before=decision,
        observed_at_utc=evidence.observed_at_utc,
        computed_at_utc=evidence.computed_at_utc,
        published_at_utc=evidence.published_at_utc,
        decision=decision,
        counter=counter,
    )
    _validate_provenance(
        method_name=evidence.method_name,
        method_version=evidence.method_version,
        source_name=evidence.source_name,
        source_bytes_sha256=evidence.source_bytes_sha256,
        counter=counter,
    )
    for problem in _license_states(
        status=evidence.license_status,
        terms_sha256=evidence.license_terms_sha256,
        verified_at_utc=evidence.license_verified_at_utc,
        decision=decision,
    ):
        counter[problem] += 1


def evaluate_aanv30_data_feasibility(
    assets: tuple[AANV30AssetEvidence, ...],
    *,
    decision_at_utc: str,
) -> AANV30FeasibilityVerdict:
    """Evaluate only whether AANV30 data could support future preregistration.

    Evidence published after ``decision_at_utc`` and daily records outside the
    exact trailing window are excluded before hashing and evaluation.  Thus
    appending valid future data cannot change any output byte for this cutoff.
    Missing/unknown evidence yields ``INSUFFICIENT_EVIDENCE``; an explicit
    semantic, licensing, identity, integrity, comparability, or temporal
    contradiction yields ``NO_GO``.  Schema v1 always retains three external
    attestation blockers, so it has no positive return path.
    """

    decision_text, decision = _decision(decision_at_utc)
    if not isinstance(assets, tuple):
        raise AANV30FeasibilityError("assets must be an immutable tuple")
    last_day = decision.date() - timedelta(days=1)
    first_day = decision.date() - timedelta(days=AANV30_WINDOW_DAYS)

    causal_assets: list[
        tuple[
            AANV30AssetEvidence,
            tuple[DailyActiveAddressesEvidence, ...],
            MarketCapAtDecisionEvidence | None,
        ]
    ] = []
    for asset in assets:
        if not isinstance(asset, AANV30AssetEvidence):
            raise AANV30FeasibilityError("every asset must be AANV30AssetEvidence")
        if not isinstance(asset.daily_active_addresses, tuple):
            raise AANV30FeasibilityError("daily_active_addresses must be an immutable tuple")
        rows = _relevant_daily_rows(
            asset.daily_active_addresses,
            first_day=first_day,
            last_day=last_day,
            decision=decision,
        )
        market_cap = _causal_market_cap(asset.market_cap_at_decision, decision=decision)
        offered_availability = [
            _availability(row.published_at_utc, decision) for row in asset.daily_active_addresses
        ]
        if asset.market_cap_at_decision is not None:
            offered_availability.append(
                _availability(asset.market_cap_at_decision.published_at_utc, decision)
            )
        if offered_availability and all(value is False for value in offered_availability):
            # The whole offered asset is known only from publications after the cutoff.
            continue
        causal_assets.append((asset, rows, market_cap))

    causal_assets.sort(
        key=lambda item: canonical_dumps(
            {
                "identity": item[0].identity.to_dict(),
                "daily_active_addresses": [row.to_dict() for row in item[1]],
                "market_cap_at_decision": (item[2].to_dict() if item[2] is not None else None),
            }
        )
    )
    causal_payload = {
        "formula": AANV30_FORMULA,
        "decision_at_utc": decision_text,
        "expected_first_measurement_date": first_day.isoformat(),
        "expected_last_measurement_date": last_day.isoformat(),
        "assets": [
            {
                "identity": asset.identity.to_dict(),
                "daily_active_addresses": [row.to_dict() for row in rows],
                "market_cap_at_decision": cap.to_dict() if cap is not None else None,
            }
            for asset, rows, cap in causal_assets
        ],
    }
    causal_sha = sha256_of_text(canonical_dumps(causal_payload))

    global_problems: Counter[tuple[BlockerSeverity, str]] = Counter(
        {(BlockerSeverity.MISSING, code): 1 for code in V1_REQUIRED_ATTESTATION_BLOCKER_CODES}
    )
    eligible_assets = 0
    eligible_daily_method_keys: set[tuple[str, str, str]] = set()
    eligible_market_cap_method_keys: set[tuple[str, str, str]] = set()
    seen_full_identities: set[tuple[str, str, int]] = set()
    cmc_bindings: dict[int, tuple[str, str]] = {}
    chain_contract_bindings: dict[tuple[str, str], int] = {}

    for asset, rows, market_cap in causal_assets:
        local: Counter[tuple[BlockerSeverity, str]] = Counter()
        identity_problem = _identity_state(asset.identity)
        _record_problem(local, identity_problem)
        key = _identity_key(asset.identity)
        if key is not None:
            chain_id, contract_id, cmc_id = key
            if key in seen_full_identities:
                global_problems[(BlockerSeverity.HARD, "DUPLICATE_ASSET_IDENTITY")] += 1
            seen_full_identities.add(key)
            existing_chain_contract = cmc_bindings.get(cmc_id)
            if existing_chain_contract is not None and existing_chain_contract != (
                chain_id,
                contract_id,
            ):
                global_problems[(BlockerSeverity.HARD, "CMC_IDENTITY_COLLISION")] += 1
            cmc_bindings[cmc_id] = (chain_id, contract_id)
            chain_contract = (chain_id, contract_id)
            existing_cmc = chain_contract_bindings.get(chain_contract)
            if existing_cmc is not None and existing_cmc != cmc_id:
                global_problems[(BlockerSeverity.HARD, "CHAIN_CONTRACT_COLLISION")] += 1
            chain_contract_bindings[chain_contract] = cmc_id

        dates = [row.measurement_date for row in rows]
        expected_dates = {
            (first_day + timedelta(days=offset)).isoformat() for offset in range(AANV30_WINDOW_DAYS)
        }
        actual_valid_dates = {value for value in dates if _measurement_date(value) is not None}
        if len(rows) != AANV30_WINDOW_DAYS or actual_valid_dates != expected_dates:
            local[(BlockerSeverity.MISSING, "ACTIVE_ADDRESS_COVERAGE_NOT_EXACT")] += 1
        if len(actual_valid_dates) != len(
            [value for value in dates if _measurement_date(value) is not None]
        ):
            local[(BlockerSeverity.HARD, "DUPLICATE_DAILY_OBSERVATION")] += 1

        method_keys: set[tuple[str, str, str]] = set()
        for row in rows:
            _validate_daily_row(
                row,
                asset_identity=asset.identity,
                decision=decision,
                counter=local,
            )
            if all(
                isinstance(value, str) and value
                for value in (row.method_name, row.method_version, row.source_name)
            ):
                assert row.method_name is not None
                assert row.method_version is not None
                assert row.source_name is not None
                method_keys.add((row.method_name, row.method_version, row.source_name))
        if len(method_keys) > 1:
            local[(BlockerSeverity.HARD, "DAILY_METHOD_CHANGED_WITHIN_WINDOW")] += 1

        _validate_market_cap(
            market_cap,
            asset_identity=asset.identity,
            decision_text=decision_text,
            decision=decision,
            counter=local,
        )
        global_problems.update(local)
        if not local:
            eligible_assets += 1
            if len(method_keys) != 1:
                raise AANV30FeasibilityError(
                    "internally complete daily evidence must have exactly one method key"
                )
            eligible_daily_method_keys.update(method_keys)
            assert market_cap is not None
            assert market_cap.source_name is not None
            assert market_cap.method_name is not None
            assert market_cap.method_version is not None
            eligible_market_cap_method_keys.add(
                (
                    market_cap.source_name,
                    market_cap.method_name,
                    market_cap.method_version,
                )
            )

    if len(eligible_daily_method_keys) > 1:
        global_problems[(BlockerSeverity.HARD, "CROSS_ASSET_ACTIVE_ADDRESS_METHOD_MISMATCH")] += 1
    if len(eligible_market_cap_method_keys) > 1:
        global_problems[(BlockerSeverity.HARD, "CROSS_ASSET_MARKET_CAP_METHOD_MISMATCH")] += 1

    if eligible_assets < MINIMUM_ELIGIBLE_ASSETS:
        global_problems[(BlockerSeverity.MISSING, "FEWER_THAN_100_ELIGIBLE_ASSETS")] += 1

    has_hard = any(severity is BlockerSeverity.HARD for severity, _ in global_problems)
    if has_hard:
        status = AANV30FeasibilityStatus.NO_GO
    else:
        status = AANV30FeasibilityStatus.INSUFFICIENT_EVIDENCE

    blockers = tuple(
        AANV30Blocker(code=code, severity=severity, count=count)
        for (severity, code), count in sorted(
            global_problems.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
    )
    return AANV30FeasibilityVerdict(
        status=status,
        decision_at_utc=decision_text,
        expected_first_measurement_date=first_day.isoformat(),
        expected_last_measurement_date=last_day.isoformat(),
        causal_assets_evaluated=len(causal_assets),
        eligible_assets=eligible_assets,
        minimum_eligible_assets=MINIMUM_ELIGIBLE_ASSETS,
        future_top_quintile_size=FUTURE_TOP_QUINTILE_SIZE,
        formula=AANV30_FORMULA,
        blockers=blockers,
        causal_evidence_sha256=causal_sha,
    )


__all__ = [
    "AANV30_FEASIBILITY_SCHEMA_VERSION",
    "AANV30_FORMULA",
    "AANV30_WINDOW_DAYS",
    "FUTURE_TOP_QUINTILE_SIZE",
    "MINIMUM_ELIGIBLE_ASSETS",
    "V1_REQUIRED_ATTESTATION_BLOCKER_CODES",
    "AANV30AssetEvidence",
    "AANV30Blocker",
    "AANV30FeasibilityError",
    "AANV30FeasibilityStatus",
    "AANV30FeasibilityVerdict",
    "AANV30Identity",
    "ActiveAddressMetricDefinition",
    "BlockerSeverity",
    "CommercialLicenseStatus",
    "DailyActiveAddressesEvidence",
    "MarketCapAtDecisionEvidence",
    "evaluate_aanv30_data_feasibility",
]
