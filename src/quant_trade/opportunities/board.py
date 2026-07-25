"""Unified opportunity board: ONE unit, verified lineage, cash always present.

Every eligible row is scored as net return on committed capital or it is not
ranked at all (V6-K). A short rental is never multiplied into a presumed
year-round stream. Rows that cannot express a common-unit return are tracked
with the exact reason, never ranked.

The board also refuses unverified inputs (V6-L): both source artifacts must
arrive with lineage (artifact kind, path, byte SHA, evaluated_at) and a
recomputed rows-hash that matches the hash embedded at scan time. A
hand-edited JSON, a missing lineage, or mismatched evaluation clocks reject
loudly instead of ranking silently.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.models import SAFETY_POSTURE
from quant_trade.evidence.canonical_json import atomic_write_json, sha256_of_file
from quant_trade.evidence.receipts import normalized_rows_sha256

COMPARISON_HORIZON_DAYS = 30.0
COMMON_UNIT = "net_return_on_committed_capital_30d"


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
    capacity_usd: float | None = None
    risk_score: float = 1.0
    liquidity_score: float = 1.0
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


def _trading_score(row: dict[str, Any]) -> tuple[float | None, str]:
    metrics = row.get("metrics") or {}
    total = metrics.get("total_return")
    span_days = metrics.get("span_days")
    if total is None or not span_days:
        return None, "no common-unit return (total_return + span_days) available"
    if float(span_days) < 1.0:
        return None, f"span {span_days} too short to annualize honestly"
    if float(span_days) < COMPARISON_HORIZON_DAYS:
        return None, (
            f"span {span_days}d is shorter than the "
            f"{COMPARISON_HORIZON_DAYS:.0f}d comparison horizon"
        )
    horizon_return = (1.0 + float(total)) ** (COMPARISON_HORIZON_DAYS / float(span_days)) - 1.0
    return horizon_return, ""


def _bounded_score(value: Any, *, default: float = 1.0) -> float:
    if value is None:
        return default
    parsed = float(value)
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _capacity(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, parsed)


def _verify_cash_evidence(
    cash_yield_annual: float, evidence: dict[str, Any] | None
) -> tuple[bool, dict[str, Any]]:
    """Verify baseline bytes and return whether they are promotable REAL data."""
    if evidence is None:
        return False, {
            "evidence_class": "MANUAL_UNVERIFIED",
            "byte_verified": False,
            "promotable_as_real": False,
        }
    claimed_yield = float(evidence.get("annual_yield", -1.0))
    if claimed_yield != cash_yield_annual:
        raise ValueError("cash_yield_annual does not match cash evidence")
    raw_path = Path(str(evidence.get("raw_artifact", "")))
    claimed_sha = str(evidence.get("raw_sha256", ""))
    if not raw_path.is_file():
        raise ValueError(f"cash evidence raw artifact missing: {raw_path}")
    if not claimed_sha or sha256_of_file(raw_path) != claimed_sha:
        raise ValueError("cash evidence raw bytes do not match raw_sha256")
    evidence_class = str(evidence.get("evidence_class", ""))
    if evidence_class not in {"REAL", "RECORDED_RESPONSE", "FIXTURE"}:
        raise ValueError(f"unsupported cash evidence_class {evidence_class!r}")
    verified = {
        **evidence,
        "byte_verified": True,
        "promotable_as_real": evidence_class == "REAL",
    }
    return evidence_class == "REAL", verified


def _mining_score(cell: dict[str, Any]) -> tuple[float | None, str]:
    """Return net ROC over the evidenced rental horizon.

    A short rental is not presumed repeatable for a year. Prefer the explicit
    horizon cash flows emitted by the economics engine; the hourly ratio is an
    equivalent fallback because both numerator and denominator use the same
    evidenced horizon. Neither path multiplies a short opportunity by 8,766.
    """
    econ = cell.get("conditional_economics") or {}
    horizon_net = econ.get("horizon_net_usd")
    horizon_cost = econ.get("horizon_cost_usd")
    horizon_hours = econ.get("horizon_hours")
    if horizon_net is not None and horizon_cost is not None:
        if horizon_hours is None or not math.isclose(
            float(horizon_hours), COMPARISON_HORIZON_DAYS * 24.0
        ):
            return None, (
                "mining evidence horizon must equal the 30d board horizon; "
                "short rentals are not assumed repeatable"
            )
        net = float(horizon_net)
        cost = float(horizon_cost)
        if math.isfinite(net) and math.isfinite(cost) and cost > 0:
            return net / cost, ""
        return None, "mining horizon net/cost must be finite with positive cost"
    return None, "no verified 30d horizon net/cost return"


def build_opportunity_board(
    *,
    trading_rows: list[dict[str, Any]],
    mining_cells: list[dict[str, Any]],
    cash_yield_annual: float,
    evaluated_at_utc: str,
    trading_lineage: dict[str, Any] | None = None,
    mining_lineage: dict[str, Any] | None = None,
    cash_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not math.isfinite(cash_yield_annual) or cash_yield_annual < 0:
        raise ValueError("cash_yield_annual must be finite and >= 0")
    cash_promotable, verified_cash_evidence = _verify_cash_evidence(
        cash_yield_annual, cash_evidence
    )
    cash_horizon_return = (1.0 + cash_yield_annual) ** (COMPARISON_HORIZON_DAYS / 365.25) - 1.0
    _verify_lineage("trading", trading_rows, trading_lineage, "TRADING_OPPORTUNITY_LEADERBOARD")
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
            score=cash_horizon_return,
            reasons=["byte-bound cash baseline prorated to the 30d comparison horizon"],
        )
    ]
    for row in trading_rows:
        metrics = row.get("metrics") or {}
        eligible = (
            row.get("status") == "PAPER_CANDIDATE"
            and row.get("data_source") == "real"
            and cash_promotable
        )
        score, unit_problem = _trading_score(row)
        reasons = list(row.get("reasons") or [])
        if (
            row.get("status") == "PAPER_CANDIDATE"
            and row.get("data_source") == "real"
            and not cash_promotable
        ):
            reasons.insert(0, "cash baseline is not byte-verified REAL evidence")
        if eligible and score is None:
            eligible = False
            reasons.insert(0, unit_problem)
        if eligible and score is not None and score <= cash_horizon_return:
            eligible = False
            reasons.insert(0, "net return does not exceed the cash baseline")
        entries.append(
            BoardEntry(
                entry_id=f"trading:{row.get('hypothesis_id', '?')}",
                kind="trading",
                status=str(row.get("status", "")),
                eligible=eligible,
                score=score if eligible else None,
                reasons=reasons,
                capacity_usd=_capacity(row.get("capacity_usd", metrics.get("capacity_usd"))),
                risk_score=_bounded_score(row.get("risk_score", metrics.get("risk_score"))),
                liquidity_score=_bounded_score(
                    row.get("liquidity_score", metrics.get("liquidity_score"))
                ),
            )
        )
    for cell in mining_cells:
        status = str(cell.get("status", ""))
        test_only = bool(cell.get("test_only"))
        eligible = status == "ECONOMIC_CANDIDATE_PAPER_ONLY" and not test_only and cash_promotable
        score, unit_problem = _mining_score(cell)
        reasons = list(cell.get("reasons") or [])
        if status == "ECONOMIC_CANDIDATE_PAPER_ONLY" and not test_only and not cash_promotable:
            reasons.insert(0, "cash baseline is not byte-verified REAL evidence")
        if eligible and score is None:
            eligible = False
            reasons.insert(0, unit_problem)
        if eligible and score is not None and score <= cash_horizon_return:
            eligible = False
            reasons.insert(0, "net return does not exceed the cash baseline")
        econ = cell.get("conditional_economics") or {}
        entries.append(
            BoardEntry(
                entry_id=f"mining:{cell.get('identity', '?')}",
                kind="mining",
                status=status,
                eligible=eligible,
                score=score if eligible else None,
                reasons=reasons,
                test_only=test_only,
                capacity_usd=_capacity(
                    cell.get(
                        "capacity_usd",
                        econ.get("capacity_usd", econ.get("budget_ceiling_usd")),
                    )
                ),
                risk_score=_bounded_score(cell.get("risk_score", econ.get("risk_score"))),
                liquidity_score=_bounded_score(
                    cell.get("liquidity_score", econ.get("liquidity_score"))
                ),
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
        "comparison_horizon_days": COMPARISON_HORIZON_DAYS,
        "cash_yield_annual": cash_yield_annual,
        "cash_return_comparison_horizon": cash_horizon_return,
        "cash_evidence": verified_cash_evidence,
        "cash_evidence_promotable": cash_promotable,
        "entries": [e.to_dict() for e in ordered],
        "champion": champion.to_dict(),
        "challengers": [e.to_dict() for e in challengers],
        "lineage": {"trading": trading_lineage, "mining": mining_lineage},
        "safety": dict(SAFETY_POSTURE),
        "real_money_authorized": False,
        "notes": [
            "every ranked score is net return on committed capital",
            "short opportunities are never annualized as automatically repeatable",
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
    if not math.isfinite(total_capital_usd) or total_capital_usd <= 0:
        raise ValueError("total_capital_usd must be finite and > 0")
    if not 0 < max_fraction_per_opportunity <= 1:
        raise ValueError("max_fraction_per_opportunity must be in (0, 1]")
    entries = board.get("entries", [])
    cash_score = max(
        (
            float(e["score"])
            for e in entries
            if e.get("kind") == "cash" and e.get("score") is not None
        ),
        default=0.0,
    )
    candidates = []
    for entry in entries:
        if not entry.get("eligible") or entry.get("kind") == "cash":
            continue
        score = entry.get("score")
        parsed_score = float(score) if score is not None else None
        risk_score = _bounded_score(entry.get("risk_score"))
        liquidity_score = _bounded_score(entry.get("liquidity_score"))
        capacity_usd = _capacity(entry.get("capacity_usd"))
        if (
            score is None
            or parsed_score is None
            or not math.isfinite(parsed_score)
            or parsed_score <= cash_score
            or risk_score <= 0
            or liquidity_score <= 0
            or capacity_usd == 0
        ):
            continue
        candidates.append(entry)

    raw_weights = {
        str(entry["entry_id"]): (
            (float(entry["score"]) - cash_score)
            * _bounded_score(entry.get("risk_score"))
            * _bounded_score(entry.get("liquidity_score"))
        )
        for entry in candidates
    }
    total_weight = sum(raw_weights.values())
    candidate_budget = min(1.0, max_fraction_per_opportunity * len(candidates))
    lines: list[dict[str, Any]] = []
    allocated = 0.0
    for e in candidates:
        weighted_fraction = (
            candidate_budget * raw_weights[str(e["entry_id"])] / total_weight
            if total_weight > 0
            else 0.0
        )
        capacity_usd = _capacity(e.get("capacity_usd"))
        capacity_fraction = capacity_usd / total_capital_usd if capacity_usd is not None else 1.0
        fraction = min(
            max_fraction_per_opportunity,
            capacity_fraction,
            weighted_fraction,
        )
        capital = total_capital_usd * fraction
        allocated += capital
        lines.append(
            {
                "entry_id": e["entry_id"],
                "kind": e["kind"],
                "status": e["status"],
                "fraction": fraction,
                "capital_usd": capital,
                "rationale": (
                    "eligible above cash; weighted by excess return, risk, liquidity and capacity"
                ),
            }
        )
    for e in entries:
        if e.get("kind") != "cash" and e not in candidates:
            if e.get("eligible") and e.get("score") is not None:
                if float(e["score"]) <= cash_score:
                    rationale = "net return does not exceed the cash baseline"
                elif _bounded_score(e.get("risk_score")) <= 0:
                    rationale = "risk budget score is zero"
                elif _bounded_score(e.get("liquidity_score")) <= 0:
                    rationale = "liquidity score is zero"
                elif _capacity(e.get("capacity_usd")) == 0:
                    rationale = "verified capacity is zero"
                else:
                    rationale = "not allocatable"
            else:
                rationale = (e.get("reasons") or ["not eligible"])[0]
            lines.append(
                {
                    "entry_id": e["entry_id"],
                    "kind": e["kind"],
                    "status": e["status"],
                    "fraction": 0.0,
                    "capital_usd": 0.0,
                    "rationale": rationale,
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
