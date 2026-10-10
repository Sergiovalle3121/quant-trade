"""A fund or portfolio report in a fund's words (errores 17).

PR 489 left an account or signal's report free of robot words; a fund or
portfolio's report still read as a backtest's: the multiplicity dimension was
"Number of settings tried", the luck section said the more configurations are
tried the higher the best one comes out and that the number could be measured
from the optimisation XML, and the technical detail said "Observed across
variants" and "no variants uploaded". Emerging managers read that report, and so
do the clients of the institutional review, who receive the sample at
/revision-institucional/ejemplo.

Each test reads the monthly CSV with its Benchmark column of
``test_audit_fund_verdict`` (with ten trials declared, with the form's single
trial and with none declared) or the sample institutional review
(``institutional_sample``), in Spanish, English and Portuguese and in every voice:

1. the luck section, the multiplicity dimension, the plan, the technical detail,
   the paid preview, the message for the manager and the PDF speak of the
   portfolios, strategies or variants evaluated before this one was chosen, a
   number declared at upload or measured from the variants matrix (the
   variants' return columns), never of an optimisation XML or a robot;
2. the sample review's notes name the dimension, the trials and the variants
   matrix as its fund report does, with the same figures;
3. a backtest keeps its words, and an account or signal those of PR 489.

No figure, class or tag changes: every test reads the stored result as the
engine wrote it. Nothing reaches the network.
"""

from __future__ import annotations

import copy
import html
import re
from functools import cache
from typing import Any

import numpy as np
import pandas as pd
import pytest
from test_audit_fund_verdict import _dated, _pair, _run

from quant_trade.audit import engine, institutional_sample, ownership, report, seller_message
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit import plan as plan_lib
from quant_trade.audit import verdict as verdict_lib
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.luck import NOTE as LUCK_NOTE
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.report import (
    CSCV_COUNTS_FUND,
    DIMENSION_TITLES,
    DIMENSION_TITLES_ACCOUNT,
    DIMENSION_TITLES_FUND,
    DIMENSION_TITLES_MIXED,
    KEY_LABELS,
    LABELS,
    LOCKED_GAINS,
    LOCKED_GAINS_ACCOUNT,
    LOCKED_GAINS_FUND,
    render_html,
)
from quant_trade.audit.sample import sample_result, signal_sample_result
from quant_trade.audit.schema import (
    AuditResult,
    DeclaredMetadata,
    build_inputs,
    declared,
    measured,
)

LOCALES = ("es", "en", "pt")
ROLES = [*ownership.ROLES, None]
#: The fixture's three ways of counting a fund's trials: ten declared, the form's
#: single trial, and none declared (computed at 1, the most favourable case).
TRIALS: dict[str, dict[str, Any]] = {
    "ten": {"trials": 10},
    "one": {},
    "undeclared": {"trials_declared": False},
}
#: What a fund's trials are, in the brief's words.
EVALUATED = {
    "es": "carteras, estrategias o variantes",
    "en": "portfolios, strategies or variants",
    "pt": "carteiras, estratégias ou variantes",
}
#: The same, in the singular or the plural ("Count every portfolio, strategy or variant").
EVALUATED_ANY = {
    "es": re.compile(r"carteras?, estrategias? o variantes?", re.I),
    "en": re.compile(r"portfolios?, strateg(?:y|ies) or variants?", re.I),
    "pt": re.compile(r"carteiras?, estratégias? ou variantes?", re.I),
}
#: The variants matrix, said as the brief says it: the variants' return columns.
MATRIX = {"es": "matriz de variantes", "en": "variants matrix", "pt": "matriz de variantes"}
RETURN_COLUMNS = {
    "es": "las columnas de retornos de las variantes",
    "en": "the variants' return columns",
    "pt": "as colunas de retornos das variantes",
}
#: The words the brief keeps out of every text.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable")
#: The report's name for the count the deflated Sharpe uses, and "or more".
TRIAL_WORD = {"es": "intentos", "en": "trials", "pt": "tentativas"}
OR_MORE = {"es": "o más", "en": "or more", "pt": "ou mais"}
#: A fund's noun right after a figure ("10 carteras", "512 or more portfolios").
FUND_NOUN = {"es": "carteras", "en": "portfolios", "pt": "carteiras"}
#: An optimiser's passes: never on a fund's page.
PASSES = re.compile(r"optimi|otimiz|pasadas|passagens", re.I)
#: A backtest's trials, a robot and an optimiser's files: none of them on a fund's page.
NOT_A_FUND = re.compile(
    r"configuraciones|configurations|configurações|\b(una sola|1) configuración"
    r"|\b(a single|1) configuration|\b(uma única|1) configuração|settings tried|\d settings\b"
    r"|\b(EA|XML|robot|robots|robô|robôs)\b|optimi[sz]\w*|optimizaci\w*|optimizador\w*"
    r"|otimiza\w*|otimizador\w*|longitud mínima del backtest|minimum backtest length"
    r"|tamanho mínimo do backtest",
    re.I,
)
#: The manager's own funds, the fund's words for its trials before this branch.
FUNDS_OF_THE_MANAGER = re.compile(
    r"fondos o estrategias|funds or strategies|fundos ou estratégias|cuántos fondos"
    r"|how many funds|quantos fundos",
    re.I,
)
NO_VARIANTS = report.NO_VARIANTS


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _voice(role: str | None) -> str:
    return role or ownership.NEUTRAL


def _labels(locale: str, role: str | None) -> dict[str, str]:
    return ownership.labels_for(LABELS[locale], locale, _voice(role))


def _with_role(data: dict[str, Any], role: str | None) -> dict[str, Any]:
    """``data`` with ``role`` declared as whose strategy it is (None: nothing declared)."""
    shown = copy.deepcopy(data)
    shown["declared"].pop("ownership", None)
    if role:
        shown["declared"]["ownership"] = declared(role)
    return shown


@cache
def _fund_result(locale: str, trials: str) -> AuditResult:
    """The monthly CSV with its Benchmark column of ``test_audit_fund_verdict``."""
    fund, index = _pair()
    result = _run(_dated(fund, index), locale, **TRIALS[trials])
    assert isinstance(result, AuditResult)
    return result


def _fund(locale: str, trials: str, role: str | None) -> dict[str, Any]:
    """The fund's stored result in ``role``'s voice (a fresh copy: tests may change it)."""
    return _with_role(_fund_result(locale, trials).model_dump(mode="json"), role)


@cache
def _fund_page(locale: str, trials: str, role: str | None) -> str:
    """The fund's full report as the PDF lays it out: every section open."""
    page = render_html(
        AuditResult.model_validate(_fund(locale, trials, role)), watermark=False, locale=locale
    )
    return pdf_lib._expand_details_for_pdf(page)


@cache
def _fund_preview(locale: str, trials: str, role: str | None) -> str:
    """The fund's paid preview: the verdict free, the rest locked."""
    data = AuditResult.model_validate(_fund(locale, trials, role))
    return render_html(data, watermark=True, free_mode=False, locale=locale)


@cache
def _institutional(locale: str) -> AuditResult:
    return institutional_sample.sample_result(locale, bootstrap_samples=60)


@cache
def _backtest(locale: str) -> AuditResult:
    return sample_result(locale, bootstrap_samples=60)


@cache
def _signal(locale: str) -> AuditResult:
    return signal_sample_result(locale, bootstrap_samples=60)


def _lockbox(page: str) -> list[str]:
    """The lines the preview's lockbox lists, as the reader gets them."""
    box = page.split("<div class='lockbox'", 1)[1].split("</ul>", 1)[0]
    return [_visible(item) for item in re.findall(r"<li>(.*?)</li>", box, re.S)]


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _backtest_words(locale: str, role: str | None) -> list[str]:
    """The backtest's texts the brief found on a fund's report."""
    labels = _labels(locale, role)
    return [
        DIMENSION_TITLES[locale]["multiplicity"],
        labels["luck_intro"],
        labels["luck_uncounted"],
        labels["luck_table_trials"],
        labels["variance_policy"],
        KEY_LABELS[locale]["observed_across_variants"],
        report._localized_reason(NO_VARIANTS, locale),
        _sentence_case(report._localized_reason(NO_VARIANTS, locale)),
    ]


def _multiplicity(data: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in data["verdict"]["dimensions"] if d["name"] == "multiplicity")


# 0 · the fixture is what the brief read ---------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_fixture_is_a_fund_with_its_class_and_tags_as_the_engine_wrote_them(
    locale: str,
) -> None:
    # The class, each dimension's status and the trial count's tag, as stored before
    # and after this branch: only words change.
    expected = {
        "ten": ("C", "WEAK", "DECLARED"),
        "one": ("B", "PASS", "DECLARED"),
        "undeclared": ("B", "NOT_MEASURED", "NOT_MEASURED"),
    }
    for trials, (overall, status, tag) in expected.items():
        data = _fund(locale, trials, None)
        assert report.report_kind(data) == "fund"
        assert data["verdict"]["overall"] == overall
        statuses = {d["name"]: d["status"] for d in data["verdict"]["dimensions"]}
        assert statuses == {
            "statistical_significance": "PASS",
            "multiplicity": status,
            "costs": "NOT_MEASURED",
            "out_of_sample": "NOT_MEASURED",
            "data_quality": "WEAK",
            "benchmark": "PASS",
        }
        assert data["multiplicity"]["trials_used"]["evidence"] == tag
        assert data["multiplicity"]["observed_across_variants"]["note"] == NO_VARIANTS
        assert data["cscv"] == {"status": "NOT_MEASURED", "reason": NO_VARIANTS}
        assert data["luck"]["counted"] is (trials == "ten")
        # A declared voice changes no figure, no class and no tag.
        fund, index = _pair()
        voiced = _run(_dated(fund, index), locale, ownership="provider", **TRIALS[trials])
        stored = voiced.model_dump(mode="json")  # type: ignore[attr-defined]
        for key in ("verdict", "multiplicity", "luck", "cscv", "performance", "significance"):
            assert stored[key] == data[key], key


# 1 · a fund's report speaks of portfolios, strategies or variants ----------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trials", list(TRIALS))
def test_a_funds_report_names_its_trials_in_every_voice(
    locale: str, role: str | None, trials: str
) -> None:
    labels = _labels(locale, role)
    text = _visible(_fund_page(locale, trials, role))
    # The dimension, the luck section and the detail count what a fund has.
    assert DIMENSION_TITLES_FUND[locale]["multiplicity"] in text
    assert labels["luck_intro_fund"] in text
    assert labels["variance_policy_fund"] in text
    assert f"{KEY_LABELS[locale]['observed_across_fund_variants']} — " in text
    # None of the backtest's texts the brief found, no optimiser, no robot.
    for phrase in _backtest_words(locale, role):
        assert phrase not in text, phrase
    assert not NOT_A_FUND.search(text), NOT_A_FUND.search(text)
    assert not FUNDS_OF_THE_MANAGER.search(text), FUNDS_OF_THE_MANAGER.search(text)
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_the_luck_section_of_a_fund_counts_what_was_evaluated(
    locale: str, role: str | None
) -> None:
    labels = _labels(locale, role)
    voice = _voice(role)
    # Nothing counted (one trial, or none declared): the table and how to count them.
    for trials in ("one", "undeclared"):
        data = _fund(locale, trials, role)
        section = _visible(
            report._luck_html(data["luck"], locale, labels, data["multiplicity"], fund=True)
        )
        uncounted = labels["luck_uncounted_fund"]
        assert uncounted in section and labels["luck_uncounted"] not in section
        if voice != ownership.BUYER:
            assert uncounted == ownership.LABELS["luck_uncounted_fund"][voice][locale]
        # Declared at upload or measured from the variants matrix, its return columns.
        assert EVALUATED[locale] in uncounted
        assert MATRIX[locale] in uncounted and RETURN_COLUMNS[locale] in uncounted
        assert labels["luck_table_trials_fund"] in section
        assert labels["luck_table_trials"] not in section
        # The sources' note names the history's minimum length, as an account's does.
        assert labels["luck_note_account"] in section
        assert localize(LUCK_NOTE, locale) not in section
        assert not NOT_A_FUND.search(section), NOT_A_FUND.search(section)
        assert find_claims(section) == []
    # Ten declared: the luck of ten portfolios, strategies or variants, in figures.
    data = _fund(locale, "ten", role)
    luck = data["luck"]
    section = _visible(
        report._luck_html(data["luck"], locale, labels, data["multiplicity"], fund=True)
    )
    n, sharpe = f"{int(luck['trials']):,}", f"{float(luck['sharpe']['value']):.2f}"
    assert n == "10"
    assert labels["luck_sharpe_fund"].format(n=n, sharpe=sharpe) in section
    assert labels["luck_after_fund"].format(n=n) in section
    assert f"{float(luck['luck_sharpe']['value']):.2f}" in section
    assert not NOT_A_FUND.search(section), NOT_A_FUND.search(section)
    # The name it gives the dimension is the dimension's.
    assert DIMENSION_TITLES_FUND[locale]["multiplicity"] in labels["luck_intro_fund"]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trials", list(TRIALS))
def test_the_multiplicity_dimension_of_a_fund_is_named_and_explained_as_a_funds(
    locale: str, role: str | None, trials: str
) -> None:
    data = _fund(locale, trials, role)
    labels = _labels(locale, role)
    voice = _voice(role)
    name = DIMENSION_TITLES_FUND[locale]["multiplicity"]
    assert report._dimension_title("multiplicity", locale, fund=True) == name
    # "What it means for you", the reasons table and the PDF's cover.
    cards = _visible(report._meaning_html(data["verdict"], locale, fund=True, role=voice))
    reasons = _visible(report._reasons_html(data["verdict"], locale, labels, data))
    cover = _visible(report._pdf_cover(data, data["verdict"], labels))
    for part in (cards, reasons, cover):
        assert name in part and DIMENSION_TITLES[locale]["multiplicity"] not in part
        assert not NOT_A_FUND.search(part), NOT_A_FUND.search(part)
    # The card's sentence counts what was evaluated, in the voice declared.
    dimension = _multiplicity(data)
    undeclared = verdict_lib.trials_undeclared(dimension.get("inputs"))
    meaning = ownership.meaning(
        "multiplicity", dimension["status"], locale, voice, fund=True, undeclared=undeclared
    ) or verdict_lib.meaning(
        "multiplicity", dimension["status"], locale, fund=True, undeclared=undeclared
    )
    assert meaning in cards
    assert EVALUATED_ANY[locale].search(meaning), meaning
    assert not FUNDS_OF_THE_MANAGER.search(meaning), meaning
    # The verdict's sentence says the same.
    summary = data["verdict"]["summary"]
    assert not NOT_A_FUND.search(summary) and not FUNDS_OF_THE_MANAGER.search(summary)
    if trials != "one":
        assert EVALUATED[locale] in summary
    assert find_claims(cards + reasons + cover) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trials", ["ten", "undeclared"])
def test_the_plan_of_a_fund_asks_for_what_was_evaluated_or_the_variants_matrix(
    locale: str, role: str | None, trials: str
) -> None:
    data = _fund(locale, trials, role)
    voice = _voice(role)
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    actions = " ".join(step.actions)
    # The title, the finding and the actions count the portfolios, strategies or variants.
    assert EVALUATED_ANY[locale].search(step.title), step.title
    assert EVALUATED[locale] in step.finding + actions
    # The number is declared at upload or measured from the variants matrix.
    assert MATRIX[locale] in actions and RETURN_COLUMNS[locale] in actions
    key = "fund_trials_undeclared" if trials == "undeclared" else "fund_trials"
    if voice != ownership.BUYER:
        assert step.actions == [ownership.PLAN[key][voice][locale]]
        assert step.title == ownership.PLAN["title_fund_multiplicity"][voice][locale]
    else:
        assert step.title == plan_lib.FUND_TITLES[locale]["multiplicity"]
    for text in (step.title, step.finding, actions):
        assert not NOT_A_FUND.search(text), NOT_A_FUND.search(text)
        assert not FUNDS_OF_THE_MANAGER.search(text), FUNDS_OF_THE_MANAGER.search(text)
        assert find_claims(text) == []
    # The page shows that step.
    page = _visible(_fund_page(locale, trials, role))
    assert step.title in page and step.actions[0] in page


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_a_count_from_the_variants_matrix_says_so_in_the_funds_plan(
    locale: str, role: str | None
) -> None:
    # The sample review uploads the variants: the count is measured from the matrix.
    data = _with_role(_institutional(locale).model_dump(mode="json"), role)
    assert data["multiplicity"]["trials_used"]["evidence"] == "MEASURED"
    assert data["multiplicity"]["trials_used"]["note"] == _matrix_note()
    voice = _voice(role)
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    if voice != ownership.BUYER:
        assert step.actions == [ownership.PLAN["fund_trials_counted"][voice][locale]]
    actions = " ".join(step.actions)
    assert MATRIX[locale] in actions and EVALUATED_ANY[locale].search(actions)
    assert not NOT_A_FUND.search(actions) and find_claims(actions) == []
    # A declared count of a fund still asks for the declaration or the matrix.
    declared_step = next(
        s
        for s in improvement_plan(_fund(locale, "ten", role), locale)
        if s.dimension == "multiplicity"
    )
    assert declared_step.actions != step.actions


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_the_technical_detail_of_a_fund_names_its_variants_matrix(
    locale: str, role: str | None
) -> None:
    labels = _labels(locale, role)
    key_labels = KEY_LABELS[locale]
    text = _visible(_fund_page(locale, "ten", role))
    # The row of the variance across the variants, its note and the variance policy.
    assert f"{key_labels['observed_across_fund_variants']} — " in text
    assert labels["no_variants_fund"] in text and labels["variance_policy_fund"] in text
    assert EVALUATED[locale] in labels["no_variants_fund"] and MATRIX[locale] in text
    # The CSCV row and the "not measured" list say the same.
    assert f"{labels['cscv']} {_sentence_case(labels['no_variants_fund'])}." in text
    for phrase in (
        key_labels["observed_across_variants"],
        labels["variance_policy"],
        report._localized_reason(NO_VARIANTS, locale),
    ):
        assert phrase not in text, phrase
    # The stored result is unchanged.
    data = _fund(locale, "ten", role)
    assert data["multiplicity"]["observed_across_variants"]["note"] == NO_VARIANTS
    assert data["cscv"]["reason"] == NO_VARIANTS


def _variants(fund: np.ndarray, columns: int) -> bytes:
    """A variants matrix for ``fund``'s months: its own column and ``columns - 1`` others."""
    rng = np.random.default_rng(5)
    stamps = pd.date_range("2016-01-31", periods=len(fund), freq="ME")
    series = [fund] + [0.5 * fund + rng.normal(0.0, 0.02, len(fund)) for _ in range(columns - 1)]
    rows = [
        f"{stamp.date()}," + ",".join(f"{column[i]:.6f}" for column in series)
        for i, stamp in enumerate(stamps)
    ]
    head = "date," + ",".join(f"v{i}" for i in range(columns))
    return (head + "\n" + "\n".join(rows) + "\n").encode()


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_a_fund_that_declares_fewer_than_its_matrix_is_asked_in_its_words(
    locale: str, role: str | None
) -> None:
    fund = np.random.default_rng(4).normal(0.002, 0.03, 60)
    extra: dict[str, Any] = {"ownership": role} if role else {}
    inputs = build_inputs(
        _dated(fund),
        DeclaredMetadata(locale=locale, trials=2, **extra),
        variants_bytes=_variants(fund, 12),
    )
    data = run_audit(inputs, bootstrap_samples=60).model_dump(mode="json")
    assert report.report_kind(data) == "fund"
    codes = {flag["code"] for flag in data["red_flags"]}
    assert "TRIALS_BELOW_VARIANTS" in codes
    assert data["multiplicity"]["trials_used"]["value"] == 12
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "data_quality")
    hint = plan_lib.FUND_FLAG_HINTS["TRIALS_BELOW_VARIANTS"][locale]
    assert any(action.endswith(hint) for action in step.actions), step.actions
    assert plan_lib.FLAG_HINTS["TRIALS_BELOW_VARIANTS"][locale] not in " ".join(step.actions)
    assert EVALUATED[locale] in hint and MATRIX[locale] in hint
    # Its multiplicity step counts the same portfolios, strategies or variants.
    multiplicity = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    assert EVALUATED[locale] in " ".join(multiplicity.actions)
    for text in (hint, *multiplicity.actions):
        assert not NOT_A_FUND.search(text) and find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_an_uploaded_matrix_keeps_its_figures_under_the_funds_name(locale: str) -> None:
    labels = LABELS[locale]
    rows = {"observed_across_variants": measured(0.0025, "variance across 10 variants")}
    shown = report._fund_multiplicity_rows(rows, labels)
    assert shown == {"observed_across_fund_variants": rows["observed_across_variants"]}
    measured_cscv = {"status": "MEASURED", "pbo": measured(0.2)}
    assert report._fund_cscv(measured_cscv, labels) == measured_cscv
    assert report._fund_cscv({"status": "NOT_MEASURED", "reason": NO_VARIANTS}, labels) == {
        "status": "NOT_MEASURED",
        "reason": labels["no_variants_fund"],
    }
    # The sample review's matrix: its measured row under the fund's name.
    data = _institutional(locale).model_dump(mode="json")
    observed = data["multiplicity"]["observed_across_variants"]
    assert observed["evidence"] == "MEASURED"
    text = _visible(render_html(_institutional(locale), watermark=False, locale=locale))
    assert f"{KEY_LABELS[locale]['observed_across_fund_variants']} " in text
    assert KEY_LABELS[locale]["observed_across_variants"] not in text


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_the_paid_preview_of_a_fund_counts_what_was_evaluated(
    locale: str, role: str | None
) -> None:
    page = _fund_preview(locale, "ten", role)
    text = _visible(page)
    assert LABELS[locale]["title_fund"] in page and LABELS[locale]["locked_intro"] in text
    items = _lockbox(page)
    gain = LOCKED_GAINS_FUND[locale]["multiplicity"]
    assert gain in items and LOCKED_GAINS[locale]["multiplicity"] not in items
    assert EVALUATED[locale] in gain
    assert DIMENSION_TITLES_FUND[locale]["multiplicity"] in text
    assert not NOT_A_FUND.search(text), NOT_A_FUND.search(text)
    assert find_claims(text) == []
    # With the variants matrix the CSCV is on offer, in the fund's words.
    sample = render_html(
        AuditResult.model_validate(
            _with_role(_institutional(locale).model_dump(mode="json"), role)
        ),
        watermark=True,
        free_mode=False,
        locale=locale,
    )
    offered = _lockbox(sample)
    assert LOCKED_GAINS_FUND[locale]["cscv"] in offered
    assert LOCKED_GAINS[locale]["cscv"] not in offered
    assert not NOT_A_FUND.search(_visible(sample)), NOT_A_FUND.search(_visible(sample))


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("trials", ["ten", "undeclared"])
def test_the_message_for_the_manager_names_the_funds_dimension(locale: str, trials: str) -> None:
    data = _fund(locale, trials, ownership.BUYER)
    words = seller_message.words(locale)
    text, _, _ = report._seller_message(data, locale, LABELS[locale])
    name = DIMENSION_TITLES_FUND[locale]["multiplicity"]
    assert text.startswith(words["hello_fund"])
    line = words["dimensions_weak"] if trials == "ten" else words["unmeasured"]
    assert line.split("{items}")[0] + name in text
    assert DIMENSION_TITLES[locale]["multiplicity"] not in text
    assert not NOT_A_FUND.search(text), NOT_A_FUND.search(text)
    assert find_claims(text) == []
    # The page carries it under the questions.
    assert html.escape(name) in report._seller_html(data, locale, LABELS[locale])


@pytest.mark.parametrize("locale", LOCALES)
def test_the_public_page_of_a_fund_names_its_dimension_as_the_report(locale: str) -> None:
    from quant_trade.audit.pages import verification_page

    for trials in TRIALS:
        data = _fund(locale, trials, None)
        page = _visible(
            verification_page(
                data,
                public_id="fondo1",
                published_at="2026-10-10T00:00:00Z",
                result_sha256="0" * 64,
                base_url="https://audit.example",
                locale=locale,
            )
        )
        name = DIMENSION_TITLES_FUND[locale]["multiplicity"]
        assert name in page and DIMENSION_TITLES[locale]["multiplicity"] not in page
        dimension = _multiplicity(data)
        meaning = verdict_lib.meaning(
            "multiplicity",
            dimension["status"],
            locale,
            fund=True,
            undeclared=verdict_lib.trials_undeclared(dimension.get("inputs")),
        )
        assert meaning in page
        assert not NOT_A_FUND.search(meaning) and not FUNDS_OF_THE_MANAGER.search(meaning)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_comparison_names_the_dimension_by_the_kinds_of_report_it_shows(locale: str) -> None:
    from quant_trade.audit.compare import comparison_body

    fund = _fund(locale, "ten", None)
    signal = _signal(locale).model_dump(mode="json")
    backtest = _backtest(locale).model_dump(mode="json")
    fund_name = DIMENSION_TITLES_FUND[locale]["multiplicity"]
    account_name = DIMENSION_TITLES_ACCOUNT[locale]["multiplicity"]
    mixed_name = DIMENSION_TITLES_MIXED[locale]["multiplicity"]
    backtest_name = DIMENSION_TITLES[locale]["multiplicity"]
    for pair, name in (
        ((fund, fund), fund_name),
        ((fund, backtest), mixed_name),
        ((backtest, fund), mixed_name),
        ((fund, signal), mixed_name),
        # An account or signal and a backtest read as after PR 489.
        ((signal, signal), account_name),
        ((signal, backtest), mixed_name),
        ((backtest, backtest), backtest_name),
    ):
        assert report.shared_dimension_title("multiplicity", locale, pair) == name
        body = comparison_body(list(pair), hrefs=["/a", "/b"], locale=locale)
        assert f"<tr><td>{html.escape(name)}</td>" in body, (name, locale)


# 2 · the sample review's notes name what its fund report names ---------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_institutional_notes_name_the_dimension_and_trials_as_the_fund_report(
    locale: str,
) -> None:
    result = _institutional(locale)
    data = result.model_dump(mode="json")
    assert report.report_kind(data) == "fund"
    words = institutional_sample.COPY[locale]
    notes = _visible(
        "".join(body for _, body in institutional_sample.notes_sections(result, locale))
    )
    page = _visible(institutional_sample.report_with_notes(result, locale=locale))
    report_only = _visible(render_html(result, watermark=False, locale=locale))
    figures = institutional_sample.note_figures(data)
    n = figures["trials"].shown
    assert n == str(institutional_sample.VARIANTS) == "10"
    # The dimension, under the fund report's own name, in the notes' table and the report.
    name = DIMENSION_TITLES_FUND[locale]["multiplicity"]
    assert name in notes and name in report_only
    backtest_name = DIMENSION_TITLES[locale]["multiplicity"]
    assert backtest_name not in notes and backtest_name not in page
    # The luck of the ten variants: the notes' name is the report's, with the same figure.
    labels = ownership.labels_for(LABELS[locale], locale, ownership.role_of(data))
    luck = data["luck"]
    sharpe = f"{float(luck['sharpe']['value']):.2f}"
    in_report = labels["luck_sharpe_fund"].format(n=n, sharpe=sharpe)
    in_notes = words["figures"]["luck_sharpe"][0].format(trials=n)
    assert in_report.startswith(in_notes)
    assert in_notes in notes and in_report in report_only
    chance = f"{float(luck['luck_sharpe']['value']):.2f}"
    assert figures["luck_sharpe"].shown == chance
    assert f"{in_notes} {chance}" in notes and chance in report_only
    # The deflated Sharpe is the figure the report quotes, at the same count and under
    # the same name: its trials, which are the portfolios, strategies or variants evaluated.
    dsr = words["figures"]["dsr"][0].format(trials=n)
    assert f"{n} {TRIAL_WORD[locale]} (" in dsr and EVALUATED[locale] in dsr
    assert f"{dsr} {figures['dsr'].shown}" in notes
    assert f"DSR {figures['dsr'].shown}" in report_only
    # The variants file is the variants matrix, one return column each, as the report's
    # trial count says it ("columns of the uploaded variants matrix").
    variants = words["reviewed"]["variants"].format(
        variants=institutional_sample.VARIANTS, trials=n
    )
    assert variants in notes and MATRIX[locale] in variants and EVALUATED[locale] in variants
    assert localize(_matrix_note(), locale) in report_only
    # The notes' question for the dimension counts what the dimension counts.
    assert EVALUATED[locale] in words["questions"]["multiplicity"]
    for text in (notes, report_only):
        assert not NOT_A_FUND.search(text), NOT_A_FUND.search(text)
        assert not FUNDS_OF_THE_MANAGER.search(text), FUNDS_OF_THE_MANAGER.search(text)
    assert find_claims(notes) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_institutional_notes_keep_every_figure_of_the_report(locale: str) -> None:
    result = _institutional(locale)
    data = result.model_dump(mode="json")
    figures = institutional_sample.note_figures(data)
    notes = _visible(
        "".join(body for _, body in institutional_sample.notes_sections(result, locale))
    )
    for figure in figures.values():
        assert figure.shown in notes, figure.key
    # The class is the report's, and every figure the notes quote is measured.
    assert data["verdict"]["overall"] == "C"
    assert all(figure.evidence == "MEASURED" for figure in figures.values())
    assert {d["name"]: d["status"] for d in data["verdict"]["dimensions"]}["multiplicity"] == (
        "WEAK"
    )


# 3 · a backtest keeps its words, an account or signal those of PR 489 --------------------


def _fund_texts(locale: str) -> list[str]:
    labels = LABELS[locale]
    return [
        DIMENSION_TITLES_FUND[locale]["multiplicity"],
        labels["luck_intro_fund"],
        labels["luck_uncounted_fund"],
        labels["luck_table_trials_fund"],
        labels["variance_policy_fund"],
        labels["no_variants_fund"],
        KEY_LABELS[locale]["observed_across_fund_variants"],
        *LOCKED_GAINS_FUND[locale].values(),
    ]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_a_backtest_and_a_signal_keep_their_words(locale: str, role: str | None) -> None:
    labels = _labels(locale, role)
    backtest = _with_role(_backtest(locale).model_dump(mode="json"), role)
    page = _visible(
        render_html(AuditResult.model_validate(backtest), watermark=False, locale=locale)
    )
    # The backtest: configurations tried, its variants and its luck, as on main.
    assert DIMENSION_TITLES[locale]["multiplicity"] in page
    assert labels["luck_intro"] in page and labels["variance_policy"] in page
    assert f"{KEY_LABELS[locale]['observed_across_variants']} " in page
    for text in _fund_texts(locale):
        assert text not in page, text
    preview = render_html(
        AuditResult.model_validate(backtest), watermark=True, free_mode=False, locale=locale
    )
    items = _lockbox(preview)
    assert LOCKED_GAINS[locale]["multiplicity"] in items
    assert LOCKED_GAINS_FUND[locale]["multiplicity"] not in items
    # The signal: the accounts or signals behind it, as PR 489 left it.
    signal = _with_role(_signal(locale).model_dump(mode="json"), role)
    page = _visible(render_html(AuditResult.model_validate(signal), watermark=False, locale=locale))
    assert DIMENSION_TITLES_ACCOUNT[locale]["multiplicity"] in page
    assert labels["luck_intro_account"] in page and labels["variance_policy_account"] in page
    for text in _fund_texts(locale):
        assert text not in page, text
    preview = render_html(
        AuditResult.model_validate(signal), watermark=True, free_mode=False, locale=locale
    )
    items = _lockbox(preview)
    assert LOCKED_GAINS_ACCOUNT[locale]["multiplicity"] in items
    assert LOCKED_GAINS_FUND[locale]["multiplicity"] not in items


@pytest.mark.parametrize("locale", LOCALES)
def test_the_backtest_and_account_texts_are_the_ones_on_main(locale: str) -> None:
    # The texts this branch reads beside the fund's own: unchanged words.
    backtest = {
        "es": "Número de configuraciones probadas",
        "en": "Number of settings tried",
        "pt": "Número de configurações testadas",
    }
    assert DIMENSION_TITLES[locale]["multiplicity"] == backtest[locale]
    account = {
        "es": "Número de cuentas o señales detrás de esta",
        "en": "Number of accounts or signals behind it",
        "pt": "Número de contas ou sinais por trás desta",
    }
    assert DIMENSION_TITLES_ACCOUNT[locale]["multiplicity"] == account[locale]
    # A backtest's and an account's luck, meaning and plan do not read the fund's texts.
    assert "configura" in LABELS[locale]["luck_intro"].lower()
    for status in ("WEAK", "PASS", "FAIL"):
        assert EVALUATED[locale] not in verdict_lib.meaning("multiplicity", status, locale)
    for key in ("multiplicity.WEAK", "multiplicity.NOT_MEASURED"):
        name, status = key.split(".")
        assert EVALUATED[locale] not in verdict_lib.meaning(name, status, locale, account=True)


# 4 · the branch's review: the flag, one name per count, the CSCV, a matrix uploaded ------


@cache
def _matrix_note() -> str:
    """The engine's note on a trial count read from an uploaded variants matrix."""
    fund, index = _pair()
    inputs = build_inputs(
        _dated(fund, index),
        DeclaredMetadata(trials_declared=False),
        variants_bytes=_variants(fund, 12),
    )
    count, evidence, note = engine.trial_count(inputs)
    assert (count, evidence) == (12, "MEASURED")
    return note


@cache
def _fund_matrix_result(locale: str, trials: int, columns: int = 12) -> AuditResult:
    """The fixture's fund (its Benchmark column included) with ``trials`` declared and
    a variants matrix of ``columns`` return columns."""
    fund, index = _pair()
    inputs = build_inputs(
        _dated(fund, index),
        DeclaredMetadata(locale=locale, trials=trials),
        variants_bytes=_variants(fund, columns),
    )
    return run_audit(inputs, bootstrap_samples=60)


def _fund_matrix(locale: str, trials: int, role: str | None) -> dict[str, Any]:
    return _with_role(_fund_matrix_result(locale, trials).model_dump(mode="json"), role)


def _flag_cards(page: str, code: str) -> list[str]:
    """The visible text of every red flag card ``code`` on ``page`` (the free summary
    lists the title alone; the full section adds the detail)."""
    cards = re.findall(r"<li>(?:(?!</li>).)*?</li>", page, re.S)
    return [_visible(card) for card in cards if f"<p class='flag-code'>{code}</p>" in card]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("trials", [5, 1])
def test_a_funds_flag_of_fewer_trials_than_its_matrix_counts_what_was_evaluated(
    locale: str, role: str | None, trials: int
) -> None:
    data = _fund_matrix(locale, trials, role)
    assert report.report_kind(data) == "fund"
    flag = next(f for f in data["red_flags"] if f["code"] == "TRIALS_BELOW_VARIANTS")
    # The stored flag is the engine's, as before this branch.
    assert flag["value"] == 12
    assert flag["detail"] == (
        f"{trials} trial(s) declared but the files show 12 variants or optimisation passes; "
        "the declared count is too low"
    )
    labels = LABELS[locale]
    key = "flag_trials_below_variants_fund" + ("_one" if trials == 1 else "")
    expected = labels[key].format(n=str(trials), m="12")
    full = render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
    for page in (full, pdf_lib._expand_details_for_pdf(full)):
        cards = _flag_cards(page, "TRIALS_BELOW_VARIANTS")
        detailed = [card for card in cards if f"{expected}." in card]
        assert len(detailed) == 1, cards
        assert EVALUATED_ANY[locale].search(detailed[0]) and MATRIX[locale] in detailed[0]
        for card in cards:
            assert not re.search(r"\bpasses\b", card), card
        text = _visible(page)
        assert not PASSES.search(text), PASSES.search(text)
        assert localize(flag["detail"], locale) not in text
        assert find_claims(text) == []
    # Off a fund's page the flag keeps the engine's words.
    shown = report._flag_detail(flag, data, labels, locale)
    assert shown == localize(flag["detail"], locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_notes_and_the_fund_report_name_each_count_alike(locale: str) -> None:
    result = _institutional(locale)
    data = result.model_dump(mode="json")
    labels = ownership.labels_for(LABELS[locale], locale, ownership.role_of(data))
    words, word, more = institutional_sample.COPY[locale], TRIAL_WORD[locale], OR_MORE[locale]
    n = institutional_sample.note_figures(data)["trials"].shown
    half = f"{int(data['multiplicity']['trials_to_half']['value']):,}"
    assert (n, half) == ("10", "512")
    # A fund's noun never names the ten or the 512 by itself where the DSR is shown.
    loose = re.compile(rf"\b(?:{n}|{half})(?: {more})? {FUND_NOUN[locale]}", re.I)
    # The notes: the deflated Sharpe at the ten trials, glossed as what a fund evaluates.
    label, description = (part.format(**_note_values(data)) for part in words["figures"]["dsr"])
    notes = _visible(institutional_sample.sample_page(result, locale=locale))
    assert f"{n} {word} (" in label and EVALUATED[locale] in label and label in notes
    assert f"{n} {word}" in description
    # The reasons table.
    reasons = _visible(report._reasons_html(data["verdict"], locale, labels, data))
    row = reasons.split(DIMENSION_TITLES_FUND[locale]["multiplicity"], 1)[1]
    assert f"{n} {word}" in row.split(report._dimension_title("costs", locale), 1)[0]
    # The plan: the ten and the 512, both trials.
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    assert f"{n} {word};" in step.finding and f"{half} {more} {word} (" in step.finding
    # The technical detail.
    rows = report._fund_multiplicity_rows(
        report._one_dsr_row(data["multiplicity"], data["declared"]), labels
    )
    detail = _visible(report._evidence_rows(rows, labels, skip={"sensitivity"}))
    assert f"{KEY_LABELS[locale]['trials_to_half']} {half}" in detail
    assert word in KEY_LABELS[locale]["trials_to_half"].lower()
    # The report and the report with the notes on top (the PDF's source), every section open.
    for with_notes in (False, True):
        page = (
            institutional_sample.report_with_notes(result, locale=locale)
            if with_notes
            else render_html(result, watermark=False, locale=locale)
        )
        text = _visible(pdf_lib._expand_details_for_pdf(page))
        assert f"{labels['trials_used']}: {n}" in text and step.finding in text
        assert (label in text) is with_notes
    for part in (label, description, row, step.finding, detail):
        assert not loose.search(part), (loose.search(part), part)
        assert find_claims(part) == []


def _note_values(data: dict[str, Any]) -> dict[str, Any]:
    return institutional_sample._values(data, institutional_sample.note_figures(data))


@pytest.mark.parametrize("locale", LOCALES)
def test_the_cscv_counts_of_a_fund_name_what_they_count(locale: str) -> None:
    names = CSCV_COUNTS_FUND[locale]
    for result in (_institutional(locale), _fund_matrix_result(locale, 5)):
        data = result.model_dump(mode="json")
        cscv = data["cscv"]
        assert report.report_kind(data) == "fund" and cscv["status"] == "MEASURED"
        expected = ", ".join(
            f"{names[key]}: {cscv[key]}"
            for key in (
                "parameter_variants",
                "effective_variants",
                "partitions",
                "combinations",
                "observations_used",
            )
        )
        assert expected.startswith(f"{names['parameter_variants']}: {cscv['parameter_variants']}")
        full = render_html(result, watermark=False, locale=locale)
        pages = [full, pdf_lib._expand_details_for_pdf(full)]
        if result is _institutional(locale):
            pages.append(institutional_sample.report_with_notes(result, locale=locale))
        for page in pages:
            text = _visible(page)
            assert expected in text
            for key in ("parameter_variants", "effective_variants", "observations_used"):
                assert key not in text, key
            assert "partitions=" not in text and "combinations=" not in text
            assert find_claims(text) == []
    # A backtest keeps the stored keys, as on main.
    cscv = {"status": "MEASURED", "partitions": 8, "combinations": 70, "parameter_variants": 4}
    assert report._cscv_counts(cscv, locale) == (
        "partitions=8, combinations=70, parameter_variants=4"
    )


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", ROLES)
def test_a_fund_that_declares_more_than_its_matrix_is_not_asked_to_upload_it(
    locale: str, role: str | None
) -> None:
    data = _fund_matrix(locale, 20, role)
    trials = data["multiplicity"]["trials_used"]
    # The declared count is used; the matrix was uploaded and its CSCV measured.
    assert (trials["value"], trials["evidence"]) == (20, "DECLARED")
    assert data["cscv"]["status"] == "MEASURED" and data["cscv"]["parameter_variants"] == 12
    assert "TRIALS_BELOW_VARIANTS" not in {flag["code"] for flag in data["red_flags"]}
    voice = _voice(role)
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    if voice != ownership.BUYER:
        template = ownership.PLAN["fund_trials_beyond_matrix"][voice][locale]
        assert step.actions == [template.format(n="20", m="12")]
    actions = " ".join(step.actions)
    assert MATRIX[locale] in actions and EVALUATED[locale] in actions
    assert "12" in actions and "20" in actions
    # Never the texts that ask for the matrix that is already there.
    for key in ("fund_trials", "fund_trials_counted", "fund_trials_undeclared"):
        for other in ownership.PLAN[key].values():
            assert other[locale] not in step.actions
    upload = re.compile(
        r"sube la matriz|pídele la matriz|aporta la matriz|upload the variants matrix"
        r"|ask them for the variants matrix|provide the variants matrix|envie a matriz"
        r"|peça a ele a matriz|forneça a matriz",
        re.I,
    )
    assert not upload.search(actions), upload.search(actions)
    assert not NOT_A_FUND.search(actions) and find_claims(actions) == []
    page = _visible(
        pdf_lib._expand_details_for_pdf(
            render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
        )
    )
    assert step.actions[0] in page
    # A matrix uploaded whose CSCV could not be measured: its columns are not known.
    unmeasured = copy.deepcopy(data)
    unmeasured["cscv"] = {"status": "NOT_MEASURED", "reason": "too short"}
    assert plan_lib._variants_matrix(unmeasured) == (True, None)
    step = next(s for s in improvement_plan(unmeasured, locale) if s.dimension == "multiplicity")
    fewer = {"es": "menos de 20", "en": "fewer than 20", "pt": "menos de 20"}[locale]
    assert fewer in " ".join(step.actions)
    assert not upload.search(" ".join(step.actions))
    # No matrix at all: the plan still asks for it.
    bare = copy.deepcopy(unmeasured)
    bare["cscv"] = {"status": "NOT_MEASURED", "reason": NO_VARIANTS}
    bare["inputs"]["digests"].pop("variants.csv")
    assert plan_lib._variants_matrix(bare) == (False, None)
    step = next(s for s in improvement_plan(bare, locale) if s.dimension == "multiplicity")
    if voice != ownership.BUYER:
        assert step.actions == [ownership.PLAN["fund_trials"][voice][locale]]


# every new text: three languages, the guard, no robot ------------------------------------


def _new_texts() -> list[tuple[str, str, str]]:
    """(where, locale, text) of every text this branch adds or rewrites."""
    out: list[tuple[str, str, str]] = []
    for locale in LOCALES:
        for text in _fund_texts(locale):
            out.append(("report", locale, text))
        for key in ("luck_narrow_fund", "luck_beats_fund", "luck_below_fund"):
            out.append(("report", locale, LABELS[locale][key]))
        for key in ("luck_sharpe_fund", "luck_after_fund"):
            out.append(("report", locale, LABELS[locale][key]))
        for key in ("flag_trials_below_variants_fund", "flag_trials_below_variants_fund_one"):
            out.append(("flag", locale, LABELS[locale][key]))
        out.append(("cscv", locale, ", ".join(CSCV_COUNTS_FUND[locale].values())))
        out.append(("plan", locale, plan_lib.FUND_TITLES[locale]["multiplicity"]))
        out.append(("hint", locale, plan_lib.FUND_FLAG_HINTS["TRIALS_BELOW_VARIANTS"][locale]))
        for key, text in verdict_lib.MEANING[locale].items():
            if key.startswith("multiplicity.") and key.endswith(".fund"):
                out.append(("meaning", locale, text))
        for key, text in verdict_lib._TEXT[locale].items():
            if key.startswith("multiplicity.") and key.endswith(".fund"):
                out.append(("summary", locale, text))
        words = institutional_sample.COPY[locale]
        out.append(("notes", locale, words["reviewed"]["variants"]))
        out.append(("notes", locale, words["questions"]["multiplicity"]))
        for key in ("dsr", "luck_sharpe", "years_needed", "pbo"):
            out += [("notes", locale, part) for part in words["figures"][key]]
    for table, keys in (
        (ownership.LABELS, ("luck_uncounted_fund",)),
        (
            ownership.MEANING,
            ("multiplicity.WEAK.fund", "multiplicity.WEAK.undeclared.fund"),
        ),
        (
            ownership.PLAN,
            (
                "fund_trials_undeclared",
                "fund_trials",
                "fund_trials_counted",
                "fund_trials_beyond_matrix",
                "title_fund_multiplicity",
            ),
        ),
    ):
        for key in keys:
            for voice in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
                for locale in LOCALES:
                    out.append((f"{key}/{voice}", locale, table[key][voice][locale]))
    return out


def test_every_new_text_exists_in_three_languages_and_passes_the_guard() -> None:
    texts = _new_texts()
    by_where: dict[str, dict[str, list[str]]] = {}
    for where, locale, text in texts:
        assert text, (where, locale)
        assert find_claims(text) == [], (where, text)
        assert not [word for word in BANNED if word in text.lower()], (where, text)
        assert not NOT_A_FUND.search(text), (where, text)
        assert not FUNDS_OF_THE_MANAGER.search(text), (where, text)
        by_where.setdefault(where, {}).setdefault(locale, []).append(text)
    for where, locales in by_where.items():
        assert set(locales) == set(LOCALES), where
        # Spanish and Portuguese are their own, not the English left in place.
        for locale in ("es", "pt"):
            assert locales[locale] != locales["en"], (where, locale)
    # Every fund text that counts trials names what a fund evaluates.
    for locale in LOCALES:
        for key in (
            "luck_intro_fund",
            "luck_uncounted_fund",
            "luck_narrow_fund",
            "luck_beats_fund",
            "luck_below_fund",
            "luck_sharpe_fund",
            "luck_after_fund",
            "variance_policy_fund",
            "no_variants_fund",
        ):
            assert EVALUATED[locale] in LABELS[locale][key], (locale, key)
        assert set(LOCKED_GAINS_FUND[locale]) <= set(LOCKED_GAINS[locale])
        assert set(DIMENSION_TITLES_FUND[locale]) <= set(DIMENSION_TITLES[locale])
