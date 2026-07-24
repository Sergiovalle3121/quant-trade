"""Byte-bound dataset manifests: evidence is chained to the exact data it used.

A :class:`DatasetManifest` records the SHA-256 of the dataset's real bytes plus
enough structure (rows, time range, symbols, venues, schema) to detect
substitution, truncation, or mixing. ``verify_dataset_manifest`` re-hashes the
file at decision time, so results produced from one dataset can never be
promoted against another — same path, different bytes, different manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DatasetManifest:
    schema_version: int
    path: str
    byte_sha256: str
    size_bytes: int
    rows: int
    time_range_start: str
    time_range_end: str
    symbols: tuple[str, ...]
    venues: tuple[str, ...]
    record_schema: tuple[str, ...]
    data_source: str  # "real" | "synthetic" | "mixed"
    source_name: str
    captured_at_utc: str
    provenance_notes: str = ""

    @property
    def manifest_hash(self) -> str:
        """Content hash of the manifest itself (stable across serialization)."""
        return sha256_of_text(canonical_dumps(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "manifest_hash": self.manifest_hash}


@dataclass
class ManifestVerification:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems)}


def _snapshot_records(payload: Any) -> list[dict[str, Any]]:
    records = payload.get("snapshots") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not records:
        raise ValueError("dataset must contain a non-empty list of records")
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("dataset records must be objects")
    return records


def build_file_manifest(
    path: str | Path,
    records: list[dict[str, Any]],
    *,
    timestamp_field: str = "captured_at_utc",
    symbol_field: str = "symbol",
    venue_field: str = "exchange",
    source_field: str = "data_source",
    provenance_notes: str = "",
) -> DatasetManifest:
    """Manifest for pre-parsed records whose bytes live at ``path``.

    The byte hash always covers the file's REAL bytes; the structural fields
    come from the caller-parsed records (JSON list, JSONL bridge, etc.).
    """
    p = Path(path)
    raw = p.read_bytes()
    if not records:
        raise ValueError("cannot build a manifest for zero records")
    timestamps = sorted(str(r.get(timestamp_field, "")) for r in records)
    symbols = tuple(sorted({str(r.get(symbol_field, "")) for r in records}))
    venues = tuple(sorted({str(r.get(venue_field, "")) for r in records}))
    sources = {str(r.get(source_field, "synthetic")) for r in records}
    data_source = sources.pop() if len(sources) == 1 else "mixed"
    schema = tuple(sorted({key for r in records for key in r}))
    source_names = {str(r.get("source_name", "")) for r in records}
    return DatasetManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        path=str(p),
        byte_sha256=sha256_of_file(p),
        size_bytes=len(raw),
        rows=len(records),
        time_range_start=timestamps[0],
        time_range_end=timestamps[-1],
        symbols=symbols,
        venues=venues,
        record_schema=schema,
        data_source=data_source,
        source_name=", ".join(sorted(n for n in source_names if n)) or "unknown",
        captured_at_utc=timestamps[-1],
        provenance_notes=provenance_notes,
    )


def build_dataset_manifest(
    path: str | Path,
    *,
    timestamp_field: str = "captured_at_utc",
    symbol_field: str = "symbol",
    venue_field: str = "exchange",
    source_field: str = "data_source",
    provenance_notes: str = "",
) -> DatasetManifest:
    """Read a JSON dataset file's REAL BYTES and derive the manifest from them."""
    p = Path(path)
    payload = load_json(p)
    records = _snapshot_records(payload)
    return build_file_manifest(
        p,
        records,
        timestamp_field=timestamp_field,
        symbol_field=symbol_field,
        venue_field=venue_field,
        source_field=source_field,
        provenance_notes=provenance_notes,
    )


def build_inline_manifest(
    records: list[dict[str, Any]],
    *,
    data_source: str,
    source_name: str,
    provenance_notes: str = "",
) -> DatasetManifest:
    """Manifest for in-memory (e.g. synthetic) data: hash of canonical content.

    There is no file, so the byte hash is the hash of the canonical JSON of the
    records — still deterministic and still able to distinguish two different
    generated datasets.
    """
    if not records:
        raise ValueError("cannot build a manifest for zero records")
    canonical = canonical_dumps(records)
    timestamps = sorted(str(r.get("captured_at_utc", "")) for r in records)
    return DatasetManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        path="<inline>",
        byte_sha256=sha256_of_text(canonical),
        size_bytes=len(canonical.encode("utf-8")),
        rows=len(records),
        time_range_start=timestamps[0],
        time_range_end=timestamps[-1],
        symbols=tuple(sorted({str(r.get("symbol", "")) for r in records})),
        venues=tuple(sorted({str(r.get("exchange", "")) for r in records})),
        record_schema=tuple(sorted({key for r in records for key in r})),
        data_source=data_source,
        source_name=source_name,
        captured_at_utc=timestamps[-1],
        provenance_notes=provenance_notes,
    )


def verify_dataset_manifest(
    manifest: DatasetManifest | dict[str, Any], path: str | Path | None = None
) -> ManifestVerification:
    """Re-hash the dataset now and compare against the manifest (fail closed)."""
    m = manifest if isinstance(manifest, dict) else manifest.to_dict()
    problems: list[str] = []
    target = Path(path) if path is not None else Path(str(m.get("path", "")))
    if str(m.get("path")) == "<inline>":
        problems.append("inline manifest cannot be re-verified against a file")
        return ManifestVerification(ok=False, problems=problems)
    if not target.exists():
        problems.append(f"dataset file missing: {target}")
        return ManifestVerification(ok=False, problems=problems)
    actual_sha = sha256_of_file(target)
    if actual_sha != m.get("byte_sha256"):
        problems.append(
            "dataset bytes changed since the manifest was produced "
            f"(manifest {str(m.get('byte_sha256'))[:12]}…, file {actual_sha[:12]}…)"
        )
    actual_size = target.stat().st_size
    if int(m.get("size_bytes", -1)) != actual_size:
        problems.append("dataset size differs from manifest")
    return ManifestVerification(ok=not problems, problems=problems)


def migrate_yaml_results_to_json(path: str | Path) -> Path:
    """Explicit migrator for pre-V4 results.json files that were written as YAML.

    This is deliberately NOT a permissive fallback in readers: old artifacts are
    converted once, on purpose, by calling this. Raises if the file is already
    valid JSON (nothing to migrate) or not parseable YAML.
    """
    import json as _json

    import yaml as _yaml

    from quant_trade.evidence.canonical_json import atomic_write_json

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        _json.loads(text)
    except _json.JSONDecodeError:
        pass
    else:
        raise ValueError(f"{p} is already valid JSON; nothing to migrate")
    payload = _yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{p} is not a mapping; refusing to migrate")
    return atomic_write_json(p, payload)
