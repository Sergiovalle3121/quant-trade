"""The institutional review's offer and its sample review.

The prices live in one place (``institutional``'s constants); the review page and
the sample review exist in three languages and pass the profit-claim guard; the
sample runs the production engine on synthetic data and its notes quote figures
read from the result; the sitemap lists both pages; the PDF holds the notes and
the report. Nothing here reaches the network.
"""

from __future__ import annotations

import html
import io
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import institutional, institutional_sample  # noqa: E402
from quant_trade.audit import pdf as pdf_lib  # noqa: E402
from quant_trade.audit.check import SAMPLE_AUDIT_ID  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import institutional_review_page  # noqa: E402
from quant_trade.audit.report import LABELS  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES, page_lastmod  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import CHECK_PATHS, create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: Words these pages never use, not even negated: the review endorses nothing.
ENDORSEMENTS = re.compile(
    r"verificad|certificad|aprobad|aprovad|garantiza|garantid|guarantee|rentable|rentáve"
    r"|profitable|lucrativ|certified|approved",
    re.IGNORECASE,
)


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)), base_url=BASE)


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _main(page: str) -> str:
    """The page's own content, without the navigation and footer every page shares."""
    return _visible(page[page.index("<main") : page.index("</main>")])


def _one(pattern: str, text: str) -> str:
    """The first group of the first match of ``pattern``, which must match."""
    match = re.search(pattern, text)
    assert match is not None, pattern
    return match[1]


@pytest.fixture(scope="module")
def results() -> dict[str, Any]:
    return {locale: institutional_sample.sample_result(locale) for locale in LOCALES}


def test_prices_come_from_their_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(institutional, "STANDARD_PRICE_USD", 3_100)
    monkeypatch.setattr(institutional, "EXTENDED_PRICE_USD", 4_900)
    monkeypatch.setattr(institutional, "DELIVERY_BUSINESS_DAYS", 12)
    for locale in LOCALES:
        page = institutional_review_page(locale=locale, base_url=BASE)
        text = _visible(page)
        assert "USD 3,100" in text and "USD 4,900" in text, locale
        assert "2,500" not in page and "4,000" not in page, locale
        assert " 12 " in _main(page), locale
        data = json.loads(_one(r"<script type='application/ld\+json'>(.*?)</script>", page))
        assert data["@type"] == "Service"
        specs = [offer["priceSpecification"] for offer in data["offers"]]
        assert specs[0]["minPrice"] == 3_100 and specs[1]["maxPrice"] == 4_900
        assert "USD 3,100" in _one(r"<title>([^<]+)</title>", page)


@pytest.mark.parametrize("locale", LOCALES)
def test_review_page_states_scope_deliverables_timeline_and_terms(
    tmp_path: Path, locale: str
) -> None:
    client = _client(tmp_path)
    response = client.get(institutional.REVIEW_PATHS[locale])
    assert response.status_code == 200
    page = response.text
    assert f"<html lang='{locale}'>" in page
    assert find_claims(page) == []
    main = _main(page)
    assert institutional.price_text(institutional.STANDARD_PRICE_USD) in main
    assert institutional.price_text(institutional.EXTENDED_PRICE_USD) in main
    for key in ("standard_items", "extended_items", "deliverables", "timeline", "terms"):
        for line in institutional.offer_lines(locale, key):
            assert line in main, (key, line)
    assert institutional.offer_text(locale, "not_audit") in main
    assert ENDORSEMENTS.search(main) is None
    # The sample review is linked, and so is the form the cards' buttons go to.
    assert f"href='{institutional.SAMPLE_PATHS[locale]}'" in page
    assert f"id='{institutional.FORM_ANCHOR}'" in page
    assert f"href='#{institutional.FORM_ANCHOR}'" in page
    assert f"action='{institutional.REVIEW_PATHS[locale]}'" in page


def test_the_offer_reads_the_same_in_every_language() -> None:
    """Each language says the same things: the same lists, with the same figures."""
    for key in ("standard_items", "extended_items", "deliverables", "timeline", "terms"):
        lengths = {len(institutional.offer_lines(locale, key)) for locale in LOCALES}
        assert len(lengths) == 1, key
        for index in range(lengths.pop()):
            numbers = {
                tuple(re.findall(r"\d[\d,]*", institutional.offer_lines(locale, key)[index]))
                for locale in LOCALES
            }
            assert len(numbers) == 1, (key, index, numbers)
    assert set(institutional.OFFER_COPY["es"]) == set(institutional.OFFER_COPY["en"])
    assert set(institutional.OFFER_COPY["es"]) == set(institutional.OFFER_COPY["pt"])
    sample_keys = set(institutional_sample.COPY["es"])
    assert (
        sample_keys == set(institutional_sample.COPY["en"]) == set(institutional_sample.COPY["pt"])
    )
    # The offer names the sample's real number of variants.
    for locale in LOCALES:
        assert str(institutional_sample.VARIANTS) in institutional.offer_text(locale, "sample_text")


@pytest.mark.parametrize("locale", LOCALES)
def test_sample_pages_answer_and_say_it_is_nobodys_portfolio(tmp_path: Path, locale: str) -> None:
    client = _client(tmp_path)
    words = institutional_sample.COPY[locale]
    notes = client.get(institutional.SAMPLE_PATHS[locale])
    assert notes.status_code == 200
    assert "x-robots-tag" not in notes.headers
    assert "index, follow" in notes.text
    assert find_claims(notes.text) == []
    main = _main(notes.text)
    assert words["banner"] in main
    assert ENDORSEMENTS.search(main) is None
    assert f"href='{institutional.SAMPLE_REPORT_PATHS[locale]}'" in notes.text
    for heading, _ in institutional_sample.notes_sections(
        institutional_sample.sample_result(locale), locale
    ):
        assert heading in main
    report = client.get(institutional.SAMPLE_REPORT_PATHS[locale])
    assert report.status_code == 200
    assert "noindex" in report.headers["x-robots-tag"]
    assert find_claims(report.text) == []
    assert words["banner"] in _visible(report.text)
    assert words["notes_title"] in _visible(report.text)
    # The notes come first, inside the report's own column.
    assert report.text.index("id='r-notes'") < report.text.index("id='r-kpis'")


def test_sitemap_lists_the_review_and_its_sample(tmp_path: Path) -> None:
    assert dict(institutional.REVIEW_PATHS) in PUBLIC_PAGES
    assert dict(institutional.SAMPLE_PATHS) in PUBLIC_PAGES
    sitemap = _client(tmp_path).get("/sitemap.xml").text
    for paths in (institutional.REVIEW_PATHS, institutional.SAMPLE_PATHS):
        for path in paths.values():
            assert f"<loc>{BASE}{path}</loc>" in sitemap, path
            assert page_lastmod(path) == institutional.OFFER_UPDATED
    for path in institutional.SAMPLE_REPORT_PATHS.values():
        assert f"<loc>{BASE}{path}</loc>" not in sitemap


def _at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    for part in path:
        data = data[part]
    return data


def test_the_sample_runs_the_engine_and_the_notes_quote_the_report(
    tmp_path: Path, results: dict[str, Any]
) -> None:
    result = results["es"]
    data = result.model_dump(mode="json")
    # The production engine read the three files as declared.
    assert data["inputs"]["observations"]["value"] == institutional_sample.MONTHS
    assert data["inputs"]["frequency_label"] == "monthly"
    assert set(data["inputs"]["digests"]) == {"equity.csv", "benchmark.csv", "variants.csv"}
    assert data["multiplicity"]["trials_used"] == {
        "value": institutional_sample.VARIANTS,
        "evidence": "MEASURED",
        "note": "columns of the uploaded variants matrix",
    }
    assert data["cscv"]["status"] == "MEASURED"
    assert data["cscv"]["parameter_variants"] == institutional_sample.VARIANTS
    assert data["cscv"]["source_validation"]["status"] == "MEASURED"
    assert data["fund"]["benchmark"]["status"] == "MEASURED"
    # Every figure the notes quote is the result's own value, measured.
    figures = institutional_sample.note_figures(result)
    assert set(figures) == set(institutional_sample.FIGURE_PATHS)
    for key, (path, _) in institutional_sample.FIGURE_PATHS.items():
        item = _at(data, path)
        assert figures[key].value == item["value"], key
        assert figures[key].evidence == item["evidence"] == "MEASURED", key
    # The notes show those figures, and the report beside them the same ones.
    client = _client(tmp_path)
    notes = _main(client.get(institutional.SAMPLE_PATHS["es"]).text)
    for figure in figures.values():
        assert figure.shown in notes, figure.key
    report = client.get(institutional.SAMPLE_REPORT_PATHS["es"]).text
    body = _visible(report[report.index("id='r-kpis'") :])
    assert f"PSR {figures['psr'].shown}" in body
    assert f"DSR {figures['dsr'].shown}" in body
    # The class the notes give is the report's.
    overall = data["verdict"]["overall"]
    assert f"Clase {overall}" in notes


def test_the_sample_is_deterministic_and_synthetic(results: dict[str, Any]) -> None:
    first = institutional_sample.sample_files()
    assert first == institutional_sample.sample_files()
    series = first["series"].decode().splitlines()
    assert series[0] == "date,return" and len(series) == institutional_sample.MONTHS + 1
    variants = first["variants"].decode().splitlines()
    assert len(variants[0].split(",")) == institutional_sample.VARIANTS + 1
    # The series under review is the selected decile's column of the variants file.
    selected = [line.split(",")[institutional_sample.SELECTED] for line in variants[1:]]
    assert selected == [line.split(",")[1] for line in series[1:]]
    again = institutional_sample.sample_result("es")
    assert institutional_sample.note_figures(again) == institutional_sample.note_figures(
        results["es"]
    )
    # The figures do not depend on the language the report is written in.
    assert {
        key: figure.value
        for key, figure in institutional_sample.note_figures(results["en"]).items()
    } == {key: figure.value for key, figure in institutional_sample.note_figures(again).items()}


@pytest.mark.parametrize("locale", LOCALES)
def test_attribution_shows_one_factor_and_leaves_several_to_the_extended_review(
    results: dict[str, Any], locale: str
) -> None:
    words = institutional_sample.COPY[locale]
    sections = dict(institutional_sample.notes_sections(results[locale], locale))
    attribution = _visible(sections[words["s_attribution"]])
    figures = institutional_sample.note_figures(results[locale])
    for key in institutional_sample.ATTRIBUTION_KEYS:
        assert figures[key].shown in attribution
    assert words["multi_factor"] in attribution
    assert re.search(r"\d", words["multi_factor"]) is None
    for text in (attribution, _visible(sections[words["s_not_measured"]])):
        assert find_claims(text) == []


def test_the_sample_pdf_holds_the_notes_and_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    laid_out: list[str] = []

    def fake_pdf(page_html: str, **_: Any) -> bytes:
        laid_out.append(page_html)
        return b"%PDF-1.7 sample"

    monkeypatch.setattr(pdf_lib, "report_pdf", fake_pdf)
    client = _client(tmp_path)
    notes = client.get(institutional.SAMPLE_PATHS["en"]).text
    assert f"href='{institutional.SAMPLE_PDF_PATHS['en']}'" in notes
    for _ in range(2):
        response = client.get(institutional.SAMPLE_PDF_PATHS["en"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            'attachment; filename="rigor-institutional-review-sample.pdf"'
        )
        assert response.content.startswith(b"%PDF")
    # Laid out once and kept; the source is the report with the notes on top.
    assert len(laid_out) == 1
    source = laid_out[0]
    words = institutional_sample.COPY["en"]
    assert words["notes_title"] in _visible(source) and words["banner"] in _visible(source)
    assert source.index("id='r-notes'") < source.index("id='r-kpis'")
    assert find_claims(_visible(source)) == []


def test_the_sample_pdf_answers_503_without_a_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*_: Any, **__: Any) -> bytes:
        raise pdf_lib.PdfUnavailable("no renderer")

    monkeypatch.setattr(pdf_lib, "report_pdf", unavailable)
    response = _client(tmp_path).get(institutional.SAMPLE_PDF_PATHS["pt"])
    assert response.status_code == 503
    assert "noindex" in response.headers["x-robots-tag"]


# ---------------------------------------------------------------------------
# What the offer promises matches what the service does
# ---------------------------------------------------------------------------

#: Each language's check page (``web.CHECK_PATHS``), which the terms name.
CHECK_PAGE = {locale: path for path, locale in CHECK_PATHS.items()}
#: The words each language uses for "the whole audit", "the written quote", "the
#: access code" and "computed apart from the Rigor report".
WHOLE_AUDIT = {"es": "auditoría completa", "en": "whole audit", "pt": "auditoria inteira"}
WRITTEN_QUOTE = {"es": "cotización escrita", "en": "written quote", "pt": "cotação escrita"}
ACCESS_CODE = {"es": "código de acceso", "en": "access code", "pt": "código de acesso"}
APART = {
    "es": "aparte del informe Rigor",
    "en": "apart from the Rigor report",
    "pt": "à parte do relatório Rigor",
}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_terms_say_the_whole_audit_is_deleted_and_the_quote_governs(locale: str) -> None:
    """``audit delete`` removes the whole audit, its issued files included, so
    /comprobar stops recognising the PDF (``test_audit_check``): the terms say so,
    with the check page of the language, instead of promising to delete only the
    files. The series goes up with an access code, so the purge of unpaid audits
    does not come first, and the written quote, not the site's terms for the
    automated report, governs the review."""
    terms = institutional.offer_lines(locale, "terms")
    deletion = [line for line in terms if WHOLE_AUDIT[locale] in line]
    assert len(deletion) == 1
    assert str(institutional.DELETE_DAYS) in deletion[0]
    assert CHECK_PAGE[locale] in deletion[0]
    assert sum(WRITTEN_QUOTE[locale] in line for line in terms) == 1
    assert sum(ACCESS_CODE[locale] in line for line in terms) == 1
    # The PDF a client shares can be checked only while the audit exists.
    pdf_line = institutional.offer_lines(locale, "deliverables")[2]
    assert CHECK_PAGE[locale] in pdf_line
    for line in (*terms, pdf_line):
        assert find_claims(line) == [], line
        assert ENDORSEMENTS.search(line) is None, line


@pytest.mark.parametrize("locale", LOCALES)
def test_what_the_engine_does_not_compute_is_said_to_be_computed_apart(locale: str) -> None:
    """Several factors and capacity are not in the engine: the extended review's
    items, the deliverables and the sample's notes say they are computed apart."""
    extended = institutional.offer_lines(locale, "extended_items")
    assert sum(APART[locale] in line for line in extended) == 2
    notes = institutional.offer_lines(locale, "deliverables")[0]
    assert "Rigor" in notes and re.search(r"apart|aparte|à parte", notes)
    words = institutional_sample.COPY[locale]
    assert APART[locale] in words["multi_factor"]
    assert APART[locale] in words["not_measured"]["costs"]


def _returns(content: bytes) -> pd.Series:
    return pd.read_csv(io.BytesIO(content))["return"]


def test_the_information_ratio_is_the_arithmetic_excess_over_tracking_error(
    results: dict[str, Any],
) -> None:
    """Recomputed from the sample's own files: the mean monthly excess times 12 over
    the tracking error, not the compound difference the row above it shows, which
    the notes now say."""
    files = institutional_sample.sample_files()
    excess = _returns(files["series"]) - _returns(files["benchmark"])
    tracking = float(excess.std(ddof=1)) * math.sqrt(12)
    information = float(excess.mean()) * 12 / tracking
    figures = institutional_sample.note_figures(results["es"])
    assert figures["tracking_error"].value == pytest.approx(tracking, rel=1e-9)
    assert figures["information_ratio"].value == pytest.approx(information, rel=1e-9)
    # The compound difference over the tracking error is another number.
    compound = float(figures["excess"].value or 0.0) / tracking
    assert abs(compound - information) > 0.05
    for locale, word in (("es", "aritmética"), ("en", "arithmetic"), ("pt", "aritmética")):
        meaning = institutional_sample.COPY[locale]["figures"]["information_ratio"][1]
        assert word in meaning, locale


@pytest.mark.parametrize("locale", LOCALES)
def test_the_exposure_says_where_cash_goes_and_the_pbo_threshold_is_a_percentage(
    results: dict[str, Any], locale: str
) -> None:
    words = institutional_sample.COPY[locale]
    data = results[locale].model_dump(mode="json")
    skill = data["fund"]["benchmark"]["skill"]
    # Offline there is no cash rate: cash is zero and stays inside exposure and alpha.
    assert skill["cash_basis"]["source"] is None
    assert skill["attribution"]["cash"]["value"] == 0.0
    sections = dict(institutional_sample.notes_sections(results[locale], locale))
    attribution = _visible(sections[words["s_attribution"]])
    assert words["exposure_no_cash"] in attribution
    assert words["attribution"]["exposure_share"][1] not in attribution
    # With a cash rate, cash is its own line and the notes say so.
    with_cash = {"fund": {"benchmark": {"skill": {"cash_basis": {"source": "DTB3"}}}}}
    assert institutional_sample._cash_counted_apart(with_cash)
    assert not institutional_sample._cash_counted_apart(data)
    # The PBO and its threshold are shown in the same unit.
    pbo_label = words["figures"]["pbo"][0]
    rows = re.findall(r"<tr>.*?</tr>", sections[words["s_results"]], flags=re.S)
    pbo_row = _visible(next(row for row in rows if html.escape(pbo_label) in row))
    threshold = float(data["verdict"]["thresholds"]["pbo_max"])
    assert f"{threshold:.0%}" in pbo_row
    assert re.search(rf"(?<![\d.]){re.escape(str(threshold))}(?![\d%])", pbo_row) is None


@pytest.mark.parametrize("locale", LOCALES)
def test_the_notes_call_the_series_synthetic_and_explain_the_fund_template(
    results: dict[str, Any], locale: str
) -> None:
    words = institutional_sample.COPY[locale]
    sections = dict(institutional_sample.notes_sections(results[locale], locale))
    reviewed = _visible(sections[words["s_reviewed"]])
    assert re.search(r"sintétic|synthetic", reviewed)
    source = _visible(sections[words["s_data"]])
    assert f" {institutional_sample.MARKET_T_DOF} " in source
    how = _visible(sections[words["s_how"]])
    assert words["how"]["template"] in how


def _identifier_checks(page: str, locale: str) -> None:
    """The page shows the sample's word as its identifier, never the stored id."""
    name = institutional_sample.REPORT_NAMES[locale]
    head = page[: page.index("</head>")]
    assert f" · {SAMPLE_AUDIT_ID}" not in head
    assert "<title>" in head and f" · {name}</title>" in head
    assert head.count(f" · {name}'") >= 4
    text = _visible(page)
    label = LABELS[locale]["audit_id"]
    assert f"{label} {SAMPLE_AUDIT_ID}" not in text
    assert f"{label} {name}" in text


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_and_its_pdf_show_the_pages_word_as_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    laid_out: list[str] = []

    def fake_pdf(page_html: str, **_: Any) -> bytes:
        laid_out.append(page_html)
        return b"%PDF-1.7 sample"

    monkeypatch.setattr(pdf_lib, "report_pdf", fake_pdf)
    client = _client(tmp_path)
    report = client.get(institutional.SAMPLE_REPORT_PATHS[locale])
    assert report.status_code == 200
    _identifier_checks(report.text, locale)
    assert client.get(institutional.SAMPLE_PDF_PATHS[locale]).status_code == 200
    assert len(laid_out) == 1
    _identifier_checks(laid_out[0], locale)
    # The stored id stays the one /comprobar reads.
    assert institutional_sample.AUDIT_ID == SAMPLE_AUDIT_ID
