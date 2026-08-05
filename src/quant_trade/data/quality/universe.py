"""Universe-dataset validation: everything is recomputed, nothing is trusted.

The collector (`quant_trade.data.universe`) journals what it did; this module
re-derives every claim from the journal and the bytes on disk (Defect E: a
collector that reports its own freshness/coverage is falsifiable, so its
reports are display hints, never gate inputs):

- journal chain re-verified from genesis;
- coverage recomputed from requested range vs day/gap records — a date with
  neither is *unobserved*, the worst state, and is counted separately;
- day files re-hashed against the journal's recorded sha256 (tampering with
  either side breaks the match);
- churn, death candidates and ticker reuse recomputed from the day files;
- the death cross-check against an external inactive list is by symbol and
  declared a heuristic (ids do not map across sources); absent list =>
  NOT_MEASURED, never "no deaths".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.data.quality.crypto import check_ticker_reuse
from quant_trade.data.universe import (
    JOURNAL_FILENAME,
    UniverseCollectorError,
    read_journal,
    verify_journal_chain,
)
from quant_trade.evidence.canonical_json import sha256_of_bytes

STATUS_MEASURED = "MEASURED"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUS_FAILED = "FAILED"

#: A coin whose last appearance is this many days before the dataset end is a
#: death/delisting candidate (ASSUMPTION-class threshold, declared).
DEATH_HORIZON_DAYS = 30
#: Universe size used for annual churn measurement (ASSUMPTION, declared).
CHURN_TOP_N = 500


@dataclass
class UniverseCheck:
    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UniverseQualityReport:
    checks: list[UniverseCheck]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "warnings": list(self.warnings),
        }

    def check(self, name: str) -> UniverseCheck:
        for item in self.checks:
            if item.name == name:
                return item
        raise KeyError(name)


def _iter_day_rows(day_file: Path) -> list[dict[str, Any]]:
    rows = []
    with day_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def validate_universe(
    out_dir: str | Path,
    *,
    requested_start: date,
    requested_end: date,
    inactive_symbols: set[str] | None = None,
    death_horizon_days: int = DEATH_HORIZON_DAYS,
    churn_top_n: int = CHURN_TOP_N,
    verify_all_day_files: bool = True,
) -> UniverseQualityReport:
    """Validate a collected universe directory. Pure read-only recomputation."""
    out = Path(out_dir)
    checks: list[UniverseCheck] = []
    warnings: list[str] = []

    # --- 1) journal integrity, re-walked from genesis -----------------------
    records = read_journal(out / JOURNAL_FILENAME)
    try:
        verify_journal_chain(records)
        chain_ok = True
        chain_reason = ""
    except UniverseCollectorError as exc:
        chain_ok = False
        chain_reason = str(exc)
    header = records[0] if records and records[0].get("type") == "header" else {}
    clock_source = str(header.get("clock_source", ""))
    checks.append(
        UniverseCheck(
            name="journal_chain",
            status=STATUS_MEASURED if chain_ok else STATUS_FAILED,
            details={
                "records": len(records),
                "policy_sha256": header.get("policy_sha256", ""),
                "clock_source": clock_source,
            },
            reason=chain_reason,
        )
    )
    if not chain_ok:
        warnings.append(f"journal chain FAILED: {chain_reason}")
        return UniverseQualityReport(checks=checks, warnings=warnings)
    if clock_source != "system":
        warnings.append(
            f"journal clock_source={clock_source!r}: test-only provenance, "
            "never promotable to research use"
        )

    # --- 2) coverage, recomputed from requested range vs records ------------
    day_records = {r["date"]: r for r in records if r.get("type") == "day"}
    gap_dates = {r["date"] for r in records if r.get("type") == "gap"}
    requested: list[str] = []
    cursor = requested_start
    while cursor <= requested_end:
        requested.append(cursor.isoformat())
        cursor = cursor + timedelta(days=1)
    covered = [d for d in requested if d in day_records]
    gaps_only = [d for d in requested if d in gap_dates and d not in day_records]
    unobserved = [d for d in requested if d not in day_records and d not in gap_dates]
    coverage_fraction = len(covered) / len(requested) if requested else 0.0
    checks.append(
        UniverseCheck(
            name="coverage",
            status=STATUS_MEASURED,
            details={
                "requested_days": len(requested),
                "covered_days": len(covered),
                "gap_days": len(gaps_only),
                "unobserved_days": len(unobserved),
                "coverage_fraction": round(coverage_fraction, 6),
                "first_unobserved": unobserved[:5],
            },
        )
    )
    if gaps_only:
        warnings.append(f"{len(gaps_only)} requested day(s) are recorded gaps")
    if unobserved:
        warnings.append(
            f"{len(unobserved)} requested day(s) are UNOBSERVED (no day record, "
            "no gap record) - the collector never looked; this is worse than a gap"
        )

    # --- 3) day files re-hashed against the journal's claims ----------------
    days_dir = out / "days"
    to_verify = sorted(day_records)
    if not verify_all_day_files and len(to_verify) > 27:
        to_verify = to_verify[:1] + to_verify[1:-1:25] + to_verify[-1:]
    mismatches: list[str] = []
    missing_files: list[str] = []
    for day_iso in to_verify:
        day_file = days_dir / f"{day_iso}.jsonl"
        if not day_file.exists():
            missing_files.append(day_iso)
            continue
        recomputed = sha256_of_bytes(day_file.read_bytes())
        if recomputed != day_records[day_iso].get("day_file_sha256"):
            mismatches.append(day_iso)
    checks.append(
        UniverseCheck(
            name="day_file_integrity",
            status=STATUS_MEASURED if not (mismatches or missing_files) else STATUS_FAILED,
            details={
                "files_verified": len(to_verify) - len(missing_files),
                "sha256_mismatches": mismatches[:10],
                "missing_files": missing_files[:10],
            },
            reason=(
                "day files drifted from journaled hashes"
                if mismatches or missing_files
                else ""
            ),
        )
    )
    if mismatches or missing_files:
        warnings.append(
            f"day-file integrity FAILED: {len(mismatches)} hash mismatch(es), "
            f"{len(missing_files)} missing file(s)"
        )

    # --- 4) streamed per-coin aggregates ------------------------------------
    first_seen: dict[int, str] = {}
    last_seen: dict[int, str] = {}
    symbols_by_id: dict[int, set[str]] = {}
    duplicate_id_days = 0
    negative_values = 0
    row_counts: dict[str, int] = {}
    membership_by_year: dict[int, set[int]] = {}
    year_first_day: dict[int, str] = {}
    for day_iso in sorted(day_records):
        day_file = days_dir / f"{day_iso}.jsonl"
        if not day_file.exists():
            continue
        rows = _iter_day_rows(day_file)
        row_counts[day_iso] = len(rows)
        seen_ids: set[int] = set()
        year = int(day_iso[:4])
        collect_membership = year_first_day.get(year) in (None, day_iso)
        if collect_membership:
            year_first_day[year] = day_iso
            membership_by_year[year] = set()
        for row in rows:
            coin_id = int(row["cmc_id"])
            if coin_id in seen_ids:
                duplicate_id_days += 1
            seen_ids.add(coin_id)
            if row["market_cap_usd"] < 0 or row["volume24h_usd"] < 0:
                negative_values += 1
            if coin_id not in first_seen:
                first_seen[coin_id] = day_iso
            last_seen[coin_id] = day_iso
            symbols_by_id.setdefault(coin_id, set()).add(row["symbol"])
            if collect_membership:
                rank = row.get("cmc_rank")
                if rank is not None and int(rank) <= churn_top_n:
                    membership_by_year[year].add(coin_id)
    checks.append(
        UniverseCheck(
            name="row_sanity",
            status=STATUS_MEASURED,
            details={
                "distinct_coins": len(first_seen),
                "duplicate_id_day_pairs": duplicate_id_days,
                "negative_value_rows": negative_values,
                "min_rows_per_day": min(row_counts.values()) if row_counts else 0,
                "max_rows_per_day": max(row_counts.values()) if row_counts else 0,
            },
        )
    )
    if duplicate_id_days:
        warnings.append(f"{duplicate_id_days} duplicate (day, coin_id) pair(s)")
    if negative_values:
        warnings.append(f"{negative_values} row(s) with negative mcap/volume")

    # --- 5) annual churn of the top-N universe ------------------------------
    years = sorted(membership_by_year)
    churn: dict[str, dict[str, int]] = {}
    for previous, current in zip(years, years[1:], strict=False):
        entered = len(membership_by_year[current] - membership_by_year[previous])
        exited = len(membership_by_year[previous] - membership_by_year[current])
        churn[str(current)] = {"entered": entered, "exited": exited}
    total_exits = sum(item["exited"] for item in churn.values())
    checks.append(
        UniverseCheck(
            name="churn",
            status=STATUS_MEASURED if churn else STATUS_NOT_MEASURED,
            details={"top_n": churn_top_n, "by_year": churn},
            reason="" if churn else "fewer than two calendar years covered",
        )
    )
    if churn and total_exits == 0:
        warnings.append(
            f"top-{churn_top_n} universe shows ZERO exits across years - "
            "this is the survivorship alarm (dead coins leaked out of the panel)"
        )

    # --- 6) death candidates + external corroboration -----------------------
    end_iso = requested_end.isoformat()
    horizon = (requested_end - timedelta(days=death_horizon_days)).isoformat()
    dead_candidates = {
        coin_id for coin_id, last in last_seen.items() if last <= horizon
    }
    check_details: dict[str, Any] = {
        "death_horizon_days": death_horizon_days,
        "dead_candidates": len(dead_candidates),
        "dataset_end": end_iso,
    }
    if inactive_symbols is None:
        checks.append(
            UniverseCheck(
                name="death_cross_check",
                status=STATUS_NOT_MEASURED,
                details=check_details,
                reason="no external inactive list provided",
            )
        )
        warnings.append(
            "death_cross_check NOT_MEASURED (no external inactive list) - "
            f"{len(dead_candidates)} death candidate(s) stand uncorroborated"
        )
    else:
        inactive_upper = {s.upper() for s in inactive_symbols}
        corroborated = sum(
            1
            for coin_id in dead_candidates
            if symbols_by_id.get(coin_id, set()) & inactive_upper
        )
        fraction = corroborated / len(dead_candidates) if dead_candidates else None
        check_details.update(
            {
                "corroborated_by_symbol": corroborated,
                "corroborated_fraction": fraction,
                "method": "symbol-match heuristic (ids do not map across sources)",
            }
        )
        checks.append(
            UniverseCheck(
                name="death_cross_check",
                status=STATUS_MEASURED,
                details=check_details,
            )
        )

    # --- 7) ticker reuse (existing detector, tiny frame) --------------------
    pairs = [
        {"coin_id": coin_id, "symbol": symbol}
        for coin_id, symbols in symbols_by_id.items()
        for symbol in symbols
    ]
    reuse = check_ticker_reuse(pd.DataFrame(pairs) if pairs else None)
    checks.append(
        UniverseCheck(
            name="ticker_reuse",
            status=reuse.status,
            details={
                "finding_count": reuse.finding_count,
                "affected": reuse.affected_symbols,
            },
            reason=reuse.reason,
        )
    )
    if reuse.finding_count:
        warnings.append(
            f"ticker_reuse: {reuse.finding_count} identity weld(s) - "
            "coin identity must be cmc_id, never the ticker"
        )

    return UniverseQualityReport(checks=checks, warnings=warnings)


__all__ = [
    "CHURN_TOP_N",
    "DEATH_HORIZON_DAYS",
    "UniverseCheck",
    "UniverseQualityReport",
    "validate_universe",
]
