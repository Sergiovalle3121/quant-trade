from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from quant_trade.cloud.exceptions import CloudConfigError

CloudMode = Literal["dry_run", "simulated_paper", "broker_plan", "alpaca_paper_submit"]
JobName = Literal[
    "data_refresh",
    "research_run",
    "simulated_paper_run",
    "broker_plan",
    "broker_submit_paper",
    "health_check",
    "heartbeat",
]

PAPER_ENDPOINTS = {"https://paper-api.alpaca.markets", "https://paper-api.alpaca.markets/v2"}


class SecretConfig(BaseModel):
    provider: Literal["env", "aws_secrets_manager"] = "env"
    alpaca_paper_secret_id: str | None = None


class MonitoringConfig(BaseModel):
    emit_json_logs: bool = True
    emit_cloudwatch_embedded_metrics: bool = False
    alert_on_job_failure: bool = True
    alert_on_kill_switch: bool = True
    alert_on_drawdown: bool = True
    alert_on_rejected_orders: bool = True
    stale_heartbeat_minutes: int = Field(default=30, gt=0)
    # When set, job failures publish to this SNS topic so a 3am failure
    # notifies a human instead of dying silently in a log group.
    sns_topic_arn: str | None = None


class LockingConfig(BaseModel):
    enabled: bool = True
    provider: Literal["local", "dynamodb"] = "local"
    table_name: str | None = None
    ttl_minutes: int = Field(default=30, gt=0)


class CloudConfig(BaseModel):
    environment: Literal["local", "aws"] = "local"
    deployment_name: str
    job_name: str = "health_check"
    mode: CloudMode = "dry_run"
    allow_paper_order_submission: bool = False
    allow_live_trading: bool = False
    real_money_enabled: bool = False
    broker_provider: Literal["simulated", "alpaca_paper"] = "simulated"
    broker_config_path: str | None = None
    paper_config_path: str | None = None
    data_config_path: str | None = None
    research_config_path: str | None = None
    mining_config_path: str | None = None
    schedule_timezone: str = "UTC"
    artifact_uri: str
    state_uri: str
    heartbeat_uri: str
    kill_switch_uri: str
    secrets: SecretConfig = Field(default_factory=SecretConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    locking: LockingConfig = Field(default_factory=LockingConfig)

    @field_validator("artifact_uri", "state_uri", "heartbeat_uri", "kill_switch_uri")
    @classmethod
    def uri_explicit(cls, value: str) -> str:
        if not value or value.strip() == "":
            raise ValueError("URI must be explicit")
        return value

    @model_validator(mode="after")
    def validate_safety(self) -> CloudConfig:
        if self.allow_live_trading:
            raise ValueError("allow_live_trading must always be false")
        if self.real_money_enabled:
            raise ValueError("real_money_enabled must always be false")
        if self.mode == "alpaca_paper_submit":
            if not self.allow_paper_order_submission:
                raise ValueError("alpaca_paper_submit requires allow_paper_order_submission=true")
            if self.broker_provider != "alpaca_paper":
                raise ValueError("alpaca_paper_submit requires broker_provider=alpaca_paper")
        if (
            self.secrets.provider == "aws_secrets_manager"
            and not self.secrets.alpaca_paper_secret_id
        ):
            raise ValueError("AWS secrets provider requires alpaca_paper_secret_id")
        if self.secrets.alpaca_paper_secret_id and any(
            token in self.secrets.alpaca_paper_secret_id.lower() for token in ("key=", "secret=")
        ):
            raise ValueError("secret config may contain only ids/names, not values")
        return self

    def to_safe_dict(self) -> dict:
        return self.model_dump(mode="json")


def load_cloud_config(path: Path | str) -> CloudConfig:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return CloudConfig(**data)
    except Exception as exc:
        if isinstance(exc, CloudConfigError):
            raise
        raise CloudConfigError(str(exc)) from exc


def write_cloud_config(path: Path, config: CloudConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config.to_safe_dict(), sort_keys=False), encoding="utf-8")

