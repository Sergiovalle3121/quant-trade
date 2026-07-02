from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fixed_commission: float = 0.0
    percentage_commission: float = 0.0
    slippage_bps: float = 0.0
    min_commission: float = 0.0
    spread_bps: float = 0.0

    def trade_cost(self, notional: float) -> float:
        if notional < 0:
            raise ValueError("notional must be non-negative")
        commission = self.fixed_commission + notional * self.percentage_commission
        if self.min_commission:
            commission = max(commission, self.min_commission)
        slippage = notional * self.slippage_bps / 10_000
        spread = notional * self.spread_bps / 10_000
        return commission + slippage + spread
