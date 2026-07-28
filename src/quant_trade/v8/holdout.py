"""A holdout that can prove it was not used for tuning.

"We kept a holdout" is unverifiable when the holdout is just a slice of an
array everything can see. This module makes the claim mechanical: the rows
behind the boundary are unreachable until :meth:`HoldoutGuard.reveal` is
called, ``reveal`` may be called exactly once, and the access is recorded with
the reason. A campaign that selects a variant after revealing, or reveals
twice, raises — it cannot silently produce a number.

The guard is deliberately dumb. It cannot stop a determined caller who reaches
around it, but it makes the ordinary path honest and makes a violation show up
as an exception in a test rather than as a slightly-too-good Sharpe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class HoldoutViolation(RuntimeError):
    """The holdout was accessed out of order, or more than once."""


@dataclass
class HoldoutAccess:
    reason: str
    at_step: str

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "at_step": self.at_step}


class HoldoutGuard:
    """Split rows chronologically and gate access to the final slice."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        holdout_fraction: float,
        timestamp_key: str = "start_ms",
    ) -> None:
        if not 0.0 < holdout_fraction < 1.0:
            raise ValueError("holdout_fraction must be in (0, 1)")
        ordered = sorted(rows, key=lambda r: r[timestamp_key])
        boundary = int(len(ordered) * (1.0 - holdout_fraction))
        if boundary <= 0 or boundary >= len(ordered):
            raise ValueError(
                f"{len(ordered)} row(s) cannot be split at holdout_fraction="
                f"{holdout_fraction}: one side would be empty"
            )
        self._rows = ordered
        self._boundary = boundary
        self._holdout_fraction = holdout_fraction
        self._accesses: list[HoldoutAccess] = []
        self._selection_frozen = False
        self._selected: Any = None

    # --- selection side ----------------------------------------------------

    @property
    def selection_rows(self) -> list[dict[str, Any]]:
        """Everything before the boundary: train + walk-forward."""
        return list(self._rows[: self._boundary])

    def freeze_selection(self, selected: Any) -> None:
        """Record the chosen variant. Must happen before ``reveal``."""
        if self._accesses:
            raise HoldoutViolation(
                "selection was frozen after the holdout had already been "
                "revealed; the choice is no longer out-of-sample"
            )
        self._selection_frozen = True
        self._selected = selected

    @property
    def selected(self) -> Any:
        return self._selected

    # --- holdout side ------------------------------------------------------

    def reveal(self, *, reason: str, at_step: str = "final_scoring") -> list[dict[str, Any]]:
        if not self._selection_frozen:
            raise HoldoutViolation(
                "the holdout cannot be read before the variant selection is "
                "frozen — that is what makes it out-of-sample"
            )
        if self._accesses:
            raise HoldoutViolation(
                "the holdout has already been revealed once; a second look "
                "would make it an in-sample set"
            )
        self._accesses.append(HoldoutAccess(reason=reason, at_step=at_step))
        return list(self._rows[self._boundary :])

    # --- reporting ---------------------------------------------------------

    @property
    def touched(self) -> bool:
        return bool(self._accesses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": len(self._rows),
            "selection_rows": self._boundary,
            "holdout_rows": len(self._rows) - self._boundary,
            "holdout_fraction": self._holdout_fraction,
            "holdout_position": "most_recent",
            "selection_frozen": self._selection_frozen,
            "selected": self._selected,
            "reveal_count": len(self._accesses),
            "accesses": [a.to_dict() for a in self._accesses],
            "boundary_timestamp": (
                self._rows[self._boundary].get("timestamp_utc")
                if self._boundary < len(self._rows)
                else None
            ),
        }


@dataclass
class SplitReport:
    """Chronological train / walk-forward / holdout boundaries."""

    total_rows: int
    train_rows: int
    walk_forward_rows: int
    holdout_rows: int
    train_end_utc: str = ""
    walk_forward_end_utc: str = ""
    holdout_end_utc: str = ""
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def chronological_split(
    rows: list[dict[str, Any]],
    *,
    train_fraction: float,
    walk_forward_fraction: float,
    timestamp_key: str = "timestamp_utc",
) -> SplitReport:
    """Describe the pre-registered three-way split of a panel."""
    total = len(rows)
    holdout_fraction = 1.0 - train_fraction - walk_forward_fraction
    report = SplitReport(
        total_rows=total,
        train_rows=int(total * train_fraction),
        walk_forward_rows=int(total * walk_forward_fraction),
        holdout_rows=0,
    )
    report.holdout_rows = total - report.train_rows - report.walk_forward_rows
    if holdout_fraction <= 0:
        report.problems.append("train + walk-forward fractions leave no holdout")
    if min(report.train_rows, report.walk_forward_rows, report.holdout_rows) <= 0:
        report.problems.append("a split section is empty")
        return report
    ordered = sorted(rows, key=lambda r: r[timestamp_key])
    report.train_end_utc = str(ordered[report.train_rows - 1][timestamp_key])
    report.walk_forward_end_utc = str(
        ordered[report.train_rows + report.walk_forward_rows - 1][timestamp_key]
    )
    report.holdout_end_utc = str(ordered[-1][timestamp_key])
    return report


__all__ = [
    "HoldoutAccess",
    "HoldoutGuard",
    "HoldoutViolation",
    "SplitReport",
    "chronological_split",
]
