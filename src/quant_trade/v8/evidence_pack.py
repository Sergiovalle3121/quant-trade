"""Content-addressed, verifiable evidence packs.

V7 ended with `REAL_LOCAL_UNCOMMITTED`: a real capture existed on one machine
and nowhere else, so nobody could re-derive its numbers. A claim that cannot
be re-derived is not evidence, whatever it says about itself.

An evidence pack fixes that by making the *bytes* the unit of exchange:

* every file is listed in a manifest with its SHA-256 and size;
* the manifest carries a Merkle root over ``(path, sha256)`` pairs, so a
  single altered byte anywhere changes one short string;
* the archive itself is written **deterministically** — sorted entries, zeroed
  mtimes/uids/modes, gzip without a timestamp — so building the same evidence
  twice produces the same archive bytes, and the archive is stored under its
  own SHA-256;
* verification is byte-for-byte and goes all the way back to raw: each
  archived response is re-parsed with the recorded parser version and must
  reproduce the receipt's ``normalized_rows_sha256``, then the whole series
  files are rebuilt from raw and compared byte-for-byte against the ones in
  the pack.

The manifest also records the exact command that rebuilds the pack, its total
size, and the redistribution policy under which the bytes were included —
because whether venue market data may be redistributed is a licensing
question, not a technical one, and the honest answer belongs next to the data.
"""

from __future__ import annotations

import gzip
import io
import json
import shutil
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_bytes,
    sha256_of_text,
)
from quant_trade.v8 import V8_SCHEMA_VERSION

PACK_SCHEMA_VERSION = 1
MANIFEST_NAME = "EVIDENCE_PACK_MANIFEST.json"

#: Files a pack carries from each evidence directory, in priority order. Only
#: research inputs — never credentials, never anything machine-specific.
PACKED_PATTERNS = (
    "raw/*.json",
    "series/*.jsonl",
    "panel/*",
    "receipts.jsonl",
    "pages_index.jsonl",
    "attempts.jsonl",
    "backfill_result.json",
    "instrument_metadata.json",
)

#: Redistribution stances a pack can declare. ``UNRESOLVED`` is the safe
#: default: it keeps the pack local and blocks committing raw bytes.
REDISTRIBUTION_STANCES = (
    "PERMITTED_DOCUMENTED",
    "PROHIBITED_DOCUMENTED",
    "UNRESOLVED",
)


@dataclass
class PackEntry:
    path: str  # POSIX, relative to the pack root
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackManifest:
    pack_id: str
    created_at_utc: str
    schema_version: int = PACK_SCHEMA_VERSION
    parser_schema_version: int = V8_SCHEMA_VERSION
    entries: list[PackEntry] = field(default_factory=list)
    merkle_root: str = ""
    total_bytes: int = 0
    archive_sha256: str = ""
    archive_bytes: int = 0
    archive_name: str = ""
    rebuild_command: str = ""
    redistribution: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [e.to_dict() for e in self.entries]
        payload["file_count"] = len(self.entries)
        return payload


def merkle_root(entries: list[PackEntry]) -> str:
    """Order-independent root over ``(path, sha256)`` pairs.

    Entries are sorted by path before hashing, so two packs built from the
    same bytes on different filesystems agree regardless of directory
    iteration order.
    """
    leaves = sorted(f"{e.path}\0{e.sha256}" for e in entries)
    return sha256_of_text("\n".join(leaves))


def _collect(source: Path, prefix: str) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for pattern in PACKED_PATTERNS:
        for path in sorted(source.glob(pattern)):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                found.append((f"{prefix}/{relative}", path))
    # deterministic and de-duplicated
    seen: dict[str, Path] = {}
    for name, path in found:
        seen.setdefault(name, path)
    return sorted(seen.items())


def _deterministic_tar_gz(members: list[tuple[str, bytes]]) -> bytes:
    """Byte-reproducible ``.tar.gz`` — no timestamps, no uid/gid, sorted."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in sorted(members):
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(payload))
    raw_tar = buffer.getvalue()
    compressed = io.BytesIO()
    # mtime=0 keeps the gzip header constant across builds.
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw_tar)
    return compressed.getvalue()


def build_evidence_pack(
    sources: Mapping[str, str | Path],
    out_dir: str | Path,
    *,
    pack_id: str,
    created_at_utc: str,
    rebuild_command: str,
    redistribution_stance: str = "UNRESOLVED",
    redistribution_reason: str = "",
    redistribution_source_terms: str = "",
    notes: list[str] | None = None,
) -> PackManifest:
    """Build a deterministic, content-addressed pack from evidence directories.

    ``sources`` maps a prefix (the directory name inside the pack) to a
    backfilled evidence directory. The same inputs always produce the same
    archive bytes and the same ``archive_sha256``.
    """
    if redistribution_stance not in REDISTRIBUTION_STANCES:
        raise ValueError(f"redistribution_stance must be one of {REDISTRIBUTION_STANCES}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    members: list[tuple[str, bytes]] = []
    entries: list[PackEntry] = []
    source_summaries: list[dict[str, Any]] = []
    for prefix in sorted(sources):
        source = Path(sources[prefix])
        if not source.exists():
            raise ValueError(f"evidence source {source} does not exist")
        collected = _collect(source, prefix)
        subtotal = 0
        for name, path in collected:
            payload = path.read_bytes()
            members.append((name, payload))
            entries.append(
                PackEntry(path=name, sha256=sha256_of_bytes(payload), bytes=len(payload))
            )
            subtotal += len(payload)
        source_summaries.append(
            {
                "prefix": prefix,
                "source_dir": str(source),
                "files": len(collected),
                "bytes": subtotal,
            }
        )

    manifest = PackManifest(
        pack_id=pack_id,
        created_at_utc=created_at_utc,
        entries=entries,
        merkle_root=merkle_root(entries),
        total_bytes=sum(e.bytes for e in entries),
        rebuild_command=rebuild_command,
        redistribution={
            "stance": redistribution_stance,
            "reason": redistribution_reason,
            "source_terms": redistribution_source_terms,
            "committable_to_git": redistribution_stance == "PERMITTED_DOCUMENTED",
        },
        sources=source_summaries,
        notes=list(notes or []),
    )

    archive = _deterministic_tar_gz(members)
    manifest.archive_sha256 = sha256_of_bytes(archive)
    manifest.archive_bytes = len(archive)
    manifest.archive_name = f"evidence-{pack_id}-{manifest.archive_sha256[:16]}.tar.gz"
    (out / manifest.archive_name).write_bytes(archive)
    atomic_write_json(out / MANIFEST_NAME, manifest.to_dict())
    return manifest


@dataclass
class PackVerification:
    pack_path: str
    manifest_path: str
    status: str  # "VERIFIED" | "CORRUPT" | "MISSING"
    files_checked: int = 0
    files_matched: int = 0
    archive_sha256_matches: bool = False
    merkle_root_matches: bool = False
    receipt_chains_verified: int = 0
    pages_reparsed: int = 0
    pages_reparse_mismatches: list[str] = field(default_factory=list)
    series_rebuilt: int = 0
    series_byte_mismatches: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def is_verified(self) -> bool:
        return self.status == "VERIFIED" and not self.problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_verified"] = self.is_verified
        return payload


def _extract(pack_path: Path, destination: Path) -> None:
    with gzip.open(pack_path, "rb") as gz:
        raw_tar = gz.read()
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                raise ValueError(f"pack contains a non-regular entry: {member.name}")
            target = (destination / member.name).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise ValueError(f"pack entry escapes the destination: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"pack entry has no content: {member.name}")
            target.write_bytes(extracted.read())


def _rebuild_series_from_raw(root: Path) -> tuple[int, list[str], int, list[str]]:
    """Re-parse every archived page and rebuild every series file from raw.

    Returns ``(pages_reparsed, page_mismatches, series_rebuilt, byte_mismatches)``.
    """
    from quant_trade.evidence.receipts import normalized_rows_sha256
    from quant_trade.v8.venues import SERIES_KINDS, series_spec

    receipts_path = root / "receipts.jsonl"
    if not receipts_path.exists():
        return 0, [f"{root.name}: no receipts.jsonl"], 0, []
    receipts = [
        json.loads(line)
        for line in receipts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    context_path = root / "backfill_result.json"
    context = load_json(context_path) if context_path.exists() else {}
    since_ms = int(context.get("since_ms", 0) or 0)
    until_ms = int(context.get("until_ms", 0) or 0)

    pages = 0
    page_mismatches: list[str] = []
    rebuilt: dict[str, dict[int, dict[str, Any]]] = {}
    for receipt in receipts:
        params = receipt.get("request_parameters", {}) or {}
        kind = str(params.get("kind", ""))
        venue = str(params.get("venue", receipt.get("provider_or_venue", "")))
        if kind not in SERIES_KINDS:
            continue
        raw_path = root / str(receipt.get("raw_path", ""))
        if not raw_path.exists():
            page_mismatches.append(f"missing raw page {receipt.get('raw_path')}")
            continue
        raw = raw_path.read_bytes()
        if sha256_of_bytes(raw) != str(receipt.get("raw_sha256", "")):
            page_mismatches.append(f"raw hash mismatch {receipt.get('raw_path')}")
            continue
        spec = series_spec(venue, kind)
        symbol = str(params.get("instrument", ""))
        try:
            rows = spec.parse(raw, symbol=symbol, kind=kind)
        except Exception as exc:  # noqa: BLE001 — a failed reparse IS the finding
            page_mismatches.append(
                f"reparse failed for {receipt.get('raw_path')}: {type(exc).__name__}: {exc}"
            )
            continue
        pages += 1
        if normalized_rows_sha256(rows) != str(receipt.get("normalized_rows_sha256", "")):
            page_mismatches.append(
                f"normalized rows differ for {receipt.get('raw_path')} "
                f"(parser {receipt.get('adapter_version')})"
            )
            continue
        stamp_field = spec.timestamp_field
        bucket = rebuilt.setdefault(kind, {})
        for row in rows:
            stamp = int(row[stamp_field])
            if until_ms and not since_ms <= stamp <= until_ms:
                continue
            bucket[stamp] = row

    series_rebuilt = 0
    byte_mismatches: list[str] = []
    for kind, bucket in sorted(rebuilt.items()):
        stored = root / "series" / f"{kind}.jsonl"
        if not stored.exists():
            byte_mismatches.append(f"{kind}: series file absent from pack")
            continue
        payload = "".join(canonical_dumps(bucket[k]) + "\n" for k in sorted(bucket))
        series_rebuilt += 1
        if payload.encode("utf-8") != stored.read_bytes():
            byte_mismatches.append(
                f"{kind}: series rebuilt from raw does not byte-match the packed file"
            )
    return pages, page_mismatches, series_rebuilt, byte_mismatches


def verify_evidence_pack(pack_path: str | Path, manifest_path: str | Path) -> PackVerification:
    """Verify a pack byte-for-byte, all the way back to the raw responses."""
    from quant_trade.evidence.receipts import verify_receipt_chain

    pack = Path(pack_path)
    manifest_file = Path(manifest_path)
    report = PackVerification(
        pack_path=str(pack), manifest_path=str(manifest_file), status="MISSING"
    )
    if not pack.exists():
        report.problems.append(f"pack archive not found: {pack}")
        return report
    if not manifest_file.exists():
        report.problems.append(f"pack manifest not found: {manifest_file}")
        return report

    manifest = load_json(manifest_file)
    if not isinstance(manifest, dict):
        report.problems.append("manifest is not a JSON object")
        report.status = "CORRUPT"
        return report

    archive_bytes = pack.read_bytes()
    report.archive_sha256_matches = sha256_of_bytes(archive_bytes) == str(
        manifest.get("archive_sha256", "")
    )
    if not report.archive_sha256_matches:
        report.problems.append("archive bytes do not match manifest archive_sha256")

    declared = {
        str(entry["path"]): (str(entry["sha256"]), int(entry["bytes"]))
        for entry in manifest.get("entries", [])
    }
    report.files_checked = len(declared)
    recomputed = [
        PackEntry(path=path, sha256=sha, bytes=size) for path, (sha, size) in declared.items()
    ]
    report.merkle_root_matches = merkle_root(recomputed) == str(manifest.get("merkle_root", ""))
    if not report.merkle_root_matches:
        report.problems.append("manifest merkle_root does not match its own entry list")

    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp)
        try:
            _extract(pack, destination)
        except (OSError, ValueError, tarfile.TarError) as exc:
            report.status = "CORRUPT"
            report.problems.append(f"extraction failed: {type(exc).__name__}: {exc}")
            return report

        extracted = {
            p.relative_to(destination).as_posix(): p
            for p in sorted(destination.rglob("*"))
            if p.is_file()
        }
        for path, (sha, size) in sorted(declared.items()):
            actual = extracted.get(path)
            if actual is None:
                report.problems.append(f"manifest lists {path}, absent from the archive")
                continue
            payload = actual.read_bytes()
            if sha256_of_bytes(payload) != sha or len(payload) != size:
                report.problems.append(f"content mismatch for {path}")
                continue
            report.files_matched += 1
        for path in sorted(set(extracted) - set(declared)):
            report.problems.append(f"archive carries {path}, absent from the manifest")

        for receipts_path in sorted(destination.rglob("receipts.jsonl")):
            records = [
                json.loads(line)
                for line in receipts_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            chain_problems = verify_receipt_chain(records)
            if chain_problems:
                report.problems.extend(f"{receipts_path.parent.name}: {p}" for p in chain_problems)
            else:
                report.receipt_chains_verified += 1

            pages, page_mismatches, series, byte_mismatches = _rebuild_series_from_raw(
                receipts_path.parent
            )
            report.pages_reparsed += pages
            report.pages_reparse_mismatches.extend(page_mismatches)
            report.series_rebuilt += series
            report.series_byte_mismatches.extend(byte_mismatches)

    report.problems.extend(report.pages_reparse_mismatches)
    report.problems.extend(report.series_byte_mismatches)
    report.status = "VERIFIED" if not report.problems else "CORRUPT"
    return report


def import_evidence_pack(
    pack_path: str | Path, manifest_path: str | Path, destination: str | Path
) -> PackVerification:
    """Verify a pack, then extract it. A failed verification imports nothing."""
    report = verify_evidence_pack(pack_path, manifest_path)
    if not report.is_verified:
        return report
    target = Path(destination)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    _extract(Path(pack_path), target)
    return report


__all__ = [
    "MANIFEST_NAME",
    "PACKED_PATTERNS",
    "PACK_SCHEMA_VERSION",
    "REDISTRIBUTION_STANCES",
    "PackEntry",
    "PackManifest",
    "PackVerification",
    "build_evidence_pack",
    "import_evidence_pack",
    "merkle_root",
    "verify_evidence_pack",
]
