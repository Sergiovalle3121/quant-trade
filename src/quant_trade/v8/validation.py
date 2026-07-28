"""Range, identity, timezone, interval, gap, duplicate and settlement checks.

Validation is deliberately *separate* from acquisition: the backfill writes
what it saw, and this module judges it. Everything fails closed — an
unverifiable dataset is treated exactly like a bad one, because a strategy
promoted on unverifiable data is indistinguishable from a strategy promoted on
fabricated data.

The settlement checks deserve a note. Perpetual funding intervals are not
constant across a venue's history (8h is common, but venues have moved
symbols to 4h and back). Counting "missing settlements" against a single
assumed interval would invent thousands of phantom gaps, so
:func:`detect_interval_segments` first segments the observed settlement times
by their actual spacing, and completeness is measured *within* each segment.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

#: A gap is only "missing" if it exceeds the expected step by this factor.
#: Venues publish bars a few milliseconds late; a strict equality test would
#: report noise as data loss.
GAP_TOLERANCE = 1.5


def _iso(ms: float) -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000.0))


@dataclass
class IntervalSegment:
    """A contiguous stretch of settlements sharing one funding interval."""

    start_ms: int
    end_ms: int
    interval_hours: float
    settlements: int
    expected_settlements: int
    missing: int

    @property
    def complete(self) -> bool:
        return self.missing == 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_utc"] = _iso(self.start_ms)
        payload["end_utc"] = _iso(self.end_ms)
        payload["complete"] = self.complete
        return payload


#: How many consecutive settlements must share a new spacing before it counts
#: as a venue interval change rather than missed settlements.
INTERVAL_CHANGE_PERSISTENCE = 3
#: Relative tolerance when matching an observed gap to an expected multiple.
INTERVAL_TOLERANCE = 0.05


def detect_interval_segments(
    times_ms: list[int],
    *,
    persistence: int = INTERVAL_CHANGE_PERSISTENCE,
    tolerance: float = INTERVAL_TOLERANCE,
) -> list[IntervalSegment]:
    """Segment settlement times by their observed spacing.

    Two things look alike in the raw stamps and must not be confused:

    * a **missed settlement** — one gap that is an exact multiple of the
      current interval, with the original spacing resuming immediately after;
    * a **venue interval change** (8h → 4h, or back) — a new spacing that
      *persists*.

    So a deviating gap only opens a new segment when the following
    ``persistence`` gaps agree with it; otherwise it is counted as absent
    settlements inside the current segment. Getting this wrong in either
    direction is expensive: read a real 8h→4h change as 50% data loss and a
    good dataset is thrown away; read repeated outages as an interval change
    and missing data silently disappears from the completeness count.
    """
    if persistence < 1:
        raise ValueError("persistence must be >= 1")
    ordered = sorted({int(t) for t in times_ms})
    if len(ordered) < 2:
        return []
    gaps = [b - a for a, b in zip(ordered[:-1], ordered[1:], strict=True)]

    segments: list[IntervalSegment] = []

    def close(start_idx: int, end_idx: int, interval_ms: int, missing: int) -> None:
        settlements = end_idx - start_idx + 1
        segments.append(
            IntervalSegment(
                start_ms=ordered[start_idx],
                end_ms=ordered[end_idx],
                interval_hours=interval_ms / 3_600_000.0,
                settlements=settlements,
                expected_settlements=settlements + missing,
                missing=missing,
            )
        )

    seg_start = 0
    seg_interval = gaps[0]
    seg_missing = 0
    index = 0
    while index < len(gaps):
        gap = gaps[index]
        ratio = gap / seg_interval
        nearest = round(ratio)
        is_multiple = nearest >= 1 and abs(ratio - nearest) <= tolerance
        if is_multiple and nearest == 1:
            index += 1
            continue
        window = gaps[index : index + persistence]
        persistent = len(window) >= persistence and all(
            abs(other - gap) <= tolerance * gap for other in window
        )
        if is_multiple and not persistent:
            seg_missing += nearest - 1  # absent settlements, same cadence
            index += 1
            continue
        # A new cadence that sticks: close the old segment; the transition gap
        # itself belongs to neither, so the next segment starts after it.
        close(seg_start, index, seg_interval, seg_missing)
        seg_start = index + 1
        seg_interval = gap
        seg_missing = 0
        index += 1
    close(seg_start, len(ordered) - 1, seg_interval, seg_missing)
    return segments


@dataclass
class SeriesValidation:
    kind: str
    rows: int = 0
    first_ms: int | None = None
    last_ms: int | None = None
    span_days: float = 0.0
    expected_rows: int = 0
    missing_rows: int = 0
    coverage_ratio: float = 0.0
    duplicate_stamps: int = 0
    conflicting_duplicates: int = 0
    misaligned_stamps: int = 0
    gap_ranges: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_clean"] = self.is_clean
        payload["first_utc"] = _iso(self.first_ms) if self.first_ms is not None else None
        payload["last_utc"] = _iso(self.last_ms) if self.last_ms is not None else None
        return payload


def validate_bar_series(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    since_ms: int,
    until_ms: int,
    interval_minutes: int,
    max_reported_gaps: int = 20,
) -> SeriesValidation:
    """Validate a kline/candle series against its requested window."""
    report = SeriesValidation(kind=kind)
    step = interval_minutes * 60_000
    if not rows:
        report.problems.append(f"{kind}: no rows")
        return report
    stamps = [int(r["start_ms"]) for r in rows]
    report.rows = len(rows)
    report.first_ms, report.last_ms = min(stamps), max(stamps)
    report.span_days = (report.last_ms - report.first_ms) / 86_400_000.0

    seen: dict[int, dict[str, Any]] = {}
    for row in rows:
        stamp = int(row["start_ms"])
        if stamp in seen:
            report.duplicate_stamps += 1
            if seen[stamp] != row:
                report.conflicting_duplicates += 1
        seen[stamp] = row
        if stamp % step != 0:
            report.misaligned_stamps += 1

    if report.conflicting_duplicates:
        report.problems.append(
            f"{kind}: {report.conflicting_duplicates} conflicting duplicate bar(s)"
        )
    if report.misaligned_stamps:
        report.problems.append(
            f"{kind}: {report.misaligned_stamps} bar(s) not aligned to the "
            f"{interval_minutes}m UTC grid"
        )
    if report.first_ms > since_ms + step:
        report.problems.append(
            f"{kind}: series starts {_iso(report.first_ms)}, after the requested "
            f"lower bound {_iso(since_ms)}"
        )
    if report.last_ms < until_ms - 2 * step:
        report.problems.append(
            f"{kind}: series ends {_iso(report.last_ms)}, before the requested "
            f"upper bound {_iso(until_ms)}"
        )

    ordered = sorted(seen)
    report.expected_rows = int((ordered[-1] - ordered[0]) // step) + 1
    report.missing_rows = report.expected_rows - len(ordered)
    report.coverage_ratio = len(ordered) / report.expected_rows if report.expected_rows else 0.0
    for a, b in zip(ordered[:-1], ordered[1:], strict=True):
        if b - a > step * GAP_TOLERANCE and len(report.gap_ranges) < max_reported_gaps:
            report.gap_ranges.append(f"{_iso(a)}..{_iso(b)}")
    if report.missing_rows > 0:
        report.problems.append(f"{kind}: {report.missing_rows} missing bar(s)")
    return report


@dataclass
class SettlementValidation:
    rows: int = 0
    unique_settlements: int = 0
    first_ms: int | None = None
    last_ms: int | None = None
    span_days: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    interval_changes: int = 0
    missing_settlements: int = 0
    conflicting_duplicates: int = 0
    realized_rate_rows: int = 0
    announced_rate_rows: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_clean"] = self.is_clean
        payload["first_utc"] = _iso(self.first_ms) if self.first_ms is not None else None
        payload["last_utc"] = _iso(self.last_ms) if self.last_ms is not None else None
        return payload


def validate_settlements(rows: list[dict[str, Any]]) -> SettlementValidation:
    """Validate settled funding: duplicates, interval changes, completeness."""
    report = SettlementValidation()
    if not rows:
        report.problems.append("funding: no settlements")
        return report
    report.rows = len(rows)
    by_time: dict[int, dict[str, Any]] = {}
    for row in rows:
        stamp = int(row["settled_at_ms"])
        previous = by_time.get(stamp)
        if previous is not None and float(previous["rate"]) != float(row["rate"]):
            report.conflicting_duplicates += 1
        by_time[stamp] = row
        if str(row.get("rate_field", "")) == "realizedRate":
            report.realized_rate_rows += 1
        else:
            report.announced_rate_rows += 1
    report.unique_settlements = len(by_time)
    report.first_ms, report.last_ms = min(by_time), max(by_time)
    report.span_days = (report.last_ms - report.first_ms) / 86_400_000.0
    segments = detect_interval_segments(list(by_time))
    report.segments = [s.to_dict() for s in segments]
    report.interval_changes = max(0, len(segments) - 1)
    report.missing_settlements = sum(s.missing for s in segments)
    if report.conflicting_duplicates:
        report.problems.append(
            f"funding: {report.conflicting_duplicates} settlement(s) reported with "
            "two different rates"
        )
    if report.missing_settlements:
        report.problems.append(
            f"funding: {report.missing_settlements} settlement(s) missing within "
            "the observed interval segments"
        )
    return report


@dataclass
class EvidenceValidation:
    """Whole-directory verdict: series, settlements, receipts and raw bytes."""

    venue: str
    symbol: str
    directory: str
    series: dict[str, dict[str, Any]] = field(default_factory=dict)
    settlements: dict[str, Any] = field(default_factory=dict)
    receipts: int = 0
    receipt_chain_problems: list[str] = field(default_factory=list)
    raw_pages: int = 0
    raw_bytes: int = 0
    corrupt_raw_pages: list[str] = field(default_factory=list)
    live_receipts: int = 0
    test_only_receipts: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems and not self.receipt_chain_problems

    @property
    def provenance(self) -> str:
        if self.receipts == 0:
            return "unverified_legacy"
        if self.live_receipts and not self.test_only_receipts:
            return "real"
        if self.test_only_receipts and not self.live_receipts:
            return "test_only"
        return "mixed"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_clean"] = self.is_clean
        payload["provenance"] = self.provenance
        return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def validate_evidence_dir(
    directory: str | Path,
    *,
    since_ms: int,
    until_ms: int,
    interval_minutes: int,
    venue: str = "",
    symbol: str = "",
) -> EvidenceValidation:
    """Validate one backfilled evidence directory end to end."""
    from quant_trade.evidence.receipts import (
        REAL_SOURCE_KINDS,
        verify_receipt_chain,
    )

    root = Path(directory)
    report = EvidenceValidation(venue=venue, symbol=symbol, directory=str(root))
    if not root.exists():
        report.problems.append(f"evidence directory {root} does not exist")
        return report

    for kind in ("spot", "perp", "mark", "index"):
        rows = _read_jsonl(root / "series" / f"{kind}.jsonl")
        series_report = validate_bar_series(
            rows,
            kind=kind,
            since_ms=since_ms,
            until_ms=until_ms,
            interval_minutes=interval_minutes,
        )
        report.series[kind] = series_report.to_dict()
        report.problems.extend(series_report.problems)

    settlement_report = validate_settlements(_read_jsonl(root / "series" / "funding.jsonl"))
    report.settlements = settlement_report.to_dict()
    report.problems.extend(settlement_report.problems)

    receipts = _read_jsonl(root / "receipts.jsonl")
    report.receipts = len(receipts)
    report.receipt_chain_problems = verify_receipt_chain(receipts)
    for receipt in receipts:
        if str(receipt.get("source_kind", "")) in REAL_SOURCE_KINDS:
            report.live_receipts += 1
        else:
            report.test_only_receipts += 1
        raw_path = root / str(receipt.get("raw_path", ""))
        if not raw_path.exists():
            report.corrupt_raw_pages.append(f"missing: {receipt.get('raw_path')}")
            continue
        if sha256_of_bytes(raw_path.read_bytes()) != str(receipt.get("raw_sha256", "")):
            report.corrupt_raw_pages.append(f"hash mismatch: {receipt.get('raw_path')}")
    if report.corrupt_raw_pages:
        report.problems.append(f"{len(report.corrupt_raw_pages)} raw page(s) missing or altered")

    raw_dir = root / "raw"
    if raw_dir.exists():
        pages = sorted(raw_dir.glob("*.json"))
        report.raw_pages = len(pages)
        report.raw_bytes = sum(p.stat().st_size for p in pages)
    if report.receipts == 0:
        report.problems.append("no ingestion receipts: provenance is unverifiable")
    return report


def sufficiency_report(
    validation: EvidenceValidation,
    *,
    min_days: float,
    min_settlements: int,
) -> dict[str, Any]:
    """Compare a validated directory against the pre-registered gates."""
    settlements = validation.settlements or {}
    unique = int(settlements.get("unique_settlements", 0) or 0)
    span = float(settlements.get("span_days", 0.0) or 0.0)
    shortfalls: list[str] = []
    if unique < min_settlements:
        shortfalls.append(
            f"{unique} unique settlement(s) < required {min_settlements} "
            f"(shortfall {min_settlements - unique})"
        )
    if span < min_days:
        shortfalls.append(
            f"span {span:.2f}d < required {min_days:.0f}d (shortfall {min_days - span:.2f}d)"
        )
    if validation.provenance != "real":
        shortfalls.append(
            f"provenance is {validation.provenance!r}; only receipt-verified live "
            "capture counts as real evidence"
        )
    return {
        "unique_settlements": unique,
        "required_settlements": min_settlements,
        "span_days": span,
        "required_days": min_days,
        "provenance": validation.provenance,
        "sufficient": not shortfalls,
        "shortfalls": shortfalls,
        "evidence_sha256": _dir_fingerprint(validation),
    }


def _dir_fingerprint(validation: EvidenceValidation) -> str:
    from quant_trade.evidence.canonical_json import sha256_of_text

    return sha256_of_text(canonical_dumps(validation.to_dict()))


__all__ = [
    "GAP_TOLERANCE",
    "EvidenceValidation",
    "IntervalSegment",
    "SeriesValidation",
    "SettlementValidation",
    "detect_interval_segments",
    "sufficiency_report",
    "validate_bar_series",
    "validate_evidence_dir",
    "validate_settlements",
]
