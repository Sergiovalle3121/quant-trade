from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from quant_trade.execution.audit import append_audit_event
from quant_trade.execution.broker import (
    BrokerAccount,
    BrokerClock,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from quant_trade.execution.config import BrokerConfig
from quant_trade.execution.exceptions import BrokerCredentialsError, BrokerSafetyError
from quant_trade.execution.safety import (
    sanitize_raw_payload,
    validate_alpaca_paper_endpoint,
    validate_order_safety,
    validate_paper_mode,
)


class AlpacaPaperBroker:
    def __init__(self, config: BrokerConfig, *, confirm_paper_order: bool = False) -> None:
        validate_paper_mode(config)
        self.config = config
        self.base_url = validate_alpaca_paper_endpoint(config.base_url)
        self.confirm_paper_order = confirm_paper_order
        self._session: Any | None = None

    def _credentials(self) -> tuple[str, str]:
        key = os.getenv("ALPACA_PAPER_API_KEY")
        secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
        if not key or not secret:
            raise BrokerCredentialsError(
                "Set ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY for Alpaca Paper. "
                "Generic/live Alpaca env vars are intentionally unsupported."
            )
        return key, secret

    def _headers(self) -> dict[str, str]:
        key, secret = self._credentials()
        return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    def _request(
        self, method: str, path: str, *, json_payload: dict[str, Any] | None = None
    ) -> Any:
        validate_alpaca_paper_endpoint(self.base_url)
        headers = self._headers()
        import requests

        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            json=json_payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        if response.text:
            return sanitize_raw_payload(response.json())
        return {}

    def get_account(self) -> BrokerAccount:
        raw = self._request("GET", "/v2/account")
        account = BrokerAccount(
            broker="alpaca_paper",
            account_id_masked=str(raw.get("id", ""))[:4] + "****",
            currency=str(raw.get("currency", "USD")),
            cash=float(raw.get("cash", 0.0)),
            buying_power=float(raw.get("buying_power", 0.0)),
            equity=float(raw.get("equity", 0.0)),
            status=str(raw.get("status", "unknown")),
            paper=True,
            pattern_day_trader=bool(raw.get("pattern_day_trader", False)),
            raw=raw,
        )
        append_audit_event(
            self.config.audit_dir,
            "broker_account_fetched",
            "Fetched paper account",
            provider=self.config.provider,
            mode=self.config.mode,
        )
        return account

    def get_positions(self) -> list[BrokerPosition]:
        rows = self._request("GET", "/v2/positions")
        positions = [
            BrokerPosition(
                symbol=str(r.get("symbol", "")).upper(),
                quantity=float(r.get("qty", 0.0)),
                market_value=float(r.get("market_value", 0.0)),
                average_entry_price=float(r.get("avg_entry_price", 0.0)),
                unrealized_pnl=float(r.get("unrealized_pl", 0.0)),
                current_price=float(r["current_price"])
                if r.get("current_price") is not None
                else None,
            )
            for r in rows
        ]
        append_audit_event(
            self.config.audit_dir,
            "broker_positions_fetched",
            "Fetched paper positions",
            provider=self.config.provider,
            mode=self.config.mode,
        )
        return positions

    def get_open_orders(self) -> list[BrokerOrder]:
        return [self._map_order(r) for r in self._request("GET", "/v2/orders")]

    def get_order(self, order_id: str) -> BrokerOrder | None:
        return self._map_order(self._request("GET", f"/v2/orders/{order_id}"))

    def submit_order(self, order: BrokerOrderRequest) -> BrokerOrder:
        if order.dry_run:
            result = BrokerOrder(
                str(uuid.uuid4()),
                order.client_order_id,
                order.symbol,
                order.side,
                order.quantity,
                0.0,
                order.order_type,
                "dry_run",
                datetime.now(UTC).isoformat(),
                True,
            )
            append_audit_event(
                self.config.audit_dir,
                "dry_run_order_created",
                "Created dry-run paper order",
                provider=self.config.provider,
                mode=self.config.mode,
                details=result.to_dict(),
            )
            return result
        if not self.confirm_paper_order:
            raise BrokerSafetyError("--confirm-paper-order is required for paper submission")
        account = self.get_account()
        validate_order_safety(order, self.config, account)
        append_audit_event(
            self.config.audit_dir,
            "paper_order_submission_requested",
            "Submitting Alpaca Paper order",
            provider=self.config.provider,
            mode=self.config.mode,
            details=order.to_dict(),
        )
        payload = {
            "symbol": order.symbol,
            "side": order.side,
            "qty": str(order.quantity),
            "type": order.order_type,
            "time_in_force": order.time_in_force,
            "client_order_id": order.client_order_id,
        }
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)
        result = self._map_order(self._request("POST", "/v2/orders", json_payload=payload))
        append_audit_event(
            self.config.audit_dir,
            "paper_order_submitted",
            "Submitted Alpaca Paper order",
            provider=self.config.provider,
            mode=self.config.mode,
            details=result.to_dict(),
        )
        return result

    def cancel_order(self, order_id: str) -> None:
        self._request("DELETE", f"/v2/orders/{order_id}")

    def cancel_all_orders(self) -> None:
        append_audit_event(
            self.config.audit_dir,
            "cancel_all_requested",
            "Cancel all requested",
            provider=self.config.provider,
            mode=self.config.mode,
        )
        self._request("DELETE", "/v2/orders")
        append_audit_event(
            self.config.audit_dir,
            "cancel_all_completed",
            "Cancel all completed",
            provider=self.config.provider,
            mode=self.config.mode,
        )

    def get_clock(self) -> BrokerClock:
        raw = self._request("GET", "/v2/clock")
        return BrokerClock(
            str(raw.get("timestamp", "")),
            bool(raw.get("is_open", False)),
            str(raw.get("next_open", "")),
            str(raw.get("next_close", "")),
        )

    def health_check(self) -> BrokerHealth:
        try:
            self._credentials()
            validate_alpaca_paper_endpoint(self.base_url)
        except Exception as exc:
            return BrokerHealth("alpaca_paper", False, True, str(exc))
        return BrokerHealth("alpaca_paper", True, True, "paper configuration is valid")

    @staticmethod
    def _map_order(raw: dict[str, Any]) -> BrokerOrder:
        return BrokerOrder(
            broker_order_id=str(raw.get("id", "")),
            client_order_id=str(raw.get("client_order_id", "")),
            symbol=str(raw.get("symbol", "")).upper(),
            side=str(raw.get("side", "")),
            quantity=float(raw.get("qty", 0.0)),
            filled_quantity=float(raw.get("filled_qty", 0.0)),
            order_type=str(raw.get("type", "")),
            status=str(raw.get("status", "")),
            submitted_at=str(raw.get("submitted_at", "")),
            filled_at=raw.get("filled_at"),
            average_fill_price=float(raw["filled_avg_price"])
            if raw.get("filled_avg_price") is not None
            else None,
            paper=True,
            raw=sanitize_raw_payload(raw),
        )
