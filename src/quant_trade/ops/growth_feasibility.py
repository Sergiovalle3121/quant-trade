"""Fail-closed arithmetic for "can this capital reach this target in this time?".

:mod:`quant_trade.ops.wealth_plan` answers the deterministic half of that
question: what compound return a goal implies, and whether a canary satisfies
the sealed diversification constraints.  It has no stochastic layer, so it
cannot say whether a required return is *attainable* by any process at all.

This module supplies that layer, under one explicitly declared model: excess
log-wealth over a horizon ``T`` years is normal with mean ``(S*sigma -
sigma**2/2) * T`` and standard deviation ``sigma * sqrt(T)``, for a net Sharpe
``S`` and an annual volatility ``sigma``.

The single most important consequence, and the reason this module exists, is
that raising volatility does **not** monotonically raise the chance of a large
multiple.  The variance drag ``-sigma**2/2`` eventually dominates, so the
probability of reaching a multiple ``M`` is maximised at a finite
``sigma* = sqrt(2*ln(M)/T)`` and can never exceed ``1 - Phi(sqrt(2*ln(M)) -
S*sqrt(T))``.  For a large multiple over a short horizon that ceiling is
minuscule unless the Sharpe is implausibly high, and no amount of leverage,
position sizing, or software changes it.

Nothing here selects a security, observes a price, forecasts a return, contacts
a venue, or authorises real money.  Every number is derived from a caller's
declared assumptions and is stamped ``ASSUMPTION`` accordingly; a caller-supplied
Sharpe can never make a target ``FEASIBLE`` beyond the declared screening
ceiling, and ``FEASIBLE`` itself means only that the supplied arithmetic
contains no contradiction.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.metrics.normal import normal_cdf, normal_inverse_cdf
from quant_trade.ops.arithmetic_guards import finite_number, invalid_safe, positive_integer
from quant_trade.ops.wealth_plan import EXTREME_TARGET_MULTIPLE

GrowthFeasibilityStatus = Literal["FEASIBLE", "NO_GO", "INSUFFICIENT_EVIDENCE"]
HorizonBasis = Literal["CALENDAR", "TRADING"]

#: Days per year under each supported horizon basis.
CALENDAR_DAYS_PER_YEAR = 365.0
TRADING_SESSIONS_PER_YEAR = 252.0

#: The probability at which this module is willing to call a target "reachable".
#: Below it, a target is a lottery ticket rather than a plan.
MINIMUM_SUCCESS_PROBABILITY = 0.05

#: A declared screening ceiling on net-of-cost Sharpe, not a measurement.  No
#: publicly documented, capacity-unconstrained, retail-accessible strategy has
#: sustained a net Sharpe above this; a requirement exceeding it is treated as
#: unmet rather than as an optimisation target.  Raising this constant to make a
#: target pass would be fabricating a gate, not discovering an edge.
MAXIMUM_CREDIBLE_NET_SHARPE = 3.0

#: Kelly fraction beyond which sizing is no longer growth-optimal in this model.
MAXIMUM_KELLY_FRACTION = 2.0

_BASIS_DAYS_PER_YEAR: dict[str, float] = {
    "CALENDAR": CALENDAR_DAYS_PER_YEAR,
    "TRADING": TRADING_SESSIONS_PER_YEAR,
}


@dataclass(frozen=True, slots=True)
class TargetFeasibilityRequest:
    """Operator-declared assumptions.  Every field is an assumption, not evidence."""

    starting_capital_usd: float | None
    target_capital_usd: float | None
    horizon_days: int | None
    horizon_basis: str | None
    assumed_net_sharpe: float | None
    assumed_annual_volatility: float | None
    kelly_fraction: float | None
    annual_round_trips: float | None
    round_trip_cost_bps: float | None
    monthly_fixed_cost_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompoundingRequirement:
    """What the target demands per period, with no claim that it is attainable."""

    target_multiple: float
    horizon_days: int
    horizon_basis: str
    horizon_years: float
    required_return_per_period_fraction: float
    equivalent_trading_sessions: float
    required_return_per_trading_session_fraction: float
    extreme_target_multiple: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LognormalReachability:
    """The ceiling on success probability, and the Sharpe each ceiling implies."""

    probability_optimal_annual_volatility: float
    maximum_attainable_probability: float
    maximum_attainable_probability_one_in: float | None
    required_sharpe_for_minimum_probability: float
    required_sharpe_for_even_odds: float
    hit_probability_at_assumed_volatility: float | None
    median_terminal_wealth_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CostBurden:
    """What frictions cost before any signal is considered."""

    annual_turnover_cost_fraction: float | None
    annual_fixed_cost_fraction_of_capital: float | None
    monthly_fixed_cost_fraction_of_capital: float | None
    total_annual_cost_fraction: float | None
    breakeven_gross_sharpe: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GeometricGrowthPath:
    """How long the target takes at a growth-optimal size, if the edge is real."""

    kelly_fraction: float
    annual_log_growth_rate: float
    years_to_target_multiple: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetFeasibility:
    """Hash-bound, deeply immutable assessment; it authorises nothing."""

    request: TargetFeasibilityRequest
    status: GrowthFeasibilityStatus
    compounding: CompoundingRequirement | None
    reachability: LognormalReachability | None
    costs: CostBurden | None
    growth_path: GeometricGrowthPath | None
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    request_digest: str
    assessment_digest: str

    @property
    def feasible(self) -> bool:
        return self.status == "FEASIBLE"

    def is_verified(self) -> bool:
        """Reject a forged or mutated result by recomputing it from its request."""
        try:
            return self == evaluate_target_feasibility(self.request)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "assessment": "GROWTH_TARGET_FEASIBILITY",
            "evidence_class": "ASSUMPTION",
            "status": self.status,
            "feasible": self.feasible,
            "declared_model": (
                "lognormal excess wealth: log return over the horizon is normal with "
                "mean (sharpe*vol - vol^2/2)*years and sd vol*sqrt(years)"
            ),
            "screening_constants": {
                "minimum_success_probability": MINIMUM_SUCCESS_PROBABILITY,
                "maximum_credible_net_sharpe": MAXIMUM_CREDIBLE_NET_SHARPE,
                "extreme_target_multiple": EXTREME_TARGET_MULTIPLE,
            },
            "compounding": self.compounding.to_dict() if self.compounding else None,
            "reachability": self.reachability.to_dict() if self.reachability else None,
            "costs": self.costs.to_dict() if self.costs else None,
            "growth_path": self.growth_path.to_dict() if self.growth_path else None,
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "request_digest": self.request_digest,
            "assessment_digest": self.assessment_digest,
            "automatic_transition_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
            "profit_claim_authorized": False,
        }


def variance_optimal_volatility(target_multiple: float, horizon_years: float) -> float:
    """The annual volatility that maximises P(reaching the multiple), not a target.

    Above this level the variance drag costs more median growth than the extra
    dispersion buys, so more risk lowers the chance of success.
    """
    _require_multiple(target_multiple)
    _require_positive(horizon_years, "horizon_years")
    return math.sqrt(2.0 * math.log(target_multiple) / horizon_years)


def maximum_hit_probability(
    target_multiple: float,
    horizon_years: float,
    net_sharpe: float,
) -> float:
    """The best achievable P(reaching the multiple) over every volatility."""
    _require_multiple(target_multiple)
    _require_positive(horizon_years, "horizon_years")
    best_standardised = math.sqrt(2.0 * math.log(target_multiple)) - net_sharpe * math.sqrt(
        horizon_years
    )
    return 1.0 - normal_cdf(best_standardised)


def hit_probability(
    target_multiple: float,
    horizon_years: float,
    net_sharpe: float,
    annual_volatility: float,
) -> float:
    """P(reaching the multiple) at one specific volatility."""
    _require_multiple(target_multiple)
    _require_positive(horizon_years, "horizon_years")
    _require_positive(annual_volatility, "annual_volatility")
    root_years = math.sqrt(horizon_years)
    standardised = (
        math.log(target_multiple) / (annual_volatility * root_years)
        + annual_volatility * root_years / 2.0
        - net_sharpe * root_years
    )
    return 1.0 - normal_cdf(standardised)


def required_sharpe_for_probability(
    target_multiple: float,
    horizon_years: float,
    probability: float,
) -> float:
    """The net Sharpe needed for the stated success probability, at best sizing."""
    _require_multiple(target_multiple)
    _require_positive(horizon_years, "horizon_years")
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be in (0, 1)")
    quantile = normal_inverse_cdf(1.0 - probability)
    return (math.sqrt(2.0 * math.log(target_multiple)) - quantile) / math.sqrt(horizon_years)


def median_log_growth(net_sharpe: float, annual_volatility: float, horizon_years: float) -> float:
    """Median log return over the horizon, including the variance drag."""
    _require_positive(horizon_years, "horizon_years")
    return (net_sharpe * annual_volatility - annual_volatility**2 / 2.0) * horizon_years


def kelly_growth_rate(net_sharpe: float, kelly_fraction: float) -> float:
    """Annual log-growth rate at a fraction of the growth-optimal *long* position.

    Full Kelly gives ``S**2 / 2``; half Kelly gives ``3 * S**2 / 8``.  Beyond
    twice Kelly the rate is negative: sizing past the optimum destroys capital
    even when the edge is real.

    At a non-positive Sharpe the unconstrained Kelly position is a short, which
    this repository does not permit.  Under the long-only constraint the best
    available position is then no position at all, so the rate is exactly zero —
    never the positive number that ``S**2`` would otherwise produce by
    discarding the sign of the edge.
    """
    if net_sharpe <= 0.0:
        return 0.0
    return net_sharpe**2 * (kelly_fraction - kelly_fraction**2 / 2.0)


def years_to_multiple(
    target_multiple: float,
    net_sharpe: float,
    kelly_fraction: float,
) -> float | None:
    """Time to compound to the multiple at that growth rate, or ``None`` if never."""
    _require_multiple(target_multiple)
    rate = kelly_growth_rate(net_sharpe, kelly_fraction)
    if rate <= 0.0:
        return None
    return math.log(target_multiple) / rate


def turnover_cost_drag(annual_round_trips: float, round_trip_cost_bps: float) -> float:
    """Annual fraction of capital paid away in frictions at that turnover."""
    return annual_round_trips * round_trip_cost_bps / 10_000.0


def breakeven_gross_sharpe(annual_cost_fraction: float, annual_volatility: float) -> float:
    """Gross Sharpe consumed by costs alone, before any net return exists."""
    _require_positive(annual_volatility, "annual_volatility")
    return annual_cost_fraction / annual_volatility


def _require_multiple(target_multiple: float) -> None:
    if not math.isfinite(target_multiple) or target_multiple <= 1.0:
        raise ValueError("target_multiple must be finite and greater than 1")


def _require_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")


def _horizon_basis(value: Any, missing: list[str], blockers: list[str]) -> str | None:
    if value is None:
        missing.append("horizon_basis")
        return None
    if not isinstance(value, str) or value not in _BASIS_DAYS_PER_YEAR:
        blockers.append("horizon_basis must be exactly CALENDAR or TRADING")
        return None
    return value


def _compounding(
    *,
    start: float,
    target: float,
    horizon_days: int,
    basis: str,
    blockers: list[str],
) -> CompoundingRequirement | None:
    multiple = target / start
    if not math.isfinite(multiple) or multiple <= 1.0:
        blockers.append("target_capital_usd must exceed starting_capital_usd")
        return None
    days_per_year = _BASIS_DAYS_PER_YEAR[basis]
    horizon_years = horizon_days / days_per_year
    log_multiple = math.log(multiple)
    sessions = horizon_days * (TRADING_SESSIONS_PER_YEAR / days_per_year)
    if sessions < 1.0:
        blockers.append("the horizon must contain at least one trading session")
        return None
    return CompoundingRequirement(
        target_multiple=multiple,
        horizon_days=horizon_days,
        horizon_basis=basis,
        horizon_years=horizon_years,
        required_return_per_period_fraction=math.expm1(log_multiple / horizon_days),
        equivalent_trading_sessions=sessions,
        required_return_per_trading_session_fraction=math.expm1(log_multiple / sessions),
        extreme_target_multiple=multiple >= EXTREME_TARGET_MULTIPLE,
    )


def _reachability(
    *,
    compounding: CompoundingRequirement,
    start: float,
    sharpe: float | None,
    volatility: float | None,
) -> LognormalReachability:
    multiple = compounding.target_multiple
    years = compounding.horizon_years
    effective_sharpe = 0.0 if sharpe is None else sharpe
    ceiling = maximum_hit_probability(multiple, years, effective_sharpe)
    one_in = 1.0 / ceiling if ceiling > 0.0 else None
    at_volatility: float | None = None
    median_wealth: float | None = None
    if volatility is not None:
        at_volatility = hit_probability(multiple, years, effective_sharpe, volatility)
        log_median = median_log_growth(effective_sharpe, volatility, years)
        median_wealth = start * math.exp(log_median) if log_median > -700.0 else 0.0
    return LognormalReachability(
        probability_optimal_annual_volatility=variance_optimal_volatility(multiple, years),
        maximum_attainable_probability=ceiling,
        maximum_attainable_probability_one_in=one_in,
        required_sharpe_for_minimum_probability=required_sharpe_for_probability(
            multiple, years, MINIMUM_SUCCESS_PROBABILITY
        ),
        required_sharpe_for_even_odds=required_sharpe_for_probability(multiple, years, 0.5),
        hit_probability_at_assumed_volatility=at_volatility,
        median_terminal_wealth_usd=median_wealth,
    )


def _costs(
    *,
    start: float,
    volatility: float | None,
    annual_round_trips: float | None,
    round_trip_cost_bps: float | None,
    monthly_fixed_cost_usd: float | None,
) -> CostBurden:
    turnover_drag: float | None = None
    if annual_round_trips is not None and round_trip_cost_bps is not None:
        turnover_drag = turnover_cost_drag(annual_round_trips, round_trip_cost_bps)
    monthly_fixed: float | None = None
    annual_fixed: float | None = None
    if monthly_fixed_cost_usd is not None:
        monthly_fixed = monthly_fixed_cost_usd / start
        annual_fixed = monthly_fixed * 12.0
    total: float | None = None
    if turnover_drag is not None or annual_fixed is not None:
        total = (turnover_drag or 0.0) + (annual_fixed or 0.0)
    breakeven: float | None = None
    if total is not None and volatility is not None:
        breakeven = breakeven_gross_sharpe(total, volatility)
    return CostBurden(
        annual_turnover_cost_fraction=turnover_drag,
        annual_fixed_cost_fraction_of_capital=annual_fixed,
        monthly_fixed_cost_fraction_of_capital=monthly_fixed,
        total_annual_cost_fraction=total,
        breakeven_gross_sharpe=breakeven,
    )


def _assessment_payload(
    *,
    status: GrowthFeasibilityStatus,
    compounding: CompoundingRequirement | None,
    reachability: LognormalReachability | None,
    costs: CostBurden | None,
    growth_path: GeometricGrowthPath | None,
    blockers: tuple[str, ...],
    missing: tuple[str, ...],
    request_digest: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "compounding": compounding.to_dict() if compounding else None,
        "reachability": reachability.to_dict() if reachability else None,
        "costs": costs.to_dict() if costs else None,
        "growth_path": growth_path.to_dict() if growth_path else None,
        "blocking_conditions": list(blockers),
        "missing_conditions": list(missing),
        "request_digest": request_digest,
        "real_money_authorized": False,
    }


def evaluate_target_feasibility(request: TargetFeasibilityRequest) -> TargetFeasibility:
    """Evaluate whether a target is reachable under declared assumptions.

    Returns ``NO_GO`` when the supplied arithmetic is self-contradictory or the
    target provably requires more than the declared screening ceiling,
    ``INSUFFICIENT_EVIDENCE`` when a required input is absent, and ``FEASIBLE``
    only to mean that nothing in the supplied arithmetic contradicts itself.
    ``FEASIBLE`` is never a profit claim, a recommendation, or an authorisation.
    """
    if not isinstance(request, TargetFeasibilityRequest):
        raise TypeError("request must be TargetFeasibilityRequest")
    missing: list[str] = []
    blockers: list[str] = []

    start = finite_number(request.starting_capital_usd, "starting_capital_usd", missing, blockers)
    target = finite_number(request.target_capital_usd, "target_capital_usd", missing, blockers)
    horizon_days = positive_integer(request.horizon_days, "horizon_days", missing, blockers)
    basis = _horizon_basis(request.horizon_basis, missing, blockers)
    sharpe = finite_number(
        request.assumed_net_sharpe,
        "assumed_net_sharpe",
        missing,
        blockers,
        allow_zero=True,
        allow_negative=True,
    )
    volatility = finite_number(
        request.assumed_annual_volatility, "assumed_annual_volatility", missing, blockers
    )
    kelly = finite_number(request.kelly_fraction, "kelly_fraction", missing, blockers)
    round_trips = finite_number(
        request.annual_round_trips, "annual_round_trips", missing, blockers, allow_zero=True
    )
    cost_bps = finite_number(
        request.round_trip_cost_bps, "round_trip_cost_bps", missing, blockers, allow_zero=True
    )
    fixed_cost = finite_number(
        request.monthly_fixed_cost_usd, "monthly_fixed_cost_usd", missing, blockers, allow_zero=True
    )

    if kelly is not None and kelly > MAXIMUM_KELLY_FRACTION:
        blockers.append(
            f"kelly_fraction {kelly:g} exceeds {MAXIMUM_KELLY_FRACTION:g}, "
            "where the growth rate is negative even with a real edge"
        )

    compounding: CompoundingRequirement | None = None
    if start is not None and target is not None and horizon_days is not None and basis is not None:
        compounding = _compounding(
            start=start,
            target=target,
            horizon_days=horizon_days,
            basis=basis,
            blockers=blockers,
        )

    reachability: LognormalReachability | None = None
    if compounding is not None and start is not None:
        reachability = _reachability(
            compounding=compounding, start=start, sharpe=sharpe, volatility=volatility
        )
        required = reachability.required_sharpe_for_minimum_probability
        if required > MAXIMUM_CREDIBLE_NET_SHARPE:
            blockers.append(
                f"reaching {compounding.target_multiple:.6g}x in "
                f"{compounding.horizon_days} {compounding.horizon_basis.lower()} days with at "
                f"least {MINIMUM_SUCCESS_PROBABILITY:.0%} probability requires a net Sharpe of "
                f"{required:.2f}, above the declared screening ceiling of "
                f"{MAXIMUM_CREDIBLE_NET_SHARPE:g}"
            )

    costs: CostBurden | None = None
    if start is not None:
        costs = _costs(
            start=start,
            volatility=volatility,
            annual_round_trips=round_trips,
            round_trip_cost_bps=cost_bps,
            monthly_fixed_cost_usd=fixed_cost,
        )
        if costs.annual_fixed_cost_fraction_of_capital is not None:
            fixed_fraction = costs.annual_fixed_cost_fraction_of_capital
            if fixed_fraction >= 1.0:
                blockers.append(
                    f"fixed costs consume {fixed_fraction:.0%} of the capital per year; "
                    "they must be paid from income earned outside the account"
                )
        if (
            costs.breakeven_gross_sharpe is not None
            and costs.breakeven_gross_sharpe > MAXIMUM_CREDIBLE_NET_SHARPE
        ):
            blockers.append(
                f"costs alone consume a gross Sharpe of {costs.breakeven_gross_sharpe:.2f}, "
                f"above the declared screening ceiling of {MAXIMUM_CREDIBLE_NET_SHARPE:g}"
            )

    growth_path: GeometricGrowthPath | None = None
    if compounding is not None and sharpe is not None and kelly is not None:
        growth_path = GeometricGrowthPath(
            kelly_fraction=kelly,
            annual_log_growth_rate=kelly_growth_rate(sharpe, kelly),
            years_to_target_multiple=years_to_multiple(compounding.target_multiple, sharpe, kelly),
        )

    blockers_tuple = tuple(sorted(set(blockers)))
    missing_tuple = tuple(sorted(set(missing)))
    if blockers_tuple:
        status: GrowthFeasibilityStatus = "NO_GO"
    elif missing_tuple:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "FEASIBLE"

    request_digest = sha256_of_text(canonical_dumps(invalid_safe(request.to_dict())))
    assessment_digest = sha256_of_text(
        canonical_dumps(
            _assessment_payload(
                status=status,
                compounding=compounding,
                reachability=reachability,
                costs=costs,
                growth_path=growth_path,
                blockers=blockers_tuple,
                missing=missing_tuple,
                request_digest=request_digest,
            )
        )
    )
    return TargetFeasibility(
        request=request,
        status=status,
        compounding=compounding,
        reachability=reachability,
        costs=costs,
        growth_path=growth_path,
        blocking_conditions=blockers_tuple,
        missing_conditions=missing_tuple,
        request_digest=request_digest,
        assessment_digest=assessment_digest,
    )


__all__ = [
    "CALENDAR_DAYS_PER_YEAR",
    "CompoundingRequirement",
    "CostBurden",
    "GeometricGrowthPath",
    "GrowthFeasibilityStatus",
    "HorizonBasis",
    "LognormalReachability",
    "MAXIMUM_CREDIBLE_NET_SHARPE",
    "MAXIMUM_KELLY_FRACTION",
    "MINIMUM_SUCCESS_PROBABILITY",
    "TRADING_SESSIONS_PER_YEAR",
    "TargetFeasibility",
    "TargetFeasibilityRequest",
    "breakeven_gross_sharpe",
    "evaluate_target_feasibility",
    "hit_probability",
    "kelly_growth_rate",
    "maximum_hit_probability",
    "median_log_growth",
    "required_sharpe_for_probability",
    "turnover_cost_drag",
    "variance_optimal_volatility",
    "years_to_multiple",
]
