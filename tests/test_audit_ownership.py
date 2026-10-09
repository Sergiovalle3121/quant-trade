"""Whose strategy it is: the optional declaration on the upload form and the
voice it gives the report.

The client's own EA reads developer actions, a buyer reads the questions for
the seller, a provider reads what clients will ask and what to provide, and
no answer reads a neutral wording, never the buyer's by default. The
figures, the class, the tags and the order of the sections are the same in
every voice. Offline and deterministic.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in, synthetic_mt5_report
from pydantic import ValidationError

from quant_trade.audit import ownership, plan, report
from quant_trade.audit.analytics import _QUESTIONS
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.live import MIN_LIVE_TRADES
from quant_trade.audit.mapping import CARRIED_FIELDS, Table, mapping_page
from quant_trade.audit.pages import upload_page, verification_card_svg, verification_page
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.report import render_html, to_json
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs, declared

LOCALES = ("es", "en", "pt")
FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
#: Words that send the reader to a seller or take them for a buyer.
SELLER: dict[str, tuple[str, ...]] = {
    "es": ("vendedor", "proveedor", "si compraste", "vas a comprar"),
    "en": ("seller", "vendor", "provider", "you bought", "about to buy"),
    "pt": ("vendedor", "fornecedor", "provedor", "você comprou", "está para comprar"),
}
#: The words the brief keeps out of every text.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable")
ROLE_ROW = re.compile(
    r"<tr><td>(?:De quién es la estrategia|Whose strategy it is|De quem é a estratégia)</td>"
    r".*?</tr>"
)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _with_role(result: AuditResult, role: str | None) -> AuditResult:
    data = dict(result.declared)
    data.pop("ownership", None)
    if role:
        data["ownership"] = declared(role)
    return result.model_copy(update={"declared": data})


@lru_cache(maxsize=3)
def _sample(locale: str) -> AuditResult:
    return sample_result(locale, bootstrap_samples=60)


@lru_cache(maxsize=16)
def _sample_page(locale: str, role: str | None) -> str:
    return render_html(_with_role(_sample(locale), role), watermark=False, locale=locale)


def _labels(locale: str, role: str) -> dict[str, str]:
    return ownership.labels_for(report.LABELS[locale], locale, role)


def _seller_words(text: str, locale: str) -> list[str]:
    lowered = text.lower()
    return [word for word in SELLER[locale] if word in lowered]


# The upload form ------------------------------------------------------------


def _ownership_select(page: str) -> list[tuple[str, bool, str]]:
    block = re.search(r"<select name='ownership'[^>]*>(.*?)</select>", page, re.S)
    assert block, "the form has no ownership field"
    return [
        (value, bool(selected), html.unescape(text))
        for value, selected, text in re.findall(
            r"<option value='([^']*)'( selected)?>([^<]*)</option>", block.group(1)
        )
    ]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_form_offers_four_answers_and_says_nothing_by_default(locale: str) -> None:
    page = upload_page(locale=locale)
    words = ownership.FORM[locale]
    options = _ownership_select(page)
    assert [value for value, _, _ in options] == ["own", "buyer", "provider", ""]
    assert [text for _, _, text in options] == list(words["choices"].values())
    assert [value for value, selected, _ in options if selected] == [""]
    shown = html.unescape(page)
    assert words["label"] in shown and words["help"] in shown
    # Next to the other optional fields: a labelled control with its help line.
    assert "<label for='f-ownership'>" in page and "id='f-ownership-help'" in page
    assert find_claims(_text(page)) == []


def test_the_spanish_answers_read_as_the_brief_asks() -> None:
    assert list(ownership.FORM["es"]["choices"].values()) == [
        "Es mía (la desarrollé o la opero yo)",
        "La compré o la voy a comprar / copiar",
        "Soy el proveedor y la muestro a otros",
        "Prefiero no decirlo",
    ]
    assert ownership.FORM["es"]["label"].startswith("¿De quién es esta estrategia?")


@pytest.mark.parametrize("locale", LOCALES)
def test_a_refused_upload_keeps_the_answer(locale: str) -> None:
    for role in ownership.ROLES:
        options = _ownership_select(upload_page(locale=locale, carried={"ownership": role}))
        assert [value for value, selected, _ in options if selected] == [role]
    # Anything else falls back to "I'd rather not say", never to the first answer.
    options = _ownership_select(upload_page(locale=locale, carried={"ownership": "<b>x"}))
    assert [value for value, selected, _ in options if selected] == [""]
    assert "ownership" in CARRIED_FIELDS
    table = Table(header=["Day", "Value"], samples=[["2025-01-01", "100"]])
    mapped = mapping_page(table, "CSV", locale=locale, carried={"ownership": "provider"})
    assert "<input type='hidden' name='ownership' value='provider'>" in mapped


# The declaration -------------------------------------------------------------


def test_no_answer_declares_nothing_and_an_unknown_one_is_refused() -> None:
    assert DeclaredMetadata(ownership="").ownership is None
    assert DeclaredMetadata(ownership="  ").ownership is None
    assert DeclaredMetadata().ownership is None
    assert DeclaredMetadata(ownership=" own ").ownership == "own"
    with pytest.raises(ValidationError):
        DeclaredMetadata(ownership="owner")


@lru_cache(maxsize=4)
def _backtest(role: str | None) -> AuditResult:
    """An MT5 tester report with trades, no live account and no holdout."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale="es", trials=40, ownership=role),
        report_bytes=synthetic_mt5_report(260),
        report_filename="tester.html",
    )
    return run_audit(inputs, bootstrap_samples=100, audit_id="ownership", now=NOW)


def test_the_result_stores_the_answer_as_a_declaration() -> None:
    for role in ownership.ROLES:
        stored = json.loads(to_json(_backtest(role)))["declared"]
        assert stored["ownership"] == {"value": role, "evidence": "DECLARED", "note": ""}
        assert ownership.role_of({"declared": stored}) == role
    assert "ownership" not in json.loads(to_json(_backtest(None)))["declared"]
    assert ownership.role_of(_backtest(None).model_dump(mode="json")) == ownership.NEUTRAL


def test_the_answer_changes_no_figure_class_or_tag_of_the_result() -> None:
    baseline = _backtest(None).model_dump(mode="json")
    for role in ownership.ROLES:
        data = _backtest(role).model_dump(mode="json")
        data["declared"].pop("ownership")
        assert data == baseline, role


# Over HTTP ---------------------------------------------------------------------


def _client(tmp_path: Path):  # type: ignore[no-untyped-def]
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _post(client, **data):  # type: ignore[no-untyped-def]
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    payload = {"trials": "3", "cost_bps": "5", **data}
    return client.post("/audits", files=files, data=payload, follow_redirects=False)


def test_over_http_the_answer_reaches_the_record_and_the_report(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = _post(client, consent="on", ownership="provider")
    assert response.status_code == 303
    location = response.headers["location"]
    path, _, query = location.partition("?")
    stored = client.get(f"{path}.json?{query}").json()
    assert stored["declared"]["ownership"] == {
        "value": "provider",
        "evidence": "DECLARED",
        "note": "",
    }
    page = html.unescape(client.get(location).text)
    labels = _labels("es", ownership.PROVIDER)
    assert labels["questions"] in page and labels["next_intro"] in page
    assert "Te van a preguntar: «" in page
    assert report.LABELS["es"]["next_intro"] not in page
    # No answer: a neutral report, without the buyer's wording.
    neutral = _post(client, consent="on")
    assert neutral.status_code == 303
    shown = html.unescape(client.get(neutral.headers["location"]).text)
    assert _labels("es", ownership.NEUTRAL)["next_intro"] in shown
    assert _seller_words(_text(shown), "es") == []


def test_over_http_a_refusal_keeps_the_answer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    refused = _post(client, ownership="own")  # no consent
    assert refused.status_code == 400
    options = _ownership_select(refused.text)
    assert [value for value, selected, _ in options if selected] == ["own"]
    unknown = _post(client, consent="on", ownership="boss")
    assert unknown.status_code == 400
    options = _ownership_select(unknown.text)
    assert [value for value, selected, _ in options if selected] == [""]


# The report's voice --------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_developer_and_the_neutral_report_send_nobody_to_a_seller(locale: str) -> None:
    for role in (ownership.OWN, None):
        page = _sample_page(locale, role)
        shown = _text(page)
        assert _seller_words(shown, locale) == [], (role, _seller_words(shown, locale))
        voice = role or ownership.NEUTRAL
        labels = _labels(locale, voice)
        for key in ("next_intro", "next_live", "next_questions", "next_keep", "questions"):
            assert labels[key] in shown, (role, key)
        assert find_claims(shown) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_buyer_reads_the_questions_for_the_seller(locale: str) -> None:
    shown = _text(_sample_page(locale, ownership.BUYER))
    labels = report.LABELS[locale]
    for key in ("next_intro", "next_live", "next_questions", "questions", "evidence_legend"):
        assert labels[key] in shown, key
    assert _seller_words(shown, locale)
    assert find_claims(shown) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_provider_reads_what_clients_will_ask_and_what_to_provide(locale: str) -> None:
    shown = _text(_sample_page(locale, ownership.PROVIDER))
    labels = _labels(locale, ownership.PROVIDER)
    for key in ("next_intro", "next_live", "next_trials", "next_questions", "questions"):
        assert labels[key] in shown, key
    lead = ownership.QUESTION_ITEM[ownership.PROVIDER][locale].split("{ask}")[0]
    asked = [q for q in _sample(locale).vendor_questions]
    assert shown.count(lead.strip()) >= len(asked)
    for question in asked:
        assert ownership.QUESTIONS[question["code"]][locale][1] in shown
    assert report.LABELS[locale]["next_intro"] not in shown
    assert find_claims(shown) == []


def test_the_sample_speaks_to_its_developer() -> None:
    """The public sample is an optimised EA declared as the client's own."""
    assert ownership.role_of(_sample("es").model_dump(mode="json")) == ownership.OWN
    page = _sample_page("es", ownership.OWN)
    labels = _labels("es", ownership.OWN)
    cover = page[page.index("<ol class='pc-next'>") :]
    cover = cover[: cover.index("</ol>")]
    assert html.escape(labels["next_live"], quote=True) in cover
    assert "Es mía (la desarrollé o la opero yo)" in page
    shown = _text(page)
    assert "Lo responde:" in shown
    assert labels["questions_intro"] in shown


@pytest.mark.parametrize("locale", LOCALES)
def test_a_developer_without_a_live_account_gets_the_developer_steps(locale: str) -> None:
    result = _backtest(ownership.OWN)
    shown = _text(render_html(result, watermark=False, locale=locale))
    labels = _labels(locale, ownership.OWN)
    for key in ("next_oos", "next_demo", "next_questions"):
        assert labels[key] in shown, key
    assert str(MIN_LIVE_TRADES) in labels["next_demo"]
    assert "MT5" in labels["next_oos"] and "forward" in labels["next_oos"]
    assert _seller_words(shown, locale) == []
    assert find_claims(shown) == []
    # The demo step is the developer's only.
    for role in (ownership.BUYER, ownership.PROVIDER, None):
        other = _text(render_html(_with_role(result, role), watermark=False, locale=locale))
        assert labels["next_demo"] not in other


def _invariants(page: str) -> dict[str, object]:
    """What may not change with the voice: figures, class, tags, section order."""
    page = ROLE_ROW.sub("", page)
    charts = page[page.index("id='r-charts'") :]
    return {
        "title": re.search(r"<title>(.*?)</title>", page).group(1),  # type: ignore[union-attr]
        "badges": re.findall(r"class='badge ([A-Za-z_ -]+)'", page),
        "values": re.findall(r"<td class='val'>(.*?)</td>", page),
        "kpis": re.findall(r"<div class='kpi [^']*'><b>(.*?)</b>", page),
        "sections": re.findall(r"<section class='rsec'(?: id='([^']*)')?>", page),
        "toc": re.findall(r"<li><a href='#([^']+)'>", page),
        "charts": charts[: charts.index("</section>")],
        "verdict": re.findall(r"<p class='verdict-text'>.*?</p>", page),
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_figures_class_tags_and_order_are_the_same_in_every_voice(locale: str) -> None:
    pages = {role: _sample_page(locale, role) for role in (*ownership.ROLES, None)}
    first = _invariants(pages[ownership.OWN])
    assert first["values"] and first["kpis"] and first["badges"]
    for role, page in pages.items():
        assert _invariants(page) == first, role


# The plan ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _account(role: str | None) -> dict:
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale="es", ownership=role),
        report_bytes=(FIXTURES / "mt4_statement.htm").read_bytes(),
        report_filename="statement.htm",
    )
    return run_audit(inputs, bootstrap_samples=100).model_dump(mode="json")


def _plan_text(data: dict, locale: str) -> str:
    return " ".join(
        " ".join([step.title, step.finding, *step.actions])
        for step in improvement_plan(data, locale)
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_of_an_account_speaks_to_each_reader(locale: str) -> None:
    asks = {
        "es": ("Pregunta al", "Pide el"),
        "en": ("Ask the", "Ask for"),
        "pt": ("Pergunte ao", "Peça o"),
    }
    buyer = _plan_text(_account(ownership.BUYER), locale)
    assert any(ask in buyer for ask in asks[locale])
    for role in (ownership.OWN, None):
        text = _plan_text(_account(role), locale)
        assert _seller_words(text, locale) == [], role
        assert not any(ask in text for ask in asks[locale]), role
    provider = _plan_text(_account(ownership.PROVIDER), locale)
    assert ownership.PLAN["account_oos_declare"][ownership.PROVIDER][locale] in provider
    for role in (*ownership.ROLES, None):
        assert find_claims(_plan_text(_account(role), locale)) == []
        page = _text(
            render_html(AuditResult.model_validate(_account(role)), watermark=False, locale=locale)
        )
        if role != ownership.BUYER:
            # The unmeasured holdout's meaning no longer sends anyone to the provider;
            # the provider's own declaration is the one place that names it.
            if role:
                page = page.replace(ownership.choice_label(role, locale), "")
            assert _seller_words(page, locale) == [], role


def test_the_plans_steps_and_classes_do_not_change_with_the_voice() -> None:
    def shape(data: dict) -> list[tuple[str, str, str | None, int]]:
        return [
            (s.dimension, s.status, s.class_if_passed, len(s.actions))
            for s in improvement_plan(data, "es")
        ]

    first = shape(_account(None))
    for role in ownership.ROLES:
        assert shape(_account(role)) == first


def _fund_grid(years: int = 6, seed: int = 5) -> bytes:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    rng = np.random.default_rng(seed)
    index = rng.normal(0.007, 0.04, 12 * years)
    fund = 0.9 * index + rng.normal(0.002, 0.012, 12 * years)
    lines = [",".join(["Year", *months])]
    for y in range(years):
        chunk = slice(12 * y, 12 * y + 12)
        lines.append(",".join([str(2018 + y), *(f"{v * 100:.2f}%" for v in fund[chunk])]))
    return ("\n".join(lines) + "\n").encode()


@lru_cache(maxsize=4)
def _fund(role: str | None) -> AuditResult:
    inputs = build_inputs(_fund_grid(), DeclaredMetadata(trials_declared=False, ownership=role))
    return run_audit(inputs, bootstrap_samples=100, audit_id="fundvoice", now=NOW)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_fund_speaks_to_its_manager_or_neutrally(locale: str) -> None:
    to_manager = {
        "es": ("Pregunta al gestor", "Pide al gestor", "Confirma con el gestor", "Si inviertes"),
        "en": ("Ask the manager", "Confirm with the manager", "If you invest"),
        "pt": ("Pergunte ao gestor", "Peça ao gestor", "Confirme com o gestor", "Se você investe"),
    }[locale]
    assert _fund(None).model_dump(mode="json")["fund"]["track_record"] is True
    for role in (ownership.OWN, None):
        page = _text(render_html(_with_role(_fund(None), role), watermark=False, locale=locale))
        labels = _labels(locale, role or ownership.NEUTRAL)
        assert labels["next_intro_fund"] in page and labels["next_keep_fund"] in page
        assert not [ask for ask in to_manager if ask in page], role
        assert _seller_words(page, locale) == []
        assert find_claims(page) == []
    provider = _text(
        render_html(_with_role(_fund(None), ownership.PROVIDER), watermark=False, locale=locale)
    )
    assert _labels(locale, ownership.PROVIDER)["next_intro_fund"] in provider


# The public page and the tables ---------------------------------------------------------


def test_the_public_page_and_its_card_never_show_the_answer() -> None:
    from quant_trade.audit.store import public_view

    plain = _with_role(_sample("es"), None).model_dump(mode="json")
    for role in ownership.ROLES:
        data = _with_role(_sample("es"), role).model_dump(mode="json")
        # The published view keeps the declared trials only.
        view, _ = public_view(_with_role(_sample("es"), role).model_dump_json())
        assert set(view["declared"]) == {"trials"}
        for locale in LOCALES:
            kwargs = {
                "public_id": "abc123",
                "published_at": "2026-10-01T00:00:00Z",
                "result_sha256": "0" * 64,
                "base_url": "https://rigorscore.com",
                "locale": locale,
            }
            page = verification_page(data, **kwargs)
            assert page == verification_page(plain, **kwargs)
            assert ownership.choice_label(role, locale) not in html.unescape(page)
            card = verification_card_svg(data, public_id="abc123", locale=locale)
            assert card == verification_card_svg(plain, public_id="abc123", locale=locale)


def _texts(node: object) -> list[str]:
    if isinstance(node, dict):
        return [text for value in node.values() for text in _texts(value)]
    if isinstance(node, (list, tuple)):
        return [text for value in node for text in _texts(value)]
    return [node] if isinstance(node, str) else []


def test_every_new_text_exists_in_three_languages_and_passes_the_guard() -> None:
    tables = (ownership.LABELS, ownership.LOCKED_GAINS, ownership.MEANING, ownership.PLAN)
    for table in tables:
        for key, voices in table.items():
            for role, texts in voices.items():
                assert role in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL), key
                assert set(texts) == set(LOCALES), (key, role)
    for text in _texts([ownership.FORM, *tables, ownership.QUESTIONS, ownership.QUESTION_ITEM]):
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
    # New keys aside, each voiced label replaces one the report already has.
    new = {"next_demo", "questions_intro"}
    assert set(ownership.LABELS) - new <= set(report.LABELS["es"])
    assert set(ownership.LOCKED_GAINS) <= set(report.LOCKED_GAINS["es"])
    for key in ownership.PLAN:
        if key.startswith("flag_"):
            assert key.removeprefix("flag_") in plan.FLAG_HINTS


@pytest.mark.parametrize("locale", LOCALES)
def test_every_text_that_names_a_seller_has_a_developer_and_a_neutral_voice(locale: str) -> None:
    for table, voiced in (
        (report.LABELS[locale], ownership.LABELS),
        (report.LOCKED_GAINS[locale], ownership.LOCKED_GAINS),
    ):
        for key, text in table.items():
            if _seller_words(text, locale):
                assert key in voiced, key
                assert {ownership.OWN, ownership.NEUTRAL} <= set(voiced[key]), key
                for role in (ownership.OWN, ownership.NEUTRAL):
                    assert _seller_words(voiced[key][role][locale], locale) == [], (key, role)
    asks = re.compile(r"\b(?:Pide|pide|Pregunta|pregunta|Ask|ask|Peça|peça|Pergunte|pergunte)\b")
    for code, hints in plan.FLAG_HINTS.items():
        if asks.search(hints[locale]):
            voices = ownership.PLAN.get(f"flag_{code}", {})
            assert {ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL} <= set(voices), code


def test_every_question_says_what_answers_it() -> None:
    assert set(_QUESTIONS) <= set(ownership.QUESTIONS)
    for code, entries in ownership.QUESTIONS.items():
        assert set(entries) == set(LOCALES), code
        for locale, (ask, answer) in entries.items():
            assert answer and answer[0].islower() and not answer.endswith("."), (code, locale)
            if ask is not None:
                assert ask.rstrip().endswith("?"), (code, locale)
                assert _seller_words(ask, locale) == []
