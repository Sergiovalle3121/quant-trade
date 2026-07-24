"""Unified opportunity board: ONE unit, verified lineage, cash always present.

Every eligible row is scored in the SAME unit — annualized net return on
committed capital — or it is not ranked at all (V6-K): Sharpe-per-period is
not USD/hour is not an annual yield, and a board that compares them can crown
an absurd champion. Rows that cannot express a common-unit return are tracked
with the exact reason, never ranked.

The board also refuses unverified inputs (V6-L): both source artifacts must
arrive with lineage (artifact kind, path, byte SHA, evaluated_at) and a
recomputed rows-hash that matches the hash embedded at scan time. A
hand-edited JSON, a missing lineage, or mismatched evaluation clocks reject
loudly instead of ranking silently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.models import SAFETY_POSTURE
from quant_trade.evidence.canonical_json import atomic_write_json
from quant_trade.evidence.receipts import normalized_rows_sha256

COMMON_UNIT = "annualized_net_return_on_capital"
HOURS_PER_YEAR = 8766.0


@dataclass
class BoardEntry:
    entry_id: str
    kind: str  # "trading" | "mining" | "cash"
    status: str
    eligible: bool
    score: float | None = None  # ALWAYS the common unit when present
    score_unit: str = COMMON_UNIT
    reasons: list[str] = field(default_factory=list)
    test_only: bool = False
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lineage_for_rows(
    rows: list[dict[str, Any]],
    *,
    artifact: str,
    path: str,
    evaluated_at_utc: str,
) -> dict[str, Any]:
    """Build a verifiable lineage record for a row set (the ONLY legit path)."""
    return {
        "artifact": artifact,
        "path": path,
        "evaluated_at_utc": evaluated_at_utc,
        "rows_sha256": normalized_rows_sha256(rows),
    }


def _verify_lineage(
    name: str,
    rows: list[dict[str, Any]],
    lineage: dict[str, Any] | None,
    expected_artifact: str,
) -> None:
    if not lineage:
        raise ValueError(
            f"{name} rows arrived without lineage; the board only ranks rows "
            "traceable to a scan artifact (artifact, path, evaluated_at, rows hash)"
        )
    if str(lineage.get("artifact", "")) != expected_artifact:
        raise ValueError(
            f"{name} lineage names artifact {lineage.get('artifact')!r}; "
            f"expected {expected_artifact!r}"
        )
    recomputed = normalized_rows_sha256(rows)
    if recomputed != str(lineage.get("rows_sha256", "")):
        raise ValueError(
            f"{name} rows do not hash to the lineage rows_sha256 — the artifact "
            "was edited after the scan; refusing to rank tampered inputs"
        )


def _annualized_trading_score(row: dict[str, Any]) -> tuple[float | None, str]:
    metrics = row.get("metrics") or {}
    total = metrics.get("total_return")
    span_days = metrics.get("span_days")
    if total is None or not span_days:
        return None, "no common-unit return (total_return + span_days) available"
    if float(span_days) < 1.0:
        return None, f"span {span_days} too short to annualize honestly"
    annualized = (1.0 + float(total)) ** (365.25 / float(span_days)) - 1.0
    return annualized, ""


def _annualized_mining_score(cell: dict[str, Any]) -> tuple[float | None, str]:
    econ = cell.get("conditional_economics") or {}
    margin = econ.get("margin_per_hour_usd")
    all_in = econ.get("all_in_cost_per_hour_usd")
    if margin is None or not all_in:
        return None, (
            "no common-unit return (margin_per_hour_usd + all_in_cost_per_hour_usd)"
        )
    return float(margin) / float(all_in) * HOURS_PER_YEAR, ""


def build_opportunity_board(
    *,
    trading_rows: list[dict[str, Any]],
    mining_cells: list[dict[str, Any]],
    cash_yield_annual: float,
    evaluated_at_utc: str,
    trading_lineage: dict[str, Any] | None = None,
    mining_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _verify_lineage(
        "trading", trading_rows, trading_lineage, "TRADING_OPPORTUNITY_LEADERBOARD"
    )
    _verify_lineage("mining", mining_cells, mining_lineage, "MINING_RENTAL_MATRIX")
    clocks = {
        str(trading_lineage.get("evaluated_at_utc", "")),  # type: ignore[union-attr]
        str(mining_lineage.get("evaluated_at_utc", "")),  # type: ignore[union-attr]
    }
    if len(clocks) != 1:
        raise ValueError(
            f"scan artifacts carry different evaluated_at_utc clocks {sorted(clocks)}; "
            "re-scan both at one evaluation time or normalize explicitly"
        )

    entries: list[BoardEntry] = [
        BoardEntry(
            entry_id="cash_usd",
            kind="cash",
            status="ELIGIBLE_BASELINE",
            eligible=True,
            score=cash_yield_annual,
            reasons=["baseline every opportunity must beat (annual yield, same unit)"],
        )
    ]
    for row in trading_rows:
        eligible = row.get("status") == "PAPER_CANDIDATE" and (
            row.get("data_source") == "real"
        )
        score, unit_problem = _annualized_trading_score(row)
        reasons = list(row.get("reasons") or [])
        if eligible and score is None:
            eligible = False
            reasons.insert(0, unit_problem)
        entries.append(
            BoardEntry(
                entry_id=f"trading:{row.get('hypothesis_id', '?')}",
                kind="trading",
                status=str(row.get("status", "")),
                eligible=eligible,
                score=score if eligible else None,
                reasons=reasons,
            )
        )
    for cell in mining_cells:
        status = str(cell.get("status", ""))
        test_only = bool(cell.get("test_only"))
        eligible = status == "ECONOMIC_CANDIDATE_PAPER_ONLY" and not test_only
        score, unit_problem = _annualized_mining_score(cell)
        reasons = list(cell.get("reasons") or [])
        if eligible and score is None:
            eligible = False
            reasons.insert(0, unit_problem)
        entries.append(
            BoardEntry(
                entry_id=f"mining:{cell.get('identity', '?')}",
                kind="mining",
                status=status,
                eligible=eligible,
                score=score if eligible else None,
                reasons=reasons,
                test_only=test_only,
            )
        )

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
        "artifact": "UNIFIED_ECONOMIC_BOARD",
        "schema_version": 2,
        "evaluated_at_utc": evaluated_at_utc,
        "score_unit": COMMON_UNIT,
        "cash_yield_annual": cash_yield_annual,
        "entries": [e.to_dict() for e in ordered],
        "champion": champion.to_dict(),
        "challengers": [e.to_dict() for e in challengers],
        "lineage": {"trading": trading_lineage, "mining": mining_lineage},
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
        "notes": [
            "every ranked score is annualized net return on committed capital",
            "rows without a common-unit return are tracked, never ranked",
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
        "schema_version": 2,
        "evaluated_at_utc": board.get("evaluated_at_utc", ""),
        "total_capital_usd": total_capital_usd,
        "paper_only": True,
        "allocations": lines,
        "champion": board.get("champion"),
        "challengers_tracked": len(board.get("challengers", [])),
        "lineage": board.get("lineage"),
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
        "notes": [
            "this is a PAPER allocation: no orders, no transfers, no spend",
            "capital sums exactly to total; cash holds the residual",
        ],
    }


def write_board(path: str | Path, board: dict[str, Any]) -> Path:
    return atomic_write_json(path, board)
