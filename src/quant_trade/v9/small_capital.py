"""Can this strategy be run with $100? With $1,000? Answered per venue rule.

V8 reported "$166,667 minimum capital", which was not a minimum — it was the
capital a $100k reference position happened to immobilise. The real question
is the opposite one: given a starting balance, is there *any* position size
that clears the venue's lot step, minimum notional and fee floors while
leaving enough margin buffer to survive a bad hour?

Below some balance the answer is simply no, and the honest output is
``INSUFFICIENT_EXECUTABLE_CAPITAL`` rather than a fractional position nobody
can place. Above it, the constraint that binds is worth naming: minimum
notional, lot granularity and fee floors bite in different places, and which
one binds tells the operator what would have to change.

Two reporting rules the numbers depend on:

* **Return is on total immobilised capital**, not on notional. A carry that
  earns 2% on notional while tying up 1.67x that notional earned 1.2%.
* **Outcomes come from the OOS distribution**, resampled, so the answer is
  P05/P50/P95 and a probability of ruin — not a single number and never a
  projection of when someone becomes rich.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.v9.margin import InstrumentRisk, capital_requirement

#: The capital ladder the report walks. The rungs below $100 are there to
#: bracket the floor rather than to be recommended: a curve whose lowest rung
#: is executable reports its own starting point as the minimum, which is not a
#: measurement of anything.
DEFAULT_CAPITAL_LADDER = (
    25.0,
    50.0,
    75.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
)

STATUS_EXECUTABLE = "EXECUTABLE"
STATUS_INSUFFICIENT = "INSUFFICIENT_EXECUTABLE_CAPITAL"

#: Ruin is a drawdown this deep: at that point the remaining balance can no
#: longer place the minimum position, so the strategy is over either way.
RUIN_DRAWDOWN = 0.50


@dataclass
class CapitalScenario:
    starting_capital_usd: float
    status: str
    binding_constraint: str = ""
    executable_notional_usd: float = 0.0
    quantity: float = 0.0
    total_capital_committed_usd: float = 0.0
    capital_efficiency: float = 0.0
    round_trip_cost_usd: float = 0.0
    round_trip_cost_fraction_of_capital: float = 0.0
    break_even_funding_per_interval: float | None = None
    capacity_notional_usd: float | None = None
    expected_return_on_capital: float | None = None
    p05_return_on_capital: float | None = None
    p50_return_on_capital: float | None = None
    p95_return_on_capital: float | None = None
    max_drawdown: float | None = None
    probability_of_loss: float | None = None
    probability_of_ruin: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        return self.status == STATUS_EXECUTABLE

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["executable"] = self.executable
        return payload


def _fees_for(
    notional: float,
    *,
    spot_taker_bps: float,
    perp_taker_bps: float,
    other_bps: float,
    fee_floor_usd: float,
    spot_leg: bool,
) -> float:
    """One round trip, per leg, with each leg's floor applied per fill."""
    fills = []
    if spot_leg:
        fills += [spot_taker_bps + other_bps] * 2
        fills += [perp_taker_bps + other_bps] * 2
    else:
        fills += [perp_taker_bps + other_bps] * 4
    total = 0.0
    for bps in fills:
        total += max(notional * bps / 10_000.0, fee_floor_usd)
    return total


def evaluate_capital_scenario(
    starting_capital_usd: float,
    *,
    risk: InstrumentRisk,
    price: float,
    spot_taker_bps: float,
    perp_taker_bps: float,
    other_bps: float = 3.5,
    fee_floor_usd: float = 0.0,
    spot_leg: bool = True,
    buffer_rate: float = 0.5,
    max_cost_fraction_of_capital: float = 0.10,
    funding_interval_hours: float = 8.0,
    holding_days: float = 30.0,
) -> CapitalScenario:
    """Find the largest position this balance can actually run, if any."""
    scenario = CapitalScenario(
        starting_capital_usd=starting_capital_usd, status=STATUS_INSUFFICIENT
    )
    if starting_capital_usd <= 0:
        scenario.problems.append("starting capital must be > 0")
        return scenario

    # Capital per unit of notional: spot inventory (if any) + initial margin +
    # emergency buffer. Solve for the notional the balance supports, then snap
    # it down to the venue's lot grid.
    tier = risk.tier_for(starting_capital_usd)
    per_notional = (1.0 if spot_leg else 0.0) + tier.initial_margin_rate * (1.0 + buffer_rate)
    affordable_notional = starting_capital_usd / per_notional
    quantity = risk.round_quantity(affordable_notional / price)
    notional = quantity * price

    if quantity <= 0:
        scenario.binding_constraint = "lot_step"
        scenario.problems.append(
            f"the affordable notional {affordable_notional:.2f} USD buys "
            f"{affordable_notional / price:.10f} units, below the venue lot step "
            f"{risk.qty_step}"
        )
        return scenario

    tradeable, why = risk.is_tradeable(quantity, price)
    if not tradeable:
        scenario.binding_constraint = "min_order_qty" if "quantity" in why else "min_notional"
        scenario.problems.append(why)
        return scenario

    requirement = capital_requirement(
        notional_usd=notional,
        risk=risk,
        round_trip_cost_fraction=0.0,
        reserve_rate=buffer_rate,
        spot_leg=spot_leg,
    )
    fees = _fees_for(
        notional,
        spot_taker_bps=spot_taker_bps,
        perp_taker_bps=perp_taker_bps,
        other_bps=other_bps,
        fee_floor_usd=fee_floor_usd,
        spot_leg=spot_leg,
    )
    committed = requirement.total_capital_usd + fees
    if committed > starting_capital_usd:
        scenario.binding_constraint = "margin_plus_fees"
        scenario.problems.append(
            f"a {notional:.2f} USD position needs {committed:.2f} USD once margin, "
            f"buffer and fees are posted, but only {starting_capital_usd:.2f} is "
            "available"
        )
        return scenario

    cost_fraction = fees / starting_capital_usd
    if cost_fraction > max_cost_fraction_of_capital:
        scenario.binding_constraint = "fee_floor"
        scenario.problems.append(
            f"one round trip costs {fees:.2f} USD, {cost_fraction:.1%} of capital; "
            f"above the {max_cost_fraction_of_capital:.0%} ceiling the position "
            "cannot recover its own frictions"
        )
        return scenario

    settlements = holding_days * 24.0 / funding_interval_hours
    scenario.status = STATUS_EXECUTABLE
    scenario.binding_constraint = "none"
    scenario.executable_notional_usd = notional
    scenario.quantity = quantity
    scenario.total_capital_committed_usd = committed
    scenario.capital_efficiency = notional / committed if committed else 0.0
    scenario.round_trip_cost_usd = fees
    scenario.round_trip_cost_fraction_of_capital = cost_fraction
    scenario.break_even_funding_per_interval = (
        fees / notional / settlements if notional and settlements else None
    )
    return scenario


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[index]


def attach_oos_distribution(
    scenario: CapitalScenario,
    oos_returns: list[float],
    *,
    samples: int = 5_000,
    seed: int = 20260728,
    block_size: int = 24,
) -> CapitalScenario:
    """Resample the OOS series to get the spread this balance would have seen.

    A stationary block bootstrap preserves the short-horizon autocorrelation
    that makes drawdowns cluster; sampling independently would understate
    exactly the tail the ruin probability is about.
    """
    if not scenario.executable or len(oos_returns) < 2:
        return scenario
    import numpy as np

    rng = np.random.default_rng(seed)
    series = np.asarray(oos_returns, dtype=float)
    length = len(series)
    horizon = length
    totals: list[float] = []
    drawdowns: list[float] = []
    ruins = 0
    for _ in range(samples):
        path: list[float] = []
        while len(path) < horizon:
            start = int(rng.integers(0, length))
            size = min(block_size, horizon - len(path))
            for offset in range(size):
                path.append(float(series[(start + offset) % length]))
        equity = 1.0
        peak = 1.0
        worst = 0.0
        for value in path:
            equity *= 1.0 + value
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1.0)
        totals.append(equity - 1.0)
        drawdowns.append(worst)
        if worst <= -RUIN_DRAWDOWN:
            ruins += 1

    # Scale from return-on-notional to return-on-committed-capital.
    leverage = (
        scenario.executable_notional_usd / scenario.total_capital_committed_usd
        if scenario.total_capital_committed_usd
        else 0.0
    )
    scaled = [t * leverage for t in totals]
    scenario.expected_return_on_capital = sum(scaled) / len(scaled)
    scenario.p05_return_on_capital = _percentile(scaled, 5.0)
    scenario.p50_return_on_capital = _percentile(scaled, 50.0)
    scenario.p95_return_on_capital = _percentile(scaled, 95.0)
    scenario.max_drawdown = _percentile(drawdowns, 5.0)
    scenario.probability_of_loss = sum(1 for t in scaled if t < 0) / len(scaled)
    scenario.probability_of_ruin = ruins / samples
    return scenario


@dataclass
class FeasibilityCurve:
    scenarios: list[CapitalScenario] = field(default_factory=list)
    price: float = 0.0
    venue: str = ""
    instrument: str = ""

    @property
    def minimum_executable_capital_usd(self) -> float | None:
        executable = [s.starting_capital_usd for s in self.scenarios if s.executable]
        return min(executable) if executable else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "SMALL_CAPITAL_FEASIBILITY",
            "schema_version": 1,
            "venue": self.venue,
            "instrument": self.instrument,
            "reference_price": self.price,
            "minimum_executable_capital_usd": self.minimum_executable_capital_usd,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "ruin_definition": (
                f"a drawdown of {RUIN_DRAWDOWN:.0%}, at which point the remaining "
                "balance can no longer place the minimum position"
            ),
            "note": (
                "Returns are on TOTAL immobilised capital, not on notional. "
                "Outcomes are P05/P50/P95 from a block bootstrap of the OOS "
                "series; no deterministic projection is made from them."
            ),
        }


def build_feasibility_curve(
    *,
    risk: InstrumentRisk,
    price: float,
    spot_taker_bps: float,
    perp_taker_bps: float,
    ladder: tuple[float, ...] = DEFAULT_CAPITAL_LADDER,
    oos_returns: list[float] | None = None,
    **scenario_kwargs: Any,
) -> FeasibilityCurve:
    """Walk the capital ladder and report where the strategy becomes runnable."""
    curve = FeasibilityCurve(price=price, venue=risk.venue, instrument=risk.instrument)
    for capital in ladder:
        scenario = evaluate_capital_scenario(
            capital,
            risk=risk,
            price=price,
            spot_taker_bps=spot_taker_bps,
            perp_taker_bps=perp_taker_bps,
            **scenario_kwargs,
        )
        if oos_returns:
            attach_oos_distribution(scenario, oos_returns)
        curve.scenarios.append(scenario)
    return curve


__all__ = [
    "DEFAULT_CAPITAL_LADDER",
    "RUIN_DRAWDOWN",
    "STATUS_EXECUTABLE",
    "STATUS_INSUFFICIENT",
    "CapitalScenario",
    "FeasibilityCurve",
    "attach_oos_distribution",
    "build_feasibility_curve",
    "evaluate_capital_scenario",
]
