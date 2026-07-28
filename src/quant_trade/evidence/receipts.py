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
from enum import StrEnum
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    sha256_of_text,
)

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
    "recorded_real",
)


class EvidenceClass(StrEnum):
    REAL = "REAL"
    RECORDED_REAL = "RECORDED_REAL"
    RECORDED_RESPONSE = "RECORDED_RESPONSE"
    PAPER = "PAPER"
    SIMULATION = "SIMULATION"
    FIXTURE = "FIXTURE"


SOURCE_KIND_EVIDENCE_CLASS = {
    "live": EvidenceClass.REAL,
    "recorded_real": EvidenceClass.RECORDED_REAL,
    "recorded_test_response": EvidenceClass.RECORDED_RESPONSE,
    "fixture": EvidenceClass.FIXTURE,
    "synthetic": EvidenceClass.SIMULATION,
    "manual": EvidenceClass.FIXTURE,
    "unknown": EvidenceClass.FIXTURE,
}


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
        for key in self.request_parameters:
            lowered = str(key).lower()
            if any(s in lowered for s in ("secret", "token", "key", "password")):
                raise ValueError("request_parameters must never carry secrets")
        if not self.raw_sha256.strip() or not self.raw_path.strip():
            raise ValueError("raw_path and raw_sha256 are required")
        if Path(self.raw_path).is_absolute():
            raise ValueError("raw_path must be relative to the receipts file")
        if not self.normalized_rows_sha256.strip():
            raise ValueError("normalized_rows_sha256 is required")
        if not self.captured_at_utc.strip():
            raise ValueError("captured_at_utc is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_rows_sha256(rows: list[dict[str, Any]]) -> str:
    return sha256_of_text("\n".join(canonical_dumps(r) for r in rows))


def receipt_relative_path(path: str | Path, receipts_path: str | Path) -> str:
    """Return a contained POSIX path relative to the receipt directory."""
    receipt_dir = Path(receipts_path).parent.resolve()
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(receipt_dir)
    except ValueError as exc:
        raise ValueError(f"raw evidence must stay inside receipt directory {receipt_dir}") from exc
    return relative.as_posix()


def _receipt_hash(record: dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "receipt_sha256"}
    return sha256_of_text(canonical_dumps(payload))


def verify_receipt_chain(records: list[dict[str, Any]]) -> list[str]:
    """Verify the append-only receipt chain. One changed field breaks the run."""
    problems: list[str] = []
    previous = "0" * 64
    for line_number, record in enumerate(records, start=1):
        if record.get("previous_receipt_sha256") != previous:
            problems.append(f"receipt chain predecessor mismatch at line {line_number}")
        expected = _receipt_hash(record)
        actual = str(record.get("receipt_sha256", ""))
        if actual != expected:
            problems.append(f"receipt content hash mismatch at line {line_number}")
        previous = actual
    return problems


def append_receipt(receipts_path: str | Path, receipt: IngestionReceipt) -> Path:
    p = Path(receipts_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = load_receipts(p)
    chain_problems = verify_receipt_chain(existing)
    if chain_problems:
        raise ValueError("cannot append to a broken receipt chain: " + "; ".join(chain_problems))
    previous = str(existing[-1]["receipt_sha256"]) if existing else "0" * 64
    record = {
        **receipt.to_dict(),
        "previous_receipt_sha256": previous,
    }
    record["receipt_sha256"] = _receipt_hash(record)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
        handle.flush()
        import os

        os.fsync(handle.fileno())
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


def rebuild_normalized_rows(record: dict[str, Any], raw: bytes) -> list[dict[str, Any]]:
    """Reparse raw bytes with the receipt-bound adapter and request identity."""
    adapter = str(record.get("adapter_name", ""))
    params = record.get("request_parameters", {})
    if not isinstance(params, dict):
        raise ValueError("receipt request_parameters must be an object")
    symbol = str(params.get("symbol", "")).upper()
    captured = str(record.get("captured_at_utc", ""))
    source_name = str(params.get("source_name", ""))
    if adapter == "evidence.json.identity":
        import json

        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
            return payload
        raise ValueError("identity JSON adapter requires an object or list of objects")
    if adapter.startswith("carry.backfill."):
        venue = adapter.rsplit(".", 1)[-1]
        from quant_trade.carry.backfill import (
            parse_bybit_funding_history,
            parse_okx_funding_history,
        )

        parsers = {
            "bybit": parse_bybit_funding_history,
            "okx": parse_okx_funding_history,
        }
        if venue not in parsers or not symbol or not source_name:
            raise ValueError("receipt is missing a supported venue, symbol, or source_name")
        return [
            row.to_dict()
            for row in parsers[venue](
                raw,
                symbol=symbol,
                captured_at_utc=captured,
                source_name=source_name,
            )
        ]
    if adapter == "carry.panel_backfill.bybit":
        kind = str(params.get("kind", ""))
        if not symbol:
            raise ValueError("panel receipt is missing symbol identity")
        if kind == "funding":
            from quant_trade.carry.backfill import parse_bybit_funding_history

            if not source_name:
                raise ValueError("panel funding receipt is missing source_name")
            return [
                row.to_dict()
                for row in parse_bybit_funding_history(
                    raw,
                    symbol=symbol,
                    captured_at_utc=captured,
                    source_name=source_name,
                )
            ]
        from quant_trade.carry.panel import parse_bybit_kline_page

        return parse_bybit_kline_page(raw, symbol=symbol, kind=kind)
    if adapter.startswith("v8.backfill."):
        # v8.backfill.<venue>.<kind>. The V8 parsers are pure and identify the
        # instrument from the receipt's own request parameters, so a rebuild
        # never has to guess what was requested.
        from quant_trade.v8.venues import parse_instruments, series_spec

        _, _, venue, kind = adapter.split(".", 3)
        instrument = str(params.get("instrument", "")) or symbol
        if not instrument:
            raise ValueError("v8 receipt is missing its instrument identity")
        if kind == "instruments":
            return parse_instruments(venue, raw, symbol=instrument)
        if kind == "server_time":
            return []
        return series_spec(venue, kind).parse(raw, symbol=instrument, kind=kind)
    raise ValueError(f"unsupported receipt adapter {adapter!r}")


def verify_receipt_bytes(record: dict[str, Any], *, base_dir: Path) -> list[str]:
    """Recompute raw and normalized hashes. Empty list means byte-verified."""
    from quant_trade.evidence.canonical_json import sha256_of_file

    problems: list[str] = []
    raw_path = Path(str(record.get("raw_path", "")))
    if raw_path.is_absolute():
        return ["raw_path must be relative to the receipts file"]
    root = base_dir.resolve()
    raw_path = (root / raw_path).resolve()
    try:
        raw_path.relative_to(root)
    except ValueError:
        return ["raw_path escapes the receipts directory (path traversal rejected)"]
    if not raw_path.exists():
        return [f"raw payload missing on disk: {raw_path}"]
    actual = sha256_of_file(raw_path)
    if actual != str(record.get("raw_sha256", "")):
        problems.append(
            f"raw payload bytes do not hash to the receipt's raw_sha256 ({raw_path.name})"
        )
        return problems
    try:
        rows = rebuild_normalized_rows(record, raw_path.read_bytes())
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"raw payload cannot be deterministically reparsed: {exc}")
        return problems
    actual_normalized = normalized_rows_sha256(rows)
    expected_normalized = str(record.get("normalized_rows_sha256", ""))
    if actual_normalized != expected_normalized:
        problems.append("normalized rows do not hash to the receipt's normalized_rows_sha256")
    return problems


@dataclass
class ProvenanceReport:
    provenance: str  # "real" | "test_only" | "unverified_legacy" | "mixed" | "invalid"
    records_total: int = 0
    records_real: int = 0
    records_test_only: int = 0
    records_unverified: int = 0
    records_invalid: int = 0
    evidence_classes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_dir_provenance(
    receipts_path: str | Path, *, base_dir: str | Path | None = None
) -> ProvenanceReport:
    """Provenance of a derived artifact directory from its page receipts.

    Every receipt is one evidence unit: all verified-live → real; any fixture/
    recorded → test_only (or mixed); any broken raw → invalid; none → the
    directory is unverified_legacy.
    """
    records = [{"raw_sha256": str(r.get("raw_sha256", ""))} for r in load_receipts(receipts_path)]
    if not records:
        return ProvenanceReport(provenance="unverified_legacy")
    return resolve_provenance(records, receipts_path, base_dir=base_dir)


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
    receipts = load_receipts(receipts_file)
    chain_problems = verify_receipt_chain(receipts)
    for receipt in receipts:
        sha = str(receipt.get("raw_sha256", ""))
        problems = list(chain_problems)
        problems.extend(verify_receipt_bytes(receipt, base_dir=base))
        if problems:
            broken[sha] = "; ".join(problems)
        else:
            verified[sha] = str(receipt.get("source_kind", "unknown"))
    report_evidence_classes = sorted(
        {
            str(SOURCE_KIND_EVIDENCE_CLASS.get(str(receipt.get("source_kind", "unknown"))))
            for receipt in receipts
        }
    )

    report = ProvenanceReport(
        provenance="unverified_legacy",
        records_total=len(records),
        evidence_classes=report_evidence_classes,
    )
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
        report.problems.append("records mix receipt-verified and unverified/test provenance")
    elif kinds:
        report.provenance = kinds.pop()
    return report
