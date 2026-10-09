"""Site copy that cost buyers' trust (errores 10): each fix by HTTP, in es, en and pt.

Every figure a test expects is computed here from the code that sets it (the
settings, ``upload_limits``, ``prop_presets.PRESETS``, the engine's version), never
typed in. The last test walks every page of the sitemap.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.about import ABOUT_ALIASES, ABOUT_COPY, ABOUT_PATH  # noqa: E402
from quant_trade.audit.articles import ARTICLES, ARTICLES_BY_KEY, article_url  # noqa: E402
from quant_trade.audit.audiences import audience_url  # noqa: E402
from quant_trade.audit.calculator import CALCULATOR_PATH  # noqa: E402
from quant_trade.audit.calculator import COPY as CALCULATOR_COPY  # noqa: E402
from quant_trade.audit.check import SAMPLE_AUDIT_ID  # noqa: E402
from quant_trade.audit.engine import ENGINE_NAME  # noqa: E402
from quant_trade.audit.examples import EXAMPLES_PATH  # noqa: E402
from quant_trade.audit.faq import FAQ_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES, guide_url, guides_index_url  # noqa: E402
from quant_trade.audit.method import CHALLENGE_SECTION, METHOD_PATH, references  # noqa: E402
from quant_trade.audit.pages import _UI, AUDIT_PATHS, verification_page  # noqa: E402
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.reading import READING_PATH  # noqa: E402
from quant_trade.audit.report import LABELS  # noqa: E402
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.sample_publication import (  # noqa: E402
    SAMPLE_SHOWN_IDS,
    sample_publication,
)
from quant_trade.audit.seo import PUBLIC_PAGES, SIGNAL_SAMPLE_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import TOOLS_PATH  # noqa: E402
from quant_trade.audit.upload_limits import (  # noqa: E402
    megabytes,
    upload_limit_text,
    upload_limits,
)
from quant_trade.audit.web import accept_language_locale, create_app  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: The evidence labels as a page prints them in front of a figure.
LABEL_PREFIXES = ("DECLARED ·", "Declarado ·", "Declared ·")
OPERATOR = {
    "AUDIT_OPERATOR_NAME": "Ana Operadora",
    "AUDIT_OPERATOR_ADDRESS": "México",
    "AUDIT_OPERATOR_ADDRESS_EN": "Mexico",
    "AUDIT_OPERATOR_CONTACT": "soporte@example.test",
    "AUDIT_CONTACT_URL": "https://wa.me/5215550000000",
    "AUDIT_JURISDICTION": "Ciudad de México",
}


def _settings(directory: Path, **environ: str) -> AuditSettings:
    settings = AuditSettings.from_env(
        {
            "AUDIT_BASE_URL": BASE,
            "AUDIT_FREE_MODE": "false",
            "AUDIT_ACCESS_CODES": "true",
            "AUDIT_PUBLIC_DATA": "false",
            "AUDIT_SKIP_EMAIL_DNS": "true",
            "STRIPE_SECRET_KEY": "sk_live_site_copy_test_only",
            "STRIPE_WEBHOOK_SECRET": "whsec_site_copy_test_only",
            "AUDIT_APPROVED_MARKETS": "MX,BR",
            **environ,
        }
    )
    return replace(settings, database_url=f"sqlite:///{directory}/site.db")


def _client(settings: AuditSettings) -> TestClient:
    # The lifespan is not entered: these pages need no worker thread.
    return TestClient(
        create_app(settings, make_store(settings.database_url)),
        base_url=BASE,
        follow_redirects=False,
    )


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """The paid site with every operator detail set and card payment public."""
    settings = _settings(tmp_path_factory.mktemp("site-copy"), **OPERATOR)
    assert settings.card_public and not settings.free_mode
    client = _client(settings)
    yield client
    client.close()


@pytest.fixture(scope="module")
def free_site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """Free mode, whose upload form opens without an account, with a 2 MB limit."""
    settings = _settings(
        tmp_path_factory.mktemp("site-copy-free"),
        AUDIT_FREE_MODE="true",
        AUDIT_MAX_UPLOAD_BYTES="2000000",
    )
    client = _client(settings)
    yield client
    client.close()


def _visible(page: str) -> str:
    """What a reader sees: no scripts, styles or tags, entities decoded."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))


def _outside_evidence(page: str) -> str:
    """The visible text outside the places evidence labels belong: tables (the
    articles' computed tables, their captions and a report's figures), the SVG
    evidence cards and the evidence lines under each public example on /ejemplos,
    which read a third party's public post."""
    page = re.sub(r"<table\b.*?</table>", " ", page, flags=re.S)
    page = re.sub(r"<svg\b.*?</svg>", " ", page, flags=re.S)
    page = re.sub(r"<p class='example-reading'>.*?</p>", " ", page, flags=re.S)
    return _visible(page)


def _get(client: TestClient, path: str, **headers: str) -> str:
    response = client.get(path, headers=headers)
    assert response.status_code == 200, (path, response.status_code)
    return response.text


# -- 1. The operator's own facts carry no evidence label --------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_faq_states_price_countries_retention_and_limit_without_labels(
    site: TestClient, locale: str
) -> None:
    settings = _settings(Path(), **OPERATOR)
    page = _get(site, FAQ_PATH[locale])
    for prefix in LABEL_PREFIXES:
        assert prefix not in html.unescape(page).replace("\\u00b7", "·"), prefix
    text = _visible(page)
    assert f"USD {settings.price_usd:.2f}" in text
    assert {"es": "México", "en": "Mexico", "pt": "México"}[locale] in text
    days = settings.retention_days
    retention = {"es": f"a los {days} días", "en": f"after {days} days", "pt": f"após {days} dias"}
    assert retention[locale] in text
    assert find_claims(text) == []


# -- 2. One limits sentence from the settings, with what to do --------------------


def test_the_limits_come_from_the_settings_and_round() -> None:
    assert upload_limits(5_000_000) == (5_000_000, 10_000_000)
    # The importers never read a report past schema.MAX_REPORT_BYTES.
    assert upload_limits(20_000_000) == (20_000_000, 10_000_000)
    assert megabytes(7 * 1024 * 1024, "en") == "7.3 MB"
    assert megabytes(7 * 1024 * 1024, "es") == megabytes(7 * 1024 * 1024, "pt") == "7,3 MB"
    assert megabytes(10_000_000, "es") == "10 MB"
    for locale in LOCALES:
        text = upload_limit_text(5_000_000, locale)
        assert "5 MB" in text and "10 MB" in text and "UTF-16" in text and "CSV" in text
        assert "4.76837" not in text and "4,76837" not in text
        assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_faq_and_mt5_guide_print_the_limits_sentence(site: TestClient, locale: str) -> None:
    sentence = html.escape(upload_limit_text(5_000_000, locale), quote=True)
    faq = _get(site, FAQ_PATH[locale])
    guide = _get(site, guide_url("mt5", locale))
    assert sentence in faq and sentence in guide
    what_to_do = {"es": "recorta el periodo", "en": "shorten the period", "pt": "encurte o período"}
    assert what_to_do[locale] in _visible(guide)
    for page in (faq, guide):
        assert "4.76837" not in page and "4,76837" not in page


@pytest.mark.parametrize("locale", LOCALES)
def test_upload_form_prints_the_limits_of_its_own_settings(
    free_site: TestClient, locale: str
) -> None:
    page = _get(free_site, AUDIT_PATHS[locale])
    # AUDIT_MAX_UPLOAD_BYTES=2000000: 2 MB a file and 4 MB a platform report.
    assert html.escape(upload_limit_text(2_000_000, locale), quote=True) in page
    shown = _visible(page)
    assert "2 MB" in shown and "4 MB" in shown
    assert find_claims(shown) == []


# -- 3. No internal path, repository or preset in public text -----------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_prop_article_says_where_the_generic_rules_come_from_in_words(
    site: TestClient, locale: str
) -> None:
    page = _get(site, article_url("cuantos-intentos-reto-prop-firm", locale))
    text = _outside_evidence(page)
    for word in ("docs/", "AUDIT_ITERATION4", "repositorio", "repository", "repositório"):
        assert word not in text, word
    assert not re.search(r"\bpresets?\b", text, re.I)
    assert {"es": "dos fases", "en": "two-step", "pt": "duas fases"}[locale] in text
    assert not any(prefix in text for prefix in LABEL_PREFIXES)


def test_no_article_paragraph_starts_with_an_evidence_label() -> None:
    for article in ARTICLES:
        for locale in LOCALES:
            text = article.text[locale]
            for paragraph in (text.intro, *(p for s in text.sections for p in s.paragraphs)):
                # A paragraph may explain the labels; none opens with one as a tag.
                assert not paragraph.startswith("DECLARED ·"), (article.key, locale)


# -- 4. The engine as the report words it ------------------------------------------


@pytest.fixture(scope="module")
def sample_view() -> tuple[dict[str, object], str]:
    _, _, view, digest = sample_publication("ejemplo", sample_result("es"))
    return view, digest


@pytest.mark.parametrize("locale", LOCALES)
def test_public_page_shows_the_engine_version_as_the_report_does(
    site: TestClient, sample_view: tuple[dict[str, object], str], locale: str
) -> None:
    view, digest = sample_view
    engine = view["engine"]
    assert isinstance(engine, dict)
    # What the purge keeps is unchanged: only its display changed.
    assert engine["name"] == ENGINE_NAME
    version = str(engine["package_version"])
    label = {"es": "Versión del motor", "en": "Engine version", "pt": "Versão do motor"}[locale]
    publication = verification_page(
        view,
        public_id="AbCdEfGhIjKl",
        published_at="2026-10-09T00:00:00+00:00",
        result_sha256=digest,
        base_url=BASE,
        locale=locale,
    )
    sample = _get(site, f"/v/ejemplo?lang={locale}")
    for page in (publication, sample):
        assert f"<tr><td>{html.escape(label)}</td><td>{html.escape(version)}</td></tr>" in page
        assert "quant_trade" not in page


# -- 5. The sample's identifier, the same on its report and its public page --------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("kind", ("backtest", "signal"))
def test_sample_identifier_is_the_same_on_report_and_public_page(
    site: TestClient, kind: str, locale: str
) -> None:
    assert SAMPLE_AUDIT_ID == "sample"  # /comprobar still reads the stored id.
    label = LABELS[locale]["audit_id"]
    assert _UI[locale]["v_id"] == label
    shown = SAMPLE_SHOWN_IDS[kind][locale]
    report_paths = {
        "backtest": {"es": "/ejemplo", "en": "/sample", "pt": "/pt/exemplo"},
        "signal": SIGNAL_SAMPLE_PATHS,
    }
    public_id = {"backtest": "ejemplo", "signal": "ejemplo-senal"}[kind]
    report = _get(site, report_paths[kind][locale])
    public = _get(site, f"/v/{public_id}?lang={locale}")
    assert f"<span>{html.escape(label)} {html.escape(shown)}</span>" in report
    assert f"<b>{html.escape(label)}</b><span>{html.escape(shown)}</span>" in public
    if locale != "en":
        assert f"{label} {SAMPLE_AUDIT_ID}" not in _visible(report)


# -- 6. Pricing: three options, one contact channel ---------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_pricing_support_line_fits_three_options(site: TestClient, locale: str) -> None:
    text = _visible(_get(site, PRICING_PATH[locale]))
    assert PRICING_COPY[locale]["support_note"] in text
    for old in ("ambos informes", "both reports", "ambos os relatórios"):
        assert old not in text


# -- 7. "costos" in Spanish ----------------------------------------------------------


def test_spanish_tools_say_costos(site: TestClient) -> None:
    for path in (WINRATE_PATH["es"], TOOLS_PATH["es"], READING_PATH["es"]):
        text = _visible(_get(site, path))
        assert not re.search(r"\bcostes?\b", text, re.I), path
        assert "costo de equilibrio" in text, path


# -- 8. Rounded figures on the examples ---------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_examples_round_nine_weeks_to_two_decimals(site: TestClient, locale: str) -> None:
    page = _get(site, EXAMPLES_PATH[locale])
    years = {"es": "0,17 años", "en": "0.17 years", "pt": "0,17 anos"}[locale]
    assert years in _visible(page)
    card = ">0.17<" if locale == "en" else ">0,17<"
    assert card in page
    assert "173077" not in page


# -- 9. The calculator's frequency against the report's ---------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_calculator_says_same_formula_and_the_reports_own_frequency(
    site: TestClient, locale: str
) -> None:
    text = _visible(_get(site, CALCULATOR_PATH[locale]))
    sentence = {
        "es": "la misma fórmula que la sección de suerte del informe; el informe usa la "
        "frecuencia real de tu archivo",
        "en": "the same formula as the report's luck section; the report uses your file's "
        "actual frequency",
        "pt": "a mesma fórmula da seção de sorte do relatório; o relatório usa a frequência "
        "real do seu arquivo",
    }[locale]
    assert sentence in text
    assert any(sentence in line for line in CALCULATOR_COPY[locale]["assumptions"])
    for old in ("misma cuenta que la sección", "same arithmetic as", "mesma conta da seção"):
        assert old not in text


# -- 10. Methodology: the report's sources and the challenge simulator --------------


@pytest.mark.parametrize("locale", LOCALES)
def test_methodology_cites_the_reports_sources_and_explains_the_simulator(
    site: TestClient, locale: str
) -> None:
    text = _visible(_get(site, METHOD_PATH[locale]))
    word = {"es": "y", "en": "and", "pt": "e"}[locale]
    for cited in (
        f"Harvey, C. R. {word} Liu, Y. (2015)",
        "Lo, A. W. (2002)",
        f"Ploberger, W. {word} Krämer, W. (1992)",
    ):
        assert any(cited in ref for ref in references(locale)), cited
        assert cited in text, cited
    title, challenge = CHALLENGE_SECTION[locale]
    assert title in text
    assert all(line in text for line in challenge)
    # No new figure: the section describes the method only.
    assert not re.search(r"\d", " ".join(challenge))
    joined = " ".join(challenge)
    for idea in {
        "es": ("bloques de días", "cierre diario", "fecha", "optimista", "operaciones abiertas"),
        "en": ("blocks of consecutive days", "daily close", "date", "optimistic", "open trades"),
        "pt": ("blocos de dias", "fechamento diário", "data", "otimista", "operações abertas"),
    }[locale]:
        assert idea in joined, idea
    assert find_claims(text) == []


# -- 11. The guides index says what the Myfxbook guide says -------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_guides_index_and_myfxbook_guide_agree_on_whose_csv(site: TestClient, locale: str) -> None:
    guide = next(g for g in GUIDES if g.slug == "myfxbook")
    text = guide.text[locale]
    owner = {"es": "dueño", "en": "owner", "pt": "titular"}[locale]
    not_yours = {"es": "no es tuya", "en": "not yours", "pt": "não for sua"}[locale]
    assert owner in text.summary and not_yours in text.summary
    assert any(owner in step and not_yours in step for step in text.steps)
    index = _visible(_get(site, guides_index_url(locale)))
    assert text.summary in index
    assert "Download a Myfxbook account's history as CSV and upload" not in index


# -- 12. Phases and programs, counted from the presets -------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_prop_page_counts_phases_and_programs_from_the_presets(
    site: TestClient, locale: str
) -> None:
    firms = [rules for rules in PRESETS.values() if rules.firm != "Generic"]
    phases, programs = len(firms), len({(r.firm, r.program) for r in firms})
    text = _visible(_get(site, audience_url("retos-prop-firm", locale)))
    expected = {
        "es": f"{phases} fases de {programs} programas",
        "en": f"{phases} phases of {programs} FTMO",
        "pt": f"{phases} fases de {programs} programas",
    }[locale]
    assert expected in text
    # Every firm phase the form offers cites its official page and the day it was read.
    assert all(rules.source_url.startswith("https://") and rules.as_of for rules in firms)


# -- 13. Guessed addresses and "who is behind it" -----------------------------------


@pytest.mark.parametrize(
    ("alias", "target"),
    [
        ("/sample-signal", "/en/sample-signal"),
        ("/en/compare", "/compare"),
        ("/en/signup", "/signup"),
        ("/register", "/signup"),
        ("/pt-br", "/pt"),
        *ABOUT_ALIASES.items(),
    ],
)
def test_guessed_addresses_move_permanently_to_a_page(
    site: TestClient, alias: str, target: str
) -> None:
    response = site.get(alias)
    assert response.status_code == 301, alias
    assert response.headers["location"] == target
    assert site.get(target).status_code == 200


def test_signup_aliases_keep_the_query(site: TestClient) -> None:
    response = site.get("/en/signup?next=/en/audit")
    assert response.status_code == 301
    assert response.headers["location"] == "/signup?next=/en/audit"


@pytest.mark.parametrize("locale", LOCALES)
def test_about_page_shows_only_the_published_operator_details(
    site: TestClient, locale: str
) -> None:
    page = _get(site, ABOUT_PATH[locale])
    words = ABOUT_COPY[locale]
    assert f"<html lang='{locale}'>" in page
    assert f"<link rel='canonical' href='{BASE}{ABOUT_PATH[locale]}'>" in page
    text = _visible(page)
    assert words["title"] in text
    assert OPERATOR["AUDIT_OPERATOR_NAME"] in text
    country = OPERATOR["AUDIT_OPERATOR_ADDRESS_EN" if locale == "en" else "AUDIT_OPERATOR_ADDRESS"]
    assert country in text
    assert "href='mailto:soporte@example.test'" in page
    assert f"href='{OPERATOR['AUDIT_CONTACT_URL']}'" in page
    # No photo: the founder decides it.
    main = page.split("<main", 1)[1].split("</main>", 1)[0]
    assert "<img" not in main and "fundador" not in page
    assert find_claims(text) == []
    for language, path in ABOUT_PATH.items():
        assert f"hreflang='{language}' href='{BASE}{path}'" in page


def test_about_page_without_details_says_so(tmp_path: Path) -> None:
    with _client(_settings(tmp_path)) as client:
        for locale, path in ABOUT_PATH.items():
            text = _visible(_get(client, path))
            assert ABOUT_COPY[locale]["none"] in text
            assert ABOUT_COPY[locale]["name"] not in text


def test_about_page_is_in_the_sitemap() -> None:
    assert dict(ABOUT_PATH) in list(PUBLIC_PAGES)


# -- 14. /v/{id} without ?lang= follows the browser -----------------------------------


def test_accept_language_picks_the_first_supported_language() -> None:
    assert accept_language_locale("pt-BR,pt;q=0.9,en;q=0.8") == "pt"
    assert accept_language_locale("en-US,en;q=0.9") == "en"
    assert accept_language_locale("es-MX") == "es"
    assert accept_language_locale("en;q=0.2, pt;q=0.8") == "pt"
    assert accept_language_locale("fr-FR, de;q=0.5") is None
    assert accept_language_locale("pt;q=0") is None
    assert accept_language_locale("") is None and accept_language_locale(None) is None


@pytest.mark.parametrize(
    ("header", "locale"),
    [("pt-BR,pt;q=0.9,en;q=0.8", "pt"), ("en-US,en;q=0.9", "en"), ("fr-FR", "es"), ("", "es")],
)
def test_public_page_without_lang_follows_accept_language(
    site: TestClient, header: str, locale: str
) -> None:
    response = site.get("/v/ejemplo", headers={"accept-language": header})
    assert response.status_code == 200
    assert f"<html lang='{locale}'>" in response.text
    assert "accept-language" in response.headers.get("vary", "").lower()
    # The canonical is the one the page has in that language, as with ?lang=.
    explicit = site.get(f"/v/ejemplo?lang={locale}").text
    canonical = re.search(r"<link rel='canonical' href='[^']*'>", explicit)
    assert canonical is not None and canonical.group(0) in response.text


def test_lang_parameter_wins_and_other_pages_keep_their_address(site: TestClient) -> None:
    portuguese = {"accept-language": "pt-BR"}
    assert "<html lang='es'>" in site.get("/v/ejemplo?lang=es", headers=portuguese).text
    assert "<html lang='es'>" in site.get(FAQ_PATH["es"], headers=portuguese).text
    assert "<html lang='en'>" in site.get(FAQ_PATH["en"], headers=portuguese).text


# -- Every page of the sitemap -------------------------------------------------------


def test_no_sitemap_page_shows_internal_paths_labels_or_raw_sizes(site: TestClient) -> None:
    sitemap = ElementTree.fromstring(_get(site, "/sitemap.xml"))
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    paths = [
        str(entry.text).removeprefix(BASE) or "/"
        for entry in sitemap.findall("s:url/s:loc", namespace)
    ]
    assert ABOUT_PATH["es"] in paths and FAQ_PATH["pt"] in paths
    assert article_url("cuantos-intentos-reto-prop-firm", "pt") in paths
    assert len(ARTICLES_BY_KEY) * len(LOCALES) < len(paths)
    for path in paths:
        page = _get(site, path)
        for raw in ("docs/", "quant_trade", "4.76837", "4,76837"):
            assert raw not in page, (path, raw)
        outside = _outside_evidence(page)
        for prefix in LABEL_PREFIXES:
            assert prefix not in outside, (path, prefix)
        scripts = " ".join(re.findall(r"<script\b.*?</script>", page, flags=re.S))
        scripts = html.unescape(scripts.replace("\\u00b7", "·"))
        assert not any(prefix in scripts for prefix in LABEL_PREFIXES), path
        for word in ("repositorio", "repository", "repositório"):
            assert word not in outside, (path, word)
        assert not re.search(r"\bpresets?\b", outside, re.I), path
        assert find_claims(_visible(page)) == [], path
