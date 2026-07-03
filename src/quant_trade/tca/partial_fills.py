"""Partial-fill simulation bounded by historical volume."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PartialFillResult:
    requested_quantity: float
    filled_quantity: float
    rejected_quantity: float
    fill_rate: float
    status: str


def simulate_partial_fills(
    quantity: float,
    available_volume: float,
    max_participation_rate: float = 0.10,
) -> PartialFillResult:
    requested = abs(float(quantity))
    capacity = max(0.0, float(available_volume) * max_participation_rate)
    filled = min(requested, capacity)
    rejected = max(0.0, requested - filled)
    status = "filled" if filled == requested else ("rejected" if filled == 0 else "partial")
    fill_rate = 0.0 if requested == 0 else filled / requested
    return PartialFillResult(requested, filled, rejected, fill_rate, status)
