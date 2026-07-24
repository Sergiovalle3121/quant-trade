"""Reproducible promotion: a claim is promotable only if a clean room rebuilds it.

``reproduce_campaign`` takes the campaign config and a directory of CLAIMED
artifacts, rebuilds the campaign from scratch in an isolated directory, and
byte-compares every evidence file. One flipped byte anywhere — results,
manifest, or return series — and the claim is rejected. Only a byte-identical
rebuild proceeds to the artifact-recomputing promotion review, whose best
possible outcome remains PAPER_CANDIDATE. The rebuild is a verification of an
existing trial, not a new one: its trial-ledger entry stays in the scratch
rebuild directory and is never counted against the claimed campaign.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import sha256_of_bytes

#: Every artifact a campaign writes that must rebuild byte-identically —
#: including the ledger's reconciliation, equity curve and cash-flow journal.
COMPARED_ARTIFACTS = (
    "results.json",
    "dataset_manifest.json",
    "net_returns.csv",
    "reconciliation.json",
    "equity_curve.csv",
    "funding_cashflows.jsonl",
)


@dataclass
class ReproductionReport:
    status: str
    reproduced: bool = False
    claimed_dir: str = ""
    rebuild_dir: str = ""
    artifact_hashes: dict[str, dict[str, str]] = field(default_factory=dict)
    mismatched_artifacts: list[str] = field(default_factory=list)
    promotion_failures: list[str] = field(default_factory=list)
    error: str = ""
    real_money_authorized: bool = False  # invariant: never True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reproduce_campaign(
    config: dict[str, Any],
    claimed_dir: str | Path,
    *,
    rebuild_dir: str | Path | None = None,
) -> ReproductionReport:
    """Clean-room rebuild + byte comparison + promotion review. Fails closed."""
    from quant_trade.carry.research import (
        evaluate_carry_promotion,
        run_carry_research,
        write_carry_artifacts,
    )
    from quant_trade.evidence.canonical_json import load_json
    from quant_trade.evidence.manifest import verify_dataset_manifest

    claimed = Path(claimed_dir)
    report = ReproductionReport(status="REJECTED_MISSING_EVIDENCE", claimed_dir=str(claimed))

    claimed_results = claimed / "results.json"
    if not claimed_results.exists():
        report.error = f"claimed artifact missing: {claimed_results}"
        return report
    try:
        claimed_payload = load_json(claimed_results)
    except Exception as exc:  # noqa: BLE001 - strict: unreadable evidence fails closed
        report.error = f"claimed results.json unreadable as strict JSON: {exc}"
        return report

    # The dataset named by the claim must still hash to the manifest's bytes —
    # a swapped or edited dataset can never quietly re-legitimise a claim.
    manifest = claimed_payload.get("dataset_manifest") or {}
    if str(manifest.get("path", "")) == "<inline>":
        # synthetic/inline datasets have no file bytes to re-verify — they can
        # never be tampered with, but they can never promote either
        report.status = "REJECTED_UNVERIFIABLE_DATASET"
        report.error = (
            "inline (synthetic) dataset manifests cannot be byte-verified; only "
            "file-backed real datasets are promotable"
        )
        return report
    verification = verify_dataset_manifest(manifest)
    if not verification.ok:
        report.status = "REJECTED_DATASET_TAMPERED"
        report.error = "; ".join(verification.problems)
        return report

    rebuild = (
        Path(rebuild_dir)
        if rebuild_dir is not None
        else Path(tempfile.mkdtemp(prefix="carry_promote_rebuild_"))
    )
    report.rebuild_dir = str(rebuild)
    try:
        result = run_carry_research(config)
        write_carry_artifacts(rebuild, config, result)
    except Exception as exc:  # noqa: BLE001 - a rebuild that cannot run cannot promote
        report.status = "REJECTED_REBUILD_FAILED"
        report.error = f"{type(exc).__name__}: {exc}"
        return report

    for name in COMPARED_ARTIFACTS:
        claimed_file = claimed / name
        rebuilt_file = rebuild / name
        claimed_sha = (
            sha256_of_bytes(claimed_file.read_bytes()) if claimed_file.exists() else ""
        )
        rebuilt_sha = (
            sha256_of_bytes(rebuilt_file.read_bytes()) if rebuilt_file.exists() else ""
        )
        report.artifact_hashes[name] = {"claimed": claimed_sha, "rebuilt": rebuilt_sha}
        if not claimed_sha or claimed_sha != rebuilt_sha:
            report.mismatched_artifacts.append(name)

    if report.mismatched_artifacts:
        report.status = "REJECTED_NOT_REPRODUCIBLE"
        report.error = (
            "clean-room rebuild does not match the claim byte-for-byte: "
            + ", ".join(report.mismatched_artifacts)
        )
        return report

    report.reproduced = True
    review = evaluate_carry_promotion(claimed_results, ledger_dir=claimed)
    report.promotion_failures = list(review.get("failures", []))
    report.status = str(review.get("status", "REJECTED"))
    return report
