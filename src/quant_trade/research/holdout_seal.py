"""A holdout seal that survives the process that created it.

`v8.holdout.HoldoutGuard` makes the holdout unreachable *within one process*.
That is the right guard for a single campaign and the wrong one for a research
programme that spans sessions, machines and CI runs: nothing in a Python object
stops the next session from slicing the same dates by hand, and "we kept a
holdout" becomes unfalsifiable again the moment the interpreter exits.

This is the durable half. Before any signal is computed, a declaration states
which dates are reserved and — the part that does the real work — *which bytes*
the reservation was made against. Both are hashed together. Afterwards:

- the seal cannot be rewritten (``seal_holdout`` refuses an existing file);
- the seal cannot be re-derived from different data (``verify_against_dataset``
  recomputes the dataset digest and compares);
- a research-side date range can be checked against the boundary
  (``assert_within_selection``) so touching reserved dates raises instead of
  quietly producing a better number;
- the reveal is recorded once, with a reason, in an append-only log, and a
  second reveal raises.

Binding to a dataset digest is what makes the rest mean anything. A seal that
named only dates would still be satisfied by a dataset rebuilt, re-collected or
silently corrected after the fact — and "we sealed the last 30%" of a panel
that changed underneath is a statement about nothing. The digest is computed
over the collector's own per-file hashes rather than over gigabytes of bars, so
committing to the full content stays cheap enough to do honestly.

pandas-free.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.data.crypto_manifest import (
    TRUSTED_CAUSAL,
    CryptoDatasetManifest,
    component_hashes,
    provenance_paths,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)
from quant_trade.ops.crypto_gates import Gate0Verdict, require_gate0_passed

SCHEMA_VERSION = 1

#: Filename a sealed holdout is written under inside an experiment directory.
SEAL_FILENAME = "holdout_seal.json"
#: Append-only reveal log. Separate from the seal so recording a reveal can
#: never rewrite the declaration it is a reveal of.
REVEAL_LOG_FILENAME = "holdout_reveals.jsonl"
#: A separate append-only historical fact: the named dataset was later found
#: unsuitable for economic inference.  The original seal remains readable,
#: but it can never be revealed or used to create a replacement seal.
INVALIDATION_FILENAME = "INVALIDATION.json"
#: Nested, independently hashed authorization used only by the protected
#: crypto sealing entry point. Legacy non-crypto seals remain unchanged.
CRYPTO_AUTHORIZATION_FIELD = "crypto_authorization"

#: Fields that constitute the declaration. Anything outside this set is
#: metadata and stays out of the hash.
SEALED_FIELDS = (
    "seal_id",
    "dataset_id",
    "dataset_digest",
    "selection_start",
    "selection_end",
    "holdout_start",
    "holdout_end",
    "rationale",
    "sealed_at_utc",
    "sealed_at_commit",
    "schema_version",
)


class HoldoutSealError(RuntimeError):
    """Raised when a seal is malformed, contradicted, or read out of order."""


def load_invalidation(directory: str | Path) -> dict[str, Any] | None:
    """Load a dataset invalidation without mutating the historical seal."""
    path = Path(directory) / INVALIDATION_FILENAME
    if not path.exists():
        return None
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise HoldoutSealError(f"dataset invalidation at {path} must be a JSON object")
    claimed = str(payload.get("seal", ""))
    actual = invalidation_seal(payload)
    if not claimed or claimed != actual:
        raise HoldoutSealError(
            f"dataset invalidation seal mismatch at {path}: stored {claimed[:12]}..., "
            f"content hashes to {actual[:12]}..."
        )
    invalid_digest = payload.get("dataset_digest")
    if not _is_sha256(invalid_digest):
        raise HoldoutSealError("dataset invalidation must name a SHA-256 dataset_digest")
    superseded = payload.get("superseded_dataset_digests", [])
    if not isinstance(superseded, list) or any(not _is_sha256(item) for item in superseded):
        raise HoldoutSealError("superseded_dataset_digests must be a list of SHA-256 digests")
    if len(set(superseded)) != len(superseded):
        raise HoldoutSealError("superseded_dataset_digests contains duplicates")
    _validate_invalidated_artifacts(Path(directory), payload)
    return payload


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_invalidated_artifacts(directory: Path, payload: dict[str, Any]) -> None:
    """Verify every historical artifact explicitly named by an invalidation."""
    artifacts = payload.get("invalidated_artifacts")
    if artifacts is None:
        return
    if not isinstance(artifacts, dict):
        raise HoldoutSealError("invalidated_artifacts must be a JSON object")
    invalid_digests = {
        str(payload["dataset_digest"]),
        *(str(item) for item in payload.get("superseded_dataset_digests", [])),
    }

    expected_holdout = artifacts.get("holdout_seal")
    if expected_holdout is not None:
        if not _is_sha256(expected_holdout):
            raise HoldoutSealError("invalidated holdout_seal must be a SHA-256 digest")
        holdout_path = directory / SEAL_FILENAME
        if not holdout_path.is_file():
            raise HoldoutSealError(f"invalidated holdout artifact is missing: {holdout_path}")
        loaded = load_seal(directory)
        if loaded.seal() != expected_holdout:
            raise HoldoutSealError(
                "invalidated holdout artifact does not match its declared digest"
            )
        if loaded.dataset_digest not in invalid_digests:
            raise HoldoutSealError(
                "invalidated holdout artifact does not bind an invalidated dataset digest"
            )

    preregistrations = artifacts.get("experiment_preregistrations", [])
    if not isinstance(preregistrations, list) or any(
        not isinstance(item, str) or not item.strip() for item in preregistrations
    ):
        raise HoldoutSealError("invalidated experiment_preregistrations must be identifiers")
    if len(set(preregistrations)) != len(preregistrations):
        raise HoldoutSealError("invalidated experiment_preregistrations contains duplicates")
    if preregistrations:
        from quant_trade.research.preregistration import (
            PreregistrationError,
            load_preregistration,
        )

        for experiment_id in preregistrations:
            experiment_directory = directory / experiment_id
            try:
                registration = load_preregistration(experiment_directory)
            except PreregistrationError as exc:
                raise HoldoutSealError(
                    f"invalidated preregistration artifact is missing or corrupt: {experiment_id}"
                ) from exc
            if registration.experiment_id != experiment_id:
                raise HoldoutSealError(
                    f"invalidated preregistration identity mismatch: {experiment_id}"
                )
            if not any(
                digest in universe_member
                for digest in invalid_digests
                for universe_member in registration.universe
            ):
                raise HoldoutSealError(
                    f"invalidated preregistration does not bind an invalidated digest: "
                    f"{experiment_id}"
                )


def invalidation_seal(payload: dict[str, Any]) -> str:
    """Hash all invalidation fields except the hash itself."""
    content = {key: value for key, value in payload.items() if key != "seal"}
    return sha256_of_text(canonical_dumps(content))


def assert_dataset_not_invalidated(directory: str | Path, digest: str) -> None:
    """Fail closed if ``digest`` is named by the directory's invalidation."""
    invalidation = load_invalidation(directory)
    if invalidation is None:
        return
    invalid_digests = {
        str(invalidation["dataset_digest"]),
        *(str(item) for item in invalidation.get("superseded_dataset_digests", [])),
    }
    if digest in invalid_digests:
        reasons = invalidation.get("reasons") or ["unspecified integrity failure"]
        raise HoldoutSealError(
            f"dataset {digest[:12]}... is {invalidation.get('status', 'INVALID')}: "
            f"{'; '.join(str(reason) for reason in reasons)}. The historical seal "
            "is retained for traceability but is not usable or revealable."
        )


def dataset_digest(components: dict[str, str]) -> str:
    """Commit to a dataset's full content via its per-file digests.

    ``components`` maps a stable member name (a date, a symbol) to that
    member's content hash — exactly what the collectors already journal. The
    result changes if any member changes, appears or disappears, which is the
    whole requirement; hashing the underlying gigabytes would add cost without
    adding commitment.
    """
    if not components:
        raise HoldoutSealError(
            "refusing to digest an empty dataset: a seal bound to nothing constrains nothing"
        )
    return sha256_of_text(canonical_dumps(dict(sorted(components.items()))))


@dataclass(frozen=True)
class HoldoutSeal:
    """What is reserved, and what it was reserved against."""

    seal_id: str
    dataset_id: str
    dataset_digest: str
    selection_start: str
    selection_end: str
    holdout_start: str
    holdout_end: str
    rationale: str
    sealed_at_utc: str
    sealed_at_commit: str = ""
    schema_version: int = SCHEMA_VERSION
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("seal_id", "dataset_id", "dataset_digest", "sealed_at_utc"):
            if not str(getattr(self, name)).strip():
                raise HoldoutSealError(f"{name} is required")
        if not self.rationale.strip():
            raise HoldoutSealError(
                "rationale is required: a split chosen without a stated reason "
                "can be re-chosen after seeing results"
            )
        if self.selection_end < self.selection_start:
            raise HoldoutSealError("selection_end must not precede selection_start")
        if self.holdout_end < self.holdout_start:
            raise HoldoutSealError("holdout_end must not precede holdout_start")
        if self.holdout_start <= self.selection_end:
            raise HoldoutSealError(
                f"holdout_start {self.holdout_start} does not follow selection_end "
                f"{self.selection_end}; overlapping sections are not a holdout"
            )

    def sealed_content(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: payload[key] for key in SEALED_FIELDS}

    def seal(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "seal": self.seal()}

    def covers_selection(self, day: str) -> bool:
        return self.selection_start <= day <= self.selection_end

    def covers_holdout(self, day: str) -> bool:
        return self.holdout_start <= day <= self.holdout_end


@dataclass(frozen=True)
class CryptoHoldoutAuthorization:
    """Hash-bound proof that the protected crypto sealing prerequisites passed."""

    dataset_id: str
    manifest_status: str
    manifest_digest: str
    gate0_status: str
    gate0_verdict_digest: str
    gate0_evidence_digest: str
    holdout_seal_digest: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise HoldoutSealError("crypto holdout dataset_id is required")
        if self.manifest_status != TRUSTED_CAUSAL:
            raise HoldoutSealError("crypto holdout manifest_status must be TRUSTED_CAUSAL")
        if self.gate0_status != "PASS":
            raise HoldoutSealError("crypto holdout gate0_status must be PASS")
        for name in (
            "manifest_digest",
            "gate0_verdict_digest",
            "gate0_evidence_digest",
            "holdout_seal_digest",
        ):
            if not _is_sha256(getattr(self, name)):
                raise HoldoutSealError(f"crypto holdout {name} must be a SHA-256 digest")
        if self.schema_version != 1:
            raise HoldoutSealError("unsupported crypto holdout authorization schema")

    def sealed_content(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.sealed_content(), "digest": self.digest()}


def _is_crypto_seal(seal: HoldoutSeal) -> bool:
    return seal.dataset_id.lower().startswith("crypto") or seal.seal_id.lower().startswith("crypto")


def _write_holdout_seal(
    directory: str | Path,
    seal: HoldoutSeal,
    *,
    crypto_authorization: CryptoHoldoutAuthorization | None = None,
) -> tuple[Path, str]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    assert_dataset_not_invalidated(out, seal.dataset_digest)
    path = out / SEAL_FILENAME
    if path.exists():
        raise HoldoutSealError(
            f"{path} already exists; a sealed holdout is never rewritten. "
            "Seal a new seal_id against a new dataset instead."
        )
    payload = seal.to_dict()
    if crypto_authorization is not None:
        payload[CRYPTO_AUTHORIZATION_FIELD] = crypto_authorization.to_dict()
    atomic_write_json(path, payload)
    return path, str(payload["seal"])


def seal_holdout(directory: str | Path, seal: HoldoutSeal) -> tuple[Path, str]:
    """Write a declaration and return its path and digest.

    Refuses to overwrite: a holdout that can be re-declared after the run is
    decoration, and making that a filesystem-level guarantee costs one
    existence check.
    """
    if _is_crypto_seal(seal):
        raise HoldoutSealError(
            "legacy seal_holdout is blocked for crypto; use seal_crypto_holdout with "
            "verified manifest and Gate 0 bindings"
        )
    return _write_holdout_seal(directory, seal)


def seal_crypto_holdout(
    directory: str | Path,
    seal: HoldoutSeal,
    *,
    manifest: CryptoDatasetManifest,
    provenance_root: str | Path,
    manifest_digest: str,
    gate0_verdict: Gate0Verdict,
    gate0_verdict_digest: str,
    gate0_evidence_digest: str,
) -> tuple[Path, str]:
    """Protected crypto entry: bind verified causal bytes and exact Gate 0 evidence."""
    if not _is_crypto_seal(seal):
        raise HoldoutSealError("seal_crypto_holdout only accepts crypto dataset identities")
    try:
        manifest.require_trusted("holdout_seal")
        require_gate0_passed(gate0_verdict, "holdout_seal")
    except (ValueError, RuntimeError) as exc:
        raise HoldoutSealError(str(exc)) from exc

    actual_manifest_digest = manifest.digest()
    if manifest_digest != actual_manifest_digest:
        raise HoldoutSealError("provided manifest_digest does not match the manifest")
    if seal.dataset_id != manifest.dataset_id:
        raise HoldoutSealError("holdout dataset_id does not match the causal manifest")
    if seal.dataset_digest != actual_manifest_digest:
        raise HoldoutSealError("holdout dataset_digest must equal the causal manifest digest")
    try:
        observed_components = component_hashes(provenance_paths(manifest, provenance_root))
    except ValueError as exc:
        raise HoldoutSealError(str(exc)) from exc
    if observed_components != manifest.components:
        raise HoldoutSealError("causal manifest component bytes do not match at holdout sealing")
    if gate0_verdict_digest != gate0_verdict.digest():
        raise HoldoutSealError("provided Gate 0 verdict digest does not match the exact verdict")
    if gate0_evidence_digest != gate0_verdict.evidence_digest():
        raise HoldoutSealError("provided Gate 0 evidence digest does not match the exact evidence")

    authorization = CryptoHoldoutAuthorization(
        dataset_id=manifest.dataset_id,
        manifest_status=manifest.status,
        manifest_digest=actual_manifest_digest,
        gate0_status=gate0_verdict.status,
        gate0_verdict_digest=gate0_verdict_digest,
        gate0_evidence_digest=gate0_evidence_digest,
        holdout_seal_digest=seal.seal(),
    )
    return _write_holdout_seal(directory, seal, crypto_authorization=authorization)


def load_seal(directory: str | Path) -> HoldoutSeal:
    """Read a seal back, re-deriving its digest from the stored content."""
    path = Path(directory) / SEAL_FILENAME
    if not path.exists():
        raise HoldoutSealError(f"no sealed holdout at {path}")
    payload = load_json(path)
    claimed = str(payload.get("seal", ""))
    known = {f.name for f in HoldoutSeal.__dataclass_fields__.values()}
    seal = HoldoutSeal(**{k: v for k, v in payload.items() if k in known})
    actual = seal.seal()
    if not claimed or claimed != actual:
        raise HoldoutSealError(
            f"holdout seal mismatch at {path}: stored {claimed[:12]}..., content "
            f"hashes to {actual[:12]}.... The declaration was edited after sealing."
        )
    return seal


def load_crypto_holdout_authorization(directory: str | Path) -> CryptoHoldoutAuthorization:
    """Verify the nested crypto prerequisite binding and its holdout linkage."""
    path = Path(directory) / SEAL_FILENAME
    if not path.exists():
        raise HoldoutSealError(f"no sealed holdout at {path}")
    payload = load_json(path)
    raw = payload.get(CRYPTO_AUTHORIZATION_FIELD)
    if not isinstance(raw, dict):
        raise HoldoutSealError("crypto holdout lacks protected manifest and Gate 0 authorization")
    known = {item.name for item in CryptoHoldoutAuthorization.__dataclass_fields__.values()}
    unknown = set(raw) - known - {"digest"}
    missing = known - set(raw)
    if unknown or missing:
        raise HoldoutSealError(
            f"malformed crypto holdout authorization; unknown={sorted(unknown)}, "
            f"missing={sorted(missing)}"
        )
    claimed = raw.get("digest")
    authorization = CryptoHoldoutAuthorization(**{key: raw[key] for key in known})
    if not isinstance(claimed, str) or claimed != authorization.digest():
        raise HoldoutSealError("crypto holdout authorization digest mismatch")
    seal = load_seal(directory)
    if authorization.dataset_id != seal.dataset_id:
        raise HoldoutSealError("crypto holdout authorization dataset identity mismatch")
    if authorization.manifest_digest != seal.dataset_digest:
        raise HoldoutSealError("crypto holdout authorization manifest digest mismatch")
    if authorization.holdout_seal_digest != seal.seal():
        raise HoldoutSealError("crypto holdout authorization seal linkage mismatch")
    return authorization


def verify_against_dataset(seal: HoldoutSeal, components: dict[str, str]) -> None:
    """Fail closed when the data is not the data that was sealed."""
    actual = dataset_digest(components)
    if actual != seal.dataset_digest:
        raise HoldoutSealError(
            f"dataset digest {actual[:12]}... does not match the sealed "
            f"{seal.dataset_digest[:12]}.... The panel changed after sealing, so "
            "the reserved dates no longer identify the reserved data."
        )


def assert_within_selection(seal: HoldoutSeal, days: list[str]) -> None:
    """Refuse a research-side date range that reaches into the holdout."""
    intruding = sorted({d for d in days if not seal.covers_selection(d)})
    if intruding:
        raise HoldoutSealError(
            f"{len(intruding)} date(s) outside the selection window "
            f"[{seal.selection_start}, {seal.selection_end}], first "
            f"{intruding[:3]}; the holdout is not readable before the final "
            "evaluation"
        )


def read_reveals(directory: str | Path) -> list[dict[str, Any]]:
    path = Path(directory) / REVEAL_LOG_FILENAME
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def assert_not_revealed(directory: str | Path) -> None:
    """Guard for every research step: the holdout must still be untouched."""
    reveals = read_reveals(directory)
    if reveals:
        raise HoldoutSealError(
            f"the holdout was already revealed at {reveals[0].get('at_utc')!r} "
            f"for {reveals[0].get('reason')!r}; research after a reveal is "
            "in-sample work wearing an out-of-sample label"
        )


def record_reveal(
    directory: str | Path,
    *,
    reason: str,
    at_utc: str,
    frozen_selection: dict[str, Any],
) -> dict[str, Any]:
    """Record the single permitted reveal, naming what was already frozen.

    ``frozen_selection`` is the decision the holdout is about to judge — the
    strategy, its parameters, the trial that produced it. Requiring it here is
    the point: a reveal that cannot say what it is testing is a reveal that can
    be re-aimed at whatever the holdout turns out to like.
    """
    if not reason.strip():
        raise HoldoutSealError("a reveal must state its reason")
    if not frozen_selection:
        raise HoldoutSealError("a reveal must name the already-frozen selection it will evaluate")
    out = Path(directory)
    seal = load_seal(out)
    assert_dataset_not_invalidated(out, seal.dataset_digest)
    if _is_crypto_seal(seal):
        load_crypto_holdout_authorization(out)
    assert_not_revealed(out)
    record = {
        "seal_id": seal.seal_id,
        "seal": seal.seal(),
        "reason": reason,
        "at_utc": at_utc,
        "frozen_selection": frozen_selection,
        "schema_version": SCHEMA_VERSION,
    }
    with (out / REVEAL_LOG_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
    return record


__all__ = [
    "CRYPTO_AUTHORIZATION_FIELD",
    "CryptoHoldoutAuthorization",
    "INVALIDATION_FILENAME",
    "REVEAL_LOG_FILENAME",
    "SEAL_FILENAME",
    "HoldoutSeal",
    "HoldoutSealError",
    "assert_dataset_not_invalidated",
    "assert_not_revealed",
    "assert_within_selection",
    "dataset_digest",
    "load_seal",
    "load_invalidation",
    "load_crypto_holdout_authorization",
    "invalidation_seal",
    "read_reveals",
    "record_reveal",
    "seal_holdout",
    "seal_crypto_holdout",
    "verify_against_dataset",
]
