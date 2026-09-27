"""E-mail confirmation and recovery copy on all three account page languages."""

from __future__ import annotations

import pytest

from quant_trade.audit import account_pages
from quant_trade.audit.mail import PATHS as EMAIL_PATHS
from quant_trade.audit.store import AccountRecord


@pytest.mark.parametrize(
    ("locale", "account_path", "forgot_path", "pending_phrase"),
    [
        ("es", "/cuenta", "/olvide", "Cambio pendiente"),
        ("en", "/account", "/forgot", "Change pending"),
        ("pt", "/pt/conta", "/pt/esqueci", "Troca pendente"),
    ],
)
def test_confirmation_status_and_recovery_forms_follow_delivery_state(
    locale: str, account_path: str, forgot_path: str, pending_phrase: str
) -> None:
    account = AccountRecord("a1", "old@example.com", locale, "2026-09-27")
    common = dict(
        locale=locale,
        account=account,
        audits=(),
        codes=(),
        credits=0,
        csrf="test-csrf",
        now="2026-09-27",
    )

    waiting = account_pages.account_page(
        **common,
        email_verified=False,
        email_pending="new@example.com",
        email_delivery_ready=True,
        email_verification_required=True,
        flash="email_pending",
    )
    assert f"action='{account_path}/verificar-correo'" in waiting
    assert f"action='{account_path}/correo'" in waiting
    assert pending_phrase in waiting and "new@example.com" in waiting
    assert "old@example.com" in waiting
    assert "name='csrf' value='test-csrf'" in waiting

    confirmed = account_pages.account_page(
        **common,
        email_verified=True,
        email_delivery_ready=True,
        email_verification_required=True,
        flash="email_verified",
    )
    assert "verificar-correo" in confirmed
    assert f"action='{account_path}/verificar-correo'" not in confirmed

    unavailable = account_pages.account_page(
        **common,
        email_delivery_ready=False,
        email_verification_required=True,
    )
    assert f"action='{account_path}/verificar-correo'" not in unavailable
    assert f"action='{account_path}/correo'" not in unavailable

    legacy = account_pages.account_page(**common)
    assert f"action='{account_path}/correo'" in legacy
    assert "<section class='acct-card acct-email-status'" not in legacy

    forgot = account_pages.forgot_page(
        locale=locale,
        contact_url="https://wa.me/123",
        csrf="test-csrf",
        email_delivery_ready=True,
        flash="email_reset_requested",
    )
    assert f"action='{forgot_path}/enlace'" in forgot
    assert f"action='{forgot_path}'" in forgot  # recovery key remains available
    assert "role='status'" in forgot
    assert "name='email'" in forgot

    offline = account_pages.forgot_page(
        locale=locale, contact_url="https://wa.me/123", csrf="test-csrf"
    )
    assert f"action='{forgot_path}/enlace'" not in offline
    assert f"action='{forgot_path}'" in offline


def test_email_page_copy_has_the_same_keys_in_all_languages() -> None:
    assert set(account_pages.COPY["es"]) == set(account_pages.COPY["en"])
    assert set(account_pages.COPY["es"]) == set(account_pages.COPY["pt"])


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_confirm_link_needs_explicit_post_and_reset_switch_keeps_token(locale: str) -> None:
    confirm_path = EMAIL_PATHS[locale]["verify"]
    token = "abc012.xyz_123"
    confirm = account_pages.email_confirm_page(
        locale=locale, action_path=confirm_path, token=token, csrf="test-csrf"
    )
    assert f"<form method='post' action='{confirm_path}'>" in confirm
    assert "name='csrf' value='test-csrf'" in confirm
    assert f"name='token' value='{token}'" in confirm
    for other in account_pages.LANGUAGES:
        if other == locale:
            continue
        assert f"{EMAIL_PATHS[other]['verify']}?token={token}" in confirm

    reset = account_pages.reset_page(locale=locale, csrf="test-csrf", token=token, email_link=True)
    assert "24 hour" not in reset and "24 horas" not in reset
    assert account_pages.COPY[locale]["reset_email_lead"] in reset
    for other in account_pages.LANGUAGES:
        if other == locale:
            continue
        assert f"{account_pages.path('reset', other)}?token={token}" in reset
