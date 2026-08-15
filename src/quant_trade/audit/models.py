"""Frozen public contracts for the local Quant Research Auditor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text


class AuditStatus(StrEnum):
    """Fail-closed status shared by individual checks and the final verdict."""

    PASS = "PASS"
    NO_GO = "NO_GO"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class AuditInput:
    """Resolved, local-only inputs selected by the operator."""

    root_dir: str
    dataset_path: str
    results_path: str
    manifest_path: str | None
    trial_ledger_path: str | None
    evaluation_cutoff_utc: str
    required_columns: tuple[str, ...]
    timestamp_column: str = "timestamp"
    max_file_size_bytes: int = 25_000_000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditJob:
    """Deterministic description of one completed offline audit."""

    job_id: str
    engine_version: str = "quant-research-auditor-v1"
    mode: str = "offline_byod"
    state: str = "completed"
    network_accessed: bool = False
    customer_code_executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditCheck:
    """One machine-readable finding with bounded, escaped evidence strings."""

    code: str
    category: str
    status: AuditStatus
    summary: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class AuditVerdict:
    """Conservative aggregate verdict; it never authorizes real money."""

    status: AuditStatus
    reasons: tuple[str, ...]
    pass_count: int
    no_go_count: int
    insufficient_evidence_count: int
    real_money_authorized: bool = False
    expected_profit_established: bool = False
    external_action_authorized: bool = False

    def __post_init__(self) -> None:
        if self.real_money_authorized:
            raise ValueError("an audit verdict can never authorize real-money trading")
        if self.expected_profit_established:
            raise ValueError("an audit verdict can never establish expected profit")
        if self.external_action_authorized:
            raise ValueError("an audit verdict can never authorize external action")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class AuditBundle:
    """Content-addressed audit result rendered as deterministic JSON and HTML."""

    audit_input: AuditInput
    job: AuditJob
    input_hashes: tuple[tuple[str, str], ...]
    checks: tuple[AuditCheck, ...]
    verdict: AuditVerdict
    schema_version: int = 1

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_input": self.audit_input.to_dict(),
            "job": self.job.to_dict(),
            "input_hashes": {key: value for key, value in self.input_hashes},
            "checks": [check.to_dict() for check in self.checks],
            "verdict": self.verdict.to_dict(),
        }

    @property
    def bundle_digest(self) -> str:
        return sha256_of_text(canonical_dumps(self._content_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "bundle_digest": self.bundle_digest}
