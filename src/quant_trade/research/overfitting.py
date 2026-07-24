"""Fail-closed overfitting evidence for rolling parameter selection."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WalkForwardOverfittingEvidence:
    """Empirical OOS rank evidence for train-selected parameter variants.

    ``walk_forward_pbo`` is the fraction of windows where the variant selected
    on training data ranks at or below the OOS median. It is deliberately
    labelled as a rolling walk-forward estimate, not the combinatorially
    symmetric cross-validation estimator from the academic PBO literature.
    """

    method: str
    windows: int
    parameter_variants: int
    walk_forward_pbo: float
    mean_selected_oos_rank_percentile: float
    mean_train_test_metric_degradation: float
    max_walk_forward_pbo: float
    min_windows: int
    decision: str
    reasons: tuple[str, ...]
    authorized_for_live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_walk_forward_overfitting(
    selected_oos_rank_percentiles: Iterable[float],
    train_test_metric_degradations: Iterable[float],
    *,
    parameter_variants: int,
    max_walk_forward_pbo: float = 0.50,
    min_windows: int = 4,
) -> WalkForwardOverfittingEvidence:
    """Assess whether train-time winners retain rank out of sample."""
    ranks = [float(value) for value in selected_oos_rank_percentiles]
    degradations = [float(value) for value in train_test_metric_degradations]
    if len(ranks) != len(degradations):
        raise ValueError("rank and degradation observations must have equal length")
    if not ranks:
        raise ValueError("at least one walk-forward window is required")
    if parameter_variants <= 0:
        raise ValueError("parameter_variants must be > 0")
    if min_windows <= 0:
        raise ValueError("min_windows must be > 0")
    if (
        not math.isfinite(max_walk_forward_pbo)
        or max_walk_forward_pbo < 0
        or max_walk_forward_pbo > 1
    ):
        raise ValueError("max_walk_forward_pbo must be finite and in [0, 1]")
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in ranks):
        raise ValueError("OOS rank percentiles must be finite and in [0, 1]")
    if any(not math.isfinite(value) for value in degradations):
        raise ValueError("metric degradations must be finite")

    pbo = sum(rank <= 0.50 for rank in ranks) / len(ranks)
    reasons: list[str] = []
    if parameter_variants < 2:
        reasons.append("at least two parameter variants are required for overfitting evidence")
    if len(ranks) < min_windows:
        reasons.append(
            f"walk-forward evidence has {len(ranks)} windows; at least {min_windows} are required"
        )
    if pbo > max_walk_forward_pbo:
        reasons.append(f"walk-forward PBO {pbo:.3f} exceeds the maximum {max_walk_forward_pbo:.3f}")

    return WalkForwardOverfittingEvidence(
        method="rolling_train_winner_oos_rank",
        windows=len(ranks),
        parameter_variants=parameter_variants,
        walk_forward_pbo=pbo,
        mean_selected_oos_rank_percentile=sum(ranks) / len(ranks),
        mean_train_test_metric_degradation=sum(degradations) / len(degradations),
        max_walk_forward_pbo=max_walk_forward_pbo,
        min_windows=min_windows,
        decision="PASS" if not reasons else "NO-GO",
        reasons=tuple(reasons),
    )
