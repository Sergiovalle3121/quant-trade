from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.execution.broker import BrokerAccount, BrokerPosition
from quant_trade.paper.models import PaperSessionState


@dataclass
class ReconciliationReport:
    cash_difference: float
    equity_difference: float
    missing_positions: list[str] = field(default_factory=list)
    extra_positions: list[str] = field(default_factory=list)
    quantity_differences: dict[str, float] = field(default_factory=dict)
    market_value_differences: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (
            self.missing_positions
            or self.extra_positions
            or self.quantity_differences
            or self.warnings
            or abs(self.cash_difference) > 0.01
            or abs(self.equity_difference) > 0.01
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def reconcile_paper_state_with_broker(
    local_state: PaperSessionState,
    broker_account: BrokerAccount,
    broker_positions: list[BrokerPosition],
) -> ReconciliationReport:
    local_symbols = set(local_state.positions)
    broker_by_symbol = {p.symbol.upper(): p for p in broker_positions}
    broker_symbols = set(broker_by_symbol)
    report = ReconciliationReport(
        cash_difference=float(local_state.cash) - float(broker_account.cash),
        equity_difference=float(local_state.equity) - float(broker_account.equity),
        missing_positions=sorted(local_symbols - broker_symbols),
        extra_positions=sorted(broker_symbols - local_symbols),
    )
    for sym in sorted(local_symbols & broker_symbols):
        local = local_state.positions[sym]
        broker = broker_by_symbol[sym]
        qdiff = float(local.quantity) - float(broker.quantity)
        if abs(qdiff) > 1e-6:
            report.quantity_differences[sym] = qdiff
        local_mv = float(local.quantity) * float(local.last_price)
        mdiff = local_mv - float(broker.market_value)
        if abs(mdiff) > 0.01:
            report.market_value_differences[sym] = mdiff
    return report
