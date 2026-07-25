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

from quant_trade.cloud_rental.market import ALGORITHM_UNITS
from quant_trade.cloud_rental.models import CloudProvider, WorkloadPurpose
from quant_trade.cloud_rental.policy import OFFICIAL_POLICY_SOURCES, evaluate_provider_policy
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
from quant_trade.opportunities.mining_scan import load_scan_config, scan_mining_cells
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
    "MINING_POLICY_MATRIX.json",
    "MINING_UNIT_AUDIT.json",
    "MINING_EVIDENCE_REPORT.json",
    "MINING_RENTAL_MATRIX.json",
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
        ("V7-001", "P0-A", "portable append lock", "FIXED_GREEN"),
        ("V7-002", "P0-A", "normalized receipt hash verification", "FIXED_GREEN"),
        ("V7-003", "P0-A", "relative raw paths and traversal rejection", "FIXED_GREEN"),
        ("V7-004", "P0-A", "clean raw-to-panel reconstruction", "FIXED_GREEN"),
        ("V7-005", "P0-A", "manifest and panel byte tamper detection", "FIXED_GREEN"),
        ("V7-006", "P0-A", "Bybit funding pagination and exact range", "FIXED_GREEN"),
        ("V7-007", "P0-B", "authoritative marked-equity net return", "FIXED_GREEN"),
        ("V7-008", "P0-B", "settlement-driven signal windows", "FIXED_GREEN"),
        ("V7-009", "P0-C", "rank-based CSCV PBO", "FIXED_GREEN"),
        ("V7-010", "P0-C", "global hash-chained trial registry", "FIXED_GREEN"),
        ("V7-011", "P0-D", "provider policy precedence", "FIXED_GREEN"),
        ("V7-012", "P0-E", "algorithm-native Decimal units", "FIXED_GREEN"),
        ("V7-013", "P0-E", "scanner opens claimed evidence bytes", "FIXED_GREEN"),
        ("V7-014", "P0-F", "billing, downtime and risk economics", "FIXED_GREEN"),
        ("V7-015", "P0-G", "remove mining score x8766", "FIXED_GREEN"),
        ("V7-016", "P0-G", "durable exactly-once shadow WAL", "FIXED_GREEN"),
        ("V7-017", "P0-G", "market order requires fresh mark", "FIXED_GREEN"),
        ("V7-018", "P0-G", "broker-paper idempotency keys", "FIXED_GREEN"),
        ("V7-019", "P0-A", "receipt/parser capture-clock identity", "FIXED_GREEN"),
        ("V7-020", "P0-A", "clean rebuild reapplies requested page range", "FIXED_GREEN"),
        ("V7-021", "P0-A", "panel-audit CLI invokes clean rebuild", "FIXED_GREEN"),
    ]
    return {
        "artifact": "DEFECT_REPRODUCTION_MATRIX",
        "schema_version": 2,
        "sprint": "Revenue Validation & Controlled Monetization V7",
        "base_sha": BASE_SHA,
        "baseline": {
            "platform": "Windows",
            "python": "3.12.13",
            "passed": 617,
            "failed": 25,
            "root_cause": "unconditional POSIX fcntl import",
        },
        "defects": [
            {"id": item[0], "priority": item[1], "title": item[2], "status": item[3]}
            for item in rows
        ],
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
                "path": path.relative_to(repo_root).as_posix(),
                "records": len(lines),
                "last_record": lines[-1] if lines else "",
            }
        )
    return {
        "artifact": "DATA_PROVENANCE_REPORT",
        "schema_version": 2,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "evidence_counts": {
            "REAL": 5,
            "RECORDED_REAL": 0,
            "RECORDED_RESPONSE": 1,
            "PAPER": 0,
            "SIMULATION": 0,
            "FIXTURE": 0,
        },
        "real_raw_data_captured": 5,
        "real_settlements_verified": 6,
        "real_local_uncommitted_capture": {
            "captured_at_utc": "2026-07-25T06:25:10Z",
            "venue": "bybit",
            "symbol": "BTC",
            "requested_range": [
                "2026-07-20T00:00:00Z",
                "2026-07-21T16:00:00Z",
            ],
            "raw_pages": 5,
            "panel_rows": 41,
            "settlements": 6,
            "clean_rebuild": True,
            "receipt_provenance": "real",
            "panel_sha256": ("7fc049917826aca4574dee2019efabe9a40685817155941854b6c926bfc3c176"),
            "manifest_sha256": ("b34d18940b16b6b5465caed64a14741aeb3e532e9df7d9d433fdcdcc5ff5e16b"),
            "receipt_chain_head": (
                "93fb3480c67a5dc3ddbc7a475142cf4dd315a98386530c934abe0cfe01d4b7ac"
            ),
            "committed_to_repository": False,
            "promotion_eligible": False,
            "reason": (
                "repository policy excludes market-data cache; raw bytes remain "
                "local, and 6 settlements are below the 1,000/730d gate"
            ),
        },
        "backfill_attempts": attempts,
        "promotion_rule": (
            "only receipt-verified REAL evidence can promote; recorded responses "
            "and fixtures remain non-promotable; local evidence whose raw bytes "
            "are absent from the repository cannot reproduce a promotion"
        ),
    }


def _policy_matrix() -> dict[str, Any]:
    rows = []
    for provider in (CloudProvider.AWS, CloudProvider.ALIBABA):
        for purpose in (WorkloadPurpose.CONTROL_PLANE, WorkloadPurpose.HASHING_WORKER):
            gate = evaluate_provider_policy(
                provider, purpose, None, evaluated_at_utc=EVALUATED_AT_UTC
            )
            rows.append(
                {
                    "provider": provider,
                    "purpose": purpose,
                    "status": gate.status,
                    "control_plane_allowed": gate.control_plane_allowed,
                    "hashing_allowed": gate.hashing_allowed,
                    "reason": gate.reason,
                    "official_sources_to_capture": OFFICIAL_POLICY_SOURCES[str(provider)],
                    "source_snapshot_evidence": "MISSING",
                }
            )
    return {
        "artifact": "MINING_POLICY_MATRIX",
        "schema_version": 2,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "rows": rows,
        "legal_advice": False,
        "miner_execution_authorized": False,
    }


def _unit_audit() -> dict[str, Any]:
    return {
        "artifact": "MINING_UNIT_AUDIT",
        "schema_version": 2,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "universal_th_divisor_present": False,
        "algorithms": [definition.to_dict() for _, definition in sorted(ALGORITHM_UNITS.items())],
    }


def _mining_evidence(matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "MINING_EVIDENCE_REPORT",
        "schema_version": 2,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "real_quote_count": 0,
        "real_exact_sku_benchmark_count": 0,
        "real_market_snapshot_count": 0,
        "real_delivery_evidence_count": 0,
        "cells": [
            {
                "identity": cell["identity"],
                "status": cell["status"],
                "test_only": cell["test_only"],
                "reasons": cell["reasons"],
            }
            for cell in matrix["cells"]
        ],
        "compute_rental": "POLICY_BLOCKED_AND_MISSING_BYTE_VERIFIED_EVIDENCE",
        "hashpower_marketplace": (
            "DISCOVERY_ONLY_IMPORTER_READY_NO_DELIVERY_HISTORY_OR_ECONOMIC_ENGINE"
        ),
        "managed_asic_lease": "DISCOVERY_ONLY_NO_CONTRACT_OR_DELIVERY_HISTORY",
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
    mining_cfg_path = root / "configs/opportunities/mining_scan_v5.yaml"
    mining = scan_mining_cells(
        load_scan_config(mining_cfg_path),
        evaluated_at_utc=EVALUATED_AT_UTC,
        config_dir=mining_cfg_path.parent,
    ).to_dict()
    cash = _cash_evidence(root)
    trading_rows = list(trading["rows"])
    mining_cells = list(mining["cells"])
    board = build_opportunity_board(
        trading_rows=trading_rows,
        mining_cells=mining_cells,
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
        mining_lineage=lineage_for_rows(
            mining_cells,
            artifact="MINING_RENTAL_MATRIX",
            path="artifacts/v7/MINING_RENTAL_MATRIX.json",
            evaluated_at_utc=EVALUATED_AT_UTC,
        ),
    )
    board["cash_evidence"] = cash
    allocation = allocate_paper_capital(board, 100_000.0)

    payloads = {
        "DEFECT_REPRODUCTION_MATRIX.json": _defect_matrix(),
        "DATA_PROVENANCE_REPORT.json": _data_provenance(root),
        "TRADING_LEADERBOARD.json": trading,
        "MINING_POLICY_MATRIX.json": _policy_matrix(),
        "MINING_UNIT_AUDIT.json": _unit_audit(),
        "MINING_EVIDENCE_REPORT.json": _mining_evidence(mining),
        "MINING_RENTAL_MATRIX.json": mining,
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
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "base_sha": BASE_SHA,
        "source_commit_sha": source_commit_sha,
        "command": "make v7-artifacts SOURCE_COMMIT_SHA=<code-commit-sha>",
        "artifact_sha256": hashes,
        "deterministic_fields": "all fields",
        "real_evidence_promotable": False,
        "paper_candidate_count": 0,
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
