from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from quant_trade.execution.exceptions import BrokerConfigurationError


@dataclass
class BrokerConfig:
    provider: Literal["simulated", "alpaca_paper"] = "simulated"
    mode: Literal["simulated", "paper"] = "simulated"
    base_url: str = "https://paper-api.alpaca.markets"
    timeout_seconds: float = 10.0
    max_retries: int = 1
    dry_run_default: bool = True
    confirm_required: bool = True
    account_id_expected: str | None = None
    universe: list[str] = field(default_factory=list)
    asset_class: str = "equities"
    allow_fractional: bool = True
    allow_short: bool = False
    allow_leverage: bool = False
    max_notional_per_order: float = 1000.0
    max_orders_per_day: int = 20
    max_gross_exposure: float = 1.0
    max_symbol_weight: float = 0.25
    min_cash_pct: float = 0.02
    audit_dir: str = "audits/broker"
    state_dir: str = "state/broker"
    real_money_enabled: bool = False
    allow_live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_broker_config(path: Path) -> BrokerConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise BrokerConfigurationError("broker config must be a YAML mapping")
    unknown = set(raw) - set(BrokerConfig.__dataclass_fields__)
    if unknown:
        raise BrokerConfigurationError(f"unknown broker config keys: {sorted(unknown)}")
    cfg = BrokerConfig(**raw)
    from quant_trade.execution.safety import validate_paper_mode

    validate_paper_mode(cfg)
    return cfg
