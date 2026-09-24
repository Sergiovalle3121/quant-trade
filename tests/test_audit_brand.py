"""The product name shows on every page and badge, so it must pass the guard."""

from __future__ import annotations

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import badge_svg, landing
from quant_trade.audit.seo import BRAND, SITE_NAME, TAGLINE


def test_brand_and_tagline_pass_the_guard() -> None:
    for locale in ("es", "en"):
        for text in (BRAND, TAGLINE[locale], SITE_NAME[locale]):
            assert find_claims(text) == [], text


def test_brand_does_not_suggest_verification_or_approval() -> None:
    lowered = " ".join([BRAND, *TAGLINE.values()]).lower()
    for word in ("verif", "certif", "aprob", "approv", "garant", "guarant", "profit", "gana"):
        assert word not in lowered


def test_landing_and_badge_carry_the_brand() -> None:
    for locale, home in (("es", "href='/'"), ("en", "href='/en'")):
        page = landing(locale=locale)
        assert f"<a class='logo' {home}>" in page and f"<span>{BRAND}</span></a>" in page
        assert f"<title>{BRAND}" in page
        badge = badge_svg(overall="C", public_id="abc123", audited_on="2026-09-24", locale=locale)
        assert f"{BRAND} · " in badge
