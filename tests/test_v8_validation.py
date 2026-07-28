"""V8 validation: gaps, duplicates, funding-interval changes, sufficiency."""

from __future__ import annotations

from pathlib import Path

import pytest
from v8_venue_fakes import FakeVenue, no_sleep

from quant_trade.v8.backfill import BackfillRequest, run_backfill
from quant_trade.v8.validation import (
    detect_interval_segments,
    sufficiency_report,
    validate_bar_series,
    validate_evidence_dir,
    validate_settlements,
)

HOUR = 3_600_000
START = 1_700_000_000_000 - (1_700_000_000_000 % HOUR)


def _bars(count: int, *, step: int = HOUR, start: int = START) -> list[dict[str, float]]:
    return [
        {"start_ms": start + i * step, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}
        for i in range(count)
    ]


# --- bar series ---------------------------------------------------------------


def test_clean_series_is_clean() -> None:
    rows = _bars(25)
    report = validate_bar_series(
        rows, kind="spot", since_ms=START, until_ms=START + 24 * HOUR, interval_minutes=60
    )
    assert report.is_clean
    assert report.rows == 25
    assert report.missing_rows == 0
    assert report.coverage_ratio == pytest.approx(1.0)


def test_missing_bars_are_reported_with_their_gap_range() -> None:
    rows = _bars(25)
    del rows[10:13]
    report = validate_bar_series(
        rows, kind="perp", since_ms=START, until_ms=START + 24 * HOUR, interval_minutes=60
    )
    assert not report.is_clean
    assert report.missing_rows == 3
    assert report.gap_ranges
    assert any("missing bar" in p for p in report.problems)


def test_misaligned_stamps_are_rejected() -> None:
    rows = _bars(5)
    rows[2]["start_ms"] += 137  # not on the UTC hour grid
    report = validate_bar_series(
        rows, kind="mark", since_ms=START, until_ms=START + 4 * HOUR, interval_minutes=60
    )
    assert report.misaligned_stamps == 1
    assert any("not aligned" in p for p in report.problems)


def test_conflicting_duplicate_bars_are_flagged() -> None:
    rows = _bars(3)
    duplicate = dict(rows[1])
    duplicate["close"] = 1.9
    rows.append(duplicate)
    report = validate_bar_series(
        rows, kind="index", since_ms=START, until_ms=START + 2 * HOUR, interval_minutes=60
    )
    assert report.conflicting_duplicates == 1
    assert any("conflicting duplicate" in p for p in report.problems)


def test_series_short_of_the_requested_window_is_reported() -> None:
    rows = _bars(5)
    report = validate_bar_series(
        rows,
        kind="spot",
        since_ms=START - 10 * HOUR,
        until_ms=START + 100 * HOUR,
        interval_minutes=60,
    )
    assert any("after the requested lower bound" in p for p in report.problems)
    assert any("before the requested upper bound" in p for p in report.problems)


# --- funding interval segmentation ---------------------------------------------


def test_constant_interval_is_one_segment() -> None:
    stamps = [START + i * 8 * HOUR for i in range(10)]
    segments = detect_interval_segments(stamps)
    assert len(segments) == 1
    assert segments[0].interval_hours == pytest.approx(8.0)
    assert segments[0].missing == 0


def test_a_funding_interval_change_becomes_two_segments() -> None:
    """8h then 4h: a real venue change must not be read as thousands of gaps."""
    eight = [START + i * 8 * HOUR for i in range(6)]
    pivot = eight[-1]
    four = [pivot + i * 4 * HOUR for i in range(1, 7)]
    segments = detect_interval_segments(eight + four)
    assert len(segments) == 2
    assert segments[0].interval_hours == pytest.approx(8.0)
    assert segments[1].interval_hours == pytest.approx(4.0)
    assert sum(s.missing for s in segments) == 0


def test_a_single_missed_settlement_stays_in_one_segment() -> None:
    stamps = [START + i * 8 * HOUR for i in range(10)]
    del stamps[4]  # one settlement absent: a 16h gap, an exact multiple of 8h
    segments = detect_interval_segments(stamps)
    assert len(segments) == 1
    assert segments[0].missing == 1


def test_settlement_validation_counts_realized_versus_announced() -> None:
    rows = [
        {
            "settled_at_ms": START + i * 8 * HOUR,
            "rate": 0.0001,
            "rate_field": "realizedRate" if i % 2 == 0 else "fundingRate",
        }
        for i in range(6)
    ]
    report = validate_settlements(rows)
    assert report.unique_settlements == 6
    assert report.realized_rate_rows == 3
    assert report.announced_rate_rows == 3
    assert report.is_clean


def test_settlement_validation_flags_contradictory_rates() -> None:
    rows = [
        {"settled_at_ms": START, "rate": 0.0001, "rate_field": "realizedRate"},
        {"settled_at_ms": START, "rate": 0.0009, "rate_field": "realizedRate"},
        {"settled_at_ms": START + 8 * HOUR, "rate": 0.0001, "rate_field": "realizedRate"},
    ]
    report = validate_settlements(rows)
    assert report.conflicting_duplicates == 1
    assert not report.is_clean


def test_empty_settlements_are_a_problem_not_a_pass() -> None:
    report = validate_settlements([])
    assert not report.is_clean
    assert "no settlements" in report.problems[0]


# --- whole-directory validation -------------------------------------------------


def _backfill(tmp_path: Path, venue: str, days: int, **kw):
    until = START + days * 24 * HOUR
    fake = FakeVenue(venue=venue, start_ms=START, end_ms=until, **kw)
    request = BackfillRequest(venue=venue, symbol="BTC", since_ms=START, until_ms=until)
    result = run_backfill(
        request,
        tmp_path,
        fetcher=fake.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
        captured_at_utc="2026-07-28T00:00:00Z",
    )
    return result, until


def test_backfilled_directory_validates_clean(tmp_path: Path) -> None:
    result, until = _backfill(tmp_path, "okx", 20)
    report = validate_evidence_dir(
        result.evidence_dir,
        since_ms=START,
        until_ms=until,
        interval_minutes=60,
        venue="okx",
        symbol="BTC",
    )
    assert report.is_clean, report.problems
    assert report.receipts > 0
    assert report.raw_pages > 0
    assert report.receipt_chain_problems == []


def test_validation_detects_a_funding_interval_change_in_real_evidence(
    tmp_path: Path,
) -> None:
    result, until = _backfill(tmp_path, "bybit", 20, interval_change_at_ms=START + 10 * 24 * HOUR)
    report = validate_evidence_dir(
        result.evidence_dir,
        since_ms=START,
        until_ms=until,
        interval_minutes=60,
        venue="bybit",
        symbol="BTC",
    )
    assert report.settlements["interval_changes"] >= 1
    intervals = {round(s["interval_hours"], 2) for s in report.settlements["segments"]}
    assert {8.0, 4.0} <= intervals


def test_a_tampered_raw_page_invalidates_the_directory(tmp_path: Path) -> None:
    result, until = _backfill(tmp_path, "bybit", 3)
    victim = sorted(Path(result.evidence_dir).glob("raw/*.json"))[0]
    victim.write_bytes(victim.read_bytes() + b" ")
    report = validate_evidence_dir(
        result.evidence_dir, since_ms=START, until_ms=until, interval_minutes=60
    )
    assert not report.is_clean
    assert report.corrupt_raw_pages
    assert any("altered" in p for p in report.problems)


def test_a_broken_receipt_chain_is_detected(tmp_path: Path) -> None:
    result, until = _backfill(tmp_path, "bybit", 3)
    receipts = Path(result.evidence_dir) / "receipts.jsonl"
    lines = receipts.read_text().splitlines()
    receipts.write_text("\n".join(lines[1:]) + "\n")  # drop the chain's first link
    report = validate_evidence_dir(
        result.evidence_dir, since_ms=START, until_ms=until, interval_minutes=60
    )
    assert report.receipt_chain_problems
    assert not report.is_clean


def test_recorded_evidence_never_resolves_to_real(tmp_path: Path) -> None:
    result, until = _backfill(tmp_path, "okx", 3)
    report = validate_evidence_dir(
        result.evidence_dir, since_ms=START, until_ms=until, interval_minutes=60
    )
    assert report.provenance == "test_only"


# --- sufficiency ----------------------------------------------------------------


def test_sufficiency_reports_the_exact_shortfall(tmp_path: Path) -> None:
    result, until = _backfill(tmp_path, "bybit", 30)
    validation = validate_evidence_dir(
        result.evidence_dir, since_ms=START, until_ms=until, interval_minutes=60
    )
    report = sufficiency_report(validation, min_days=730.0, min_settlements=1000)
    assert not report["sufficient"]
    assert report["unique_settlements"] == 90
    assert "shortfall 910" in report["shortfalls"][0]
    assert any("only receipt-verified live capture" in s for s in report["shortfalls"])


def test_sufficiency_passes_only_with_real_provenance_and_full_history(
    tmp_path: Path,
) -> None:
    result, until = _backfill(tmp_path, "bybit", 400)
    validation = validate_evidence_dir(
        result.evidence_dir, since_ms=START, until_ms=until, interval_minutes=60
    )
    # 400 days at 8h = 1200 settlements: the count gate clears...
    assert validation.settlements["unique_settlements"] >= 1000
    report = sufficiency_report(validation, min_days=730.0, min_settlements=1000)
    # ...but span and provenance still fail closed.
    assert not report["sufficient"]
    assert any("span" in s for s in report["shortfalls"])
    assert any("provenance" in s for s in report["shortfalls"])
