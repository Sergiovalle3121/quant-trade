"""Hash-bound manifest and trust gate for a causal single-venue crypto panel."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)

DatasetStatus = Literal["TRUSTED_CAUSAL", "UNVALIDATED", "INVALID"]
MANIFEST_SCHEMA_VERSION = 1
TRUSTED_CAUSAL = "TRUSTED_CAUSAL"


class CryptoManifestError(ValueError):
    """Raised when provenance is incomplete or a trust claim is unsupported."""


@dataclass(frozen=True)
class CausalValidationEvidence:
    """The adversarial checks that must all pass before a panel is trusted."""

    prefix_invariance_passed: bool = False
    fixed_venue_passed: bool = False
    stable_identity_and_rename_passed: bool = False
    unique_and_ambiguous_price_binding_passed: bool = False
    causal_warmup_passed: bool = False
    rank_exit_reentry_passed: bool = False
    gap_and_halt_semantics_passed: bool = False
    explicit_delisting_semantics_passed: bool = False

    @property
    def passed(self) -> bool:
        return all(asdict(self).values())

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class CryptoDatasetManifest:
    dataset_id: str
    status: DatasetStatus
    venue: str
    market: str
    quote_asset: str
    timezone: str
    start_date: str
    end_date: str
    rows: int
    instruments: int
    schema_version: int
    code_commit: str
    policy: dict[str, Any]
    components: dict[str, str]
    component_provenance: dict[str, str]
    causal_validation: CausalValidationEvidence
    gap_summary: dict[str, Any]
    terms_status: str
    redistribution_allowed: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
    manifest_schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.manifest_schema_version != MANIFEST_SCHEMA_VERSION:
            raise CryptoManifestError(f"manifest_schema_version must be {MANIFEST_SCHEMA_VERSION}")
        if self.status not in {TRUSTED_CAUSAL, "UNVALIDATED", "INVALID"}:
            raise CryptoManifestError(f"unsupported dataset status {self.status!r}")
        if not self.dataset_id.strip():
            raise CryptoManifestError("dataset_id is required")
        if self.venue != "bybit" or self.market != "spot" or self.quote_asset != "USDT":
            raise CryptoManifestError("v1 manifest must be Bybit Spot USDT")
        if self.timezone != "UTC":
            raise CryptoManifestError("crypto panel timezone must be UTC")
        if self.end_date < self.start_date:
            raise CryptoManifestError("end_date must not precede start_date")
        if self.rows <= 0 or self.instruments <= 0:
            raise CryptoManifestError("rows and instruments must be positive")
        if self.schema_version < 2:
            raise CryptoManifestError("causal panel schema_version must be >= 2")
        if not re.fullmatch(r"[0-9a-f]{40}", self.code_commit):
            raise CryptoManifestError("code_commit must be a full lowercase Git SHA-1")
        if not self.policy:
            raise CryptoManifestError("the full panel policy is required")
        if not self.components:
            raise CryptoManifestError("component byte hashes are required")
        for name, digest in self.components.items():
            if not name.strip() or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise CryptoManifestError(f"invalid SHA-256 component {name!r}")
        if set(self.component_provenance) != set(self.components):
            raise CryptoManifestError(
                "component_provenance must name exactly every hashed component"
            )
        for name, provenance in self.component_provenance.items():
            _validate_provenance_path(name, provenance)
        if not isinstance(self.gap_summary, dict) or not self.gap_summary:
            raise CryptoManifestError("gap_summary is required")
        unexplained = self.gap_summary.get("unexplained")
        if isinstance(unexplained, bool) or not isinstance(unexplained, int) or unexplained < 0:
            raise CryptoManifestError("gap_summary.unexplained must be a non-negative integer")
        if self.status == TRUSTED_CAUSAL and unexplained != 0:
            raise CryptoManifestError("TRUSTED_CAUSAL requires zero unexplained gaps")
        if not isinstance(self.terms_status, str) or not self.terms_status.strip():
            raise CryptoManifestError("terms_status is required")
        if self.redistribution_allowed:
            raise CryptoManifestError(
                "market-data redistribution remains disabled until licenses are resolved"
            )
        if self.status == TRUSTED_CAUSAL and not self.causal_validation.passed:
            raise CryptoManifestError(
                "TRUSTED_CAUSAL requires every adversarial causal check to pass"
            )
        if self.status == "INVALID" and not self.notes:
            raise CryptoManifestError("an invalid dataset must state why")

    def sealed_content(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "digest": self.digest()}

    def require_trusted(self, action: str) -> None:
        if self.status != TRUSTED_CAUSAL or not self.causal_validation.passed:
            raise CryptoManifestError(
                f"dataset {self.dataset_id!r} is {self.status}; it cannot be used for "
                f"{action}. A TRUSTED_CAUSAL manifest with all adversarial checks is required."
            )


def component_hashes(paths: Mapping[str, str | Path]) -> dict[str, str]:
    """Hash exact bytes using stable logical names; missing bytes are fatal."""
    if not paths:
        raise CryptoManifestError("at least one component path is required")
    hashes: dict[str, str] = {}
    for name, raw_path in sorted(paths.items()):
        path = Path(raw_path)
        if not path.is_file():
            raise CryptoManifestError(f"component {name!r} is not a file: {path}")
        hashes[name] = sha256_of_file(path)
    return hashes


def _validate_provenance_path(name: str, raw_path: str) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path.strip() or raw_path != raw_path.strip():
        raise CryptoManifestError(f"component provenance for {name!r} must be a relative path")
    if "\\" in raw_path:
        raise CryptoManifestError(f"component provenance for {name!r} must use POSIX separators")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        raise CryptoManifestError(
            f"component provenance for {name!r} must stay beneath the provenance root"
        )
    return path


def provenance_paths(
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
) -> dict[str, Path]:
    """Resolve sealed, portable provenance paths beneath an explicit root."""
    root = Path(provenance_root).resolve()
    paths: dict[str, Path] = {}
    for name, raw_path in sorted(manifest.component_provenance.items()):
        relative = _validate_provenance_path(name, raw_path)
        path = root.joinpath(*relative.parts).resolve()
        if path != root and root not in path.parents:
            raise CryptoManifestError(
                f"component provenance for {name!r} escapes the provenance root"
            )
        paths[name] = path
    return paths


def verify_component_bytes(
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
) -> dict[str, str]:
    """Rehash every sealed component before trusted bytes are consumed."""
    observed = component_hashes(provenance_paths(manifest, provenance_root))
    if observed != manifest.components:
        mismatched = sorted(
            name
            for name in set(observed) | set(manifest.components)
            if observed.get(name) != manifest.components.get(name)
        )
        raise CryptoManifestError(f"component byte hash mismatch: {mismatched}")
    return observed


def load_manifest(
    path: str | Path,
    *,
    provenance_root: str | Path | None = None,
) -> CryptoDatasetManifest:
    """Load a manifest and re-derive both its digest and every component hash."""
    source = Path(path)
    payload = load_json(source)
    if not isinstance(payload, dict):
        raise CryptoManifestError(f"manifest at {source} must be a JSON object")

    known = {item.name for item in fields(CryptoDatasetManifest)}
    unknown = set(payload) - known - {"digest"}
    missing = known - set(payload)
    if unknown:
        raise CryptoManifestError(f"unknown manifest fields: {sorted(unknown)}")
    if missing:
        raise CryptoManifestError(f"missing manifest fields: {sorted(missing)}")
    claimed_digest = payload.get("digest")
    if not isinstance(claimed_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed_digest):
        raise CryptoManifestError("embedded manifest digest must be a lowercase SHA-256")

    validation_payload = payload.get("causal_validation")
    if not isinstance(validation_payload, dict):
        raise CryptoManifestError("causal_validation must be a JSON object")
    validation_names = {item.name for item in fields(CausalValidationEvidence)}
    if set(validation_payload) != validation_names:
        raise CryptoManifestError("causal_validation must contain exactly every required check")
    if any(type(value) is not bool for value in validation_payload.values()):
        raise CryptoManifestError("causal_validation values must be booleans")

    raw_manifest = {key: value for key, value in payload.items() if key in known}
    notes = raw_manifest.get("notes")
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise CryptoManifestError("notes must be a JSON array of strings")
    raw_manifest["notes"] = tuple(notes)
    raw_manifest["causal_validation"] = CausalValidationEvidence(**validation_payload)
    for name in ("policy", "components", "component_provenance", "gap_summary"):
        if not isinstance(raw_manifest.get(name), dict):
            raise CryptoManifestError(f"{name} must be a JSON object")
    try:
        manifest = CryptoDatasetManifest(**raw_manifest)
    except TypeError as exc:
        raise CryptoManifestError(f"malformed manifest at {source}: {exc}") from exc

    actual_digest = manifest.digest()
    if not hmac.compare_digest(claimed_digest, actual_digest):
        raise CryptoManifestError(
            f"manifest digest mismatch at {source}: stored {claimed_digest[:12]}..., "
            f"content hashes to {actual_digest[:12]}..."
        )

    root = source.parent if provenance_root is None else provenance_root
    verify_component_bytes(manifest, root)
    return manifest


def write_manifest(
    path: str | Path,
    manifest: CryptoDatasetManifest,
    *,
    overwrite: bool = False,
) -> Path:
    """Write canonical evidence; replacement requires an explicit new version."""
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise CryptoManifestError(
            f"manifest already exists at {destination}; use a new dataset_id/version"
        )
    return atomic_write_json(destination, manifest.to_dict())


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "TRUSTED_CAUSAL",
    "CausalValidationEvidence",
    "CryptoDatasetManifest",
    "CryptoManifestError",
    "component_hashes",
    "load_manifest",
    "provenance_paths",
    "verify_component_bytes",
    "write_manifest",
]
