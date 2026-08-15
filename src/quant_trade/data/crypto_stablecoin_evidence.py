"""Receipt-bound CMC stablecoin tag observations, without causal backfilling.

This module extracts only what an archived CoinMarketCap historical-snapshot
response actually says on the requested date.  It intentionally does *not*
turn the absence of a ``stablecoin`` tag into negative evidence and it never
propagates a classification to another date.

The artifact is evidence-only.  CMC's response timestamp and the local capture
timestamp can be years after the requested snapshot, so this extractor cannot
prove when an individual tag first became public and cannot clear the causal
stablecoin-classification blocker by itself.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from quant_trade.data.universe import UNIVERSE_POLICY, parse_snapshot_page
from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    sha256_of_bytes,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.evidence.receipts import (
    load_receipts,
    normalized_rows_sha256,
    verify_receipt_chain,
)

ARTIFACT_NAME = "stablecoin_observations_v1"
SCHEMA_VERSION = 1
OBSERVATIONS_DIRECTORY = "days"
MANIFEST_FILENAME = f"{ARTIFACT_NAME}.manifest.json"
MANIFEST_SHA256_FILENAME = f"{ARTIFACT_NAME}.manifest.sha256"
RECEIPTS_FILENAME = "receipts.jsonl"

# The protected validation holdout starts on 2023-11-29.  V1 fails before
# opening a source file if asked to cross that boundary.
MAXIMUM_CUTOFF = date(2023, 11, 28)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_CMC_ADAPTER = "data.universe.cmc_snapshots"
_CMC_PROVIDER = "coinmarketcap"


class StablecoinEvidenceError(ValueError):
    """The source evidence or derived artifact is unsafe to use."""


class StablecoinEvidenceState(StrEnum):
    """Tri-state contract for stablecoin evidence.

    ``NON_STABLE`` is reserved for a future independently evidenced, typed
    ledger.  The automatic CMC-tag extractor never emits it.
    """

    STABLECOIN_POSITIVE = "STABLECOIN_POSITIVE"
    NON_STABLE = "NON_STABLE"
    UNKNOWN = "UNKNOWN"


class TagsShape(StrEnum):
    ABSENT = "ABSENT"
    NULL = "NULL"
    LIST = "LIST"


EXTRACTION_POLICY: dict[str, Any] = {
    "artifact_name": ARTIFACT_NAME,
    "automatic_states_emitted": [
        StablecoinEvidenceState.STABLECOIN_POSITIVE,
        StablecoinEvidenceState.UNKNOWN,
    ],
    "classification": (
        "case-insensitive substring 'stablecoin' in any exact source tag => "
        "STABLECOIN_POSITIVE; absent/null/no matching tag => UNKNOWN"
    ),
    "cutoff_maximum": MAXIMUM_CUTOFF.isoformat(),
    "future_receipt_policy": (
        "parse request date only; receipts after cutoff are ignored and their raw paths "
        "are never resolved or opened"
    ),
    "negative_inference": "prohibited",
    "temporal_propagation": "no forward-fill and no backfill",
    "source_adapter": _CMC_ADAPTER,
    "source_endpoint": UNIVERSE_POLICY["endpoint"],
    "source_provider": _CMC_PROVIDER,
}
EXTRACTION_POLICY_SHA256 = sha256_of_text(canonical_dumps(EXTRACTION_POLICY))


def _strict_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StablecoinEvidenceError(f"{field_name} must be an integer >= {minimum}")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StablecoinEvidenceError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _parse_date(value: object, *, field_name: str) -> date:
    if not isinstance(value, str):
        raise StablecoinEvidenceError(f"{field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise StablecoinEvidenceError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise StablecoinEvidenceError(f"{field_name} must use canonical YYYY-MM-DD form")
    return parsed


def _canonical_utc_timestamp(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StablecoinEvidenceError(f"{field_name} must be an explicit UTC timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise StablecoinEvidenceError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise StablecoinEvidenceError(f"{field_name} must include a timezone")
    utc = parsed.astimezone(UTC)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _state_for_tags(tags: tuple[str, ...] | None) -> StablecoinEvidenceState:
    if tags is not None and any("stablecoin" in tag.casefold() for tag in tags):
        return StablecoinEvidenceState.STABLECOIN_POSITIVE
    return StablecoinEvidenceState.UNKNOWN


@dataclass(frozen=True)
class StablecoinObservation:
    cmc_id: int
    snapshot_date: str
    effective_at_utc: str
    tags: tuple[str, ...] | None
    tags_shape: TagsShape
    evidence_state: StablecoinEvidenceState
    request_page_start: int
    source_entry_index: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _strict_int(self.cmc_id, field_name="cmc_id", minimum=1)
        snapshot = _parse_date(self.snapshot_date, field_name="snapshot_date")
        effective = _canonical_utc_timestamp(self.effective_at_utc, field_name="effective_at_utc")
        if effective != self.effective_at_utc:
            raise StablecoinEvidenceError("effective_at_utc must be canonical UTC")
        if datetime.fromisoformat(effective.replace("Z", "+00:00")).date() != snapshot:
            raise StablecoinEvidenceError(
                "effective_at_utc date must equal the receipt-requested snapshot_date"
            )
        _strict_int(self.request_page_start, field_name="request_page_start", minimum=1)
        _strict_int(self.source_entry_index, field_name="source_entry_index", minimum=0)
        _strict_int(self.schema_version, field_name="schema_version", minimum=1)
        if self.schema_version != SCHEMA_VERSION:
            raise StablecoinEvidenceError("unsupported observation schema_version")
        if self.tags_shape is TagsShape.LIST:
            if self.tags is None or any(not isinstance(tag, str) for tag in self.tags):
                raise StablecoinEvidenceError("LIST tags must contain only exact strings")
        elif self.tags is not None:
            raise StablecoinEvidenceError("ABSENT/NULL tags must serialize as null")
        derived = _state_for_tags(self.tags)
        if self.evidence_state is StablecoinEvidenceState.NON_STABLE:
            raise StablecoinEvidenceError(
                "automatic CMC tag observations must never assert NON_STABLE"
            )
        if self.evidence_state is not derived:
            raise StablecoinEvidenceError("evidence_state does not match exact source tags")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags) if self.tags is not None else None
        payload["tags_shape"] = self.tags_shape.value
        payload["evidence_state"] = self.evidence_state.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StablecoinObservation:
        expected = {
            "cmc_id",
            "effective_at_utc",
            "evidence_state",
            "request_page_start",
            "schema_version",
            "snapshot_date",
            "source_entry_index",
            "tags",
            "tags_shape",
        }
        if set(payload) != expected:
            raise StablecoinEvidenceError("observation fields do not match schema v1")
        raw_tags = payload["tags"]
        tags: tuple[str, ...] | None
        if raw_tags is None:
            tags = None
        elif isinstance(raw_tags, list) and all(isinstance(tag, str) for tag in raw_tags):
            tags = tuple(raw_tags)
        else:
            raise StablecoinEvidenceError("tags must be null or a list of strings")
        try:
            tags_shape = TagsShape(payload["tags_shape"])
            evidence_state = StablecoinEvidenceState(payload["evidence_state"])
        except (TypeError, ValueError) as exc:
            raise StablecoinEvidenceError("invalid tags_shape or evidence_state") from exc
        return cls(
            cmc_id=payload["cmc_id"],
            snapshot_date=payload["snapshot_date"],
            effective_at_utc=payload["effective_at_utc"],
            tags=tags,
            tags_shape=tags_shape,
            evidence_state=evidence_state,
            request_page_start=payload["request_page_start"],
            source_entry_index=payload["source_entry_index"],
            schema_version=payload["schema_version"],
        )


@dataclass(frozen=True)
class StablecoinEvidenceBuildResult:
    artifact_dir: str
    cutoff_date: str
    days: int
    source_entries: int
    positive_observations: int
    unknown: int
    manifest_sha256: str
    blocker_cleared: bool = False


@dataclass(frozen=True)
class LoadedStablecoinEvidence:
    root: Path
    manifest: dict[str, Any]

    def iter_observations(self) -> Iterator[StablecoinObservation]:
        days = self.manifest["days"]
        for day_record in days:
            path = self.root / day_record["relative_path"]
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise StablecoinEvidenceError("observation line must be an object")
                    yield StablecoinObservation.from_dict(payload)


@dataclass(frozen=True)
class _SelectedReceipt:
    snapshot_date: date
    page_start: int
    raw_path: str
    raw_sha256: str
    normalized_rows_sha256: str
    receipt_sha256: str
    captured_at_utc: str
    source_kind: str


@dataclass(frozen=True)
class _PageExtraction:
    positive_observations: tuple[StablecoinObservation, ...]
    source_entries: int
    unknown: int
    unknown_by_tags_shape: dict[str, int]
    unknown_evidence_sha256: str
    projection_sha256: str
    source_response_at_utc: str


def _receipt_content_sha256(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_of_text(canonical_dumps(payload))


def _has_symlink_component(path: Path) -> bool:
    """Return true when any existing component preserves indirection."""

    absolute = path.absolute()
    return any(component.is_symlink() for component in (absolute, *absolute.parents))


def _selected_receipts(source_dir: Path, cutoff: date) -> list[_SelectedReceipt]:
    receipts_path = source_dir / RECEIPTS_FILENAME
    if not receipts_path.is_file():
        raise StablecoinEvidenceError(f"missing source receipt ledger: {receipts_path}")
    if _has_symlink_component(receipts_path):
        raise StablecoinEvidenceError("source receipt ledger must not be a symlink")
    try:
        all_receipts = load_receipts(receipts_path)
    except (json.JSONDecodeError, OSError) as exc:
        raise StablecoinEvidenceError(
            "source receipt ledger is not readable canonical JSONL"
        ) from exc
    chain_problems = verify_receipt_chain(all_receipts)
    if chain_problems:
        raise StablecoinEvidenceError(
            "complete source receipt chain is invalid: " + "; ".join(chain_problems)
        )
    selected: list[_SelectedReceipt] = []
    for line_number, receipt in enumerate(all_receipts, start=1):
        if not isinstance(receipt, dict):
            raise StablecoinEvidenceError(f"receipt line {line_number} must be an object")
        parameters = receipt.get("request_parameters")
        if not isinstance(parameters, dict):
            raise StablecoinEvidenceError(
                f"receipt line {line_number} has no request-parameter binding"
            )
        requested = _parse_date(
            parameters.get("date"), field_name=f"receipt line {line_number} request date"
        )
        if requested > cutoff:
            # Deliberately do not inspect, resolve or hash this raw path.
            continue
        if receipt.get("provider_or_venue") != _CMC_PROVIDER:
            raise StablecoinEvidenceError(
                f"receipt line {line_number} is not bound to CoinMarketCap"
            )
        if receipt.get("endpoint") != UNIVERSE_POLICY["endpoint"]:
            raise StablecoinEvidenceError(
                f"receipt line {line_number} endpoint differs from frozen CMC policy"
            )
        if receipt.get("adapter_name") != _CMC_ADAPTER:
            raise StablecoinEvidenceError(
                f"receipt line {line_number} adapter is not {_CMC_ADAPTER}"
            )
        if (
            _strict_int(
                receipt.get("http_status"),
                field_name=f"receipt line {line_number} http_status",
                minimum=100,
            )
            != 200
        ):
            raise StablecoinEvidenceError(f"receipt line {line_number} is not HTTP 200")
        start = _strict_int(
            parameters.get("start"),
            field_name=f"receipt line {line_number} page start",
            minimum=1,
        )
        if start not in UNIVERSE_POLICY["page_starts"]:
            raise StablecoinEvidenceError(
                f"receipt line {line_number} page start differs from frozen CMC policy"
            )
        receipt_sha = _require_sha256(
            receipt.get("receipt_sha256"),
            field_name=f"receipt line {line_number} receipt_sha256",
        )
        if _receipt_content_sha256(receipt) != receipt_sha:
            raise StablecoinEvidenceError(f"receipt content hash mismatch at line {line_number}")
        raw_sha = _require_sha256(
            receipt.get("raw_sha256"),
            field_name=f"receipt line {line_number} raw_sha256",
        )
        normalized_sha = _require_sha256(
            receipt.get("normalized_rows_sha256"),
            field_name=f"receipt line {line_number} normalized_rows_sha256",
        )
        raw_path = receipt.get("raw_path")
        if not isinstance(raw_path, str) or not raw_path:
            raise StablecoinEvidenceError(f"receipt line {line_number} raw_path is required")
        captured = _canonical_utc_timestamp(
            receipt.get("captured_at_utc"),
            field_name=f"receipt line {line_number} captured_at_utc",
        )
        source_kind = receipt.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind:
            raise StablecoinEvidenceError(f"receipt line {line_number} source_kind is required")
        selected.append(
            _SelectedReceipt(
                snapshot_date=requested,
                page_start=start,
                raw_path=raw_path,
                raw_sha256=raw_sha,
                normalized_rows_sha256=normalized_sha,
                receipt_sha256=receipt_sha,
                captured_at_utc=captured,
                source_kind=source_kind,
            )
        )
    return sorted(
        selected,
        key=lambda item: (item.snapshot_date, item.page_start, item.receipt_sha256),
    )


def _resolve_raw_path(source_dir: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise StablecoinEvidenceError("receipt raw_path must be relative")
    root = source_dir.resolve()
    unresolved = root / candidate
    if _has_symlink_component(unresolved):
        raise StablecoinEvidenceError("receipt raw_path must not traverse a symlink")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StablecoinEvidenceError("receipt raw_path escapes source directory") from exc
    if not resolved.is_file():
        raise StablecoinEvidenceError(f"receipt-bound raw payload is missing: {relative_path}")
    return resolved


def _tags_from_entry(entry: dict[str, Any]) -> tuple[tuple[str, ...] | None, TagsShape]:
    if "tags" not in entry:
        return None, TagsShape.ABSENT
    raw_tags = entry["tags"]
    if raw_tags is None:
        return None, TagsShape.NULL
    if not isinstance(raw_tags, list) or any(not isinstance(tag, str) for tag in raw_tags):
        raise StablecoinEvidenceError("CMC tags must be null or a list of exact strings")
    return tuple(raw_tags), TagsShape.LIST


def _extract_page(source_dir: Path, receipt: _SelectedReceipt) -> _PageExtraction:
    raw_path = _resolve_raw_path(source_dir, receipt.raw_path)
    raw = raw_path.read_bytes()
    if sha256_of_bytes(raw) != receipt.raw_sha256:
        raise StablecoinEvidenceError(
            f"raw payload hash mismatch for {receipt.snapshot_date.isoformat()} "
            f"page {receipt.page_start}"
        )
    try:
        normalized = parse_snapshot_page(raw)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise StablecoinEvidenceError("receipt-bound CMC raw payload cannot be reparsed") from exc
    if normalized_rows_sha256(normalized) != receipt.normalized_rows_sha256:
        raise StablecoinEvidenceError(
            f"normalized-row hash mismatch for {receipt.snapshot_date.isoformat()} "
            f"page {receipt.page_start}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StablecoinEvidenceError("CMC raw payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise StablecoinEvidenceError("CMC raw payload must be an object")
    status = payload.get("status")
    if not isinstance(status, dict):
        raise StablecoinEvidenceError("CMC raw payload lacks response status binding")
    source_response_at = _canonical_utc_timestamp(
        status.get("timestamp"), field_name="CMC source response timestamp"
    )
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise StablecoinEvidenceError("CMC raw payload data must be a list")
    if len(entries) != len(normalized):
        raise StablecoinEvidenceError(
            "CMC raw entries do not map one-to-one to receipt-normalized rows"
        )
    positive_observations: list[StablecoinObservation] = []
    unknown_by_shape: Counter[str] = Counter()
    unknown_facts: list[str] = []
    projection_entries: list[dict[str, Any]] = []
    for entry_index, value in enumerate(entries):
        if not isinstance(value, dict):
            raise StablecoinEvidenceError("CMC data entries must be objects")
        cmc_id = _strict_int(value.get("id"), field_name="CMC id", minimum=1)
        if normalized[entry_index].get("cmc_id") != cmc_id:
            raise StablecoinEvidenceError(
                "CMC raw entry order differs from receipt-normalized rows"
            )
        effective_at = _canonical_utc_timestamp(
            value.get("lastUpdated"), field_name=f"CMC:{cmc_id} effective_at"
        )
        effective_date = datetime.fromisoformat(effective_at.replace("Z", "+00:00")).date()
        if effective_date != receipt.snapshot_date:
            raise StablecoinEvidenceError(
                f"CMC:{cmc_id} effective date {effective_date.isoformat()} does not bind to "
                f"receipt request {receipt.snapshot_date.isoformat()}"
            )
        tags, tags_shape = _tags_from_entry(value)
        projection_entry = {
            "cmc_id": cmc_id,
            "effective_at_utc": effective_at,
            "source_entry_index": entry_index,
            "tags": list(tags) if tags is not None else None,
            "tags_shape": tags_shape.value,
        }
        projection_entries.append(projection_entry)
        evidence_state = _state_for_tags(tags)
        if evidence_state is StablecoinEvidenceState.STABLECOIN_POSITIVE:
            positive_observations.append(
                StablecoinObservation(
                    cmc_id=cmc_id,
                    snapshot_date=receipt.snapshot_date.isoformat(),
                    effective_at_utc=effective_at,
                    tags=tags,
                    tags_shape=tags_shape,
                    evidence_state=evidence_state,
                    request_page_start=receipt.page_start,
                    source_entry_index=entry_index,
                )
            )
        else:
            unknown_by_shape[tags_shape.value] += 1
            # This digest binds every compacted UNKNOWN decision, including
            # exact non-matching tags, without serializing millions of rows.
            unknown_facts.append(canonical_dumps(projection_entry))
    projection = {
        "entries": projection_entries,
        "page_start": receipt.page_start,
        "snapshot_date": receipt.snapshot_date.isoformat(),
    }
    return _PageExtraction(
        positive_observations=tuple(positive_observations),
        source_entries=len(entries),
        unknown=sum(unknown_by_shape.values()),
        unknown_by_tags_shape={
            shape.value: unknown_by_shape.get(shape.value, 0) for shape in TagsShape
        },
        unknown_evidence_sha256=sha256_of_text("\n".join(unknown_facts)),
        projection_sha256=sha256_of_text(canonical_dumps(projection)),
        source_response_at_utc=source_response_at,
    )


def _prepare_target(out_dir: Path) -> Path:
    if out_dir.exists() or out_dir.is_symlink():
        raise StablecoinEvidenceError(
            f"artifact output must not already exist (refusing overwrite): {out_dir}"
        )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(out_dir.parent):
        raise StablecoinEvidenceError("artifact output parent must not be a symlink")
    return Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", dir=out_dir.parent))


def build_stablecoin_observations(
    source_dir: str | Path,
    out_dir: str | Path,
    *,
    cutoff_date: date,
) -> StablecoinEvidenceBuildResult:
    """Build deterministic daily tag observations through ``cutoff_date``.

    Post-cutoff receipt metadata is used only to recognize its requested date;
    its raw path is never resolved or opened.  The target must be new so an old
    artifact can never be silently mixed with a new evidence policy.
    """

    if cutoff_date > MAXIMUM_CUTOFF:
        raise StablecoinEvidenceError(
            f"cutoff_date crosses protected holdout; maximum is {MAXIMUM_CUTOFF.isoformat()}"
        )
    source = Path(source_dir)
    if not source.is_dir():
        raise StablecoinEvidenceError(f"source directory does not exist: {source}")
    if _has_symlink_component(source):
        raise StablecoinEvidenceError("source directory must not be a symlink")
    receipts = _selected_receipts(source, cutoff_date)
    if not receipts:
        raise StablecoinEvidenceError("no receipt-bound CMC snapshots exist through cutoff")
    by_day: dict[date, list[_SelectedReceipt]] = defaultdict(list)
    for receipt in receipts:
        by_day[receipt.snapshot_date].append(receipt)

    destination = Path(out_dir)
    temporary = _prepare_target(destination)
    total_source_entries = 0
    total_positive = 0
    total_unknown = 0
    source_kind_counts: Counter[str] = Counter()
    day_records: list[dict[str, Any]] = []
    try:
        days_dir = temporary / OBSERVATIONS_DIRECTORY
        days_dir.mkdir()
        for snapshot_date in sorted(by_day):
            day_receipts = by_day[snapshot_date]
            receipts_by_page: dict[int, list[_SelectedReceipt]] = defaultdict(list)
            for receipt in day_receipts:
                receipts_by_page[receipt.page_start].append(receipt)
            if min(receipts_by_page) != UNIVERSE_POLICY["page_starts"][0]:
                raise StablecoinEvidenceError(
                    f"snapshot {snapshot_date.isoformat()} lacks its first CMC page"
                )
            observations: list[StablecoinObservation] = []
            page_sizes: dict[int, int] = {}
            page_coverages: list[dict[str, Any]] = []
            day_unknown_by_shape: Counter[str] = Counter()
            day_source_entries = 0
            day_unknown = 0
            for page_start in sorted(receipts_by_page):
                corroborating_receipts = sorted(
                    receipts_by_page[page_start],
                    key=lambda item: (item.raw_sha256, item.receipt_sha256),
                )
                extracted = [
                    (receipt, _extract_page(source, receipt)) for receipt in corroborating_receipts
                ]
                projection_digests = {extraction.projection_sha256 for _, extraction in extracted}
                if len(projection_digests) != 1:
                    raise StablecoinEvidenceError(
                        "ambiguous stablecoin-relevant projections for "
                        f"{snapshot_date.isoformat()} page {page_start}"
                    )
                # Every retry above was byte/receipt/normalization verified.
                # Projection equality makes this representative semantic row
                # set independent of capture order and response metadata.
                extraction = extracted[0][1]
                observations.extend(extraction.positive_observations)
                page_sizes[page_start] = extraction.source_entries
                day_source_entries += extraction.source_entries
                day_unknown += extraction.unknown
                day_unknown_by_shape.update(extraction.unknown_by_tags_shape)
                page_coverages.append(
                    {
                        "corroborating_receipts": len(corroborating_receipts),
                        "page_start": page_start,
                        "positive_observations": len(extraction.positive_observations),
                        "projection_sha256": extraction.projection_sha256,
                        "source_captured_at_utcs": sorted(
                            {receipt.captured_at_utc for receipt, _ in extracted}
                        ),
                        "source_entries": extraction.source_entries,
                        "source_kinds": sorted({receipt.source_kind for receipt, _ in extracted}),
                        "source_kind_receipt_counts": dict(
                            sorted(Counter(receipt.source_kind for receipt, _ in extracted).items())
                        ),
                        "source_raw_sha256s": sorted(
                            {receipt.raw_sha256 for receipt, _ in extracted}
                        ),
                        "source_receipt_sha256s": sorted(
                            {receipt.receipt_sha256 for receipt, _ in extracted}
                        ),
                        "source_response_at_utcs": sorted(
                            {item.source_response_at_utc for _, item in extracted}
                        ),
                        "unknown": extraction.unknown,
                        "unknown_by_tags_shape": extraction.unknown_by_tags_shape,
                        "unknown_evidence_sha256": extraction.unknown_evidence_sha256,
                    }
                )
                for receipt, _ in extracted:
                    source_kind_counts[receipt.source_kind] += 1
            first_start = UNIVERSE_POLICY["page_starts"][0]
            second_start = UNIVERSE_POLICY["page_starts"][1]
            first_is_full = page_sizes[first_start] == UNIVERSE_POLICY["page_limit"]
            if first_is_full != (second_start in page_sizes):
                raise StablecoinEvidenceError(
                    f"snapshot {snapshot_date.isoformat()} has an incomplete CMC page set"
                )
            observations.sort(
                key=lambda row: (
                    row.cmc_id,
                    row.request_page_start,
                    row.source_entry_index,
                )
            )
            text = "".join(canonical_dumps(row.to_dict()) + "\n" for row in observations)
            relative_path = f"{OBSERVATIONS_DIRECTORY}/{snapshot_date.isoformat()}.jsonl"
            path = temporary / relative_path
            path.write_text(text, encoding="utf-8", newline="\n")
            positive = len(observations)
            if positive + day_unknown != day_source_entries:
                raise StablecoinEvidenceError("page coverage does not account for every source row")
            total_source_entries += day_source_entries
            total_positive += positive
            total_unknown += day_unknown
            day_records.append(
                {
                    "bytes": path.stat().st_size,
                    "page_coverage": page_coverages,
                    "positive_observations": positive,
                    "relative_path": relative_path,
                    "sha256": sha256_of_file(path),
                    "snapshot_date": snapshot_date.isoformat(),
                    "source_entries": day_source_entries,
                    "source_raw_sha256s": sorted({receipt.raw_sha256 for receipt in day_receipts}),
                    "source_receipt_sha256s": sorted(
                        {receipt.receipt_sha256 for receipt in day_receipts}
                    ),
                    "unknown": day_unknown,
                    "unknown_by_tags_shape": {
                        shape.value: day_unknown_by_shape.get(shape.value, 0) for shape in TagsShape
                    },
                }
            )

        manifest: dict[str, Any] = {
            "artifact_name": ARTIFACT_NAME,
            "blocker_cleared": False,
            "causal_warning": (
                "response/capture timestamps do not prove when each tag first became public; "
                "do not join these observations into a causal eligibility panel"
            ),
            "cutoff_date": cutoff_date.isoformat(),
            "days": day_records,
            "extraction_policy": EXTRACTION_POLICY,
            "extraction_policy_sha256": EXTRACTION_POLICY_SHA256,
            "profitability_evidence": False,
            "schema_version": SCHEMA_VERSION,
            "source_kind_receipt_counts": dict(sorted(source_kind_counts.items())),
            "status": "INSUFFICIENT_EVIDENCE",
            "totals": {
                "days": len(day_records),
                "positive_observations": total_positive,
                "source_entries": total_source_entries,
                "unknown": total_unknown,
            },
        }
        manifest_bytes = (canonical_dumps(manifest) + "\n").encode("utf-8")
        manifest_path = temporary / MANIFEST_FILENAME
        manifest_path.write_bytes(manifest_bytes)
        manifest_sha = sha256_of_bytes(manifest_bytes)
        (temporary / MANIFEST_SHA256_FILENAME).write_text(
            manifest_sha + "\n", encoding="ascii", newline="\n"
        )
        os.replace(temporary, destination)
        return StablecoinEvidenceBuildResult(
            artifact_dir=str(destination),
            cutoff_date=cutoff_date.isoformat(),
            days=len(day_records),
            source_entries=total_source_entries,
            positive_observations=total_positive,
            unknown=total_unknown,
            manifest_sha256=manifest_sha,
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_FILENAME
    digest_path = root / MANIFEST_SHA256_FILENAME
    if not manifest_path.is_file() or not digest_path.is_file():
        raise StablecoinEvidenceError("artifact manifest or manifest digest is missing")
    if _has_symlink_component(manifest_path) or _has_symlink_component(digest_path):
        raise StablecoinEvidenceError("artifact metadata must not traverse symlinks")
    claimed = digest_path.read_text(encoding="ascii").strip()
    _require_sha256(claimed, field_name="manifest digest")
    manifest_bytes = manifest_path.read_bytes()
    if sha256_of_bytes(manifest_bytes) != claimed:
        raise StablecoinEvidenceError("artifact manifest hash mismatch")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise StablecoinEvidenceError("artifact manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise StablecoinEvidenceError("artifact manifest must be an object")
    if manifest_bytes != (canonical_dumps(manifest) + "\n").encode("utf-8"):
        raise StablecoinEvidenceError("artifact manifest is not canonical JSON")
    if manifest.get("artifact_name") != ARTIFACT_NAME:
        raise StablecoinEvidenceError("unexpected stablecoin artifact name")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise StablecoinEvidenceError("unsupported stablecoin artifact schema")
    if manifest.get("extraction_policy") != EXTRACTION_POLICY:
        raise StablecoinEvidenceError("stablecoin extraction policy differs from v1")
    if manifest.get("extraction_policy_sha256") != EXTRACTION_POLICY_SHA256:
        raise StablecoinEvidenceError("stablecoin extraction policy hash mismatch")
    cutoff = _parse_date(manifest.get("cutoff_date"), field_name="manifest cutoff_date")
    if cutoff > MAXIMUM_CUTOFF:
        raise StablecoinEvidenceError("artifact crosses protected holdout")
    if manifest.get("blocker_cleared") is not False:
        raise StablecoinEvidenceError("v1 artifact must not claim the blocker is cleared")
    if manifest.get("profitability_evidence") is not False:
        raise StablecoinEvidenceError("stablecoin tags are not profitability evidence")
    if manifest.get("status") != "INSUFFICIENT_EVIDENCE":
        raise StablecoinEvidenceError("v1 artifact must remain INSUFFICIENT_EVIDENCE")
    return manifest


def load_stablecoin_observations(
    artifact_dir: str | Path,
) -> LoadedStablecoinEvidence:
    """Rehash and schema-validate every artifact byte before returning a loader."""

    root = Path(artifact_dir)
    if not root.is_dir():
        raise StablecoinEvidenceError(f"artifact directory does not exist: {root}")
    if _has_symlink_component(root):
        raise StablecoinEvidenceError("artifact directory must not traverse symlinks")
    manifest = _load_manifest(root)
    day_records = manifest.get("days")
    if not isinstance(day_records, list):
        raise StablecoinEvidenceError("manifest days must be a list")
    expected_paths: list[str] = []
    total_source_entries = 0
    total_positive = 0
    total_unknown = 0
    source_kind_counts: Counter[str] = Counter()
    prior_date: date | None = None
    for day_record in day_records:
        if not isinstance(day_record, dict):
            raise StablecoinEvidenceError("manifest day records must be objects")
        snapshot = _parse_date(day_record.get("snapshot_date"), field_name="snapshot_date")
        if prior_date is not None and snapshot <= prior_date:
            raise StablecoinEvidenceError("manifest days must be unique and increasing")
        prior_date = snapshot
        expected_relative = f"{OBSERVATIONS_DIRECTORY}/{snapshot.isoformat()}.jsonl"
        if day_record.get("relative_path") != expected_relative:
            raise StablecoinEvidenceError("manifest day path is not canonical")
        expected_paths.append(expected_relative)
        path = root / expected_relative
        if not path.is_file():
            raise StablecoinEvidenceError(f"manifest-bound day file missing: {expected_relative}")
        if _has_symlink_component(path):
            raise StablecoinEvidenceError("artifact day files must not traverse symlinks")
        claimed_sha = _require_sha256(
            day_record.get("sha256"), field_name=f"{expected_relative} sha256"
        )
        if sha256_of_file(path) != claimed_sha:
            raise StablecoinEvidenceError(f"day file hash mismatch: {expected_relative}")
        raw_bytes = path.read_bytes()
        if _strict_int(
            day_record.get("bytes"), field_name=f"{expected_relative} bytes", minimum=0
        ) != len(raw_bytes):
            raise StablecoinEvidenceError(f"day byte count mismatch: {expected_relative}")
        if raw_bytes and not raw_bytes.endswith(b"\n"):
            raise StablecoinEvidenceError(f"day file lacks canonical newline: {expected_relative}")
        rows = 0
        positive_by_page: Counter[int] = Counter()
        for raw_line in raw_bytes.splitlines():
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise StablecoinEvidenceError(
                    f"invalid observation JSON in {expected_relative}"
                ) from exc
            if not isinstance(payload, dict):
                raise StablecoinEvidenceError("observation line must be an object")
            if raw_line != canonical_dumps(payload).encode("utf-8"):
                raise StablecoinEvidenceError("observation line is not canonical JSON")
            observation = StablecoinObservation.from_dict(payload)
            if observation.snapshot_date != snapshot.isoformat():
                raise StablecoinEvidenceError("observation is stored under the wrong day")
            if observation.evidence_state is not StablecoinEvidenceState.STABLECOIN_POSITIVE:
                raise StablecoinEvidenceError(
                    "compact v1 day files may contain only STABLECOIN_POSITIVE rows"
                )
            rows += 1
            positive_by_page[observation.request_page_start] += 1

        page_coverage = day_record.get("page_coverage")
        if not isinstance(page_coverage, list) or not page_coverage:
            raise StablecoinEvidenceError("day page_coverage must be a non-empty list")
        page_starts: list[int] = []
        page_raw_shas: list[str] = []
        page_receipt_shas: list[str] = []
        day_source_entries = 0
        day_positive = 0
        day_unknown = 0
        day_unknown_by_shape: Counter[str] = Counter()
        for page in page_coverage:
            if not isinstance(page, dict):
                raise StablecoinEvidenceError("page coverage records must be objects")
            page_start = _strict_int(
                page.get("page_start"), field_name="coverage page_start", minimum=1
            )
            if page_start in page_starts:
                raise StablecoinEvidenceError("coverage page starts must be unique")
            page_starts.append(page_start)
            corroborating = _strict_int(
                page.get("corroborating_receipts"),
                field_name="coverage corroborating_receipts",
                minimum=1,
            )
            raw_shas = page.get("source_raw_sha256s")
            receipt_shas = page.get("source_receipt_sha256s")
            if not isinstance(raw_shas, list) or raw_shas != sorted(set(raw_shas)):
                raise StablecoinEvidenceError("coverage raw digest list must be sorted and unique")
            if not isinstance(receipt_shas, list) or receipt_shas != sorted(set(receipt_shas)):
                raise StablecoinEvidenceError(
                    "coverage receipt digest list must be sorted and unique"
                )
            for digest in raw_shas:
                page_raw_shas.append(_require_sha256(digest, field_name="coverage raw_sha256"))
            for digest in receipt_shas:
                page_receipt_shas.append(
                    _require_sha256(digest, field_name="coverage receipt_sha256")
                )
            if len(receipt_shas) != corroborating:
                raise StablecoinEvidenceError("coverage receipt count does not match digests")
            _require_sha256(page.get("projection_sha256"), field_name="coverage projection_sha256")
            _require_sha256(
                page.get("unknown_evidence_sha256"),
                field_name="coverage unknown_evidence_sha256",
            )
            for timestamp_field in (
                "source_captured_at_utcs",
                "source_response_at_utcs",
            ):
                timestamps = page.get(timestamp_field)
                if not isinstance(timestamps, list) or timestamps != sorted(set(timestamps)):
                    raise StablecoinEvidenceError(
                        f"coverage {timestamp_field} must be sorted and unique"
                    )
                for timestamp in timestamps:
                    _canonical_utc_timestamp(timestamp, field_name=timestamp_field)
            kinds = page.get("source_kinds")
            kind_counts = page.get("source_kind_receipt_counts")
            if not isinstance(kinds, list) or kinds != sorted(set(kinds)):
                raise StablecoinEvidenceError("coverage source_kinds must be sorted and unique")
            if not isinstance(kind_counts, dict) or sorted(kind_counts) != kinds:
                raise StablecoinEvidenceError("coverage source-kind counts are incomplete")
            if (
                sum(
                    _strict_int(value, field_name="source-kind receipt count", minimum=1)
                    for value in kind_counts.values()
                )
                != corroborating
            ):
                raise StablecoinEvidenceError("coverage source-kind counts do not sum")
            source_kind_counts.update(kind_counts)
            source_entries = _strict_int(
                page.get("source_entries"), field_name="coverage source_entries", minimum=0
            )
            positive = _strict_int(
                page.get("positive_observations"),
                field_name="coverage positive_observations",
                minimum=0,
            )
            unknown = _strict_int(page.get("unknown"), field_name="coverage unknown", minimum=0)
            if source_entries != positive + unknown:
                raise StablecoinEvidenceError("page coverage does not account for source entries")
            if positive_by_page[page_start] != positive:
                raise StablecoinEvidenceError("page positive count differs from day rows")
            by_shape = page.get("unknown_by_tags_shape")
            expected_shape_keys = {shape.value for shape in TagsShape}
            if not isinstance(by_shape, dict) or set(by_shape) != expected_shape_keys:
                raise StablecoinEvidenceError("coverage unknown tags-shape fields are incomplete")
            shape_sum = 0
            for shape in TagsShape:
                count = _strict_int(
                    by_shape.get(shape.value),
                    field_name=f"coverage unknown {shape.value}",
                    minimum=0,
                )
                day_unknown_by_shape[shape.value] += count
                shape_sum += count
            if shape_sum != unknown:
                raise StablecoinEvidenceError("coverage unknown tags-shape counts do not sum")
            day_source_entries += source_entries
            day_positive += positive
            day_unknown += unknown
        if page_starts != sorted(page_starts):
            raise StablecoinEvidenceError("coverage pages must be increasing")
        if set(positive_by_page) - set(page_starts):
            raise StablecoinEvidenceError("positive rows refer to an unmanifested source page")
        if day_positive != rows:
            raise StablecoinEvidenceError("day positive count differs from serialized rows")
        expected_day_counts = {
            "positive_observations": day_positive,
            "source_entries": day_source_entries,
            "unknown": day_unknown,
        }
        for field_name, actual in expected_day_counts.items():
            if (
                _strict_int(
                    day_record.get(field_name),
                    field_name=f"{expected_relative} {field_name}",
                    minimum=0,
                )
                != actual
            ):
                raise StablecoinEvidenceError(f"day {field_name} mismatch: {expected_relative}")
        manifest_shapes = day_record.get("unknown_by_tags_shape")
        expected_shapes = {
            shape.value: day_unknown_by_shape.get(shape.value, 0) for shape in TagsShape
        }
        if manifest_shapes != expected_shapes:
            raise StablecoinEvidenceError("day unknown tags-shape coverage mismatch")
        if day_record.get("source_raw_sha256s") != sorted(set(page_raw_shas)):
            raise StablecoinEvidenceError("day raw digest list differs from page coverage")
        if day_record.get("source_receipt_sha256s") != sorted(set(page_receipt_shas)):
            raise StablecoinEvidenceError("day receipt digest list differs from page coverage")
        total_source_entries += day_source_entries
        total_positive += day_positive
        total_unknown += day_unknown

    days_root = root / OBSERVATIONS_DIRECTORY
    actual_paths = (
        sorted(path.relative_to(root).as_posix() for path in days_root.rglob("*") if path.is_file())
        if days_root.is_dir()
        else []
    )
    if actual_paths != expected_paths:
        raise StablecoinEvidenceError("artifact has missing or unmanifested day files")
    totals = manifest.get("totals")
    if not isinstance(totals, dict):
        raise StablecoinEvidenceError("manifest totals must be an object")
    expected_totals = {
        "days": len(day_records),
        "positive_observations": total_positive,
        "source_entries": total_source_entries,
        "unknown": total_unknown,
    }
    if totals != expected_totals:
        raise StablecoinEvidenceError("manifest totals do not match reloaded observations")
    if manifest.get("source_kind_receipt_counts") != dict(sorted(source_kind_counts.items())):
        raise StablecoinEvidenceError("manifest source-kind counts differ from page coverage")
    return LoadedStablecoinEvidence(root=root, manifest=manifest)


__all__ = [
    "ARTIFACT_NAME",
    "EXTRACTION_POLICY",
    "EXTRACTION_POLICY_SHA256",
    "MANIFEST_FILENAME",
    "MANIFEST_SHA256_FILENAME",
    "MAXIMUM_CUTOFF",
    "LoadedStablecoinEvidence",
    "StablecoinEvidenceBuildResult",
    "StablecoinEvidenceError",
    "StablecoinEvidenceState",
    "StablecoinObservation",
    "TagsShape",
    "build_stablecoin_observations",
    "load_stablecoin_observations",
]
