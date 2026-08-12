"""Apply the measured cost model to a portfolio rebalance.

`crypto_lowcap.py` answers "what does one order of size N in tier T cost".
A backtest asks a different question: what does moving this portfolio from
these weights to those weights cost, when every holding sits in a different
tier and some of them cannot be traded at the required size at all.

Three things this refuses to do, each of which would flatter the result:

**Charge for a trade that cannot happen.** A notional the visible book cannot
fill has no cost, it has a refusal. The leg is capped at the largest size the
tier's book demonstrably fills, the shortfall is reported, and the portfolio
simply does not reach its target weight. Extrapolating a cost past the
measured depth would turn "impossible" into "expensive", which is exactly the
error that makes small-cap backtests look tradable.

**Silently interpolate.** ``TierCostProfile.exec_cost_bps`` charges the cost of
the smallest calibrated notional at or above the request, never below, so a
$1,500 order pays the $5,000 rate rather than an invented one.

**Confuse a round trip with a leg.** The measured numbers are round-trip costs
against mid. A rebalance leg is one way, so it pays half the execution cost and
one taker fee. Summed over a full portfolio replacement this reproduces the
repo's turnover convention exactly: sum of |delta weight| = 2.0 is one round
trip, i.e. turnover 1.0, and the drag equals the round-trip cost.

Coins outside every calibrated tier — below $1M or above $10B market cap — have
no measured profile. They are refused rather than assigned the nearest tier's
numbers, and counted, because a coin too small to have been measured is
precisely the coin whose cost cannot be guessed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.costs.crypto_lowcap import (
    BYBIT_SPOT_TAKER_FEE,
    DEFAULT_TIER_PROFILES,
    CostInput,
    CostModelError,
    TierCostProfile,
    tier_for_market_cap,
)

QUANTILE_P50 = "p50"
QUANTILE_P75 = "p75"


@dataclass
class LegOutcome:
    """What happened to one asset's leg of a rebalance."""

    symbol: str
    tier: str
    requested_notional_usd: float
    executed_notional_usd: float
    cost_bps_of_leg: float
    cost_usd: float
    executable: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RebalanceCost:
    """The cost of one rebalance, and what it could not do."""

    portfolio_value_usd: float
    turnover: float
    cost_usd: float
    cost_bps_of_portfolio: float
    legs: list[LegOutcome] = field(default_factory=list)
    refused_legs: int = 0
    capped_legs: int = 0
    unpriceable_legs: int = 0
    achieved_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_value_usd": self.portfolio_value_usd,
            "turnover": self.turnover,
            "cost_usd": self.cost_usd,
            "cost_bps_of_portfolio": self.cost_bps_of_portfolio,
            "refused_legs": self.refused_legs,
            "capped_legs": self.capped_legs,
            "unpriceable_legs": self.unpriceable_legs,
            "legs": [leg.to_dict() for leg in self.legs],
            "achieved_weights": dict(self.achieved_weights),
        }


def _profiles_by_tier(
    profiles: tuple[TierCostProfile, ...],
) -> dict[str, TierCostProfile]:
    return {profile.tier: profile for profile in profiles}


def _exec_cost_bps(
    profile: TierCostProfile, notional_usd: float, quantile: str
) -> float | None:
    table = (
        profile.exec_cost_bps_by_notional
        if quantile == QUANTILE_P50
        else profile.exec_cost_p75_bps_by_notional
    )
    eligible = [n for n, v in table.items() if n >= notional_usd and v is not None]
    if not eligible:
        return None
    return table[min(eligible)]


def max_calibrated_notional(
    profile: TierCostProfile, quantile: str = QUANTILE_P75
) -> float:
    """Largest notional this tier was measured at, fillable or not."""
    table = (
        profile.exec_cost_bps_by_notional
        if quantile == QUANTILE_P50
        else profile.exec_cost_p75_bps_by_notional
    )
    priced = [n for n, v in table.items() if v is not None]
    return max(priced) if priced else 0.0


def max_fully_executable_notional(
    profile: TierCostProfile, min_executable_fraction: float = 1.0
) -> float:
    """Largest notional EVERY sampled book in the tier could fill.

    This is the capacity number, and it is a different question from the cost
    number. ``executable_fraction_by_notional`` records that only 75% of micro
    books and 92% of low books could fill $10,000 on visible depth; the cost
    quantiles at those sizes cover only the books that could, so reading a cost
    without this is how a tier looks cheaper than it is. Sizes with no recorded
    fraction are treated as unmeasured, not as fully fillable.
    """
    fractions = profile.executable_fraction_by_notional
    if not fractions:
        return 0.0
    fillable = [n for n, f in fractions.items() if f >= min_executable_fraction]
    return max(fillable) if fillable else 0.0


def rebalance_cost(
    weights_before: dict[str, float],
    weights_target: dict[str, float],
    market_caps: dict[str, float],
    *,
    portfolio_value_usd: float,
    quantile: str = QUANTILE_P75,
    profiles: tuple[TierCostProfile, ...] = DEFAULT_TIER_PROFILES,
    taker_fee: CostInput = BYBIT_SPOT_TAKER_FEE,
    min_executable_fraction: float = 1.0,
) -> RebalanceCost:
    """Cost of moving from ``weights_before`` to ``weights_target``.

    Returns the cost AND the weights actually achievable, which are not the
    target when a book cannot absorb the required size. Callers must use
    ``achieved_weights`` for the next period; using the target would let the
    backtest hold positions it could never have built.

    ``min_executable_fraction`` is the share of the tier's sampled books that
    must have filled a size before it counts as tradable. The default of 1.0
    means every sampled book, which refuses $10,000 in micro (75% filled) and
    in low (92%) — deliberately strict, because a backtest cannot know which
    quartile of the cross-section a given coin sits in, and the alternative is
    to hold positions that a quarter of the time could not be opened.
    ASSUMPTION class, declared.
    """
    if quantile not in (QUANTILE_P50, QUANTILE_P75):
        raise CostModelError(f"quantile must be {QUANTILE_P50!r} or {QUANTILE_P75!r}")
    if portfolio_value_usd <= 0:
        raise CostModelError("portfolio_value_usd must be positive")
    by_tier = _profiles_by_tier(profiles)

    result = RebalanceCost(
        portfolio_value_usd=portfolio_value_usd,
        turnover=0.0,
        cost_usd=0.0,
        cost_bps_of_portfolio=0.0,
    )
    achieved = dict(weights_before)
    total_cost_usd = 0.0
    executed_notional = 0.0

    for symbol in sorted(set(weights_before) | set(weights_target)):
        before = float(weights_before.get(symbol, 0.0))
        target = float(weights_target.get(symbol, 0.0))
        delta = target - before
        if delta == 0.0:
            achieved[symbol] = target
            continue
        requested = abs(delta) * portfolio_value_usd
        market_cap = float(market_caps.get(symbol, 0.0))
        tier = tier_for_market_cap(market_cap) if market_cap > 0 else None
        if tier is None or tier not in by_tier:
            # No measured profile: refuse rather than borrow another tier's
            # numbers. The position stays where it was.
            achieved[symbol] = before
            result.unpriceable_legs += 1
            result.legs.append(
                LegOutcome(
                    symbol=symbol,
                    tier=tier or "none",
                    requested_notional_usd=requested,
                    executed_notional_usd=0.0,
                    cost_bps_of_leg=0.0,
                    cost_usd=0.0,
                    executable=False,
                    reason=(
                        f"market cap {market_cap:,.0f} falls outside every calibrated "
                        "tier; cost is NOT_MEASURED and is not extrapolated"
                    ),
                )
            )
            continue

        profile = by_tier[tier]
        reason = ""

        # Two different refusals, kept apart because conflating them is how a
        # capacity limit gets invented where only a measurement gap exists.
        if requested > max_calibrated_notional(profile, quantile):
            # Beyond the measured domain. The model was calibrated at $100 to
            # $10,000 for small capital; a larger order is NOT_MEASURED, not
            # impossible. Capping it here would assert a capacity limit the
            # measurement never established.
            achieved[symbol] = before
            result.unpriceable_legs += 1
            result.legs.append(
                LegOutcome(
                    symbol=symbol,
                    tier=tier,
                    requested_notional_usd=requested,
                    executed_notional_usd=0.0,
                    cost_bps_of_leg=0.0,
                    cost_usd=0.0,
                    executable=False,
                    reason=(
                        f"requested {requested:,.0f} exceeds the calibrated domain "
                        f"({max_calibrated_notional(profile, quantile):,.0f} in "
                        f"{tier}); cost is NOT_MEASURED at this size"
                    ),
                )
            )
            continue

        capacity = max_fully_executable_notional(profile, min_executable_fraction)
        executed = requested
        if requested > capacity:
            # A real capacity limit: some sampled books in this tier could not
            # fill this size at any price. A trade that cannot fill is not an
            # expensive trade, it is an absent one.
            if capacity <= 0:
                achieved[symbol] = before
                result.refused_legs += 1
                result.legs.append(
                    LegOutcome(
                        symbol=symbol,
                        tier=tier,
                        requested_notional_usd=requested,
                        executed_notional_usd=0.0,
                        cost_bps_of_leg=0.0,
                        cost_usd=0.0,
                        executable=False,
                        reason=(
                            f"no measured size in {tier} fills for at least "
                            f"{min_executable_fraction:.0%} of sampled books"
                        ),
                    )
                )
                continue
            executed = capacity
            result.capped_legs += 1
            reason = (
                f"requested {requested:,.0f} exceeds {tier} capacity {capacity:,.0f} "
                f"(largest size at least {min_executable_fraction:.0%} of sampled "
                "books could fill); capped, target weight not reached"
            )
        cost_bps = _exec_cost_bps(profile, executed, quantile)
        if cost_bps is None:  # pragma: no cover - domain checked above
            raise CostModelError(f"no calibrated cost for {executed} in {tier}")
        # One-way leg: half the round-trip execution cost, one taker fee.
        leg_bps = cost_bps / 2.0 + taker_fee.value_bps
        leg_cost_usd = executed * leg_bps / 10_000.0
        total_cost_usd += leg_cost_usd
        executed_notional += executed
        achieved[symbol] = before + (executed / portfolio_value_usd) * (
            1.0 if delta > 0 else -1.0
        )
        result.legs.append(
            LegOutcome(
                symbol=symbol,
                tier=tier,
                requested_notional_usd=requested,
                executed_notional_usd=executed,
                cost_bps_of_leg=leg_bps,
                cost_usd=leg_cost_usd,
                executable=True,
                reason=reason,
            )
        )

    result.cost_usd = total_cost_usd
    result.cost_bps_of_portfolio = total_cost_usd / portfolio_value_usd * 10_000.0
    # Repo convention: turnover 1.0 is one full round trip of the portfolio,
    # so a complete replacement (sum |delta w| = 2) counts as 1.0.
    result.turnover = executed_notional / portfolio_value_usd / 2.0
    result.achieved_weights = {s: w for s, w in achieved.items() if w != 0.0}
    return result


__all__ = [
    "QUANTILE_P50",
    "QUANTILE_P75",
    "LegOutcome",
    "RebalanceCost",
    "max_calibrated_notional",
    "max_fully_executable_notional",
    "rebalance_cost",
]
