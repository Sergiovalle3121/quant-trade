"""Result types of the battery: frozen, language-free, float-free."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUS_CLEAN = "CLEAN"
STATUS_SIGNAL = "SIGNAL"
STATUS_INFO = "INFO"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUSES = (STATUS_CLEAN, STATUS_SIGNAL, STATUS_INFO, STATUS_NOT_MEASURED)

MEASURED = "MEASURED"
DECLARED = "DECLARED"
NOT_MEASURED = "NOT_MEASURED"
EVIDENCE = (MEASURED, DECLARED, NOT_MEASURED)

#: How many raw-row indexes a check keeps as examples (the lowest ones).
MAX_EXAMPLES = 5

Figure = tuple[str, str, str]
"""``(key, value_as_text, evidence)``: counts as decimal digits, money at
printed precision, ratios with three decimals, dates ISO ``YYYY-MM-DDTHH:MM:SSZ``."""


@dataclass(frozen=True)
class RawOutcome:
    """What a check module returns before the status rule is applied."""

    hits: int = 0
    figures: tuple[Figure, ...] = ()
    examples: tuple[int, ...] = ()
    not_measured: bool = False
    reason: str = ""

    @staticmethod
    def skip(reason: str, figures: tuple[Figure, ...] = ()) -> RawOutcome:
        return RawOutcome(not_measured=True, reason=reason, figures=figures)


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: str
    figures: tuple[Figure, ...] = ()
    examples: tuple[int, ...] = ()
    reason: str = ""
    applies: bool = False
    calibration: tuple[tuple[str, str], ...] = ()

    def figure(self, key: str) -> str | None:
        for name, value, _evidence in self.figures:
            if name == key:
                return value
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "figures": [list(figure) for figure in self.figures],
            "examples": list(self.examples),
            "reason": self.reason,
            "applies": self.applies,
            "calibration": [list(item) for item in self.calibration],
        }


@dataclass(frozen=True)
class ForensicResult:
    method_version: str
    source_format: str
    family: str
    checks: tuple[CheckResult, ...]
    rows_read: int
    truncated: bool
    header_present: bool
    counts: tuple[tuple[str, int], ...] = field(default=())

    def check(self, check_id: str) -> CheckResult:
        for item in self.checks:
            if item.id == check_id:
                return item
        raise KeyError(check_id)

    def count(self, status: str) -> int:
        for name, value in self.counts:
            if name == status:
                return value
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_version": self.method_version,
            "source_format": self.source_format,
            "family": self.family,
            "checks": [check.as_dict() for check in self.checks],
            "counts": [[name, value] for name, value in self.counts],
            "rows_read": self.rows_read,
            "truncated": self.truncated,
            "header_present": self.header_present,
        }
