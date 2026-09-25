"""The landing answers, for each kind of visitor, who it is for, what to upload
and what they get, and says nothing about payment that is not true today."""

from __future__ import annotations

import re

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import AUDIENCES, landing


def _paid_landing(locale: str, *, card_payments: bool) -> str:
    return landing(
        locale=locale,
        free_mode=False,
        price_usd=29,
        access_codes=True,
        card_payments=card_payments,
        contact_url="https://wa.me/10000000000",
        pack_price_usd=69,
    )


def test_every_audience_shows_in_every_language() -> None:
    assert set(AUDIENCES) == {"es", "en", "pt"}
    assert {len(words["items"]) for words in AUDIENCES.values()} == {4}
    for locale in ("es", "en", "pt"):
        page = _paid_landing(locale, card_payments=False)
        assert "id='para-quien'" in page
        for _icon, title, *_rest in AUDIENCES[locale]["items"]:
            assert title in page
        assert find_claims(page) == []


def test_audience_texts_pass_the_guard() -> None:
    for words in AUDIENCES.values():
        text = " ".join(" ".join(item[1:5]) for item in words["items"])
        assert find_claims(text) == []
        assert not re.search(r"\bganar|\bearn|\bprofits?\b", text.lower())


def test_landing_names_no_payment_method_it_cannot_show() -> None:
    for locale in ("es", "en"):
        page = _paid_landing(locale, card_payments=False)
        assert "Mercado Pago" not in page
        assert "Pago seguro" not in page and "Secure payment" not in page
    # With cards on, the Stripe line appears.
    assert "Stripe" in _paid_landing("es", card_payments=True)


def test_landing_names_the_recognised_formats_under_the_platform_strip() -> None:
    from quant_trade.audit.audiences import PLATFORMS_EN, PLATFORMS_ES

    for locale, names, words in (
        ("es", PLATFORMS_ES, "Y reconoce el formato de exportación de"),
        ("en", PLATFORMS_EN, "It also recognises the export format of"),
    ):
        page = _paid_landing(locale, card_payments=False)
        also = page.split("class='platforms-also'", 1)[1].split("</p>", 1)[0]
        assert words in also
        assert names.replace("&", "&amp;") in also
        assert "csv" in also
        assert find_claims(also) == []


def test_paid_price_card_explains_the_flow_and_lists_fund_checks() -> None:
    for locale, cta, fund in (
        ("es", "Empieza con la vista previa gratis", "Para fondos: calendario año por mes"),
        ("en", "Start with the free preview", "For funds: year-by-month calendar"),
    ):
        page = _paid_landing(locale, card_payments=False)
        pricing = page.split("id='pricing'", 1)[1]
        assert cta in pricing and fund in pricing
        assert find_claims(pricing) == []


def test_second_files_and_challenge_sit_in_a_closed_extras_box() -> None:
    for locale, summary in (("es", "Añadir más archivos"), ("en", "Add more files")):
        page = _paid_landing(locale, card_payments=False)
        form = page.split("id='subir'", 1)[1].split("</form>", 1)[0]
        before, extras = form.split("<details class='adv extras'>", 1)
        # One file is enough: the main report and the curve come first, open.
        assert "name='report'" in before and "name='equity'" in before
        extras = extras.split("</details>", 1)[0]
        assert summary in extras
        for name in ("optimization", "live", "challenge"):
            assert f"name='{name}'" in extras and f"name='{name}'" not in before
        assert find_claims(extras) == []


def test_pricing_offers_the_free_account_that_the_preview_needs() -> None:
    for locale, words, href in (
        ("es", "gratis al crear tu cuenta; después, 3 vistas previas", "/registro"),
        ("en", "free when you create your account; then 3 free previews", "/signup"),
    ):
        page = _paid_landing(locale, card_payments=False)
        note = page.split("class='muted account-note'", 1)[1].split("</p>", 1)[0]
        assert words in note and f"href='{href}'" in note
        assert find_claims(note) == []


def test_account_note_links_a_live_sign_up_page(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/a.db", base_url="https://x")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    for path in ("/registro", "/signup"):
        assert client.get(path).status_code == 200, path
