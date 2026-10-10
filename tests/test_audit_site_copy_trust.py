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
from quant_trade.audit.report import KEY_LABELS, LABELS  # noqa: E402
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.sample_publication import (  # noqa: E402
    SAMPLE_SEAL_NOTE,
    SAMPLE_SHOWN_IDS,
    sample_publication,
)
from quant_trade.audit.seo import PUBLIC_PAGES, SIGNAL_SAMPLE_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import TOOLS_PATH  # noqa: E402
from quant_trade.audit.upload_limits import (  # noqa: E402
    FIELD_LIMITS,
    UploadLimits,
    field_limit,
    guide_limit_text,
    megabytes,
    upload_limit_text,
    upload_limits,
)
from quant_trade.audit.web import REPORT_FIELDS, accept_language_locale, create_app  # noqa: E402
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


# -- 2. One limits sentence from the settings, field by field, with what to do -----

#: What to do with a larger file, the only advice the sentence gives.
SHORTEN = {"es": "recorta el periodo", "en": "shorten the period", "pt": "encurte o período"}
#: Advice the sentence no longer gives: a CSV to someone who may already upload one,
#: and an encoding that is MetaTrader 5's, not MetaTrader 4's.
NOT_SAID = ("exportación CSV", "CSV export", "exportação CSV", "UTF-16")


def test_the_limits_come_from_the_settings_and_the_readers() -> None:
    # Fields that may carry a platform report take twice the setting, and the readers
    # cap what they read: 10 MB of a report, 5 MB of a curve or any other CSV.
    assert upload_limits(5_000_000) == UploadLimits(10_000_000, 5_000_000, 5_000_000)
    assert upload_limits(2_000_000) == UploadLimits(4_000_000, 4_000_000, 2_000_000)
    # A larger setting never promises what schema._read_csv and the importers refuse.
    assert upload_limits(20_000_000) == UploadLimits(10_000_000, 5_000_000, 5_000_000)
    # The fields that take the wider limit are web.REPORT_FIELDS, and no other.
    assert {name for name, kind in FIELD_LIMITS.items() if kind != "other"} == REPORT_FIELDS
    assert set(FIELD_LIMITS) == {*REPORT_FIELDS, "trades", "benchmark", "variants"}
    assert megabytes(7 * 1024 * 1024, "en") == "7.3 MB"
    assert megabytes(7 * 1024 * 1024, "es") == megabytes(7 * 1024 * 1024, "pt") == "7,3 MB"
    assert megabytes(10_000_000, "es") == "10 MB"
    for locale in LOCALES:
        for size in (5_000_000, 2_000_000, 20_000_000):
            text = upload_limit_text(size, locale)
            assert SHORTEN[locale] in text
            assert not any(words in text for words in NOT_SAID), (locale, size)
            assert "4.76837" not in text and "4,76837" not in text
            assert find_claims(text) == []
        # The default: the report field and its kin up to 10 MB, every other file 5 MB,
        # said once (the curve and the trade list share the same limit).
        default = upload_limit_text(5_000_000, locale)
        assert default.count("10 MB") == 1 and default.count("5 MB") == 1
        # Two smaller limits are said apart.
        small = upload_limit_text(2_000_000, locale)
        assert small.count("4 MB") == 2 and small.count("2 MB") == 1


@pytest.mark.parametrize("locale", LOCALES)
def test_faq_says_the_sentence_and_every_guide_its_fields_limit(
    site: TestClient, locale: str
) -> None:
    faq = _get(site, FAQ_PATH[locale])
    assert html.escape(upload_limit_text(5_000_000, locale), quote=True) in faq
    assert "4.76837" not in faq and "4,76837" not in faq
    for guide in GUIDES:
        page = _get(site, guide_url(guide.slug, locale))
        line = guide_limit_text(guide.field, 5_000_000, locale)
        assert html.escape(line, quote=True) in page, guide.slug
        assert megabytes(field_limit(guide.field), locale) in line
        # Every guide's file goes in a field that takes a platform report: 10 MB.
        assert "10 MB" in line and SHORTEN[locale] in line
        shown = _visible(page)
        assert not any(words in shown for words in NOT_SAID[:3]), guide.slug
        assert upload_limit_text(5_000_000, locale) not in shown, guide.slug
    # The MetaTrader 4 guide never says its HTML is UTF-16: MT4 writes the Windows
    # code page (importers.py), and the limit does not depend on the encoding.
    assert "UTF-16" not in _visible(_get(site, guide_url("mt4", locale)))


@pytest.mark.parametrize("locale", LOCALES)
def test_upload_form_prints_the_limits_of_its_own_settings(
    free_site: TestClient, locale: str
) -> None:
    page = _get(free_site, AUDIT_PATHS[locale])
    # AUDIT_MAX_UPLOAD_BYTES=2000000: 4 MB a platform report or a curve, 2 MB the rest.
    sentence = html.escape(upload_limit_text(2_000_000, locale), quote=True)
    # In the main field's own help.
    report_field = page.split("id='f-report'", 1)[1].split("class='field'", 1)[0]
    assert sentence in report_field
    shown = _visible(page)
    assert "2 MB" in shown and "4 MB" in shown
    assert find_claims(shown) == []


def _trades_csv(rows: int, pad: int) -> bytes:
    """A broker's generic trade list (``universal_trades_csv``), with a wide note on
    each row so that a few trades make a file of several MB."""
    lines = ["entry_time,exit_time,symbol,side,quantity,entry_price,exit_price,pnl,note"]
    for day in range(rows):
        date = f"{2022 + day // 336}-{1 + day // 28 % 12:02d}-{1 + day % 28:02d}"
        pnl = "25.0" if day % 3 else "-40.0"
        lines.append(f"{date} 09:00,{date} 12:00,EURUSD,buy,1,1.1000,1.1010,{pnl},{'x' * pad}")
    return ("\n".join(lines) + "\n").encode()


def _refusal(page: str) -> str:
    return _visible(page.split("<p role='alert'>", 1)[1].split("</p>", 1)[0])


@pytest.mark.parametrize("locale", LOCALES)
def test_a_generic_csv_over_5_mb_goes_in_the_report_field_as_the_sentence_says(
    tmp_path: Path, locale: str
) -> None:
    """The sentence gives the report field 10 MB, whatever the export's format, and
    the closed-trades field 5 MB: the same 6 MB broker CSV is taken by the first and
    refused by the second."""
    data = _trades_csv(300, 20_000)
    limits = upload_limits(5_000_000)
    assert limits.other < len(data) < limits.report
    sentence = upload_limit_text(5_000_000, locale)
    assert megabytes(limits.report, locale) in sentence
    assert megabytes(limits.other, locale) in sentence
    # The lifespan is not entered: the upload is taken and queued, never audited here.
    client = _client(_settings(tmp_path, AUDIT_FREE_MODE="true"))
    try:
        form = {"consent": "on", "locale": locale}
        sent = {"report": ("operaciones.csv", data, "text/csv")}
        taken = client.post("/audits", files=sent, data=form)
        assert taken.status_code == 303, taken.text[:2000]
        assert taken.headers["location"].startswith("/audits/")
        sent = {"trades": ("operaciones.csv", data, "text/csv")}
        refused = client.post("/audits", files=sent, data=form)
        assert refused.status_code == 413
        assert megabytes(limits.other, locale) in _refusal(refused.text)
    finally:
        client.close()


def test_a_larger_setting_still_says_and_applies_the_readers_limits(tmp_path: Path) -> None:
    """With AUDIT_MAX_UPLOAD_BYTES at 20 MB the sentence says 5 MB for a curve, the
    curve reader's own limit, and 10 MB for a report, the importers'."""
    settings = _settings(tmp_path, AUDIT_FREE_MODE="true", AUDIT_MAX_UPLOAD_BYTES="20000000")
    sentence = upload_limit_text(settings.max_upload_bytes, "es")
    assert "20 MB" not in sentence and "40 MB" not in sentence
    assert "hasta 10 MB" in sentence and "hasta 5 MB" in sentence
    line = b"2024-01-02 00:00:00,10000.123456\n"
    curve = b"timestamp,equity\n" + line * (6_000_000 // len(line))
    assert 5_000_000 < len(curve) < settings.max_upload_bytes
    client = _client(settings)
    try:
        assert html.escape(sentence, quote=True) in _get(client, AUDIT_PATHS["es"])
        refused = client.post(
            "/audits",
            files={"equity": ("curva.csv", curve, "text/csv")},
            data={"consent": "on", "locale": "es"},
        )
        assert refused.status_code == 400
        assert "5 MB" in _refusal(refused.text)
    finally:
        client.close()


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
    shown = SAMPLE_SHOWN_IDS[kind][locale]
    report_paths = {
        "backtest": {"es": "/ejemplo", "en": "/sample", "pt": "/pt/exemplo"},
        "signal": SIGNAL_SAMPLE_PATHS,
    }
    public_id = {"backtest": "ejemplo", "signal": "ejemplo-senal"}[kind]
    report = _get(site, report_paths[kind][locale])
    public = _get(site, f"/v/{public_id}?lang={locale}")
    assert f"<span>{html.escape(label)} {html.escape(shown)}</span>" in report
    # A sample's page says the report's own word, since it shows the report's value.
    assert f"<b>{html.escape(label)}</b><span>{html.escape(shown)}</span>" in public
    assert html.escape(_UI[locale]["v_id"]) not in public
    if locale != "en":
        assert f"{label} {SAMPLE_AUDIT_ID}" not in _visible(report)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_publication_never_calls_its_page_code_the_reports_identifier(
    sample_view: tuple[dict[str, object], str], locale: str
) -> None:
    """A publication's page shows its own 12-character code, which is not the
    report's identifier: it says so in its own words, never the report's."""
    view, digest = sample_view
    page = verification_page(
        view,
        public_id="AbCdEfGhIjKl",
        published_at="2026-10-09T00:00:00+00:00",
        result_sha256=digest,
        base_url=BASE,
        locale=locale,
    )
    words = {
        "es": "Código de la página pública",
        "en": "Public page code",
        "pt": "Código da página pública",
    }[locale]
    assert _UI[locale]["v_id"] == words != LABELS[locale]["audit_id"]
    assert f"<b>{html.escape(words)}</b><span>AbCdEfGhIjKl</span>" in page
    assert f"<b>{html.escape(LABELS[locale]['audit_id'])}</b>" not in page
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize(("locale", "path"), [("es", "/ejemplo"), ("pt", "/pt/exemplo")])
def test_the_sealed_sample_id_is_explained_where_it_shows(
    site: TestClient, locale: str, path: str
) -> None:
    """The holdout seal keeps the stored id, "sample", since its SHA-256 is computed
    with it; beside it the report says the rest of the page shows another word."""
    text = _visible(_get(site, path))
    shown = SAMPLE_SHOWN_IDS["backtest"][locale]
    note = SAMPLE_SEAL_NOTE[locale].format(shown=shown)
    seal = KEY_LABELS[locale]["seal_id"]
    assert f"{seal} {SAMPLE_AUDIT_ID} ({note})" in text
    # Every visible "sample" is that one: the stored id beside its note.
    assert len(re.findall(rf"\b{SAMPLE_AUDIT_ID}\b", text)) == 1
    assert find_claims(note) == []
    # The English report shows the stored id itself: no note there.
    english = _visible(_get(site, "/sample"))
    assert f"{KEY_LABELS['en']['seal_id']} {SAMPLE_AUDIT_ID} Selection" in english
    assert "(the identifier this sample" not in english


@pytest.mark.parametrize(("locale", "path"), [("es", "/ejemplo.pdf"), ("pt", "/pt/exemplo.pdf")])
def test_the_sample_pdf_explains_the_sealed_id_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str, path: str
) -> None:
    """The PDF is printed from the same HTML: the same identifier and the same note."""
    from quant_trade.audit import pdf as pdf_lib

    printed: list[str] = []

    def fake_pdf(page: str, **_: object) -> bytes:
        printed.append(page)
        return b"%PDF-1.7 test"

    monkeypatch.setattr(pdf_lib, "report_pdf", fake_pdf)
    client = _client(_settings(tmp_path))
    try:
        assert client.get(path).status_code == 200
    finally:
        client.close()
    text = _visible(printed[0])
    shown = SAMPLE_SHOWN_IDS["backtest"][locale]
    assert f"{LABELS[locale]['audit_id']} {shown}" in text
    note = SAMPLE_SEAL_NOTE[locale].format(shown=shown)
    assert f"{KEY_LABELS[locale]['seal_id']} {SAMPLE_AUDIT_ID} ({note})" in text


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
    # The calculator link carries the same 0.17, never the float's 17 digits.
    assert "17307" not in page and "years=0.17&" in page
    link = re.search(r"href='([^']*years=0\.17[^']*)'", page)
    assert link is not None
    calculator = _get(site, html.unescape(link.group(1)))
    assert "17307" not in calculator and "value='0.17'" in calculator


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


# -- 12. Rule sets and programs, counted from the presets ----------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_prop_page_counts_rule_sets_and_programs_from_the_presets(
    site: TestClient, locale: str
) -> None:
    firms = [rules for rules in PRESETS.values() if rules.firm != "Generic"]
    rule_sets, programs = len(firms), len({(r.firm, r.program) for r in firms})
    # A rule set is not always one phase: The5ers' Bootcamp preset holds for each of
    # its three steps, so "phases" would undercount.
    assert any(not rules.phase[:1].isdigit() for rules in firms)
    generic = [rules for rules in PRESETS.values() if rules.firm == "Generic"]
    assert [rules.phase for rules in generic] == ["1"]
    text = _visible(_get(site, audience_url("retos-prop-firm", locale)))
    expected = {
        "es": f"{rule_sets} juegos de reglas de {programs} programas",
        "en": f"{rule_sets} rule sets from {programs} programs",
        "pt": f"{rule_sets} conjuntos de regras de {programs} programas",
    }[locale]
    assert expected in text
    generic_words = {
        "es": "más la fase 1 de un reto genérico de dos fases",
        "en": "plus phase 1 of a generic two-phase challenge",
        "pt": "mais a fase 1 de um desafio genérico de duas fases",
    }[locale]
    assert generic_words in text
    assert not re.search(r"\d+ (fases|phases) (de|of) \d+", text)
    # The key figures' label counts the same unit.
    unit = {
        "es": "juegos de reglas de prop firms",
        "en": "prop-firm rule sets",
        "pt": "conjuntos de regras de prop firms",
    }[locale]
    labels = [label for value, label in _UI[locale]["stats"] if value == "{presets}"]
    assert len(labels) == 1 and labels[0].startswith(unit)
    # Every firm rule set the form offers cites its official page and the day it was read.
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
    [("pt-BR,pt;q=0.9,en;q=0.8", "pt"), ("en-US,en;q=0.9", "en"), ("de;q=1, en;q=0.5", "en")],
)
def test_public_page_without_lang_sends_the_browser_to_its_language(
    site: TestClient, header: str, locale: str
) -> None:
    """/v/{id} keeps one content and one canonical, the Spanish page's; a browser that
    asks for English or Portuguese is sent to that page's own address, its ?ref= kept."""
    response = site.get("/v/ejemplo?ref=v-ejemplo", headers={"accept-language": header})
    assert response.status_code == 302
    assert response.headers["location"] == f"/v/ejemplo?ref=v-ejemplo&lang={locale}"
    assert "accept-language" in response.headers.get("vary", "").lower()
    page = site.get(response.headers["location"], headers={"accept-language": header}).text
    assert f"<html lang='{locale}'>" in page


@pytest.mark.parametrize("header", ["es-MX,es;q=0.9", "fr-FR", "*", "en;q=0", ""])
def test_public_page_without_lang_is_the_spanish_page_with_its_own_canonical(
    site: TestClient, header: str
) -> None:
    response = site.get("/v/ejemplo", headers={"accept-language": header})
    assert response.status_code == 200
    assert "<html lang='es'>" in response.text
    assert f"<link rel='canonical' href='{BASE}/v/ejemplo'>" in response.text
    assert "accept-language" in response.headers.get("vary", "").lower()


def test_lang_parameter_wins_and_other_pages_keep_their_address(site: TestClient) -> None:
    portuguese = {"accept-language": "pt-BR"}
    assert "<html lang='es'>" in site.get("/v/ejemplo?lang=es", headers=portuguese).text
    assert "<html lang='es'>" in site.get(FAQ_PATH["es"], headers=portuguese).text
    assert "<html lang='en'>" in site.get(FAQ_PATH["en"], headers=portuguese).text


@pytest.mark.parametrize("header", ["en-US,en;q=0.9", "pt-BR,pt;q=0.9"])
def test_the_language_switch_reaches_spanish_from_any_browser(
    site: TestClient, header: str
) -> None:
    """The switch's "Español" carries ?lang=es, so the choice beats Accept-Language;
    the Spanish page's canonical stays /v/{id}."""
    browser = {"accept-language": header}
    for public_id in ("ejemplo", "ejemplo-senal"):
        page = site.get(f"/v/{public_id}?lang=en", headers=browser).text
        nav = page.split("</header>", 1)[0]
        links = re.findall(r"<a [^>]*href='([^']*)' hreflang='es'", nav)
        assert links and set(links) == {f"/v/{public_id}?lang=es"}, links
        assert f"/v/{public_id}'" not in nav
        followed = site.get(links[0], headers=browser)
        assert followed.status_code == 200
        assert "<html lang='es'>" in followed.text
        assert f"<link rel='canonical' href='{BASE}/v/{public_id}'>" in followed.text


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
