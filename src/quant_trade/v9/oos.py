"""Walk-forward that is actually out-of-sample, and a holdout that stays sealed.

V8 called its procedure walk-forward but selected one variant on the whole
selection window and then reported per-window returns for that single choice.
That is a full-sample fit sliced up afterwards: every window's "test" return
came from a variant chosen with knowledge of that window.

The rewrite does the thing the name promises. For window *k*:

1. the selector sees only bars strictly before window *k*'s test block, minus a
   purge and an embargo;
2. it picks a variant from that view alone;
3. that variant is evaluated on window *k*'s test block and nowhere else;
4. only those test returns are concatenated into the OOS series.

The variant may differ from window to window — that is the point. A procedure
that always picks the same one has not been shown to be robust; it has been
shown to have been lucky once.

The holdout is sealed behind :class:`HoldoutSeal`, which will not open until a
configuration hash has been frozen and will not open twice. And the decisive
number is the *holdout*: the full-sample figure is reported because it is
informative about fit, but it can never rescue a negative holdout.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

#: Pre-registered chronological split.
TRAIN_FRACTION = 0.50
WALK_FORWARD_FRACTION = 0.30
HOLDOUT_FRACTION = 0.20


class HoldoutViolation(RuntimeError):
    """The holdout was read out of order, twice, or before the config froze."""


class InsufficientData(ValueError):
    """The series cannot support the pre-registered split."""


@dataclass(frozen=True)
class SplitPlan:
    """Index boundaries of the chronological three-way split."""

    total_rows: int
    train_end: int
    walk_forward_end: int

    @property
    def holdout_start(self) -> int:
        return self.walk_forward_end

    @property
    def train_rows(self) -> int:
        return self.train_end

    @property
    def walk_forward_rows(self) -> int:
        return self.walk_forward_end - self.train_end

    @property
    def holdout_rows(self) -> int:
        return self.total_rows - self.walk_forward_end

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "train_rows": self.train_rows,
            "walk_forward_rows": self.walk_forward_rows,
            "holdout_rows": self.holdout_rows,
            "train_end_index": self.train_end,
            "walk_forward_end_index": self.walk_forward_end,
            "holdout_start_index": self.holdout_start,
            "fractions": {
                "train": TRAIN_FRACTION,
                "walk_forward": WALK_FORWARD_FRACTION,
                "holdout": HOLDOUT_FRACTION,
            },
        }


def plan_splits(
    total_rows: int,
    *,
    train_fraction: float = TRAIN_FRACTION,
    walk_forward_fraction: float = WALK_FORWARD_FRACTION,
) -> SplitPlan:
    if total_rows < 10:
        raise InsufficientData(f"{total_rows} rows cannot support a three-way split")
    train_end = int(total_rows * train_fraction)
    walk_forward_end = train_end + int(total_rows * walk_forward_fraction)
    plan = SplitPlan(total_rows=total_rows, train_end=train_end, walk_forward_end=walk_forward_end)
    if min(plan.train_rows, plan.walk_forward_rows, plan.holdout_rows) <= 0:
        raise InsufficientData("a split section would be empty")
    return plan


@dataclass
class WalkForwardWindow:
    index: int
    selection_end_index: int
    test_start_index: int
    test_end_index: int
    selected_variant: str
    selection_score: float
    test_total_return: float
    test_observations: int
    candidates_considered: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    oos_returns: list[float] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def window_count(self) -> int:
        return len(self.windows)

    @property
    def oos_total_return(self) -> float:
        total = 1.0
        for value in self.oos_returns:
            total *= 1.0 + value
        return total - 1.0

    @property
    def positive_windows(self) -> int:
        return sum(1 for w in self.windows if w.test_total_return > 0)

    @property
    def distinct_variants(self) -> int:
        return len({w.selected_variant for w in self.windows})

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "window_count": self.window_count,
            "positive_windows": self.positive_windows,
            "distinct_variants_selected": self.distinct_variants,
            "oos_observations": len(self.oos_returns),
            "oos_total_return": self.oos_total_return,
            "problems": list(self.problems),
            "method": (
                "anchored walk-forward; each window selects on data strictly "
                "before its own test block, minus purge and embargo, and only "
                "test-block returns are concatenated"
            ),
        }


def run_walk_forward(
    row_count: int,
    variants: Sequence[str],
    evaluate: Callable[[str, int, int], list[float]],
    *,
    plan: SplitPlan,
    test_size: int,
    step_size: int | None = None,
    min_selection_rows: int = 1,
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> WalkForwardResult:
    """Run anchored walk-forward over ``[0, plan.walk_forward_end)``.

    ``evaluate(variant, start, end)`` returns the per-bar returns of one
    variant over ``[start, end)``. It is called for selection on past data and
    again on the test block; the function never sees the holdout because the
    walk-forward never indexes past ``plan.walk_forward_end``.
    """
    if not variants:
        raise InsufficientData("walk-forward needs at least one variant")
    if test_size <= 0:
        raise InsufficientData("test_size must be > 0")
    step = step_size or test_size
    result = WalkForwardResult()

    test_start = plan.train_end
    index = 0
    while test_start + test_size <= plan.walk_forward_end:
        # Everything the selector may see: strictly before this test block,
        # with a purge and an embargo carved out so a position opened near the
        # boundary cannot leak its outcome into the selection view.
        selection_end = test_start - purge_bars - embargo_bars
        if selection_end < min_selection_rows:
            result.problems.append(
                f"window {index}: only {max(0, selection_end)} selectable rows "
                f"before the purge/embargo; needs {min_selection_rows}"
            )
            test_start += step
            index += 1
            continue

        best_variant = ""
        best_score = -math.inf
        for variant in variants:
            returns = evaluate(variant, 0, selection_end)
            score = _total_return(returns)
            if score > best_score:
                best_score, best_variant = score, variant

        test_end = test_start + test_size
        test_returns = evaluate(best_variant, test_start, test_end)
        result.windows.append(
            WalkForwardWindow(
                index=index,
                selection_end_index=selection_end,
                test_start_index=test_start,
                test_end_index=test_end,
                selected_variant=best_variant,
                selection_score=best_score,
                test_total_return=_total_return(test_returns),
                test_observations=len(test_returns),
                candidates_considered=list(variants),
            )
        )
        result.oos_returns.extend(test_returns)
        test_start += step
        index += 1

    if not result.windows:
        result.problems.append("no walk-forward window fitted inside the walk-forward section")
    return result


def _total_return(returns: Sequence[float]) -> float:
    total = 1.0
    for value in returns:
        total *= 1.0 + value
    return total - 1.0


class HoldoutSeal:
    """The final slice, unreadable until a configuration has been frozen."""

    def __init__(self, plan: SplitPlan) -> None:
        self.plan = plan
        self._frozen: dict[str, Any] | None = None
        self._reveals: list[dict[str, Any]] = []

    def freeze(self, *, variant: str, config: dict[str, Any]) -> str:
        if self._reveals:
            raise HoldoutViolation(
                "the holdout has already been revealed; freezing a configuration "
                "now would make the choice in-sample"
            )
        payload = {"variant": variant, "config": config}
        self._frozen = payload
        return sha256_of_text(canonical_dumps(payload))

    @property
    def frozen_hash(self) -> str:
        if self._frozen is None:
            return ""
        return sha256_of_text(canonical_dumps(self._frozen))

    @property
    def frozen_variant(self) -> str:
        return str(self._frozen["variant"]) if self._frozen else ""

    def reveal(self, *, reason: str) -> tuple[int, int]:
        """Return the holdout index range, exactly once."""
        if self._frozen is None:
            raise HoldoutViolation("the holdout cannot be read before the configuration is frozen")
        if self._reveals:
            raise HoldoutViolation(
                "the holdout has already been revealed once; a second look would "
                "make it an in-sample set"
            )
        self._reveals.append({"reason": reason, "frozen_hash": self.frozen_hash})
        return self.plan.holdout_start, self.plan.total_rows

    @property
    def touched(self) -> bool:
        return bool(self._reveals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "frozen": self._frozen is not None,
            "frozen_hash": self.frozen_hash,
            "frozen_variant": self.frozen_variant,
            "reveal_count": len(self._reveals),
            "reveals": list(self._reveals),
        }


@dataclass
class HoldoutVerdict:
    """The decisive result. A negative holdout is never rescued."""

    frozen_variant: str
    frozen_hash: str
    holdout_observations: int
    holdout_net_return: float
    holdout_net_return_2x_costs: float
    holdout_net_return_3x_costs: float
    full_sample_net_return: float
    oos_net_return: float
    bootstrap_p05: float | None = None
    probabilistic_sharpe: float | None = None
    deflated_sharpe: float | None = None
    liquidations: int = 0
    failed_reconciliations: int = 0
    unverified_inputs: list[str] = field(default_factory=list)
    benchmark_returns: dict[str, float] = field(default_factory=dict)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return not self.rejection_reasons

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact"] = "HOLDOUT_VERDICT"
        payload["schema_version"] = 1
        payload["promoted"] = self.promoted
        payload["decision"] = "BACKTEST_CANDIDATE" if self.promoted else "MEASURED_REJECTED"
        payload["note"] = (
            "The holdout is decisive. The full-sample figure is reported because "
            "it is informative about fit, and is never used to overturn a "
            "negative holdout."
        )
        return payload


def evaluate_holdout(
    verdict: HoldoutVerdict,
    *,
    min_probabilistic_sharpe: float = 0.95,
    min_deflated_sharpe: float = 0.95,
) -> HoldoutVerdict:
    """Apply the promotion gates. Every failure is named."""
    checks: list[dict[str, Any]] = []

    def gate(name: str, required: Any, observed: Any, passed: bool) -> None:
        checks.append({"gate": name, "required": required, "observed": observed, "passed": passed})

    gate("holdout_net_positive", "> 0", verdict.holdout_net_return, verdict.holdout_net_return > 0)
    gate(
        "holdout_positive_at_1x_costs",
        "> 0",
        verdict.holdout_net_return,
        verdict.holdout_net_return > 0,
    )
    gate(
        "holdout_positive_at_2x_costs",
        "> 0",
        verdict.holdout_net_return_2x_costs,
        verdict.holdout_net_return_2x_costs > 0,
    )
    gate(
        "bootstrap_p05_positive",
        "> 0",
        verdict.bootstrap_p05,
        verdict.bootstrap_p05 is not None and verdict.bootstrap_p05 > 0,
    )
    gate(
        "probabilistic_sharpe",
        f">= {min_probabilistic_sharpe}",
        verdict.probabilistic_sharpe,
        verdict.probabilistic_sharpe is not None
        and verdict.probabilistic_sharpe >= min_probabilistic_sharpe,
    )
    gate(
        "deflated_sharpe",
        f">= {min_deflated_sharpe}",
        verdict.deflated_sharpe,
        verdict.deflated_sharpe is not None and verdict.deflated_sharpe >= min_deflated_sharpe,
    )
    gate("zero_liquidations", 0, verdict.liquidations, verdict.liquidations == 0)
    gate(
        "zero_failed_reconciliations",
        0,
        verdict.failed_reconciliations,
        verdict.failed_reconciliations == 0,
    )
    gate(
        "no_unverified_inputs",
        [],
        verdict.unverified_inputs,
        not verdict.unverified_inputs,
    )
    for name, value in sorted(verdict.benchmark_returns.items()):
        gate(
            f"beats_{name}",
            f"> {value}",
            verdict.holdout_net_return,
            verdict.holdout_net_return > value,
        )

    verdict.gate_results = checks
    verdict.rejection_reasons = [
        f"{c['gate']}: required {c['required']}, observed {c['observed']}"
        for c in checks
        if not c["passed"]
    ]
    return verdict


__all__ = [
    "HOLDOUT_FRACTION",
    "TRAIN_FRACTION",
    "WALK_FORWARD_FRACTION",
    "HoldoutSeal",
    "HoldoutVerdict",
    "HoldoutViolation",
    "InsufficientData",
    "SplitPlan",
    "WalkForwardResult",
    "WalkForwardWindow",
    "evaluate_holdout",
    "plan_splits",
    "run_walk_forward",
]
