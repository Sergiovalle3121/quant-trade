"""Settings: no secret defaults, free mode forced without Stripe."""

from __future__ import annotations

from typing import Any

import pytest

from quant_trade.audit.card_markets import EU_MARKETS, MARKET_NAMES, REVIEWED_MARKETS
from quant_trade.audit.settings import AuditSettings, normalise_database_url

STRIPE = {
    "STRIPE_SECRET_KEY": "sk_test_x",
    "STRIPE_WEBHOOK_SECRET": "whsec_x",
    "STRIPE_PRICE_ID": "price_x",
}


def test_reviewed_billing_markets_accept_the_exact_country_list() -> None:
    countries = (
        "MX,US,BR,AT,BE,BG,HR,CY,CZ,DK,EE,FI,FR,DE,GR,HU,IE,IT,LV,LT,LU,MT,NL,PL,PT,"
        "RO,SK,SI,ES,SE,GB"
    )
    expected = frozenset(countries.split(","))
    assert len(EU_MARKETS) == 27
    assert len(expected) == 31
    assert expected == REVIEWED_MARKETS
    assert set(MARKET_NAMES) == expected
    assert all(set(names) == {"es", "en", "pt"} for names in MARKET_NAMES.values())
    assert AuditSettings(approved_markets=expected).approved_markets == expected
    assert (
        AuditSettings.from_env({"AUDIT_APPROVED_MARKETS": countries}).approved_markets == expected
    )
    # Environment normalization still accepts whitespace/lowercase, not aliases.
    assert AuditSettings.from_env(
        {"AUDIT_APPROVED_MARKETS": " gr, gb, de "}
    ).approved_markets == frozenset({"GR", "GB", "DE"})
    assert AuditSettings.from_env({}).approved_markets == frozenset()


@pytest.mark.parametrize("container", [tuple, list])
def test_approved_markets_built_directly_accept_any_iterable(container: Any) -> None:
    """Built directly, a tuple or a list is checked like a frozenset, not a TypeError."""
    reviewed = container(["MX", "GB"])
    assert AuditSettings(approved_markets=reviewed).approved_markets == reviewed
    with pytest.raises(ValueError, match="reviewed ISO countries"):
        AuditSettings(approved_markets=container(["MX", "UK"]))
    with pytest.raises(ValueError, match="reviewed ISO countries"):
        AuditSettings(approved_markets=container(["EL"]))


@pytest.mark.parametrize("country", ["UK", "EL", "CA"])
def test_unreviewed_billing_countries_and_non_iso_aliases_are_rejected(country: str) -> None:
    with pytest.raises(ValueError, match="reviewed ISO countries"):
        AuditSettings(approved_markets=frozenset({"MX", country}))
    with pytest.raises(ValueError, match="reviewed ISO countries"):
        AuditSettings.from_env({"AUDIT_APPROVED_MARKETS": f"MX,{country}"})


def test_defaults_are_free_sqlite_and_secretless() -> None:
    settings = AuditSettings.from_env({})
    assert settings.free_mode is True
    assert settings.stripe_enabled is False
    assert settings.database_kind == "sqlite"
    assert settings.stripe_secret_key == ""
    assert settings.price_usd == 29.0
    assert settings.pack_price_usd_cents == 6900
    assert settings.pack_price_usd == 0.0  # free mode cannot sell a pack


def test_free_mode_is_forced_without_every_stripe_variable() -> None:
    partial = {**STRIPE, "AUDIT_FREE_MODE": "false"}
    del partial["STRIPE_WEBHOOK_SECRET"]
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


def test_empty_smtp_port_and_referral_cap_use_their_defaults() -> None:
    """A variable left blank in a hosting panel means unset, not a crash."""
    blank = AuditSettings.from_env(
        {"AUDIT_SMTP_PORT": "", "AUDIT_REFERRAL_GLOBAL_MONTHLY_CAP": "  "}
    )
    assert blank.smtp_port == 587
    assert blank.referral_global_monthly_cap == 100
    given = AuditSettings.from_env(
        {"AUDIT_SMTP_PORT": "465", "AUDIT_REFERRAL_GLOBAL_MONTHLY_CAP": "7"}
    )
    assert (given.smtp_port, given.referral_global_monthly_cap) == (465, 7)


def test_trusted_proxy_hops_defaults_to_zero_and_reads_the_environment() -> None:
    assert AuditSettings.from_env({}).trusted_proxy_hops == 0
    assert AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": ""}).trusted_proxy_hops == 0
    assert AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": "1"}).trusted_proxy_hops == 1
    with pytest.raises(ValueError):
        AuditSettings.from_env({"AUDIT_TRUSTED_PROXY_HOPS": "-1"})
    with pytest.raises(ValueError):
        AuditSettings(trusted_proxy_hops=11)
