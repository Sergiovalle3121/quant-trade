"""The shared visual system: static files, fonts and the enhancement script."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import legal_url  # noqa: E402
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
    assert "<b>Se espera:</b>" in card and "<span class='dot warn'>" in page
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


def test_stress_becomes_cards_and_timing_a_compact_table_on_phones(tmp_path: Path) -> None:
    from quant_trade.audit.report import KPI_CSS

    page = _client(tmp_path).get("/ejemplo").text
    stress = page.split("<table class='stress'>", 1)[1].split("</table>", 1)[0]
    timing = page.split("<table class='timing'>", 1)[1].split("</table>", 1)[0]
    assert "data-l='Queda'" in stress and "data-l='¿Sigue sobre cero?'" in stress
    assert "<td class='empty'></td>" in stress
    assert "data-l='Operaciones'" in timing and "data-l='Aciertos'" in timing
    assert ".stress td[data-l]::before{" in STYLE
    # Eleven day and hour rows read better as one short table than as tall cards.
    assert ".timing td[data-l]::before" not in STYLE
    assert ".timing td:first-child::first-letter{text-transform:uppercase}" in STYLE
    # A lone last key figure spans the row on phones instead of leaving a gap.
    assert ".kpis>.kpi:last-child:nth-child(odd){grid-column:1/-1}" in KPI_CSS
    assert find_claims(page) == []


def test_deposit_rows_are_cards_on_phones_and_facts_share_a_printed_row(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/ejemplo").text
    deposits = page.split("<table class='metrics deposits'>", 1)[1].split("</table>", 1)[0]
    assert "data-l='Importe'" in deposits and "data-l='Balance antes'" in deposits
    assert ".deposits td[data-l]::before" in STYLE
    assert ".facts{display:block}.fact{break-inside:avoid;display:inline-block" in STYLE


def test_upload_form_leaves_no_lone_field_on_desktop() -> None:
    page = landing(locale="es", free_mode=False, price_usd=29, access_codes=True)
    grid = page.split("<div class='form-grid'>", 1)[1].split("<details", 1)[0]
    assert "name='access_code'" in grid and "name='optimization'" in grid
    assert ".form-grid>:last-child:nth-child(odd){grid-column:1/-1}" in STYLE


def test_account_losses_read_red_and_reading_notes_are_a_list(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/ejemplo").text
    # Percent gain, money result and open loss of the sample account are losses.
    assert page.count("<div class='fact neg'>") >= 3
    assert "<div class='read-notes'><p>Avisos de lectura</p><ul><li>" in page
    assert ".read-notes{" in STYLE and "Input values" not in page
    assert find_claims(page) == []


def test_held_back_capital_reads_as_a_card() -> None:
    from quant_trade.audit.report import LABELS, _capital_html

    reason = "needs trades spread over at least 90 days"
    held = _capital_html({"status": "NOT_MEASURED", "reason": reason}, "es", LABELS["es"])
    assert held.startswith("<div class='live-verdict held'>") and "NOT_MEASURED" in held
    assert LABELS["es"]["capital_missing"][:30] in held


def test_form_labels_are_tied_to_their_fields_and_greys_meet_contrast() -> None:
    page = landing(locale="es", free_mode=False, price_usd=29, access_codes=True)
    for name in ("challenge", "locale", "access_code", "trials", "description"):
        assert f"<label for='f-{name}'>" in page and f"id='f-{name}'" in page
    assert "aria-describedby='f-access_code-help'" in page
    # 4.5:1 on the page and card backgrounds, light and dark.
    assert "--text-3:#72727a" not in STYLE and "--text-3:#707077" not in STYLE
    assert "--text-3:#66666e" in STYLE and "--text-3:#84848b" in STYLE
    assert "--ok:#17742f" in STYLE and "--warn:#9a5200" in STYLE
    assert ".drop:focus-within{outline" in STYLE and "height:44px;transform" in STYLE


def test_risk_percentiles_are_cards_and_values_keep_their_tag() -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result

    page = render_html(sample_result("es", bootstrap_samples=60), watermark=False, locale="es")
    assert page.count("Drawdown máximo a un año · p") == 3
    assert "<td></td><td>" not in page
    assert "<span class='vc'>" in page and ".vc{white-space:nowrap}" in STYLE


def test_an_error_with_a_fix_puts_the_fix_on_its_own_line() -> None:
    from quant_trade.audit.pages import error_page

    es = error_page(
        "El archivo de optimización es de otra prueba (símbolo GBPJPY; el informe dice "
        "EURUSD): sube la optimización del mismo robot, símbolo y marco temporal.",
        locale="es",
    )
    assert "<p class='err-msg'>El archivo de optimización es de otra prueba" in es
    assert "EURUSD).</p><p class='err-exp'><b>Qué hacer:</b> Sube la optimización" in es
    en = error_page(
        "the optimisation file is for another test (symbol GBPJPY; the report says EURUSD): "
        "upload the optimisation of the same robot, symbol and timeframe",
        locale="en",
    )
    assert "<b>What to do:</b> Upload the optimisation" in en
    assert find_claims(es) == [] and find_claims(en) == []


def test_long_key_figures_step_down_to_fit_a_phone_tile() -> None:
    from quant_trade.audit.report import KPI_CSS, render_html
    from quant_trade.audit.sample import sample_result
    from quant_trade.audit.schema import AuditResult

    data = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    data["performance"]["total_return"]["value"] = 1911.36
    page = render_html(AuditResult.model_validate(data), watermark=False, locale="es")
    assert "<div class='kpi  long'><b>+191,136.0%</b>" in page
    assert "<div class='kpi good long'><b>+4,529.30</b>" in page
    assert "class='kpi  long'><b>560 · 56%" not in page
    assert "<div class='tscroll'><table>" in page
    assert ".kpi.long b{font-size:" in KPI_CSS and ".kpi.xlong b{font-size:" in KPI_CSS
    data["performance"]["total_return"]["value"] = 100000.046
    huge = render_html(AuditResult.model_validate(data), watermark=False, locale="es")
    assert "<div class='kpi  xlong'><b>+10,000,004.6%</b>" in huge


def test_grid_capital_hold_back_puts_the_fix_on_its_own_line() -> None:
    from quant_trade.audit.report import LABELS, _capital_html
    from quant_trade.audit.sizing import HIDDEN_LOSSES

    for locale in ("es", "en"):
        held = _capital_html(
            {"status": "NOT_MEASURED", "reason": HIDDEN_LOSSES}, locale, LABELS[locale]
        )
        assert held.startswith("<div class='live-verdict held'>")
        assert f"<b>{LABELS[locale]['what_to_do']}</b> " in held
        assert ("Sube una curva" if locale == "es" else "Upload an equity curve") in held
        assert find_claims(held) == []


def test_huge_chart_axes_and_monthly_cells_stay_on_the_page() -> None:
    from quant_trade.audit import charts
    from quant_trade.audit.theme import STYLE

    assert charts._fmt_number(1.5e12) == "1.5T"
    assert charts._fmt_number(2.0e18) == "2.0e18"
    assert charts._fmt_number(-2.5e16) == "-2.5e16"
    fan = {
        k: [1.0, 1e15 * m]
        for k, m in zip(charts.FAN_PERCENTILES, (0.2, 0.5, 1, 1.5, 2), strict=True)
    }
    svg = charts.fan_chart(fan)
    assert "000000.0B" not in svg and "2.0e15" in svg
    ticks = [0.0, 1_000_000.0, 2_000_000.0]
    assert charts._axis_left(ticks, lambda v: f"{v:,.1f}B") > charts.MARGIN_LEFT
    assert charts._axis_left([0.0, 0.5, 1.0], charts._fmt_number) == charts.MARGIN_LEFT
    table = charts.monthly_heatmap(
        ["2023-01-31", "2023-02-28", "2023-03-31"], [1e4, 1e4, 1e9], locale="es"
    )
    assert '<td class="long" style=' in table
    assert "table.monthly td.long{" in STYLE and ".chart-scroll{overflow:visible}" in STYLE


def test_losing_history_capital_card_reads_as_one_sentence() -> None:
    from quant_trade.audit.report import LABELS, _capital_html
    from quant_trade.audit.sizing import NET_LOSS

    cases = (("es", "Las operaciones cerradas", "pierde."), ("en", "The closed trades", "loses."))
    for locale, start, end in cases:
        held = _capital_html({"status": "NOT_MEASURED", "reason": NET_LOSS}, locale, LABELS[locale])
        assert held.startswith("<div class='live-verdict held'>")
        assert f"<span class='muted'>{start}" in held and f"{end}</span>" in held
        assert find_claims(held) == []


def test_full_report_flags_and_not_measured_read_as_cards() -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result
    from quant_trade.audit.schema import AuditResult
    from quant_trade.audit.theme import STYLE

    data = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    data["red_flags"] = [
        {
            "code": "PROFIT_CONCENTRATION",
            "severity": "WARN",
            "detail": "the best trade makes 41% of the total of the winning trades (64 trades)",
            "value": 0.41,
        },
        {"code": "IMPLAUSIBLE_SHARPE", "severity": "FAIL", "detail": "sharpe 9.1", "value": 9.1},
    ]
    data["benchmark"] = {"status": "NOT_MEASURED", "reason": "no benchmark was uploaded"}
    for locale in ("es", "en"):
        page = render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
        cards = page[page.index("<ul class='flag-list acct-flags flag-cards'>") :]
        # The graver flag comes first; the code stays, small, under its title.
        assert cards.index("IMPLAUSIBLE_SHARPE") < cards.index("PROFIT_CONCENTRATION")
        assert "<p class='flag-code'>PROFIT_CONCENTRATION</p>" in cards
        assert "<td>PROFIT_CONCENTRATION</td>" not in page
        assert "<ul class='nm-list'><li><b>" in page
        assert ("Resultado concentrado" if locale == "es" else "Result carried") in cards
        assert find_claims(page) == []
    assert ".nm-list li{" in STYLE and ".flag-cards li,.nm-list li{break-inside:avoid" in STYLE
    # Huge figures wrap inside their cell in the PDF instead of leaving the page.
    assert "td+td{overflow-wrap:anywhere}" in STYLE


def test_declared_midnight_dates_and_seal_rows_read_plainly() -> None:
    from quant_trade.audit.report import LABELS, _evidence_rows, _fmt

    assert _fmt("2024-06-03T00:00:00Z") == "2024-06-03"
    assert _fmt("2024-06-02T23:59:59Z") == "2024-06-02T23:59:59Z"
    held = {"status": "NOT_MEASURED", "reason": "no benchmark was uploaded"}
    assert _evidence_rows(held, LABELS["es"], skip=set()) == ""


def test_report_ends_with_one_tidy_footer_bar() -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result
    from quant_trade.audit.schema import AuditResult
    from quant_trade.audit.theme import STYLE

    for locale in ("es", "en"):
        data = sample_result(locale, bootstrap_samples=60).model_dump(mode="json")
        page = render_html(
            AuditResult.model_validate(data), watermark=False, locale=locale, legal_links=True
        )
        foot = page[page.index("<div class='report-foot'>") :]
        assert "<p class='rf-sha'><span>" in foot
        bar = foot[foot.index("<div class='rf-bar'>") :]
        assert bar.index("<p class='rf-brand'><b>Rigor</b>") < bar.index("<nav class='rf-links'>")
        assert bar.count("<a ") == 3 and "class='no-print'" in bar
        assert find_claims(foot) == []
        bare = render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
        assert bare[bare.index("<nav class='rf-links'>") :].count("<a ") >= 1
    assert ".rf-bar{" in STYLE and "@media print{.rf-links{display:block}" in STYLE


def test_landing_mockup_ends_sharp() -> None:
    from quant_trade.audit.theme import STYLE

    # overflow:hidden made the hero the scroll-driven tilt's scroller, which never
    # scrolls, so the mockup stayed tilted (and soft) forever; clip is not a scroller.
    assert ".hero{position:relative;overflow:hidden;overflow:clip;" in STYLE
    # The entrance fade leaves no filter behind on the text or the mockup.
    rise = STYLE[STYLE.index(".rise{") :]
    assert "filter" not in rise[: rise.index("}")]
    assert "@keyframes rise{to{opacity:1;transform:none}}" in STYLE


def test_refusals_read_calm_with_sizes_and_what_to_do() -> None:
    from quant_trade.audit.pages import error_page
    from quant_trade.audit.theme import STYLE
    from quant_trade.audit.web import _megabytes, message

    assert _megabytes(10_000_000) == "10 MB" and _megabytes(1_500_000) == "1.5 MB"
    assert _megabytes(25_000) == "25 KB"
    for locale, label in (("es", "Qué hacer:"), ("en", "What to do:")):
        big = error_page(
            message("too_large", locale, what="de optimización", limit="10 MB"), locale=locale
        )
        assert f"<p class='err-exp'><b>{label}</b> " in big and "10 MB" in big
        assert "bytes" not in big
        assert find_claims(big) == []
    dates = error_page(
        "las fechas pueden ser día/mes o mes/día; expórtalas como AAAA-MM-DD y vuelve a subir "
        "el archivo"
    )
    assert "mes/día.</p><p class='err-exp'><b>Qué hacer:</b> Expórtalas como" in dates
    assert dates.rstrip().count("el archivo.</p>") == 1
    # A refusal is a fix to make, not an alarm: amber rail and dot, not red.
    assert "border-left:4px solid var(--warn)" in STYLE
    assert "class='dot warn'" in dates or 'class="dot warn"' in dates


def test_verification_details_show_figures_with_their_evidence_badge() -> None:
    from quant_trade.audit.pages import verification_page
    from quant_trade.audit.sample import sample_result
    from quant_trade.audit.store import public_view

    for locale in ("es", "en"):
        view, sha = public_view(sample_result(locale, bootstrap_samples=60).model_dump_json())
        page = verification_page(
            view,
            public_id="a1b2c3d4e5",
            published_at="2026-09-25T12:00:00Z",
            result_sha256=sha,
            base_url="https://example.test",
            locale=locale,
        )
        assert "(DECLARED)" not in page and "(MEASURED)" not in page
        assert "<span class='vc'>120 <span class='badge DECLARED'>DECLARED</span></span>" in page
        assert f"<code>{sha}</code>" in page
        # A buyer holding the PDF or JSON is pointed to the page that checks it.
        check = "/check" if locale == "en" else "/comprobar"
        assert "<p class='check-cta'>" in page and f"<a href='{check}'>" in page
        assert find_claims(page) == []


def test_phone_report_is_compact_and_reads_in_words() -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result

    for locale, none_text, gap in (
        ("es", "Sin banderas rojas en los archivos auditados.", "Diferencia de Sharpe"),
        ("en", "No red flags in the audited files.", "Sharpe gap"),
    ):
        html_text = render_html(
            sample_result(locale, bootstrap_samples=60), watermark=False, locale=locale
        )
        # Reasons per dimension become cards on a phone; the evidence badge
        # shares the label's line; timing stays a compact table.
        assert "<table class='reasons'>" in html_text
        assert ".metrics.ev td:nth-child(3){grid-area:1/2" in html_text
        assert ".paper table.timing{overflow:visible;font-size:.86rem}" in html_text
        # An empty flag list is a calm line, and raw engine keys read as words.
        assert "<p class='no-flags'>" in html_text and none_text in html_text
        assert "<td>sharpe_annualised</td>" not in html_text and "<td>gap</td>" not in html_text
        assert gap in html_text


def test_landing_form_help_is_short_and_the_footer_says_things_once() -> None:
    for locale, short, question in (
        ("es", "Tal cual lo guarda tu plataforma: HTML, XLSX o CSV, hasta 10 MB.", "¿Qué archivo"),
        ("en", "As your platform saves it: HTML, XLSX or CSV, up to 10 MB.", "Which file"),
    ):
        page = landing(locale=locale, free_mode=False, price_usd=29, access_codes=True)
        # One line under the main file; the formats and export guides open on demand.
        assert short in page
        assert f"<details class='more-help'><summary>{question}" in page
        assert page.count(">MetaTrader 5</a>") >= 1
        # The footer names the brand, the notice and the legal pages once each.
        foot = page.split("<footer class='foot'>", 1)[1]
        assert "foot-base" not in foot and foot.count(legal_url("terms", locale)) == 1
        assert find_claims(page) == []
    # How it works: number and text share a row on phones.
    assert ".steps li{display:grid;grid-template-columns:44px minmax(0,1fr)" in STYLE


def test_check_page_is_a_drop_zone_and_is_linked_where_a_buyer_needs_it(tmp_path: Path) -> None:
    from quant_trade.audit.report import render_html
    from quant_trade.audit.sample import sample_result

    client = _client(tmp_path)
    for path, other, link in (
        ("/comprobar", "/check", "Cómo lo comprueba"),
        ("/check", "/comprobar", "How they check"),
    ):
        page = client.get(path).text
        # The same drop zone as the upload, with how the check works as icon steps.
        assert "<div class='drop drop-main'>" in page and "<ol class='chk-steps'>" in page
        assert "btn btn-primary btn-lg" in page
        # Every footer links the page, in the page's own language.
        foot = page.split("<footer class='foot'>", 1)[1]
        assert f"href='{path}'" in foot and f"href='{other}'" not in foot
        locale = "en" if path == "/check" else "es"
        report = render_html(
            sample_result(locale, bootstrap_samples=60),
            watermark=False,
            locale=locale,
            pdf_url="/audits/x/pdf",
        )
        # Next to the report's PDF download, the page that checks it.
        assert f"<a href='{path}'>{link}</a>" in report
        assert find_claims(page) == [] and find_claims(report) == []
    # An unmatched file reads as a caution, not as an alarm.
    assert ".chk-result.bad{--tone:var(--warn)}" in client.get("/comprobar").text


@pytest.mark.parametrize(("locale", "lead"), [("es", "Pregunta"), ("en", "Ask")])
def test_behaviour_findings_read_as_what_it_shows_then_the_question(locale: str, lead: str) -> None:
    from quant_trade.audit.report import LABELS, _behaviour_ask

    for code in ("losers_held_longer", "quick_after_loss", "worse_after_streak"):
        text = LABELS[locale]["beh_" + code]
        item = _behaviour_ask(text)
        # The finding in bold, the question to the seller on its own line.
        assert "<p class='beh-what'>" in item and "<p class='beh-ask'><svg" in item
        assert f"<span>{lead} " in item
        plain = re.sub(r"<[^>]+>", " ", item)
        assert " ".join(plain.split()) == " ".join(text.split())
    assert ".beh-asks li{margin-top:12px" in STYLE


def test_instrument_findings_read_like_behaviour_ones_and_a_lone_fact_sits_in_a_row() -> None:
    from test_audit_instruments import _book

    from quant_trade.audit.instruments import instrument_review
    from quant_trade.audit.report import LABELS, _instruments_html

    trades, symbols = _book(
        {"XAUUSD": [50.0] * 15, "EURUSD": [-5.0, 2.0] * 10, "GBPUSD": [-6.0, 3.0] * 10}
    )
    review = instrument_review(trades, symbols)
    for locale, lead in (("es", "Pregunta"), ("en", "Ask")):
        html = _instruments_html(review, locale, LABELS[locale])
        # Each finding: what the trades show, then the question on its own line.
        assert "<ul class='beh-asks'>" in html and html.count("<p class='beh-ask'>") == 2
        assert f"<span>{lead} " in html
        assert find_claims(html) == []
    # One headline figure reads as a row beside its sentence on screens, not a lone tile.
    assert "@media screen and (min-width:621px){.facts>.fact:only-child{display:flex" in STYLE


def test_the_live_account_line_sits_apart_under_the_verdict_with_its_tone(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/ejemplo").text
    # The sample carries a live account: one line under the verdict, toned by the outcome.
    assert "<p class='verdict-live weak'>" in page
    for tone, token in (("pass", "--ok"), ("weak", "--warn"), ("fail", "--bad")):
        assert f".verdict-live.{tone}::before{{background:var({token})" in STYLE
    assert ".verdict-live{margin:20px 0 0;padding-top:16px;border-top:1px solid" in STYLE
    # In the PDF it keeps the verdict's print size and turns black like it.
    assert ".verdict-text,.verdict-lead,.verdict-live," in STYLE
    assert ".verdict-live{border-top-color:#ddd;font-size:9pt" in STYLE


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_fund_calendar_keeps_its_years_in_view_and_fits_the_pdf(locale: str) -> None:
    from test_audit_fund import _grid_csv, _returns

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.report import LABELS, render_html
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(_grid_csv(_returns(36)), DeclaredMetadata(locale=locale))
    html = render_html(
        run_audit(inputs, bootstrap_samples=200, risk_samples=300), watermark=False, locale=locale
    )
    # The last column is the year's total, named apart from the year column.
    assert f"<th class='tot'>{LABELS[locale]['fund_total']}</th>" in html
    assert LABELS[locale]["fund_total"] != LABELS[locale]["fund_year"]
    assert find_claims(LABELS[locale]["fund_total"]) == []
    # On a phone the table scrolls inside its frame and the year column stays put.
    assert ".fund-cal th[scope=row]{position:sticky;left:0" in STYLE
    assert ".paper .fund-cal-wrap table.fund-cal{display:table;overflow:visible" in STYLE
    # In the PDF it drops the screen width and fits the page.
    assert ".paper .fund-cal-wrap table.fund-cal{min-width:0;width:100%" in STYLE


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_universal_file_shows_each_column_and_what_it_was_read_as(locale: str) -> None:
    from test_audit_universal_import import _trades_csv

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.report import LABELS, render_html
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    declared = DeclaredMetadata(locale=locale, initial_balance=5_000)
    inputs = build_inputs(None, declared, report_bytes=_trades_csv(), report_filename="x.csv")
    html = render_html(
        run_audit(inputs, bootstrap_samples=200, risk_samples=300), watermark=False, locale=locale
    )
    assert LABELS[locale]["colmap"] in html and find_claims(LABELS[locale]["colmap"]) == []
    entry = "hora de entrada" if locale == "es" else "entry time"
    assert "<li><code>Open Time</code><svg" in html and f"<span>{entry}</span></li>" in html
    # The columns leave the platform table instead of repeating "Column read as" ten times.
    assert ("Columna leída como" if locale == "es" else "Column read as") not in html
    # Symbol comes first, as a trader reads a row.
    assert html.index("<code>Symbol</code>") < html.index("<code>Open Time</code>")
    assert (
        ".colmap-list{list-style:none" in STYLE and ".colmap-list li{display:inline-block" in STYLE
    )


def test_what_to_do_now_reads_as_numbered_steps_with_a_link_to_each_section(
    tmp_path: Path,
) -> None:
    page = _client(tmp_path).get("/ejemplo").text
    assert "<ol class='next-steps'>" in page and "class='muted evidence-legend'" in page
    # Each step is a card with its number in a disc; the last one (keep the report) is quieter.
    assert ".next-steps li::before{content:counter(ns)" in STYLE
    assert (
        ".next-steps li:last-child{margin-bottom:0;background:transparent;border-style:dashed"
        in STYLE
    )
    # The link to the section ends in an arrow (a CSS escape, not a stray control character).
    assert ".next-steps a::after{content:' \\2192'}" in STYLE
    # Margins, not flex gap, so the PDF keeps the spacing.
    assert ".next-steps li{break-inside:avoid;font-size:9pt" in STYLE


def test_audience_pages_show_problems_checks_price_and_other_cases_as_cards(
    tmp_path: Path,
) -> None:
    from quant_trade.audit.audiences import audience_url

    client = _client(tmp_path)
    for locale in ("es", "en"):
        page = client.get(audience_url("compradores-de-robots", locale))
        assert page.status_code == 200
        html = page.text
        for cls in ("checks aud-pains", "checks aud-checks", "aud-price", "aud-others"):
            assert f"class='{cls}'" in html
        # A check named as a question keeps its question mark alone.
        assert "?.</strong>" not in html
    assert "@media (min-width:760px){.aud-checks{grid-template-columns:repeat(2" in STYLE
    assert ".prose .aud-pains,.prose .aud-checks,.prose .aud-others{padding-left:0}" in STYLE


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_name_its_columns_step_groups_fields_by_file_shape(tmp_path: Path, locale: str) -> None:
    page = _client(tmp_path).get(f"/?lang={locale}").text
    groups = (
        ("Una fila por operación", "Una fila por ejecución", "En los dos casos")
        if locale == "es"
        else ("One row per trade", "One row per fill", "Either way")
    )
    starts = [page.index(f"<legend>{title}</legend>") for title in groups]
    assert starts == sorted(starts)
    assert all(find_claims(title) == [] for title in groups)
    # Each group holds its own fields: per trade has the entry, per fill the fill time.
    trade = page[starts[0] : starts[1]]
    fill = page[starts[1] : starts[2]]
    assert "name='col_entry_time'" in trade and "name='col_time'" not in trade
    assert "name='col_time'" in fill and "name='col_price'" in fill
    for role in ("side", "quantity", "symbol", "profit", "commission", "multiplier"):
        assert f"name='col_{role}'" in page[starts[2] :]
    # The file's own column names show as chips once a file is picked (filled by app.js).
    assert "id='report-columns-shown' hidden>" in page
    assert ".map-found code{display:inline-block" in STYLE
