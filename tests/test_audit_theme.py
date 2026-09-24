"""The shared visual system: static files, fonts and the enhancement script."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import (  # noqa: E402
    STATIC_CACHE_CONTROL,
    STATIC_DIR,
    STATIC_FILES,
    STYLE,
    static_file,
)
from quant_trade.audit.web import create_app  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db")
    return TestClient(
        create_app(settings, make_store(settings.database_url)), raise_server_exceptions=False
    )


def test_every_listed_static_file_exists_and_every_font_has_its_licence() -> None:
    for name in STATIC_FILES:
        assert (STATIC_DIR / name).is_file(), name
    for licence in ("OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
        assert "Open Font License" in (STATIC_DIR / "fonts" / licence).read_text()


def test_static_route_serves_only_the_allow_list(tmp_path: Path) -> None:
    client = _client(tmp_path)
    font = client.get("/static/fonts/inter-var.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    assert font.headers["Cache-Control"] == STATIC_CACHE_CONTROL
    script = client.get("/static/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    for path in ("/static/fonts/OFL-Inter.txt", "/static/../web.py", "/static/%2e%2e/web.py"):
        assert client.get(path).status_code == 404, path
    assert static_file("../web.py") is None


def test_script_never_sends_anything_anywhere() -> None:
    script = (STATIC_DIR / "app.js").read_text()
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "eval(", "innerHTML"):
        assert word not in script, word


def test_pages_use_self_hosted_fonts_and_no_third_party() -> None:
    assert "/static/fonts/" in STYLE and "prefers-reduced-motion" in STYLE
    for locale in ("es", "en"):
        page = landing(locale=locale)
        assert "fonts.googleapis" not in page and "cdn." not in page
        assert find_claims(page) == []


def test_navigation_has_a_phone_menu_and_links_the_comparison() -> None:
    for locale, compare in (("es", "/comparar"), ("en", "/compare")):
        page = landing(locale=locale)
        nav = page.split("<header", 1)[1].split("</header>", 1)[0]
        # The menu opens without script, and holds the same links.
        assert "<details class='menu'>" in nav and "class='menu-panel'" in nav
        assert nav.count(f"href='{compare}'") == 2
        footer = page.split("<footer", 1)[1]
        assert f"href='{compare}'" in footer


def test_landing_leads_with_the_product_and_real_key_figures() -> None:
    from quant_trade.audit.pages import PLATFORMS
    from quant_trade.audit.prop_presets import PRESETS
    from quant_trade.audit.redflags import FLAG_TITLES

    for locale in ("es", "en"):
        page = landing(locale=locale)
        # The illustration sits under the headline and says it is synthetic.
        assert page.index("<h1") < page.index("class='stage") < page.index("class='specs'")
        assert ("sintéticos" if locale == "es" else "synthetic") in page
        specs = page.split("class='specs'", 1)[1].split("</div></div>", 1)[0]
        for count in (len(FLAG_TITLES), len(PRESETS), len(PLATFORMS)):
            assert f"<b data-count>{count}</b>" in specs
    # One sans family plus the mono; the old serif is gone from pages and static files.
    assert "Instrument Serif" not in STYLE
    assert not any("instrument" in name for name in STATIC_FILES)
