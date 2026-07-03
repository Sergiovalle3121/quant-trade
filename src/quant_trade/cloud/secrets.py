from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel

from quant_trade.cloud.config import PAPER_ENDPOINTS
from quant_trade.cloud.exceptions import SafetyGateError


class AlpacaPaperCredentials(BaseModel):
    api_key: str
    secret_key: str
    base_url: str


def redact_secret_values(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: (
                "***REDACTED***"
                if any(s in k.lower() for s in ("key", "secret", "token", "password"))
                else redact_secret_values(v)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_secret_values(x) for x in data]
    return data


def _creds_from_dict(data: dict[str, Any]) -> AlpacaPaperCredentials:
    url = str(data.get("ALPACA_PAPER_BASE_URL", ""))
    if url.rstrip("/") not in {u.rstrip("/") for u in PAPER_ENDPOINTS}:
        raise SafetyGateError("Alpaca Paper base URL must be the official paper endpoint")
    key = str(data.get("ALPACA_PAPER_API_KEY", ""))
    secret = str(data.get("ALPACA_PAPER_SECRET_KEY", ""))
    if not key or not secret:
        raise SafetyGateError("missing Alpaca Paper credentials")
    return AlpacaPaperCredentials(api_key=key, secret_key=secret, base_url=url)


class EnvSecretsProvider:
    def get_secret_json(self, secret_id: str) -> dict[str, Any]:
        raise SafetyGateError("env provider does not support named secret lookup")

    def get_alpaca_paper_credentials(self) -> AlpacaPaperCredentials:
        return _creds_from_dict(
            {
                k: os.getenv(k, "")
                for k in (
                    "ALPACA_PAPER_API_KEY",
                    "ALPACA_PAPER_SECRET_KEY",
                    "ALPACA_PAPER_BASE_URL",
                )
            }
        )


class AwsSecretsManagerProvider:
    def __init__(self, client: Any | None = None, secret_id: str | None = None) -> None:
        self._client = client
        self.secret_id = secret_id

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ModuleNotFoundError as exc:
                raise SafetyGateError(
                    'boto3 is required; install with python -m pip install -e ".[cloud]"'
                ) from exc
            self._client = boto3.client("secretsmanager")
        return self._client

    def get_secret_json(self, secret_id: str) -> dict[str, Any]:
        raw = self.client.get_secret_value(SecretId=secret_id).get("SecretString", "{}")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise SafetyGateError("secret JSON must be an object")
        return data

    def get_alpaca_paper_credentials(self) -> AlpacaPaperCredentials:
        if not self.secret_id:
            raise SafetyGateError("missing Alpaca Paper secret id")
        return _creds_from_dict(self.get_secret_json(self.secret_id))
