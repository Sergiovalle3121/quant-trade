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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_text,
)

SCHEMA_VERSION = 1

#: Filename a sealed holdout is written under inside an experiment directory.
SEAL_FILENAME = "holdout_seal.json"
#: Append-only reveal log. Separate from the seal so recording a reveal can
#: never rewrite the declaration it is a reveal of.
REVEAL_LOG_FILENAME = "holdout_reveals.jsonl"

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
            "refusing to digest an empty dataset: a seal bound to nothing "
            "constrains nothing"
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


def seal_holdout(directory: str | Path, seal: HoldoutSeal) -> tuple[Path, str]:
    """Write a declaration and return its path and digest.

    Refuses to overwrite: a holdout that can be re-declared after the run is
    decoration, and making that a filesystem-level guarantee costs one
    existence check.
    """
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    path = out / SEAL_FILENAME
    if path.exists():
        raise HoldoutSealError(
            f"{path} already exists; a sealed holdout is never rewritten. "
            "Seal a new seal_id against a new dataset instead."
        )
    payload = seal.to_dict()
    atomic_write_json(path, payload)
    return path, str(payload["seal"])


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
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
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
        raise HoldoutSealError(
            "a reveal must name the already-frozen selection it will evaluate"
        )
    out = Path(directory)
    seal = load_seal(out)
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
    "REVEAL_LOG_FILENAME",
    "SEAL_FILENAME",
    "HoldoutSeal",
    "HoldoutSealError",
    "assert_not_revealed",
    "assert_within_selection",
    "dataset_digest",
    "load_seal",
    "read_reveals",
    "record_reveal",
    "seal_holdout",
    "verify_against_dataset",
]
