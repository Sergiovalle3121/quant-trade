"""Unified opportunity board and paper capital allocator.

The board merges the trading leaderboard, the mining rental matrix, and cash
into one ranked view. Eligibility is strict:

- trading: only a ``PAPER_CANDIDATE`` verdict on real data;
- mining: only a non-TEST_ONLY ``ECONOMIC_CANDIDATE_PAPER_ONLY`` cell
  (a policy block or missing evidence can never be out-ranked by economics);
- cash: always present — every opportunity must beat it or it wins.

The allocator distributes PAPER capital only. Ineligible rows get exactly
zero; eligible non-cash rows are equal-weighted up to a per-opportunity cap;
cash absorbs the remainder so the allocation always sums to the total. The
champion/challenger scoreboard shadows the ranking: the champion is today's
best eligible row (cash until something beats it), challengers are tracked
with the exact reason they are not eligible yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.models import SAFETY_POSTURE
from quant_trade.evidence.canonical_json import atomic_write_json


@dataclass
class BoardEntry:
    entry_id: str
    kind: str  # "trading" | "mining" | "cash"
    status: str
    eligible: bool
    score: float | None = None  # ranking score among eligible rows only
    expected_annual_return: float | None = None
    reasons: list[str] = field(default_factory=list)
    test_only: bool = False
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_opportunity_board(
    *,
    trading_rows: list[dict[str, Any]],
    mining_cells: list[dict[str, Any]],
    cash_yield_annual: float,
    evaluated_at_utc: str,
) -> dict[str, Any]:
    entries: list[BoardEntry] = [
        BoardEntry(
            entry_id="cash_usd",
            kind="cash",
            status="ELIGIBLE_BASELINE",
            eligible=True,
            score=cash_yield_annual,
            expected_annual_return=cash_yield_annual,
            reasons=["baseline every opportunity must beat"],
        )
    ]
    for row in trading_rows:
        eligible = row.get("status") == "PAPER_CANDIDATE" and (
            row.get("data_source") == "real"
        )
        sharpe = (row.get("metrics") or {}).get("sharpe_per_period")
        entries.append(
            BoardEntry(
                entry_id=f"trading:{row.get('hypothesis_id', '?')}",
                kind="trading",
                status=str(row.get("status", "")),
                eligible=eligible,
                score=float(sharpe) if eligible and sharpe is not None else None,
                reasons=list(row.get("reasons") or []),
            )
        )
    for cell in mining_cells:
        status = str(cell.get("status", ""))
        test_only = bool(cell.get("test_only"))
        eligible = status == "ECONOMIC_CANDIDATE_PAPER_ONLY" and not test_only
        econ = cell.get("conditional_economics") or {}
        margin = econ.get("margin_per_hour_usd")
        entries.append(
            BoardEntry(
                entry_id=f"mining:{cell.get('identity', '?')}",
                kind="mining",
                status=status,
                eligible=eligible,
                score=float(margin) if eligible and margin is not None else None,
                reasons=list(cell.get("reasons") or []),
                test_only=test_only,
            )
        )

    # rank eligible rows only; deterministic tie-break favours cash, then id
    eligible_rows = [e for e in entries if e.eligible]
    eligible_rows.sort(
        key=lambda e: (
            -(e.score if e.score is not None else 0.0),
            0 if e.kind == "cash" else 1,
            e.entry_id,
        )
    )
    for i, entry in enumerate(eligible_rows, start=1):
        entry.rank = i

    champion = eligible_rows[0]
    challengers = [e for e in entries if e is not champion]
    ordered = eligible_rows + [e for e in entries if not e.eligible]
    return {
        "artifact": "UNIFIED_OPPORTUNITY_BOARD",
        "schema_version": 1,
        "evaluated_at_utc": evaluated_at_utc,
        "cash_yield_annual": cash_yield_annual,
        "entries": [e.to_dict() for e in ordered],
        "champion": champion.to_dict(),
        "challengers": [e.to_dict() for e in challengers],
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
        "notes": [
            "cash is always on the board; beating it is the bar",
            "blocked/missing/NOT_RUN rows are tracked, never ranked",
            "a rank is a research output, not an authorization",
        ],
    }


def allocate_paper_capital(
    board: dict[str, Any],
    total_capital_usd: float,
    *,
    max_fraction_per_opportunity: float = 0.25,
) -> dict[str, Any]:
    """PAPER capital only. Ineligible rows get zero; cash absorbs the rest."""
    if total_capital_usd <= 0:
        raise ValueError("total_capital_usd must be > 0")
    if not 0 < max_fraction_per_opportunity <= 1:
        raise ValueError("max_fraction_per_opportunity must be in (0, 1]")
    entries = board.get("entries", [])
    candidates = [
        e for e in entries if e.get("eligible") and e.get("kind") != "cash"
    ]
    per_candidate = min(
        max_fraction_per_opportunity,
        (1.0 / len(candidates)) if candidates else 0.0,
    )
    lines: list[dict[str, Any]] = []
    allocated = 0.0
    for e in candidates:
        fraction = per_candidate
        capital = total_capital_usd * fraction
        allocated += capital
        lines.append(
            {
                "entry_id": e["entry_id"],
                "kind": e["kind"],
                "status": e["status"],
                "fraction": fraction,
                "capital_usd": capital,
                "rationale": "eligible candidate; equal weight under per-opportunity cap",
            }
        )
    for e in entries:
        if e.get("kind") != "cash" and not e.get("eligible"):
            lines.append(
                {
                    "entry_id": e["entry_id"],
                    "kind": e["kind"],
                    "status": e["status"],
                    "fraction": 0.0,
                    "capital_usd": 0.0,
                    "rationale": (e.get("reasons") or ["not eligible"])[0],
                }
            )
    cash_capital = total_capital_usd - allocated
    lines.insert(
        0,
        {
            "entry_id": "cash_usd",
            "kind": "cash",
            "status": "ELIGIBLE_BASELINE",
            "fraction": cash_capital / total_capital_usd,
            "capital_usd": cash_capital,
            "rationale": "residual paper capital; cash absorbs whatever is unallocated",
        },
    )
    return {
        "artifact": "PAPER_CAPITAL_ALLOCATION",
        "schema_version": 1,
        "evaluated_at_utc": board.get("evaluated_at_utc", ""),
        "total_capital_usd": total_capital_usd,
        "paper_only": True,
        "allocations": lines,
        "champion": board.get("champion"),
        "challengers_tracked": len(board.get("challengers", [])),
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
        "notes": [
            "this is a PAPER allocation: no orders, no transfers, no spend",
            "capital sums exactly to total; cash holds the residual",
        ],
    }


def write_board(path: str | Path, board: dict[str, Any]) -> Path:
    return atomic_write_json(path, board)
