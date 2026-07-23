import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fixed_commission: float = 0.0
    percentage_commission: float = 0.0
    slippage_bps: float = 0.0
    min_commission: float = 0.0
    spread_bps: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "fixed_commission",
            "percentage_commission",
            "slippage_bps",
            "min_commission",
            "spread_bps",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def trade_cost(self, notional: float, *, include_slippage: bool = True) -> float:
        """Total cash cost for a trade of ``notional``.

        ``include_slippage=False`` is for engines that already apply
        ``slippage_bps`` as an adverse fill-price adjustment, so slippage is
        never charged twice.
        """
        if notional < 0:
            raise ValueError("notional must be non-negative")
        commission = self.fixed_commission + notional * self.percentage_commission
        if self.min_commission:
            commission = max(commission, self.min_commission)
        slippage = notional * self.slippage_bps / 10_000 if include_slippage else 0.0
        spread = notional * self.spread_bps / 10_000
        return commission + slippage + spread


# Deliberately conservative default used whenever a caller does not specify
# costs. Frictionless backtests require explicitly passing an all-zero
# CostModel; omission must never silently disable trading costs.
CONSERVATIVE_COST_MODEL = CostModel(
    percentage_commission=0.0005,  # 5 bps per side
    slippage_bps=5.0,
    spread_bps=2.0,
)

