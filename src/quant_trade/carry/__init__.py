"""Research-only cash-and-carry / funding market-neutral toolkit.

No module here submits an order, connects to a live exchange, or moves funds.
Everything is a paper calculation over read-only snapshots.
"""

from quant_trade.carry.economics import evaluate_carry
from quant_trade.carry.execution import (
    FillStep,
    TwoLegPlan,
    TwoLegResult,
    TwoLegState,
    simulate_two_leg,
)
from quant_trade.carry.models import (
    CarryCostModel,
    CarryEvaluation,
    CarryPolicy,
    CarryPosition,
    CarrySnapshot,
)

__all__ = [
    "CarryCostModel",
    "CarryEvaluation",
    "CarryPolicy",
    "CarryPosition",
    "CarrySnapshot",
    "evaluate_carry",
    "FillStep",
    "TwoLegPlan",
    "TwoLegResult",
    "TwoLegState",
    "simulate_two_leg",
]
