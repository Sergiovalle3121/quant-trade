"""Capital pre-feasibility screen for a strategy family, before any data.

A trial spent is a trial spent.  Every evaluation this repository runs enters an
append-only ledger and raises the deflated-Sharpe threshold every later result
must clear, so a family that could never have been executed at the available
capital still costs statistical power when it is tested and rejected.

This screen runs first and reads no returns.  It asks only whether a family
*could* be run at all: does each position clear the venue's minimum, do the
frictions leave any Sharpe to find, can the fixed data cost be paid, and is
there a point-in-time source whose licence permits the use.  A family that fails
here is refused before it consumes a trial, a holdout, or a subscription.

``FEASIBLE`` means the family is worth preregistering.  It is not evidence of
edge, a forecast, or an authorisation, and nothing here observes a price,
contacts a venue, or moves money.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.arithmetic_guards import finite_number, invalid_safe, positive_integer
from quant_trade.ops.growth_feasibility import (
    MAXIMUM_CREDIBLE_NET_SHARPE,
    breakeven_gross_sharpe,
    turnover_cost_drag,
)

FamilyScreenStatus = Literal["FEASIBLE", "NO_GO", "INSUFFICIENT_EVIDENCE"]

#: Why a family cannot be run, named so a report can group by cause rather than
#: repeating prose.  Mirrors the vocabulary of :mod:`quant_trade.v9.small_capital`.
BindingConstraint = Literal[
    "min_notional",
    "indivisible_unit",
    "cost_drag",
    "fixed_data_cost",
    "data_license",
    "no_point_in_time_data",
    "none",
]

#: A licence state.  ``UNKNOWN`` is missing evidence, never permission.
LicenceStatus = Literal["NOT_REQUIRED", "COMMERCIAL_VERIFIED", "NON_COMMERCIAL", "UNKNOWN"]

_LICENCE_STATES: frozenset[str] = frozenset(
    {"NOT_REQUIRED", "COMMERCIAL_VERIFIED", "NON_COMMERCIAL", "UNKNOWN"}
)

#: One round trip is two fills.
FILLS_PER_ROUND_TRIP = 2


@dataclass(frozen=True, slots=True)
class StrategyFamilyProfile:
    """A family's declared execution shape.  Every field is an assumption."""

    family_id: str | None
    capital_usd: float | None
    concurrent_positions: int | None
    annual_rebalances: float | None
    portfolio_fraction_traded_per_rebalance: float | None
    per_side_cost_bps: float | None
    minimum_notional_usd: float | None
    reference_unit_price_usd: float | None
    fractional_units_supported: bool | None
    monthly_data_cost_usd: float | None
    data_licence_status: str | None
    point_in_time_data_available: bool | None
    assumed_annual_volatility: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FamilyScreen:
    """Hash-bound screening result.  It authorises nothing and claims no edge."""

    profile: StrategyFamilyProfile
    status: FamilyScreenStatus
    binding_constraint: BindingConstraint
    capital_per_position_usd: float | None
    minimum_executable_outlay_usd: float | None
    minimum_capital_for_this_shape_usd: float | None
    annual_round_trips: float | None
    annual_turnover_cost_fraction: float | None
    annual_fixed_cost_fraction: float | None
    total_annual_cost_fraction: float | None
    breakeven_gross_sharpe: float | None
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    profile_digest: str
    screen_digest: str

    @property
    def feasible(self) -> bool:
        return self.status == "FEASIBLE"

    def is_verified(self) -> bool:
        """Reject a forged or mutated result by recomputing it from its profile."""
        try:
            return self == screen_family(self.profile)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "assessment": "STRATEGY_FAMILY_CAPITAL_SCREEN",
            "evidence_class": "ASSUMPTION",
            "status": self.status,
            "feasible": self.feasible,
            "binding_constraint": self.binding_constraint,
            "capital_per_position_usd": self.capital_per_position_usd,
            "minimum_executable_outlay_usd": self.minimum_executable_outlay_usd,
            "minimum_capital_for_this_shape_usd": self.minimum_capital_for_this_shape_usd,
            "annual_round_trips": self.annual_round_trips,
            "annual_turnover_cost_fraction": self.annual_turnover_cost_fraction,
            "annual_fixed_cost_fraction": self.annual_fixed_cost_fraction,
            "total_annual_cost_fraction": self.total_annual_cost_fraction,
            "breakeven_gross_sharpe": self.breakeven_gross_sharpe,
            "maximum_credible_net_sharpe": MAXIMUM_CREDIBLE_NET_SHARPE,
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "profile_digest": self.profile_digest,
            "screen_digest": self.screen_digest,
            "edge_established": False,
            "preregistration_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
        }


def _boolean(value: Any, name: str, missing: list[str], blockers: list[str]) -> bool | None:
    if value is None:
        missing.append(name)
        return None
    if not isinstance(value, bool):
        blockers.append(f"{name} must be a boolean")
        return None
    return value


def _licence(value: Any, missing: list[str], blockers: list[str]) -> str | None:
    if value is None:
        missing.append("data_licence_status")
        return None
    if not isinstance(value, str) or value not in _LICENCE_STATES:
        allowed = ", ".join(sorted(_LICENCE_STATES))
        blockers.append(f"data_licence_status must be one of {allowed}")
        return None
    return value


def _screen_payload(screen: dict[str, Any], profile_digest: str) -> dict[str, Any]:
    return {**screen, "profile_digest": profile_digest, "real_money_authorized": False}


def screen_family(profile: StrategyFamilyProfile) -> FamilyScreen:
    """Decide whether a family can be executed at all, before opening any data."""
    if not isinstance(profile, StrategyFamilyProfile):
        raise TypeError("profile must be StrategyFamilyProfile")
    missing: list[str] = []
    blockers: list[str] = []

    if profile.family_id is None:
        missing.append("family_id")
    elif not isinstance(profile.family_id, str) or not profile.family_id.strip():
        blockers.append("family_id must be a non-empty name")

    capital = finite_number(profile.capital_usd, "capital_usd", missing, blockers)
    positions = positive_integer(
        profile.concurrent_positions, "concurrent_positions", missing, blockers
    )
    rebalances = finite_number(
        profile.annual_rebalances, "annual_rebalances", missing, blockers, allow_zero=True
    )
    traded_fraction = finite_number(
        profile.portfolio_fraction_traded_per_rebalance,
        "portfolio_fraction_traded_per_rebalance",
        missing,
        blockers,
    )
    per_side_bps = finite_number(
        profile.per_side_cost_bps, "per_side_cost_bps", missing, blockers, allow_zero=True
    )
    min_notional = finite_number(
        profile.minimum_notional_usd, "minimum_notional_usd", missing, blockers, allow_zero=True
    )
    unit_price = finite_number(
        profile.reference_unit_price_usd, "reference_unit_price_usd", missing, blockers
    )
    fractional = _boolean(
        profile.fractional_units_supported, "fractional_units_supported", missing, blockers
    )
    data_cost = finite_number(
        profile.monthly_data_cost_usd, "monthly_data_cost_usd", missing, blockers, allow_zero=True
    )
    licence = _licence(profile.data_licence_status, missing, blockers)
    point_in_time = _boolean(
        profile.point_in_time_data_available, "point_in_time_data_available", missing, blockers
    )
    volatility = finite_number(
        profile.assumed_annual_volatility, "assumed_annual_volatility", missing, blockers
    )

    if traded_fraction is not None and traded_fraction > 1.0:
        blockers.append("portfolio_fraction_traded_per_rebalance cannot exceed 1")

    per_position = capital / positions if capital is not None and positions is not None else None
    # An indivisible instrument cannot be bought below the price of one unit, so
    # that price, not the venue minimum, is what actually binds.
    minimum_outlay: float | None = None
    if min_notional is not None and unit_price is not None and fractional is not None:
        minimum_outlay = min_notional if fractional else max(min_notional, unit_price)
    minimum_capital: float | None = None
    if minimum_outlay is not None and positions is not None:
        minimum_capital = minimum_outlay * positions

    round_trips: float | None = None
    if rebalances is not None and traded_fraction is not None:
        round_trips = rebalances * traded_fraction
    turnover_fraction: float | None = None
    if round_trips is not None and per_side_bps is not None:
        turnover_fraction = turnover_cost_drag(round_trips, per_side_bps * FILLS_PER_ROUND_TRIP)
    fixed_fraction: float | None = None
    if data_cost is not None and capital is not None:
        fixed_fraction = data_cost * 12.0 / capital
    total_fraction: float | None = None
    if turnover_fraction is not None and fixed_fraction is not None:
        total_fraction = turnover_fraction + fixed_fraction
    breakeven: float | None = None
    if total_fraction is not None and volatility is not None:
        breakeven = breakeven_gross_sharpe(total_fraction, volatility)

    constraint: BindingConstraint = "none"
    if licence == "NON_COMMERCIAL":
        constraint = "data_license"
        blockers.append(
            "the only documented licence for this source forbids commercial use, "
            "so the data cannot be used to trade an own account"
        )
    if point_in_time is False:
        constraint = "no_point_in_time_data"
        blockers.append(
            "no point-in-time source is available, so survivorship and restatement "
            "look-ahead cannot be excluded by construction"
        )
    if fixed_fraction is not None and fixed_fraction >= 1.0:
        constraint = "fixed_data_cost"
        blockers.append(
            f"fixed data cost is {fixed_fraction:.0%} of the capital per year; "
            "it has to be paid from income earned outside the account"
        )
    if breakeven is not None and breakeven > MAXIMUM_CREDIBLE_NET_SHARPE:
        constraint = "cost_drag"
        blockers.append(
            f"frictions alone consume a gross Sharpe of {breakeven:.2f}, above the "
            f"declared screening ceiling of {MAXIMUM_CREDIBLE_NET_SHARPE:g}"
        )
    if per_position is not None and minimum_outlay is not None and per_position < minimum_outlay:
        indivisible = bool(fractional is False and unit_price is not None and unit_price > 0)
        constraint = "indivisible_unit" if indivisible else "min_notional"
        reason = (
            f"each position gets ${per_position:,.2f} but the smallest executable "
            f"outlay is ${minimum_outlay:,.2f}"
        )
        if minimum_capital is not None:
            reason += f"; this shape needs at least ${minimum_capital:,.2f}"
        blockers.append(reason)

    blockers_tuple = tuple(sorted(set(blockers)))
    missing_tuple = tuple(sorted(set(missing)))
    if blockers_tuple:
        status: FamilyScreenStatus = "NO_GO"
    elif missing_tuple or licence == "UNKNOWN":
        status = "INSUFFICIENT_EVIDENCE"
        if licence == "UNKNOWN":
            missing_tuple = tuple(sorted({*missing_tuple, "verified_data_licence"}))
    else:
        status = "FEASIBLE"

    profile_digest = sha256_of_text(canonical_dumps(invalid_safe(profile.to_dict())))
    screen_body: dict[str, Any] = {
        "status": status,
        "binding_constraint": constraint,
        "capital_per_position_usd": per_position,
        "minimum_executable_outlay_usd": minimum_outlay,
        "minimum_capital_for_this_shape_usd": minimum_capital,
        "annual_round_trips": round_trips,
        "annual_turnover_cost_fraction": turnover_fraction,
        "annual_fixed_cost_fraction": fixed_fraction,
        "total_annual_cost_fraction": total_fraction,
        "breakeven_gross_sharpe": breakeven,
        "blocking_conditions": list(blockers_tuple),
        "missing_conditions": list(missing_tuple),
    }
    screen_digest = sha256_of_text(canonical_dumps(_screen_payload(screen_body, profile_digest)))
    return FamilyScreen(
        profile=profile,
        status=status,
        binding_constraint=constraint,
        capital_per_position_usd=per_position,
        minimum_executable_outlay_usd=minimum_outlay,
        minimum_capital_for_this_shape_usd=minimum_capital,
        annual_round_trips=round_trips,
        annual_turnover_cost_fraction=turnover_fraction,
        annual_fixed_cost_fraction=fixed_fraction,
        total_annual_cost_fraction=total_fraction,
        breakeven_gross_sharpe=breakeven,
        blocking_conditions=blockers_tuple,
        missing_conditions=missing_tuple,
        profile_digest=profile_digest,
        screen_digest=screen_digest,
    )


def screen_families(profiles: tuple[StrategyFamilyProfile, ...]) -> tuple[FamilyScreen, ...]:
    """Screen a whole matrix in declaration order, with no cross-family effects."""
    return tuple(screen_family(profile) for profile in profiles)


def minimum_capital_for_shape(
    *,
    concurrent_positions: int,
    minimum_notional_usd: float,
    reference_unit_price_usd: float,
    fractional_units_supported: bool,
) -> float:
    """Smallest capital at which every position clears its minimum outlay."""
    if concurrent_positions <= 0:
        raise ValueError("concurrent_positions must be positive")
    for name, value in (
        ("minimum_notional_usd", minimum_notional_usd),
        ("reference_unit_price_usd", reference_unit_price_usd),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    outlay = (
        minimum_notional_usd
        if fractional_units_supported
        else max(minimum_notional_usd, reference_unit_price_usd)
    )
    return outlay * concurrent_positions


__all__ = [
    "FILLS_PER_ROUND_TRIP",
    "BindingConstraint",
    "FamilyScreen",
    "FamilyScreenStatus",
    "LicenceStatus",
    "StrategyFamilyProfile",
    "minimum_capital_for_shape",
    "screen_families",
    "screen_family",
]
