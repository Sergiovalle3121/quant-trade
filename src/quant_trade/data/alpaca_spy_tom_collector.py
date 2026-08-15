"""Read-only Alpaca evidence collector for the sealed SPY TOM evaluator.

This module is deliberately separate from every execution adapter.  It can
only issue allowlisted HTTP GET requests for public market evidence, never
queries an account, and never stores credentials.  Collection is resumable in
a content-addressed staging directory; publishing is an atomic, no-overwrite
rename.

The resulting bundle matches ``alpaca_spy_sip_development_bundle_v2``.  The
extra ``.collector`` directory keeps the exact HTTP response bytes and a hash
chain for audit/resume.  It is not consumed as external authority by the
development evaluator and must never be committed to source control.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import math
import os
import stat
import tempfile
import time as time_module
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

COLLECTOR_SCHEMA = "alpaca_spy_sip_readonly_collector_v1"
MANIFEST_SCHEMA = "alpaca_spy_sip_development_bundle_v2"
SCHEMA_VERSION = 1
SYMBOL = "SPY"
CALENDAR_ID = "XNYS"

DATA_BASE_URL = "https://data.alpaca.markets"
PAPER_BASE_URL = "https://paper-api.alpaca.markets"

API_KEY_ENV = "ALPACA_PAPER_API_KEY"
API_SECRET_ENV = "ALPACA_PAPER_SECRET_KEY"
DATA_PLAN_ENV = "ALPACA_MARKET_DATA_PLAN"

_FORBIDDEN_CREDENTIAL_ENV_VARS = (
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "APCA_API_BASE_URL",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL",
)

PLAN_BASIC = "BASIC"
PLAN_PLUS = "ALGO_TRADER_PLUS"
_PLAN_CALLS_PER_MINUTE = {PLAN_BASIC: 200, PLAN_PLUS: 10_000}
_EARLIEST_HISTORICAL_DATE = date(2016, 1, 1)
_BASIC_SIP_DELAY = timedelta(minutes=15)
_MINIMUM_ATTESTABLE_PAIRS = 120
_NY = ZoneInfo("America/New_York")
_ZERO_SHA256 = "0" * 64
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_NORMALIZED_CHUNK_BYTES = 128 * 1024 * 1024
_MAX_STATE_BYTES = 64 * 1024 * 1024
_MAX_FEE_SCHEDULE_BYTES = 4 * 1024 * 1024
_MAX_CALENDAR_ROWS_BYTES = 64 * 1024 * 1024
_MAX_CORPORATE_ACTION_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_RESPONSE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TOTAL_ROWS_BYTES = 2 * 1024 * 1024 * 1024
_MAX_RECORDED_REQUESTS = 5_000
_MAX_HTTP_ATTEMPTS_PER_INVOCATION = 6_000
_MAX_MARKET_WINDOWS = 600
_MAX_PAGES_PER_MARKET_WINDOW = 16
_MARKET_WINDOW_START = time(15, 56)
_MARKET_WINDOW_END = time(15, 58)
_COLLECTOR_STATE_VERSION = 3
_ROLE_CURSOR_FIELDS = (
    "complete",
    "next_page_token",
    "next_chunk_index",
    "next_sequence",
    "last_timestamp",
)
_MARKET_COLLECTION_MODE = "EXACT_EVENT_WINDOWS_1556_1558_ET"

_ENDPOINTS = {
    "calendar": "/v2/calendar",
    "quotes": "/v2/stocks/SPY/quotes",
    "trades": "/v2/stocks/SPY/trades",
    "corporate_actions": "/v2/corporate_actions/announcements",
    "fees": "/disclosures/fees",
}
_ALLOWED_GET_TARGETS = {
    ("paper-api.alpaca.markets", _ENDPOINTS["calendar"]),
    ("paper-api.alpaca.markets", _ENDPOINTS["corporate_actions"]),
    ("data.alpaca.markets", _ENDPOINTS["quotes"]),
    ("data.alpaca.markets", _ENDPOINTS["trades"]),
}
_NETWORK_ROLES = ("calendar", "quotes", "trades", "corporate_actions")
_SOURCE_ROLES = (*_NETWORK_ROLES, "fees")
_MANIFEST_ROLES = (*_SOURCE_ROLES, "receipts")
_FINAL_PATHS = {
    "calendar": "raw/calendar.jsonl",
    "quotes": "raw/quotes.jsonl",
    "trades": "raw/trades.jsonl",
    "corporate_actions": "raw/corporate_actions.jsonl",
    "fees": "raw/fees.jsonl",
    "receipts": "raw/receipts.jsonl",
}


class AlpacaSpyTomCollectorError(RuntimeError):
    """A fail-closed preflight, collection, or evidence-integrity error."""


class AlpacaSpyTomTransportError(RuntimeError):
    """A redacted transport error safe to retry without exposing credentials."""


@dataclass(frozen=True)
class HttpResponse:
    """Minimal immutable response boundary used by real and mocked transports."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class ReadOnlyTransport(Protocol):
    """Transport that exposes GET only; there is no generic request method."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse: ...


class _WindowsFileLockApi(Protocol):
    """Typed subset of ``msvcrt`` used for non-blocking file locks."""

    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, file_descriptor: int, mode: int, byte_count: int, /) -> None: ...


class _PosixFileLockApi(Protocol):
    """Typed subset of ``fcntl`` used for non-blocking file locks."""

    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, file_descriptor: int, operation: int, /) -> None: ...


def _windows_file_lock_api() -> _WindowsFileLockApi:
    return cast(_WindowsFileLockApi, importlib.import_module("msvcrt"))


def _posix_file_lock_api() -> _PosixFileLockApi:
    return cast(_PosixFileLockApi, importlib.import_module("fcntl"))


def _lock_file_descriptor(file_descriptor: int) -> None:
    if os.name == "nt":
        windows_lock_api = _windows_file_lock_api()
        windows_lock_api.locking(file_descriptor, windows_lock_api.LK_NBLCK, 1)
        return
    posix_lock_api = _posix_file_lock_api()
    posix_lock_api.flock(
        file_descriptor,
        posix_lock_api.LOCK_EX | posix_lock_api.LOCK_NB,
    )


def _unlock_file_descriptor(file_descriptor: int) -> None:
    if os.name == "nt":
        windows_lock_api = _windows_file_lock_api()
        windows_lock_api.locking(file_descriptor, windows_lock_api.LK_UNLCK, 1)
        return
    posix_lock_api = _posix_file_lock_api()
    posix_lock_api.flock(file_descriptor, posix_lock_api.LOCK_UN)


class RequestsReadOnlyTransport:
    """Explicit opt-in GET-only transport for the official allowlisted hosts."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        _require_allowlisted_get(url)
        response: Any | None = None
        try:
            import requests

            outbound_headers = dict(headers)
            outbound_headers["Accept-Encoding"] = "identity"
            response = requests.get(
                url,
                params=dict(params),
                headers=outbound_headers,
                timeout=timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            response_headers = {str(key): str(value) for key, value in response.headers.items()}
            content_encoding = next(
                (
                    value
                    for key, value in response_headers.items()
                    if key.casefold() == "content-encoding"
                ),
                None,
            )
            if content_encoding is not None and content_encoding.strip().casefold() not in {
                "",
                "identity",
            }:
                raise AlpacaSpyTomCollectorError("ALPACA_COMPRESSED_RESPONSE_IS_NOT_PERMITTED")
            content_length = next(
                (
                    value
                    for key, value in response_headers.items()
                    if key.casefold() == "content-length"
                ),
                None,
            )
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise AlpacaSpyTomCollectorError("ALPACA_CONTENT_LENGTH_IS_INVALID") from exc
                if declared_length < 0 or declared_length > _MAX_RESPONSE_BYTES:
                    raise AlpacaSpyTomCollectorError("ALPACA_RESPONSE_IS_TOO_LARGE")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise AlpacaSpyTomCollectorError("ALPACA_RESPONSE_IS_TOO_LARGE")
                body.extend(chunk)
            return HttpResponse(
                status_code=int(response.status_code),
                headers=response_headers,
                body=bytes(body),
            )
        except AlpacaSpyTomCollectorError:
            raise
        except Exception:
            # Never interpolate the provider exception: some HTTP stacks include
            # request headers or URLs in exception representations.
            raise AlpacaSpyTomTransportError("ALPACA_GET_TRANSPORT_FAILED") from None
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    response.close()


@dataclass(frozen=True, repr=False)
class _Credentials:
    key_id: str
    secret_key: str
    plan: str

    def __repr__(self) -> str:
        return f"_Credentials(key_id=<redacted>, secret_key=<redacted>, plan={self.plan!r})"


@dataclass(frozen=True)
class AlpacaSpyTomCollectorConfig:
    """Immutable boundaries for one historical, development-only capture."""

    output_root: Path
    start: datetime
    hard_cutoff: datetime
    as_of: datetime
    fee_schedule_path: Path
    expected_fee_schedule_sha256: str
    timeout_seconds: float = 30.0
    max_retries: int = 4
    maximum_retry_after_seconds: float = 60.0
    maximum_run_seconds: float = 3_600.0


@dataclass(frozen=True)
class CollectionResult:
    """Published local evidence address; never a trading or promotion result."""

    bundle_root: Path
    manifest_sha256: str
    captured_at_utc: str
    request_count: int
    maximum_attestable_pairs: int
    development_only: bool = field(default=True, init=False)
    external_data_authority_verified: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    real_money_authorized: bool = field(default=False, init=False)


class _CollectionMutex:
    """Cross-process, crash-released lock for one output identity."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any | None = None

    def __enter__(self) -> _CollectionMutex:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            descriptor = os.open(
                self._path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
                0o600,
            )
            handle = os.fdopen(descriptor, "r+b", buffering=0)
            created = True
        except FileExistsError:
            handle = _open_regular_single_link(
                self._path,
                "r+b",
                "COLLECTION_LOCK_FILE_IS_UNSAFE",
            )
        try:
            if created:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            else:
                handle.seek(0)
                if handle.read(2) != b"\0":
                    raise AlpacaSpyTomCollectorError("COLLECTION_LOCK_FILE_IS_UNSAFE")
            handle.seek(0)
            _lock_file_descriptor(handle.fileno())
        except AlpacaSpyTomCollectorError:
            handle.close()
            raise
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise AlpacaSpyTomCollectorError(
                "COLLECTION_OUTPUT_IS_LOCKED_BY_ANOTHER_PROCESS"
            ) from exc
        self._handle = handle
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        with contextlib.suppress(OSError):
            handle.seek(0)
            _unlock_file_descriptor(handle.fileno())
        handle.close()


def _utc(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE")
    try:
        normalized = value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_OUTSIDE_SUPPORTED_RANGE") from exc
    if not 2016 <= normalized.year <= 2100:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_OUTSIDE_SUPPORTED_RANGE")
    return normalized


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_TIMESTAMP_IS_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_TIMESTAMP_IS_INVALID") from exc
    return _utc(parsed, name)


def _sha256(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_SHA256_IS_INVALID")
    return value


def _strict_json(payload: bytes, name: str) -> Any:
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_RESPONSE_IS_TOO_LARGE")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("non-finite constant")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_RESPONSE_IS_NOT_STRICT_JSON") from exc


def _canonical_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise AlpacaSpyTomCollectorError("CANONICAL_JSONL_MUST_NOT_BE_EMPTY")
    try:
        return ("".join(canonical_dumps(dict(row)) + "\n" for row in rows)).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AlpacaSpyTomCollectorError("CANONICAL_JSONL_VALUE_IS_INVALID") from exc


def _read_canonical_jsonl(payload: bytes, name: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_NOT_UTF8") from exc
    if not text or not text.endswith("\n") or "\r" in text:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_NOT_CANONICAL_JSONL")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parsed = _strict_json(line.encode("utf-8"), name)
        if not isinstance(parsed, dict) or canonical_dumps(parsed) != line:
            raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_NOT_CANONICAL_JSONL")
        rows.append(parsed)
    if not rows:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_EMPTY")
    return rows


def _decimal_text(value: Any, name: str, *, positive: bool = True) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_INVALID")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_INVALID") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_INVALID")
    if number.adjusted() > 12 or number.adjusted() < -12:
        raise AlpacaSpyTomCollectorError(f"{name.upper()}_IS_OUTSIDE_SAFE_RANGE")
    return format(number, "f")


def _normalize_plan(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {"ALGOTRADER_PLUS": PLAN_PLUS, "ALGO_TRADER_PLUS": PLAN_PLUS, "BASIC": PLAN_BASIC}
    if normalized not in aliases:
        raise AlpacaSpyTomCollectorError("ALPACA_MARKET_DATA_PLAN_IS_NOT_RECOGNIZED")
    return aliases[normalized]


def _credentials_from_env(environ: Mapping[str, str]) -> _Credentials:
    if any(environ.get(name, "") for name in _FORBIDDEN_CREDENTIAL_ENV_VARS):
        raise AlpacaSpyTomCollectorError("GENERIC_OR_LIVE_ALPACA_CREDENTIAL_ENV_VARS_ARE_FORBIDDEN")
    key = environ.get(API_KEY_ENV, "")
    secret = environ.get(API_SECRET_ENV, "")
    plan_value = environ.get(DATA_PLAN_ENV, "")
    if not key or not secret:
        raise AlpacaSpyTomCollectorError("ALPACA_DATA_CREDENTIAL_ENV_VARS_ARE_MISSING")
    if not plan_value:
        raise AlpacaSpyTomCollectorError("ALPACA_MARKET_DATA_PLAN_ENV_VAR_IS_MISSING")
    if any(character.isspace() for character in key + secret):
        raise AlpacaSpyTomCollectorError("ALPACA_DATA_CREDENTIAL_ENV_VARS_ARE_INVALID")
    return _Credentials(key_id=key, secret_key=secret, plan=_normalize_plan(plan_value))


def _validate_fee_evidence(config: AlpacaSpyTomCollectorConfig) -> bytes:
    expected = _sha256(config.expected_fee_schedule_sha256, "expected_fee_schedule")
    path = config.fee_schedule_path
    if path.is_symlink() or not path.is_file():
        raise AlpacaSpyTomCollectorError("FEE_SCHEDULE_IS_MISSING_OR_SYMLINKED")
    payload = _read_bounded_regular_file(
        path,
        _MAX_FEE_SCHEDULE_BYTES,
        "FEE_SCHEDULE_IS_UNREADABLE_OR_TOO_LARGE",
    )
    if sha256_of_bytes(payload) != expected:
        raise AlpacaSpyTomCollectorError("FEE_SCHEDULE_SHA256_MISMATCH")
    rows = _read_canonical_jsonl(payload, "fee_schedule")
    required = {
        "effective_start",
        "effective_end",
        "commission_bps_per_side",
        "regulatory_sell_bps",
        "regulatory_sell_fixed_cents",
        "source_url",
    }
    prior_end: date | None = None
    for row in rows:
        if set(row) != required:
            raise AlpacaSpyTomCollectorError("FEE_SCHEDULE_ROW_SCHEMA_MISMATCH")
        try:
            start = date.fromisoformat(str(row["effective_start"]))
            end = date.fromisoformat(str(row["effective_end"]))
        except ValueError as exc:
            raise AlpacaSpyTomCollectorError("FEE_SCHEDULE_DATE_IS_INVALID") from exc
        if start > end or (prior_end is not None and start != prior_end + timedelta(days=1)):
            raise AlpacaSpyTomCollectorError("FEE_SCHEDULE_INTERVALS_ARE_NOT_CONTIGUOUS")
        _decimal_text(row["commission_bps_per_side"], "commission_bps", positive=False)
        regulatory = Decimal(
            _decimal_text(row["regulatory_sell_bps"], "regulatory_sell_bps", positive=False)
        )
        if regulatory < Decimal("0.01"):
            raise AlpacaSpyTomCollectorError("REGULATORY_SELL_BPS_IS_BELOW_EVALUATOR_FLOOR")
        fixed = row["regulatory_sell_fixed_cents"]
        if type(fixed) is not int or fixed < 0 or fixed > 10_000:
            raise AlpacaSpyTomCollectorError("REGULATORY_FIXED_FEE_IS_INVALID")
        source = row["source_url"]
        if not isinstance(source, str):
            raise AlpacaSpyTomCollectorError("FEE_SOURCE_URL_IS_INVALID")
        parsed = urlsplit(source)
        if parsed.scheme != "https" or parsed.hostname not in {
            "alpaca.markets",
            "docs.alpaca.markets",
            "files.alpaca.markets",
        }:
            raise AlpacaSpyTomCollectorError("FEE_SOURCE_URL_IS_NOT_OFFICIAL_ALPACA")
        prior_end = end
    return payload


def _validate_config(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    *,
    observed_now: datetime,
    allow_clock_after_as_of_for_offline_publish: bool = False,
) -> tuple[datetime, datetime, datetime]:
    start = _utc(config.start, "start")
    cutoff = _utc(config.hard_cutoff, "hard_cutoff")
    as_of = _utc(config.as_of, "as_of")
    now = _utc(observed_now, "clock")
    if not start < cutoff <= as_of:
        raise AlpacaSpyTomCollectorError("COLLECTION_TIME_BOUNDARIES_ARE_INVALID")
    if now < cutoff or (now > as_of and not allow_clock_after_as_of_for_offline_publish):
        raise AlpacaSpyTomCollectorError("COLLECTION_CLOCK_IS_OUTSIDE_CUTOFF_AND_AS_OF")
    start_local = start.astimezone(_NY)
    cutoff_local = cutoff.astimezone(_NY)
    if start_local.date() < _EARLIEST_HISTORICAL_DATE:
        raise AlpacaSpyTomCollectorError("ALPACA_STOCK_HISTORY_BEFORE_2016_IS_UNAVAILABLE")
    if start_local.time().replace(tzinfo=None) != time(9, 30):
        raise AlpacaSpyTomCollectorError("START_MUST_EQUAL_FIRST_XNYS_SESSION_OPEN")
    if cutoff_local.time().replace(tzinfo=None) not in {time(13), time(16)}:
        raise AlpacaSpyTomCollectorError("HARD_CUTOFF_MUST_EQUAL_LAST_XNYS_SESSION_CLOSE")
    if credentials.plan == PLAN_BASIC and cutoff > now - _BASIC_SIP_DELAY:
        raise AlpacaSpyTomCollectorError("BASIC_PLAN_SIP_CUTOFF_MUST_BE_AT_LEAST_15_MINUTES_OLD")
    if not math.isfinite(config.timeout_seconds) or not 1 <= config.timeout_seconds <= 120:
        raise AlpacaSpyTomCollectorError("TIMEOUT_SECONDS_IS_INVALID")
    if type(config.max_retries) is not int or not 0 <= config.max_retries <= 10:
        raise AlpacaSpyTomCollectorError("MAX_RETRIES_IS_INVALID")
    if (
        not math.isfinite(config.maximum_retry_after_seconds)
        or not 0 <= config.maximum_retry_after_seconds <= 60
    ):
        raise AlpacaSpyTomCollectorError("MAXIMUM_RETRY_AFTER_SECONDS_IS_INVALID")
    if (
        isinstance(config.maximum_run_seconds, bool)
        or not isinstance(config.maximum_run_seconds, (int, float))
        or not math.isfinite(config.maximum_run_seconds)
        or not 60 <= config.maximum_run_seconds <= 21_600
    ):
        raise AlpacaSpyTomCollectorError("MAXIMUM_RUN_SECONDS_IS_INVALID")
    output = config.output_root
    if output.exists() or output.is_symlink():
        raise AlpacaSpyTomCollectorError("OUTPUT_ROOT_ALREADY_EXISTS_NO_OVERWRITE")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.is_symlink():
        raise AlpacaSpyTomCollectorError("OUTPUT_PARENT_MUST_NOT_BE_A_SYMLINK")
    return start, cutoff, as_of


def _require_allowlisted_get(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or (parsed.hostname, parsed.path) not in _ALLOWED_GET_TARGETS
    ):
        raise AlpacaSpyTomCollectorError("NETWORK_GET_TARGET_IS_NOT_ALLOWLISTED")


def _safe_relative(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative:
        raise AlpacaSpyTomCollectorError("COLLECTOR_PATH_IS_INVALID")
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AlpacaSpyTomCollectorError("COLLECTOR_PATH_IS_INVALID")
    resolved_root = root.resolve()
    candidate = (resolved_root / path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AlpacaSpyTomCollectorError("COLLECTOR_PATH_ESCAPES_STAGING_ROOT") from exc
    return candidate


def _open_regular_single_link(path: Path, mode: str, reason: str) -> Any:
    """Open one existing regular inode without following or accepting hardlinks."""

    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AlpacaSpyTomCollectorError(reason)
        handle = path.open(mode)
        after = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
        ):
            handle.close()
            raise AlpacaSpyTomCollectorError(reason)
    except AlpacaSpyTomCollectorError:
        raise
    except OSError as exc:
        raise AlpacaSpyTomCollectorError(reason) from exc
    return handle


def _read_bounded_regular_file(path: Path, maximum_bytes: int, reason: str) -> bytes:
    handle = _open_regular_single_link(path, "rb", reason)
    try:
        declared_size = os.fstat(handle.fileno()).st_size
        if declared_size < 0 or declared_size > maximum_bytes:
            raise AlpacaSpyTomCollectorError(reason)
        payload = bytearray()
        while chunk := handle.read(min(1024 * 1024, maximum_bytes + 1 - len(payload))):
            payload.extend(chunk)
            if len(payload) > maximum_bytes:
                raise AlpacaSpyTomCollectorError(reason)
        if len(payload) != declared_size or os.fstat(handle.fileno()).st_size != declared_size:
            raise AlpacaSpyTomCollectorError(reason)
    except AlpacaSpyTomCollectorError:
        raise
    except OSError as exc:
        raise AlpacaSpyTomCollectorError(reason) from exc
    finally:
        handle.close()
    return bytes(payload)


def _write_exclusive_or_verify(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_digest = sha256_of_bytes(payload)
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise AlpacaSpyTomCollectorError("EXISTING_CONTENT_ADDRESSED_FILE_MISMATCH")
        observed_digest, observed_size = _file_digest_and_size(path, maximum_bytes=len(payload))
        if observed_digest != expected_digest or observed_size != len(payload):
            raise AlpacaSpyTomCollectorError("EXISTING_CONTENT_ADDRESSED_FILE_MISMATCH")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink():
                raise AlpacaSpyTomCollectorError(
                    "EXISTING_CONTENT_ADDRESSED_FILE_MISMATCH"
                ) from None
            observed_digest, observed_size = _file_digest_and_size(path, maximum_bytes=len(payload))
            if observed_digest != expected_digest or observed_size != len(payload):
                raise AlpacaSpyTomCollectorError(
                    "EXISTING_CONTENT_ADDRESSED_FILE_MISMATCH"
                ) from None
        except OSError as exc:
            raise AlpacaSpyTomCollectorError(
                "ATOMIC_CONTENT_ADDRESSED_PUBLISH_IS_UNAVAILABLE"
            ) from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _file_digest_and_size(path: Path, *, maximum_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    handle = _open_regular_single_link(
        path,
        "rb",
        "COLLECTOR_FILE_IS_UNREADABLE_OR_UNSAFE",
    )
    try:
        declared_size = os.fstat(handle.fileno()).st_size
        if declared_size < 0 or declared_size > maximum_bytes:
            raise AlpacaSpyTomCollectorError("COLLECTOR_FILE_EXCEEDS_BYTE_LIMIT")
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > maximum_bytes:
                raise AlpacaSpyTomCollectorError("COLLECTOR_FILE_EXCEEDS_BYTE_LIMIT")
            digest.update(chunk)
        if size != declared_size or os.fstat(handle.fileno()).st_size != declared_size:
            raise AlpacaSpyTomCollectorError("COLLECTOR_FILE_CHANGED_DURING_READ")
    except AlpacaSpyTomCollectorError:
        raise
    except OSError as exc:
        raise AlpacaSpyTomCollectorError("COLLECTOR_FILE_IS_UNREADABLE") from exc
    finally:
        handle.close()
    return digest.hexdigest(), size


def _read_chain_bound_bytes(
    staging: Path,
    entry: Mapping[str, Any],
    kind: str,
) -> bytes:
    """Read exactly the inode whose digest and size are committed in the chain."""

    if kind not in {"response", "rows"}:
        raise AlpacaSpyTomCollectorError("COLLECTOR_CHAIN_FILE_KIND_IS_INVALID")
    relative = entry.get(f"{kind}_path")
    expected_sha = entry.get(f"{kind}_sha256")
    expected_size = entry.get(f"{kind}_bytes")
    if (
        not isinstance(relative, str)
        or not isinstance(expected_sha, str)
        or type(expected_size) is not int
        or expected_size < 0
    ):
        raise AlpacaSpyTomCollectorError(f"COLLECTOR_{kind.upper()}_REFERENCE_IS_INVALID")
    maximum_size = _MAX_RESPONSE_BYTES if kind == "response" else _MAX_NORMALIZED_CHUNK_BYTES
    if expected_size > maximum_size:
        raise AlpacaSpyTomCollectorError(f"COLLECTOR_{kind.upper()}_SIZE_MISMATCH")
    path = _safe_relative(staging, relative)
    payload = _read_bounded_regular_file(
        path,
        expected_size,
        f"COLLECTOR_{kind.upper()}_FILE_IS_UNSAFE",
    )
    if len(payload) != expected_size:
        raise AlpacaSpyTomCollectorError(f"COLLECTOR_{kind.upper()}_SIZE_MISMATCH")
    if sha256_of_bytes(payload) != _sha256(expected_sha, f"collector_{kind}"):
        raise AlpacaSpyTomCollectorError(f"COLLECTOR_{kind.upper()}_SHA256_MISMATCH")
    return payload


def _atomic_state_write(path: Path, state: Mapping[str, Any]) -> None:
    payload = canonical_dumps(dict(state)).encode("utf-8")
    if len(payload) > _MAX_STATE_BYTES:
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_EXCEEDS_BYTE_LIMIT")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


def _config_payload(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    start: datetime,
    cutoff: datetime,
    as_of: datetime,
) -> dict[str, Any]:
    return {
        "collector_schema": COLLECTOR_SCHEMA,
        "start": _utc_text(start),
        "hard_cutoff": _utc_text(cutoff),
        "as_of": _utc_text(as_of),
        "fee_schedule_sha256": config.expected_fee_schedule_sha256,
        "market_data_plan": credentials.plan,
        "symbol": SYMBOL,
        "feed": "SIP",
        "calendar_id": CALENDAR_ID,
        "maximum_run_seconds": config.maximum_run_seconds,
        "resource_budget": {
            "maximum_http_attempts_per_invocation": _MAX_HTTP_ATTEMPTS_PER_INVOCATION,
            "maximum_market_windows": _MAX_MARKET_WINDOWS,
            "maximum_pages_per_market_window": _MAX_PAGES_PER_MARKET_WINDOW,
            "maximum_recorded_requests": _MAX_RECORDED_REQUESTS,
            "maximum_response_bytes": _MAX_RESPONSE_BYTES,
            "maximum_total_response_bytes": _MAX_TOTAL_RESPONSE_BYTES,
            "maximum_total_rows_bytes": _MAX_TOTAL_ROWS_BYTES,
        },
    }


def _new_state(config_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": _COLLECTOR_STATE_VERSION,
        "collector_schema": COLLECTOR_SCHEMA,
        "config_sha256": config_sha256,
        "chain_head": _ZERO_SHA256,
        "manifest_captured_at": None,
        "requests": [],
        "roles": {
            role: {
                "complete": False,
                "next_page_token": None,
                "next_chunk_index": 0,
                "next_sequence": 0,
                "last_timestamp": None,
                "receipt_id": None,
            }
            for role in _SOURCE_ROLES
        },
    }


def _role_cursor(role_state: Mapping[str, Any]) -> dict[str, Any]:
    return {name: role_state.get(name) for name in _ROLE_CURSOR_FIELDS}


def _validate_role_cursor(cursor: Any, role: str) -> dict[str, Any]:
    if not isinstance(cursor, dict) or set(cursor) != set(_ROLE_CURSOR_FIELDS):
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_CURSOR_SCHEMA_IS_INVALID")
    if type(cursor["complete"]) is not bool:
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_COMPLETE_STATE_IS_INVALID")
    token = cursor["next_page_token"]
    if token is not None and (not isinstance(token, str) or not token):
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_PAGE_TOKEN_IS_INVALID")
    chunk_index = cursor["next_chunk_index"]
    sequence = cursor["next_sequence"]
    if type(chunk_index) is not int or chunk_index < 0:
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_CHUNK_INDEX_IS_INVALID")
    if type(sequence) is not int or sequence < 0:
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_SEQUENCE_IS_INVALID")
    last_timestamp = cursor["last_timestamp"]
    if last_timestamp is not None:
        _parse_timestamp(last_timestamp, f"{role}_cursor_last_timestamp")
    return dict(cursor)


def _load_or_create_state(staging: Path, config_sha256: str) -> dict[str, Any]:
    state_path = staging / ".collector" / "state.json"
    if not staging.exists():
        staging.mkdir(parents=False, exist_ok=False)
        (staging / ".collector").mkdir(exist_ok=False)
        state = _new_state(config_sha256)
        _atomic_state_write(state_path, state)
        return state
    if staging.is_symlink() or not staging.is_dir() or state_path.is_symlink():
        raise AlpacaSpyTomCollectorError("STAGING_ROOT_IS_INVALID")
    payload = _read_bounded_regular_file(
        state_path,
        _MAX_STATE_BYTES,
        "COLLECTOR_STATE_IS_MISSING_UNSAFE_OR_TOO_LARGE",
    )
    parsed = _strict_json(payload, "collector_state")
    if not isinstance(parsed, dict) or canonical_dumps(parsed).encode("utf-8") != payload:
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_IS_NOT_CANONICAL")
    if (
        parsed.get("schema_version") != _COLLECTOR_STATE_VERSION
        or parsed.get("collector_schema") != COLLECTOR_SCHEMA
        or parsed.get("config_sha256") != config_sha256
    ):
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_CONFIG_MISMATCH")
    _verify_state(staging, parsed)
    return parsed


def _request_chain_digest(entry: Mapping[str, Any]) -> str:
    content = {key: value for key, value in entry.items() if key != "receipt_sha256"}
    return sha256_of_bytes(canonical_dumps(content).encode("utf-8"))


def _state_resource_usage(state: Mapping[str, Any]) -> tuple[int, int, int]:
    requests_value = state.get("requests")
    if not isinstance(requests_value, list):
        raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_CHAIN_IS_INVALID")
    response_bytes = 0
    rows_bytes = 0
    for entry in requests_value:
        if not isinstance(entry, dict):
            raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_CHAIN_IS_INVALID")
        response_size = entry.get("response_bytes")
        rows_size = entry.get("rows_bytes")
        if type(response_size) is not int or not 0 <= response_size <= _MAX_RESPONSE_BYTES:
            raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_SIZE_IS_INVALID")
        if type(rows_size) is not int or not 0 <= rows_size <= _MAX_NORMALIZED_CHUNK_BYTES:
            raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_IS_INVALID")
        response_bytes += response_size
        rows_bytes += rows_size
    if len(requests_value) > _MAX_RECORDED_REQUESTS:
        raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_BUDGET_EXCEEDED")
    if response_bytes > _MAX_TOTAL_RESPONSE_BYTES:
        raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_BYTE_BUDGET_EXCEEDED")
    if rows_bytes > _MAX_TOTAL_ROWS_BYTES:
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_BYTE_BUDGET_EXCEEDED")
    return len(requests_value), response_bytes, rows_bytes


def _verify_state(staging: Path, state: Mapping[str, Any]) -> str:
    if (
        state.get("schema_version") != _COLLECTOR_STATE_VERSION
        or state.get("collector_schema") != COLLECTOR_SCHEMA
    ):
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_SCHEMA_MISMATCH")
    manifest_captured_at = state.get("manifest_captured_at")
    if manifest_captured_at is not None:
        _parse_timestamp(manifest_captured_at, "state_manifest_captured_at")
    requests_value = state.get("requests")
    roles = state.get("roles")
    if not isinstance(requests_value, list) or not isinstance(roles, dict):
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_SCHEMA_MISMATCH")
    if set(roles) != set(_SOURCE_ROLES):
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_ROLE_MISMATCH")
    _state_resource_usage(state)
    head = _ZERO_SHA256
    last_role_head: dict[str, str] = {}
    initial_roles = _new_state("0" * 64)["roles"]
    expected_role_cursors = {role: _role_cursor(initial_roles[role]) for role in _SOURCE_ROLES}
    for index, entry in enumerate(requests_value):
        if not isinstance(entry, dict):
            raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_CHAIN_IS_INVALID")
        if entry.get("index") != index or entry.get("previous_receipt_sha256") != head:
            raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_CHAIN_IS_BROKEN")
        role = entry.get("role")
        if role not in _SOURCE_ROLES:
            raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_ROLE_IS_INVALID")
        response_path = entry.get("response_path")
        response_sha = entry.get("response_sha256")
        if not isinstance(response_path, str) or not isinstance(response_sha, str):
            raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_REFERENCE_IS_INVALID")
        response_file = _safe_relative(staging, response_path)
        if response_file.is_symlink() or not response_file.is_file():
            raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_FILE_IS_MISSING")
        observed, observed_size = _file_digest_and_size(
            response_file,
            maximum_bytes=entry["response_bytes"],
        )
        if observed != _sha256(response_sha, "collector_response"):
            raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_SHA256_MISMATCH")
        if entry.get("response_bytes") != observed_size:
            raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_SIZE_MISMATCH")
        rows_path = entry.get("rows_path")
        rows_sha = entry.get("rows_sha256")
        if rows_path is not None:
            if not isinstance(rows_path, str) or not isinstance(rows_sha, str):
                raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_REFERENCE_IS_INVALID")
            rows_file = _safe_relative(staging, rows_path)
            if rows_file.is_symlink() or not rows_file.is_file():
                raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_FILE_IS_MISSING")
            rows_digest, rows_size = _file_digest_and_size(
                rows_file,
                maximum_bytes=entry["rows_bytes"],
            )
            if rows_digest != _sha256(rows_sha, "collector_rows"):
                raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SHA256_MISMATCH")
            if entry.get("rows_bytes") != rows_size:
                raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
        elif entry.get("rows_bytes") != 0:
            raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
        expected = _request_chain_digest(entry)
        if entry.get("receipt_sha256") != expected:
            raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_RECEIPT_SHA256_MISMATCH")
        expected_role_cursors[str(role)] = _validate_role_cursor(
            entry.get("role_state_after"), str(role)
        )
        head = expected
        last_role_head[str(role)] = head
    if state.get("chain_head") != head:
        raise AlpacaSpyTomCollectorError("COLLECTOR_CHAIN_HEAD_MISMATCH")
    for role, role_state in roles.items():
        if not isinstance(role_state, dict):
            raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_STATE_IS_INVALID")
        observed_cursor = _validate_role_cursor(_role_cursor(role_state), role)
        if canonical_dumps(observed_cursor) != canonical_dumps(expected_role_cursors[role]):
            raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_CURSOR_DOES_NOT_MATCH_CHAIN")
        receipt_id = role_state.get("receipt_id")
        if receipt_id is not None and receipt_id != last_role_head.get(role):
            raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_RECEIPT_ID_MISMATCH")
    return head


class _RatePacer:
    def __init__(
        self,
        calls_per_minute: int,
        sleeper: Callable[[float], None],
        monotonic: Callable[[], float],
    ) -> None:
        self._period = 60.0 / calls_per_minute
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self._monotonic()
        if self._last_call is not None:
            remaining = self._period - (now - self._last_call)
            if remaining > 0:
                self._sleeper(remaining)
        self._last_call = self._monotonic()


class _InvocationBudget:
    def __init__(self, monotonic: Callable[[], float], maximum_seconds: float) -> None:
        self._monotonic = monotonic
        self._deadline = monotonic() + maximum_seconds
        self._http_attempts = 0

    def ensure_time(self) -> None:
        if self._monotonic() > self._deadline:
            raise AlpacaSpyTomCollectorError("COLLECTION_INVOCATION_TIME_BUDGET_EXCEEDED")

    def before_http_attempt(self) -> None:
        self.ensure_time()
        if self._http_attempts >= _MAX_HTTP_ATTEMPTS_PER_INVOCATION:
            raise AlpacaSpyTomCollectorError("COLLECTION_HTTP_ATTEMPT_BUDGET_EXCEEDED")
        self._http_attempts += 1


def _retry_delay(response: HttpResponse, attempt: int, maximum: float) -> float:
    headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    raw = headers.get("retry-after")
    if raw is not None:
        try:
            delay = float(raw)
        except ValueError as exc:
            raise AlpacaSpyTomCollectorError("ALPACA_RETRY_AFTER_IS_INVALID") from exc
    else:
        delay = min(float(2**attempt), maximum)
    if not math.isfinite(delay) or delay < 0 or delay > maximum:
        raise AlpacaSpyTomCollectorError("ALPACA_RETRY_DELAY_TOO_LARGE_RESUME_LATER")
    return delay


def _get_with_retries(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    transport: ReadOnlyTransport,
    pacer: _RatePacer,
    budget: _InvocationBudget,
    *,
    url: str,
    params: Mapping[str, str | int],
    sleeper: Callable[[float], None],
) -> HttpResponse:
    _require_allowlisted_get(url)
    headers = {
        "APCA-API-KEY-ID": credentials.key_id,
        "APCA-API-SECRET-KEY": credentials.secret_key,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": f"quant-trade/{COLLECTOR_SCHEMA}",
    }
    for attempt in range(config.max_retries + 1):
        budget.before_http_attempt()
        pacer.wait()
        budget.ensure_time()
        try:
            response = transport.get(
                url,
                params=dict(params),
                headers=headers,
                timeout_seconds=config.timeout_seconds,
            )
        except AlpacaSpyTomTransportError:
            if attempt == config.max_retries:
                raise AlpacaSpyTomCollectorError("ALPACA_GET_FAILED_RESUME_SAFE") from None
            sleeper(min(float(2**attempt), config.maximum_retry_after_seconds))
            continue
        if response.status_code == 200:
            response_headers = {
                str(key).casefold(): str(value).strip().casefold()
                for key, value in response.headers.items()
            }
            if response_headers.get("content-encoding", "identity") not in {"", "identity"}:
                raise AlpacaSpyTomCollectorError("ALPACA_COMPRESSED_RESPONSE_IS_NOT_PERMITTED")
            if (
                credentials.key_id.encode() in response.body
                or credentials.secret_key.encode() in response.body
            ):
                raise AlpacaSpyTomCollectorError("ALPACA_RESPONSE_ECHOED_A_CREDENTIAL")
            if len(response.body) > _MAX_RESPONSE_BYTES:
                raise AlpacaSpyTomCollectorError("ALPACA_RESPONSE_IS_TOO_LARGE")
            return response
        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        if retryable and attempt < config.max_retries:
            sleeper(_retry_delay(response, attempt, config.maximum_retry_after_seconds))
            continue
        if response.status_code == 401:
            raise AlpacaSpyTomCollectorError("ALPACA_CREDENTIALS_REJECTED")
        if response.status_code == 403:
            raise AlpacaSpyTomCollectorError("ALPACA_SIP_ACCESS_FORBIDDEN_VERIFY_PLAN")
        if response.status_code == 429:
            raise AlpacaSpyTomCollectorError("ALPACA_RATE_LIMIT_EXHAUSTED_RESUME_SAFE")
        raise AlpacaSpyTomCollectorError(
            f"ALPACA_READ_ONLY_GET_REJECTED_STATUS_{response.status_code}"
        )
    raise AssertionError("unreachable retry loop")


def _checkpoint_response(
    staging: Path,
    state: dict[str, Any],
    *,
    role: str,
    endpoint: str,
    params: Mapping[str, str | int],
    response: HttpResponse,
    captured_at: datetime,
    rows: bytes | None,
    role_state_updates: Mapping[str, Any],
) -> None:
    if not set(role_state_updates).issubset(_ROLE_CURSOR_FIELDS):
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROLE_CURSOR_UPDATE_IS_INVALID")
    role_state_after = _role_cursor(state["roles"][role])
    role_state_after.update(dict(role_state_updates))
    role_state_after = _validate_role_cursor(role_state_after, role)
    request_count, response_total, rows_total = _state_resource_usage(state)
    if request_count >= _MAX_RECORDED_REQUESTS:
        raise AlpacaSpyTomCollectorError("COLLECTOR_REQUEST_BUDGET_EXCEEDED")
    if response_total + len(response.body) > _MAX_TOTAL_RESPONSE_BYTES:
        raise AlpacaSpyTomCollectorError("COLLECTOR_RESPONSE_BYTE_BUDGET_EXCEEDED")
    if rows_total + (len(rows) if rows is not None else 0) > _MAX_TOTAL_ROWS_BYTES:
        raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_BYTE_BUDGET_EXCEEDED")
    response_sha = sha256_of_bytes(response.body)
    response_relative = f".collector/responses/{role}/{response_sha}.json"
    _write_exclusive_or_verify(_safe_relative(staging, response_relative), response.body)
    rows_relative: str | None = None
    rows_sha: str | None = None
    if rows is not None:
        rows_sha = sha256_of_bytes(rows)
        rows_relative = f".collector/rows/{role}/{rows_sha}.jsonl"
        _write_exclusive_or_verify(_safe_relative(staging, rows_relative), rows)
    request_index = len(state["requests"])
    entry: dict[str, Any] = {
        "index": request_index,
        "role": role,
        "endpoint": endpoint,
        "request_parameters": dict(params),
        "http_status": 200,
        "captured_at_utc": _utc_text(captured_at),
        "response_path": response_relative,
        "response_sha256": response_sha,
        "response_bytes": len(response.body),
        "rows_path": rows_relative,
        "rows_sha256": rows_sha,
        "rows_bytes": len(rows) if rows is not None else 0,
        "role_state_after": role_state_after,
        "previous_receipt_sha256": state["chain_head"],
    }
    receipt_sha = _request_chain_digest(entry)
    entry["receipt_sha256"] = receipt_sha
    state["requests"].append(entry)
    state["chain_head"] = receipt_sha
    state["roles"][role]["receipt_id"] = receipt_sha
    state["roles"][role].update(role_state_after)
    _atomic_state_write(staging / ".collector" / "state.json", state)


def _response_payload(response: HttpResponse, role: str) -> Any:
    return _strict_json(response.body, f"alpaca_{role}")


def _calendar_timestamp(day: date, value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise AlpacaSpyTomCollectorError(f"CALENDAR_{name.upper()}_IS_INVALID")
    if len(value) in {5, 8} and value[2] == ":":
        try:
            local_time = time.fromisoformat(value)
        except ValueError as exc:
            raise AlpacaSpyTomCollectorError(f"CALENDAR_{name.upper()}_IS_INVALID") from exc
        return datetime.combine(day, local_time, tzinfo=_NY).astimezone(UTC)
    return _parse_timestamp(value, f"calendar_{name}")


def _normalize_calendar_response(
    response: HttpResponse,
    *,
    start: datetime,
    cutoff: datetime,
) -> bytes:
    payload = _response_payload(response, "calendar")
    if not isinstance(payload, list) or not payload:
        raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_RESPONSE_SCHEMA_MISMATCH")
    rows: list[dict[str, Any]] = []
    prior: date | None = None
    for item in payload:
        if not isinstance(item, dict) or not {"date", "open", "close"}.issubset(item):
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_ROW_SCHEMA_MISMATCH")
        try:
            day = date.fromisoformat(str(item["date"]))
        except ValueError as exc:
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_DATE_IS_INVALID") from exc
        opened = _calendar_timestamp(day, item["open"], "open")
        closed = _calendar_timestamp(day, item["close"], "close")
        if prior is not None and day <= prior:
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_IS_NOT_STRICTLY_ORDERED")
        if opened.astimezone(_NY).time().replace(tzinfo=None) != time(9, 30):
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_OPEN_IS_NOT_0930_ET")
        if closed.astimezone(_NY).time().replace(tzinfo=None) not in {time(13), time(16)}:
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_CLOSE_IS_NOT_1300_OR_1600_ET")
        if not start <= opened < closed <= cutoff:
            raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_EXCEEDS_HARD_BOUNDARY")
        rows.append(
            {"date": day.isoformat(), "open": _utc_text(opened), "close": _utc_text(closed)}
        )
        prior = day
    if _parse_timestamp(rows[0]["open"], "calendar_first_open") != start:
        raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_FIRST_OPEN_MISMATCH")
    if _parse_timestamp(rows[-1]["close"], "calendar_last_close") != cutoff:
        raise AlpacaSpyTomCollectorError("ALPACA_CALENDAR_LAST_CLOSE_MISMATCH")
    return _canonical_jsonl(rows)


def _attestable_pair_event_dates(calendar_payload: bytes) -> tuple[int, tuple[date, ...]]:
    """Return eligible pairs and the exact deduplicated event sessions they need."""

    rows = _read_canonical_jsonl(calendar_payload, "calendar")
    grouped: dict[str, list[tuple[date, datetime]]] = {}
    for row in rows:
        try:
            session_date = date.fromisoformat(str(row["date"]))
        except (KeyError, ValueError) as exc:
            raise AlpacaSpyTomCollectorError("CALENDAR_DATE_IS_INVALID_FOR_PAIR_PREFLIGHT") from exc
        closed = _parse_timestamp(row.get("close"), "calendar_pair_close")
        grouped.setdefault(session_date.strftime("%Y-%m"), []).append((session_date, closed))
    months = sorted(grouped)
    if len(months) < 2:
        raise AlpacaSpyTomCollectorError("MAXIMUM_ATTESTABLE_PAIRS_BELOW_120")
    month_indices: list[int] = []
    for month in months:
        year_value, month_value = (int(part) for part in month.split("-"))
        month_indices.append(year_value * 12 + month_value - 1)
        sessions = grouped[month]
        if len(sessions) < 12 or sessions[0][0].day > 7 or sessions[-1][0].day < 22:
            raise AlpacaSpyTomCollectorError("CALENDAR_MONTH_IS_NOT_COMPLETE_FOR_PAIR_PREFLIGHT")
    if any(
        right != left + 1 for left, right in zip(month_indices, month_indices[1:], strict=False)
    ):
        raise AlpacaSpyTomCollectorError("CALENDAR_MONTHS_ARE_NOT_ADJACENT_FOR_PAIR_PREFLIGHT")

    eligible = 0
    event_dates: set[date] = set()
    for anchor, following in zip(months, months[1:], strict=False):
        anchor_sessions = grouped[anchor]
        following_sessions = grouped[following]
        event_sessions = (
            anchor_sessions[-2],
            following_sessions[2],
            following_sessions[7],
            following_sessions[11],
        )
        if all(
            closed.astimezone(_NY).time().replace(tzinfo=None) >= time(15, 58)
            for _, closed in event_sessions
        ):
            eligible += 1
            event_dates.update(session_date for session_date, _ in event_sessions)
    ordered_dates = tuple(sorted(event_dates))
    if len(ordered_dates) > _MAX_MARKET_WINDOWS:
        raise AlpacaSpyTomCollectorError("MARKET_EVENT_WINDOW_BUDGET_EXCEEDED")
    return eligible, ordered_dates


def _maximum_attestable_pairs(calendar_payload: bytes) -> int:
    """Apply the sealed four-event/early-close rule before tick downloads."""

    return _attestable_pair_event_dates(calendar_payload)[0]


def _market_event_windows(calendar_payload: bytes) -> tuple[tuple[datetime, datetime], ...]:
    _, event_dates = _attestable_pair_event_dates(calendar_payload)
    return tuple(
        (
            datetime.combine(session_date, _MARKET_WINDOW_START, tzinfo=_NY).astimezone(UTC),
            datetime.combine(session_date, _MARKET_WINDOW_END, tzinfo=_NY).astimezone(UTC),
        )
        for session_date in event_dates
    )


def _market_window_scope_from_state(
    state: Mapping[str, Any],
    role: str,
    *,
    scope_start: str,
    scope_end: str,
) -> dict[str, Any]:
    windows: set[tuple[str, str]] = set()
    for entry in state["requests"]:
        if entry["role"] != role:
            continue
        params = entry["request_parameters"]
        if (
            not isinstance(params, dict)
            or params.get("feed") != "sip"
            or params.get("limit") != 10_000
            or params.get("sort") != "asc"
        ):
            raise AlpacaSpyTomCollectorError(f"{role.upper()}_REQUEST_SCOPE_IS_INVALID")
        start = params.get("start")
        end = params.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            raise AlpacaSpyTomCollectorError(f"{role.upper()}_REQUEST_SCOPE_IS_INVALID")
        windows.add((start, end))
    if not windows:
        raise AlpacaSpyTomCollectorError(f"{role.upper()}_REQUEST_SCOPE_IS_EMPTY")
    canonical_windows = [{"end": end, "start": start} for start, end in sorted(windows)]
    return {
        "collection_mode": _MARKET_COLLECTION_MODE,
        "event_window_count": len(canonical_windows),
        "event_windows_sha256": sha256_of_bytes(canonical_dumps(canonical_windows).encode("utf-8")),
        "feed": "SIP",
        "limit": 10_000,
        "scope_end": scope_end,
        "scope_start": scope_start,
        "sort": "asc",
        "symbol": SYMBOL,
    }


def _pair_capacity_preflight(staging: Path, state: dict[str, Any]) -> int:
    calendar_payload = _role_rows(staging, state, "calendar")
    eligible, event_dates = _attestable_pair_event_dates(calendar_payload)
    state["roles"]["calendar"]["maximum_attestable_pairs"] = eligible
    state["roles"]["calendar"]["market_event_window_count"] = len(event_dates)
    _atomic_state_write(staging / ".collector" / "state.json", state)
    if eligible < _MINIMUM_ATTESTABLE_PAIRS:
        raise AlpacaSpyTomCollectorError("MAXIMUM_ATTESTABLE_PAIRS_BELOW_120")
    return eligible


def _market_page(
    response: HttpResponse,
    role: str,
    *,
    start: datetime,
    cutoff: datetime,
    next_sequence: int,
    last_timestamp: datetime | None,
) -> tuple[bytes, str | None, int, datetime | None]:
    payload = _response_payload(response, role)
    if not isinstance(payload, dict):
        raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_RESPONSE_SCHEMA_MISMATCH")
    items = payload.get(role)
    if not isinstance(items, list):
        raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_ROWS_ARE_MISSING")
    symbol = payload.get("symbol")
    if symbol is not None and symbol != SYMBOL:
        raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_SYMBOL_IS_NOT_SPY")
    token = payload.get("next_page_token")
    if token is not None and (not isinstance(token, str) or not token):
        raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_PAGE_TOKEN_IS_INVALID")
    rows: list[dict[str, Any]] = []
    observed_last = last_timestamp
    for item in items:
        if not isinstance(item, dict):
            raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_ROW_SCHEMA_MISMATCH")
        timestamp = _parse_timestamp(item.get("t"), f"{role}_timestamp")
        if not start <= timestamp <= cutoff:
            raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_EXCEEDS_HARD_CUTOFF")
        if observed_last is not None and timestamp < observed_last:
            raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_IS_NOT_ASCENDING")
        if role == "quotes":
            bid_price = _decimal_text(item.get("bp"), "quote_bid")
            ask_price = _decimal_text(item.get("ap"), "quote_ask")
            row = {
                "timestamp": _utc_text(timestamp),
                "symbol": SYMBOL,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "bid_size": _decimal_text(item.get("bs"), "quote_bid_size"),
                "ask_size": _decimal_text(item.get("as"), "quote_ask_size"),
                "sequence": next_sequence,
            }
            if Decimal(ask_price) < Decimal(bid_price):
                raise AlpacaSpyTomCollectorError("ALPACA_QUOTE_MARKET_IS_CROSSED")
        else:
            exchange = item.get("x")
            if not isinstance(exchange, str) or not exchange:
                raise AlpacaSpyTomCollectorError("ALPACA_TRADE_EXCHANGE_IS_INVALID")
            row = {
                "timestamp": _utc_text(timestamp),
                "symbol": SYMBOL,
                "price": _decimal_text(item.get("p"), "trade_price"),
                "size": _decimal_text(item.get("s"), "trade_size"),
                "exchange": exchange,
                "sequence": next_sequence,
            }
        rows.append(row)
        next_sequence += 1
        observed_last = timestamp
    if not rows and token is not None:
        raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_EMPTY_PAGE_HAS_TOKEN")
    rows_payload = _canonical_jsonl(rows) if rows else b""
    return rows_payload, token, next_sequence, observed_last


def _corporate_chunks(start: datetime, cutoff: datetime) -> tuple[tuple[date, date], ...]:
    cursor = start.astimezone(_NY).date()
    final = cutoff.astimezone(_NY).date()
    chunks: list[tuple[date, date]] = []
    while cursor <= final:
        # Alpaca documents a maximum difference of 90 days for announcements.
        chunk_end = min(cursor + timedelta(days=90), final)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return tuple(chunks)


def _corporate_response_rows(response: HttpResponse) -> list[dict[str, Any]]:
    payload = _response_payload(response, "corporate_actions")
    if not isinstance(payload, list):
        raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_RESPONSE_SCHEMA_MISMATCH")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_ROW_SCHEMA_MISMATCH")
        rows.append(dict(item))
    return rows


def _normalize_corporate_actions(
    staging: Path,
    state: Mapping[str, Any],
    *,
    start: datetime,
    cutoff: datetime,
) -> bytes:
    grouped: dict[str, list[dict[str, Any]]] = {}
    total_source_bytes = 0
    for entry in state["requests"]:
        if entry["role"] != "corporate_actions":
            continue
        raw = _read_chain_bound_bytes(staging, entry, "response")
        total_source_bytes += len(raw)
        if total_source_bytes > _MAX_CORPORATE_ACTION_BYTES:
            raise AlpacaSpyTomCollectorError("CORPORATE_ACTION_SOURCE_BYTE_BUDGET_EXCEEDED")
        response = HttpResponse(200, {}, raw)
        for item in _corporate_response_rows(response):
            symbol = item.get("initiating_symbol")
            if symbol != SYMBOL:
                raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_SYMBOL_IS_NOT_SPY")
            corporate_id = item.get("corporate_action_id") or item.get("id")
            if not isinstance(corporate_id, str) or not corporate_id:
                raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_ID_IS_INVALID")
            grouped.setdefault(corporate_id, []).append(item)
    normalized: list[dict[str, Any]] = []
    for corporate_id, revisions in grouped.items():
        typed: list[tuple[date, str, dict[str, Any]]] = []
        for revision in revisions:
            try:
                declared = date.fromisoformat(str(revision.get("declaration_date")))
            except ValueError as exc:
                raise AlpacaSpyTomCollectorError(
                    "ALPACA_CORPORATE_ACTION_DECLARATION_DATE_IS_INVALID"
                ) from exc
            announcement_id = revision.get("id")
            if not isinstance(announcement_id, str) or not announcement_id:
                raise AlpacaSpyTomCollectorError("ALPACA_ANNOUNCEMENT_ID_IS_INVALID")
            typed.append((declared, announcement_id, revision))
        typed.sort(key=lambda value: (value[0], value[1]))
        earliest_date = typed[0][0]
        revised_date, _, latest = typed[-1]
        try:
            effective = date.fromisoformat(str(latest.get("ex_date")))
        except ValueError as exc:
            raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_EX_DATE_IS_INVALID") from exc
        if not start.astimezone(_NY).date() <= effective <= cutoff.astimezone(_NY).date():
            continue
        if revised_date > effective:
            raise AlpacaSpyTomCollectorError("ALPACA_CORPORATE_ACTION_REVISION_IS_POST_EFFECTIVE")
        action_type = str(latest.get("ca_type", "")).casefold()
        subtype = str(latest.get("ca_sub_type", "")).casefold()
        if action_type == "dividend" and subtype == "cash":
            normalized_type = "CASH_DIVIDEND"
            amount = _decimal_text(latest.get("cash"), "cash_dividend")
            ratio: str | None = None
        elif action_type == "split" and subtype in {
            "stock_split",
            "unit_split",
            "reverse_split",
            "split",
        }:
            old_rate = Decimal(_decimal_text(latest.get("old_rate"), "split_old_rate"))
            new_rate = Decimal(_decimal_text(latest.get("new_rate"), "split_new_rate"))
            normalized_type = "SPLIT"
            amount = None
            ratio = format(new_rate / old_rate, "f")
        else:
            continue
        announced_at = datetime.combine(earliest_date, time(0), tzinfo=UTC)
        revised_at = datetime.combine(revised_date, time(0), tzinfo=UTC)
        normalized.append(
            {
                "action_id": corporate_id,
                "symbol": SYMBOL,
                "action_type": normalized_type,
                "effective_date": effective.isoformat(),
                "announced_at_utc": _utc_text(announced_at),
                "revised_at_utc": _utc_text(revised_at),
                "amount_per_share": amount,
                "split_ratio": ratio,
            }
        )
    normalized.sort(key=lambda row: (row["effective_date"], row["action_type"], row["action_id"]))
    if not any(row["action_type"] == "CASH_DIVIDEND" for row in normalized):
        raise AlpacaSpyTomCollectorError("SPY_CASH_DIVIDEND_EVIDENCE_IS_MISSING")
    return _canonical_jsonl(normalized)


def _role_rows(staging: Path, state: Mapping[str, Any], role: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for entry in state["requests"]:
        if entry["role"] != role or entry.get("rows_path") is None:
            continue
        chunk = _read_chain_bound_bytes(staging, entry, "rows")
        total += len(chunk)
        if total > _MAX_CALENDAR_ROWS_BYTES:
            raise AlpacaSpyTomCollectorError(f"{role.upper()}_ROWS_BYTE_BUDGET_EXCEEDED")
        chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload:
        raise AlpacaSpyTomCollectorError(f"{role.upper()}_COLLECTION_IS_EMPTY")
    _read_canonical_jsonl(payload, role)
    return payload


def _materialize_role_rows(
    staging: Path,
    state: Mapping[str, Any],
    role: str,
    relative: str,
) -> tuple[str, int]:
    """Stream verified row chunks into one artifact without joining them in RAM."""

    target = _safe_relative(staging, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".materializing", dir=target.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    total = 0
    observed_chunk = False
    try:
        with os.fdopen(descriptor, "wb") as output:
            for entry in state["requests"]:
                if entry["role"] != role or entry.get("rows_path") is None:
                    continue
                observed_chunk = True
                source = _safe_relative(staging, entry["rows_path"])
                expected_chunk_size = entry.get("rows_bytes")
                expected_chunk_sha = entry.get("rows_sha256")
                if (
                    type(expected_chunk_size) is not int
                    or not 0 <= expected_chunk_size <= _MAX_NORMALIZED_CHUNK_BYTES
                    or not isinstance(expected_chunk_sha, str)
                ):
                    raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
                chunk_digest = hashlib.sha256()
                chunk_total = 0
                final_chunk_size = -1
                handle = _open_regular_single_link(
                    source,
                    "rb",
                    "COLLECTOR_ROWS_FILE_IS_UNSAFE",
                )
                with handle:
                    if os.fstat(handle.fileno()).st_size != expected_chunk_size:
                        raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
                    while chunk := handle.read(1024 * 1024):
                        chunk_total += len(chunk)
                        if chunk_total > expected_chunk_size:
                            raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
                        total += len(chunk)
                        if total > _MAX_TOTAL_ROWS_BYTES:
                            raise AlpacaSpyTomCollectorError(
                                f"{role.upper()}_ROWS_BYTE_BUDGET_EXCEEDED"
                            )
                        chunk_digest.update(chunk)
                        digest.update(chunk)
                        output.write(chunk)
                    final_chunk_size = os.fstat(handle.fileno()).st_size
                if chunk_total != expected_chunk_size or final_chunk_size != expected_chunk_size:
                    raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SIZE_MISMATCH")
                if chunk_digest.hexdigest() != _sha256(expected_chunk_sha, "collector_rows"):
                    raise AlpacaSpyTomCollectorError("COLLECTOR_ROWS_SHA256_MISMATCH")
            output.flush()
            os.fsync(output.fileno())
        if not observed_chunk or total == 0:
            raise AlpacaSpyTomCollectorError(f"{role.upper()}_COLLECTION_IS_EMPTY")
        expected_digest = digest.hexdigest()
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise AlpacaSpyTomCollectorError("MATERIALIZED_ROLE_TARGET_IS_A_SYMLINK")
            observed_digest, observed_size = _file_digest_and_size(target, maximum_bytes=total)
            if observed_digest != expected_digest or observed_size != total:
                raise AlpacaSpyTomCollectorError("MATERIALIZED_ROLE_TARGET_MISMATCH")
        else:
            try:
                os.link(temporary, target)
            except FileExistsError:
                observed_digest, observed_size = _file_digest_and_size(target, maximum_bytes=total)
                if observed_digest != expected_digest or observed_size != total:
                    raise AlpacaSpyTomCollectorError("MATERIALIZED_ROLE_TARGET_MISMATCH") from None
            except OSError as exc:
                raise AlpacaSpyTomCollectorError(
                    "ATOMIC_MATERIALIZED_ROLE_PUBLISH_IS_UNAVAILABLE"
                ) from exc
        return expected_digest, total
    except OSError as exc:
        raise AlpacaSpyTomCollectorError("MATERIALIZED_ROLE_WRITE_FAILED_RESUME_SAFE") from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _append_local_fee_receipt(
    staging: Path,
    state: dict[str, Any],
    fee_payload: bytes,
    *,
    start: datetime,
    cutoff: datetime,
    captured_at: datetime,
    as_of: datetime,
) -> None:
    if state["roles"]["fees"]["complete"]:
        return
    if captured_at < cutoff or captured_at > as_of:
        raise AlpacaSpyTomCollectorError("FEE_CAPTURE_IS_OUTSIDE_CAUSAL_BOUNDARY")
    params = {
        "effective_start": start.astimezone(_NY).date().isoformat(),
        "effective_end": cutoff.astimezone(_NY).date().isoformat(),
        "scope": "SPY_EQUITY_AND_REGULATORY_FEES",
    }
    response = HttpResponse(status_code=200, headers={}, body=fee_payload)
    _checkpoint_response(
        staging,
        state,
        role="fees",
        endpoint=_ENDPOINTS["fees"],
        params=params,
        response=response,
        captured_at=captured_at,
        rows=fee_payload,
        role_state_updates={"complete": True},
    )


def _collect_calendar(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    transport: ReadOnlyTransport,
    pacer: _RatePacer,
    budget: _InvocationBudget,
    staging: Path,
    state: dict[str, Any],
    *,
    start: datetime,
    cutoff: datetime,
    as_of: datetime,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None],
) -> None:
    if state["roles"]["calendar"]["complete"]:
        return
    params: dict[str, str | int] = {
        "start": start.astimezone(_NY).date().isoformat(),
        "end": cutoff.astimezone(_NY).date().isoformat(),
        "date_type": "TRADING",
    }
    response = _get_with_retries(
        config,
        credentials,
        transport,
        pacer,
        budget,
        url=f"{PAPER_BASE_URL}{_ENDPOINTS['calendar']}",
        params=params,
        sleeper=sleeper,
    )
    captured = _utc(clock(), "calendar_capture")
    if captured > as_of:
        raise AlpacaSpyTomCollectorError("CALENDAR_CAPTURE_IS_AFTER_AS_OF")
    rows = _normalize_calendar_response(response, start=start, cutoff=cutoff)
    _checkpoint_response(
        staging,
        state,
        role="calendar",
        endpoint=_ENDPOINTS["calendar"],
        params=params,
        response=response,
        captured_at=captured,
        rows=rows,
        role_state_updates={"complete": True},
    )


def _collect_market_role(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    transport: ReadOnlyTransport,
    pacer: _RatePacer,
    budget: _InvocationBudget,
    staging: Path,
    state: dict[str, Any],
    role: str,
    *,
    as_of: datetime,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None],
) -> None:
    role_state = state["roles"][role]
    if role_state["complete"]:
        return
    calendar_payload = _role_rows(staging, state, "calendar")
    windows = _market_event_windows(calendar_payload)
    window_index = role_state["next_chunk_index"]
    if type(window_index) is not int or not 0 <= window_index <= len(windows):
        raise AlpacaSpyTomCollectorError(f"{role.upper()}_WINDOW_RESUME_INDEX_IS_INVALID")
    if window_index == len(windows):
        raise AlpacaSpyTomCollectorError(f"{role.upper()}_COMPLETION_STATE_IS_INCONSISTENT")
    next_sequence = role_state["next_sequence"]
    last_timestamp = (
        _parse_timestamp(role_state["last_timestamp"], f"{role}_resume_timestamp")
        if role_state["last_timestamp"] is not None
        else None
    )
    token = role_state["next_page_token"]
    while window_index < len(windows):
        window_start, window_end = windows[window_index]
        start_text = _utc_text(window_start)
        end_text = _utc_text(window_end)
        prior_window_entries = [
            entry
            for entry in state["requests"]
            if entry["role"] == role
            and entry["request_parameters"].get("start") == start_text
            and entry["request_parameters"].get("end") == end_text
        ]
        seen_tokens = {
            str(entry["request_parameters"]["page_token"])
            for entry in prior_window_entries
            if "page_token" in entry["request_parameters"]
        }
        pages_in_window = len(prior_window_entries)
        while True:
            if pages_in_window >= _MAX_PAGES_PER_MARKET_WINDOW:
                raise AlpacaSpyTomCollectorError(
                    f"ALPACA_{role.upper()}_WINDOW_PAGE_BUDGET_EXCEEDED"
                )
            params: dict[str, str | int] = {
                "start": start_text,
                "end": end_text,
                "feed": "sip",
                "limit": 10_000,
                "sort": "asc",
            }
            if token is not None:
                params["page_token"] = token
            response = _get_with_retries(
                config,
                credentials,
                transport,
                pacer,
                budget,
                url=f"{DATA_BASE_URL}{_ENDPOINTS[role]}",
                params=params,
                sleeper=sleeper,
            )
            captured = _utc(clock(), f"{role}_capture")
            if captured > as_of:
                raise AlpacaSpyTomCollectorError(f"{role.upper()}_CAPTURE_IS_AFTER_AS_OF")
            rows, next_token, next_sequence, last_timestamp = _market_page(
                response,
                role,
                start=window_start,
                cutoff=window_end,
                next_sequence=next_sequence,
                last_timestamp=last_timestamp,
            )
            if next_token is not None and (next_token == token or next_token in seen_tokens):
                raise AlpacaSpyTomCollectorError(f"ALPACA_{role.upper()}_PAGE_TOKEN_REPEATED")
            next_window_index = window_index if next_token is not None else window_index + 1
            complete = next_token is None and next_window_index == len(windows)
            _checkpoint_response(
                staging,
                state,
                role=role,
                endpoint=_ENDPOINTS[role],
                params=params,
                response=response,
                captured_at=captured,
                rows=rows if rows else None,
                role_state_updates={
                    "next_page_token": next_token,
                    "next_chunk_index": next_window_index,
                    "next_sequence": next_sequence,
                    "last_timestamp": (
                        _utc_text(last_timestamp) if last_timestamp is not None else None
                    ),
                    "complete": complete,
                },
            )
            pages_in_window += 1
            if next_token is not None:
                seen_tokens.add(next_token)
                token = next_token
                continue
            token = None
            window_index = next_window_index
            break


def _collect_corporate_actions(
    config: AlpacaSpyTomCollectorConfig,
    credentials: _Credentials,
    transport: ReadOnlyTransport,
    pacer: _RatePacer,
    budget: _InvocationBudget,
    staging: Path,
    state: dict[str, Any],
    *,
    start: datetime,
    cutoff: datetime,
    as_of: datetime,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], None],
) -> None:
    role_state = state["roles"]["corporate_actions"]
    if role_state["complete"]:
        return
    chunks = _corporate_chunks(start, cutoff)
    chunk_index = role_state["next_chunk_index"]
    if type(chunk_index) is not int or not 0 <= chunk_index <= len(chunks):
        raise AlpacaSpyTomCollectorError("CORPORATE_ACTION_RESUME_INDEX_IS_INVALID")
    for index in range(chunk_index, len(chunks)):
        since, until = chunks[index]
        params: dict[str, str | int] = {
            "ca_types": "dividend,split",
            "since": since.isoformat(),
            "until": until.isoformat(),
            "symbol": SYMBOL,
            "date_type": "ex_date",
        }
        response = _get_with_retries(
            config,
            credentials,
            transport,
            pacer,
            budget,
            url=f"{PAPER_BASE_URL}{_ENDPOINTS['corporate_actions']}",
            params=params,
            sleeper=sleeper,
        )
        _corporate_response_rows(response)
        captured = _utc(clock(), "corporate_action_capture")
        if captured > as_of:
            raise AlpacaSpyTomCollectorError("CORPORATE_ACTION_CAPTURE_IS_AFTER_AS_OF")
        _checkpoint_response(
            staging,
            state,
            role="corporate_actions",
            endpoint=_ENDPOINTS["corporate_actions"],
            params=params,
            response=response,
            captured_at=captured,
            rows=None,
            role_state_updates={
                "next_chunk_index": index + 1,
                "complete": index + 1 == len(chunks),
            },
        )


def _source_receipts(
    state: Mapping[str, Any],
    artifact_hashes: Mapping[str, str],
    *,
    start: datetime,
    cutoff: datetime,
) -> bytes:
    paths = _FINAL_PATHS
    start_text = _utc_text(start)
    end_text = _utc_text(cutoff)
    market_scopes = {
        role: _market_window_scope_from_state(
            state,
            role,
            scope_start=start_text,
            scope_end=end_text,
        )
        for role in ("quotes", "trades")
    }
    if canonical_dumps(market_scopes["quotes"]) != canonical_dumps(market_scopes["trades"]):
        raise AlpacaSpyTomCollectorError("QUOTE_AND_TRADE_EVENT_WINDOW_SCOPES_DIFFER")
    rows: list[dict[str, Any]] = []
    for role in _SOURCE_ROLES:
        receipt_id = state["roles"][role]["receipt_id"]
        _sha256(receipt_id, f"{role}_receipt")
        if role == "calendar":
            params: dict[str, Any] = {
                "calendar_id": CALENDAR_ID,
                "start_date": start.astimezone(_NY).date().isoformat(),
                "end_date": cutoff.astimezone(_NY).date().isoformat(),
            }
        elif role in {"quotes", "trades"}:
            params = market_scopes[role]
        elif role == "corporate_actions":
            params = {
                "action_types": ["cash_dividend", "split"],
                "end": end_text,
                "start": start_text,
                "symbol": SYMBOL,
            }
        else:
            params = {
                "effective_end": cutoff.astimezone(_NY).date().isoformat(),
                "effective_start": start.astimezone(_NY).date().isoformat(),
                "scope": "SPY_EQUITY_AND_REGULATORY_FEES",
            }
        role_entries = [entry for entry in state["requests"] if entry["role"] == role]
        if not role_entries:
            raise AlpacaSpyTomCollectorError(f"{role.upper()}_RECEIPT_CHAIN_IS_MISSING")
        role_captured = _parse_timestamp(
            role_entries[-1]["captured_at_utc"], f"{role}_receipt_capture"
        )
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "receipt_id": receipt_id,
                "provider": "ALPACA",
                "source_kind": (
                    "ALPACA_OFFICIAL_DOCUMENT_CAPTURE"
                    if role == "fees"
                    else "ALPACA_HISTORICAL_API"
                ),
                "artifact_role": role,
                "endpoint": _ENDPOINTS[role],
                "request_parameters": params,
                "http_status": 200,
                "captured_at_utc": _utc_text(role_captured),
                "raw_path": paths[role],
                "raw_sha256": artifact_hashes[role],
            }
        )
    return _canonical_jsonl(rows)


def _publish_bundle(
    staging: Path,
    output: Path,
    state: dict[str, Any],
    fee_payload: bytes,
    *,
    start: datetime,
    cutoff: datetime,
    as_of: datetime,
    clock: Callable[[], datetime],
    maximum_attestable_pairs: int,
) -> CollectionResult:
    if any(not state["roles"][role]["complete"] for role in _SOURCE_ROLES):
        raise AlpacaSpyTomCollectorError("COLLECTION_IS_NOT_COMPLETE")
    request_captures = [
        _parse_timestamp(entry["captured_at_utc"], "request_capture") for entry in state["requests"]
    ]
    persisted_capture = state.get("manifest_captured_at")
    if persisted_capture is None:
        captured = _utc(clock(), "manifest_capture")
    else:
        captured = _parse_timestamp(persisted_capture, "manifest_capture")
    if captured < cutoff or captured > as_of:
        raise AlpacaSpyTomCollectorError("MANIFEST_CAPTURE_IS_OUTSIDE_CAUSAL_BOUNDARY")
    if request_captures and captured < max(request_captures):
        raise AlpacaSpyTomCollectorError("MANIFEST_CAPTURE_PRECEDES_A_SOURCE_CAPTURE")
    if persisted_capture is None:
        state["manifest_captured_at"] = _utc_text(captured)
        _atomic_state_write(staging / ".collector" / "state.json", state)
    _verify_state(staging, state)
    files: dict[str, dict[str, str]] = {}
    artifact_hashes: dict[str, str] = {}
    for role in ("calendar", "quotes", "trades"):
        relative = _FINAL_PATHS[role]
        digest, _ = _materialize_role_rows(staging, state, role, relative)
        artifact_hashes[role] = digest
        files[role] = {"path": relative, "sha256": digest}
    small_artifacts = {
        "corporate_actions": _normalize_corporate_actions(
            staging, state, start=start, cutoff=cutoff
        ),
        "fees": fee_payload,
    }
    for role, payload in small_artifacts.items():
        relative = _FINAL_PATHS[role]
        _write_exclusive_or_verify(_safe_relative(staging, relative), payload)
        digest = sha256_of_bytes(payload)
        artifact_hashes[role] = digest
        files[role] = {"path": relative, "sha256": digest}
    receipts = _source_receipts(
        state,
        artifact_hashes,
        start=start,
        cutoff=cutoff,
    )
    receipts_relative = _FINAL_PATHS["receipts"]
    _write_exclusive_or_verify(_safe_relative(staging, receipts_relative), receipts)
    files["receipts"] = {
        "path": receipts_relative,
        "sha256": sha256_of_bytes(receipts),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "provider": "ALPACA",
        "feed": "SIP",
        "symbol": SYMBOL,
        "calendar_id": CALENDAR_ID,
        "calendar_source": "ALPACA_CALENDAR_API",
        "start": _utc_text(start),
        "end": _utc_text(cutoff),
        "captured_at_utc": _utc_text(captured),
        "development_only": True,
        "files": files,
    }
    manifest_payload = canonical_dumps(manifest).encode("utf-8")
    _write_exclusive_or_verify(staging / "manifest.json", manifest_payload)
    if output.exists():
        raise AlpacaSpyTomCollectorError("OUTPUT_ROOT_APPEARED_NO_OVERWRITE")
    try:
        staging.rename(output)
    except OSError as exc:
        raise AlpacaSpyTomCollectorError("ATOMIC_BUNDLE_PUBLISH_FAILED_RESUME_SAFE") from exc
    return CollectionResult(
        bundle_root=output.resolve(),
        manifest_sha256=sha256_of_bytes(manifest_payload),
        captured_at_utc=_utc_text(captured),
        request_count=len(state["requests"]),
        maximum_attestable_pairs=maximum_attestable_pairs,
    )


def _collect_alpaca_spy_tom_bundle_locked(
    config: AlpacaSpyTomCollectorConfig,
    transport: ReadOnlyTransport,
    *,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time_module.sleep,
    monotonic: Callable[[], float] = time_module.monotonic,
) -> CollectionResult:
    """Collect and atomically publish one resumable, read-only evidence bundle.

    The caller must explicitly provide a transport.  All tests use a fake; a
    real request is impossible merely by importing or constructing a config.
    Every preflight check runs before the transport can be called.
    """

    selected_environment = os.environ if environ is None else environ
    selected_clock = (lambda: datetime.now(UTC)) if clock is None else clock
    credentials = _credentials_from_env(selected_environment)
    observed_now = selected_clock()
    observed_now_utc = _utc(observed_now, "clock")
    configured_as_of = _utc(config.as_of, "as_of")
    output = config.output_root.resolve()
    staging = output.with_name(f".{output.name}.partial")
    offline_publish_candidate = observed_now_utc > configured_as_of and staging.exists()
    start, cutoff, as_of = _validate_config(
        config,
        credentials,
        observed_now=observed_now,
        allow_clock_after_as_of_for_offline_publish=offline_publish_candidate,
    )
    fee_payload = _validate_fee_evidence(config)
    config_payload = _config_payload(config, credentials, start, cutoff, as_of)
    config_sha = sha256_of_bytes(canonical_dumps(config_payload).encode("utf-8"))
    state = _load_or_create_state(staging, config_sha)
    if observed_now_utc > as_of:
        if state.get("manifest_captured_at") is None or any(
            not state["roles"][role]["complete"] for role in _SOURCE_ROLES
        ):
            raise AlpacaSpyTomCollectorError("COLLECTION_CLOCK_IS_OUTSIDE_CUTOFF_AND_AS_OF")
        maximum_attestable_pairs = _pair_capacity_preflight(staging, state)
        return _publish_bundle(
            staging,
            output,
            state,
            fee_payload,
            start=start,
            cutoff=cutoff,
            as_of=as_of,
            clock=selected_clock,
            maximum_attestable_pairs=maximum_attestable_pairs,
        )
    pacer = _RatePacer(_PLAN_CALLS_PER_MINUTE[credentials.plan], sleeper, monotonic)
    budget = _InvocationBudget(monotonic, config.maximum_run_seconds)

    _collect_calendar(
        config,
        credentials,
        transport,
        pacer,
        budget,
        staging,
        state,
        start=start,
        cutoff=cutoff,
        as_of=as_of,
        clock=selected_clock,
        sleeper=sleeper,
    )
    maximum_attestable_pairs = _pair_capacity_preflight(staging, state)
    _collect_market_role(
        config,
        credentials,
        transport,
        pacer,
        budget,
        staging,
        state,
        "quotes",
        as_of=as_of,
        clock=selected_clock,
        sleeper=sleeper,
    )
    _collect_market_role(
        config,
        credentials,
        transport,
        pacer,
        budget,
        staging,
        state,
        "trades",
        as_of=as_of,
        clock=selected_clock,
        sleeper=sleeper,
    )
    _collect_corporate_actions(
        config,
        credentials,
        transport,
        pacer,
        budget,
        staging,
        state,
        start=start,
        cutoff=cutoff,
        as_of=as_of,
        clock=selected_clock,
        sleeper=sleeper,
    )
    _append_local_fee_receipt(
        staging,
        state,
        fee_payload,
        start=start,
        cutoff=cutoff,
        captured_at=_utc(selected_clock(), "fee_capture"),
        as_of=as_of,
    )
    return _publish_bundle(
        staging,
        output,
        state,
        fee_payload,
        start=start,
        cutoff=cutoff,
        as_of=as_of,
        clock=selected_clock,
        maximum_attestable_pairs=maximum_attestable_pairs,
    )


def collect_alpaca_spy_tom_bundle(
    config: AlpacaSpyTomCollectorConfig,
    transport: ReadOnlyTransport,
    *,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] = time_module.sleep,
    monotonic: Callable[[], float] = time_module.monotonic,
) -> CollectionResult:
    """Serialize one output identity, then run the read-only resumable collector."""

    if type(config) is not AlpacaSpyTomCollectorConfig or not isinstance(config.output_root, Path):
        raise AlpacaSpyTomCollectorError("COLLECTOR_CONFIG_OR_OUTPUT_ROOT_IS_INVALID")
    output_parent = config.output_root.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    if output_parent.is_symlink():
        raise AlpacaSpyTomCollectorError("OUTPUT_PARENT_MUST_NOT_BE_A_SYMLINK")
    lock_path = output_parent.resolve() / f".{config.output_root.name}.collector.lock"
    with _CollectionMutex(lock_path):
        return _collect_alpaca_spy_tom_bundle_locked(
            config,
            transport,
            environ=environ,
            clock=clock,
            sleeper=sleeper,
            monotonic=monotonic,
        )


def verify_alpaca_spy_tom_collection_ledger(bundle_root: str | Path) -> str:
    """Offline verification of the retained HTTP response hash chain."""

    root = Path(bundle_root)
    if root.is_symlink() or not root.is_dir():
        raise AlpacaSpyTomCollectorError("BUNDLE_ROOT_IS_INVALID")
    state_path = root / ".collector" / "state.json"
    payload = _read_bounded_regular_file(
        state_path,
        _MAX_STATE_BYTES,
        "COLLECTOR_STATE_IS_MISSING_UNSAFE_OR_TOO_LARGE",
    )
    state = _strict_json(payload, "collector_state")
    if not isinstance(state, dict) or canonical_dumps(state).encode("utf-8") != payload:
        raise AlpacaSpyTomCollectorError("COLLECTOR_STATE_IS_NOT_CANONICAL")
    return _verify_state(root, state)


__all__ = [
    "API_KEY_ENV",
    "API_SECRET_ENV",
    "COLLECTOR_SCHEMA",
    "DATA_PLAN_ENV",
    "AlpacaSpyTomCollectorConfig",
    "AlpacaSpyTomCollectorError",
    "AlpacaSpyTomTransportError",
    "CollectionResult",
    "HttpResponse",
    "PLAN_BASIC",
    "PLAN_PLUS",
    "ReadOnlyTransport",
    "RequestsReadOnlyTransport",
    "collect_alpaca_spy_tom_bundle",
    "verify_alpaca_spy_tom_collection_ledger",
]
