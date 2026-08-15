"""Offline development evaluator for the sealed SPY turn-of-month campaign.

The evaluator has no network, credential, broker, registry, or order-routing
path.  It accepts an externally content-addressed local bundle, verifies every
declared byte before parsing raw evidence, derives conservative quote fills,
and schema v1 can return only ``INSUFFICIENT_EVIDENCE`` because external data
authority is not cryptographically verified.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, DecimalException, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from zoneinfo import ZoneInfo

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_text
from quant_trade.research.prospective_spy_tom import (
    CALENDAR_ID,
    SPEC_SEAL,
    STRATEGY_ID,
    SYMBOL,
    ExplicitExchangeCalendar,
    SpyTomError,
    SpyTomSpec,
    TargetIntention,
    generate_spy_tom_targets,
)

VerdictStatus = Literal["INSUFFICIENT_EVIDENCE"]
SCHEMA_VERSION = 1
MANIFEST_SCHEMA = "alpaca_spy_sip_development_bundle_v2"
MARKET_COLLECTION_MODE = "EXACT_EVENT_WINDOWS_1556_1558_ET"
BOOTSTRAP_SEED = 20_260_814
BOOTSTRAP_REPETITIONS = 2_000
MINIMUM_PAIRED_MONTHS = 120
NORMAL_IMPACT_BPS_PER_SIDE = 1.0
STRESS_IMPACT_BPS_PER_SIDE = 5.0
MINIMUM_REGULATORY_SELL_BPS = 0.01
MINIMUM_PRICE_USD = Decimal("0.0001")
MAXIMUM_PRICE_USD = Decimal("10000000")
MINIMUM_SIZE = Decimal("0.000001")
MAXIMUM_SIZE = Decimal("1000000000")
MAXIMUM_DIVIDEND_PER_SHARE_USD = Decimal("10000")
MAXIMUM_SPLIT_RATIO = Decimal("1000")

_SCENARIO_CONSTRUCTION_TOKEN = object()
_VERDICT_CONSTRUCTION_TOKEN = object()

_NY = ZoneInfo("America/New_York")
_SAFE_FALLBACK_TIMESTAMP = datetime(1900, 1, 1, tzinfo=UTC)
_MANIFEST_ROLES = (
    "calendar",
    "quotes",
    "trades",
    "corporate_actions",
    "fees",
    "receipts",
)
_MANIFEST_KEYS = {
    "schema_version",
    "manifest_schema",
    "provider",
    "feed",
    "symbol",
    "calendar_id",
    "calendar_source",
    "start",
    "end",
    "captured_at_utc",
    "development_only",
    "files",
}
_FILE_KEYS = {"path", "sha256"}
_RECEIPT_KEYS = {
    "schema_version",
    "receipt_id",
    "provider",
    "source_kind",
    "artifact_role",
    "endpoint",
    "request_parameters",
    "http_status",
    "captured_at_utc",
    "raw_path",
    "raw_sha256",
}
_RECEIPT_ENDPOINTS = {
    "calendar": "/v2/calendar",
    "quotes": "/v2/stocks/SPY/quotes",
    "trades": "/v2/stocks/SPY/trades",
    "corporate_actions": "/v2/corporate_actions/announcements",
    "fees": "/disclosures/fees",
}


class SpyTomDevelopmentEvidenceError(ValueError):
    """A bundle or evaluation-boundary violation that must fail closed."""


def _finite_nonnegative(name: str, value: Any, *, maximum: float) -> float:
    if type(value) not in (int, float):
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_FINITE")
    try:
        decimal_value = Decimal(str(value))
    except DecimalException as exc:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_FINITE") from exc
    if not decimal_value.is_finite() or decimal_value < 0 or decimal_value > Decimal(str(maximum)):
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_OUTSIDE_ALLOWED_RANGE")
    return float(decimal_value)


@dataclass(frozen=True)
class ScenarioSnapshot:
    """Metrics re-derived from fills for one immutable cost scenario."""

    impact_bps_per_side: float
    fee_multiplier: float
    paired_months: int
    primary_total_return: float
    control_total_return: float
    primary_mean_monthly_return: float
    control_mean_monthly_return: float
    mean_paired_excess: float
    primary_max_drawdown: float
    control_max_drawdown: float
    bootstrap_year_count: int
    bootstrap_repetitions: int
    bootstrap_seed: int
    paired_excess_ci_low: float
    paired_excess_ci_high: float
    primary_total_fees_usd: float
    control_total_fees_usd: float
    diagnostic_only: bool = field(default=True, init=False)
    _construction_token: InitVar[object] = None

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _SCENARIO_CONSTRUCTION_TOKEN:
            raise ValueError("ScenarioSnapshot may only be constructed by the sealed evaluator")
        if (self.impact_bps_per_side, self.fee_multiplier) not in {
            (NORMAL_IMPACT_BPS_PER_SIDE, 1.0),
            (STRESS_IMPACT_BPS_PER_SIDE, 2.0),
        }:
            raise ValueError("scenario cost assumptions are not sealed")
        if self.paired_months < MINIMUM_PAIRED_MONTHS or self.bootstrap_year_count < 2:
            raise ValueError("scenario requires the sealed paired-month and year minimums")
        if self.bootstrap_repetitions != BOOTSTRAP_REPETITIONS:
            raise ValueError("scenario bootstrap repetitions are sealed")
        if self.bootstrap_seed != BOOTSTRAP_SEED:
            raise ValueError("scenario bootstrap seed is sealed")
        if not self.diagnostic_only:
            raise ValueError("v1 scenario metrics must remain diagnostic only")
        for name, value in self.to_dict().items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"scenario {name} must be finite")
        if not -1.0 <= self.primary_max_drawdown <= 0.0 or not (
            -1.0 <= self.control_max_drawdown <= 0.0
        ):
            raise ValueError("scenario drawdowns must be fractions from -1 through 0")
        if self.paired_excess_ci_low > self.paired_excess_ci_high:
            raise ValueError("scenario bootstrap interval is inverted")
        if self.primary_total_fees_usd < 0.0 or self.control_total_fees_usd < 0.0:
            raise ValueError("scenario fees cannot be negative")

    def to_dict(self) -> dict[str, float | int]:
        return {
            "impact_bps_per_side": self.impact_bps_per_side,
            "fee_multiplier": self.fee_multiplier,
            "paired_months": self.paired_months,
            "primary_total_return": self.primary_total_return,
            "control_total_return": self.control_total_return,
            "primary_mean_monthly_return": self.primary_mean_monthly_return,
            "control_mean_monthly_return": self.control_mean_monthly_return,
            "mean_paired_excess": self.mean_paired_excess,
            "primary_max_drawdown": self.primary_max_drawdown,
            "control_max_drawdown": self.control_max_drawdown,
            "bootstrap_year_count": self.bootstrap_year_count,
            "bootstrap_repetitions": self.bootstrap_repetitions,
            "bootstrap_seed": self.bootstrap_seed,
            "paired_excess_ci_low": self.paired_excess_ci_low,
            "paired_excess_ci_high": self.paired_excess_ci_high,
            "primary_total_fees_usd": self.primary_total_fees_usd,
            "control_total_fees_usd": self.control_total_fees_usd,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class SpyTomDevelopmentVerdict:
    """Content-addressed development report with no promotional state."""

    status: VerdictStatus
    strategy_id: str
    expected_manifest_sha256: str
    development_cutoff: str
    as_of: str
    eligible_pairs: int
    completed_pairs: int
    evidence_hashes: Mapping[str, str]
    scenarios: Mapping[str, ScenarioSnapshot]
    reasons: Sequence[str]
    schema_version: int = SCHEMA_VERSION
    development_only: bool = field(default=True, init=False)
    metrics_diagnostic_only: bool = field(default=True, init=False)
    external_data_authority_verified: bool = field(default=False, init=False)
    pass_allowed: bool = field(default=False, init=False)
    promotion_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    real_money_authorized: bool = field(default=False, init=False)
    bank_transfer_authorized: bool = field(default=False, init=False)
    _construction_token: InitVar[object] = None

    def __post_init__(self, _construction_token: object) -> None:
        if _construction_token is not _VERDICT_CONSTRUCTION_TOKEN:
            raise ValueError("SpyTomDevelopmentVerdict may only come from the sealed evaluator")
        if self.status != "INSUFFICIENT_EVIDENCE":
            raise ValueError("v1 lacks external authority and can only be INSUFFICIENT_EVIDENCE")
        if self.strategy_id != STRATEGY_ID or self.schema_version != SCHEMA_VERSION:
            raise ValueError("SPY TOM development verdict identity is sealed")
        if not self.reasons or any(
            not isinstance(reason, str) or not reason for reason in self.reasons
        ):
            raise ValueError("SPY TOM development verdict requires at least one reason")
        if self.eligible_pairs < 0 or not 0 <= self.completed_pairs <= self.eligible_pairs:
            raise ValueError("SPY TOM development pair counts are invalid")
        if (
            not self.development_only
            or not self.metrics_diagnostic_only
            or self.external_data_authority_verified
            or self.pass_allowed
            or self.promotion_authorized
            or self.live_execution_authorized
            or self.real_money_authorized
            or self.bank_transfer_authorized
        ):
            raise ValueError("development evidence cannot authorize PASS, promotion, or money")
        if "EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED" not in self.reasons:
            raise ValueError("v1 verdict must disclose its external-authority blocker")
        if self.expected_manifest_sha256 != "INVALID":
            _sha256("report_expected_manifest", self.expected_manifest_sha256)
        for name, digest in self.evidence_hashes.items():
            if not isinstance(name, str) or not name:
                raise ValueError("evidence hash names must be non-empty strings")
            _sha256(f"report_{name}", digest)
        if (
            "manifest" in self.evidence_hashes
            and self.evidence_hashes["manifest"] != self.expected_manifest_sha256
        ):
            raise ValueError("report manifest hash contradicts its expected content address")
        cutoff = _iso_timestamp("report_development_cutoff", self.development_cutoff)
        observed_as_of = _iso_timestamp("report_as_of", self.as_of)
        if cutoff > observed_as_of:
            raise ValueError("report cutoff cannot be after as_of")
        if self.scenarios:
            if set(self.scenarios) != {"normal", "stress_5bps_2x_fees"}:
                raise ValueError("report scenario names are sealed")
            normal = self.scenarios["normal"]
            stress = self.scenarios["stress_5bps_2x_fees"]
            if (
                normal.impact_bps_per_side != NORMAL_IMPACT_BPS_PER_SIDE
                or normal.fee_multiplier != 1.0
                or stress.impact_bps_per_side != STRESS_IMPACT_BPS_PER_SIDE
                or stress.fee_multiplier != 2.0
                or normal.paired_months != self.completed_pairs
                or stress.paired_months != self.completed_pairs
                or self.completed_pairs < MINIMUM_PAIRED_MONTHS
            ):
                raise ValueError("report scenarios contradict sealed costs or pair counts")
        object.__setattr__(self, "evidence_hashes", MappingProxyType(dict(self.evidence_hashes)))
        object.__setattr__(self, "scenarios", MappingProxyType(dict(self.scenarios)))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "strategy_id": self.strategy_id,
            "expected_manifest_sha256": self.expected_manifest_sha256,
            "development_cutoff": self.development_cutoff,
            "as_of": self.as_of,
            "eligible_pairs": self.eligible_pairs,
            "completed_pairs": self.completed_pairs,
            "evidence_hashes": dict(sorted(self.evidence_hashes.items())),
            "scenarios": {
                name: scenario.to_dict() for name, scenario in sorted(self.scenarios.items())
            },
            "reasons": list(self.reasons),
            "development_only": self.development_only,
            "metrics_diagnostic_only": self.metrics_diagnostic_only,
            "external_data_authority_verified": self.external_data_authority_verified,
            "pass_allowed": self.pass_allowed,
            "promotion_authorized": self.promotion_authorized,
            "live_execution_authorized": self.live_execution_authorized,
            "real_money_authorized": self.real_money_authorized,
            "bank_transfer_authorized": self.bank_transfer_authorized,
        }

    def report_sha256(self) -> str:
        return sha256_of_text(canonical_dumps(self.to_dict()))


@dataclass(frozen=True)
class _Bundle:
    manifest: Mapping[str, Any]
    manifest_sha256: str
    raw_bytes: Mapping[str, bytes]
    raw_hashes: Mapping[str, str]
    start: datetime
    end: datetime
    captured_at: datetime


@dataclass(frozen=True)
class _Quote:
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    sequence: int


@dataclass(frozen=True)
class _Trade:
    timestamp: datetime
    sequence: int


@dataclass(frozen=True)
class _SessionHours:
    opened: datetime
    closed: datetime


@dataclass(frozen=True)
class _CorporateAction:
    action_id: str
    action_type: str
    effective_date: date
    announced_at: datetime
    revised_at: datetime
    amount_per_share: Decimal | None
    split_ratio: Decimal | None


@dataclass(frozen=True)
class _FeeRate:
    effective_start: date
    effective_end: date
    commission_bps_per_side: Decimal
    regulatory_sell_bps: Decimal
    regulatory_sell_fixed_cents: int


@dataclass(frozen=True)
class _Fill:
    target: TargetIntention
    price: Decimal
    quote_count: int
    trade_count: int


@dataclass(frozen=True)
class _Episode:
    net_return: float
    fees_usd: float


def _iso_timestamp(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_AN_ISO_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE")
        normalized = parsed.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_AN_ISO_TIMESTAMP") from exc
    if not 1900 <= normalized.year <= 2100:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_OUTSIDE_SUPPORTED_YEAR_RANGE")
    return normalized


def _aware_input(name: str, value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE")
    try:
        normalized = value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_OUTSIDE_SUPPORTED_RANGE") from exc
    if not 1900 <= normalized.year <= 2100:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_OUTSIDE_SUPPORTED_YEAR_RANGE")
    return normalized


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_SHA256_IS_INVALID")
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _strict_json(payload: str) -> Any:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=pairs_hook, parse_constant=_reject_constant)


def _canonical_jsonl(payload: bytes, role: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpyTomDevelopmentEvidenceError(f"{role.upper()}_IS_NOT_UTF8") from exc
    if not text or not text.endswith("\n") or "\r" in text:
        raise SpyTomDevelopmentEvidenceError(f"{role.upper()}_IS_NOT_CANONICAL_JSONL")
    rows: list[dict[str, Any]] = []
    try:
        for line in text.splitlines():
            if not line:
                raise ValueError("blank JSONL line")
            row = _strict_json(line)
            if not isinstance(row, dict) or canonical_dumps(row) != line:
                raise ValueError("noncanonical JSONL object")
            rows.append(row)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SpyTomDevelopmentEvidenceError(f"{role.upper()}_IS_NOT_CANONICAL_JSONL") from exc
    if not rows:
        raise SpyTomDevelopmentEvidenceError(f"{role.upper()}_IS_EMPTY")
    return rows


def _safe_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_PATH_IS_INVALID")
    path = Path(relative)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_PATH_IS_INVALID")
    resolved_root = root.resolve()
    candidate = (resolved_root / path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_ESCAPES_BUNDLE") from exc
    return candidate


def _load_bundle(
    root: Path,
    expected_manifest_sha256: str,
    *,
    cutoff: datetime,
    as_of: datetime,
) -> _Bundle:
    expected = _sha256("expected_manifest", expected_manifest_sha256)
    try:
        manifest_bytes = (root / "manifest.json").read_bytes()
    except OSError as exc:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_MISSING_OR_UNREADABLE") from exc
    manifest_sha = sha256_of_bytes(manifest_bytes)
    if manifest_sha != expected:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_SHA256_MISMATCH")
    try:
        manifest = _strict_json(manifest_bytes.decode("utf-8"))
        if (
            not isinstance(manifest, dict)
            or canonical_dumps(manifest).encode("utf-8") != manifest_bytes
        ):
            raise ValueError("manifest is not canonical")
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_IS_NOT_CANONICAL_JSON") from exc
    if set(manifest) != _MANIFEST_KEYS:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_SCHEMA_FIELDS_MISMATCH")
    exact_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "provider": "ALPACA",
        "feed": "SIP",
        "symbol": SYMBOL,
        "calendar_id": CALENDAR_ID,
        "calendar_source": "ALPACA_CALENDAR_API",
        "development_only": True,
    }
    for name, expected_value in exact_manifest.items():
        if manifest.get(name) != expected_value or type(manifest.get(name)) is not type(
            expected_value
        ):
            raise SpyTomDevelopmentEvidenceError(f"MANIFEST_{name.upper()}_MISMATCH")
    start = _iso_timestamp("manifest_start", manifest["start"])
    end = _iso_timestamp("manifest_end", manifest["end"])
    captured = _iso_timestamp("manifest_captured_at", manifest["captured_at_utc"])
    if not start < end:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_WINDOW_IS_INVALID")
    if end != cutoff:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_END_DOES_NOT_EQUAL_HARD_CUTOFF")
    if end > as_of:
        raise SpyTomDevelopmentEvidenceError("DEVELOPMENT_CUTOFF_IS_AFTER_AS_OF")
    if captured < end:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_CAPTURE_PRECEDES_DATA_END")
    if captured > as_of:
        raise SpyTomDevelopmentEvidenceError("MANIFEST_CAPTURE_IS_AFTER_AS_OF")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_MANIFEST_ROLES):
        raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_ROLES_MISMATCH")
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for role in _MANIFEST_ROLES:
        entry = files[role]
        if not isinstance(entry, dict) or set(entry) != _FILE_KEYS:
            raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_ENTRY_MISMATCH")
        paths[role] = _safe_file(root, entry["path"])
        hashes[role] = _sha256(role, entry["sha256"])
    if len({path.resolve() for path in paths.values()}) != len(paths):
        raise SpyTomDevelopmentEvidenceError("MANIFEST_FILE_PATHS_MUST_BE_DISTINCT")

    # Read and hash every declared artifact before any one of them is parsed.
    raw_bytes: dict[str, bytes] = {}
    for role in _MANIFEST_ROLES:
        try:
            payload = paths[role].read_bytes()
        except OSError as exc:
            raise SpyTomDevelopmentEvidenceError(f"RAW_{role.upper()}_MISSING") from exc
        if sha256_of_bytes(payload) != hashes[role]:
            raise SpyTomDevelopmentEvidenceError(f"RAW_{role.upper()}_SHA256_MISMATCH")
        raw_bytes[role] = payload
    return _Bundle(
        manifest=MappingProxyType(manifest),
        manifest_sha256=manifest_sha,
        raw_bytes=MappingProxyType(raw_bytes),
        raw_hashes=MappingProxyType(hashes),
        start=start,
        end=end,
        captured_at=captured,
    )


def _market_event_window_scope(
    calendar: ExplicitExchangeCalendar,
    bundle: _Bundle,
) -> dict[str, Any]:
    grouped = calendar.sessions_by_month()
    sessions = calendar.session_by_date()
    event_dates: set[date] = set()
    for anchor, following in zip(
        calendar.complete_months,
        calendar.complete_months[1:],
        strict=False,
    ):
        anchor_sessions = grouped[anchor]
        following_sessions = grouped[following]
        pair_dates = (
            anchor_sessions[-2],
            following_sessions[2],
            following_sessions[7],
            following_sessions[11],
        )
        if all(
            sessions[session_date].close_timestamp.astimezone(_NY).time().replace(tzinfo=None)
            >= time(15, 58)
            for session_date in pair_dates
        ):
            event_dates.update(pair_dates)
    windows = [
        {
            "end": datetime.combine(session_date, time(15, 58), tzinfo=_NY)
            .astimezone(UTC)
            .isoformat(),
            "start": datetime.combine(session_date, time(15, 56), tzinfo=_NY)
            .astimezone(UTC)
            .isoformat(),
        }
        for session_date in sorted(event_dates)
    ]
    return {
        "collection_mode": MARKET_COLLECTION_MODE,
        "event_window_count": len(windows),
        "event_windows_sha256": sha256_of_bytes(canonical_dumps(windows).encode("utf-8")),
        "feed": "SIP",
        "limit": 10_000,
        "scope_end": bundle.manifest["end"],
        "scope_start": bundle.manifest["start"],
        "sort": "asc",
        "symbol": SYMBOL,
    }


def _verify_receipts(
    bundle: _Bundle,
    calendar: ExplicitExchangeCalendar,
    *,
    as_of: datetime,
) -> None:
    rows = _canonical_jsonl(bundle.raw_bytes["receipts"], "receipts")
    if len(rows) != 5:
        raise SpyTomDevelopmentEvidenceError("RECEIPTS_REQUIRE_EXACTLY_FIVE_SOURCE_RECORDS")
    files = bundle.manifest["files"]
    observed_roles: set[str] = set()
    observed_receipt_ids: set[str] = set()
    for row in rows:
        if set(row) != _RECEIPT_KEYS:
            raise SpyTomDevelopmentEvidenceError("RECEIPT_SCHEMA_FIELDS_MISMATCH")
        role = row.get("artifact_role")
        source_roles = {"calendar", "quotes", "trades", "corporate_actions", "fees"}
        if not isinstance(role, str) or role not in source_roles or role in observed_roles:
            raise SpyTomDevelopmentEvidenceError("RECEIPT_ARTIFACT_ROLES_MISMATCH")
        observed_roles.add(role)
        exact = {
            "schema_version": SCHEMA_VERSION,
            "provider": "ALPACA",
            "source_kind": (
                "ALPACA_OFFICIAL_DOCUMENT_CAPTURE" if role == "fees" else "ALPACA_HISTORICAL_API"
            ),
            "endpoint": _RECEIPT_ENDPOINTS[role],
            "http_status": 200,
            "raw_path": files[role]["path"],
            "raw_sha256": files[role]["sha256"],
        }
        for name, expected in exact.items():
            if row.get(name) != expected or type(row.get(name)) is not type(expected):
                raise SpyTomDevelopmentEvidenceError("RECEIPT_SOURCE_OR_BINDING_MISMATCH")
        receipt_id = row.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id or receipt_id in observed_receipt_ids:
            raise SpyTomDevelopmentEvidenceError("RECEIPT_ID_IS_MISSING")
        observed_receipt_ids.add(receipt_id)
        captured = _iso_timestamp("receipt_captured_at", row["captured_at_utc"])
        if captured < bundle.end or captured > as_of or captured > bundle.captured_at:
            raise SpyTomDevelopmentEvidenceError("RECEIPT_CAPTURE_OUTSIDE_CAUSAL_WINDOW")
        params = row.get("request_parameters")
        if not isinstance(params, dict):
            raise SpyTomDevelopmentEvidenceError("RECEIPT_REQUEST_PARAMETERS_INVALID")
        expected_params: dict[str, Any]
        if role == "calendar":
            expected_params = {
                "calendar_id": CALENDAR_ID,
                "start_date": bundle.start.astimezone(_NY).date().isoformat(),
                "end_date": bundle.end.astimezone(_NY).date().isoformat(),
            }
        elif role in {"quotes", "trades"}:
            expected_params = _market_event_window_scope(calendar, bundle)
        elif role == "corporate_actions":
            expected_params = {
                "action_types": ["cash_dividend", "split"],
                "end": bundle.manifest["end"],
                "start": bundle.manifest["start"],
                "symbol": SYMBOL,
            }
        else:
            expected_params = {
                "effective_end": bundle.end.astimezone(_NY).date().isoformat(),
                "effective_start": bundle.start.astimezone(_NY).date().isoformat(),
                "scope": "SPY_EQUITY_AND_REGULATORY_FEES",
            }
        if canonical_dumps(params) != canonical_dumps(expected_params):
            raise SpyTomDevelopmentEvidenceError("RECEIPT_REQUEST_WINDOW_OR_SCOPE_MISMATCH")
    if observed_roles != {"calendar", "quotes", "trades", "corporate_actions", "fees"}:
        raise SpyTomDevelopmentEvidenceError("RECEIPT_ARTIFACT_ROLES_MISMATCH")


def _parse_calendar(
    bundle: _Bundle,
    calendar: ExplicitExchangeCalendar,
) -> Mapping[date, _SessionHours]:
    rows = _canonical_jsonl(bundle.raw_bytes["calendar"], "calendar")
    expected_dates = tuple(calendar.session_dates)
    observed_dates: list[date] = []
    hours: dict[date, _SessionHours] = {}
    for row in rows:
        if set(row) != {"date", "open", "close"}:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_ROW_SCHEMA_MISMATCH")
        try:
            session_date = date.fromisoformat(str(row["date"]))
        except ValueError as exc:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_DATE_IS_INVALID") from exc
        opened = _iso_timestamp("calendar_open", row["open"])
        closed = _iso_timestamp("calendar_close", row["close"])
        open_local = opened.astimezone(_NY)
        close_local = closed.astimezone(_NY)
        if open_local.date() != session_date or close_local.date() != session_date:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_TIMESTAMP_DATE_MISMATCH")
        if open_local.time().replace(tzinfo=None) != time(9, 30) or close_local.time().replace(
            tzinfo=None
        ) not in {time(13, 0), time(16, 0)}:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_SESSION_HOURS_INVALID")
        if not opened < closed:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_SESSION_WINDOW_INVALID")
        observed_dates.append(session_date)
        hours[session_date] = _SessionHours(opened=opened, closed=closed)
    if tuple(observed_dates) != expected_dates:
        raise SpyTomDevelopmentEvidenceError("CALENDAR_DATES_DO_NOT_MATCH_CALLER_ATTESTATION")
    if (
        hours[expected_dates[0]].opened != bundle.start
        or hours[expected_dates[-1]].closed != bundle.end
    ):
        raise SpyTomDevelopmentEvidenceError("CALENDAR_BOUNDS_DO_NOT_MATCH_MANIFEST")
    if any(value.opened < bundle.start for value in hours.values()) or any(
        value.closed > bundle.end for value in hours.values()
    ):
        raise SpyTomDevelopmentEvidenceError("CALENDAR_CONTAINS_POST_CUTOFF_OR_PRESTART_DATA")
    declared = calendar.session_by_date()
    for session_date, value in hours.items():
        session = declared[session_date]
        if (
            session.open_timestamp.astimezone(UTC) != value.opened
            or session.close_timestamp.astimezone(UTC) != value.closed
        ):
            raise SpyTomDevelopmentEvidenceError("CALENDAR_HOURS_DO_NOT_MATCH_CALLER_ATTESTATION")
    return MappingProxyType(hours)


def _bounded_decimal(
    name: str,
    value: Any,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    if isinstance(value, bool) or type(value) not in (int, float, str):
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_INVALID")
    try:
        number = Decimal(str(value))
    except Exception as exc:  # Decimal raises several concrete conversion errors.
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_INVALID") from exc
    if not number.is_finite() or number < minimum or number > maximum:
        raise SpyTomDevelopmentEvidenceError(f"{name.upper()}_IS_INVALID")
    return number


def _parse_quotes(bundle: _Bundle) -> tuple[_Quote, ...]:
    rows = _canonical_jsonl(bundle.raw_bytes["quotes"], "quotes")
    quotes: list[_Quote] = []
    prior: tuple[datetime, int] | None = None
    prior_sequence = -1
    for row in rows:
        if set(row) != {
            "timestamp",
            "symbol",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "sequence",
        }:
            raise SpyTomDevelopmentEvidenceError("QUOTE_ROW_SCHEMA_MISMATCH")
        if row["symbol"] != SYMBOL:
            raise SpyTomDevelopmentEvidenceError("QUOTE_SYMBOL_IS_NOT_SPY")
        timestamp = _iso_timestamp("quote_timestamp", row["timestamp"])
        sequence = row["sequence"]
        if type(sequence) is not int or sequence < 0:
            raise SpyTomDevelopmentEvidenceError("QUOTE_SEQUENCE_IS_INVALID")
        key = (timestamp, sequence)
        if prior is not None and key <= prior:
            raise SpyTomDevelopmentEvidenceError("QUOTES_ARE_NOT_STRICTLY_ORDERED")
        if sequence <= prior_sequence:
            raise SpyTomDevelopmentEvidenceError("QUOTE_SEQUENCE_IS_NOT_STRICTLY_INCREASING")
        if timestamp < bundle.start or timestamp > bundle.end:
            raise SpyTomDevelopmentEvidenceError("QUOTE_CONTAINS_POST_CUTOFF_OR_PRESTART_DATA")
        bid = _bounded_decimal(
            "quote_bid", row["bid_price"], minimum=MINIMUM_PRICE_USD, maximum=MAXIMUM_PRICE_USD
        )
        ask = _bounded_decimal(
            "quote_ask", row["ask_price"], minimum=MINIMUM_PRICE_USD, maximum=MAXIMUM_PRICE_USD
        )
        _bounded_decimal(
            "quote_bid_size", row["bid_size"], minimum=MINIMUM_SIZE, maximum=MAXIMUM_SIZE
        )
        _bounded_decimal(
            "quote_ask_size", row["ask_size"], minimum=MINIMUM_SIZE, maximum=MAXIMUM_SIZE
        )
        if ask < bid:
            raise SpyTomDevelopmentEvidenceError("QUOTE_MARKET_IS_CROSSED")
        quotes.append(_Quote(timestamp=timestamp, bid=bid, ask=ask, sequence=sequence))
        prior = key
        prior_sequence = sequence
    return tuple(quotes)


def _parse_trades(bundle: _Bundle) -> tuple[_Trade, ...]:
    rows = _canonical_jsonl(bundle.raw_bytes["trades"], "trades")
    trades: list[_Trade] = []
    prior: tuple[datetime, int] | None = None
    prior_sequence = -1
    for row in rows:
        if set(row) != {"timestamp", "symbol", "price", "size", "exchange", "sequence"}:
            raise SpyTomDevelopmentEvidenceError("TRADE_ROW_SCHEMA_MISMATCH")
        if row["symbol"] != SYMBOL:
            raise SpyTomDevelopmentEvidenceError("TRADE_SYMBOL_IS_NOT_SPY")
        if not isinstance(row["exchange"], str) or not row["exchange"]:
            raise SpyTomDevelopmentEvidenceError("TRADE_EXCHANGE_IS_INVALID")
        timestamp = _iso_timestamp("trade_timestamp", row["timestamp"])
        sequence = row["sequence"]
        if type(sequence) is not int or sequence < 0:
            raise SpyTomDevelopmentEvidenceError("TRADE_SEQUENCE_IS_INVALID")
        key = (timestamp, sequence)
        if prior is not None and key <= prior:
            raise SpyTomDevelopmentEvidenceError("TRADES_ARE_NOT_STRICTLY_ORDERED")
        if sequence <= prior_sequence:
            raise SpyTomDevelopmentEvidenceError("TRADE_SEQUENCE_IS_NOT_STRICTLY_INCREASING")
        if timestamp < bundle.start or timestamp > bundle.end:
            raise SpyTomDevelopmentEvidenceError("TRADE_CONTAINS_POST_CUTOFF_OR_PRESTART_DATA")
        _bounded_decimal(
            "trade_price", row["price"], minimum=MINIMUM_PRICE_USD, maximum=MAXIMUM_PRICE_USD
        )
        _bounded_decimal("trade_size", row["size"], minimum=MINIMUM_SIZE, maximum=MAXIMUM_SIZE)
        trades.append(_Trade(timestamp=timestamp, sequence=sequence))
        prior = key
        prior_sequence = sequence
    return tuple(trades)


def _verify_market_session_dates(
    quotes: Sequence[_Quote],
    trades: Sequence[_Trade],
    session_hours: Mapping[date, _SessionHours],
) -> None:
    valid_dates = set(session_hours)
    if any(quote.timestamp.astimezone(_NY).date() not in valid_dates for quote in quotes):
        raise SpyTomDevelopmentEvidenceError("QUOTE_DATE_IS_NOT_IN_ATTESTED_XNYS_CALENDAR")
    if any(trade.timestamp.astimezone(_NY).date() not in valid_dates for trade in trades):
        raise SpyTomDevelopmentEvidenceError("TRADE_DATE_IS_NOT_IN_ATTESTED_XNYS_CALENDAR")


def _parse_corporate_actions(
    bundle: _Bundle,
    *,
    calendar: ExplicitExchangeCalendar,
    as_of: datetime,
) -> tuple[_CorporateAction, ...]:
    rows = _canonical_jsonl(bundle.raw_bytes["corporate_actions"], "corporate_actions")
    actions: list[_CorporateAction] = []
    observed_ids: set[str] = set()
    prior_key: tuple[date, str, str] | None = None
    session_dates = set(calendar.session_dates)
    for row in rows:
        if set(row) != {
            "action_id",
            "symbol",
            "action_type",
            "effective_date",
            "announced_at_utc",
            "revised_at_utc",
            "amount_per_share",
            "split_ratio",
        }:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_ROW_SCHEMA_MISMATCH")
        action_id = row["action_id"]
        action_type = row["action_type"]
        if not isinstance(action_id, str) or not action_id or action_id in observed_ids:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_ID_IS_INVALID_OR_DUPLICATE")
        if (
            row["symbol"] != SYMBOL
            or not isinstance(action_type, str)
            or action_type not in {"CASH_DIVIDEND", "SPLIT"}
        ):
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_SCOPE_IS_INVALID")
        try:
            effective_date = date.fromisoformat(str(row["effective_date"]))
        except ValueError as exc:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_DATE_IS_INVALID") from exc
        if effective_date not in session_dates:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_DATE_IS_NOT_AN_XNYS_SESSION")
        announced = _iso_timestamp("corporate_action_announced_at", row["announced_at_utc"])
        revised = _iso_timestamp("corporate_action_revised_at", row["revised_at_utc"])
        effective_open = calendar.session_by_date()[effective_date].open_timestamp.astimezone(UTC)
        if announced > revised or revised > effective_open or revised > as_of:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTION_VINTAGE_IS_NOT_POINT_IN_TIME")
        if action_type == "CASH_DIVIDEND":
            amount = _bounded_decimal(
                "dividend_amount",
                row["amount_per_share"],
                minimum=MINIMUM_SIZE,
                maximum=MAXIMUM_DIVIDEND_PER_SHARE_USD,
            )
            if row["split_ratio"] is not None:
                raise SpyTomDevelopmentEvidenceError("DIVIDEND_ROW_CONTAINS_SPLIT_RATIO")
            ratio = None
        else:
            ratio = _bounded_decimal(
                "split_ratio",
                row["split_ratio"],
                minimum=MINIMUM_SIZE,
                maximum=MAXIMUM_SPLIT_RATIO,
            )
            if row["amount_per_share"] is not None:
                raise SpyTomDevelopmentEvidenceError("SPLIT_ROW_CONTAINS_DIVIDEND_AMOUNT")
            amount = None
        key = (effective_date, str(action_type), action_id)
        if prior_key is not None and key <= prior_key:
            raise SpyTomDevelopmentEvidenceError("CORPORATE_ACTIONS_ARE_NOT_STRICTLY_ORDERED")
        actions.append(
            _CorporateAction(
                action_id=action_id,
                action_type=str(action_type),
                effective_date=effective_date,
                announced_at=announced,
                revised_at=revised,
                amount_per_share=amount,
                split_ratio=ratio,
            )
        )
        observed_ids.add(action_id)
        prior_key = key
    if not any(action.action_type == "CASH_DIVIDEND" for action in actions):
        raise SpyTomDevelopmentEvidenceError("SPY_DIVIDEND_EVIDENCE_IS_MISSING")
    return tuple(actions)


def _parse_fee_schedule(
    bundle: _Bundle,
    *,
    calendar: ExplicitExchangeCalendar,
) -> tuple[_FeeRate, ...]:
    rows = _canonical_jsonl(bundle.raw_bytes["fees"], "fees")
    schedule: list[_FeeRate] = []
    prior_end: date | None = None
    for row in rows:
        if set(row) != {
            "effective_start",
            "effective_end",
            "commission_bps_per_side",
            "regulatory_sell_bps",
            "regulatory_sell_fixed_cents",
            "source_url",
        }:
            raise SpyTomDevelopmentEvidenceError("FEE_ROW_SCHEMA_MISMATCH")
        try:
            start = date.fromisoformat(str(row["effective_start"]))
            end = date.fromisoformat(str(row["effective_end"]))
        except ValueError as exc:
            raise SpyTomDevelopmentEvidenceError("FEE_EFFECTIVE_DATE_IS_INVALID") from exc
        if start > end or (prior_end is not None and start != prior_end + timedelta(days=1)):
            raise SpyTomDevelopmentEvidenceError("FEE_INTERVALS_ARE_GAPPED_OR_OVERLAPPING")
        commission = Decimal(
            str(
                _finite_nonnegative(
                    "fee_commission_bps", row["commission_bps_per_side"], maximum=1_000.0
                )
            )
        )
        regulatory = Decimal(
            str(
                _finite_nonnegative(
                    "fee_regulatory_sell_bps", row["regulatory_sell_bps"], maximum=1_000.0
                )
            )
        )
        if regulatory < Decimal(str(MINIMUM_REGULATORY_SELL_BPS)):
            raise SpyTomDevelopmentEvidenceError("REGULATORY_SELL_BPS_IS_BELOW_SEALED_FLOOR")
        fixed = row["regulatory_sell_fixed_cents"]
        if type(fixed) is not int or fixed < 0 or fixed > 10_000:
            raise SpyTomDevelopmentEvidenceError("REGULATORY_FIXED_FEE_IS_INVALID")
        if not isinstance(row["source_url"], str) or not row["source_url"].startswith("https://"):
            raise SpyTomDevelopmentEvidenceError("FEE_SOURCE_URL_IS_INVALID")
        schedule.append(
            _FeeRate(
                effective_start=start,
                effective_end=end,
                commission_bps_per_side=commission,
                regulatory_sell_bps=regulatory,
                regulatory_sell_fixed_cents=fixed,
            )
        )
        prior_end = end
    first_date = calendar.session_dates[0]
    last_date = calendar.session_dates[-1]
    if schedule[0].effective_start > first_date or schedule[-1].effective_end < last_date:
        raise SpyTomDevelopmentEvidenceError("FEE_SCHEDULE_DOES_NOT_COVER_CALENDAR")
    return tuple(schedule)


def _fee_for(day: date, schedule: Sequence[_FeeRate]) -> _FeeRate:
    matches = [rate for rate in schedule if rate.effective_start <= day <= rate.effective_end]
    if len(matches) != 1:
        raise SpyTomDevelopmentEvidenceError("EXACTLY_ONE_FEE_INTERVAL_MUST_COVER_EACH_FILL")
    return matches[0]


def _all_clock_observations(
    calendar: ExplicitExchangeCalendar,
    *,
    cutoff: datetime,
) -> tuple[datetime, ...]:
    values = [
        datetime.combine(session, time(15, 55), tzinfo=_NY)
        for session in calendar.session_dates
        if datetime.combine(session, time(15, 55), tzinfo=_NY).astimezone(UTC) <= cutoff
    ]
    return tuple(values)


def _target_groups(
    spec: SpyTomSpec,
    calendar: ExplicitExchangeCalendar,
    bundle: _Bundle,
) -> Mapping[str, tuple[TargetIntention, ...]]:
    try:
        targets = generate_spy_tom_targets(
            spec,
            calendar,
            _all_clock_observations(calendar, cutoff=bundle.end),
            as_of=bundle.end,
        )
    except SpyTomError as exc:
        raise SpyTomDevelopmentEvidenceError("SPEC_OR_CALENDAR_REVALIDATION_FAILED") from exc
    grouped: dict[str, list[TargetIntention]] = defaultdict(list)
    for target in targets:
        if (
            target.decision_timestamp.astimezone(UTC) >= bundle.start
            and target.expires_at.astimezone(UTC) <= bundle.end
        ):
            grouped[target.pair_id].append(target)
    complete: dict[str, tuple[TargetIntention, ...]] = {}
    required = {
        ("PRIMARY", "ENTRY"),
        ("PRIMARY", "EXIT"),
        ("CONTROL", "ENTRY"),
        ("CONTROL", "EXIT"),
    }
    for pair_id, pair_targets in sorted(grouped.items()):
        observed = {(target.leg, target.action) for target in pair_targets}
        if observed != required or len(pair_targets) != 4:
            raise SpyTomDevelopmentEvidenceError("TARGET_PAIR_IS_NOT_EXACTLY_MATCHED")
        complete[pair_id] = tuple(
            sorted(pair_targets, key=lambda target: target.decision_timestamp.astimezone(UTC))
        )
    if not complete:
        raise SpyTomDevelopmentEvidenceError("NO_COMPLETE_TARGET_PAIRS_INSIDE_MANIFEST_WINDOW")
    return MappingProxyType(complete)


def _select_fills(
    groups: Mapping[str, tuple[TargetIntention, ...]],
    quotes: tuple[_Quote, ...],
    trades: tuple[_Trade, ...],
    session_hours: Mapping[date, _SessionHours],
) -> tuple[Mapping[tuple[str, str, str], _Fill], str]:
    quotes_by_date: dict[date, list[_Quote]] = defaultdict(list)
    trades_by_date: dict[date, list[_Trade]] = defaultdict(list)
    for quote in quotes:
        quotes_by_date[quote.timestamp.astimezone(_NY).date()].append(quote)
    for trade in trades:
        trades_by_date[trade.timestamp.astimezone(_NY).date()].append(trade)
    fills: dict[tuple[str, str, str], _Fill] = {}
    audit_rows: list[dict[str, Any]] = []
    for pair_id, targets in sorted(groups.items()):
        for target in targets:
            session_date = target.decision_timestamp.date()
            hours = session_hours.get(session_date)
            if hours is None or hours.closed < target.expires_at.astimezone(UTC):
                raise SpyTomDevelopmentEvidenceError("TARGET_WINDOW_FALLS_AFTER_SESSION_CLOSE")
            start = target.earliest_execution_timestamp.astimezone(UTC)
            end = target.expires_at.astimezone(UTC)
            window_quotes = [
                quote for quote in quotes_by_date[session_date] if start <= quote.timestamp <= end
            ]
            window_trades = [
                trade for trade in trades_by_date[session_date] if start <= trade.timestamp <= end
            ]
            if not window_quotes or not window_trades:
                raise SpyTomDevelopmentEvidenceError(
                    f"EXACT_QUOTE_OR_TRADE_WINDOW_MISSING:{pair_id}:{target.leg}:{target.action}"
                )
            if target.action == "ENTRY":
                price = max(quote.ask for quote in window_quotes)
                price_source = "WORST_ASK"
            else:
                price = min(quote.bid for quote in window_quotes)
                price_source = "WORST_BID"
            key = (pair_id, target.leg, target.action)
            fills[key] = _Fill(
                target=target,
                price=price,
                quote_count=len(window_quotes),
                trade_count=len(window_trades),
            )
            audit_rows.append(
                {
                    "pair_id": pair_id,
                    "leg": target.leg,
                    "action": target.action,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "price_source": price_source,
                    "selected_price": str(price),
                    "quote_count": len(window_quotes),
                    "trade_count": len(window_trades),
                }
            )
    return MappingProxyType(fills), sha256_of_text(canonical_dumps(audit_rows))


def _episode(
    entry_fill: _Fill,
    exit_fill: _Fill,
    fee_schedule: Sequence[_FeeRate],
    corporate_actions: Sequence[_CorporateAction],
    session_hours: Mapping[date, _SessionHours],
    *,
    impact_bps: Decimal,
    fee_multiplier: Decimal,
) -> _Episode:
    capital = Decimal("200")
    maximum_debit = Decimal("195")
    bps = Decimal("10000")
    buy = entry_fill.price * (Decimal(1) + impact_bps / bps)
    sell = exit_fill.price * (Decimal(1) - impact_bps / bps)
    entry_day = entry_fill.target.decision_timestamp.date()
    exit_day = exit_fill.target.decision_timestamp.date()
    entry_rates = _fee_for(entry_day, fee_schedule)
    exit_rates = _fee_for(exit_day, fee_schedule)
    entry_commission_rate = entry_rates.commission_bps_per_side / bps * fee_multiplier
    exit_commission_rate = exit_rates.commission_bps_per_side / bps * fee_multiplier
    regulatory_rate = exit_rates.regulatory_sell_bps / bps * fee_multiplier
    entry_notional = maximum_debit / (Decimal(1) + entry_commission_rate)
    entry_fee = entry_notional * entry_commission_rate
    quantity = entry_notional / buy
    dividend_cash = Decimal(0)
    entry_time = entry_fill.target.earliest_execution_timestamp.astimezone(UTC)
    exit_time = exit_fill.target.earliest_execution_timestamp.astimezone(UTC)
    held_actions = [
        action
        for action in corporate_actions
        if entry_time < session_hours[action.effective_date].opened <= exit_time
    ]
    for action in sorted(
        held_actions,
        key=lambda item: (item.effective_date, 0 if item.action_type == "SPLIT" else 1),
    ):
        if action.action_type == "SPLIT":
            if action.split_ratio is None:
                raise SpyTomDevelopmentEvidenceError("SPLIT_RATIO_DISAPPEARED_AFTER_VALIDATION")
            quantity *= action.split_ratio
        else:
            if action.amount_per_share is None:
                raise SpyTomDevelopmentEvidenceError("DIVIDEND_AMOUNT_DISAPPEARED_AFTER_VALIDATION")
            dividend_cash += quantity * action.amount_per_share
    exit_notional = quantity * sell
    exit_fee = exit_notional * (exit_commission_rate + regulatory_rate) + (
        Decimal(exit_rates.regulatory_sell_fixed_cents) / Decimal(100) * fee_multiplier
    )
    terminal = capital - entry_notional - entry_fee + exit_notional + dividend_cash - exit_fee
    if terminal <= 0:
        raise SpyTomDevelopmentEvidenceError("FEE_POLICY_OR_PRICE_PATH_EXHAUSTS_CAPITAL")
    return _Episode(
        net_return=float(terminal / capital - Decimal(1)),
        fees_usd=float(entry_fee + exit_fee),
    )


def _total_return_and_drawdown(returns: Sequence[float]) -> tuple[float, float]:
    equity = 200.0
    peak = equity
    minimum_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        minimum_drawdown = min(minimum_drawdown, equity / peak - 1.0)
    return equity / 200.0 - 1.0, minimum_drawdown


def _bootstrap_by_year(values: Sequence[tuple[int, float]]) -> tuple[int, float, float]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for year, value in values:
        grouped[year].append(value)
    years = sorted(grouped)
    if len(years) < 2:
        raise SpyTomDevelopmentEvidenceError("PAIRED_BOOTSTRAP_REQUIRES_TWO_CALENDAR_YEARS")
    rng = random.Random(BOOTSTRAP_SEED)
    estimates: list[float] = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        sampled = [rng.choice(years) for _ in years]
        observations = [value for year in sampled for value in grouped[year]]
        estimates.append(sum(observations) / len(observations))
    estimates.sort()
    low = estimates[int(0.025 * (len(estimates) - 1))]
    high = estimates[int(0.975 * (len(estimates) - 1))]
    return len(years), low, high


def _scenario(
    groups: Mapping[str, tuple[TargetIntention, ...]],
    fills: Mapping[tuple[str, str, str], _Fill],
    fee_schedule: Sequence[_FeeRate],
    corporate_actions: Sequence[_CorporateAction],
    session_hours: Mapping[date, _SessionHours],
    *,
    impact_bps: float,
    fee_multiplier: float,
) -> ScenarioSnapshot:
    primary_returns: list[float] = []
    control_returns: list[float] = []
    primary_fees = 0.0
    control_fees = 0.0
    excess_by_year: list[tuple[int, float]] = []
    for pair_id in sorted(groups):
        primary = _episode(
            fills[(pair_id, "PRIMARY", "ENTRY")],
            fills[(pair_id, "PRIMARY", "EXIT")],
            fee_schedule,
            corporate_actions,
            session_hours,
            impact_bps=Decimal(str(impact_bps)),
            fee_multiplier=Decimal(str(fee_multiplier)),
        )
        control = _episode(
            fills[(pair_id, "CONTROL", "ENTRY")],
            fills[(pair_id, "CONTROL", "EXIT")],
            fee_schedule,
            corporate_actions,
            session_hours,
            impact_bps=Decimal(str(impact_bps)),
            fee_multiplier=Decimal(str(fee_multiplier)),
        )
        primary_returns.append(primary.net_return)
        control_returns.append(control.net_return)
        primary_fees += primary.fees_usd
        control_fees += control.fees_usd
        following_month = pair_id.split("_TO_")[1]
        excess_by_year.append((int(following_month[:4]), primary.net_return - control.net_return))
    primary_total, primary_drawdown = _total_return_and_drawdown(primary_returns)
    control_total, control_drawdown = _total_return_and_drawdown(control_returns)
    year_count, ci_low, ci_high = _bootstrap_by_year(excess_by_year)
    count = len(primary_returns)
    return ScenarioSnapshot(
        impact_bps_per_side=impact_bps,
        fee_multiplier=fee_multiplier,
        paired_months=count,
        primary_total_return=primary_total,
        control_total_return=control_total,
        primary_mean_monthly_return=sum(primary_returns) / count,
        control_mean_monthly_return=sum(control_returns) / count,
        mean_paired_excess=sum(
            primary - control
            for primary, control in zip(primary_returns, control_returns, strict=True)
        )
        / count,
        primary_max_drawdown=primary_drawdown,
        control_max_drawdown=control_drawdown,
        bootstrap_year_count=year_count,
        bootstrap_repetitions=BOOTSTRAP_REPETITIONS,
        bootstrap_seed=BOOTSTRAP_SEED,
        paired_excess_ci_low=ci_low,
        paired_excess_ci_high=ci_high,
        primary_total_fees_usd=primary_fees,
        control_total_fees_usd=control_fees,
        _construction_token=_SCENARIO_CONSTRUCTION_TOKEN,
    )


def _calendar_attestation_sha256(calendar: ExplicitExchangeCalendar) -> str:
    payload = {
        "calendar_id": calendar.calendar_id,
        "complete_months": list(calendar.complete_months),
        "sessions": [
            {
                "date": session.session_date.isoformat(),
                "open": session.open_timestamp.astimezone(UTC).isoformat(),
                "close": session.close_timestamp.astimezone(UTC).isoformat(),
            }
            for session in calendar.sessions
        ],
    }
    return sha256_of_text(canonical_dumps(payload))


def _verdict(
    *,
    status: VerdictStatus,
    expected_manifest_sha256: str,
    cutoff: datetime,
    as_of: datetime,
    eligible_pairs: int,
    completed_pairs: int,
    evidence_hashes: Mapping[str, str],
    scenarios: Mapping[str, ScenarioSnapshot],
    reasons: Sequence[str],
) -> SpyTomDevelopmentVerdict:
    return SpyTomDevelopmentVerdict(
        status=status,
        strategy_id=STRATEGY_ID,
        expected_manifest_sha256=expected_manifest_sha256,
        development_cutoff=cutoff.isoformat(),
        as_of=as_of.isoformat(),
        eligible_pairs=eligible_pairs,
        completed_pairs=completed_pairs,
        evidence_hashes=evidence_hashes,
        scenarios=scenarios,
        reasons=tuple(reasons),
        _construction_token=_VERDICT_CONSTRUCTION_TOKEN,
    )


def evaluate_spy_tom_development(
    bundle_root: str | Path,
    spec: SpyTomSpec,
    calendar: ExplicitExchangeCalendar,
    *,
    expected_manifest_sha256: str,
    development_cutoff: datetime,
    as_of: datetime,
) -> SpyTomDevelopmentVerdict:
    """Evaluate one local development bundle without accepting caller metrics."""

    fallback_cutoff = _SAFE_FALLBACK_TIMESTAMP
    fallback_as_of = _SAFE_FALLBACK_TIMESTAMP
    report_manifest_reference = (
        expected_manifest_sha256
        if isinstance(expected_manifest_sha256, str)
        and len(expected_manifest_sha256) == 64
        and all(character in "0123456789abcdef" for character in expected_manifest_sha256)
        else "INVALID"
    )
    evidence_hashes: dict[str, str] = {"spec": SPEC_SEAL}
    eligible_pairs = 0
    try:
        cutoff = _aware_input("development_cutoff", development_cutoff)
        observed_as_of = _aware_input("as_of", as_of)
        fallback_cutoff = cutoff
        fallback_as_of = observed_as_of
        if cutoff > observed_as_of:
            raise SpyTomDevelopmentEvidenceError("DEVELOPMENT_CUTOFF_IS_AFTER_AS_OF")
        if type(spec) is not SpyTomSpec or spec.seal() != SPEC_SEAL:
            raise SpyTomDevelopmentEvidenceError("SPEC_IS_NOT_THE_SEALED_SPY_TOM_CAMPAIGN")
        if type(calendar) is not ExplicitExchangeCalendar:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_TYPE_IS_NOT_EXPLICIT_XNYS")
        try:
            validated_calendar = ExplicitExchangeCalendar(
                calendar_id=calendar.calendar_id,
                complete_months=calendar.complete_months,
                sessions=calendar.sessions,
            )
        except (AttributeError, TypeError, SpyTomError) as exc:
            raise SpyTomDevelopmentEvidenceError("CALENDAR_CONSTRUCTOR_FORGERY_DETECTED") from exc
        bundle = _load_bundle(
            Path(bundle_root),
            expected_manifest_sha256,
            cutoff=cutoff,
            as_of=observed_as_of,
        )
        evidence_hashes.update(
            {
                "manifest": bundle.manifest_sha256,
                "calendar_attestation": _calendar_attestation_sha256(validated_calendar),
                **{f"raw_{name}": digest for name, digest in bundle.raw_hashes.items()},
            }
        )
        try:
            _verify_receipts(bundle, calendar, as_of=observed_as_of)
            session_hours = _parse_calendar(bundle, validated_calendar)
            quotes = _parse_quotes(bundle)
            trades = _parse_trades(bundle)
            _verify_market_session_dates(quotes, trades, session_hours)
            corporate_actions = _parse_corporate_actions(
                bundle,
                calendar=validated_calendar,
                as_of=observed_as_of,
            )
            fee_schedule = _parse_fee_schedule(bundle, calendar=validated_calendar)
        except SpyTomDevelopmentEvidenceError:
            raise
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise SpyTomDevelopmentEvidenceError("EVIDENCE_SCHEMA_INVALID") from exc
        groups = _target_groups(spec, validated_calendar, bundle)
        eligible_pairs = len(groups)
        fills, fill_sha = _select_fills(groups, quotes, trades, session_hours)
        evidence_hashes["selected_fills"] = fill_sha
        completed_pairs = len(groups)
        if completed_pairs < MINIMUM_PAIRED_MONTHS:
            return _verdict(
                status="INSUFFICIENT_EVIDENCE",
                expected_manifest_sha256=report_manifest_reference,
                cutoff=cutoff,
                as_of=observed_as_of,
                eligible_pairs=eligible_pairs,
                completed_pairs=completed_pairs,
                evidence_hashes=evidence_hashes,
                scenarios={},
                reasons=(
                    f"REQUIRES_{MINIMUM_PAIRED_MONTHS}_MATCHED_MONTHS_HAS_{completed_pairs}",
                    "EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED",
                    "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PASS_OR_LIVE_EXECUTION",
                ),
            )
        scenarios = {
            "normal": _scenario(
                groups,
                fills,
                fee_schedule,
                corporate_actions,
                session_hours,
                impact_bps=NORMAL_IMPACT_BPS_PER_SIDE,
                fee_multiplier=1.0,
            ),
            "stress_5bps_2x_fees": _scenario(
                groups,
                fills,
                fee_schedule,
                corporate_actions,
                session_hours,
                impact_bps=STRESS_IMPACT_BPS_PER_SIDE,
                fee_multiplier=2.0,
            ),
        }
        reasons: list[str] = []
        for name, scenario in scenarios.items():
            if scenario.mean_paired_excess <= 0.0:
                reasons.append(f"{name.upper()}_MEAN_PAIRED_EXCESS_IS_NOT_POSITIVE")
            if scenario.primary_total_return <= scenario.control_total_return:
                reasons.append(f"{name.upper()}_PRIMARY_DOES_NOT_OUTPERFORM_CONTROL")
        if not reasons:
            if scenarios["stress_5bps_2x_fees"].paired_excess_ci_low <= 0.0:
                reasons.append("STRESS_YEAR_BOOTSTRAP_LOWER_BOUND_IS_NOT_POSITIVE")
            reasons.append("DEVELOPMENT_ONLY_POSITIVE_RESULT_CANNOT_BECOME_PASS")
        else:
            reasons = [f"DIAGNOSTIC_ONLY:{reason}" for reason in reasons]
        reasons.append("EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED")
        reasons.append("LIVE_EXECUTION_AND_REAL_MONEY_REMAIN_UNAUTHORIZED")
        return _verdict(
            status="INSUFFICIENT_EVIDENCE",
            expected_manifest_sha256=report_manifest_reference,
            cutoff=cutoff,
            as_of=observed_as_of,
            eligible_pairs=eligible_pairs,
            completed_pairs=completed_pairs,
            evidence_hashes=evidence_hashes,
            scenarios=scenarios,
            reasons=reasons,
        )
    except SpyTomDevelopmentEvidenceError as exc:
        return _verdict(
            status="INSUFFICIENT_EVIDENCE",
            expected_manifest_sha256=report_manifest_reference,
            cutoff=min(fallback_cutoff, fallback_as_of),
            as_of=fallback_as_of,
            eligible_pairs=eligible_pairs,
            completed_pairs=0,
            evidence_hashes=evidence_hashes,
            scenarios={},
            reasons=(
                str(exc),
                "EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED",
                "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PASS_OR_LIVE_EXECUTION",
            ),
        )
    except (
        DecimalException,
        IndexError,
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ):
        return _verdict(
            status="INSUFFICIENT_EVIDENCE",
            expected_manifest_sha256=report_manifest_reference,
            cutoff=min(fallback_cutoff, fallback_as_of),
            as_of=fallback_as_of,
            eligible_pairs=eligible_pairs,
            completed_pairs=0,
            evidence_hashes=evidence_hashes,
            scenarios={},
            reasons=(
                "EVIDENCE_SCHEMA_INVALID_OR_OUT_OF_RANGE",
                "EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED",
                "DEVELOPMENT_ONLY_CANNOT_AUTHORIZE_PASS_OR_LIVE_EXECUTION",
            ),
        )


__all__ = [
    "BOOTSTRAP_REPETITIONS",
    "BOOTSTRAP_SEED",
    "MANIFEST_SCHEMA",
    "MINIMUM_PAIRED_MONTHS",
    "SCHEMA_VERSION",
    "MINIMUM_REGULATORY_SELL_BPS",
    "NORMAL_IMPACT_BPS_PER_SIDE",
    "ScenarioSnapshot",
    "SpyTomDevelopmentEvidenceError",
    "SpyTomDevelopmentVerdict",
    "STRESS_IMPACT_BPS_PER_SIDE",
    "evaluate_spy_tom_development",
]
