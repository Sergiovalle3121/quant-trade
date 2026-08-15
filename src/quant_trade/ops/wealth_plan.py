"""Fail-closed wealth-planning arithmetic for a small research account.

The objects in this module separate total risk capital from a proposed canary,
test whether the canary can satisfy the sealed diversification constraints,
and make goal arithmetic explicit.  They do not select securities, forecast a
return, connect to a venue, or authorise real-money trading.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.arithmetic_guards import (
    finite_number,
    invalid_safe,
    positive_integer,
    qualified_type_name,
)

# Single implementation of the input guards, shared with the other fail-closed
# arithmetic modules; these aliases keep this module's call sites unchanged.
_qualified_type_name = qualified_type_name
_invalid_safe = invalid_safe
_number = finite_number
_positive_integer = positive_integer

WealthPlanStatus = Literal["FEASIBLE", "NO_GO", "INSUFFICIENT_EVIDENCE"]
Workstream = Literal["AUDIT_REVENUE", "H2_RESEARCH"]

MAXIMUM_CANARY_FRACTION = 0.10
MAXIMUM_CANARY_USD = 500.0
MAXIMUM_ASSET_FRACTION = 0.05
MINIMUM_DISTINCT_ASSETS = 20
EXTREME_TARGET_MULTIPLE = 1_000.0
_CURRENCY_PATTERN = re.compile(r"[A-Z][A-Z0-9]{2,9}")


@dataclass(frozen=True, slots=True)
class GrowthGoal:
    """An illustrative same-currency goal, never a return forecast.

    ``starting_amount`` and ``target_amount`` must use ``currency``.  A caller
    must perform any USD/MXN conversion from separately verified evidence
    before constructing this object; this module deliberately assumes no FX
    rate.
    """

    starting_amount: float | None
    target_amount: float | None
    currency: str | None
    horizon_months: int | None
    illustrative_annual_return_fraction: float | None
    monthly_contribution: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WealthPlanRequest:
    """Operator-supplied assumptions for capital and goal arithmetic."""

    total_risk_capital_usd: float | None
    proposed_canary_usd: float | None
    eligible_asset_count: int | None
    minimum_notional_usd: float | None
    minimum_notional_cushion_fraction: float | None
    goal: GrowthGoal | None

    def to_dict(self) -> dict[str, Any]:
        if isinstance(self.goal, GrowthGoal):
            goal: Any = self.goal.to_dict()
        elif self.goal is None:
            goal = None
        else:
            goal = {"__invalid_type__": _qualified_type_name(self.goal)}
        return {
            "total_risk_capital_usd": self.total_risk_capital_usd,
            "proposed_canary_usd": self.proposed_canary_usd,
            "eligible_asset_count": self.eligible_asset_count,
            "minimum_notional_usd": self.minimum_notional_usd,
            "minimum_notional_cushion_fraction": self.minimum_notional_cushion_fraction,
            "goal": goal,
        }


@dataclass(frozen=True, slots=True)
class GoalProjection:
    """Transparent consequences of a goal and explicitly labelled assumptions."""

    currency: str
    target_multiple: float
    required_horizon_return_fraction: float
    required_monthly_compound_return_fraction: float
    illustrative_months_to_target: int | None
    required_monthly_contribution_for_horizon: float
    extreme_1000x_target: bool
    impossible_1000x_one_month_target: bool
    warning: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RoadmapItem:
    """One bounded, evidence-producing step; no item can route an order."""

    sequence: int
    workstream: Workstream
    action: str
    acceptance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


WEALTH_ROADMAP: tuple[RoadmapItem, ...] = (
    RoadmapItem(
        sequence=1,
        workstream="AUDIT_REVENUE",
        action="Package the existing bias, cost, provenance, and holdout checks as one audit.",
        acceptance="A deterministic HTML/JSON audit is reproducible from a clean checkout.",
    ),
    RoadmapItem(
        sequence=2,
        workstream="AUDIT_REVENUE",
        action="Validate demand with independent pilot users before building billing or hosting.",
        acceptance="Pilots provide recorded problem evidence; revenue is never assumed.",
    ),
    RoadmapItem(
        sequence=3,
        workstream="H2_RESEARCH",
        action="Seal the H2 death-avoidance experiment against a causal Binance-only panel.",
        acceptance="The immutable spec fixes data, control, costs, split, and refutation first.",
    ),
    RoadmapItem(
        sequence=4,
        workstream="H2_RESEARCH",
        action="Run H2 once in development and publish PASS, NO_GO, or insufficient evidence.",
        acceptance="No post-hoc variants and no holdout access follow a failed development result.",
    ),
    RoadmapItem(
        sequence=5,
        workstream="H2_RESEARCH",
        action="Use Demo and shadow validation only after economic evidence passes every gate.",
        acceptance="No real-money path is added by this plan.",
    ),
)


@dataclass(frozen=True, slots=True)
class WealthPlanAssessment:
    """Hash-bound, deeply immutable assessment of a wealth-plan request."""

    request: WealthPlanRequest
    status: WealthPlanStatus
    allowed_canary_usd: float | None
    per_asset_cap_usd: float | None
    minimum_per_asset_outlay_usd: float | None
    minimum_canary_usd: float | None
    minimum_total_risk_capital_usd: float | None
    required_total_risk_capital_usd_for_proposed_canary: float | None
    goal_projection: GoalProjection | None
    blocking_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    roadmap: tuple[RoadmapItem, ...]
    request_digest: str
    assessment_digest: str

    @property
    def feasible(self) -> bool:
        return self.status == "FEASIBLE"

    def is_verified(self) -> bool:
        """Reject a forged or mutated result by recomputing from its request."""
        try:
            return self == evaluate_wealth_plan(self.request)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "assessment": "SMALL_CAPITAL_WEALTH_PLAN",
            "status": self.status,
            "feasible": self.feasible,
            "constraints": {
                "maximum_canary_fraction": MAXIMUM_CANARY_FRACTION,
                "maximum_canary_usd": MAXIMUM_CANARY_USD,
                "maximum_asset_fraction": MAXIMUM_ASSET_FRACTION,
                "minimum_distinct_assets": MINIMUM_DISTINCT_ASSETS,
            },
            "allowed_canary_usd": self.allowed_canary_usd,
            "per_asset_cap_usd": self.per_asset_cap_usd,
            "minimum_per_asset_outlay_usd": self.minimum_per_asset_outlay_usd,
            "minimum_canary_usd": self.minimum_canary_usd,
            "minimum_total_risk_capital_usd": self.minimum_total_risk_capital_usd,
            "required_total_risk_capital_usd_for_proposed_canary": (
                self.required_total_risk_capital_usd_for_proposed_canary
            ),
            "goal_projection": (
                self.goal_projection.to_dict() if self.goal_projection is not None else None
            ),
            "blocking_conditions": list(self.blocking_conditions),
            "missing_conditions": list(self.missing_conditions),
            "roadmap": [item.to_dict() for item in self.roadmap],
            "request_digest": self.request_digest,
            "assessment_digest": self.assessment_digest,
            "automatic_transition_authorized": False,
            "external_action_authorized": False,
            "real_money_authorized": False,
            "profit_claim_authorized": False,
        }


def _currency(value: Any, missing: list[str], blockers: list[str]) -> str | None:
    if value is None or not isinstance(value, str) or not value:
        missing.append("goal.currency")
        return None
    if not _CURRENCY_PATTERN.fullmatch(value):
        blockers.append("goal.currency must be an explicit upper-case currency code")
        return None
    return value


def _months_to_target(
    starting: float,
    target: float,
    annual_return: float,
    contribution: float,
) -> int | None:
    if starting >= target:
        return 0
    monthly_rate = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    if monthly_rate == 0.0:
        if contribution == 0.0:
            return None
        return math.ceil((target - starting) / contribution)
    ratio = (target + contribution / monthly_rate) / (starting + contribution / monthly_rate)
    if ratio <= 1.0:
        return 0
    months = math.log(ratio) / math.log1p(monthly_rate)
    if not math.isfinite(months):
        return None
    return math.ceil(months - 1e-12)


def _required_contribution(
    starting: float,
    target: float,
    annual_return: float,
    horizon_months: int,
) -> float:
    monthly_rate = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    growth = (1.0 + monthly_rate) ** horizon_months
    shortfall = target - starting * growth
    if shortfall <= 0.0:
        return 0.0
    if monthly_rate == 0.0:
        return shortfall / horizon_months
    annuity_factor = (growth - 1.0) / monthly_rate
    return shortfall / annuity_factor


def _evaluate_goal(
    goal: GrowthGoal | None,
    missing: list[str],
    blockers: list[str],
) -> GoalProjection | None:
    if goal is None:
        missing.append("goal")
        return None
    if not isinstance(goal, GrowthGoal):
        blockers.append("goal must be GrowthGoal")
        return None
    starting = _number(goal.starting_amount, "goal.starting_amount", missing, blockers)
    target = _number(goal.target_amount, "goal.target_amount", missing, blockers)
    currency = _currency(goal.currency, missing, blockers)
    horizon = _positive_integer(goal.horizon_months, "goal.horizon_months", missing, blockers)
    annual_return = _number(
        goal.illustrative_annual_return_fraction,
        "goal.illustrative_annual_return_fraction",
        missing,
        blockers,
        allow_zero=True,
    )
    contribution = _number(
        goal.monthly_contribution,
        "goal.monthly_contribution",
        missing,
        blockers,
        allow_zero=True,
    )
    if None in (starting, target, currency, horizon, annual_return, contribution):
        return None
    assert isinstance(starting, float)
    assert isinstance(target, float)
    assert isinstance(currency, str)
    assert isinstance(horizon, int)
    assert isinstance(annual_return, float)
    assert isinstance(contribution, float)
    if target <= starting:
        blockers.append("goal.target_amount must exceed goal.starting_amount")
        return None

    try:
        target_multiple = target / starting
        required_monthly = target_multiple ** (1.0 / horizon) - 1.0
        required_horizon = target_multiple - 1.0
        months = _months_to_target(starting, target, annual_return, contribution)
        required_contribution = _required_contribution(starting, target, annual_return, horizon)
    except (OverflowError, ValueError, ZeroDivisionError):
        blockers.append("goal derived arithmetic must remain finite")
        return None
    if not all(
        math.isfinite(value)
        for value in (
            target_multiple,
            required_monthly,
            required_horizon,
            required_contribution,
        )
    ):
        blockers.append("goal derived arithmetic must remain finite")
        return None
    extreme = target_multiple >= EXTREME_TARGET_MULTIPLE
    impossible_shortcut = extreme and horizon <= 1
    return GoalProjection(
        currency=currency,
        target_multiple=target_multiple,
        required_horizon_return_fraction=required_horizon,
        required_monthly_compound_return_fraction=required_monthly,
        illustrative_months_to_target=months,
        required_monthly_contribution_for_horizon=required_contribution,
        extreme_1000x_target=extreme,
        impossible_1000x_one_month_target=impossible_shortcut,
        warning=(
            "Illustration only: the return is an operator assumption, not a forecast, "
            "promise, strategy result, or trading authorization."
        ),
    )


def _assessment_payload(
    *,
    status: WealthPlanStatus,
    allowed_canary: float | None,
    per_asset_cap: float | None,
    minimum_outlay: float | None,
    minimum_canary: float | None,
    minimum_total: float | None,
    required_total_for_proposed: float | None,
    projection: GoalProjection | None,
    blockers: tuple[str, ...],
    missing: tuple[str, ...],
    request_digest: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "allowed_canary_usd": allowed_canary,
        "per_asset_cap_usd": per_asset_cap,
        "minimum_per_asset_outlay_usd": minimum_outlay,
        "minimum_canary_usd": minimum_canary,
        "minimum_total_risk_capital_usd": minimum_total,
        "required_total_risk_capital_usd_for_proposed_canary": required_total_for_proposed,
        "goal_projection": projection.to_dict() if projection is not None else None,
        "blocking_conditions": list(blockers),
        "missing_conditions": list(missing),
        "roadmap": [item.to_dict() for item in WEALTH_ROADMAP],
        "request_digest": request_digest,
        "real_money_authorized": False,
    }


def evaluate_wealth_plan(request: WealthPlanRequest) -> WealthPlanAssessment:
    """Evaluate capital feasibility and goal arithmetic without side effects."""
    missing: list[str] = []
    blockers: list[str] = []
    if not isinstance(request, WealthPlanRequest):
        raise TypeError("request must be WealthPlanRequest")

    total = _number(
        request.total_risk_capital_usd,
        "total_risk_capital_usd",
        missing,
        blockers,
    )
    canary = _number(
        request.proposed_canary_usd,
        "proposed_canary_usd",
        missing,
        blockers,
    )
    asset_count = _positive_integer(
        request.eligible_asset_count,
        "eligible_asset_count",
        missing,
        blockers,
    )
    minimum_notional = _number(
        request.minimum_notional_usd,
        "minimum_notional_usd",
        missing,
        blockers,
    )
    cushion = _number(
        request.minimum_notional_cushion_fraction,
        "minimum_notional_cushion_fraction",
        missing,
        blockers,
        allow_zero=True,
    )
    projection = _evaluate_goal(request.goal, missing, blockers)
    if projection is not None and projection.impossible_1000x_one_month_target:
        blockers.append(
            "a 1000x target in one month is not an investable or repeatable wealth plan"
        )

    allowed_canary = (
        min(MAXIMUM_CANARY_FRACTION * total, MAXIMUM_CANARY_USD) if total is not None else None
    )
    per_asset_cap = canary * MAXIMUM_ASSET_FRACTION if canary is not None else None
    minimum_outlay = None
    if minimum_notional is not None and cushion is not None:
        derived_outlay = minimum_notional * (1.0 + cushion)
        if math.isfinite(derived_outlay):
            minimum_outlay = derived_outlay
        else:
            blockers.append("cushioned minimum-notional arithmetic must remain finite")
    minimum_canary = minimum_outlay / MAXIMUM_ASSET_FRACTION if minimum_outlay is not None else None
    minimum_total = (
        minimum_canary / MAXIMUM_CANARY_FRACTION
        if minimum_canary is not None and minimum_canary <= MAXIMUM_CANARY_USD
        else None
    )
    required_total_for_proposed = (
        canary / MAXIMUM_CANARY_FRACTION
        if canary is not None and canary <= MAXIMUM_CANARY_USD
        else None
    )

    if allowed_canary is not None and canary is not None and canary > allowed_canary:
        blockers.append(f"proposed canary ${canary:g} exceeds the allowed ${allowed_canary:g}")
    if asset_count is not None and asset_count < MINIMUM_DISTINCT_ASSETS:
        blockers.append(
            f"only {asset_count} eligible assets supplied; {MINIMUM_DISTINCT_ASSETS} are required"
        )
    if per_asset_cap is not None and minimum_outlay is not None and per_asset_cap < minimum_outlay:
        blockers.append(
            f"per-asset cap ${per_asset_cap:g} is below cushioned minimum ${minimum_outlay:g}"
        )
    if minimum_canary is not None and minimum_canary > MAXIMUM_CANARY_USD:
        blockers.append("minimum executable diversified canary exceeds the $500 hard ceiling")

    blockers_tuple = tuple(sorted(set(blockers)))
    missing_tuple = tuple(sorted(set(missing)))
    if blockers_tuple:
        status: WealthPlanStatus = "NO_GO"
    elif missing_tuple:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "FEASIBLE"

    request_digest = sha256_of_text(canonical_dumps(_invalid_safe(request.to_dict())))
    digest_payload = _assessment_payload(
        status=status,
        allowed_canary=allowed_canary,
        per_asset_cap=per_asset_cap,
        minimum_outlay=minimum_outlay,
        minimum_canary=minimum_canary,
        minimum_total=minimum_total,
        required_total_for_proposed=required_total_for_proposed,
        projection=projection,
        blockers=blockers_tuple,
        missing=missing_tuple,
        request_digest=request_digest,
    )
    assessment_digest = sha256_of_text(canonical_dumps(digest_payload))
    return WealthPlanAssessment(
        request=request,
        status=status,
        allowed_canary_usd=allowed_canary,
        per_asset_cap_usd=per_asset_cap,
        minimum_per_asset_outlay_usd=minimum_outlay,
        minimum_canary_usd=minimum_canary,
        minimum_total_risk_capital_usd=minimum_total,
        required_total_risk_capital_usd_for_proposed_canary=required_total_for_proposed,
        goal_projection=projection,
        blocking_conditions=blockers_tuple,
        missing_conditions=missing_tuple,
        roadmap=WEALTH_ROADMAP,
        request_digest=request_digest,
        assessment_digest=assessment_digest,
    )


__all__ = [
    "EXTREME_TARGET_MULTIPLE",
    "GrowthGoal",
    "GoalProjection",
    "MAXIMUM_ASSET_FRACTION",
    "MAXIMUM_CANARY_FRACTION",
    "MAXIMUM_CANARY_USD",
    "MINIMUM_DISTINCT_ASSETS",
    "RoadmapItem",
    "WEALTH_ROADMAP",
    "WealthPlanAssessment",
    "WealthPlanRequest",
    "WealthPlanStatus",
    "evaluate_wealth_plan",
]
