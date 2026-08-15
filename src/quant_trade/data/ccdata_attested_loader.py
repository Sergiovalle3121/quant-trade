"""Offline, fail-closed loader for externally attested CCData evidence.

This module is deliberately narrower than a data-provider adapter.  It never
opens a socket and it does not calculate a signal, portfolio, backtest, P&L,
or trading decision.  Its job is to bind five things that ordinary local
hashes cannot bind on their own:

* exact provider bytes and their append-only capture receipts;
* the provider schema and a reviewed, version-pinned parser;
* historical vintage/revision identity and availability timestamps;
* the exact commercial quote, terms, and executed license grant; and
* a detached signature verified from a trust root supplied outside the bundle.

The provider schema is not guessed here.  A real bundle remains unloadable
until a parser for the contracted CCData product is supplied and its identity,
version, and schema digest match the signed manifest exactly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes, sha256_of_file

MANIFEST_FILENAME = "manifest.json"
ATTESTATION_FILENAME = "attestation.json"
SIGNATURE_FILENAME = "attestation.sig"

BUNDLE_TYPE = "CCDATA_WORLD_ORDER_FLOW_ATTESTED_BUNDLE"
STATEMENT_TYPE = "CCDATA_WORLD_ORDER_FLOW_BUNDLE_ATTESTATION"
SCHEMA_VERSION = 1
PROVIDER_NAME = "CCData"
SOURCE_CONTRACT = "cryptocompare_signed_volume_g11_multi_exchange"
SIGNATURE_ALGORITHM = "ED25519"
PAPER_CALENDAR_NAME = "WEEKDAYS_EXCLUDING_US_HOLIDAYS"

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
REQUIRED_LICENSE_USES = (
    "COMMERCIAL_RESEARCH",
    "DERIVED_BACKTESTS_AND_SIGNALS",
    "LOCAL_RAW_STORAGE",
    "PROPRIETARY_TRADING_OWN_CAPITAL",
)
REQUIRED_PROVIDER_FIELDS = tuple(
    sorted(
        {
            "CCSEQ",
            "BASE",
            "BASE_ID",
            "INSTRUMENT",
            "MAPPED_INSTRUMENT",
            "MARKET",
            "QUOTE_VOLUME_BUY",
            "QUOTE_VOLUME_SELL",
            "QUOTE_VOLUME_UNKNOWN",
            "RECEIVED_TIMESTAMP",
            "RECEIVED_TIMESTAMP_NS",
            "QUOTE",
            "QUOTE_ID",
            "SIDE",
            "SOURCE",
            "STATUS",
            "TIMESTAMP",
            "TIMESTAMP_NS",
            "TOTAL_TRADES_BUY",
            "TOTAL_TRADES_SELL",
            "TOTAL_TRADES_UNKNOWN",
            "TRANSFORM_FUNCTION",
            "UNIT",
            "VOLUME_BUY",
            "VOLUME_SELL",
            "VOLUME_UNKNOWN",
            "correction_or_invalidation_type",
        }
    )
)
REQUIRED_SOURCE_ROLES = (
    "COMMERCIAL_QUOTE",
    "LICENSE_GRANT",
    "LICENSE_TERMS",
    "PAPER_CALENDAR",
    "PROVIDER_SCHEMA",
    "REVISION_POLICY",
)
DATA_SOURCE_ROLE = "SIGNED_VOLUME_RAW"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?")
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_SIGNATURE_BYTES = 16 * 1024
_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_ZERO_SHA256 = "0" * 64


class CCDataAttestedLoaderError(ValueError):
    """The bundle is incomplete, ambiguous, tampered, or not trusted."""


class Ed25519SignatureVerifier:
    """Ed25519 backend using the optional, audited ``cryptography`` package."""

    def verify(
        self,
        *,
        algorithm: str,
        verification_key: bytes,
        message: bytes,
        signature: bytes,
    ) -> None:
        if algorithm != SIGNATURE_ALGORITHM:
            raise CCDataAttestedLoaderError("only ED25519 attestations are supported")
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as exc:  # pragma: no cover - depends on an optional runtime extra
            raise CCDataAttestedLoaderError(
                "Ed25519 verification requires the optional cryptography package"
            ) from exc
        try:
            Ed25519PublicKey.from_public_bytes(verification_key).verify(signature, message)
        except (InvalidSignature, ValueError) as exc:
            raise CCDataAttestedLoaderError("detached attestation signature is invalid") from exc


@dataclass(frozen=True)
class AttestationTrustRoot:
    """Out-of-band policy and public key; never loaded from the evidence bundle."""

    root_id: str
    issuer_id: str
    key_id: str
    algorithm: str
    verification_key: bytes = field(repr=False)
    valid_from_utc: str
    valid_until_utc: str
    allowed_provider_product_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("root_id", self.root_id),
            ("issuer_id", self.issuer_id),
            ("key_id", self.key_id),
        ):
            _identifier(value, field_name=label)
        if self.algorithm != SIGNATURE_ALGORITHM:
            raise CCDataAttestedLoaderError("trust root algorithm must be ED25519")
        if not isinstance(self.verification_key, bytes) or len(self.verification_key) != 32:
            raise CCDataAttestedLoaderError("Ed25519 trust root must contain a 32-byte public key")
        start = _utc(self.valid_from_utc, field_name="trust root valid_from_utc")
        end = _utc(self.valid_until_utc, field_name="trust root valid_until_utc")
        if start >= end:
            raise CCDataAttestedLoaderError("trust root validity interval is empty")
        products = self.allowed_provider_product_ids
        if (
            not isinstance(products, tuple)
            or not products
            or products != tuple(sorted(set(products)))
        ):
            raise CCDataAttestedLoaderError(
                "allowed_provider_product_ids must be a sorted, unique, non-empty tuple"
            )
        for product in products:
            _identifier(product, field_name="allowed provider product id")

    @property
    def verification_key_sha256(self) -> str:
        return sha256_of_bytes(self.verification_key)

    @property
    def seal(self) -> str:
        return sha256_of_bytes(
            canonical_dumps(
                {
                    "root_id": self.root_id,
                    "issuer_id": self.issuer_id,
                    "key_id": self.key_id,
                    "algorithm": self.algorithm,
                    "verification_key_sha256": self.verification_key_sha256,
                    "valid_from_utc": self.valid_from_utc,
                    "valid_until_utc": self.valid_until_utc,
                    "allowed_provider_product_ids": list(self.allowed_provider_product_ids),
                }
            ).encode("utf-8")
        )


@dataclass(frozen=True)
class CCDataSourceReceipt:
    """One signed, append-only source artifact receipt."""

    sequence: int
    receipt_id: str
    role: str
    path: str
    media_type: str
    byte_length: int
    sha256: str
    captured_at_utc: str
    available_at_utc: str
    vintage_id: str
    revision_id: str
    revision_sequence: int
    supersedes_receipt_sha256: str
    previous_receipt_sha256: str
    receipt_sha256: str


@dataclass(frozen=True)
class ParsedCCDataDelivery:
    """Deterministic result returned by the contracted raw parser."""

    observations: tuple[dict[str, Any], ...]
    venue_constituents: tuple[dict[str, Any], ...]


class CCDataRawParser(Protocol):
    """Version-pinned parser for the exact contracted provider schema."""

    parser_name: str
    parser_version: str
    provider_product_id: str
    provider_schema_version: str
    provider_schema_sha256: str

    def parse(self, raw: bytes, *, receipt: CCDataSourceReceipt) -> ParsedCCDataDelivery: ...


@dataclass(frozen=True)
class AttestedWorldOrderFlowRow:
    """Exact normalized signed-volume schema produced from provider bytes."""

    stable_asset_id: str
    cmc_id: int
    chain_id: str
    contract_or_native_id: str
    measurement_date: str
    fiat_currency: str
    buyer_initiated_volume: str
    seller_initiated_volume: str
    contributing_venues: tuple[str, ...]
    computed_at_utc: str
    published_at_utc: str
    available_at_utc: str
    vintage_id: str
    revision_id: str
    revision_sequence: int
    source_receipt_sha256: str
    source_bytes_sha256: str = field(repr=False)
    source_captured_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stable_asset_id": self.stable_asset_id,
            "cmc_id": self.cmc_id,
            "chain_id": self.chain_id,
            "contract_or_native_id": self.contract_or_native_id,
            "measurement_date": self.measurement_date,
            "fiat_currency": self.fiat_currency,
            "buyer_initiated_volume": self.buyer_initiated_volume,
            "seller_initiated_volume": self.seller_initiated_volume,
            "contributing_venues": list(self.contributing_venues),
            "signed_volume_definition": "BUYER_AND_SELLER_INITIATED",
            "source_scope": "MULTI_VENUE_FIAT",
            "computed_at_utc": self.computed_at_utc,
            "published_at_utc": self.published_at_utc,
            "available_at_utc": self.available_at_utc,
            "vintage_id": self.vintage_id,
            "revision_id": self.revision_id,
            "revision_sequence": self.revision_sequence,
            "source_receipt_sha256": self.source_receipt_sha256,
        }


@dataclass(frozen=True)
class LoadedAttestedCCDataBundle:
    """Verified data projection.  It carries no economic or trading approval."""

    root: Path
    provider_product_id: str
    delivery_id: str
    classification_method: str
    classification_method_version: str
    knowledge_cutoff_utc: str
    verification_at_utc: str
    attestation_issued_at_utc: str
    manifest_sha256: str
    attestation_sha256: str
    signature_sha256: str
    trust_root_sha256: str
    source_receipt_chain_head_sha256: str
    causal_source_receipts_sha256: str
    causal_rows_sha256: str
    rows: tuple[AttestedWorldOrderFlowRow, ...]
    paper_calendar_dates: tuple[str, ...]
    license_terms_sha256: str
    license_grant_sha256: str
    commercial_quote_sha256: str
    _verification_token: object = field(repr=False, compare=False)
    external_signature_verified_to_supplied_root: bool = field(default=True, init=False)
    commercial_license_claim_signature_verified: bool = field(default=True, init=False)
    commercial_data_use_authorized: bool = field(default=False, init=False)
    structural_data_only: bool = field(default=True, init=False)
    preregistration_authorized: bool = field(default=False, init=False)
    signal_generation_authorized: bool = field(default=False, init=False)
    backtest_authorized: bool = field(default=False, init=False)
    pnl_evaluation_authorized: bool = field(default=False, init=False)
    holdout_access_authorized: bool = field(default=False, init=False)
    network_access_authorized: bool = field(default=False, init=False)
    real_money_authorized: bool = field(default=False, init=False)
    profitability_evidence: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._verification_token is not _VERIFIED_BUNDLE_TOKEN:
            raise CCDataAttestedLoaderError(
                "verified bundle results can only be constructed by the loader"
            )


_MANIFEST_KEYS = {
    "schema_version",
    "bundle_type",
    "provider_name",
    "provider_product_id",
    "delivery_id",
    "provider_schema_version",
    "source_contract",
    "provider_operation_ids",
    "required_provider_fields",
    "parser_name",
    "parser_version",
    "classification_method",
    "classification_method_version",
    "aggregation_method",
    "aggregation_method_version",
    "license",
    "vintage_policy",
    "source_receipts",
    "derived_artifacts",
}
_LICENSE_KEYS = {
    "licensee_fingerprint_sha256",
    "permitted_uses",
    "territories",
    "valid_from_utc",
    "valid_until_utc",
    "terms_receipt_sha256",
    "grant_receipt_sha256",
    "quote_receipt_sha256",
}
_VINTAGE_KEYS = {
    "policy_id",
    "policy_version",
    "revision_policy_receipt_sha256",
    "historical_vintages_preserved",
    "corrections_are_append_only",
    "correction_log_includes_revised_at",
    "correction_log_includes_old_and_new_values",
    "revision_history_complete_through_utc",
}
_DERIVED_KEYS = {"normalized_observations", "revision_log", "venue_constituents"}
_ARTIFACT_KEYS = {"schema_version", "path", "media_type", "byte_length", "sha256"}
_RECEIPT_KEYS = {
    "schema_version",
    "sequence",
    "receipt_id",
    "role",
    "path",
    "media_type",
    "byte_length",
    "sha256",
    "captured_at_utc",
    "available_at_utc",
    "vintage_id",
    "revision_id",
    "revision_sequence",
    "supersedes_receipt_sha256",
    "previous_receipt_sha256",
    "receipt_sha256",
}
_ATTESTATION_KEYS = {
    "schema_version",
    "statement_type",
    "statement_id",
    "issuer_id",
    "key_id",
    "algorithm",
    "issued_at_utc",
    "expires_at_utc",
    "provider_name",
    "provider_product_id",
    "delivery_id",
    "manifest_sha256",
    "claims",
}
_CLAIM_KEYS = {
    "source_bytes_authentic",
    "provider_schema_authentic",
    "historical_vintages_authentic",
    "revision_history_complete",
    "venue_constituents_authentic",
    "commercial_quote_authentic",
    "commercial_license_terms_authentic",
    "commercial_license_grant_executed",
    "financial_product_restriction_reviewed_and_own_account_trading_permitted",
    "historical_correction_log_authentic",
}
_OBSERVATION_KEYS = {
    "schema_version",
    "stable_asset_id",
    "cmc_id",
    "chain_id",
    "contract_or_native_id",
    "measurement_date",
    "fiat_currency",
    "buyer_initiated_volume",
    "seller_initiated_volume",
    "contributing_venues",
    "signed_volume_definition",
    "source_scope",
    "computed_at_utc",
    "published_at_utc",
    "available_at_utc",
    "vintage_id",
    "revision_id",
    "revision_sequence",
    "source_receipt_sha256",
}
_VENUE_KEYS = {
    "schema_version",
    "measurement_date",
    "contributing_venues",
    "available_at_utc",
    "vintage_id",
    "revision_id",
    "revision_sequence",
    "source_receipt_sha256",
}
_REVISION_EVENT_KEYS = {
    "schema_version",
    "vintage_id",
    "prior_revision_id",
    "revision_id",
    "revision_sequence",
    "revised_at_utc",
    "old_source_receipt_sha256",
    "old_source_bytes_sha256",
    "new_source_receipt_sha256",
    "new_source_bytes_sha256",
}

_VERIFIED_BUNDLE_TOKEN = object()


def _expect_keys(value: object, expected: set[str], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CCDataAttestedLoaderError(f"{field_name} must be an object")
    actual = {str(key) for key in value}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CCDataAttestedLoaderError(
            f"{field_name} has wrong fields (missing={missing}, extra={extra})"
        )
    return value


def _strict_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CCDataAttestedLoaderError(f"{field_name} must be an integer >= {minimum}")
    return value


def _strict_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise CCDataAttestedLoaderError(f"{field_name} must be a boolean")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CCDataAttestedLoaderError(f"{field_name} must be non-empty trimmed text")
    return value


def _identifier(value: object, *, field_name: str) -> str:
    text = _text(value, field_name=field_name)
    if _IDENTIFIER_RE.fullmatch(text) is None:
        raise CCDataAttestedLoaderError(f"{field_name} is not a canonical identifier")
    return text


def _sha256(value: object, *, field_name: str, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CCDataAttestedLoaderError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CCDataAttestedLoaderError(f"{field_name} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CCDataAttestedLoaderError(f"{field_name} must be canonical UTC text") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value
    ):
        raise CCDataAttestedLoaderError(f"{field_name} must be canonical UTC text")
    return parsed.astimezone(UTC)


def _date(value: object, *, field_name: str) -> date:
    if not isinstance(value, str):
        raise CCDataAttestedLoaderError(f"{field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CCDataAttestedLoaderError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise CCDataAttestedLoaderError(f"{field_name} must be an ISO date")
    return parsed


def _sorted_unique_texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CCDataAttestedLoaderError(f"{field_name} must be a non-empty list")
    items = tuple(_identifier(item, field_name=field_name) for item in value)
    if items != tuple(sorted(set(items))):
        raise CCDataAttestedLoaderError(f"{field_name} must be sorted and unique")
    return items


def _canonical_decimal(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
        raise CCDataAttestedLoaderError(f"{field_name} must be a canonical decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already excludes invalid text
        raise CCDataAttestedLoaderError(f"{field_name} must be a decimal") from exc
    if parsed <= 0:
        raise CCDataAttestedLoaderError(f"{field_name} must be positive")
    return value


def _contained_path(root: Path, relative_path: object, *, field_name: str) -> Path:
    text = _text(relative_path, field_name=field_name)
    pure = PurePosixPath(text)
    if (
        pure.is_absolute()
        or pure.as_posix() != text
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CCDataAttestedLoaderError(f"{field_name} must be a contained POSIX path")
    unresolved = root.joinpath(*pure.parts)
    cursor = root
    if root.is_symlink():
        raise CCDataAttestedLoaderError("bundle root must not be a symlink")
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CCDataAttestedLoaderError(f"{field_name} must not traverse a symlink")
    resolved_root = root.resolve()
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise CCDataAttestedLoaderError(f"{field_name} escapes the bundle") from exc
    if not resolved.is_file():
        raise CCDataAttestedLoaderError(f"bundle artifact is missing: {text}")
    return resolved


def _read_canonical_json(root: Path, filename: str) -> tuple[dict[str, Any], bytes]:
    path = _contained_path(root, filename, field_name=filename)
    raw = path.read_bytes()
    if not raw or len(raw) > _MAX_METADATA_BYTES:
        raise CCDataAttestedLoaderError(f"{filename} has an invalid byte length")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CCDataAttestedLoaderError(f"{filename} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CCDataAttestedLoaderError(f"{filename} must contain a JSON object")
    if raw != (canonical_dumps(value) + "\n").encode("utf-8"):
        raise CCDataAttestedLoaderError(f"{filename} is not canonical JSON plus LF")
    return value, raw


def _verify_artifact(
    root: Path, descriptor: Mapping[str, Any], *, field_name: str
) -> tuple[Path, bytes]:
    _expect_keys(descriptor, _ARTIFACT_KEYS, field_name=field_name)
    if descriptor["schema_version"] != SCHEMA_VERSION:
        raise CCDataAttestedLoaderError(f"{field_name} schema version is unsupported")
    expected_length = _strict_int(
        descriptor["byte_length"], field_name=f"{field_name} byte_length", minimum=1
    )
    if expected_length > _MAX_ARTIFACT_BYTES:
        raise CCDataAttestedLoaderError(f"{field_name} exceeds the offline loader size limit")
    _text(descriptor["media_type"], field_name=f"{field_name} media_type")
    expected_sha = _sha256(descriptor["sha256"], field_name=f"{field_name} sha256")
    path = _contained_path(root, descriptor["path"], field_name=f"{field_name} path")
    if path.stat().st_size != expected_length:
        raise CCDataAttestedLoaderError(f"{field_name} byte length mismatch")
    if sha256_of_file(path) != expected_sha:
        raise CCDataAttestedLoaderError(f"{field_name} byte hash mismatch")
    return path, path.read_bytes()


def _parse_receipts(
    root: Path, value: object, *, verification_at: datetime
) -> tuple[tuple[CCDataSourceReceipt, ...], dict[str, bytes]]:
    if not isinstance(value, list) or not value:
        raise CCDataAttestedLoaderError("source_receipts must be a non-empty list")
    previous = _ZERO_SHA256
    receipts: list[CCDataSourceReceipt] = []
    raw_by_receipt: dict[str, bytes] = {}
    paths: set[str] = set()
    ids: set[str] = set()
    by_hash: dict[str, CCDataSourceReceipt] = {}
    role_counts: dict[str, int] = {}
    allowed_roles = set(REQUIRED_SOURCE_ROLES) | {DATA_SOURCE_ROLE}
    for index, item in enumerate(value, start=1):
        record = _expect_keys(item, _RECEIPT_KEYS, field_name=f"source receipt {index}")
        if record["schema_version"] != SCHEMA_VERSION:
            raise CCDataAttestedLoaderError("source receipt schema version is unsupported")
        sequence = _strict_int(record["sequence"], field_name="receipt sequence", minimum=1)
        if sequence != index:
            raise CCDataAttestedLoaderError("source receipt sequence is not contiguous")
        receipt_id = _identifier(record["receipt_id"], field_name="receipt_id")
        if receipt_id in ids:
            raise CCDataAttestedLoaderError("source receipt ids must be unique")
        ids.add(receipt_id)
        role = _identifier(record["role"], field_name="receipt role")
        if role not in allowed_roles:
            raise CCDataAttestedLoaderError(f"unsupported source receipt role {role!r}")
        role_counts[role] = role_counts.get(role, 0) + 1
        relative_path = _text(record["path"], field_name="receipt path")
        if relative_path in paths:
            raise CCDataAttestedLoaderError("source receipt paths must be unique")
        paths.add(relative_path)
        media_type = _text(record["media_type"], field_name="receipt media_type")
        byte_length = _strict_int(
            record["byte_length"], field_name="receipt byte_length", minimum=1
        )
        if byte_length > _MAX_ARTIFACT_BYTES:
            raise CCDataAttestedLoaderError("source receipt exceeds the loader size limit")
        content_sha = _sha256(record["sha256"], field_name="receipt sha256")
        captured = _utc(record["captured_at_utc"], field_name="receipt captured_at_utc")
        available = _utc(record["available_at_utc"], field_name="receipt available_at_utc")
        if not available <= captured <= verification_at:
            raise CCDataAttestedLoaderError(
                "source receipt availability/capture is after verification or out of order"
            )
        vintage_id = str(record["vintage_id"])
        revision_id = str(record["revision_id"])
        revision_sequence = _strict_int(
            record["revision_sequence"], field_name="receipt revision_sequence"
        )
        supersedes = _sha256(
            record["supersedes_receipt_sha256"],
            field_name="supersedes_receipt_sha256",
            allow_empty=True,
        )
        if role == DATA_SOURCE_ROLE:
            _identifier(vintage_id, field_name="data vintage_id")
            _identifier(revision_id, field_name="data revision_id")
            if revision_sequence == 0 and supersedes:
                raise CCDataAttestedLoaderError("initial data vintage cannot supersede a receipt")
            if revision_sequence > 0:
                predecessor = by_hash.get(supersedes)
                if (
                    predecessor is None
                    or predecessor.role != DATA_SOURCE_ROLE
                    or predecessor.vintage_id != vintage_id
                    or predecessor.revision_sequence + 1 != revision_sequence
                ):
                    raise CCDataAttestedLoaderError(
                        "data revision does not supersede the immediately prior vintage receipt"
                    )
        elif any((vintage_id, revision_id, supersedes)) or revision_sequence != 0:
            raise CCDataAttestedLoaderError(
                "non-data source receipts cannot claim a data vintage or revision"
            )
        prior = _sha256(record["previous_receipt_sha256"], field_name="previous_receipt_sha256")
        if prior != previous:
            raise CCDataAttestedLoaderError("source receipt chain predecessor mismatch")
        receipt_sha = _sha256(record["receipt_sha256"], field_name="receipt_sha256")
        body = {key: record[key] for key in sorted(_RECEIPT_KEYS - {"receipt_sha256"})}
        expected_receipt_sha = sha256_of_bytes(canonical_dumps(body).encode("utf-8"))
        if receipt_sha != expected_receipt_sha:
            raise CCDataAttestedLoaderError("source receipt content hash mismatch")
        path = _contained_path(root, relative_path, field_name="receipt path")
        if path.stat().st_size != byte_length:
            raise CCDataAttestedLoaderError("source receipt byte length mismatch")
        if sha256_of_file(path) != content_sha:
            raise CCDataAttestedLoaderError("source receipt raw byte hash mismatch")
        receipt = CCDataSourceReceipt(
            sequence=sequence,
            receipt_id=receipt_id,
            role=role,
            path=relative_path,
            media_type=media_type,
            byte_length=byte_length,
            sha256=content_sha,
            captured_at_utc=str(record["captured_at_utc"]),
            available_at_utc=str(record["available_at_utc"]),
            vintage_id=vintage_id,
            revision_id=revision_id,
            revision_sequence=revision_sequence,
            supersedes_receipt_sha256=supersedes,
            previous_receipt_sha256=prior,
            receipt_sha256=receipt_sha,
        )
        receipts.append(receipt)
        raw_by_receipt[receipt_sha] = path.read_bytes()
        by_hash[receipt_sha] = receipt
        previous = receipt_sha

    for role in REQUIRED_SOURCE_ROLES:
        if role_counts.get(role) != 1:
            raise CCDataAttestedLoaderError(f"exactly one {role} receipt is required")
    if role_counts.get(DATA_SOURCE_ROLE, 0) < 1:
        raise CCDataAttestedLoaderError("at least one SIGNED_VOLUME_RAW receipt is required")
    return tuple(receipts), raw_by_receipt


def _parse_jsonl(raw: bytes, *, field_name: str) -> tuple[dict[str, Any], ...]:
    if not raw or not raw.endswith(b"\n"):
        raise CCDataAttestedLoaderError(f"{field_name} must be non-empty canonical JSONL")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw[:-1].split(b"\n"), start=1):
        if not line:
            raise CCDataAttestedLoaderError(f"{field_name} contains an empty line")
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CCDataAttestedLoaderError(f"{field_name} line {line_number} is not JSON") from exc
        if not isinstance(row, dict):
            raise CCDataAttestedLoaderError(f"{field_name} rows must be objects")
        if line != canonical_dumps(row).encode("utf-8"):
            raise CCDataAttestedLoaderError(f"{field_name} is not canonical JSONL")
        rows.append(row)
    return tuple(rows)


def _parse_observation(
    value: Mapping[str, Any], *, data_receipts: Mapping[str, CCDataSourceReceipt]
) -> AttestedWorldOrderFlowRow:
    _expect_keys(value, _OBSERVATION_KEYS, field_name="normalized observation")
    if value["schema_version"] != SCHEMA_VERSION:
        raise CCDataAttestedLoaderError("normalized observation schema is unsupported")
    cmc_id = _strict_int(value["cmc_id"], field_name="cmc_id", minimum=1)
    stable_id = _identifier(value["stable_asset_id"], field_name="stable_asset_id")
    if stable_id != f"CMC:{cmc_id}":
        raise CCDataAttestedLoaderError("stable_asset_id must equal CMC:<cmc_id>")
    chain_id = _identifier(value["chain_id"], field_name="chain_id")
    contract_id = _identifier(value["contract_or_native_id"], field_name="contract_or_native_id")
    measurement = _date(value["measurement_date"], field_name="measurement_date")
    fiat = _identifier(value["fiat_currency"], field_name="fiat_currency")
    if fiat not in REQUIRED_FIAT_CURRENCIES:
        raise CCDataAttestedLoaderError("normalized observation currency is outside G11")
    buy = _canonical_decimal(value["buyer_initiated_volume"], field_name="buyer volume")
    sell = _canonical_decimal(value["seller_initiated_volume"], field_name="seller volume")
    venues = _sorted_unique_texts(value["contributing_venues"], field_name="venues")
    if value["signed_volume_definition"] != "BUYER_AND_SELLER_INITIATED":
        raise CCDataAttestedLoaderError("signed buy/sell definition is not the paper contract")
    if value["source_scope"] != "MULTI_VENUE_FIAT":
        raise CCDataAttestedLoaderError("source scope is not multi-venue fiat")
    computed = _utc(value["computed_at_utc"], field_name="computed_at_utc")
    published = _utc(value["published_at_utc"], field_name="published_at_utc")
    available = _utc(value["available_at_utc"], field_name="available_at_utc")
    complete_at = datetime.combine(measurement + timedelta(days=1), time.min, UTC)
    if not complete_at <= computed <= published <= available:
        raise CCDataAttestedLoaderError("observation vintage timestamps are non-causal")
    vintage_id = _identifier(value["vintage_id"], field_name="vintage_id")
    revision_id = _identifier(value["revision_id"], field_name="revision_id")
    revision_sequence = _strict_int(value["revision_sequence"], field_name="revision_sequence")
    receipt_sha = _sha256(value["source_receipt_sha256"], field_name="source_receipt_sha256")
    receipt = data_receipts.get(receipt_sha)
    if receipt is None:
        raise CCDataAttestedLoaderError("observation refers to an unknown data receipt")
    if (
        receipt.available_at_utc != value["available_at_utc"]
        or receipt.vintage_id != vintage_id
        or receipt.revision_id != revision_id
        or receipt.revision_sequence != revision_sequence
    ):
        raise CCDataAttestedLoaderError("observation vintage differs from its source receipt")
    return AttestedWorldOrderFlowRow(
        stable_asset_id=stable_id,
        cmc_id=cmc_id,
        chain_id=chain_id,
        contract_or_native_id=contract_id,
        measurement_date=measurement.isoformat(),
        fiat_currency=fiat,
        buyer_initiated_volume=buy,
        seller_initiated_volume=sell,
        contributing_venues=venues,
        computed_at_utc=str(value["computed_at_utc"]),
        published_at_utc=str(value["published_at_utc"]),
        available_at_utc=str(value["available_at_utc"]),
        vintage_id=vintage_id,
        revision_id=revision_id,
        revision_sequence=revision_sequence,
        source_receipt_sha256=receipt_sha,
        source_bytes_sha256=receipt.sha256,
        source_captured_at_utc=receipt.captured_at_utc,
    )


def _validate_venue_rows(
    values: Sequence[Mapping[str, Any]],
    *,
    data_receipts: Mapping[str, CCDataSourceReceipt],
) -> dict[tuple[str, str], tuple[str, ...]]:
    coverage: dict[tuple[str, str], tuple[str, ...]] = {}
    for value in values:
        _expect_keys(value, _VENUE_KEYS, field_name="venue constituent row")
        if value["schema_version"] != SCHEMA_VERSION:
            raise CCDataAttestedLoaderError("venue constituent schema is unsupported")
        measurement = _date(value["measurement_date"], field_name="venue measurement_date")
        venues = _sorted_unique_texts(value["contributing_venues"], field_name="venues")
        available = _utc(value["available_at_utc"], field_name="venue available_at_utc")
        receipt_sha = _sha256(
            value["source_receipt_sha256"], field_name="venue source_receipt_sha256"
        )
        receipt = data_receipts.get(receipt_sha)
        revision_sequence = _strict_int(
            value["revision_sequence"], field_name="venue revision_sequence"
        )
        if receipt is None:
            raise CCDataAttestedLoaderError("venue row refers to an unknown data receipt")
        if (
            receipt.available_at_utc != value["available_at_utc"]
            or receipt.vintage_id != value["vintage_id"]
            or receipt.revision_id != value["revision_id"]
            or receipt.revision_sequence != revision_sequence
        ):
            raise CCDataAttestedLoaderError("venue row vintage differs from its source receipt")
        key = (receipt_sha, measurement.isoformat())
        if key in coverage:
            raise CCDataAttestedLoaderError("duplicate venue constituent coverage row")
        coverage[key] = venues
        if available != _utc(receipt.available_at_utc, field_name="receipt available_at_utc"):
            raise CCDataAttestedLoaderError("venue availability differs from source receipt")
    return coverage


def _validate_revision_log(
    raw: bytes,
    *,
    data_receipts: Mapping[str, CCDataSourceReceipt],
) -> None:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CCDataAttestedLoaderError("revision log is not JSON") from exc
    record = _expect_keys(payload, {"schema_version", "events"}, field_name="revision log")
    if raw != (canonical_dumps(record) + "\n").encode("utf-8"):
        raise CCDataAttestedLoaderError("revision log is not canonical JSON plus LF")
    if record["schema_version"] != SCHEMA_VERSION or not isinstance(record["events"], list):
        raise CCDataAttestedLoaderError("revision log schema is unsupported")
    expected_revision_receipts = {
        receipt.receipt_sha256: receipt
        for receipt in data_receipts.values()
        if receipt.revision_sequence > 0
    }
    seen: set[str] = set()
    for item in record["events"]:
        event = _expect_keys(item, _REVISION_EVENT_KEYS, field_name="revision event")
        if event["schema_version"] != SCHEMA_VERSION:
            raise CCDataAttestedLoaderError("revision event schema is unsupported")
        new_receipt_sha = _sha256(
            event["new_source_receipt_sha256"], field_name="new_source_receipt_sha256"
        )
        if new_receipt_sha in seen:
            raise CCDataAttestedLoaderError("duplicate revision event")
        seen.add(new_receipt_sha)
        current = expected_revision_receipts.get(new_receipt_sha)
        old_receipt_sha = _sha256(
            event["old_source_receipt_sha256"], field_name="old_source_receipt_sha256"
        )
        predecessor = data_receipts.get(old_receipt_sha)
        revised_at = _utc(event["revised_at_utc"], field_name="revision revised_at_utc")
        revision_sequence = _strict_int(
            event["revision_sequence"], field_name="revision event sequence", minimum=1
        )
        if current is None or predecessor is None:
            raise CCDataAttestedLoaderError("revision event refers to an unknown source receipt")
        if (
            current.supersedes_receipt_sha256 != old_receipt_sha
            or current.vintage_id != event["vintage_id"]
            or predecessor.revision_id != event["prior_revision_id"]
            or current.revision_id != event["revision_id"]
            or current.revision_sequence != revision_sequence
            or revised_at
            != _utc(current.available_at_utc, field_name="revision receipt available_at_utc")
            or event["old_source_bytes_sha256"] != predecessor.sha256
            or event["new_source_bytes_sha256"] != current.sha256
        ):
            raise CCDataAttestedLoaderError(
                "revision event does not bind revised-at plus exact old/new provider bytes"
            )
    if seen != set(expected_revision_receipts):
        raise CCDataAttestedLoaderError(
            "revision log does not cover every revised data receipt exactly once"
        )


def _validate_license(
    value: object,
    *,
    receipts_by_hash: Mapping[str, CCDataSourceReceipt],
    verification_at: datetime,
) -> tuple[CCDataSourceReceipt, CCDataSourceReceipt, CCDataSourceReceipt]:
    license_record = _expect_keys(value, _LICENSE_KEYS, field_name="license")
    _sha256(
        license_record["licensee_fingerprint_sha256"],
        field_name="licensee_fingerprint_sha256",
    )
    uses = _sorted_unique_texts(license_record["permitted_uses"], field_name="permitted_uses")
    if not set(REQUIRED_LICENSE_USES) <= set(uses):
        raise CCDataAttestedLoaderError(
            "executed license lacks a required explicit internal-use entitlement"
        )
    territories = _sorted_unique_texts(license_record["territories"], field_name="territories")
    if "MX" not in territories and "WORLDWIDE" not in territories:
        raise CCDataAttestedLoaderError("executed license does not cover Mexico")
    valid_from = _utc(license_record["valid_from_utc"], field_name="license valid_from_utc")
    valid_until = _utc(license_record["valid_until_utc"], field_name="license valid_until_utc")
    if not valid_from <= verification_at <= valid_until:
        raise CCDataAttestedLoaderError("commercial license is not valid at verification time")
    expected = (
        ("terms_receipt_sha256", "LICENSE_TERMS"),
        ("grant_receipt_sha256", "LICENSE_GRANT"),
        ("quote_receipt_sha256", "COMMERCIAL_QUOTE"),
    )
    selected: list[CCDataSourceReceipt] = []
    for field_name, role in expected:
        receipt_sha = _sha256(license_record[field_name], field_name=field_name)
        receipt = receipts_by_hash.get(receipt_sha)
        if receipt is None or receipt.role != role:
            raise CCDataAttestedLoaderError(
                f"license {field_name} does not bind the {role} receipt"
            )
        selected.append(receipt)
    return selected[0], selected[1], selected[2]


def _validate_vintage_policy(
    value: object,
    *,
    receipts_by_hash: Mapping[str, CCDataSourceReceipt],
    knowledge_cutoff: datetime,
    attestation_issued_at: datetime,
) -> None:
    record = _expect_keys(value, _VINTAGE_KEYS, field_name="vintage_policy")
    _identifier(record["policy_id"], field_name="vintage policy_id")
    _identifier(record["policy_version"], field_name="vintage policy_version")
    policy_sha = _sha256(
        record["revision_policy_receipt_sha256"],
        field_name="revision_policy_receipt_sha256",
    )
    receipt = receipts_by_hash.get(policy_sha)
    if receipt is None or receipt.role != "REVISION_POLICY":
        raise CCDataAttestedLoaderError("vintage policy does not bind revision-policy bytes")
    if not _strict_bool(
        record["historical_vintages_preserved"],
        field_name="historical_vintages_preserved",
    ):
        raise CCDataAttestedLoaderError("historical vintages are not preserved")
    if not _strict_bool(
        record["corrections_are_append_only"],
        field_name="corrections_are_append_only",
    ):
        raise CCDataAttestedLoaderError("provider corrections are not append-only revisions")
    if not _strict_bool(
        record["correction_log_includes_revised_at"],
        field_name="correction_log_includes_revised_at",
    ):
        raise CCDataAttestedLoaderError(
            "correction log does not bind when each revision became knowable"
        )
    if not _strict_bool(
        record["correction_log_includes_old_and_new_values"],
        field_name="correction_log_includes_old_and_new_values",
    ):
        raise CCDataAttestedLoaderError(
            "correction log does not bind both pre- and post-revision values"
        )
    complete_through = _utc(
        record["revision_history_complete_through_utc"],
        field_name="revision_history_complete_through_utc",
    )
    if not knowledge_cutoff <= complete_through <= attestation_issued_at:
        raise CCDataAttestedLoaderError(
            "revision history is incomplete at cutoff or claims knowledge after attestation"
        )


def _verify_attestation(
    value: Mapping[str, Any],
    raw: bytes,
    signature: bytes,
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    trust_root: AttestationTrustRoot,
    verification_at: datetime,
) -> datetime:
    record = _expect_keys(value, _ATTESTATION_KEYS, field_name="attestation")
    if record["schema_version"] != SCHEMA_VERSION or record["statement_type"] != STATEMENT_TYPE:
        raise CCDataAttestedLoaderError("attestation statement identity is unsupported")
    _identifier(record["statement_id"], field_name="attestation statement_id")
    if record["issuer_id"] != trust_root.issuer_id or record["key_id"] != trust_root.key_id:
        raise CCDataAttestedLoaderError("attestation is not issued by the supplied trust root")
    if record["algorithm"] != trust_root.algorithm:
        raise CCDataAttestedLoaderError("attestation algorithm differs from the trust root")
    issued = _utc(record["issued_at_utc"], field_name="attestation issued_at_utc")
    expires = _utc(record["expires_at_utc"], field_name="attestation expires_at_utc")
    root_start = _utc(trust_root.valid_from_utc, field_name="trust root valid_from_utc")
    root_end = _utc(trust_root.valid_until_utc, field_name="trust root valid_until_utc")
    if not root_start <= issued <= verification_at <= min(root_end, expires):
        raise CCDataAttestedLoaderError(
            "attestation or trust root is not valid at verification time"
        )
    if (
        record["provider_name"] != PROVIDER_NAME
        or record["provider_product_id"] != manifest["provider_product_id"]
        or record["delivery_id"] != manifest["delivery_id"]
    ):
        raise CCDataAttestedLoaderError("attestation subject differs from the manifest")
    if record["provider_product_id"] not in trust_root.allowed_provider_product_ids:
        raise CCDataAttestedLoaderError("provider product is outside the trust-root scope")
    if (
        _sha256(record["manifest_sha256"], field_name="attestation manifest_sha256")
        != manifest_sha256
    ):
        raise CCDataAttestedLoaderError("attestation does not bind the exact manifest bytes")
    claims = _expect_keys(record["claims"], _CLAIM_KEYS, field_name="attestation claims")
    if any(not _strict_bool(claims[key], field_name=f"attestation claim {key}") for key in claims):
        raise CCDataAttestedLoaderError("every required external attestation claim must be true")
    try:
        Ed25519SignatureVerifier().verify(
            algorithm=trust_root.algorithm,
            verification_key=trust_root.verification_key,
            message=raw,
            signature=signature,
        )
    except CCDataAttestedLoaderError:
        raise
    except Exception as exc:
        raise CCDataAttestedLoaderError("detached attestation signature is invalid") from exc
    return issued


def _parse_calendar(raw: bytes, *, knowledge_cutoff: datetime) -> tuple[str, ...]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CCDataAttestedLoaderError("paper calendar bytes are not JSON") from exc
    expected = {"schema_version", "calendar_name", "method_version", "source_name", "dates"}
    record = _expect_keys(payload, expected, field_name="paper calendar")
    if raw != (canonical_dumps(record) + "\n").encode("utf-8"):
        raise CCDataAttestedLoaderError("paper calendar is not canonical JSON plus LF")
    if record["schema_version"] != SCHEMA_VERSION or record["calendar_name"] != PAPER_CALENDAR_NAME:
        raise CCDataAttestedLoaderError("paper calendar identity is unsupported")
    _identifier(record["method_version"], field_name="calendar method_version")
    _identifier(record["source_name"], field_name="calendar source_name")
    if not isinstance(record["dates"], list) or not record["dates"]:
        raise CCDataAttestedLoaderError("paper calendar dates must be a non-empty list")
    parsed = tuple(_date(item, field_name="paper calendar date") for item in record["dates"])
    if parsed != tuple(sorted(set(parsed))):
        raise CCDataAttestedLoaderError("paper calendar dates must be strictly increasing")
    if any(item.weekday() >= 5 for item in parsed):
        raise CCDataAttestedLoaderError("paper calendar contains a weekend")
    return tuple(item.isoformat() for item in parsed if item < knowledge_cutoff.date())


def _causal_projection(
    rows: tuple[AttestedWorldOrderFlowRow, ...], *, knowledge_cutoff: datetime
) -> tuple[AttestedWorldOrderFlowRow, ...]:
    by_cell: dict[tuple[str, str, str, str, str], AttestedWorldOrderFlowRow] = {}
    for row in rows:
        if _utc(row.available_at_utc, field_name="row available_at_utc") > knowledge_cutoff:
            continue
        key = (
            row.stable_asset_id,
            row.chain_id,
            row.contract_or_native_id,
            row.measurement_date,
            row.fiat_currency,
        )
        previous = by_cell.get(key)
        if previous is None or previous.revision_sequence < row.revision_sequence:
            by_cell[key] = row
        elif previous.revision_sequence == row.revision_sequence:
            raise CCDataAttestedLoaderError(
                "two causal rows claim the same cell and revision sequence"
            )
    if not by_cell:
        raise CCDataAttestedLoaderError("bundle has no observations available at the cutoff")
    return tuple(
        sorted(
            by_cell.values(),
            key=lambda row: (
                row.stable_asset_id,
                row.chain_id,
                row.contract_or_native_id,
                row.measurement_date,
                row.fiat_currency,
            ),
        )
    )


def load_attested_ccdata_bundle(
    bundle_dir: str | Path,
    *,
    trust_root: AttestationTrustRoot,
    parser: CCDataRawParser,
    knowledge_cutoff_utc: str,
    verification_at_utc: str,
) -> LoadedAttestedCCDataBundle:
    """Load and re-derive one signed CCData evidence bundle entirely offline.

    ``trust_root`` must be distributed independently of ``bundle_dir``.  The
    historical ``knowledge_cutoff_utc`` selects the first available revision
    for each cell as of that instant; ``verification_at_utc`` is the explicit,
    reproducible instant at which key, signature, and license validity are
    evaluated.
    """

    root = Path(bundle_dir)
    if not root.is_dir() or root.is_symlink():
        raise CCDataAttestedLoaderError("bundle_dir must be a real directory, not a symlink")
    knowledge_cutoff = _utc(knowledge_cutoff_utc, field_name="knowledge_cutoff_utc")
    verification_at = _utc(verification_at_utc, field_name="verification_at_utc")
    if knowledge_cutoff > verification_at:
        raise CCDataAttestedLoaderError("knowledge cutoff cannot follow verification time")

    manifest, manifest_raw = _read_canonical_json(root, MANIFEST_FILENAME)
    _expect_keys(manifest, _MANIFEST_KEYS, field_name="manifest")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["bundle_type"] != BUNDLE_TYPE:
        raise CCDataAttestedLoaderError("manifest identity is unsupported")
    if manifest["provider_name"] != PROVIDER_NAME:
        raise CCDataAttestedLoaderError("manifest provider must be CCData")
    product_id = _identifier(manifest["provider_product_id"], field_name="provider_product_id")
    delivery_id = _identifier(manifest["delivery_id"], field_name="delivery_id")
    provider_schema_version = _identifier(
        manifest["provider_schema_version"], field_name="provider_schema_version"
    )
    if manifest["source_contract"] != SOURCE_CONTRACT:
        raise CCDataAttestedLoaderError("manifest does not bind the paper's multi-venue contract")
    _sorted_unique_texts(manifest["provider_operation_ids"], field_name="provider_operation_ids")
    provider_fields = _sorted_unique_texts(
        manifest["required_provider_fields"], field_name="required_provider_fields"
    )
    if not set(REQUIRED_PROVIDER_FIELDS) <= set(provider_fields):
        raise CCDataAttestedLoaderError(
            "contracted provider schema omits signed-volume or replay/correction fields"
        )
    parser_name = _identifier(manifest["parser_name"], field_name="parser_name")
    parser_version = _identifier(manifest["parser_version"], field_name="parser_version")
    for field_name in (
        "classification_method",
        "classification_method_version",
        "aggregation_method",
        "aggregation_method_version",
    ):
        _identifier(manifest[field_name], field_name=field_name)

    attestation, attestation_raw = _read_canonical_json(root, ATTESTATION_FILENAME)
    signature_path = _contained_path(root, SIGNATURE_FILENAME, field_name=SIGNATURE_FILENAME)
    signature = signature_path.read_bytes()
    if not signature or len(signature) > _MAX_SIGNATURE_BYTES:
        raise CCDataAttestedLoaderError("detached signature has an invalid byte length")
    manifest_sha = sha256_of_bytes(manifest_raw)
    issued_at = _verify_attestation(
        attestation,
        attestation_raw,
        signature,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        trust_root=trust_root,
        verification_at=verification_at,
    )

    receipts, raw_by_receipt = _parse_receipts(
        root, manifest["source_receipts"], verification_at=verification_at
    )
    receipts_by_hash = {receipt.receipt_sha256: receipt for receipt in receipts}
    terms, grant, quote = _validate_license(
        manifest["license"],
        receipts_by_hash=receipts_by_hash,
        verification_at=verification_at,
    )
    _validate_vintage_policy(
        manifest["vintage_policy"],
        receipts_by_hash=receipts_by_hash,
        knowledge_cutoff=knowledge_cutoff,
        attestation_issued_at=issued_at,
    )

    derived = _expect_keys(
        manifest["derived_artifacts"], _DERIVED_KEYS, field_name="derived_artifacts"
    )
    normalized_path, normalized_raw = _verify_artifact(
        root,
        _expect_keys(
            derived["normalized_observations"],
            _ARTIFACT_KEYS,
            field_name="normalized_observations",
        ),
        field_name="normalized_observations",
    )
    venues_path, venues_raw = _verify_artifact(
        root,
        _expect_keys(
            derived["venue_constituents"],
            _ARTIFACT_KEYS,
            field_name="venue_constituents",
        ),
        field_name="venue_constituents",
    )
    revisions_path, revisions_raw = _verify_artifact(
        root,
        _expect_keys(
            derived["revision_log"],
            _ARTIFACT_KEYS,
            field_name="revision_log",
        ),
        field_name="revision_log",
    )
    if len({normalized_path, venues_path, revisions_path}) != 3:
        raise CCDataAttestedLoaderError("derived artifacts must use distinct files")

    role_receipts = {
        receipt.role: receipt for receipt in receipts if receipt.role != DATA_SOURCE_ROLE
    }
    schema_receipt = role_receipts["PROVIDER_SCHEMA"]
    for label, actual, expected in (
        ("parser_name", getattr(parser, "parser_name", None), parser_name),
        ("parser_version", getattr(parser, "parser_version", None), parser_version),
        ("provider_product_id", getattr(parser, "provider_product_id", None), product_id),
        (
            "provider_schema_version",
            getattr(parser, "provider_schema_version", None),
            provider_schema_version,
        ),
        (
            "provider_schema_sha256",
            getattr(parser, "provider_schema_sha256", None),
            schema_receipt.sha256,
        ),
    ):
        if actual != expected:
            raise CCDataAttestedLoaderError(f"reviewed parser {label} differs from manifest")

    expected_observations: list[dict[str, Any]] = []
    expected_venues: list[dict[str, Any]] = []
    data_receipts = {
        receipt.receipt_sha256: receipt for receipt in receipts if receipt.role == DATA_SOURCE_ROLE
    }
    _validate_revision_log(revisions_raw, data_receipts=data_receipts)
    for receipt in receipts:
        if receipt.role != DATA_SOURCE_ROLE:
            continue
        try:
            parsed = parser.parse(raw_by_receipt[receipt.receipt_sha256], receipt=receipt)
        except CCDataAttestedLoaderError:
            raise
        except Exception as exc:
            raise CCDataAttestedLoaderError("contracted CCData parser failed") from exc
        if not isinstance(parsed, ParsedCCDataDelivery):
            raise CCDataAttestedLoaderError("contracted parser returned the wrong result type")
        expected_observations.extend(parsed.observations)
        expected_venues.extend(parsed.venue_constituents)

    observation_records = _parse_jsonl(normalized_raw, field_name="normalized observations")
    venue_records = _parse_jsonl(venues_raw, field_name="venue constituents")
    if tuple(expected_observations) != observation_records:
        raise CCDataAttestedLoaderError(
            "normalized observations were not exactly re-derived from provider bytes"
        )
    if tuple(expected_venues) != venue_records:
        raise CCDataAttestedLoaderError(
            "venue constituents were not exactly re-derived from provider bytes"
        )

    rows = tuple(
        _parse_observation(record, data_receipts=data_receipts) for record in observation_records
    )
    venue_coverage = _validate_venue_rows(venue_records, data_receipts=data_receipts)
    for row in rows:
        key = (row.source_receipt_sha256, row.measurement_date)
        if venue_coverage.get(key) != row.contributing_venues:
            raise CCDataAttestedLoaderError(
                "observation venues differ from the attested vintage constituent list"
            )

    causal_rows = _causal_projection(rows, knowledge_cutoff=knowledge_cutoff)
    causal_bytes = b"".join(
        (canonical_dumps(row.to_dict()) + "\n").encode("utf-8") for row in causal_rows
    )
    causal_receipts = sorted({row.source_receipt_sha256 for row in causal_rows})
    calendar_receipt = role_receipts["PAPER_CALENDAR"]
    calendar_dates = _parse_calendar(
        raw_by_receipt[calendar_receipt.receipt_sha256], knowledge_cutoff=knowledge_cutoff
    )
    return LoadedAttestedCCDataBundle(
        root=root.resolve(),
        provider_product_id=product_id,
        delivery_id=delivery_id,
        classification_method=str(manifest["classification_method"]),
        classification_method_version=str(manifest["classification_method_version"]),
        knowledge_cutoff_utc=knowledge_cutoff_utc,
        verification_at_utc=verification_at_utc,
        attestation_issued_at_utc=issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        manifest_sha256=manifest_sha,
        attestation_sha256=sha256_of_bytes(attestation_raw),
        signature_sha256=sha256_of_bytes(signature),
        trust_root_sha256=trust_root.seal,
        source_receipt_chain_head_sha256=receipts[-1].receipt_sha256,
        causal_source_receipts_sha256=sha256_of_bytes(
            canonical_dumps(causal_receipts).encode("utf-8")
        ),
        causal_rows_sha256=sha256_of_bytes(causal_bytes),
        rows=causal_rows,
        paper_calendar_dates=calendar_dates,
        license_terms_sha256=terms.sha256,
        license_grant_sha256=grant.sha256,
        commercial_quote_sha256=quote.sha256,
        _verification_token=_VERIFIED_BUNDLE_TOKEN,
    )


__all__ = [
    "ATTESTATION_FILENAME",
    "BUNDLE_TYPE",
    "CCDataAttestedLoaderError",
    "CCDataRawParser",
    "CCDataSourceReceipt",
    "DATA_SOURCE_ROLE",
    "Ed25519SignatureVerifier",
    "LoadedAttestedCCDataBundle",
    "MANIFEST_FILENAME",
    "PAPER_CALENDAR_NAME",
    "PROVIDER_NAME",
    "REQUIRED_LICENSE_USES",
    "REQUIRED_PROVIDER_FIELDS",
    "ParsedCCDataDelivery",
    "SCHEMA_VERSION",
    "SIGNATURE_ALGORITHM",
    "SIGNATURE_FILENAME",
    "SOURCE_CONTRACT",
    "STATEMENT_TYPE",
    "AttestationTrustRoot",
    "AttestedWorldOrderFlowRow",
    "load_attested_ccdata_bundle",
]
