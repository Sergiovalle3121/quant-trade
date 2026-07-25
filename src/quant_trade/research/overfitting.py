"""Fail-closed overfitting evidence for rolling parameter selection."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

import numpy as np


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


@dataclass(frozen=True)
class CSCVPBOEvidence:
    """Combinatorially symmetric, rank-based backtest-overfitting evidence.

    ``pbo`` is the fraction of symmetric train/test combinations where the
    in-sample winner ranks at or below the out-of-sample median. Ranks use the
    Bailey et al. logit transform ``log(omega / (1 - omega))`` with
    ``omega = rank / (n_variants + 1)``. All statistics are computed from the
    complete observation-by-variant matrix; this is not a renamed
    walk-forward loss rate.
    """

    method: str
    observations: int
    parameter_variants: int
    partitions: int
    combinations: int
    pbo: float
    max_pbo: float
    oos_rank_percentiles: tuple[float, ...]
    logits: tuple[float, ...]
    selected_variant_indices: tuple[int, ...]
    decision: str
    reasons: tuple[str, ...]
    authorized_for_live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _average_ascending_rank(values: np.ndarray, selected: int) -> float:
    """Return a deterministic 1-based average rank; larger values rank higher."""
    value = values[selected]
    lower = int(np.count_nonzero(values < value))
    equal = int(np.count_nonzero(values == value))
    return 1.0 + lower + (equal - 1) / 2.0


def cscv_probability_of_backtest_overfitting(
    variant_returns: Any,
    *,
    partitions: int = 8,
    max_pbo: float = 0.50,
) -> CSCVPBOEvidence:
    """Estimate rank-based PBO using combinatorially symmetric cross-validation.

    Parameters
    ----------
    variant_returns:
        A finite ``(observations, parameter_variants)`` matrix. Columns are
        complete strategy/configuration return series evaluated on the same
        timestamps. Rows must already be ordered causally.
    partitions:
        An even number of equal contiguous partitions. Every choice of half
        the partitions is evaluated in-sample and its complement out-of-sample.
    max_pbo:
        Conservative decision threshold. Passing requires ``pbo < max_pbo``.
    """
    matrix = np.asarray(variant_returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("variant_returns must be a 2-D observations-by-variants matrix")
    observations, variants = matrix.shape
    if variants < 2:
        raise ValueError("CSCV requires at least two parameter variants")
    if not np.isfinite(matrix).all():
        raise ValueError("variant_returns must contain only finite values")
    if int(partitions) != partitions or partitions < 2 or partitions % 2:
        raise ValueError("partitions must be an even integer >= 2")
    partitions = int(partitions)
    if observations < partitions or observations % partitions:
        raise ValueError(
            "observations must be divisible into equal CSCV partitions "
            f"({observations} observations, {partitions} partitions)"
        )
    if not math.isfinite(max_pbo) or not 0 < max_pbo <= 1:
        raise ValueError("max_pbo must be finite and in (0, 1]")

    blocks = np.split(np.arange(observations), partitions)
    half = partitions // 2
    rank_percentiles: list[float] = []
    logits: list[float] = []
    selected_variants: list[int] = []

    for train_block_indices in combinations(range(partitions), half):
        train_set = set(train_block_indices)
        train_rows = np.concatenate([blocks[i] for i in train_block_indices])
        test_rows = np.concatenate([blocks[i] for i in range(partitions) if i not in train_set])
        train_scores = matrix[train_rows].mean(axis=0)
        # np.argmax gives a stable, IS-only tie break (lowest column index).
        selected = int(np.argmax(train_scores))
        test_scores = matrix[test_rows].mean(axis=0)
        rank = _average_ascending_rank(test_scores, selected)
        omega = rank / (variants + 1.0)
        logit = math.log(omega / (1.0 - omega))
        selected_variants.append(selected)
        rank_percentiles.append(omega)
        logits.append(logit)

    pbo = sum(value <= 0.0 for value in logits) / len(logits)
    reasons: list[str] = []
    if pbo >= max_pbo:
        reasons.append(f"CSCV rank-based PBO {pbo:.3f} is not below the maximum {max_pbo:.3f}")
    return CSCVPBOEvidence(
        method="cscv_rank_based",
        observations=observations,
        parameter_variants=variants,
        partitions=partitions,
        combinations=len(logits),
        pbo=pbo,
        max_pbo=max_pbo,
        oos_rank_percentiles=tuple(rank_percentiles),
        logits=tuple(logits),
        selected_variant_indices=tuple(selected_variants),
        decision="PASS" if not reasons else "NO-GO",
        reasons=tuple(reasons),
    )


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
