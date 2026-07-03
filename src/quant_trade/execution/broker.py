from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


def _dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


@dataclass
class BrokerCapabilities:
    provider: str
    paper: bool = True
    supports_market_orders: bool = True
    supports_limit_orders: bool = True
    supports_fractional: bool = True
    supports_shorting: bool = False
    supports_leverage: bool = False
    asset_class: str = "equities"

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerAccount:
    broker: str
    account_id_masked: str
    currency: str
    cash: float
    buying_power: float
    equity: float
    status: str
    paper: bool
    pattern_day_trader: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerPosition:
    symbol: str
    quantity: float
    market_value: float
    average_entry_price: float
    unrealized_pnl: float
    current_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerOrderRequest:
    symbol: str
    side: str
    quantity: float
    order_type: str
    time_in_force: str
    client_order_id: str
    dry_run: bool = True
    limit_price: float | None = None
    stop_price: float | None = None
    strategy_id: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerFill:
    broker_order_id: str
    symbol: str
    quantity: float
    price: float
    filled_at: str

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    order_type: str
    status: str
    submitted_at: str
    paper: bool
    filled_at: str | None = None
    average_fill_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerClock:
    timestamp: str
    is_open: bool
    next_open: str
    next_close: str

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


@dataclass
class BrokerHealth:
    provider: str
    ok: bool
    paper: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return _dict(self)


class Broker(Protocol):
    def get_account(self) -> BrokerAccount: ...
    def get_positions(self) -> list[BrokerPosition]: ...
    def get_open_orders(self) -> list[BrokerOrder]: ...
    def get_order(self, order_id: str) -> BrokerOrder | None: ...
    def submit_order(self, order: BrokerOrderRequest) -> BrokerOrder: ...
    def cancel_order(self, order_id: str) -> None: ...
    def cancel_all_orders(self) -> None: ...
    def get_clock(self) -> BrokerClock: ...
    def health_check(self) -> BrokerHealth: ...
