"""Frozen public contracts for the local Quant Research Auditor."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text


class AuditStatus(StrEnum):
    """Fail-closed status shared by individual checks and the final verdict."""

    PASS = "PASS"
    NO_GO = "NO_GO"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FindingClass(StrEnum):
    """Whether a finding is about the method or about the result.

    A package can be methodologically clean and still not beat its benchmark.
    Both are worth reporting, but only the first is a defect in how the research
    was conducted, and a customer is owed that distinction.  This label changes
    nothing about the verdict: a blocking check blocks either way.
    """

    #: An error in how the result was produced: look-ahead, unbound bytes,
    #: same-bar execution, undeclared costs, a broken trial ledger.
    DEFECT = "DEFECT"
    #: A property of the result itself, correctly measured.
    RESULT = "RESULT"


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
    symbol_column: str = "symbol"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def redacted(self) -> AuditInput:
        """Drop local filesystem layout from anything that leaves this machine.

        The delivered bundle keeps file *names* so a customer can tell which
        artifact a finding refers to, and loses the directory tree of whoever
        ran the audit.  The result stays self-consistent: its digest still
        recomputes from exactly the bytes in the delivered file.
        """
        return replace(
            self,
            root_dir="<redacted>",
            dataset_path=PurePath(self.dataset_path).name,
            results_path=PurePath(self.results_path).name,
            manifest_path=PurePath(self.manifest_path).name if self.manifest_path else None,
            trial_ledger_path=(
                PurePath(self.trial_ledger_path).name if self.trial_ledger_path else None
            ),
        )


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
    finding_class: FindingClass = FindingClass.DEFECT

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["finding_class"] = self.finding_class.value
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
    # v2 adds AuditCheck.finding_class and AuditInput.symbol_column, so a v2
    # digest is deliberately not comparable with a v1 one.
    schema_version: int = 2

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


def recompute_bundle_digest(payload: dict[str, Any]) -> str:
    """Recompute a delivered bundle's digest from its own bytes.

    A content address nobody else can check is decoration.  This lets the
    recipient of an ``audit.json`` confirm, with no trust in the sender and no
    access to the original inputs, that the file was not edited after it was
    produced.
    """
    if not isinstance(payload, dict) or "bundle_digest" not in payload:
        raise ValueError("payload must be an audit bundle containing bundle_digest")
    content = {key: value for key, value in payload.items() if key != "bundle_digest"}
    return sha256_of_text(canonical_dumps(content))
