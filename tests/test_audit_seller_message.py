"""The questions for the seller in one message, ready to copy into a chat.

With "La compré o la voy a comprar / copiar" declared, the questions section
ends with a plain text for the seller: the class, the dimensions that do not
pass, two to four key figures with their evidence tag in words, the open
questions numbered and, when the report is published, its public page. It is
built from the report alone, stays under Telegram's limit, uses the site's
copy button, and no other voice, the locked preview or the PDF shows it.
Offline and deterministic.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in, synthetic_mt5_report

from quant_trade.audit import funnel, ownership, report, seller_message
from quant_trade.audit.analytics import _QUESTIONS
from quant_trade.audit.engine import UNDECLARED_TRIALS, run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.live import MIN_LIVE_TRADES
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs, declared
from quant_trade.audit.theme import PRINT, STYLE

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
#: The words the brief keeps out of every text.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable", "verified", "certified")
TEXTAREA = re.compile(r"<textarea id='seller-message-text'[^>]*>(.*?)</textarea>", re.S)
PUBLIC_ID = "pub7a2b"
LIVE_SHORT = f"the live statement has fewer than {MIN_LIVE_TRADES} closed trades"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _with_role(result: AuditResult, role: str | None) -> AuditResult:
    data = dict(result.declared)
    data.pop("ownership", None)
    if role:
        data["ownership"] = declared(role)
    return result.model_copy(update={"declared": data})


@lru_cache(maxsize=1)
def _buyer() -> AuditResult:
    """An MT5 tester report with a live account, declared by its buyer."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale="es", trials=40, ownership="buyer"),
        report_bytes=synthetic_mt5_report(260, edge_pips=3.0),
        report_filename="tester.html",
        live_bytes=synthetic_mt5_report(40, seed=3),
        live_filename="live.html",
    )
    return run_audit(
        inputs,
        bootstrap_samples=60,
        risk_samples=50,
        challenge_samples=50,
        audit_id="sellermsg",
        now=NOW,
    )


@lru_cache(maxsize=8)
def _page(locale: str, role: str | None = ownership.BUYER, public_id: str | None = None) -> str:
    return render_html(
        _with_role(_buyer(), role), watermark=False, locale=locale, public_id=public_id
    )


def _locked(locale: str, role: str | None) -> str:
    return render_html(
        _with_role(_buyer(), role),
        watermark=True,
        free_mode=False,
        price_usd=29,
        checkout_url="/audits/abc123/checkout",
        locale=locale,
        public_id=PUBLIC_ID,
    )


def _message(page: str) -> str:
    found = TEXTAREA.search(page)
    assert found, "the page has no message for the seller"
    return html.unescape(found.group(1))


def _block(page: str) -> str:
    start = page.index("<div class='seller-msg no-print' id='seller-message'>")
    return page[start : page.index("</div></div>", start) + len("</div></div>")]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_buyer_gets_the_message_with_the_copy_button(locale: str) -> None:
    page = _page(locale)
    words = seller_message.words(locale)
    block = _block(page)
    # Inside the questions section, after the questions themselves.
    questions = page.index(f"<h2>{html.escape(report.LABELS[locale]['questions'])}</h2>")
    assert questions < page.index("id='seller-message'") < page.index("</details>", questions)
    assert html.escape(words["title"]) in block
    assert html.escape(words["intro"].format(who=words["who"])) in block
    # The site's copy button (static/app.js), pointing at the text, hidden until the script runs.
    assert "data-copy='seller-message-text'" in block
    assert f"data-done='{html.escape(words['done'])}' hidden>" in block
    assert html.escape(words["copy"]) in block
    assert "<textarea id='seller-message-text' readonly" in block
    assert "<script" not in block
    message = _message(page)
    assert find_claims(message) == [] and find_claims(_text(block)) == []
    assert not [word for word in BANNED if word in message.lower()]
    assert find_claims(_text(page)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_message_carries_class_figures_with_tags_and_the_questions(locale: str) -> None:
    data = _buyer().model_dump(mode="json")
    labels = report.LABELS[locale]
    words = seller_message.words(locale)
    message = _message(_page(locale))
    assert seller_message.chat_length(message) < seller_message.MAX_CHARS
    lines = message.split("\n")
    assert lines[0] == words["hello"]
    assert words["class"].format(cls=data["verdict"]["overall"]) in lines
    # Every dimension that fails or is weak, by its name, with its status in words.
    status = report.STATUS_TEXT[locale]
    for dimension in data["verdict"]["dimensions"]:
        named = f"{report._dimension_title(dimension['name'], locale)} ("
        if dimension["status"] in ("FAIL", "WEAK"):
            assert f"{named}{status[dimension['status']].lower()})" in message
        else:
            assert named not in message
    # Two to four figures, each with its evidence tag in words, as the report computes them.
    start = lines.index(words["figures"]) + 1
    figures = lines[start : lines.index("", start)]
    assert 2 <= len(figures) <= 4
    tags = {report.evidence_label(tag, locale).lower() for tag in ("MEASURED", "DECLARED")}
    assert all(re.search(r"\(([^()]+)\)$", line).group(1) in tags for line in figures)
    costs = data["costs"]
    breakeven = costs["break_even_bps"]["value"]
    assert breakeven > 0 and costs["break_even_pips"]["evidence"] == "MEASURED"
    units = "; ".join([labels["bps_side"], *report._trader_units(costs, labels)])
    measured = report.evidence_label("MEASURED", locale).lower()
    assert f"- {labels['kpi_breakeven']}: {breakeven:,.2f} {units} ({measured})" in figures
    assert f"{costs['break_even_pips']['value']:,.1f} pips" in units
    live = data["live"]
    assert live["status"] == "MEASURED"
    assert any(
        line.startswith(f"- {labels['live']}: {labels['live_badge_' + live['outcome']]}; ")
        and f": {live['net_below']['value']:.0%} ({measured})" in line
        for line in figures
    )
    trials = data["multiplicity"]["trials_used"]
    declared_word = report.evidence_label("DECLARED", locale).lower()
    assert f"- {labels['trials_used']}: {trials['value']} ({declared_word})" in figures
    drawdown = data["performance"]["max_drawdown"]["value"]
    assert any(f": {report._pct(drawdown)} ({measured})" in line for line in figures)
    # The open questions, numbered, in the seller's wording.
    asked = ownership.open_questions(data, ownership.BUYER)
    assert asked
    for number, question in enumerate(asked, 1):
        text = seller_message.seller_question(
            question["code"], report._question_text(question, locale), locale
        )
        assert f"{number}. {text}" in lines
    assert lines[-1] == words["made"]
    if locale == "es":
        assert lines[-1] == "Informe hecho con Rigor (rigorscore.com)"


def test_a_question_for_the_buyer_reaches_the_seller_as_a_question() -> None:
    message = _message(_page("es"))
    assert "Pide " not in message and "pide " not in message
    assert "¿Puedes enviar el archivo de optimización?" in message
    # The section above keeps the stored wording.
    assert "Pide el archivo de optimización." in _text(_page("es"))


@pytest.mark.parametrize("locale", LOCALES)
def test_no_other_voice_gets_the_message(locale: str) -> None:
    for role in (ownership.OWN, ownership.PROVIDER, None):
        page = _page(locale, role)
        assert "seller-message" not in page, role
        assert "data-copy='seller-message-text'" not in page, role
        words = seller_message.words(locale)
        assert words["title"] not in html.unescape(page), role


@pytest.mark.parametrize("locale", LOCALES)
def test_the_public_link_only_when_the_report_is_published(locale: str) -> None:
    words = seller_message.words(locale)
    private = _message(_page(locale))
    assert "rigorscore.com/v/" not in private
    assert words["public"].split("{url}")[0] not in private
    published = _message(_page(locale, public_id=PUBLIC_ID))
    url = f"https://rigorscore.com/v/{PUBLIC_ID}?ref=vendedor" + (
        "" if locale == "es" else f"&lang={locale}"
    )
    assert words["public"].format(url=url) in published.split("\n")
    assert published.split("\n")[-1] == words["made"]
    # The tag counts in the funnel, so /panel shows the visits the message brings.
    assert seller_message.REF in funnel.REF_TAGS
    assert funnel.clean_ref(seller_message.REF) == seller_message.REF


@pytest.mark.parametrize("locale", LOCALES)
def test_the_locked_preview_names_the_message_for_the_buyer_only(locale: str) -> None:
    words = seller_message.words(locale)
    locked = _locked(locale, ownership.BUYER)
    assert "seller-message" not in locked
    box = html.unescape(locked.split("class='lockbox'", 1)[1].split("class='lock-sample'", 1)[0])
    gains = report.LOCKED_GAINS[locale]
    assert words["lock"] in box
    assert box.index(gains["questions"]) < box.index(words["lock"])
    assert find_claims(box) == []
    for role in (ownership.OWN, ownership.PROVIDER, None):
        other = html.unescape(_locked(locale, role))
        assert words["lock"] not in other and "seller-message" not in other, role


def test_an_unmeasured_figure_says_so_with_its_reason() -> None:
    data = _buyer().model_dump(mode="json")
    data["multiplicity"]["trials_used"] = {
        "value": 1,
        "evidence": "NOT_MEASURED",
        "note": UNDECLARED_TRIALS,
    }
    data["live"] = {"status": "NOT_MEASURED", "reason": LIVE_SHORT}
    for locale in LOCALES:
        labels = report.LABELS[locale]
        unmeasured = seller_message.words(locale)["not_measured"]
        figures = report._seller_figures(data, locale, labels)
        reason = report._localized_reason(UNDECLARED_TRIALS, locale)
        assert f"{labels['trials_used']}: {unmeasured} ({reason})" in figures
        # No count is given for an undeclared trial count.
        assert not any(line.startswith(f"{labels['trials_used']}: 1") for line in figures)
        live_reason = report._localized_reason(LIVE_SHORT, locale)
        assert f"{labels['live']}: {unmeasured} ({live_reason})" in figures
        assert 2 <= len(figures) <= 4


def test_a_message_too_long_for_telegram_drops_questions_and_says_so() -> None:
    data = _buyer().model_dump(mode="json")
    long_question = {
        "code": "best_trade",
        "es": "¿Qué pasó en la mejor operación? " * 12,
        "en": "What happened in the best trade? " * 12,
    }
    data["vendor_questions"] = [dict(long_question) for _ in range(30)]
    result = AuditResult.model_validate(data)
    for locale in LOCALES:
        words = seller_message.words(locale)
        text, shown, total = report._seller_message(data, locale, report.LABELS[locale], PUBLIC_ID)
        assert total == 30 and 0 < shown < total
        assert seller_message.chat_length(text) < seller_message.MAX_CHARS
        assert words["trimmed"].format(n=total - shown) in text.split("\n")
        assert f"{shown}. " in text and f"{shown + 1}. " not in text
        page = render_html(result, watermark=False, locale=locale)
        note = words["trimmed_note"].format(shown=shown, total=total)
        assert html.escape(note) in _block(page)
        assert find_claims(text) == [] and find_claims(note) == []


def _fund_grid(years: int = 6, seed: int = 5) -> bytes:
    """A fund's monthly returns with a benchmark row per year."""
    rng = np.random.default_rng(seed)
    index = rng.normal(0.007, 0.04, 12 * years)
    fund = 0.9 * index + rng.normal(0.002, 0.012, 12 * years)
    lines = [",".join(["Year", *MONTHS])]
    for year in range(years):
        chunk = slice(12 * year, 12 * year + 12)
        lines.append(",".join([str(2018 + year), *(f"{v * 100:.2f}%" for v in fund[chunk])]))
        lines.append(",".join(["Benchmark", *(f"{v * 100:.2f}%" for v in index[chunk])]))
    return ("\n".join(lines) + "\n").encode()


def test_a_fund_message_goes_to_its_manager() -> None:
    inputs = build_inputs(_fund_grid(), DeclaredMetadata(ownership="buyer"))
    result = run_audit(inputs, now=NOW, audit_id="fundmsg", bootstrap_samples=60)
    data = result.model_dump(mode="json")
    for locale in LOCALES:
        words = seller_message.words(locale)
        page = render_html(result, watermark=False, locale=locale)
        message = _message(page)
        assert html.escape(words["title_fund"]) in _block(page)
        assert message.startswith(words["hello_fund"])
        assert "robot" not in message.lower() and "robô" not in message.lower()
        # A fund has no trades to cost: no break-even line rather than an empty one.
        assert report.LABELS[locale]["kpi_breakeven"] not in message
        figures = report._seller_figures(data, locale, report.LABELS[locale])
        assert 2 <= len(figures) <= 4
        assert seller_message.chat_length(message) < seller_message.MAX_CHARS
        assert find_claims(message) == []


def test_every_text_exists_in_three_languages_and_passes_the_guard() -> None:
    assert set(seller_message.COPY) == set(LOCALES)
    keys = set(seller_message.COPY["es"])
    for locale in LOCALES:
        assert set(seller_message.COPY[locale]) == keys, locale
    texts = [text for words in seller_message.COPY.values() for text in words.values()]
    for code, asks in seller_message.SELLER_ASK.items():
        assert set(asks) == set(LOCALES), code
        assert code in _QUESTIONS, code
        for locale, ask in asks.items():
            # A question to the seller, never an instruction to the buyer.
            assert ask.rstrip().endswith("?"), (code, locale)
            assert not re.search(r"\b(?:Pide|pide|Ask for|ask for|Peça|peça)\b", ask), code
            texts.append(ask)
    for text in texts:
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
    # Every stored question that speaks to the buyer has the seller's wording.
    buyer_words = re.compile(r"\b(?:Pide|pide|su bróker)\b")
    for code, stored in _QUESTIONS.items():
        if buyer_words.search(stored["es"]):
            assert code in seller_message.SELLER_ASK, code


def test_the_pdf_leaves_the_message_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page laid out as PDF has the block marked no-print, which the print
    stylesheet hides; the PDF keeps the questions themselves."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit import pdf as pdf_lib
    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    laid_out: list[str] = []

    def fake_pdf(page_html: str, **_: object) -> bytes:
        laid_out.append(page_html)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(pdf_lib, "available", lambda: True)
    monkeypatch.setattr(pdf_lib, "report_pdf", fake_pdf)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=60)
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    response = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "ownership": "buyer"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"]).text
    assert "data-copy='seller-message-text'" in page
    start = page.index("/pdf?token=")
    link = page[page.rindex("'", 0, start) + 1 : page.index("'", start)].replace("&amp;", "&")
    pdf = client.get(link)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert len(laid_out) == 1
    printed = laid_out[0]
    assert "<div class='seller-msg no-print' id='seller-message'>" in printed
    assert re.search(r"\.no-print[^{}]*\{\s*display:none!important", PRINT) and PRINT in STYLE
    # The questions themselves stay in the printed report.
    assert html.escape(report.LABELS["es"]["questions"]) in printed
