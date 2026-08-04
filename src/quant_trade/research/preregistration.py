"""Per-experiment pre-registration: declare it before you run it, or it cannot promote.

The trial ledger already records what was run. It cannot record what was
*intended*, and that asymmetry is the whole problem: a search that tries fifty
things and reports the one that worked produces a ledger indistinguishable from
a search that predicted the winner in advance. Deflated Sharpe corrects for the
trial count only if the trial count is honest, and nothing forces it to be.

This seals the intent first. Before a run, an experiment states its hypothesis,
its universe, its date range, the selection criterion it will be judged by, the
maximum number of trials it may spend, and — the field that does the real work —
what result would count as refutation. The document is hashed, the hash is
written into every trial the experiment produces, and promotion refuses any
candidate whose trials carry no seal.

Deliberately NOT a generalisation of v8/preregistration.py or
v9/preregistration.py. Those are sprint-level records: one frozen document per
version, authored as module constants, whose freeze_hash() is stamped into every
artifact of that version. They are history and are left alone. This is the live,
per-experiment instrument, and it reuses their sealing primitive and their gate
vocabulary rather than competing with them.

Three properties are load-bearing:

sealed before, not after
    ``seal()`` is computed over the declared fields only. Results cannot enter
    the hash, so a document cannot be edited to match what was found.

revealable
    The full document is stored, not just its digest, and ``verify()``
    recomputes the seal from the stored content. A seal you cannot re-derive is
    a number, not evidence.

binding
    ``max_trials`` is declared up front and the ledger counts against it,
    including trials that failed. An experiment that spends more attempts than
    it declared has falsified its own trial count, which is exactly the thing
    the deflation arithmetic depends on.
"""

from __future__ import annotations

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

#: Filename a sealed pre-registration is written under inside an experiment dir.
SEAL_FILENAME = "preregistration.json"

#: Fields that constitute the declaration. Anything outside this set is
#: metadata and is excluded from the seal, so recording where a document was
#: filed cannot change what it claims.
SEALED_FIELDS = (
    "experiment_id",
    "hypothesis",
    "universe",
    "start_date",
    "end_date",
    "selection_criterion",
    "max_trials",
    "refutation",
    "registered_at_utc",
    "registered_at_commit",
    "schema_version",
)


class PreregistrationError(RuntimeError):
    """Raised when a declaration is malformed, unsealed, or contradicted."""


@dataclass(frozen=True)
class ExperimentPreregistration:
    """What an experiment claims, before it is allowed to look."""

    experiment_id: str
    hypothesis: str
    universe: list[str]
    start_date: str
    end_date: str
    selection_criterion: dict[str, Any]
    max_trials: int
    refutation: str
    registered_at_utc: str
    registered_at_commit: str = ""
    schema_version: int = SCHEMA_VERSION
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.experiment_id.strip():
            raise PreregistrationError("experiment_id is required")
        if not self.hypothesis.strip():
            raise PreregistrationError("hypothesis is required")
        if not self.universe:
            raise PreregistrationError(
                "universe is required: an experiment that does not say what it "
                "will look at can be re-aimed after the fact"
            )
        if not self.start_date.strip() or not self.end_date.strip():
            raise PreregistrationError("start_date and end_date are required")
        if self.end_date < self.start_date:
            raise PreregistrationError("end_date must not precede start_date")
        if not self.selection_criterion:
            raise PreregistrationError("selection_criterion is required")
        if self.max_trials < 1:
            raise PreregistrationError("max_trials must be at least 1")
        if not self.refutation.strip():
            raise PreregistrationError(
                "refutation is required: a hypothesis that cannot be refuted by "
                "any stated result is not being tested"
            )
        if not self.registered_at_utc.strip():
            raise PreregistrationError("registered_at_utc is required")

    def sealed_content(self) -> dict[str, Any]:
        """Exactly the declared fields, in canonical order."""
        payload = asdict(self)
        return {key: payload[key] for key in SEALED_FIELDS}

    def seal(self) -> str:
        """The digest of the declaration. Results never enter it."""
        return sha256_of_text(canonical_dumps(self.sealed_content()))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "seal": self.seal()}


def seal_preregistration(
    directory: str | Path, prereg: ExperimentPreregistration
) -> tuple[Path, str]:
    """Write a declaration and return its path and seal.

    Refuses to overwrite. A pre-registration that can be rewritten after the run
    is not a pre-registration, and making that a filesystem-level guarantee
    costs one existence check.
    """
    out = Path(directory) / SEAL_FILENAME
    if out.exists():
        raise PreregistrationError(
            f"{out} already exists; a sealed pre-registration is never rewritten. "
            "Register a new experiment_id instead."
        )
    payload = prereg.to_dict()
    atomic_write_json(out, payload)
    return out, str(payload["seal"])


def load_preregistration(directory: str | Path) -> ExperimentPreregistration:
    """Read a sealed declaration back, verifying the seal still matches."""
    path = Path(directory) / SEAL_FILENAME
    if not path.exists():
        raise PreregistrationError(f"no sealed pre-registration at {path}")
    payload = load_json(path)
    claimed = str(payload.get("seal", ""))
    known = {f.name for f in ExperimentPreregistration.__dataclass_fields__.values()}
    prereg = ExperimentPreregistration(**{k: v for k, v in payload.items() if k in known})
    actual = prereg.seal()
    if not claimed or claimed != actual:
        raise PreregistrationError(
            f"pre-registration seal mismatch at {path}: stored {claimed[:12]}..., "
            f"content hashes to {actual[:12]}.... The declaration was edited after sealing."
        )
    return prereg


def verify(prereg: ExperimentPreregistration, seal: str) -> bool:
    """Whether a seal belongs to this declaration."""
    return bool(seal) and prereg.seal() == seal


def trials_for_seal(records: list[dict[str, Any]], seal: str) -> list[dict[str, Any]]:
    """Every ledger record bound to a seal, whatever its outcome.

    A pre-registered trial that failed counts. That is the point: the deflation
    arithmetic asks how many attempts were made, not how many worked, and an
    experiment that could quietly drop its failures would deflate against a
    number it chose.
    """
    return [r for r in records if str(r.get("preregistration_seal", "")) == seal]


def budget_status(
    prereg: ExperimentPreregistration, records: list[dict[str, Any]]
) -> dict[str, Any]:
    """How much of the declared trial budget an experiment has spent."""
    spent = len(trials_for_seal(records, prereg.seal()))
    return {
        "experiment_id": prereg.experiment_id,
        "seal": prereg.seal(),
        "max_trials": prereg.max_trials,
        "trials_spent": spent,
        "trials_remaining": max(0, prereg.max_trials - spent),
        "over_budget": spent > prereg.max_trials,
    }


def assert_within_budget(
    prereg: ExperimentPreregistration, records: list[dict[str, Any]]
) -> None:
    """Fail closed when an experiment has spent more trials than it declared."""
    status = budget_status(prereg, records)
    if status["over_budget"]:
        raise PreregistrationError(
            f"experiment {prereg.experiment_id!r} declared max_trials="
            f"{prereg.max_trials} but the ledger holds {status['trials_spent']} "
            "trials against its seal; the declared trial count is no longer true, "
            "so nothing derived from it can be trusted"
        )
