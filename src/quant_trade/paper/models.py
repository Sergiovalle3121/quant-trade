from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Side = Literal["buy", "sell"]
OrderStatus = Literal["pending", "filled", "rejected", "cancelled"]
SessionStatus = Literal["initialized", "running", "paused", "stopped"]


@dataclass
class PaperPosition:
    symbol: str
    quantity: float
    average_cost: float = 0.0
    last_price: float = 0.0


@dataclass
class PaperOrder:
    order_id: str
    timestamp: str
    symbol: str
    side: Side
    quantity: float
    order_type: str = "market"
    status: OrderStatus = "pending"
    reason: str = ""
    submitted_at: str = ""
    filled_at: str = ""
    fill_price: float = 0.0
    cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperFill:
    fill_id: str
    order_id: str
    timestamp: str
    symbol: str
    side: Side
    quantity: float
    price: float
    cost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperTrade:
    trade_id: str
    timestamp: str
    symbol: str
    side: Side
    quantity: float
    price: float
    cost: float


@dataclass
class PaperPortfolioSnapshot:
    timestamp: str
    cash: float
    equity: float
    gross_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperEvent:
    event_id: str
    timestamp: str
    event_type: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperRiskLimits:
    max_gross_exposure: float = 1.0
    max_weight_per_asset: float = 0.25
    max_daily_loss_pct: float = 0.02
    max_total_drawdown_pct: float = 0.10
    max_turnover_per_rebalance: float = 0.50
    min_cash_pct: float = 0.01
    max_orders_per_day: int = 50
    allow_short: bool = False
    allow_leverage: bool = False
    kill_switch_enabled: bool = True
    minimum_order_notional: float = 1.0


@dataclass
class PaperAccount:
    cash: float
    equity: float


@dataclass
class PaperTradingConfig:
    paper_session_name: str
    mode: str
    data_path: str
    strategy: str
    strategy_params: dict[str, Any]
    universe: dict[str, list[str]]
    initial_cash: float
    costs: dict[str, float]
    risk_limits: PaperRiskLimits
    execution: dict[str, Any]
    state_dir: str = "state/paper"
    output_dir: str = "outputs/paper"
    candidate_id: str | None = None


@dataclass
class PaperSessionState:
    cash: float
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    open_orders: list[PaperOrder] = field(default_factory=list)
    fills: list[PaperFill] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float = 0.0
    high_water_mark: float = 0.0
    max_drawdown: float = 0.0
    last_processed_timestamp: str = ""
    kill_switch_active: bool = False
    status: SessionStatus = "initialized"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
