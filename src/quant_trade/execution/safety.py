from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from quant_trade.execution.broker import BrokerAccount, BrokerOrderRequest
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerSafetyError

PAPER_URL = "https://paper-api.alpaca.markets"
SECRET_KEYS = ("secret", "token", "key", "authorization", "password")


def validate_paper_mode(config: BrokerConfig) -> None:
    if config.provider not in {"alpaca_paper", "simulated"}:
        raise BrokerSafetyError("provider must be alpaca_paper or simulated")
    if config.mode not in {"paper", "simulated"}:
        raise BrokerSafetyError("mode must be paper or simulated; live mode is forbidden")
    if config.real_money_enabled or config.allow_live_trading:
        raise BrokerSafetyError("real-money and live trading flags must be false")
    if "live" in (config.base_url or "").lower():
        raise BrokerSafetyError("live-like endpoint names are forbidden")
    if config.provider == "alpaca_paper":
        validate_alpaca_paper_endpoint(config.base_url)


def validate_alpaca_paper_endpoint(base_url: str) -> str:
    if not base_url or not base_url.strip():
        raise BrokerSafetyError("Alpaca paper base URL is required")
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or parsed.netloc != "paper-api.alpaca.markets" or parsed.path:
        raise BrokerSafetyError("only https://paper-api.alpaca.markets is allowed")
    return PAPER_URL


def validate_order_safety(
    order: BrokerOrderRequest, risk_limits: BrokerConfig, account: BrokerAccount
) -> dict[str, Any]:
    symbol = order.symbol.upper().strip()
    if order.side not in {"buy", "sell"}:
        raise BrokerSafetyError("order side must be buy or sell")
    if order.quantity <= 0:
        raise BrokerSafetyError("order quantity must be positive")
    if order.order_type not in {"market", "limit"}:
        raise BrokerSafetyError("only market and limit orders are supported")
    if order.stop_price is not None:
        raise BrokerSafetyError("stop/bracket/OCO orders are not supported")
    if risk_limits.asset_class != "equities":
        raise BrokerSafetyError("only equities/ETFs are supported")
    if not risk_limits.allow_fractional and not float(order.quantity).is_integer():
        raise BrokerSafetyError("fractional shares are disabled")
    if risk_limits.allow_short or risk_limits.allow_leverage:
        raise BrokerSafetyError("shorting and leverage must remain disabled")
    if order.side == "sell" and "short" in (order.reason or "").lower():
        raise BrokerSafetyError("shorting is not allowed")
    if risk_limits.universe and symbol not in {s.upper() for s in risk_limits.universe}:
        raise BrokerSafetyError(f"symbol {symbol} is outside configured universe")
    price = order.limit_price or 1.0
    notional = abs(order.quantity * price)
    if notional > risk_limits.max_notional_per_order:
        raise BrokerSafetyError("order notional exceeds max_notional_per_order")
    if account.equity > 0 and notional / account.equity > risk_limits.max_symbol_weight:
        raise BrokerSafetyError("order exceeds max_symbol_weight")
    if order.side == "buy" and account.cash - notional < account.equity * risk_limits.min_cash_pct:
        raise BrokerSafetyError("order violates min cash buffer")
    return {"passed": True, "symbol": symbol, "notional": notional}


def redact_secret(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}****{text[-2:]}"


def sanitize_raw_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            if any(s in str(key).lower() for s in SECRET_KEYS):
                clean[str(key)] = redact_secret(value)
            else:
                clean[str(key)] = sanitize_raw_payload(value)
        return clean
    if isinstance(payload, list):
        return [sanitize_raw_payload(v) for v in payload]
    return payload
