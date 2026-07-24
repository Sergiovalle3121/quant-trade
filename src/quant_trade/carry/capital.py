"""Collateral, margin-path, and capital-efficiency accounting for carry.

A cash-and-carry position immobilizes real capital: the spot leg is fully
funded, the short perp posts initial margin, and the perp leg pays/receives
variation margin along the actual price path. A static normal approximation is
not enough to judge liquidation risk — this module walks the trajectory and
reports the minimum maintenance-margin distance and the maximum adverse
excursion actually reached.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


@dataclass(frozen=True)
class CapitalRequirement:
    """Capital actually immobilized for one unit of hedge notional (USD)."""

    notional_usd: float
    spot_capital_usd: float
    perp_initial_margin_usd: float
    liquidity_buffer_usd: float
    total_capital_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def capital_required(
    notional_usd: float,
    *,
    perp_leverage: float = 1.0,
    buffer_fraction: float = 0.10,
) -> CapitalRequirement:
    """Spot fully funded + perp initial margin + an explicit liquidity buffer."""
    _positive("notional_usd", notional_usd)
    _positive("perp_leverage", perp_leverage)
    if not 0 <= buffer_fraction < 1:
        raise ValueError("buffer_fraction must be in [0, 1)")
    spot = notional_usd
    margin = notional_usd / perp_leverage
    buffer = notional_usd * buffer_fraction
    return CapitalRequirement(
        notional_usd=notional_usd,
        spot_capital_usd=spot,
        perp_initial_margin_usd=margin,
        liquidity_buffer_usd=buffer,
        total_capital_usd=spot + margin + buffer,
    )


@dataclass
class MarginPathResult:
    """Trajectory-based margin outcome for the short perp leg."""

    entry_price: float
    min_margin_distance: float  # min over time of equity_fraction - maintenance
    breached: bool
    breach_index: int | None
    max_adverse_excursion: float  # worst adverse price move fraction (price up)
    final_variation_margin: float  # cumulative VM per unit notional (signed)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_perp_margin_path(
    perp_prices: list[float],
    *,
    perp_leverage: float = 1.0,
    maintenance_margin_rate: float = 0.005,
    entry_index: int = 0,
) -> MarginPathResult:
    """Walk the short-perp margin account along the ACTUAL price path.

    Per unit of entry notional: equity fraction at t is
    ``1/leverage + (entry - price_t) / entry`` (initial margin plus cumulative
    variation margin of a short). Breach = equity falls to or below the
    maintenance rate. MAE is the worst adverse (upward) price excursion.
    """
    if not perp_prices:
        raise ValueError("perp_prices must be non-empty")
    if entry_index < 0 or entry_index >= len(perp_prices):
        raise ValueError("entry_index out of range")
    _positive("perp_leverage", perp_leverage)
    if not 0 <= maintenance_margin_rate < 1:
        raise ValueError("maintenance_margin_rate must be in [0, 1)")
    entry = float(perp_prices[entry_index])
    _positive("entry price", entry)
    initial_margin = 1.0 / perp_leverage
    min_distance = math.inf
    breached = False
    breach_index: int | None = None
    mae = 0.0
    vm = 0.0
    for i in range(entry_index, len(perp_prices)):
        price = float(perp_prices[i])
        vm = (entry - price) / entry  # cumulative VM of the short, per notional
        equity_fraction = initial_margin + vm
        distance = equity_fraction - maintenance_margin_rate
        min_distance = min(min_distance, distance)
        mae = max(mae, max(0.0, (price - entry) / entry))
        if distance <= 0 and not breached:
            breached = True
            breach_index = i
    return MarginPathResult(
        entry_price=entry,
        min_margin_distance=float(min_distance),
        breached=breached,
        breach_index=breach_index,
        max_adverse_excursion=mae,
        final_variation_margin=vm,
    )


def collateral_invariants(
    *,
    initial_capital_usd: float,
    cash_usd: float,
    spot_value_usd: float,
    perp_margin_account_usd: float,
    cumulative_pnl_usd: float,
    tolerance_usd: float = 1e-6,
) -> list[str]:
    """Accounting identity violations (empty list = books balance).

    cash + spot value + perp margin account must equal initial capital plus
    cumulative P&L. A silent hole here means phantom money somewhere.
    """
    violations: list[str] = []
    lhs = cash_usd + spot_value_usd + perp_margin_account_usd
    rhs = initial_capital_usd + cumulative_pnl_usd
    if abs(lhs - rhs) > tolerance_usd:
        violations.append(
            f"collateral identity broken: assets {lhs:.6f} != capital+pnl {rhs:.6f}"
        )
    if perp_margin_account_usd < -tolerance_usd:
        violations.append("perp margin account is negative")
    if spot_value_usd < -tolerance_usd:
        violations.append("spot value is negative")
    return violations


def residual_delta(
    spot_quantity: float, perp_quantity: float, *, tolerance: float = 1e-9
) -> tuple[float, bool]:
    """Signed residual delta of the pair and whether it is hedged within tolerance."""
    delta = spot_quantity - perp_quantity
    return delta, abs(delta) <= tolerance
