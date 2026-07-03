import pytest

from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.secrets import (
    AwsSecretsManagerProvider,
    EnvSecretsProvider,
    redact_secret_values,
)


def test_env_credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "s")
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    assert EnvSecretsProvider().get_alpaca_paper_credentials().base_url.endswith("markets")


def test_live_endpoint_rejected(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "s")
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://api.alpaca.markets")
    with pytest.raises(SafetyGateError):
        EnvSecretsProvider().get_alpaca_paper_credentials()


def test_redact():
    assert (
        redact_secret_values({"api_key": "abc", "nested": {"secret": "x"}})["api_key"]
        == "***REDACTED***"
    )


def test_aws_mocked():
    class C:
        def get_secret_value(self, SecretId):
            return {
                "SecretString": '{"ALPACA_PAPER_API_KEY":"k","ALPACA_PAPER_SECRET_KEY":"s","ALPACA_PAPER_BASE_URL":"https://paper-api.alpaca.markets"}'
            }

    assert AwsSecretsManagerProvider(C(), "id").get_alpaca_paper_credentials().api_key == "k"
