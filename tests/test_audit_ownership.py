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
from quant_trade.audit.live import MIN_BACKTEST_TRADES, MIN_LIVE_TRADES
from quant_trade.audit.mapping import CARRIED_FIELDS, Table, mapping_page
from quant_trade.audit.pages import upload_page, verification_card_svg, verification_page
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.report import render_html, to_json
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs, declared
from quant_trade.audit.verdict import MEANING as VERDICT_MEANING

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
    # The help says all it changes: the report's sentences, and the developer's demo step.
    assert "demo" in words["help"] and "«Qué hacer ahora»" not in words["help"]
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
    data = _with_role(_sample(locale), ownership.PROVIDER).model_dump(mode="json")
    asked = ownership.open_questions(data, ownership.PROVIDER)
    assert asked and shown.count(lead.strip()) >= len(asked)
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


def _steps(result: AuditResult | dict, locale: str = "es") -> list[str]:
    """The "What to do now" keys of a result, in its declared voice."""
    data = result if isinstance(result, dict) else result.model_dump(mode="json")
    labels = _labels(locale, ownership.role_of(data))
    return [key for key, _ in report._next_steps(data, data["verdict"], labels)]


def _status(result: AuditResult, name: str) -> dict:
    dimensions = result.model_dump(mode="json")["verdict"]["dimensions"]
    return next(d for d in dimensions if d["name"] == name)


@lru_cache(maxsize=4)
def _own(case: str) -> AuditResult:
    """The client's own robot in the shapes the review found wording gaps in."""
    files: dict[str, object] = {"report_filename": "tester.html"}
    declared = DeclaredMetadata(locale="es", trials=40, ownership="own")
    if case == "short":  # fewer closed trades than the live comparison needs
        files["report_bytes"] = synthetic_mt5_report(25)
    elif case == "short_live":  # ... with an account long enough on its own
        files["report_bytes"] = synthetic_mt5_report(25)
        files["live_bytes"] = synthetic_mt5_report(40, seed=3)
        files["live_filename"] = "live.html"
    elif case == "fixture":  # the MT5 tester fixture: real ticks, five trades, an account
        files = {
            "report_bytes": (FIXTURES / "mt5_tester.html").read_bytes(),
            "report_filename": "mt5_tester.html",
            "optimization_bytes": (FIXTURES / "mt5_optimization.xml").read_bytes(),
            "live_bytes": (FIXTURES / "mt5_history.html").read_bytes(),
            "live_filename": "mt5_history.html",
        }
        declared = DeclaredMetadata(ownership="own")
    elif case == "undeclared":  # no trial count, a thin edge: multiplicity fails at 1 trial
        files["report_bytes"] = synthetic_mt5_report(260, edge_pips=0.2)
        declared = DeclaredMetadata(trials_declared=False, ownership="own")
    inputs = build_inputs(None, declared, **files)  # type: ignore[arg-type]
    return run_audit(
        inputs,
        bootstrap_samples=60,
        risk_samples=50,
        challenge_samples=50,
        audit_id="ownership",
        now=NOW,
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_a_backtest_too_short_to_compare_names_both_minimums(locale: str) -> None:
    own = _labels(locale, ownership.OWN)
    text = own["next_demo_short"]
    assert str(MIN_BACKTEST_TRADES) in text and str(MIN_LIVE_TRADES) in text
    for case in ("short", "short_live", "fixture"):
        result = _own(case)
        data = result.model_dump(mode="json")
        assert data["trade_stats"]["trade_count"]["value"] < MIN_BACKTEST_TRADES, case
        if case != "short":
            # An account was uploaded, and the backtest is what keeps it unmeasured.
            assert data["live"]["status"] == "NOT_MEASURED"
            assert str(MIN_BACKTEST_TRADES) in data["live"]["reason"]
        keys = _steps(result, locale)
        assert "next_demo_short" in keys and "next_demo" not in keys, (case, keys)
        shown = _text(render_html(result, watermark=False, locale=locale))
        assert text in shown and own["next_demo"] not in shown, case
        assert find_claims(shown) == []
    # A backtest long enough keeps the plain demo step.
    assert "next_demo" in _steps(_backtest(ownership.OWN), locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_an_undeclared_trial_count_is_not_asked_to_be_cut(locale: str) -> None:
    result = _own("undeclared")
    multiplicity = _status(result, "multiplicity")
    assert multiplicity["status"] in ("WEAK", "FAIL")
    assert multiplicity["inputs"]["trials_used"] == {
        "value": 1,
        "evidence": "NOT_MEASURED",
        "note": "",
    }
    cut = ownership.LABELS["next_trials"][ownership.OWN][locale]
    for role in (ownership.OWN, None):
        voiced = _with_role(result, role)
        keys = _steps(voiced, locale)
        assert "next_trials_undeclared" in keys and "next_trials" not in keys, role
        shown = _text(render_html(voiced, watermark=False, locale=locale))
        assert _labels(locale, role or ownership.NEUTRAL)["next_trials_undeclared"] in shown
        assert cut not in shown
        assert find_claims(shown) == []
    # The buyer and the provider keep their question: it holds whatever the count.
    for role in (ownership.BUYER, ownership.PROVIDER):
        assert "next_trials" in _steps(_with_role(result, role), locale)


def test_cutting_trials_is_offered_only_when_more_than_one_was_counted() -> None:
    def step(value: int, evidence: str, role: str = ownership.OWN) -> str:
        dimension = {"inputs": {"trials_used": {"value": value, "evidence": evidence}}}
        return ownership.trials_step(dimension, role)

    assert step(40, "DECLARED") == step(120, "MEASURED") == "next_trials"
    assert step(1, "DECLARED") == step(1, "MEASURED") == "next_trials_one"
    assert step(1, "NOT_MEASURED") == "next_trials_undeclared"
    assert step(1, "NOT_MEASURED", ownership.NEUTRAL) == "next_trials_undeclared"
    for role in (ownership.BUYER, ownership.PROVIDER):
        assert step(1, "NOT_MEASURED", role) == step(1, "DECLARED", role) == "next_trials"
    for locale in LOCALES:
        for key in ("next_trials_undeclared", "next_trials_one"):
            text = _labels(locale, ownership.OWN)[key]
            assert "0.95" in text and find_claims(text) == []


def _forward_export() -> bytes:
    """An MT5 forward optimisation export whose ranking holds (as in test_audit_forward)."""
    names = ["Pass", "Forward Result", "Back Result", "Profit", "Expected Payoff"]
    names += ["Profit Factor", "Recovery Factor", "Sharpe Ratio", "Custom", "Equity DD %"]
    names += ["Trades", "FastMA", "SlowMA"]

    def cell(value: object) -> str:
        kind = "Number" if isinstance(value, int | float) else "String"
        return f'<Cell><Data ss:Type="{kind}">{value}</Data></Cell>'

    rows = ["<Row>" + "".join(cell(name) for name in names) + "</Row>"]
    number = 0
    for fast in (4, 8, 12, 16, 20):
        for slow in (24, 36, 48, 60, 72):
            back = 1000.0 - 20 * abs(fast - 12) - 5 * abs(slow - 48)
            profit = back / 4 - 150.0
            values = [number, 10_000 + profit, 10_000 + back, profit, 1.0, 1.2, 0.5, 0.3]
            values += [0, 5.0, 40, fast, slow]
            rows.append("<Row>" + "".join(cell(v) for v in values) + "</Row>")
            number += 1
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        + "".join(rows)
        + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


@lru_cache(maxsize=1)
def _with_forward() -> AuditResult:
    inputs = build_inputs(
        None,
        DeclaredMetadata(locale="es", trials=40, ownership="own"),
        report_bytes=synthetic_mt5_report(260),
        report_filename="tester.html",
        optimization_bytes=_forward_export(),
    )
    return run_audit(
        inputs,
        bootstrap_samples=60,
        risk_samples=50,
        challenge_samples=50,
        audit_id="ownership",
        now=NOW,
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_an_uploaded_forward_export_is_not_asked_for_again(locale: str) -> None:
    result = _with_forward()
    assert result.model_dump(mode="json")["forward"]["status"] == "MEASURED"
    assert _status(result, "out_of_sample")["status"] == "NOT_MEASURED"
    keys = _steps(result, locale)
    assert "next_oos_forward" in keys and "next_oos" not in keys
    own = _labels(locale, ownership.OWN)
    assert "XML" not in own["next_oos_forward"]
    shown = _text(render_html(result, watermark=False, locale=locale))
    assert own["next_oos_forward"] in shown and own["next_oos"] not in shown
    assert find_claims(shown) == []
    # Without a forward export, the step says the XML is reviewed apart from this test.
    assert "XML" in own["next_oos"] and "next_oos" in _steps(_backtest(ownership.OWN), locale)


@pytest.mark.parametrize("status", ["WEAK", "FAIL"])
def test_an_out_of_sample_stretch_already_seen_is_not_reoptimised_on(status: str) -> None:
    data = _backtest(ownership.OWN).model_dump(mode="json")
    verdict = {
        **data["verdict"],
        "dimensions": [
            {**d, "status": status} if d["name"] == "out_of_sample" else d
            for d in data["verdict"]["dimensions"]
        ],
    }
    for locale in LOCALES:
        for role, expected in ((ownership.OWN, "next_oos_seen"), (ownership.NEUTRAL, "next_oos")):
            keys = [k for k, _ in report._next_steps(data, verdict, _labels(locale, role))]
            assert expected in keys, (role, keys)
        text = _labels(locale, ownership.OWN)["next_oos_seen"]
        assert "reoptimi" in text.lower() or "reotimi" in text.lower()
        assert "declara" not in text.lower() and find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_modelling_question_does_not_send_the_developer_back_to_the_same_file(
    locale: str,
) -> None:
    buyer_answer = ownership.QUESTIONS["modelling"][locale][1]
    unread = ownership.QUESTIONS["modelling_unread"][locale][1]
    # The sample's MT5 report prints no mode we recognise: ask for one that does.
    sample = _sample(locale).model_dump(mode="json")
    assert sample["test_data"]["tick_model"]["evidence"] == "NOT_MEASURED"
    shown = _text(_sample_page(locale, ownership.OWN))
    assert unread in shown and buyer_answer not in shown
    # The fixture's MT5 report states real ticks: the question is answered, so it goes.
    fixture = _own("fixture")
    data = fixture.model_dump(mode="json")
    assert data["test_data"]["tick_model"]["value"] == "real ticks"
    assert "modelling" in [q["code"] for q in data["vendor_questions"]]
    for role in (ownership.OWN, ownership.PROVIDER, None):
        codes = [q["code"] for q in ownership.open_questions(data, role or ownership.NEUTRAL)]
        assert not [code for code in codes if code.startswith("modelling")], role
        page = _text(render_html(_with_role(fixture, role), watermark=False, locale=locale))
        assert buyer_answer not in page and unread not in page
    # The buyer still asks the seller to confirm what the header says.
    assert "modelling" in [q["code"] for q in ownership.open_questions(data, ownership.BUYER)]


def test_a_flagged_or_unread_tester_mode_gets_its_own_wording() -> None:
    question = {"code": "modelling", "es": "¿Con qué modo?", "en": "Which mode?"}

    def codes(test_data: dict, flags: list[str], role: str = ownership.OWN) -> list[str]:
        data = {
            "vendor_questions": [question, {"code": "costs", "es": "¿Costos?", "en": "Costs?"}],
            "test_data": test_data,
            "red_flags": [{"code": code} for code in flags],
        }
        return [q["code"] for q in ownership.open_questions(data, role)]

    def review(model: str | None) -> dict:
        evidence = "DECLARED" if model else "NOT_MEASURED"
        return {"status": "MEASURED", "tick_model": {"value": model, "evidence": evidence}}

    stated, coarse, unread = review("every tick"), review("open prices only"), review(None)
    other = {"status": "NOT_MEASURED", "reason": "the file is not a MetaTrader tester report"}
    assert codes(stated, []) == ["costs"]
    assert codes(coarse, ["COARSE_TICK_MODEL"]) == ["modelling_flagged", "costs"]
    assert codes(stated, ["TEST_DATA_QUALITY_LOW"]) == ["modelling_flagged", "costs"]
    assert codes(unread, []) == ["modelling_unread", "costs"]
    assert codes(other, []) == ["modelling", "costs"]
    assert codes(stated, [], ownership.BUYER) == ["modelling", "costs"]
    for locale in LOCALES:
        for code in ("modelling_flagged", "modelling_unread"):
            for role in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
                text = ownership.question_item(code, "¿Con qué modo?", locale, role)
                assert ownership.QUESTIONS[code][locale][1] in text
                assert find_claims(text) == [] and _seller_words(text, locale) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_sample_does_not_ask_its_developer_for_their_own_optimisation_file(
    locale: str,
) -> None:
    sample = _sample(locale)
    multiplicity = _status(sample, "multiplicity")
    assert multiplicity["status"] == "WEAK"
    assert multiplicity["inputs"]["trials_used"]["evidence"] == "MEASURED"
    asks = {
        "es": ("Pregunta cuántas", "pide el archivo"),
        "en": ("Ask how many", "request the optimisation file"),
        "pt": ("Pergunte quantas", "peça o arquivo"),
    }[locale]
    for role in (ownership.OWN, ownership.PROVIDER, None):
        shown = _text(_sample_page(locale, role))
        assert not [ask for ask in asks if ask in shown], role
        voiced = ownership.MEANING["multiplicity.WEAK"][role or ownership.NEUTRAL][locale]
        assert voiced in shown, role
    assert VERDICT_MEANING[locale]["multiplicity.WEAK"] in _text(
        _sample_page(locale, ownership.BUYER)
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_landing_promises_questions_every_voice_gets(locale: str) -> None:
    """The sample and an unanswered report show the questions the report leaves
    open, not questions for a seller: the landing says so for every reader."""
    from quant_trade.audit.pages import _COPY, _full_items

    texts = [
        *_full_items(locale),
        *(answer for _, answer in _COPY[locale]["faq"]),
    ]
    promise = {
        "es": ("preguntas para el vendedor", "Preguntas concretas para el vendedor"),
        "en": ("questions for the vendor", "Specific questions for the robot's vendor"),
        "pt": ("perguntas para o vendedor", "Perguntas concretas para o vendedor"),
    }[locale]
    joined = " ".join(texts)
    assert not [words for words in promise if words in joined]
    leaves_open = {"es": "deja abiertas", "en": "leaves open", "pt": "deixa abertas"}[locale]
    assert leaves_open in _full_items(locale)[3]
    assert sum(leaves_open in text for text in texts) >= 2
    assert find_claims(joined) == []


def test_the_meaning_of_a_weak_search_speaks_to_each_reader() -> None:
    asks = re.compile(r"\b(?:Pregunta|pregunta|Pide|pide|Ask|ask|Pergunte|Peça|peça)\b")
    for locale in LOCALES:
        assert ownership.meaning("multiplicity", "WEAK", locale, ownership.BUYER) is None
        for role in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
            for flags, key in (
                ({}, "multiplicity.WEAK"),
                ({"fund": True}, "multiplicity.WEAK.fund"),
                ({"undeclared": True}, "multiplicity.WEAK.undeclared"),
                ({"undeclared": True, "fund": True}, "multiplicity.WEAK.undeclared.fund"),
            ):
                text = ownership.meaning("multiplicity", "WEAK", locale, role, **flags)
                assert text == ownership.MEANING[key][role][locale], (role, key)
                assert not asks.search(text) and find_claims(text) == [], (role, key)
            # The verdict's wording names nobody there: it stays.
            assert ownership.meaning("multiplicity", "FAIL", locale, role, undeclared=True) is None
            assert ownership.meaning("multiplicity", "FAIL", locale, role) is None


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


#: The buyer's fund wording: to the manager, or to whoever offers the fund.
OFFERED: dict[str, tuple[str, ...]] = {
    "es": ("quien te ofrece", "Lleva las preguntas"),
    "en": ("offers you", "whoever offers", "Take this report's questions"),
    "pt": ("quem oferece", "Leve as perguntas"),
}


@pytest.mark.parametrize("locale", LOCALES)
def test_a_fund_speaks_to_its_manager_or_neutrally(locale: str) -> None:
    to_manager = {
        "es": ("Pregunta al gestor", "Pide al gestor", "Confirma con el gestor", "Si inviertes"),
        "en": ("Ask the manager", "Confirm with the manager", "If you invest"),
        "pt": ("Pergunte ao gestor", "Peça ao gestor", "Confirme com o gestor", "Se você investe"),
    }[locale] + OFFERED[locale]
    assert _fund(None).model_dump(mode="json")["fund"]["track_record"] is True
    for role in (ownership.OWN, None):
        raw = render_html(_with_role(_fund(None), role), watermark=False, locale=locale)
        page = _text(raw)
        labels = _labels(locale, role or ownership.NEUTRAL)
        assert labels["next_intro_fund"] in page and labels["next_keep_fund"] in page
        # "What to do now" and the PDF cover send the reader to the questions in this voice.
        assert page.count(labels["next_questions_fund"]) == 2, role
        assert not [ask for ask in to_manager if ask in page], role
        assert _seller_words(page, locale) == []
        assert find_claims(page) == []
    provider = _text(
        render_html(_with_role(_fund(None), ownership.PROVIDER), watermark=False, locale=locale)
    )
    labels = _labels(locale, ownership.PROVIDER)
    assert labels["next_intro_fund"] in provider
    assert provider.count(labels["next_questions_fund"]) == 2
    assert not [ask for ask in OFFERED[locale] if ask in provider]
    assert find_claims(provider) == []
    # Only the buyer is sent to whoever offers the fund.
    buyer = _text(
        render_html(_with_role(_fund(None), ownership.BUYER), watermark=False, locale=locale)
    )
    assert report.LABELS[locale]["next_questions_fund"] in buyer


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
    new = {
        "next_demo",
        "next_demo_short",
        "next_trials_undeclared",
        "next_trials_one",
        "next_oos_forward",
        "next_oos_seen",
        "questions_intro",
    }
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
