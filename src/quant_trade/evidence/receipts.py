"""Ingestion receipts: provenance is VERIFIED, never self-declared.

A receipt is written at capture time for every raw response: where it came
from, how it was requested, where the raw bytes live, and the SHA-256 of both
the raw bytes and the normalized rows. Provenance resolution then works
backwards from the receipts:

- a record is ``real`` ONLY if its ``raw_sha256`` matches a receipt whose
  ``source_kind`` is ``live`` AND whose raw bytes still hash correctly;
- ``fixture`` / ``recorded_test_response`` / ``manual`` / ``synthetic`` /
  ``unknown`` receipts are TEST_ONLY forever;
- records without any receipt are ``unverified_legacy`` — not promotable;
- a broken raw file invalidates the dataset; mixtures resolve to ``mixed``.

Any ``data_source`` string carried INSIDE a record is ignored by resolution:
reproducibility is not authenticity, and a self-label is not evidence. Hashes
and manifests stay verifiable offline; an external signing interface can be
layered on in production — no invented keys here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

RECEIPTS_FILENAME = "receipts.jsonl"

#: The ONLY source kind that can ever resolve to real.
REAL_SOURCE_KINDS = ("live",)
#: Kinds that are valid receipts but can never be real.
TEST_ONLY_SOURCE_KINDS = (
    "fixture",
    "recorded_test_response",
    "manual",
    "synthetic",
    "unknown",
)


@dataclass(frozen=True)
class IngestionReceipt:
    provider_or_venue: str
    endpoint: str
    request_parameters: dict[str, Any]  # never secrets
    http_status: int
    captured_at_utc: str
    adapter_name: str
    adapter_version: str
    raw_path: str  # relative to the receipts file's directory when possible
    raw_sha256: str
    normalized_rows_sha256: str
    source_kind: str
    server_timestamp_utc: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        valid = REAL_SOURCE_KINDS + TEST_ONLY_SOURCE_KINDS
        if self.source_kind not in valid:
            raise ValueError(f"source_kind must be one of {valid}")
        if not self.raw_sha256.strip() or not self.raw_path.strip():
            raise ValueError("raw_path and raw_sha256 are required")
        if not self.captured_at_utc.strip():
            raise ValueError("captured_at_utc is required")
        for key in self.request_parameters:
            lowered = str(key).lower()
            if any(s in lowered for s in ("secret", "token", "key", "password")):
                raise ValueError("request_parameters must never carry secrets")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_rows_sha256(rows: list[dict[str, Any]]) -> str:
    return sha256_of_text("\n".join(canonical_dumps(r) for r in rows))


def append_receipt(receipts_path: str | Path, receipt: IngestionReceipt) -> Path:
    p = Path(receipts_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(receipt.to_dict()) + "\n")
    return p


def load_receipts(receipts_path: str | Path) -> list[dict[str, Any]]:
    import json

    p = Path(receipts_path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def verify_receipt_bytes(record: dict[str, Any], *, base_dir: Path) -> list[str]:
    """Recompute the raw SHA from the actual bytes. Empty list = verified."""
    from quant_trade.evidence.canonical_json import sha256_of_file

    problems: list[str] = []
    raw_path = Path(str(record.get("raw_path", "")))
    if not raw_path.is_absolute():
        raw_path = base_dir / raw_path
    if not raw_path.exists():
        return [f"raw payload missing on disk: {raw_path}"]
    actual = sha256_of_file(raw_path)
    if actual != str(record.get("raw_sha256", "")):
        problems.append(
            f"raw payload bytes do not hash to the receipt's raw_sha256 ({raw_path.name})"
        )
    return problems


@dataclass
class ProvenanceReport:
    provenance: str  # "real" | "test_only" | "unverified_legacy" | "mixed" | "invalid"
    records_total: int = 0
    records_real: int = 0
    records_test_only: int = 0
    records_unverified: int = 0
    records_invalid: int = 0
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_provenance(
    records: list[dict[str, Any]],
    receipts_path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> ProvenanceReport:
    """Resolve dataset provenance from VERIFIED receipts; self-labels ignored."""
    receipts_file = Path(receipts_path)
    base = Path(base_dir) if base_dir is not None else receipts_file.parent
    verified: dict[str, str] = {}  # raw_sha256 -> source_kind (byte-verified)
    broken: dict[str, str] = {}
    for receipt in load_receipts(receipts_file):
        sha = str(receipt.get("raw_sha256", ""))
        problems = verify_receipt_bytes(receipt, base_dir=base)
        if problems:
            broken[sha] = "; ".join(problems)
        else:
            verified[sha] = str(receipt.get("source_kind", "unknown"))

    report = ProvenanceReport(provenance="unverified_legacy", records_total=len(records))
    kinds: set[str] = set()
    for record in records:
        sha = str(record.get("raw_sha256", ""))
        if sha and sha in broken:
            report.records_invalid += 1
            kinds.add("invalid")
            report.problems.append(broken[sha])
        elif sha and sha in verified:
            if verified[sha] in REAL_SOURCE_KINDS:
                report.records_real += 1
                kinds.add("real")
            else:
                report.records_test_only += 1
                kinds.add("test_only")
        else:
            report.records_unverified += 1
            kinds.add("unverified_legacy")

    if "invalid" in kinds:
        report.provenance = "invalid"
        report.problems.insert(0, "raw evidence broken: dataset invalidated")
    elif len(kinds) > 1:
        report.provenance = "mixed"
        report.problems.append(
            "records mix receipt-verified and unverified/test provenance"
        )
    elif kinds:
        report.provenance = kinds.pop()
    return report
