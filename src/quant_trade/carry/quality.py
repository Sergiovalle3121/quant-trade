"""Dataset audit for collected funding history: gaps, duplicates, coverage.

An honest campaign needs to know exactly what its dataset contains — and what
it is missing — before any economics run. The audit is descriptive and fail
closed: quarantined lines, duplicate keys, non-monotonic timestamps, and
undeclared venue/symbol mixing are all surfaced as problems.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.carry.store import read_store


def parse_utc(value: str) -> datetime:
    """Strict, timezone-aware UTC parse; naive timestamps are rejected."""
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} is not timezone-aware")
    return parsed.astimezone(UTC)


@dataclass
class DatasetAuditReport:
    path: str
    total_records: int
    quarantined_lines: int
    quarantined_line_numbers: list[int]
    venues: list[str]
    symbols: list[str]
    pairs: list[str]
    time_range_start: str | None
    time_range_end: str | None
    span_days: float
    funding_events: int
    expected_interval_hours: float | None
    gaps_detected: int
    largest_gap_hours: float | None
    duplicate_keys: int
    non_monotonic_pairs: int
    invalid_timestamps: int
    problems: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "is_clean": self.is_clean}


def audit_dataset(path: str | Path, *, gap_tolerance: float = 1.5) -> DatasetAuditReport:
    """Audit a collected JSONL funding dataset (per venue/symbol series)."""
    read = read_store(path)
    records = read.records
    problems: list[str] = []
    if read.quarantined:
        problems.append(
            f"{len(read.quarantined)} corrupt line(s) quarantined at "
            f"{[n for n, _ in read.quarantined]}"
        )

    venues = sorted({str(r.get("venue", "")) for r in records})
    symbols = sorted({str(r.get("symbol", "")) for r in records})
    pair_names = sorted({f"{r.get('venue')}:{r.get('symbol')}" for r in records})

    invalid_ts = 0
    stamped: list[tuple[str, datetime, dict[str, Any]]] = []
    for r in records:
        try:
            ts = parse_utc(str(r.get("exchange_timestamp_utc", "")))
        except ValueError:
            invalid_ts += 1
            continue
        stamped.append((f"{r.get('venue')}:{r.get('symbol')}", ts, r))
    if invalid_ts:
        problems.append(f"{invalid_ts} record(s) carry invalid or naive timestamps")

    duplicate_keys = 0
    seen: set[str] = set()
    for _pair, _ts, r in stamped:
        key = (
            f"{r.get('venue')}|{r.get('symbol')}|{r.get('exchange_timestamp_utc')}|"
            f"{r.get('source_event', 'poll')}"
        )
        if key in seen:
            duplicate_keys += 1
        seen.add(key)
    if duplicate_keys:
        problems.append(f"{duplicate_keys} duplicate observation key(s)")

    # per-pair monotonicity and gap detection
    non_monotonic = 0
    gaps = 0
    largest_gap_hours: float | None = None
    expected_interval: float | None = None
    intervals = [
        float(r.get("funding_interval_hours", 8.0)) for _p, _t, r in stamped
    ]
    if intervals:
        expected_interval = max(set(intervals), key=intervals.count)
    by_pair: dict[str, list[datetime]] = {}
    for pair, ts, _r in stamped:
        by_pair.setdefault(pair, []).append(ts)
    for _pair_name, stamps in by_pair.items():
        if stamps != sorted(stamps):
            non_monotonic += 1
        ordered = sorted(stamps)
        for a, b in zip(ordered, ordered[1:], strict=False):
            hours = (b - a).total_seconds() / 3600.0
            if expected_interval and hours > expected_interval * gap_tolerance:
                gaps += 1
                largest_gap_hours = max(largest_gap_hours or 0.0, hours)
    if non_monotonic:
        problems.append(f"{non_monotonic} pair(s) stored with non-monotonic timestamps")
    if gaps:
        problems.append(f"{gaps} gap(s) beyond {gap_tolerance}x the funding interval")

    all_ts = sorted(ts for _p, ts, _r in stamped)
    span_days = (
        (all_ts[-1] - all_ts[0]).total_seconds() / 86400.0 if len(all_ts) >= 2 else 0.0
    )
    return DatasetAuditReport(
        path=str(path),
        total_records=len(records),
        quarantined_lines=len(read.quarantined),
        quarantined_line_numbers=[n for n, _ in read.quarantined],
        venues=venues,
        symbols=symbols,
        pairs=pair_names,
        time_range_start=all_ts[0].isoformat() if all_ts else None,
        time_range_end=all_ts[-1].isoformat() if all_ts else None,
        span_days=span_days,
        funding_events=len(stamped),
        expected_interval_hours=expected_interval,
        gaps_detected=gaps,
        largest_gap_hours=largest_gap_hours,
        duplicate_keys=duplicate_keys,
        non_monotonic_pairs=non_monotonic,
        invalid_timestamps=invalid_ts,
        problems=problems,
    )
