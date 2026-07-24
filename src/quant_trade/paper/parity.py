"""Execution parity: backtest vs simulated paper vs broker paper.

Compares the execution a strategy *expected* (backtest) against what a
simulated-paper run and a broker-paper run actually did, field by field, and
explains each divergence. It never calls a broker: a broker-paper
:class:`ExecutionRecord` is built from recorded fills (a fixture in tests, a
real Alpaca-Paper session log in production), never a live submission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionRecord:
    """A normalised view of one execution path's results."""

    source: str  # "backtest" | "simulated_paper" | "broker_paper"
    target_weights: dict[str, float] = field(default_factory=dict)
    order_quantities: dict[str, float] = field(default_factory=dict)
    fills: list[dict[str, Any]] = field(default_factory=list)  # symbol, qty, price, ts, fee, slip
    cancellations: int = 0
    partial_fills: int = 0
    final_positions: dict[str, float] = field(default_factory=dict)
    final_cash: float = 0.0
    final_equity: float = 0.0

    def total_fees(self) -> float:
        return float(sum(f.get("fee", 0.0) for f in self.fills))

    def total_filled_quantity(self) -> float:
        return float(sum(abs(f.get("quantity", 0.0)) for f in self.fills))


@dataclass
class FieldComparison:
    field: str
    a_value: Any
    b_value: Any
    absolute_difference: float | None
    status: str  # "match" | "within_tolerance" | "divergence"
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParityTolerances:
    equity_abs: float = 1.0
    cash_abs: float = 1.0
    position_abs: float = 1e-6
    weight_abs: float = 1e-4
    quantity_abs: float = 1e-6
    fee_abs: float = 0.01


@dataclass
class ParityReport:
    source_a: str
    source_b: str
    comparisons: list[FieldComparison]
    equity_drift: float
    max_position_drift: float
    reconciled: bool
    divergences: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_a": self.source_a,
            "source_b": self.source_b,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "equity_drift": self.equity_drift,
            "max_position_drift": self.max_position_drift,
            "reconciled": self.reconciled,
            "divergences": self.divergences,
        }


def _status(diff: float, tol: float) -> str:
    if diff == 0:
        return "match"
    return "within_tolerance" if diff <= tol else "divergence"


def _explain(name: str, status: str) -> str:
    if status == "match":
        return f"{name} identical"
    if status == "within_tolerance":
        return f"{name} differs within tolerance (rounding, lot sizing, or fee precision)"
    return {
        "final_equity": "equity diverges: fills, fees, or slippage differ between paths",
        "final_cash": "cash diverges: fee or fill-price differences accumulate",
        "total_fees": "fee models differ (commission/spread assumptions)",
        "cancellations": "one path cancelled orders the other filled (liquidity/timeout)",
        "partial_fills": "partial-fill counts differ (participation limits or liquidity)",
        "total_filled_quantity": "filled quantity differs (fill-rate or lot-size differences)",
    }.get(name, f"{name} diverges beyond tolerance")


def _compare_scalar(
    name: str, a: float, b: float, tol: float, comparisons: list[FieldComparison]
) -> float:
    diff = abs(float(a) - float(b))
    status = _status(diff, tol)
    comparisons.append(FieldComparison(name, a, b, diff, status, _explain(name, status)))
    return diff


def _compare_maps(
    name: str, a: dict[str, float], b: dict[str, float], tol: float,
    comparisons: list[FieldComparison]
) -> float:
    keys = set(a) | set(b)
    max_diff = 0.0
    worst_status = "match"
    for k in sorted(keys):
        diff = abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0)))
        max_diff = max(max_diff, diff)
        if diff > tol:
            worst_status = "divergence"
        elif diff > 0 and worst_status != "divergence":
            worst_status = "within_tolerance"
    comparisons.append(
        FieldComparison(
            name, dict(a), dict(b), max_diff, worst_status, _explain(name, worst_status)
        )
    )
    return max_diff


def compare_executions(
    a: ExecutionRecord, b: ExecutionRecord, *, tolerances: ParityTolerances | None = None
) -> ParityReport:
    """Field-by-field parity between two execution paths."""
    tol = tolerances or ParityTolerances()
    comparisons: list[FieldComparison] = []
    _compare_maps("target_weights", a.target_weights, b.target_weights, tol.weight_abs, comparisons)
    _compare_maps(
        "order_quantities", a.order_quantities, b.order_quantities, tol.quantity_abs, comparisons
    )
    max_pos = _compare_maps(
        "final_positions", a.final_positions, b.final_positions, tol.position_abs, comparisons
    )
    equity_drift = _compare_scalar(
        "final_equity", a.final_equity, b.final_equity, tol.equity_abs, comparisons
    )
    _compare_scalar("final_cash", a.final_cash, b.final_cash, tol.cash_abs, comparisons)
    _compare_scalar("total_fees", a.total_fees(), b.total_fees(), tol.fee_abs, comparisons)
    _compare_scalar(
        "total_filled_quantity", a.total_filled_quantity(), b.total_filled_quantity(),
        tol.quantity_abs, comparisons,
    )
    _compare_scalar(
        "cancellations", a.cancellations, b.cancellations, 0.0, comparisons
    )
    _compare_scalar("partial_fills", a.partial_fills, b.partial_fills, 0.0, comparisons)
    divergences = [c.explanation for c in comparisons if c.status == "divergence"]
    return ParityReport(
        source_a=a.source,
        source_b=b.source,
        comparisons=comparisons,
        equity_drift=equity_drift,
        max_position_drift=max_pos,
        reconciled=not divergences,
        divergences=divergences,
    )


def three_way_parity(
    backtest: ExecutionRecord,
    simulated_paper: ExecutionRecord,
    broker_paper: ExecutionRecord,
    *,
    tolerances: ParityTolerances | None = None,
) -> dict[str, Any]:
    """Backtest vs simulated-paper and simulated-paper vs broker-paper reports."""
    bt_vs_sim = compare_executions(backtest, simulated_paper, tolerances=tolerances)
    sim_vs_broker = compare_executions(simulated_paper, broker_paper, tolerances=tolerances)
    return {
        "backtest_vs_simulated_paper": bt_vs_sim.to_dict(),
        "simulated_paper_vs_broker_paper": sim_vs_broker.to_dict(),
        "fully_reconciled": bt_vs_sim.reconciled and sim_vs_broker.reconciled,
    }
