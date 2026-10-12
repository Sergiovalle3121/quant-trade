"""The institutional checklist and its downloadable, fictional return template."""

from __future__ import annotations

import calendar
import csv
import html
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import institutional  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import spanish  # noqa: E402
from quant_trade.audit.importers import import_return_series  # noqa: E402
from quant_trade.audit.schema import (  # noqa: E402
    MAX_UPLOAD_BYTES,
    MAX_VARIANTS,
    AuditInputs,
    DeclaredMetadata,
    ParseError,
    build_inputs,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
SEND_TITLES = {"es": "Qué mandar", "en": "What to send", "pt": "O que enviar"}


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)), base_url=BASE)


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def _section(page: str, title: str) -> str:
    sections = re.findall(r"<section\b[^>]*>.*?</section>", page, flags=re.S)
    matching = [section for section in sections if f"<h2>{title}</h2>" in section]
    assert len(matching) == 1, title
    return matching[0]


@pytest.mark.parametrize("locale", SEND_TITLES)
def test_what_to_send_sits_after_deliverables_and_before_the_form(
    tmp_path: Path, locale: str
) -> None:
    response = _client(tmp_path).get(institutional.REVIEW_PATHS[locale])
    assert response.status_code == 200
    page = response.text
    send = _section(page, SEND_TITLES[locale])
    delivered = _section(page, institutional.offer_text(locale, "deliverables_title"))
    assert page.index(delivered) < page.index(send) < page.index("<form")
    assert "<section" not in page[page.index(delivered) + len(delivered) : page.index(send)]
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", send, flags=re.S)
    assert len(items) == 5
    for item, expected in zip(items, institutional.offer_lines(locale, "send_items"), strict=True):
        assert expected in _visible(item)
    assert f"href='{institutional.TEMPLATE_PATH}'" in send
    text = _visible(send)
    for key in ("template_link", "template_note", "nda", "publication_note"):
        assert institutional.offer_text(locale, key) in text
    assert not re.search(r"(?:DECLARED|Declared|Declarado)\s*·", text)
    terms = _section(page, institutional.offer_text(locale, "terms_title"))
    assert institutional.offer_text(locale, "scope_limit") in _visible(terms)
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize(
    ("locale", "required"),
    [
        (
            "es",
            (
                ("mensual", "diari", "CSV", "NAV", "brut", "net", "cost"),
                ("referencia", "serie", "nombre", "estándar"),
                ("variantes", "reglas", "columna", "CSV", "número", "declarado"),
                ("fecha", "reglas", "fijas", "anterior", "elegir"),
                ("rotación", "rebalanceo", "puntos básicos"),
            ),
        ),
        (
            "en",
            (
                ("monthly", "daily", "CSV", "NAV", "gross", "net", "cost"),
                ("benchmark", "series", "name", "standard"),
                ("variants", "rules", "column", "CSV", "count", "declared"),
                ("date", "rules", "fixed", "earlier", "choose"),
                ("turnover", "rebalance", "basis points"),
            ),
        ),
        (
            "pt",
            (
                ("mensais", "diários", "CSV", "NAV", "brut", "líquid", "cust"),
                ("referência", "série", "nome", "padrão"),
                ("variantes", "regras", "coluna", "CSV", "número", "declarado"),
                ("data", "regras", "fixas", "anterior", "escolhê"),
                ("giro", "rebalanceamento", "pontos-base"),
            ),
        ),
    ],
)
def test_the_five_items_keep_the_data_request_in_each_language(
    locale: str, required: tuple[tuple[str, ...], ...]
) -> None:
    for item, terms in zip(institutional.offer_lines(locale, "send_items"), required, strict=True):
        for term in terms:
            assert term.casefold() in item.casefold(), (locale, term, item)


def test_nda_accepts_the_clients_document_before_any_data_is_sent() -> None:
    assert institutional.offer_text("es", "nda") == (
        "Firmamos un NDA mutuo antes de que nos mandes nada; puedes mandar el tuyo."
    )
    for locale in SEND_TITLES:
        assert "NDA" in institutional.offer_text(locale, "nda")
        assert "GIPS" in institutional.offer_text(locale, "scope_limit")


def test_new_english_notices_have_spanish_i18n_rules() -> None:
    for key in ("template_note", "nda", "publication_note", "scope_limit"):
        assert spanish(institutional.offer_text("en", key)) == institutional.offer_text("es", key)
    assert spanish(institutional.COPY["en"]["next"]) == institutional.COPY["es"]["next"]


def test_template_download_is_an_attachment_outside_the_sitemap(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get(institutional.TEMPLATE_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "text/csv"
    assert response.headers["content-disposition"] == (
        'attachment; filename="institutional-fictional-template.csv"'
    )
    # The literal the site's other attachments carry.
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.content == institutional.TEMPLATE_CSV
    assert b"\r" not in response.content
    assert institutional.TEMPLATE_PATH not in client.get("/sitemap.xml").text
    robots = RobotFileParser()
    robots.parse(client.get("/robots.txt").text.splitlines())
    assert robots.can_fetch("*", BASE + institutional.TEMPLATE_PATH)


def test_downloaded_template_preserves_all_series_in_the_sites_importer(tmp_path: Path) -> None:
    data = _client(tmp_path).get(institutional.TEMPLATE_PATH).content
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    # The importer-supported fallback uses its real aliases and a separate variants file.
    assert rows[0] == ["date", "gross_return", "net_return", "benchmark"]
    assert 3 <= len(rows) - 1 <= 4
    assert [row[0] for row in rows[1:]] == [
        "2000-01-31",
        "2000-02-29",
        "2000-03-31",
        "2000-04-30",
    ]
    series = import_return_series(data, frequency="monthly", unit="fraction")
    assert series.source == "returns"
    assert series.observations == series.raw_rows == 4
    assert series.unparseable_rows == series.duplicate_timestamps == 0
    assert series.frame["gross_ret"].tolist() == pytest.approx([0.010, -0.020, 0.000, 0.020])
    assert series.frame["net_ret"].tolist() == pytest.approx([0.009, -0.021, -0.001, 0.019])
    assert series.returns.tolist() == series.frame["net_ret"].tolist()
    assert series.benchmark is not None
    assert series.benchmark["ret"].tolist() == pytest.approx([0.005, -0.010, 0.000, 0.010])
    inputs = build_inputs(
        data,
        DeclaredMetadata(trials=7, return_frequency="monthly", return_unit="fraction"),
        now=datetime(2001, 1, 1, tzinfo=UTC),
    )
    assert inputs.frequency_label == "monthly"
    assert inputs.periods_per_year == 12
    assert inputs.equity.frame.equals(series.frame)
    assert inputs.equity.benchmark is not None
    assert inputs.equity.benchmark.equals(series.benchmark)
    assert inputs.variants is None and inputs.report_variants is None
    assert inputs.declared.trials == 7


def _month_ends(count: int) -> list[str]:
    days = []
    for index in range(count):
        year, month = 2000 + index // 12, index % 12 + 1
        days.append(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
    return days


def _fictional_files(rows: int, variants: int = 2) -> tuple[bytes, bytes]:
    """A portfolio with the template's headers and its variants on the same dates."""
    names = ",".join(f"variant_{number}" for number in range(1, variants + 1))
    portfolio = ["date,gross_return,net_return,benchmark"]
    matrix = [f"date,{names}"]
    for index, day in enumerate(_month_ends(rows)):
        gross = 0.005 * (index % 5 - 2)
        portfolio.append(f"{day},{gross:.4f},{gross - 0.001:.4f},{gross / 2:.4f}")
        cells = ",".join(f"{gross + 0.002 * number:.4f}" for number in range(1, variants + 1))
        matrix.append(f"{day},{cells}")
    return ("\n".join(portfolio) + "\n").encode(), ("\n".join(matrix) + "\n").encode()


def _inputs(portfolio: bytes, variants: bytes) -> AuditInputs:
    return build_inputs(
        portfolio,
        DeclaredMetadata(trials=2, return_frequency="monthly", return_unit="fraction"),
        variants_bytes=variants,
        now=datetime(2003, 1, 1, tzinfo=UTC),
    )


def test_the_variants_csv_the_page_asks_for_reads_beside_the_template() -> None:
    portfolio, variants = _fictional_files(20)
    assert variants.splitlines()[0] == b"date,variant_1,variant_2"
    inputs = _inputs(portfolio, variants)
    assert inputs.variants is not None
    assert inputs.variants.shape == (20, 2)
    assert inputs.variant_validation is not None
    assert inputs.variant_validation["status"] == "MEASURED"
    assert inputs.equity.frame["net_ret"].size == 20


def test_the_variants_limits_on_the_page_are_the_importers() -> None:
    assert MAX_VARIANTS == 500
    assert MAX_UPLOAD_BYTES == 5_000_000
    for locale in SEND_TITLES:
        item = institutional.offer_lines(locale, "send_items")[2]
        for limit in ("2 ", "16 ", "500 ", "5 MB"):
            assert limit in item, (locale, limit)
    with pytest.raises(ParseError) as one_variant:
        _inputs(*_fictional_files(20, variants=1))
    assert one_variant.value.code == "too_few_variants"
    with pytest.raises(ParseError) as short:
        _inputs(*_fictional_files(15))
    assert short.value.code == "too_few_variant_rows"
