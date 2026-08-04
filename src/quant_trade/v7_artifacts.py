"""Deterministic V7 economic-board and evidence-artifact regeneration.

This module performs only offline reads and local artifact writes. It never
submits orders, starts miners, calls cloud control planes, or authorizes spend.
The fixed evaluation clock makes repeated builds byte-identical for the same
source commit and evidence bytes.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    load_json,
    sha256_of_file,
)
from quant_trade.opportunities.board import (
    allocate_paper_capital,
    build_opportunity_board,
    lineage_for_rows,
)
from quant_trade.opportunities.trading_scan import (
    load_trading_scan_config,
    scan_trading_opportunities,
)

EVALUATED_AT_UTC = "2026-07-25T06:00:00Z"
BASE_SHA = "98daabe6585bfa80d7706a61c8742d5da8ac9ea3"
ARTIFACT_NAMES = (
    "DEFECT_REPRODUCTION_MATRIX.json",
    "DATA_PROVENANCE_REPORT.json",
    "TRADING_LEADERBOARD.json",
    "UNIFIED_OPPORTUNITY_BOARD.json",
    "PAPER_ALLOCATION.json",
    "SHADOW_STATUS.json",
    "PROMOTION_REPRODUCIBILITY.json",
)


def _source_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _cash_evidence(repo_root: Path) -> dict[str, Any]:
    evidence = load_json(repo_root / "configs/opportunities/cash_baseline_v7.json")
    raw_path = repo_root / str(evidence["raw_artifact"])
    actual = sha256_of_file(raw_path)
    if actual != evidence["raw_sha256"]:
        raise ValueError("cash baseline raw bytes do not match raw_sha256")
    if float(evidence["annual_yield"]) < 0:
        raise ValueError("cash baseline annual_yield must be non-negative")
    return {
        **evidence,
        "byte_verified": True,
        "promotable_as_real": evidence["evidence_class"] == "REAL",
    }


def _defect_matrix() -> dict[str, Any]:
    rows = [
        ("V7-001", "P0-A", "portable append lock"),
        ("V7-002", "P0-A", "normalized receipt hash verification"),
        ("V7-003", "P0-A", "relative raw paths and traversal rejection"),
        ("V7-004", "P0-A", "clean raw-to-panel reconstruction"),
        ("V7-005", "P0-A", "manifest and panel byte tamper detection"),
        ("V7-006", "P0-A", "Bybit funding pagination and exact range"),
        ("V7-007", "P0-B", "authoritative marked-equity net return"),
        ("V7-008", "P0-B", "settlement-driven signal windows"),
        ("V7-009", "P0-C", "rank-based CSCV PBO"),
        ("V7-010", "P0-C", "global hash-chained trial registry"),
        ("V7-011", "P0-D", "provider policy precedence"),
        ("V7-012", "P0-E", "algorithm-native Decimal units"),
        ("V7-013", "P0-E", "scanner opens claimed evidence bytes"),
        ("V7-014", "P0-F", "billing, downtime and risk economics"),
        ("V7-015", "P0-G", "remove mining score x8766"),
        ("V7-016", "P0-G", "durable exactly-once shadow WAL"),
        ("V7-017", "P0-G", "market order requires fresh mark"),
        ("V7-018", "P0-G", "broker-paper idempotency keys"),
        ("V7-019", "P0-A", "receipt/parser capture-clock identity"),
        ("V7-020", "P0-A", "clean rebuild reapplies requested page range"),
        ("V7-021", "P0-A", "panel-audit CLI invokes clean rebuild"),
    ]
    return {
        "artifact": "DEFECT_REPRODUCTION_MATRIX",
        "schema_version": 3,
        "sprint": "Revenue Validation & Controlled Monetization V7",
        "base_sha": BASE_SHA,
        "evidence_class": "NOT_MEASURED",
        # This generator runs no test suite and parses no test report, so it
        # cannot state a baseline or a per-defect outcome. The previous shape
        # published "passed": 617 / "failed": 25 and 21 rows of "FIXED_GREEN"
        # as if they had been observed; nothing produced them.
        "baseline": None,
        "baseline_state": "NOT_MEASURED",
        "defects": [
            {
                "id": item[0],
                "priority": item[1],
                "title": item[2],
                "status": "NOT_MEASURED",
            }
            for item in rows
        ],
        "what_is_and_is_not_measured": (
            "the defect identifiers, priorities and titles are a hand-maintained "
            "register and are accurate as a list of intent; no field here reports "
            "a verification outcome, because this generator verifies nothing. "
            "Whether a defect is closed can only be read from the test suite."
        ),
        "open_routes": [
            {
                "route": "OKX full historical panel acquisition",
                "status": "TECHNICALLY_BLOCKED_NOT_IMPLEMENTED",
            },
            {
                "route": "hashpower marketplace economic execution model",
                "status": "DISCOVERY_ONLY_IMPORTER_ONLY_ECONOMICS_NOT_IMPLEMENTED",
            },
        ],
    }


def _data_provenance(repo_root: Path) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for path in sorted((repo_root / "data/carry").glob("**/backfill_attempts.jsonl")):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        attempts.append(
            {
                # This entry is read from disk, so it carries its own class:
                # the report as a whole measures nothing, but these counts do.
                "evidence_class": "MEASURED",
                "path": path.relative_to(repo_root).as_posix(),
                "records": len(lines),
                "last_record": lines[-1] if lines else "",
            }
        )
    return {
        "artifact": "DATA_PROVENANCE_REPORT",
        "schema_version": 3,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "evidence_class": "NOT_MEASURED",
        # Nothing in this generator censuses evidence by class, and no capture
        # of real venue data has ever completed here: the only machine record
        # of the attempt is backfill_attempts below, which reports
        # status NOT_RUN_NETWORK_BLOCKED with 0 settlements and 0 panel rows.
        "evidence_counts": None,
        "real_raw_data_captured": None,
        "real_settlements_verified": None,
        "real_local_uncommitted_capture": None,
        "withdrawn_claims": [
            "evidence_counts previously reported 5 REAL artefacts; no directory "
            "walk or registry read produced that number",
            "real_raw_data_captured (5) and real_settlements_verified (6) were "
            "literals, contradicted by the recorded backfill attempt",
            "real_local_uncommitted_capture asserted a completed Bybit capture "
            "of 5 raw pages, 41 panel rows and 6 settlements, carrying a "
            "panel_sha256, a manifest_sha256 and a receipt_chain_head. Those "
            "three digests corresponded to no bytes in this repository or "
            "anywhere else; they are withdrawn rather than reissued",
        ],
        "backfill_attempts": attempts,
        "promotion_rule": (
            "only receipt-verified REAL evidence can promote; recorded responses "
            "and fixtures remain non-promotable; local evidence whose raw bytes "
            "are absent from the repository cannot reproduce a promotion"
        ),
    }


def _shadow_status(allocation: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "SHADOW_STATUS",
        "schema_version": 2,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "status": "NOT_STARTED_NO_ELIGIBLE_NON_CASH_CANDIDATE",
        "allocation_artifact": allocation["artifact"],
        "events_processed": 0,
        "broker_paper_claimed": False,
        "real_money_authorized": False,
        "reason": "100% cash; starting a shadow deployment would add no economic evidence",
    }


def generate_v7_artifacts(
    *,
    repo_root: str | Path,
    output_dir: str | Path,
    source_commit_sha: str,
) -> list[Path]:
    """Regenerate every required V7 JSON artifact in dependency order."""
    root = Path(repo_root).resolve()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    trading_cfg_path = root / "configs/opportunities/trading_scan_v5.yaml"
    trading = scan_trading_opportunities(
        load_trading_scan_config(trading_cfg_path),
        evaluated_at_utc=EVALUATED_AT_UTC,
        config_dir=root,
    ).to_dict()
    cash = _cash_evidence(root)
    trading_rows = list(trading["rows"])
    board = build_opportunity_board(
        trading_rows=trading_rows,
        cash_yield_annual=float(cash["annual_yield"]),
        evaluated_at_utc=EVALUATED_AT_UTC,
        cash_evidence={
            **cash,
            "raw_artifact": str(root / str(cash["raw_artifact"])),
        },
        trading_lineage=lineage_for_rows(
            trading_rows,
            artifact="TRADING_OPPORTUNITY_LEADERBOARD",
            path="artifacts/v7/TRADING_LEADERBOARD.json",
            evaluated_at_utc=EVALUATED_AT_UTC,
        ),
    )
    board["cash_evidence"] = cash
    allocation = allocate_paper_capital(board, 100_000.0)

    payloads = {
        "DEFECT_REPRODUCTION_MATRIX.json": _defect_matrix(),
        "DATA_PROVENANCE_REPORT.json": _data_provenance(root),
        "TRADING_LEADERBOARD.json": trading,
        "UNIFIED_OPPORTUNITY_BOARD.json": board,
        "PAPER_ALLOCATION.json": allocation,
        "SHADOW_STATUS.json": _shadow_status(allocation),
    }
    written = [atomic_write_json(out / name, payload) for name, payload in payloads.items()]
    hashes = {
        path.name: sha256_of_file(path) for path in sorted(written, key=lambda item: item.name)
    }
    reproducibility = {
        "artifact": "PROMOTION_REPRODUCIBILITY",
        "schema_version": 2,
        # File hashes computed from bytes, flags derived from the board and
        # the leaderboard: everything here is produced by this run.
        "evidence_class": "MEASURED",
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "base_sha": BASE_SHA,
        "source_commit_sha": source_commit_sha,
        "command": "make v7-artifacts SOURCE_COMMIT_SHA=<code-commit-sha>",
        "artifact_sha256": hashes,
        "deterministic_fields": "all fields",
        # Derived from the board and the leaderboard rather than restated: both
        # were literals that happened to agree with the computation, so they
        # would not have followed it if the underlying evidence changed.
        "real_evidence_promotable": bool(board["cash_evidence_promotable"]),
        "paper_candidate_count": int(trading["counts_by_status"].get("PAPER_CANDIDATE", 0)),
        "safety": {
            "live_orders": 0,
            "miners_started": 0,
            "cloud_resources_created": 0,
            "external_spend_usd": 0,
        },
    }
    written.append(atomic_write_json(out / "PROMOTION_REPRODUCIBILITY.json", reproducibility))
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/v7"))
    parser.add_argument("--source-commit-sha")
    args = parser.parse_args()
    source_sha = args.source_commit_sha or _source_commit(args.repo_root.resolve())
    written = generate_v7_artifacts(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        source_commit_sha=source_sha,
    )
    print(f"generated {len(written)} V7 artifacts; source_commit_sha={source_sha}")


if __name__ == "__main__":
    main()
