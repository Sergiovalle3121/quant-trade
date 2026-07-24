"""Rented-mining opportunity scanner over provider×region×SKU×algorithm×coin.

Each cell is one fully-identified evidence bundle. The pipeline per cell is
fail-closed and order-preserving:

1. bundle validation (exact identity, byte-verified SHAs, fixture → TEST_ONLY);
2. the provider policy gate (a BLOCKED status survives — it is never converted
   into an economic verdict, and conditional economics computed while blocked
   can never rank above the block);
3. quote freshness, benchmark gate, cancelable-hourly economics.

The scan output is the MINING_RENTAL_MATRIX: every cell appears with its
status and reasons — blocked, missing, no-go, and candidate cells alike — so
absence of evidence is visible, never silently dropped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quant_trade.cloud_rental.bundle import EvidenceBundleValidator
from quant_trade.cloud_rental.catalog import (
    load_benchmark,
    load_policy_evidence,
    load_quote,
    load_spec,
)
from quant_trade.cloud_rental.economics import RevenueAssumptions
from quant_trade.cloud_rental.feasibility import evaluate_feasibility
from quant_trade.cloud_rental.models import SAFETY_POSTURE, WorkloadPurpose
from quant_trade.evidence.canonical_json import atomic_write_json


@dataclass
class MiningCellResult:
    identity: str
    provider: str
    region: str
    sku: str
    accelerator_model: str
    algorithm: str
    coin: str
    status: str
    test_only: bool
    bundle_status: str
    reasons: list[str] = field(default_factory=list)
    conditional_economics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MiningScanResult:
    evaluated_at_utc: str
    cells: list[MiningCellResult]
    counts_by_status: dict[str, int]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "MINING_RENTAL_MATRIX",
            "schema_version": 1,
            "evaluated_at_utc": self.evaluated_at_utc,
            "cells": [c.to_dict() for c in self.cells],
            "counts_by_status": self.counts_by_status,
            "safety": self.safety,
            "notes": [
                "TEST_ONLY cells exercise the pipeline and can never be real opportunities",
                "BLOCKED is a legal/operational state; economics never override it",
                "no miners were run, no resources created, no spend authorized",
            ],
        }


def load_scan_config(path: str | Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cells = payload.get("cells", [])
    if not isinstance(cells, list) or not cells:
        raise ValueError("mining scan config needs a non-empty 'cells' list")
    return cells


def scan_mining_cells(
    cells: list[dict[str, Any]], *, evaluated_at_utc: str, config_dir: Path | None = None
) -> MiningScanResult:
    """Evaluate every configured cell; nothing is dropped from the matrix."""
    validator = EvidenceBundleValidator()
    results: list[MiningCellResult] = []
    root = config_dir or Path(".")

    def resolve(p: str | None) -> Path | None:
        if not p:
            return None
        candidate = Path(p)
        return candidate if candidate.is_absolute() else root / candidate

    for cell in cells:
        quote = load_quote(cell["quote"])
        spec = load_spec(cell["spec"])
        benchmark = load_benchmark(cell["benchmark"]) if cell.get("benchmark") else None
        policy = (
            load_policy_evidence(cell["policy_evidence"])
            if cell.get("policy_evidence")
            else None
        )
        algorithm = str(cell.get("algorithm", "sha256"))
        coin = str(cell.get("coin", "BTC"))
        purpose = WorkloadPurpose(str(cell.get("purpose", "hashing_worker")))

        bundle = validator.validate(
            spec=spec,
            quote=quote,
            benchmark=benchmark,
            policy_evidence=policy,
            workload=purpose,
            algorithm=algorithm,
            benchmark_artifact_path=resolve(cell.get("benchmark_artifact")),
            policy_snapshot_path=resolve(cell.get("policy_snapshot")),
            require_benchmark=purpose is WorkloadPurpose.HASHING_WORKER,
        )
        row = MiningCellResult(
            identity=f"{bundle.identity}|{coin}",
            provider=str(spec.provider),
            region=spec.region,
            sku=spec.sku,
            accelerator_model=spec.accelerator_model,
            algorithm=algorithm,
            coin=coin,
            status="",
            test_only=bundle.test_only,
            bundle_status=bundle.status,
        )

        if bundle.status in ("REJECTED_IDENTITY_MISMATCH", "REJECTED_SHA_MISMATCH"):
            # Incoherent evidence can't even establish what the cell IS —
            # reject outright before consulting policy or economics.
            row.status = bundle.status
            row.reasons = bundle.problems
            results.append(row)
            continue

        revenue_cfg = cell.get("revenue") or {}
        decision = evaluate_feasibility(
            purpose=purpose,
            quote=quote,
            spec=spec,
            benchmark=benchmark,
            policy_evidence=policy,
            algorithm=algorithm,
            manual_hashrate_declared=bool(cell.get("manual_hashrate_hs")),
            revenue=RevenueAssumptions(**revenue_cfg) if revenue_cfg else None,
            horizon_hours=float(cell.get("horizon_hours", 24.0 * 30)),
            budget_ceiling_usd=float(cell.get("budget_ceiling_usd", 1000.0)),
            evaluated_at_utc=evaluated_at_utc,
        )
        status = decision.status
        if status.startswith("BLOCKED_P"):
            # legal/operational block is decisive — it outranks missing
            # benchmarks and is never converted into an economic verdict
            status = f"POLICY_BLOCKED:{decision.status}"
        elif (
            status == "BLOCKED_MISSING_BENCHMARK"
            or bundle.status == "REJECTED_MISSING_EVIDENCE"
        ):
            status = "MISSING_EVIDENCE"
        elif bundle.test_only and status.startswith("ECONOMIC_CANDIDATE"):
            # fixture-fed pipelines exercise the machinery; they are never
            # real opportunities and the status itself must say so
            status = f"TEST_ONLY_{status}"
        row.status = status
        row.reasons = [
            r
            for r in (
                decision.policy_reason,
                decision.benchmark_reason,
                decision.economic_reason,
                *bundle.problems,
            )
            if r
        ]
        # Conditional economics may be computed while blocked, but the block
        # stays the status; candidates carry their economics as details.
        if decision.details:
            row.conditional_economics = decision.details
        results.append(row)

    counts: dict[str, int] = {}
    for row in results:
        counts[row.status] = counts.get(row.status, 0) + 1
    return MiningScanResult(
        evaluated_at_utc=evaluated_at_utc,
        cells=results,
        counts_by_status=dict(sorted(counts.items())),
        safety=dict(SAFETY_POSTURE),
    )


def write_mining_matrix(path: str | Path, result: MiningScanResult) -> Path:
    return atomic_write_json(path, result.to_dict())
