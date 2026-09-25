"""The shared visual system: static files, fonts and the enhancement script."""

from __future__ import annotations

import re
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


def test_long_pages_have_an_index_that_links_every_section(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, label in (
        ("/terminos", "En esta página"),
        ("/privacy", "On this page"),
        ("/guias/mt5", "En esta página"),
    ):
        page = client.get(path).text
        assert label in page and "data-toc" in page, path
        headings = re.findall(r"<h2 id='(s\d+)'>", page)
        links = re.findall(r"<li><a href='#(s\d+)'>", page)
        assert headings and headings == links, path
        assert find_claims(page) == []


def test_the_class_range_never_breaks_across_lines() -> None:
    assert "A a D." in landing(locale="es")
    assert "A to D." in landing(locale="en")
    assert "@media (max-width:620px){.statement{" in STYLE


def test_each_dimension_has_its_own_icon() -> None:
    from quant_trade.audit.pages import _DIMENSION_ICONS
    from quant_trade.audit.theme import ICONS

    names = list(_DIMENSION_ICONS.values())
    assert len(set(names)) == len(names)
    assert len({ICONS[name] for name in names}) == len(names)


def test_a_chosen_report_turns_the_drop_zone_into_a_ready_state() -> None:
    assert ".drop-main.has .icon svg{display:none}" in STYLE
    assert ".drop-main.has .formats{display:none}" in STYLE
    assert 'zone.classList.toggle("has"' in (STATIC_DIR / "app.js").read_text()


def test_guide_steps_wrap_long_code_lines_on_phones() -> None:
    # A step like pf.trades.records_readable.to_csv(...) must not widen the page.
    assert "grid-template-columns:minmax(0,1fr)}\n.list-steps li{overflow-wrap:anywhere}" in STYLE


def test_methodology_page_uses_cards_badges_and_chips() -> None:
    from quant_trade.audit.pages import method_page

    for locale in ("es", "en"):
        page = method_page(locale=locale)
        assert page.count("<div class='mdim'>") == 6
        assert page.count("<li class='rung'") == 4
        assert "<span class='badge MEASURED'>MEASURED</span>" in page
        assert "<ul class='chips'>" in page and "checks nots" in page
        assert find_claims(page) == []


def test_every_footer_and_the_landing_link_the_methodology(tmp_path: Path) -> None:
    from quant_trade.audit.pages import INVESTOR_COPY

    client = _client(tmp_path)
    for path, target in (
        ("/", "/metodologia"),
        ("/en", "/methodology"),
        ("/guias", "/metodologia"),
    ):
        page = client.get(path).text
        foot = page.split("<footer", 1)[1]
        assert f"href='{target}'" in foot
    for locale, path in (("es", "/"), ("en", "/en")):
        page = client.get(path).text
        assert "class='investor'" in page and INVESTOR_COPY[locale]["title"] in page
        assert (
            "/guias/cuenta-proveedor'" if locale == "es" else "/guides/provider-account'"
        ) in page
        assert find_claims(page) == []


def test_prop_simulator_ranges_are_cards_and_open_losses_a_callout() -> None:
    from dataclasses import replace

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import synthetic_mt5_report
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=synthetic_mt5_report(200),
        report_filename="ReportTester.html",
    )
    deep = {"declared_equity_drawdown_relative": "40.51% (1 027.00)"}
    inputs = replace(inputs, report_metadata={**inputs.report_metadata, **deep})
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, challenge_samples=200)
    for locale in ("es", "en"):
        page = render_html(result, watermark=False, locale=locale)
        challenge = page.split("class='live-verdict lv-FAIL'", 1)[1]
        # The 95 % range and the days to target read as two fact cards, one tag each.
        facts = challenge.split("<div class='facts'>", 1)[1].split("</div></div>", 1)[0]
        assert facts.count("<div class='fact'>") == 2 and " – " in facts and " / " in facts
        assert facts.count('class="badge MEASURED"') == 2
        # The break-even tile keeps one short number; the pips go in its label.
        assert re.search(r"<b>[\d.,]+</b><span>[^<]*pips\)</span>", page)
        assert find_claims(page) == []


def test_guides_index_lists_backtests_and_live_accounts_apart(tmp_path: Path) -> None:
    from quant_trade.audit.guides import GUIDES
    from quant_trade.audit.pages import ACCOUNT_GUIDES

    assert {guide.slug for guide in GUIDES} >= ACCOUNT_GUIDES
    client = _client(tmp_path)
    for path, heading in (("/guias", "Cuentas reales"), ("/guides", "Live accounts")):
        page = client.get(path).text
        assert page.count("<section class='guide-group'>") == 2
        backtests, accounts = page.split(f"<h2>{heading}</h2>", 1)
        assert "/myfxbook'" in accounts and "/myfxbook'" not in backtests.split("<main", 1)[-1]
        assert "/mt5'" in backtests
        assert find_claims(page) == []
    # Ten or more platforms sit in two even rows on a wide screen.
    assert "gap:14px 40px;max-width:880px}" in STYLE


def test_error_page_shows_the_field_problem_and_expected_formats_apart() -> None:
    from quant_trade.audit.pages import error_page

    page = error_page(
        "Estado de cuenta real: el archivo no es un informe compatible. Se espera: un informe "
        "de MetaTrader 5 o 4.",
        locale="es",
    )
    card = page.split("<div class='error-card' role='alert'>", 1)[1]
    assert "<p class='err-field'>Estado de cuenta real</p>" in card
    assert "<p class='err-msg'>El archivo no es un informe compatible.</p>" in card
    assert "<b>Se espera:</b>" in card and "<span class='dot bad'>" in page
    # A plain sentence keeps its words and gets no field label.
    plain = error_page("No encontramos esa página. Revisa el enlace.", locale="es")
    assert "<p class='err-field'>" not in plain and "Revisa el enlace." in plain
    assert find_claims(page) == [] and find_claims(plain) == []


def test_capital_limits_read_as_four_cards() -> None:
    from html import escape

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.report import LABELS, render_html
    from quant_trade.audit.sample import synthetic_mt5_report
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=synthetic_mt5_report(200),
        report_filename="ReportTester.html",
    )
    result = run_audit(inputs, bootstrap_samples=100, risk_samples=200, challenge_samples=200)
    for locale in ("es", "en"):
        page = render_html(result, watermark=False, locale=locale)
        tiles = page.split("<ol class='caps'>", 1)[1].split("</ol>", 1)[0]
        assert tiles.count("<li class='cap'>") == 4
        assert tiles.count(escape(LABELS[locale]["capital_needed"])) == 4
        assert "<b>10%</b>" in tiles and "<b>50%</b>" in tiles
        assert find_claims(page) == []
    assert "@media print{ol.caps{display:block}" in STYLE


def test_stress_and_timing_tables_become_cards_on_phones(tmp_path: Path) -> None:
    from quant_trade.audit.report import KPI_CSS

    page = _client(tmp_path).get("/ejemplo").text
    stress = page.split("<table class='stress'>", 1)[1].split("</table>", 1)[0]
    timing = page.split("<table class='timing'>", 1)[1].split("</table>", 1)[0]
    assert "data-l='Queda'" in stress and "data-l='¿Sigue sobre cero?'" in stress
    assert "<td class='empty'></td>" in stress
    assert "data-l='Operaciones'" in timing and "data-l='Aciertos'" in timing
    assert ".stress td[data-l]::before,.timing td[data-l]::before" in STYLE
    # A lone last key figure spans the row on phones instead of leaving a gap.
    assert ".kpis>.kpi:last-child:nth-child(odd){grid-column:1/-1}" in KPI_CSS
    assert find_claims(page) == []
