"""Settings: no secret defaults, free mode forced without Stripe."""

from __future__ import annotations

import pytest

from quant_trade.audit.settings import AuditSettings, normalise_database_url

STRIPE = {
    "STRIPE_SECRET_KEY": "sk_test_x",
    "STRIPE_WEBHOOK_SECRET": "whsec_x",
    "STRIPE_PRICE_ID": "price_x",
}


def test_defaults_are_free_sqlite_and_secretless() -> None:
    settings = AuditSettings.from_env({})
    assert settings.free_mode is True
    assert settings.stripe_enabled is False
    assert settings.database_kind == "sqlite"
    assert settings.stripe_secret_key == ""
    assert settings.price_usd == 49.0


def test_free_mode_is_forced_without_every_stripe_variable() -> None:
    partial = {**STRIPE, "AUDIT_FREE_MODE": "false"}
    del partial["STRIPE_PRICE_ID"]
    settings = AuditSettings.from_env(partial)
    assert settings.free_mode is True
    assert settings.stripe_configured is False


def test_paid_mode_needs_stripe_and_an_explicit_opt_out_of_free() -> None:
    settings = AuditSettings.from_env({**STRIPE, "AUDIT_FREE_MODE": "false"})
    assert settings.free_mode is False
    assert settings.stripe_enabled is True
    still_free = AuditSettings.from_env(STRIPE)
    assert still_free.free_mode is True
    assert still_free.stripe_enabled is False


def test_database_url_normalisation_and_base_url() -> None:
    assert normalise_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalise_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalise_database_url("sqlite:///x.db") == "sqlite:///x.db"
    settings = AuditSettings.from_env(
        {"DATABASE_URL": "postgres://u:p@h/db", "AUDIT_BASE_URL": "https://audit.example/"}
    )
    assert settings.database_kind == "postgresql"
    assert settings.base_url == "https://audit.example"


def test_trusted_proxy_hops_defaults_to_zero_and_reads_the_environment() -> None:
    assert AuditSettings.from_env({}).trusted_proxy_hops == 0
    assert AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": ""}).trusted_proxy_hops == 0
    assert AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": "1"}).trusted_proxy_hops == 1
    with pytest.raises(ValueError):
        AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": "-1"})
    with pytest.raises(ValueError):
        AuditSettings(trusted_proxy_hops=11)
