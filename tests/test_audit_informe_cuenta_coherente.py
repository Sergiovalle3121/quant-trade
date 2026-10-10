"""An account or signal report without contradictions (errores 13).

Since 9 Oct the preview needs no account and the full report is paid from the
first one: whoever copies a signal reads the public signal sample before paying,
so every figure it shows twice must read the same both times. Each test reads
the signal sample (``sample.signal_sample_result``) or the backtest sample in
Spanish, English and Portuguese, and checks one contradiction a buyer found:

1. the PSR the plan, the table and the technical detail quote is named, and the
   class's figure is the same one everywhere;
2. the reconciliation shows the floating result the file declares, tagged
   Declared, as the account's section does, and says why it stays out;
3. under a year of history is never rounded up to "12 months";
4. a yearly band below -100 % reads "-100.0% or worse";
5. an account or signal is not spoken of as a robot, in every voice (PR 478);
6. the challenge says first that the open loss already counts against its
   limits, and folds the figures that cannot see it;
7. the two periods say where each comes from;
8. each average win says whether it is net or gross.

The second pass (review of the same branch) adds: a backtest with an account
history uploaded as its real account keeps that account's floating result out
of the backtest's reconciliation and challenge; no "configuration", optimiser
or XML wording in any multiplicity text of an account, in every voice, nor an
optimiser or "same robot" anywhere on its page; the challenge callout never
reads "0%" and names the hidden floating drawdown; the dependence sentence and
the table's note follow the figure the stored class used; "net of fees" only
when both files itemise them.

The fourth pass (review of the third) adds: the recent stretch's question asks
whether the account or signal's settings changed or it was restarted, never
whether a system was reoptimised; the reconciliation keeps its stored tag for
the starting capital; the multiplicity detail and CSCV of an account
name the other accounts or signals, not variants; a comparison names the
dimension by the kinds of report it shows; a stretch under a year never reads
"12.0 months" or "1.0 months"; Portuguese says "fornecedor"; the extreme jumps
hint asks the provider in the buyer's voice; Start and End taken from the
trades say so.

The fifth pass adds: the paid preview of an account or signal (an anonymous
upload with the production settings) lists what the multiplicity section tells
in the account's words, not "the configurations tried"; each starting balance
shows the tag the downloadable JSON stores (the reconciliation's Measured, the
size table's Declared, on the samples and on an uploaded account), and on an
account or signal the size table's 1x line says the file declares it.

No figure, class or tag changes: every test reads the stored result as the
engine wrote it. Nothing reaches the network.
"""

from __future__ import annotations

import copy
import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from quant_trade.audit import analytics, ownership, psr_names, report, seller_message
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit import plan as plan_lib
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.live import compare_live
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.redflags import flag_title
from quant_trade.audit.report import (
    INTEGRITY_TEXT,
    KEY_LABELS,
    LABELS,
    RECON_COVERAGE_VALUES,
    declared_open_value,
    evidence_label,
    platform_label,
    render_html,
    unseen_open_loss,
    unseen_open_loss_warning,
)
from quant_trade.audit.sample import sample_result, signal_sample_result, synthetic_live_statement
from quant_trade.audit.schema import (
    AuditResult,
    DeclaredMetadata,
    ParsedTrades,
    build_inputs,
    declared,
    measured,
    not_measured,
)
from quant_trade.audit.verdict import _TEXT as VERDICT_TEXT
from quant_trade.audit.verdict import meaning as verdict_meaning
from quant_trade.audit.verdict import trials_undeclared
from quant_trade.core.models import Trade

LOCALES = ("es", "en", "pt")
#: The words the brief keeps out of every text.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable")
#: Robot and optimiser words an account or signal's plan steps and meanings must not use.
ROBOT = re.compile(
    r"\b(robot|robô|EA|XML|optimi[sz]ation|optimi[sz]er|optimización|optimizador|otimização|"
    r"otimizador)\b",
    re.I,
)
#: Optimiser words, a reoptimisation, variants and the robot's backtest, anywhere on
#: an account or signal's page.
ROBOT_ANYWHERE = re.compile(
    r"\b(EA|XML|optimi[sz]ation|optimi[sz]er|optimización|optimizador|otimização|otimizador)\b"
    r"|\bre-?optimi\w*|\breotimi\w*|\bvariant\w*"
    r"|same robot|mismo robot|mesmo robô",
    re.I,
)
#: Configurations counted as trials: what an account or signal's multiplicity texts
#: count instead are the accounts or signals behind it ("configuración" alone is
#: the settings a signal keeps or changes, and stays).
CONFIGURATIONS = re.compile(
    r"configuraciones|configurations|configurações|"
    r"\b(una sola|1) configuración|\b(a single|1) configuration|\b(uma única|1) configuração",
    re.I,
)
#: The account wording of the out-of-sample meaning: the account or signal, and the resets.
ACCOUNT_OR_SIGNAL = {"es": "cuenta o señal", "en": "account or signal", "pt": "conta ou sinal"}
RESET = {"es": "reinicios", "en": "reset", "pt": "reinícios"}
NET = {"es": "neta", "en": "net", "pt": "líquido"}
GROSS = {"es": "bruta", "en": "gross", "pt": "bruto"}


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


@cache
def _signal_result(locale: str) -> AuditResult:
    return signal_sample_result(locale, bootstrap_samples=60)


def _signal(locale: str) -> dict[str, Any]:
    """The signal sample's stored result (a fresh copy: tests may change it)."""
    return copy.deepcopy(_signal_result(locale).model_dump(mode="json"))


@cache
def _signal_page(locale: str) -> str:
    return render_html(_signal_result(locale), watermark=False, locale=locale)


@cache
def _backtest_result(locale: str) -> AuditResult:
    return sample_result(locale, bootstrap_samples=60)


def _with_role(data: dict[str, Any], role: str | None) -> dict[str, Any]:
    """``data`` with ``role`` declared as whose strategy it is (None: nothing declared)."""
    shown = copy.deepcopy(data)
    shown["declared"].pop("ownership", None)
    if role:
        shown["declared"]["ownership"] = declared(role)
    return shown


def _statistical(data: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in data["verdict"]["dimensions"] if d["name"] == "statistical_significance")


# 1 · one name per PSR --------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_each_psr_says_which_it_is_with_one_name_in_plan_table_and_detail(locale: str) -> None:
    data = _signal(locale)
    significance = data["significance"]
    plain = significance["psr"]["value"]
    adjusted = significance["dependence"]["psr"]["value"]
    # Two figures for the same history: the plain count (0.687) and the one adjusted
    # for the returns' dependence (0.677), which is the one the class used.
    assert f"{plain:.3f}" != f"{adjusted:.3f}"
    used, track, kind = psr_names.class_psr(data)
    assert used == _statistical(data)["inputs"]["psr"]["value"] == adjusted
    assert kind == psr_names.ADJUSTED
    assert track == significance["dependence"]["min_track_record_length"]["value"]
    name = psr_names.psr_name(psr_names.ADJUSTED, locale)
    plain_name = psr_names.psr_name(psr_names.PLAIN, locale)
    text = _visible(_signal_page(locale))
    # The plan quotes the class's figure under its name ...
    step = next(
        s for s in improvement_plan(data, locale) if s.dimension == "statistical_significance"
    )
    assert step.finding.startswith(f"{name} {adjusted:.3f} ")
    assert step.finding in text
    # ... the technical detail too ...
    assert f"{name} {adjusted:.3f} < 0.8" in text
    # ... and the table shows both, each with the same name.
    keys = KEY_LABELS[locale]
    assert name in keys["psr_dependence"] and plain_name in keys["psr"]
    assert f"{keys['psr_dependence']} {report._table_pct(adjusted)}" in text
    assert f"{keys['psr']} {report._table_pct(plain)}" in text
    # No figure goes by the bare name, and the class is never said to use the plain count.
    assert f"PSR {plain:.3f}" not in text and f"PSR {adjusted:.3f}" not in text
    assert name in LABELS[locale]["dependence_info"]
    assert LABELS[locale]["dependence_info"] in text
    assert localize(psr_names.CLASS_NOTE, locale) in text
    assert LABELS[locale]["dependence_info_plain"] not in text
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_without_a_dependence_figure_the_class_uses_the_plain_count_by_that_name(
    locale: str,
) -> None:
    data = {
        "significance": {
            "status": "MEASURED",
            "observations": measured(300),
            "psr": measured(0.42),
            "min_track_record_length": measured(900.0),
            "dependence": {"psr": not_measured("observed Sharpe <= 0")},
        },
        "verdict": {
            "dimensions": [{"name": "statistical_significance", "inputs": {"psr": measured(0.42)}}]
        },
    }
    assert psr_names.class_psr(data) == (0.42, 900.0, psr_names.PLAIN)
    name = psr_names.psr_name(psr_names.PLAIN, locale)
    assert report._class_psr_reason("PSR 0.420 < 0.8", data, locale) == f"{name} 0.420 < 0.8"
    # A result stored without the dimension's input still names the lower figure.
    data["verdict"] = {}
    data["significance"]["dependence"]["psr"] = measured(0.40)
    assert psr_names.class_psr(data)[0] == 0.40
    assert psr_names.class_psr(data)[2] == psr_names.ADJUSTED


# 2 · the floating result, once ----------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_reconciliation_shows_the_floating_result_the_account_section_shows(
    locale: str,
) -> None:
    data = _signal(locale)
    floating = data["account"]["floating_pnl"]
    assert floating["evidence"] == "DECLARED" and floating["value"] < 0
    recon = data["reconciliation"]
    # The engine values no open position: its expected balance counts closed trades only.
    assert recon["open_position_value"]["evidence"] == "NOT_MEASURED"
    assert declared_open_value(data) == floating
    copy_ = INTEGRITY_TEXT[locale]
    amount = f"{floating['value']:,.2f}"
    tag = evidence_label("DECLARED", locale)
    text = _visible(_signal_page(locale))
    assert f"{copy_['recon_open']} {amount} {tag}" in text
    assert f"{copy_['recon_open']} — " not in text
    note = localize(floating["note"], locale).rstrip(".")
    assert f"{copy_['recon_open']}: {note}. {copy_['recon_open_not_added']}" in text
    assert copy_["recon_open_declared"].format(value=amount) in text
    # The same figure and tag as the account's section; the reconciliation's own
    # figures are as stored.
    assert f"{KEY_LABELS[locale]['floating_pnl']} {amount} {tag}" in text
    expected = f"{recon['expected_final']['value']:,.2f}"
    assert f"{copy_['recon_expected']} {expected}" in text
    assert find_claims(text) == []


def test_a_file_that_declares_no_floating_result_keeps_the_reconciliation_as_it_was() -> None:
    data = _signal("en")
    data["account"]["floating_pnl"] = not_measured("not stated")
    data["inputs"]["report_metadata"].pop("declared_floating_pnl")
    assert declared_open_value(data) is None
    shown = _visible(report._reconciliation_html(data["reconciliation"], "en", None))
    copy_ = INTEGRITY_TEXT["en"]
    assert f"{copy_['recon_open']} — NOT_MEASURED" in shown
    assert copy_["recon_open_not_added"] not in shown


# 3 · under a year is not 12 months ----------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_luck_section_never_rounds_under_a_year_up_to_twelve_months(locale: str) -> None:
    data = _signal(locale)
    luck = data["luck"]
    span = luck["span_years"]["value"]
    assert span < 1
    # The annual return says "under a year of history" for the same file.
    assert data["performance"]["cagr"]["evidence"] == "NOT_MEASURED"
    labels = LABELS[locale]
    sharpe = f"{luck['sharpe']['value']:.2f}"
    text = _visible(_signal_page(locale))
    real = labels["luck_months"].format(n=f"{span * 12:.1f}")
    assert labels["luck_span_line"].format(sharpe=sharpe, span=real) in text
    twelve = labels["luck_span_line"].format(sharpe=sharpe, span=labels["luck_months"].format(n=12))
    assert twelve not in text
    assert localize(data["performance"]["cagr"]["note"], locale) in text
    # A history a day or two short of a year says "almost 12 months".
    luck["span_years"]["value"] = 0.998
    almost = _visible(report._luck_html(luck, locale, labels))
    assert labels["luck_span_line"].format(sharpe=sharpe, span=labels["luck_almost_year"]) in almost
    assert find_claims(almost) == []


# 4 · no yearly figure below -100 % ------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_an_annual_band_below_minus_100_reads_as_minus_100_or_worse(locale: str) -> None:
    data = _signal(locale)
    after = data["mean_shift"]["after"]
    # The band as computed is unchanged: its lower end is below -100 % a year.
    assert after["low"]["value"] < -1
    labels = LABELS[locale]
    floor = labels["shift_floor"].format(pct=report._pct(-1.0, signed=True))
    high = report._pct(after["high"]["value"], signed=True)
    text = _visible(_signal_page(locale))
    assert labels["shift_band"].format(low=floor, high=high) in text
    assert report._pct(after["low"]["value"], signed=True) not in text
    section = _visible(report._shift_html(data["mean_shift"], locale, labels))
    for figure in re.findall(r"-([\d,]+\.\d+)%", section):
        assert float(figure.replace(",", "")) <= 100, figure
    assert find_claims(section) == []


# 5 · an account or signal, not a robot ------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_an_account_report_speaks_of_the_account_or_signal_in_every_voice(
    locale: str, role: str | None
) -> None:
    data = _with_role(_signal(locale), role)
    voice = role or ownership.NEUTRAL
    steps = {step.dimension: step for step in improvement_plan(data, locale)}
    for name in ("multiplicity", "out_of_sample"):
        step = steps[name]
        for text in (step.title, step.finding, *step.actions):
            assert not ROBOT.search(text), (name, text)
            assert name != "multiplicity" or not CONFIGURATIONS.search(text), text
            assert find_claims(text) == []
    # Since when it has traded unchanged, and whether it was reset or replaced.
    oos = ownership.meaning(
        "out_of_sample", "NOT_MEASURED", locale, voice, account=True
    ) or verdict_meaning("out_of_sample", "NOT_MEASURED", locale, account=True)
    assert ACCOUNT_OR_SIGNAL[locale] in oos and RESET[locale] in oos
    assert not ROBOT.search(oos)
    multiplicity = next(d for d in data["verdict"]["dimensions"] if d["name"] == "multiplicity")
    assert multiplicity["status"] == "WEAK"
    undeclared = trials_undeclared(multiplicity["inputs"])
    search = ownership.meaning(
        "multiplicity", "WEAK", locale, voice, account=True, undeclared=undeclared
    ) or verdict_meaning("multiplicity", "WEAK", locale, account=True, undeclared=undeclared)
    assert not ROBOT.search(search) and find_claims(search) == []
    assert not CONFIGURATIONS.search(search)
    labels = ownership.labels_for(LABELS[locale], locale, voice)
    keep = labels["next_keep_account"]
    assert not ROBOT.search(keep)
    # More months of the same account are data its settings were not chosen on.
    significance = steps["statistical_significance"]
    for text in significance.actions:
        assert not ROBOT.search(text), text
    # The luck section counts the accounts or signals behind it, with no XML to upload.
    luck = labels["luck_uncounted_account"]
    assert not ROBOT.search(luck) and not CONFIGURATIONS.search(luck)
    assert ACCOUNT_OR_SIGNAL[locale].split()[0] in luck
    # The header's summary counts the same accounts or signals.
    summary = report._summary_in(data, locale)
    assert not CONFIGURATIONS.search(summary), summary
    page = _visible(render_html(AuditResult.model_validate(data), watermark=False, locale=locale))
    for shown in (oos, search, keep, luck):
        assert shown in page
    if locale != "pt":
        assert data["verdict"]["summary"] in page
        assert not CONFIGURATIONS.search(data["verdict"]["summary"])
    # No optimiser, no XML and no "same robot" anywhere on the page.
    assert not ROBOT_ANYWHERE.search(page), ROBOT_ANYWHERE.search(page)
    if voice != ownership.BUYER:
        # The voice keeps its own wording (PR 478): nobody is sent to a provider.
        assert ownership.PLAN["account_trials"][voice][locale] in steps["multiplicity"].actions
        assert (
            ownership.PLAN["account_oos_backtest"][voice][locale] in steps["out_of_sample"].actions
        )
    assert find_claims(page) == []


# 6 · the challenge sees the open loss first --------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_challenge_says_the_open_loss_counts_first_and_folds_its_figures(
    locale: str,
) -> None:
    data = _signal(locale)
    codes = {flag["code"] for flag in data["red_flags"]}
    assert {"FLOATING_LOSS_AT_END", "HIDDEN_FLOATING_DRAWDOWN"} <= codes
    assert data["inputs"]["balance_only"] and data["challenge"]["status"] == "MEASURED"
    unseen, share = unseen_open_loss(data)
    assert unseen and share == data["account"]["floating_share"]["value"]
    labels = LABELS[locale]
    page = _signal_page(locale)
    section = page.split(f"<h2>{html.escape(labels['challenge'], quote=True)}</h2>")[-1]
    section = section.split("<details open class='detail report-detail'")[0]
    fold = "<details class='unseen-open'>"
    warning = labels["ch_unseen_open"].format(
        share=f"{abs(share):.0%}", tag=evidence_label("DECLARED", locale)
    )
    head = section[: section.index(fold)]
    # The warning comes before any simulated figure: no table and no value cell above it.
    assert html.escape(warning, quote=True) in head
    # The hidden floating drawdown during the history is named right after it.
    assert html.escape(f"{warning} {labels['ch_unseen_hidden_also']}", quote=True) in head
    assert "<table" not in head and "class='vc'" not in head
    # The challenge figures, the sizes and the firms' table sit folded under it.
    assert section.count(fold) == 3
    sizes = (
        f"<h3>{html.escape(labels['ch_size_title'], quote=True)}</h3>"
        f"<p><strong>{html.escape(labels['ch_unseen_sizes'], quote=True)}</strong></p>{fold}"
    )
    firms = (
        f"<h3>{html.escape(labels['ff_title'], quote=True)}</h3>"
        f"<p><strong>{html.escape(labels['ch_unseen_firms'], quote=True)}</strong></p>{fold}"
    )
    assert sizes in section and firms in section
    # The simulator's figures are still there, unchanged, inside the fold.
    shown = report._fmt(data["challenge"]["probability"]["pass"]["value"], key="p50")
    assert f"<span class='vc'>{shown} " in section[section.index(fold) :]
    # The PDF prints them after the warning.
    expanded = pdf_lib._expand_details_for_pdf(page)
    assert fold not in expanded and "<details open class='unseen-open'>" in expanded
    for key in ("ch_unseen_open", "ch_unseen_open_any", "ch_unseen_summary", "ch_unseen_sizes"):
        assert not re.search(r"aprob|aprova|approv", labels[key], re.I), key
    assert find_claims(_visible(section)) == []


def test_a_history_whose_curve_sees_its_open_trades_keeps_its_figures_unfolded() -> None:
    data = _backtest_result("en").model_dump(mode="json")
    assert unseen_open_loss(data) == (False, None)
    assert "unseen-open" not in render_html(_backtest_result("en"), watermark=False, locale="en")
    # A file with open losses only at the end, on a curve with floating results, sees them.
    data["red_flags"] = [{"code": "FLOATING_LOSS_AT_END", "severity": "WARN", "value": -0.2}]
    data["inputs"]["balance_only"] = False
    assert unseen_open_loss(data) == (False, None)
    data["inputs"]["balance_only"] = True
    data["account"] = None
    assert unseen_open_loss(data) == (True, -0.2)


# 7 · two periods, each with its source --------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_two_periods_say_where_each_comes_from(locale: str) -> None:
    data = _signal(locale)
    first = data["inputs"]["first_timestamp"][:10]
    last = data["inputs"]["last_timestamp"][:10]
    start = data["inputs"]["report_metadata"]["start"]
    # The curve starts with the opening deposit; the first trade comes days later.
    assert start != first
    labels = LABELS[locale]
    text = _visible(_signal_page(locale))
    assert f"{labels['data_period']} {first} → {last}" in text
    assert f"{platform_label('start', locale)} {start}" in text
    # A Myfxbook statement gives no period: Rigor took Start and End from its trades.
    assert labels["platform_period_trades"].format(first=first, last=last) in text
    assert labels["platform_period_note"].format(first=first, last=last) not in text
    assert find_claims(labels["platform_period_note"]) == []


# 8 · net or gross ------------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_each_average_win_says_whether_it_is_net_or_gross(locale: str) -> None:
    data = _backtest_result(locale).model_dump(mode="json")
    stats = data["trade_stats"]
    live = data["live"]
    # Fees are itemised per trade: the trade table's averages are before them, the
    # backtest-against-live table's are after them.
    assert "win_rate_gross" in stats
    assert live["fees_itemised"] == {"backtest": True, "live": True}
    net = live["backtest"]["avg_win"]["value"]
    gross = stats["average_win"]["value"]
    assert f"{net:,.2f}" != f"{gross:,.2f}"
    labels, keys = LABELS[locale], KEY_LABELS[locale]
    assert NET[locale] in labels["live_avg_win"] and GROSS[locale] in keys["average_win_gross"]
    text = _visible(_backtest_page(locale))
    shown_live = live["live"]["avg_win"]["value"]
    assert f"{labels['live_avg_win']} {shown_live:,.2f} {net:,.2f}" in text
    assert f"{keys['average_win_gross']} {gross:,.2f}" in text
    loss = stats["average_loss"]["value"]
    assert f"{keys['average_loss_gross']} {loss:,.2f}" in text
    # Neither figure is left under the bare name.
    assert f"{keys['average_win']} {gross:,.2f}" not in text
    assert f"{keys['average_win']} {shown_live:,.2f}" not in text
    assert find_claims(text) == []


# The new texts ---------------------------------------------------------------------------

NEW_LABELS = (
    "luck_almost_year",
    "shift_floor",
    "platform_period_note",
    "next_keep_account",
    "ch_unseen_open",
    "ch_unseen_open_any",
    "ch_unseen_summary",
    "ch_unseen_sizes",
    "ch_unseen_firms",
    "dependence_info",
    "dependence_info_plain",
    "live_avg_win",
    "live_avg_loss",
    "live_avg_win_plain",
    "live_avg_loss_plain",
    "data_period",
    "luck_uncounted_account",
    "ch_unseen_hidden",
    "ch_unseen_hidden_also",
)
NEW_KEYS = (
    "psr",
    "psr_dependence",
    "min_track_record_length",
    "average_win_gross",
    "average_loss_gross",
)
NEW_INTEGRITY = ("recon_open_declared", "recon_open_not_added")
NEW_VOICED = (
    "account_trials",
    "account_trials_undeclared",
    "account_oos_backtest",
    "title_account_multiplicity",
)


def test_every_new_text_exists_in_three_languages_and_passes_the_guard() -> None:
    texts: list[str] = []
    for locale in LOCALES:
        for table, keys in (
            (LABELS, NEW_LABELS),
            (KEY_LABELS, NEW_KEYS),
            (INTEGRITY_TEXT, NEW_INTEGRITY),
        ):
            for key in keys:
                text = table[locale][key]
                if locale != "en":
                    # Translated, not the English left in place.
                    assert text != table["en"][key], (locale, key)
                texts.append(text)
        texts.extend(names[locale] for names in psr_names.NAMES.values())
        for key in NEW_VOICED:
            texts.extend(voices[locale] for voices in ownership.PLAN[key].values())
        for key in (
            "multiplicity.WEAK.account",
            "multiplicity.WEAK.undeclared.account",
            "multiplicity.FAIL.undeclared.account",
            "multiplicity.NOT_MEASURED.undeclared.account",
        ):
            texts.extend(voices[locale] for voices in ownership.MEANING[key].values())
        for key in ("next_keep_account", "luck_uncounted_account"):
            texts.extend(voices[locale] for voices in ownership.LABELS[key].values())
        texts.append(verdict_meaning("multiplicity", "WEAK", locale, account=True))
        for status in ("FAIL", "NOT_MEASURED"):
            texts.append(
                verdict_meaning("multiplicity", status, locale, account=True, undeclared=True)
            )
        for status in ("NOT_MEASURED", "WEAK", "FAIL"):
            texts.append(VERDICT_TEXT[locale][f"multiplicity.{status}.undeclared.account"])
        texts.extend(ownership.QUESTIONS["backtest_match"][locale])
        texts.append(seller_message.SELLER_ASK["backtest_match"][locale])
        texts.append(report._question_text({"code": "backtest_match"}, locale))
        texts.append(localize(psr_names.CLASS_NOTE, locale))
        if locale != "en":
            assert localize(psr_names.CLASS_NOTE, locale) != psr_names.CLASS_NOTE
    for text in texts:
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text


# Second pass ------------------------------------------------------------------------------

#: When the synthetic Myfxbook statement is audited on its own (``_statement_result``).
STATEMENT_NOW = datetime(2026, 10, 8, tzinfo=UTC)


@cache
def _backtest_page(locale: str) -> str:
    return render_html(_backtest_result(locale), watermark=False, locale=locale)


@cache
def _statement_result(locale: str) -> AuditResult:
    """The sample's Myfxbook statement audited alone, with no trial count declared
    and no voice: a failed multiplicity and only the hidden floating drawdown."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(trials_declared=False, locale=locale),
        report_bytes=synthetic_live_statement(),
        report_filename="statement.csv",
        now=STATEMENT_NOW,
    )
    return run_audit(
        inputs, now=STATEMENT_NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=50
    )


def _trades(pnl: list[float], start: datetime, fees: list[float] | None = None) -> ParsedTrades:
    """Closed trades of one unit, one a day, with the costs the file itemises (or none)."""
    rows = [
        Trade(
            entry_time=start + i * timedelta(days=1),
            exit_time=start + i * timedelta(days=1, hours=3),
            quantity=1.0,
            entry_price=1.0,
            exit_price=1.0,
            pnl=value,
            return_pct=0.0,
        )
        for i, value in enumerate(pnl)
    ]
    return ParsedTrades(
        trades=rows, sides=["buy"] * len(rows), client_pnl=list(pnl), invalid_rows=0, fees=fees
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_a_backtests_reconciliation_never_shows_the_live_accounts_floating_result(
    locale: str,
) -> None:
    data = _backtest_result(locale).model_dump(mode="json")
    account = data["account"]
    # The account history uploaded as the real account has its own review, with
    # its own floating result; the tester report declares none.
    assert account["source"] == "live"
    floating = account["floating_pnl"]
    assert floating["evidence"] == "DECLARED" and floating["value"] < 0
    assert not (data["inputs"].get("report_metadata") or {}).get("declared_floating_pnl")
    assert data["reconciliation"]["open_position_value"]["evidence"] == "NOT_MEASURED"
    assert declared_open_value(data) is None
    copy_ = INTEGRITY_TEXT[locale]
    amount = f"{floating['value']:,.2f}"
    text = _visible(_backtest_page(locale))
    # The backtest's reconciliation: not measured, and not valued separately.
    assert f"{copy_['recon_open']} — {evidence_label('NOT_MEASURED', locale)}" in text
    not_valued = RECON_COVERAGE_VALUES["not valued separately"][LOCALES.index(locale)]
    assert f"{copy_['recon_open_coverage']}: {not_valued}" in text
    assert f"{copy_['recon_open']} {amount}" not in text
    assert copy_["recon_open_declared"].format(value=amount) not in text
    assert copy_["recon_open_not_added"] not in text
    # A hidden floating drawdown of the backtest never quotes the real account's share.
    share = f"{abs(account['floating_share']['value']):.0%}"
    data["red_flags"] = [
        *data["red_flags"],
        {"code": "HIDDEN_FLOATING_DRAWDOWN", "severity": "WARN", "value": 2},
    ]
    assert unseen_open_loss(data) == (True, None)
    warning = _visible(unseen_open_loss_warning(data, LABELS[locale]))
    assert LABELS[locale]["ch_unseen_hidden"] in warning and share not in warning
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("status", ["FAIL", "NOT_MEASURED"])
def test_an_account_with_no_count_declared_counts_accounts_not_configurations(
    locale: str, status: str
) -> None:
    data = _signal(locale)
    multiplicity = next(d for d in data["verdict"]["dimensions"] if d["name"] == "multiplicity")
    multiplicity["status"] = status
    assert trials_undeclared(multiplicity["inputs"])
    buyer = verdict_meaning("multiplicity", status, locale, account=True, undeclared=True)
    general = verdict_meaning("multiplicity", status, locale, undeclared=True)
    assert buyer != general
    for voice in ownership.ROLES:
        text = (
            ownership.meaning("multiplicity", status, locale, voice, account=True, undeclared=True)
            or buyer
        )
        assert ACCOUNT_OR_SIGNAL[locale].split()[0] in text
        assert not CONFIGURATIONS.search(text) and not ROBOT.search(text), text
        shown = _visible(report._meaning_html(data["verdict"], locale, account=True, role=voice))
        assert text in shown and general not in shown
        assert find_claims(text) == []
    # The header's summary counts the same accounts or signals.
    summary = report._summary_in(data, locale)
    assert VERDICT_TEXT[locale][f"multiplicity.{status}.undeclared.account"] in summary
    assert not CONFIGURATIONS.search(summary)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_myfxbook_statement_reads_as_an_account_in_every_section(locale: str) -> None:
    result = _statement_result(locale)
    data = result.model_dump(mode="json")
    multiplicity = next(d for d in data["verdict"]["dimensions"] if d["name"] == "multiplicity")
    assert multiplicity["status"] == "FAIL" and trials_undeclared(multiplicity["inputs"])
    voice = ownership.role_of(data)
    text = _visible(render_html(result, watermark=False, locale=locale))
    meaning = ownership.meaning(
        "multiplicity", "FAIL", locale, voice, account=True, undeclared=True
    ) or verdict_meaning("multiplicity", "FAIL", locale, account=True, undeclared=True)
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    summary = VERDICT_TEXT[locale]["multiplicity.FAIL.undeclared.account"]
    # The meaning, the plan and the summary count accounts: "Even at 1 account".
    for shown in (meaning, step.finding, summary):
        assert shown in text
        assert not CONFIGURATIONS.search(shown), shown
    assert "1 " + ACCOUNT_OR_SIGNAL[locale].split()[0] in step.finding
    assert not ROBOT_ANYWHERE.search(text), ROBOT_ANYWHERE.search(text)
    # Only the hidden floating drawdown fired: the callout names it after the figure.
    codes = {flag["code"] for flag in data["red_flags"]}
    assert "HIDDEN_FLOATING_DRAWDOWN" in codes and "FLOATING_LOSS_AT_END" not in codes
    labels = LABELS[locale]
    share = data["account"]["floating_share"]["value"]
    warning = labels["ch_unseen_open"].format(
        share=f"{abs(share):.0%}", tag=evidence_label("DECLARED", locale)
    )
    assert f"{warning} {labels['ch_unseen_hidden_also']}" in text
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_hidden_floating_drawdown_alone_never_reads_as_a_zero_open_loss(locale: str) -> None:
    data = _signal(locale)
    data["red_flags"] = [f for f in data["red_flags"] if f["code"] != "FLOATING_LOSS_AT_END"]
    data["account"]["floating_share"]["value"] = -0.003
    assert unseen_open_loss(data) == (True, None)
    labels = LABELS[locale]
    warning = _visible(unseen_open_loss_warning(data, labels))
    # It names the hidden floating drawdown, with no figure at all.
    assert labels["ch_unseen_hidden"] in warning
    assert flag_title("HIDDEN_FLOATING_DRAWDOWN", locale) in labels["ch_unseen_hidden"]
    assert "0%" not in warning and not re.search(r"\d", labels["ch_unseen_hidden"])
    # The challenge section opens with it, before any figure.
    page = render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
    section = page.split(f"<h2>{html.escape(labels['challenge'], quote=True)}</h2>")[-1]
    head = section[: section.index("<details class='unseen-open'>")]
    assert html.escape(labels["ch_unseen_hidden"], quote=True) in head
    assert "<table" not in head
    # An open loss that shows as a figure is given, the hidden drawdown after it.
    data["account"]["floating_share"]["value"] = -0.04
    assert unseen_open_loss(data) == (True, -0.04)
    warning = _visible(unseen_open_loss_warning(data, labels))
    declared_tag = evidence_label("DECLARED", locale)
    expected = (
        labels["ch_unseen_open"].format(share="4%", tag=declared_tag)
        + " "
        + labels["ch_unseen_hidden_also"]
    )
    assert expected in warning
    for key in ("ch_unseen_hidden", "ch_unseen_hidden_also"):
        assert not re.search(r"aprob|aprova|approv", labels[key], re.I), key
    assert find_claims(warning) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_small_widening_that_moves_the_table_says_both_figures(locale: str) -> None:
    labels, keys = LABELS[locale], KEY_LABELS[locale]
    significance = {
        "status": "MEASURED",
        "observations": measured(400),
        "psr": measured(0.955),
        "min_track_record_length": measured(380.0),
        "dependence": {
            "ratio": measured(1.09),
            "psr": measured(0.948),
            "min_track_record_length": measured(415.0),
        },
    }
    data: dict[str, Any] = {
        "significance": significance,
        "verdict": {
            "dimensions": [{"name": "statistical_significance", "inputs": {"psr": measured(0.948)}}]
        },
    }
    rows = _visible(
        report._evidence_rows(report._significance_rows(significance, data), labels, skip=set())
    )
    assert f"{keys['psr']} 95.50%" in rows and f"{keys['psr_dependence']} 94.80%" in rows
    assert localize(psr_names.CLASS_NOTE, locale) in rows
    # Under a tenth of widening, but the class's figure is below 95 %: both are said.
    line = _visible(report._dependence_html(significance, labels, data))
    assert labels["dependence_none"] not in line
    assert "1.09" in line and "95.50%" in line and "94.80%" in line
    assert labels["dependence_pass_rests"] in line and labels["dependence_info"] in line
    assert find_claims(line) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_result_classified_on_the_plain_count_says_so_in_the_table_and_the_line(
    locale: str,
) -> None:
    data = _signal(locale)
    significance = data["significance"]
    plain = significance["psr"]["value"]
    adjusted = significance["dependence"]["psr"]["value"]
    # As stored between 26 and 27 September: the adjusted figure measured as
    # information, the class decided on the plain count.
    dimension = _statistical(data)
    dimension["inputs"]["psr"] = measured(plain)
    for key in ("reasons", "reasons_es"):
        if dimension.get(key):
            dimension[key] = [
                reason.replace(f"PSR {adjusted:.3f}", f"PSR {plain:.3f}")
                for reason in dimension[key]
            ]
    assert psr_names.class_psr(data)[2] == psr_names.PLAIN
    labels = LABELS[locale]
    assert report._significance_rows(significance, data)["psr_dependence"].get("note") != (
        psr_names.CLASS_NOTE
    )
    line = _visible(report._dependence_html(significance, labels, data))
    assert labels["dependence_info_plain"] in line and labels["dependence_info"] not in line
    text = _visible(render_html(AuditResult.model_validate(data), watermark=False, locale=locale))
    assert localize(psr_names.CLASS_NOTE, locale) not in text
    assert labels["dependence_info"] not in text and labels["dependence_info_plain"] in text
    name = psr_names.psr_name(psr_names.PLAIN, locale)
    assert f"{name} {plain:.3f} < 0.8" in text
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_without_itemised_fees_the_live_table_does_not_say_net_of_fees(locale: str) -> None:
    labels = LABELS[locale]
    rng = np.random.default_rng(3)
    backtest_pnl = [float(v) for v in rng.normal(5.0, 40.0, 400).round(2)]
    live_pnl = [float(v) for v in rng.normal(5.0, 40.0, 60).round(2)]
    backtest_start = datetime(2023, 1, 2, tzinfo=UTC)
    live_start = datetime(2024, 6, 3, tzinfo=UTC)
    # CSV trades with no cost columns on either side.
    live = compare_live(_trades(backtest_pnl, backtest_start), _trades(live_pnl, live_start))
    assert live["fees_itemised"] == {"backtest": False, "live": False}
    shown = _visible(report._live_html(live, locale, labels, {}))
    win = live["live"]["avg_win"]["value"]
    assert f"{labels['live_avg_win_plain']} {win:,.2f}" in shown
    assert labels["live_avg_win"] not in shown and labels["live_avg_loss"] not in shown
    # Fees on the backtest only: the row covers both columns, so it stays plain.
    backtest_fees = _trades(backtest_pnl, backtest_start, [0.5] * len(backtest_pnl))
    live = compare_live(backtest_fees, _trades(live_pnl, live_start))
    assert live["fees_itemised"] == {"backtest": True, "live": False}
    assert labels["live_avg_win"] not in _visible(report._live_html(live, locale, labels))
    # Both files itemise them: net of fees.
    live = compare_live(backtest_fees, _trades(live_pnl, live_start, [0.5] * len(live_pnl)))
    assert report.live_net_of_fees(live)
    assert labels["live_avg_win"] in _visible(report._live_html(live, locale, labels))
    # A result stored before the indicator does not know the live file's.
    live.pop("fees_itemised")
    assert not report.live_net_of_fees(live, {"win_rate_gross": measured(0.5)})
    for key in ("live_avg_win_plain", "live_avg_loss_plain"):
        assert NET[locale] not in labels[key] and GROSS[locale] not in labels[key]


@pytest.mark.parametrize("locale", LOCALES)
def test_a_stored_backtest_question_reads_as_the_plan_does(locale: str) -> None:
    stored = {
        "code": "backtest_match",
        "es": "Pide el backtest del mismo robot con la misma configuración: subido junto a "
        "esta cuenta, el informe compara los dos operación por operación.",
        "en": "Ask for the backtest of the same robot with the same settings: uploaded "
        "together with this account, the report compares the two trade by trade.",
    }
    current = analytics.question_now("backtest_match")
    assert current is not None and analytics.question_now("trials") is None
    shown = report._question_text(stored, locale)
    assert shown == (localize(current["en"], "pt") if locale == "pt" else current[locale])
    assert locale != "pt" or shown != current["en"]
    assert not ROBOT.search(shown) and not ROBOT_ANYWHERE.search(shown)
    for voice in ownership.ROLES:
        item = ownership.question_item("backtest_match", shown, locale, voice)
        assert not ROBOT.search(item) and find_claims(item) == []
    assert not ROBOT.search(seller_message.SELLER_ASK["backtest_match"][locale])


# Third pass ------------------------------------------------------------------------------
#
# What the review of the second pass left: the luck section, the questions, the data
# step of the plan and the dimension's name of an account or signal still spoke of
# configurations tried and of a robot; the challenge callout's open loss carried no
# tag; the variance ratio, the p95 drawdown and the starting balance read two ways;
# the mean-shift section annualised short stretches without saying so; the seller's
# message listed weak dimensions under "do not pass"; and four sentences read badly.

#: The robot itself, which no text of an account or signal page names.
ROBOT_WORD = re.compile(r"\b(robot|robots|robô|robôs)\b", re.I)
#: The flags whose plan step was written for whoever builds and backtests the robot
#: (the extreme jumps' "fix them" too: only the file's author can).
BUILDER_FLAGS = (
    "MARTINGALE_SIZING",
    "GRID_AVERAGING",
    "MANY_CONCURRENT_POSITIONS",
    "HIDDEN_FLOATING_DRAWDOWN",
    "MAD_SPIKES",
)


def _page_of(data: dict[str, Any], locale: str) -> str:
    return _visible(render_html(AuditResult.model_validate(data), watermark=False, locale=locale))


@cache
def _voiced_signal_page(locale: str, role: str | None) -> str:
    return _page_of(_with_role(_signal(locale), role), locale)


def _luck_note() -> str:
    from quant_trade.audit.luck import NOTE

    return NOTE


# 1 · the luck section counts the accounts or signals behind it -------------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_the_luck_section_of_an_account_counts_accounts_or_signals(
    locale: str, role: str | None
) -> None:
    data = _with_role(_signal(locale), role)
    voice = role or ownership.NEUTRAL
    labels = ownership.labels_for(LABELS[locale], locale, voice)
    section = _visible(
        report._luck_html(data["luck"], locale, labels, data["multiplicity"], account=True)
    )
    # The introduction, the table's header and the dimension it names count the
    # accounts or signals: what the trial count of an account is.
    assert labels["luck_intro_account"] in section and labels["luck_intro"] not in section
    assert labels["luck_table_trials_account"] in section
    assert labels["luck_table_trials"] not in section
    name = report._dimension_title("multiplicity", locale, account=True)
    assert name in labels["luck_intro_account"]
    assert report.DIMENSION_TITLES[locale]["multiplicity"] not in section
    assert ACCOUNT_OR_SIGNAL[locale].split()[0] in labels["luck_table_trials_account"].lower()
    assert not CONFIGURATIONS.search(section), CONFIGURATIONS.search(section)
    # The challenge's "luck discounted" row says the same.
    ladder = _visible(
        report._challenge_ladder_html(data["challenge"]["scenarios"], locale, labels, account=True)
    )
    assert labels["ch_ladder_undeclared_account"] in ladder
    assert not CONFIGURATIONS.search(ladder), ladder
    # The whole page: no configurations tried, and the account's name of the dimension.
    page = _voiced_signal_page(locale, role)
    assert not CONFIGURATIONS.search(page), CONFIGURATIONS.search(page)
    assert labels["luck_intro_account"] in page and labels["luck_intro"] not in page
    assert find_claims(section) == [] and find_claims(ladder) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_counted_luck_of_an_account_names_accounts_and_a_backtest_keeps_its_words(
    locale: str,
) -> None:
    labels = LABELS[locale]
    data = _backtest_result(locale).model_dump(mode="json")
    luck = data["luck"]
    assert luck["counted"] and luck["trials"] > 1
    account = _visible(report._luck_html(luck, locale, labels, data["multiplicity"], account=True))
    n = f"{int(luck['trials']):,}"
    sharpe = f"{float(luck['sharpe']['value']):.2f}"
    assert labels["luck_sharpe_account"].format(n=n, sharpe=sharpe) in account
    assert labels["luck_after_account"].format(n=n) in account
    assert not CONFIGURATIONS.search(account), CONFIGURATIONS.search(account)
    assert labels["luck_sharpe"].format(n=n, sharpe=sharpe) not in account
    assert labels["luck_note_account"] in account
    # A backtest's section is as it was: configurations tried, the backtest's length.
    backtest = _visible(report._luck_html(luck, locale, labels, data["multiplicity"]))
    assert labels["luck_intro"] in backtest and labels["luck_table_trials"] in backtest
    assert labels["luck_sharpe"].format(n=n, sharpe=sharpe) in backtest
    assert labels["luck_note_account"] not in backtest
    assert localize(luck["note"], locale) in backtest
    assert find_claims(account) == []


# 2 · the questions ask about the account or signal ---------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_the_questions_of_an_account_ask_about_the_account_or_signal(
    locale: str, role: str | None
) -> None:
    data = _with_role(_signal(locale), role)
    voice = role or ownership.NEUTRAL
    codes = {q["code"] for q in data["vendor_questions"]}
    assert {"martingale", "grid"} <= codes
    # A fading edge asks about the recent stretch, stored with the robot's wording
    # (a result stored before the account's): the page shows the account's.
    assert "recent_period" not in codes
    data["vendor_questions"].append(
        {"code": "recent_period", **analytics._QUESTIONS["recent_period"]}
    )
    page = _page_of(data, locale)
    for question in ownership.open_questions(data, voice):
        shown = report._question_text(question, locale, account=True)
        item = ownership.question_item(question["code"], shown, locale, voice, account=True)
        assert not ROBOT_WORD.search(item), item
        assert item in page, item
        assert find_claims(item) == []
        assert not ROBOT_ANYWHERE.search(item), item
        if question["code"] in ("martingale", "grid", "recent_period"):
            # The question and, in every voice but the buyer's, what answers it.
            assert ACCOUNT_OR_SIGNAL[locale] in shown, shown
            if voice != ownership.BUYER:
                answer = ownership.ACCOUNT_QUESTIONS[question["code"]][locale][1]
                assert answer in item and ACCOUNT_OR_SIGNAL[locale] in answer
    if voice == ownership.BUYER:
        # Questions 6 and 7 of the message to paste, and the recent stretch's.
        message = report._seller_message(data, locale, LABELS[locale])[0]
        assert not ROBOT_WORD.search(message), ROBOT_WORD.search(message)
        assert not ROBOT_ANYWHERE.search(message), ROBOT_ANYWHERE.search(message)
        for code in ("martingale", "grid", "recent_period"):
            question = next(q for q in data["vendor_questions"] if q["code"] == code)
            assert report._question_text(question, locale, account=True) in message
    assert not ROBOT_WORD.search(page), ROBOT_WORD.search(page)
    assert not ROBOT_ANYWHERE.search(page), ROBOT_ANYWHERE.search(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_question_stored_with_the_robot_reads_as_the_account_and_a_backtest_keeps_it(
    locale: str,
) -> None:
    asked = analytics.vendor_questions(
        ["MARTINGALE_SIZING", "GRID_AVERAGING", "EDGE_FADING"],
        has_trades=True,
        trials_measured=False,
        has_out_of_sample=False,
        has_costs=False,
        balance_only=False,
        account_history=True,
    )
    # The recent stretch asks whether the account or signal changed or was restarted.
    recent = next(q for q in asked if q["code"] == "recent_period")
    assert recent["es"] == analytics.ACCOUNT_QUESTIONS["recent_period"]["es"]
    assert recent["en"] == analytics.ACCOUNT_QUESTIONS["recent_period"]["en"]
    stored = {"code": "recent_period", **analytics._QUESTIONS["recent_period"]}
    for question in (recent, stored):
        account = report._question_text(question, locale, account=True)
        assert ACCOUNT_OR_SIGNAL[locale] in account and not ROBOT_ANYWHERE.search(account)
        assert locale != "pt" or account != analytics.ACCOUNT_QUESTIONS["recent_period"]["en"]
        assert find_claims(account) == []
    # A backtest's keeps its reoptimisation.
    backtest = report._question_text(stored, locale)
    assert re.search(r"reoptimi|reotimi", backtest), backtest
    kept = analytics.vendor_questions(
        ["EDGE_FADING"],
        has_trades=True,
        trials_measured=True,
        has_out_of_sample=True,
        has_costs=True,
        balance_only=False,
    )
    assert next(q for q in kept if q["code"] == "recent_period") == stored
    for code in ("martingale", "grid"):
        stored = {"code": code, **analytics._QUESTIONS[code]}
        account = report._question_text(stored, locale, account=True)
        assert not ROBOT_WORD.search(account) and ACCOUNT_OR_SIGNAL[locale] in account
        if locale == "pt":
            assert account != analytics.ACCOUNT_QUESTIONS[code]["en"]
        # The engine stores the account's wording for an account history ...
        kept = next(q for q in asked if q["code"] == code)
        assert kept["es"] == analytics.ACCOUNT_QUESTIONS[code]["es"]
        assert kept["en"] == analytics.ACCOUNT_QUESTIONS[code]["en"]
        # ... and a backtest's question still speaks of its robot.
        backtest = report._question_text(stored, locale)
        assert ROBOT_WORD.search(backtest), backtest
        for voice in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
            item = ownership.question_item(code, backtest, locale, voice)
            assert ownership.QUESTIONS[code][locale][1] in item
    # Asked of an account, the recent stretch is answered by the account's history.
    for voice in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
        item = ownership.question_item("recent_period", "?", locale, voice, account=True)
        assert not ROBOT_WORD.search(item) and find_claims(item) == []
        assert ownership.ACCOUNT_QUESTIONS["recent_period"][locale][1] in item


# 3 · the data step of the plan: what someone with an account can do ---------------------


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_the_data_step_of_an_account_asks_what_an_account_can_give(
    locale: str, role: str | None
) -> None:
    data = _with_role(_signal(locale), role)
    voice = role or ownership.NEUTRAL
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "data_quality")
    page = _voiced_signal_page(locale, role)
    for code in BUILDER_FLAGS:
        lead = f"{flag_title(code, locale)}. "
        action = next(a for a in step.actions if a.startswith(lead))
        hint = action[len(lead) :]
        voiced = ownership.plan_text(f"account_flag_{code}", locale, voice)
        assert voice == ownership.BUYER or voiced is not None
        assert hint == (voiced or plan_lib.ACCOUNT_FLAG_HINTS[code][locale])
        # No backtest to upload, no robot, nothing only a builder does.
        assert hint != plan_lib.FLAG_HINTS[code][locale]
        assert not re.search(r"backtest|robot|robô", hint, re.I), hint
        assert action in page
        assert find_claims(hint) == []
    # A backtest's step keeps the builder's wording.
    backtest = _backtest_result(locale).model_dump(mode="json")
    backtest["red_flags"] = [{"code": code, "severity": "WARN"} for code in BUILDER_FLAGS]
    _, actions = plan_lib._data_quality_step(backtest, "WEAK", locale)
    for code in BUILDER_FLAGS:
        assert f"{flag_title(code, locale)}. {plan_lib.FLAG_HINTS[code][locale]}" in actions


# 4 · the dimension's name ------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_an_account_names_the_multiplicity_dimension_by_what_it_counts(locale: str) -> None:
    from quant_trade.audit.pages import verification_page

    data = _signal(locale)
    name = report._dimension_title("multiplicity", locale, account=True)
    backtest_name = report.DIMENSION_TITLES[locale]["multiplicity"]
    assert name != backtest_name and ACCOUNT_OR_SIGNAL[locale].split()[0] in name.lower()
    page = _signal_page(locale)
    # The list of dimensions, the technical detail, the PDF cover and the message.
    assert f"<h3>{html.escape(name, quote=True)} " in page
    assert f"<td>{html.escape(name, quote=True)}</td>" in page
    assert f"<span>{html.escape(name, quote=True)}</span>" in page
    message = report._seller_message(data, locale, LABELS[locale])[0]
    assert name in message and backtest_name not in message
    assert backtest_name not in _visible(page)
    # The public page's cards too.
    public = _visible(
        verification_page(
            data,
            public_id="abc123",
            published_at="2026-10-01T00:00:00Z",
            result_sha256="0" * 64,
            base_url="https://rigorscore.com",
            locale=locale,
        )
    )
    assert name in public and backtest_name not in public
    # A backtest keeps its name.
    assert backtest_name in _visible(_backtest_page(locale))
    assert report._dimension_title("multiplicity", locale) == backtest_name
    assert find_claims(name) == []


# 5 · the challenge callout tags the declared open loss -----------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_challenge_callout_tags_the_open_loss_as_declared(locale: str) -> None:
    data = _signal(locale)
    share = data["account"]["floating_share"]
    assert share["evidence"] == "DECLARED"
    labels = LABELS[locale]
    tag = evidence_label("DECLARED", locale)
    warning = labels["ch_unseen_open"].format(share=f"{abs(share['value']):.0%}", tag=tag)
    assert f"({tag})" in warning
    assert warning in _visible(unseen_open_loss_warning(data, labels))
    # The same figure carries the same tag in the account's section.
    page = _visible(_signal_page(locale))
    assert warning in page
    floating = f"{KEY_LABELS[locale]['floating_share']} {report._table_pct(share['value'])}"
    assert f"{floating} {tag}" in page
    # A share read from the flag alone is the file's declared figure too.
    data["account"] = None
    assert f"({tag})" in _visible(unseen_open_loss_warning(data, labels))
    assert find_claims(warning) == []


# 6 · one presentation of the variance ratio -----------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_variance_ratio_reads_the_same_in_the_sentence_and_the_table(locale: str) -> None:
    data = _signal(locale)
    labels = LABELS[locale]
    significance = data["significance"]
    ratio = significance["dependence"]["ratio"]["value"]
    assert f"{ratio:.1f}" != f"{ratio:.2f}"
    shown = report._fmt(ratio, key="dependence_ratio")
    line = _visible(report._dependence_html(significance, labels, data))
    expected = labels["dependence_line"].format(
        ratio=shown,
        plain=report._table_pct(significance["psr"]["value"]),
        psr=report._table_pct(significance["dependence"]["psr"]["value"]),
    )
    assert expected in line
    text = _visible(_signal_page(locale))
    assert expected in text
    assert f"{KEY_LABELS[locale]['dependence_ratio']} {shown}" in text


# 7 · one sign for the p95 drawdown --------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_p95_drawdown_has_one_sign_in_the_summary_and_the_risk_section(locale: str) -> None:
    data = _signal(locale)
    labels = LABELS[locale]
    drawdown = data["risk"]["max_drawdown"]
    tiles = {label: shown for label, shown, _ in report._kpi_list(data, labels)}
    tile = tiles[labels["kpi_dd_p95_closed"]]
    section = _visible(report._risk_html(data["risk"], locale, labels))
    fact = report._fmt(-abs(drawdown["p95"]["value"]), key="p50")
    assert tile.startswith("-") and fact.startswith("-")
    for q in ("p50", "p95", "p99"):
        value = abs(drawdown[q]["value"])
        assert f"{report._fmt(-value, key='p50')} {labels['risk_dd']} · {q}" in section
        positive = re.escape(f"{report._fmt(value, key='p50')} {labels['risk_dd']}")
        assert not re.search(rf"(?<![-\d.]){positive}", section), section
    # The same figure, rounded the same way.
    assert abs(float(tile.rstrip("%")) - float(fact.rstrip("%"))) < 0.06
    assert f"{fact} {labels['risk_dd']} · p95" in _visible(_signal_page(locale))


# 8 · a short stretch's annual rate says it is one ------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_mean_shift_says_its_annual_rates_come_from_short_stretches(locale: str) -> None:
    data = _signal(locale)
    labels = LABELS[locale]
    shift = data["mean_shift"]
    ppy = data["inputs"]["periods_per_year"]["value"]
    before, after = shift["before"]["returns"], shift["after"]["returns"]
    assert before < ppy and after < ppy
    # The annual return says it is not annualised under a year.
    assert data["performance"]["cagr"]["evidence"] == "NOT_MEASURED"

    def months(count: int) -> str:
        return labels["luck_months"].format(n=f"{count / ppy * 12:.1f}")

    note = labels["shift_short"].format(before=months(before), after=months(after))
    section = _visible(report._shift_html(shift, locale, labels, periods_per_year=ppy))
    assert note in section
    assert note in _visible(_signal_page(locale))
    # Two stretches of over a year each need no such note.
    long_shift = copy.deepcopy(shift)
    long_shift["before"]["returns"] = long_shift["after"]["returns"] = int(ppy * 2)
    long = _visible(report._shift_html(long_shift, locale, labels, periods_per_year=ppy))
    assert labels["shift_short"].split("{")[0].strip() not in long
    assert find_claims(note) == []


# 9 · the seller's message lists what fails apart from what is weak -------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_seller_message_lists_weak_dimensions_apart_from_those_that_fail(
    locale: str,
) -> None:
    data = _signal(locale)
    words = seller_message.words(locale)

    def names(status: str) -> str:
        statuses = {d["name"]: d["status"] for d in data["verdict"]["dimensions"]}
        return ", ".join(
            report._dimension_title(name, locale, account=True)
            for name in report.DIMENSION_ORDER
            if statuses.get(name) == status
        )

    assert names("FAIL") and names("WEAK")
    line = (
        words["dimensions"].format(items=names("FAIL"))
        + " "
        + words["dimensions_weak"].format(items=names("WEAK"))
    )
    lines = report._seller_message(data, locale, LABELS[locale])[0].split("\n")
    assert line in lines
    weak = report.STATUS_TEXT[locale]["WEAK"].lower()
    assert f"({weak})" not in "\n".join(lines)
    # Only weak ones: none fails, and the weak ones are named as such.
    weak_names = names("WEAK")
    for dimension in data["verdict"]["dimensions"]:
        if dimension["status"] == "FAIL":
            dimension["status"] = "PASS"
    lines = report._seller_message(data, locale, LABELS[locale])[0].split("\n")
    only_weak = words["dimensions_none"] + " " + words["dimensions_weak"].format(items=weak_names)
    assert only_weak in lines
    assert find_claims(line) == []


# 10 · each starting balance with the tag its JSON stores -----------------------------------

#: How an account or signal's 1x line says where its balance comes from.
FILE_DECLARES = {
    "es": "balance inicial que declara el archivo",
    "en": "starting balance the file declares",
    "pt": "saldo inicial que o arquivo declara",
}
#: The backtest sample's two lines as e1df258 (before this branch) shows them.
BACKTEST_BALANCE_LINES = {
    "es": (
        "Capital inicial 10,000.00 Medido",
        "Los porcentajes de 1x se miden sobre el balance inicial del archivo (10,000). Declarado",
    ),
    "en": (
        "Starting capital 10,000.00 Measured",
        "The shares at 1x are measured on the file's starting balance (10,000). Declared",
    ),
    "pt": (
        "Capital inicial 10,000.00 Medido",
        "As porcentagens de 1x são medidas sobre o saldo inicial do arquivo (10,000). Declarado",
    ),
}


def _balance_lines(text: str, data: dict[str, Any], locale: str, *, account: bool) -> None:
    """``text`` shows the reconciliation's starting capital and the size table's
    balance each with the tag ``data`` (the downloadable JSON) stores, and the 1x
    line of an account or signal says the file declares it."""
    recon = data["reconciliation"]["initial_capital"]
    sizing = data["challenge"]["sizing"]["starting_balance"]
    tags = {key: evidence_label(key, locale) for key in ("MEASURED", "DECLARED")}
    initial = INTEGRITY_TEXT[locale]["recon_initial"]
    amount = report._table_money(recon["value"])
    for key, tag in tags.items():
        assert (f"{initial} {amount} {tag}" in text) is (key == recon["evidence"]), key
    labels = LABELS[locale]
    balance = report._fmt(float(sizing["value"]), key="starting_balance")
    said, other = ("ch_size_balance_declared", "ch_size_balance")
    if not account:
        said, other = other, said
    line = labels[said].format(balance=balance)
    for key, tag in tags.items():
        assert (f"{line} {tag}" in text) is (key == sizing["evidence"]), key
    assert labels[other].format(balance=balance) not in text
    assert (FILE_DECLARES[locale] in line) is account
    assert f"({balance})" in line


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("kind", ["signal", "backtest"])
def test_each_starting_balance_shows_the_tag_its_json_stores(locale: str, kind: str) -> None:
    signal = kind == "signal"
    data = _signal(locale) if signal else _backtest_result(locale).model_dump(mode="json")
    recon = data["reconciliation"]["initial_capital"]
    sizing = data["challenge"]["sizing"]["starting_balance"]
    # The same figure stored twice: Measured by the reconciliation (the first point of
    # the curve the engine rebuilds from the deposits the file lists, or its balance)
    # and Declared by the size table (the balance the file declares).
    assert data["inputs"]["initial_balance"]["value"] == recon["value"] == sizing["value"]
    assert recon["evidence"] == "MEASURED" and sizing["evidence"] == "DECLARED"
    assert report.file_declares_balance(data)
    text = _visible(_signal_page(locale) if signal else _backtest_page(locale))
    _balance_lines(text, data, locale, account=signal)
    if signal:
        # The money deposited, which holds that starting balance, keeps its own tag.
        deposited = data["account"]["deposits"]["total"]
        assert deposited["evidence"] == "MEASURED"
        money = report._fmt(deposited["value"], key="deposits_total")
        tag = evidence_label("MEASURED", locale)
        assert f"{KEY_LABELS[locale]['deposits_total']} {money} {tag}" in text
    else:
        # A backtest reads both lines word for word as before this branch.
        for line in BACKTEST_BALANCE_LINES[locale]:
            assert line in text, line
    # The stored result is untouched.
    assert data["reconciliation"]["initial_capital"]["evidence"] == "MEASURED"
    assert data["challenge"]["sizing"]["starting_balance"]["evidence"] == "DECLARED"


def test_only_the_files_own_declared_balance_says_the_file_declares_it() -> None:
    data = _signal("es")
    sizing = data["challenge"]["sizing"]
    value = sizing["starting_balance"]["value"]
    labels = LABELS["es"]
    balance = report._fmt(float(value), key="starting_balance")
    assert report.file_declares_balance(data)
    # The client declared that balance on the form: it may stand in for the file's.
    client = copy.deepcopy(data)
    client["declared"]["initial_balance"] = declared(value)
    assert not report.file_declares_balance(client)
    page = _page_of(client, "es")
    plain = labels["ch_size_balance"].format(balance=balance)
    assert f"{plain} {evidence_label('DECLARED', 'es')}" in page
    assert FILE_DECLARES["es"] not in page
    # Another balance on the form: the file's own one was used.
    other = copy.deepcopy(data)
    other["declared"]["initial_balance"] = declared(value + 500)
    assert report.file_declares_balance(other)
    # An assumed balance, a curve's first value or no balance never say so.
    assumed = copy.deepcopy(data)
    assumed["inputs"]["parse_warnings"].append(
        f"report: {report.ASSUMED_BALANCE_WARNING}; 10,000 was assumed"
    )
    assert not report.file_declares_balance(assumed)
    curve = copy.deepcopy(data)
    curve["challenge"]["sizing"]["starting_balance"]["evidence"] = "MEASURED"
    assert not report.file_declares_balance(curve)
    empty = copy.deepcopy(data)
    empty["challenge"] = None
    assert not report.file_declares_balance(empty)
    # The line keeps the stored tag whatever it says.
    said = report._sizing_balance_html(sizing, labels, file_balance=True)
    assert labels["ch_size_balance_declared"].format(balance=balance) in html.unescape(said)
    assert said.endswith(report._badge("DECLARED"))
    kept = report._sizing_balance_html(sizing, labels)
    assert plain in html.unescape(kept) and kept.endswith(report._badge("DECLARED"))
    first = report._sizing_balance_html(curve["challenge"]["sizing"], labels, file_balance=True)
    assert plain in html.unescape(first) and first.endswith(report._badge("MEASURED"))


# 11 · four sentences --------------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_backtest_question_says_if_it_has_one_once_in_every_voice(locale: str) -> None:
    once = {"es": "si lo tiene", "en": "if it has one", "pt": "se ela tiver um"}[locale]
    data = _signal(locale)
    question = next(q for q in data["vendor_questions"] if q["code"] == "backtest_match")
    shown = report._question_text(question, locale, account=True)
    for voice in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
        item = ownership.question_item("backtest_match", shown, locale, voice, account=True)
        assert item.count(once) == 1, item
        assert item in _voiced_signal_page(locale, voice)


@pytest.mark.parametrize("locale", LOCALES)
def test_what_to_do_and_the_instruments_of_an_account_name_no_robot(locale: str) -> None:
    labels = LABELS[locale]
    page = _visible(_signal_page(locale))
    for key in ("next_intro_account", "ins_intro_account"):
        assert labels[key] in page and not ROBOT_WORD.search(labels[key])
        assert labels[key.removesuffix("_account")] not in page
    assert ACCOUNT_OR_SIGNAL[locale] in labels["next_intro_account"]
    # Every other voice keeps its own introduction (PR 478).
    for voice in (ownership.OWN, ownership.PROVIDER, ownership.NEUTRAL):
        voiced = ownership.labels_for(labels, locale, voice)
        assert voiced["next_intro_account"] == voiced["next_intro"]
        assert voiced["next_intro"] in _voiced_signal_page(locale, voice)
    # The luck section's sources speak of the history's length.
    assert labels["luck_note_account"] in page
    assert localize(_luck_note(), locale) not in page
    # A backtest keeps its words.
    backtest = _visible(_backtest_page(locale))
    assert labels["ins_intro"] in backtest and labels["ins_intro_account"] not in backtest
    assert localize(_luck_note(), locale) in backtest
    for key in ("next_intro_account", "ins_intro_account", "luck_note_account"):
        assert find_claims(labels[key]) == []


# The new texts of the third pass ------------------------------------------------------------

THIRD_LABELS = (
    "luck_intro_account",
    "luck_table_trials_account",
    "luck_narrow_account",
    "luck_beats_account",
    "luck_below_account",
    "luck_sharpe_account",
    "luck_after_account",
    "luck_note_account",
    "ch_ladder_undeclared_account",
    "ins_intro_account",
    "next_intro_account",
    "shift_short",
)


def test_every_third_pass_text_exists_in_three_languages_and_passes_the_guard() -> None:
    texts: list[str] = []
    for locale in LOCALES:
        for key in THIRD_LABELS:
            text = LABELS[locale][key]
            if locale != "en":
                assert text != LABELS["en"][key], (locale, key)
            assert not CONFIGURATIONS.search(text), (locale, key)
            texts.append(text)
        name = report.DIMENSION_TITLES_ACCOUNT[locale]["multiplicity"]
        if locale != "en":
            assert name != report.DIMENSION_TITLES_ACCOUNT["en"]["multiplicity"]
        texts.append(name)
        words = seller_message.COPY[locale]["dimensions_weak"]
        assert locale == "en" or words != seller_message.COPY["en"]["dimensions_weak"]
        texts.append(words)
        for answers in ownership.ACCOUNT_QUESTIONS.values():
            texts.append(answers[locale][1])
        for code in BUILDER_FLAGS:
            texts.append(plan_lib.ACCOUNT_FLAG_HINTS[code][locale])
            texts.extend(
                voices[locale] for voices in ownership.PLAN[f"account_flag_{code}"].values()
            )
        for code in ("martingale", "grid"):
            texts.append(report._question_text({"code": code}, locale, account=True))
    for text in texts:
        assert text, texts
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
        assert not ROBOT_WORD.search(text), text


# Fourth pass ------------------------------------------------------------------------------
# A review of the third pass found: the recent stretch's question still asked about a
# reoptimisation; the reconciliation's starting capital turned Declared although the file's
# deposits give it; the multiplicity detail and CSCV of an account spoke of variants; a
# comparison named the dimension "settings tried"; a stretch under a year read "12.0 months"
# or "1.0 months"; Portuguese said "provedor"; the extreme jumps asked the buyer to fix the
# data; Start and End taken from the trades read as the platform's.


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_the_multiplicity_detail_of_an_account_names_the_other_accounts_not_variants(
    locale: str, role: str | None
) -> None:
    voice = role or ownership.NEUTRAL
    labels = ownership.labels_for(LABELS[locale], locale, voice)
    data = _signal(locale)
    observed = data["multiplicity"]["observed_across_variants"]
    assert observed["evidence"] == "NOT_MEASURED" and observed["note"] == report.NO_VARIANTS
    assert data["cscv"] == {"status": "NOT_MEASURED", "reason": report.NO_VARIANTS}
    page = _voiced_signal_page(locale, role)
    assert labels["variance_policy_account"] in page and labels["variance_policy"] not in page
    key_labels = KEY_LABELS[locale]
    assert f"{key_labels['observed_across_accounts']} — " in page
    assert key_labels["observed_across_variants"] not in page
    assert labels["no_variants_account"] in page
    # The CSCV row and the "not measured" list say the same.
    assert f"{labels['cscv']} {_sentence_case(labels['no_variants_account'])}." in page
    assert localize(report.NO_VARIANTS, locale) not in page
    assert not ROBOT_ANYWHERE.search(page), ROBOT_ANYWHERE.search(page)
    # The stored result is unchanged.
    assert data["multiplicity"]["observed_across_variants"] == observed


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


@pytest.mark.parametrize("locale", LOCALES)
def test_a_backtest_keeps_its_variants_and_an_uploaded_matrix_keeps_its_row(locale: str) -> None:
    labels, key_labels = LABELS[locale], KEY_LABELS[locale]
    backtest = _visible(_backtest_page(locale))
    assert labels["variance_policy"] in backtest
    assert labels["variance_policy_account"] not in backtest
    assert f"{key_labels['observed_across_variants']} — " in backtest
    assert labels["no_variants_account"] not in backtest
    # An account whose matrix was uploaded keeps the row as measured.
    rows = {"observed_across_variants": measured(0.01, "variance across 3 variants")}
    kept, unmatched = report._account_multiplicity_rows(rows, labels)
    assert kept == rows and not unmatched
    measured_cscv = {"status": "MEASURED", "pbo": measured(0.2)}
    assert report._account_cscv(measured_cscv, labels) == measured_cscv


@pytest.mark.parametrize("locale", LOCALES)
def test_a_comparison_names_the_dimension_by_the_kinds_of_report_it_shows(locale: str) -> None:
    from quant_trade.audit.compare import comparison_body
    from quant_trade.audit.comparison_delta import change_summary
    from quant_trade.audit.strategies import what_changed

    signal = _signal(locale)
    backtest = _backtest_result(locale).model_dump(mode="json")
    account_name = report.DIMENSION_TITLES_ACCOUNT[locale]["multiplicity"]
    mixed_name = report.DIMENSION_TITLES_MIXED[locale]["multiplicity"]
    backtest_name = report.DIMENSION_TITLES[locale]["multiplicity"]
    for pair, name in (
        ((signal, signal), account_name),
        ((signal, backtest), mixed_name),
        ((backtest, signal), mixed_name),
        ((backtest, backtest), backtest_name),
    ):
        body = comparison_body(list(pair), hrefs=["/a", "/b"], locale=locale)
        assert f"<tr><td>{html.escape(name)}</td>" in body, (name, locale)
        others = {account_name, mixed_name, backtest_name} - {name}
        assert not [other for other in others if f"<td>{html.escape(other)}</td>" in body]
        assert report.shared_dimension_title("multiplicity", locale, pair) == name
    # What changed between two of them names it the same way.
    changed = copy.deepcopy(signal)
    for dimension in changed["verdict"]["dimensions"]:
        if dimension["name"] == "multiplicity":
            dimension["status"] = "PASS"
    summary = _visible(change_summary(signal, changed, locale))
    assert account_name in summary and backtest_name not in summary
    lines = [what for what, _ in what_changed(signal, changed, locale)]
    assert any(line.startswith(f"{account_name}: ") for line in lines), lines
    assert not CONFIGURATIONS.search(" ".join(lines))
    for name in (mixed_name, account_name):
        assert find_claims(name) == [] and not CONFIGURATIONS.search(name)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_stretch_under_a_year_never_reads_twelve_or_one_point_zero_months(locale: str) -> None:
    data = _signal(locale)
    labels = LABELS[locale]
    ppy = data["inputs"]["periods_per_year"]["value"]
    assert 259 < ppy < 261

    def sentence(before: int, after: int) -> str:
        shift = copy.deepcopy(data["mean_shift"])
        shift["before"]["returns"], shift["after"]["returns"] = before, after
        return _visible(report._shift_html(shift, locale, labels, periods_per_year=ppy))

    six = labels["luck_months"].format(n="6.0")
    # 260 returns are just under a year: almost 12 months, never "12.0 months".
    almost = sentence(260, 131)
    assert labels["shift_short"].format(before=labels["luck_almost_year"], after=six) in almost
    assert labels["luck_months"].format(n="12.0") not in almost
    # 22 returns are one month: "1 month", never "1.0 months".
    one = sentence(22, 131)
    assert labels["shift_short"].format(before=labels["luck_month_one"], after=six) in one
    assert labels["luck_months"].format(n="1.0") not in one
    # A full year reads in years; under a month, as the luck section says it.
    year = sentence(262, 131)
    full = f"1.0 {labels['luck_years_unit']}"
    assert labels["shift_short"].format(before=full, after=six) in year
    assert labels["luck_under_month"] in sentence(5, 131)
    # The luck section's history reads its length with the same words.
    assert report._span_text(0.999, labels) == labels["luck_almost_year"]
    assert report._span_text(1 / 12, labels) == labels["luck_month_one"]


def test_portuguese_asks_the_fornecedor_everywhere() -> None:
    page = _visible(_signal_page("pt"))
    assert not re.search(r"\bprovedor", page, re.I)
    for code, hints in plan_lib.ACCOUNT_FLAG_HINTS.items():
        assert "provedor" not in hints["pt"], code
    assert "fornecedor" in LABELS["pt"]["account_clean_unseen"]
    assert "provedor" not in LABELS["pt"]["account_clean_unseen"]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_extreme_jumps_of_an_account_ask_instead_of_fixing(locale: str) -> None:
    fix = {"es": "corrígelos", "en": "fix them", "pt": "corrija-os"}[locale]
    assert fix in plan_lib.FLAG_HINTS["MAD_SPIKES"][locale]
    data = _signal(locale)
    assert "MAD_SPIKES" in {flag["code"] for flag in data["red_flags"]}
    for role in (*ownership.ROLES, None):
        voice = role or ownership.NEUTRAL
        step = next(
            s
            for s in improvement_plan(_with_role(data, role), locale)
            if s.dimension == "data_quality"
        )
        lead = f"{flag_title('MAD_SPIKES', locale)}. "
        action = next(a for a in step.actions if a.startswith(lead))
        assert fix not in action, (voice, action)
        if voice == ownership.BUYER:
            assert action == lead + plan_lib.ACCOUNT_FLAG_HINTS["MAD_SPIKES"][locale]
        assert find_claims(action) == []
        assert action in _voiced_signal_page(locale, role)


def test_start_and_end_say_whether_the_platform_or_the_trades_give_them() -> None:
    states = report._platform_states_period
    tester = {"period": "H1 (2020.01.02 - 2024.11.29)", "start": "2020-01-02", "end": "2024-11-29"}
    assert states(tester)
    assert not states({"start": "2025-09-22", "end": "2026-09-16"})
    # A period that does not hold Start or End: they came from the trades.
    assert not states({"period": "2019.01.01 - 2019.12.31", "start": "2020-01-02"})
    backtest = _backtest_result("es").model_dump(mode="json")
    metadata = backtest["inputs"]["report_metadata"]
    first, last = (
        backtest["inputs"]["first_timestamp"][:10],
        backtest["inputs"]["last_timestamp"][:10],
    )
    assert metadata["start"] != first and states(metadata)
    text = _visible(_backtest_page("es"))
    assert LABELS["es"]["platform_period_note"].format(first=first, last=last) in text
    assert LABELS["es"]["platform_period_trades"].split(":")[0] not in text


FOURTH_LABELS = ("variance_policy_account", "no_variants_account", "platform_period_trades")


def test_every_fourth_pass_text_exists_in_three_languages_and_passes_the_guard() -> None:
    texts: list[str] = []
    for locale in LOCALES:
        for key in FOURTH_LABELS:
            text = LABELS[locale][key]
            assert locale == "en" or text != LABELS["en"][key], (locale, key)
            texts.append(text)
        texts.append(KEY_LABELS[locale]["observed_across_accounts"])
        texts.append(report.DIMENSION_TITLES_MIXED[locale]["multiplicity"])
        texts.append(plan_lib.ACCOUNT_FLAG_HINTS["MAD_SPIKES"][locale])
        texts.extend(
            voices[locale] for voices in ownership.PLAN["account_flag_MAD_SPIKES"].values()
        )
        texts.append(report._question_text({"code": "recent_period"}, locale, account=True))
        texts.append(ownership.ACCOUNT_QUESTIONS["recent_period"][locale][1])
    observed = {locale: KEY_LABELS[locale]["observed_across_accounts"] for locale in LOCALES}
    assert len(set(observed.values())) == len(LOCALES)
    for text in texts:
        assert text, texts
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
        assert not ROBOT_WORD.search(text) and not ROBOT_ANYWHERE.search(text), text
        assert not CONFIGURATIONS.search(text), text


# Fifth pass -------------------------------------------------------------------------------
# What a copier reads before paying: the preview of an anonymous upload, with the
# production settings, listed "the configurations tried" for an account; and the
# starting balance read Measured twice on the page while the JSON stores it Declared in
# the size table.

#: The accounts or signals an account's trials count, as its dimension and plan name them.
ACCOUNTS_OR_SIGNALS = {
    "es": "cuentas o señales",
    "en": "accounts or signals",
    "pt": "contas ou sinais",
}
#: Configurations, robots and optimisers: none of them on an account's preview.
NOT_AN_ACCOUNT = re.compile(
    r"configuraciones|configurations|configurações|\b(robot|robots|robô|robôs)\b", re.I
)


def _lockbox(page: str) -> list[str]:
    """The lines the preview's lockbox lists, as the reader gets them."""
    box = page.split("<div class='lockbox'", 1)[1].split("</ul>", 1)[0]
    return [_visible(item) for item in re.findall(r"<li>(.*?)</li>", box, re.S)]


def _production_app(tmp_path: Path) -> Any:
    """The service as production runs it since 9 Oct: paid mode, the preview with no
    account (``anon_preview``) and no free first report (``welcome_full_report``).
    Stripe and mail are configured but never reached."""
    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://rigor.example",
        free_mode=False,
        email_verification_required=True,
        email_token_secret="stable secret shared across replicas 1234567890",
        resend_api_key="re_test_0123456789abcdefghij",
        smtp_from="Rigor <hola@example.com>",
        stripe_secret_key="sk_live_x",
        stripe_webhook_secret="whsec_cuenta",
        approved_markets=frozenset({"MX"}),
        operator_contact="soporte@example.com",
        trusted_proxy_hops=1,
        anon_preview=True,
        welcome_full_report=False,
    )
    return create_app(settings, make_store(settings.database_url))


@pytest.fixture(scope="module")
def anonymous_previews(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """The Myfxbook statement uploaded with no account, once per language: its preview."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    app = _production_app(tmp_path_factory.mktemp("vista-previa-cuenta"))
    client = TestClient(
        app, base_url="https://rigor.example", headers={"X-Forwarded-For": "203.0.113.7"}
    )
    pages: dict[str, str] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "quant_trade.audit.market._download",
            lambda series, *_: (_ for _ in ()).throw(RuntimeError(f"network off ({series})")),
        )
        for locale in LOCALES:
            answer = client.post(
                "/audits",
                files={"report": ("statement.csv", synthetic_live_statement(), "text/csv")},
                data={"consent": "on", "locale": locale},
                follow_redirects=False,
            )
            assert answer.status_code == 303, answer.text[:300]
            location = answer.headers["location"]
            assert location.endswith("&acct=anon_preview"), location
            pages[locale] = client.get(f"{location}&lang={locale}").text
    yield pages


@pytest.mark.parametrize("locale", LOCALES)
def test_the_paid_preview_of_an_account_counts_accounts_not_configurations(
    anonymous_previews: dict[str, str], locale: str
) -> None:
    page = anonymous_previews[locale]
    text = _visible(page)
    # An account's preview, locked, with the full report on sale.
    assert LABELS[locale]["title_account"] in page
    assert LABELS[locale]["locked_intro"] in text
    items = _lockbox(page)
    gain = report.LOCKED_GAINS_ACCOUNT[locale]["multiplicity"]
    # The multiplicity line counts what the account's dimension and plan step count.
    assert gain in items, items
    assert report.LOCKED_GAINS[locale]["multiplicity"] not in items
    name = report._dimension_title("multiplicity", locale, account=True)
    assert ACCOUNTS_OR_SIGNALS[locale] in gain and ACCOUNTS_OR_SIGNALS[locale] in name
    assert name in text
    # Nowhere on the preview a configuration tried, a robot or an optimiser.
    assert not NOT_AN_ACCOUNT.search(text), NOT_AN_ACCOUNT.search(text)
    assert not ROBOT_ANYWHERE.search(text), ROBOT_ANYWHERE.search(text)
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("role", [*ownership.ROLES, None])
def test_the_preview_of_an_account_names_its_trials_in_every_voice(
    locale: str, role: str | None
) -> None:
    data = _with_role(_signal(locale), role)
    page = render_html(
        AuditResult.model_validate(data), watermark=True, free_mode=False, locale=locale
    )
    items = _lockbox(page)
    gain = report.LOCKED_GAINS_ACCOUNT[locale]["multiplicity"]
    assert gain in items and report.LOCKED_GAINS[locale]["multiplicity"] not in items
    # The plan's step names the same accounts or signals, in the declared voice.
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    text = _visible(page)
    assert ACCOUNTS_OR_SIGNALS[locale] in step.title and step.title in text
    # Nowhere on the preview, in any voice, a configuration tried, a robot or an optimiser.
    assert not NOT_AN_ACCOUNT.search(text), NOT_AN_ACCOUNT.search(text)
    assert not ROBOT_ANYWHERE.search(text), ROBOT_ANYWHERE.search(text)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_backtests_preview_keeps_the_configurations_tried(locale: str) -> None:
    page = render_html(_backtest_result(locale), watermark=True, free_mode=False, locale=locale)
    items = _lockbox(page)
    assert report.LOCKED_GAINS[locale]["multiplicity"] in items
    assert report.LOCKED_GAINS_ACCOUNT[locale]["multiplicity"] not in items


@pytest.fixture(scope="module")
def uploaded_account(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Any, str]]:
    """The Myfxbook statement uploaded in free mode: its full page and its JSON."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    path = tmp_path_factory.mktemp("cuenta-json")
    settings = AuditSettings(
        database_url=f"sqlite:///{path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "quant_trade.audit.market._download",
            lambda series, *_: (_ for _ in ()).throw(RuntimeError(f"network off ({series})")),
        )
        answer = client.post(
            "/audits",
            files={"report": ("statement.csv", synthetic_live_statement(), "text/csv")},
            data={"consent": "on", "locale": "es"},
            follow_redirects=False,
        )
        assert answer.status_code == 303, answer.text[:300]
        yield client, answer.headers["location"]


@pytest.mark.parametrize("locale", LOCALES)
def test_an_uploaded_accounts_page_shows_the_tags_its_json_stores(
    uploaded_account: tuple[Any, str], locale: str
) -> None:
    client, location = uploaded_account
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1].split("&")[0]
    stored = client.get(f"/audits/{audit_id}.json?token={token}")
    assert stored.status_code == 200
    data = stored.json()
    assert data["reconciliation"]["initial_capital"]["evidence"] == "MEASURED"
    assert data["challenge"]["sizing"]["starting_balance"]["evidence"] == "DECLARED"
    page = client.get(f"{location}&lang={locale}").text
    _balance_lines(_visible(page), data, locale, account=True)


@pytest.fixture(scope="module")
def sample_pages(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    """The service's public samples, as /ejemplo, /sample and their signal serve them."""
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    path = tmp_path_factory.mktemp("muestras")
    settings = AuditSettings(
        database_url=f"sqlite:///{path}/audit.db", base_url="https://audit.example"
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "quant_trade.audit.market._download",
            lambda series, *_: (_ for _ in ()).throw(RuntimeError(f"network off ({series})")),
        )
        yield TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", LOCALES)
def test_the_served_samples_show_each_starting_balance_as_stored(
    sample_pages: Any, locale: str
) -> None:
    from quant_trade.audit.seo import SIGNAL_SAMPLE_PATHS

    backtest = sample_pages.get(report.SAMPLE_PATHS[locale])
    assert backtest.status_code == 200
    text = _visible(backtest.text)
    # /ejemplo and /sample read as in e1df258, and as their JSON stores them.
    for line in BACKTEST_BALANCE_LINES[locale]:
        assert line in text, line
    _balance_lines(text, _backtest_result(locale).model_dump(mode="json"), locale, account=False)
    signal = sample_pages.get(SIGNAL_SAMPLE_PATHS[locale])
    assert signal.status_code == 200
    _balance_lines(_visible(signal.text), _signal(locale), locale, account=True)


def test_every_fifth_pass_text_exists_in_three_languages_and_passes_the_guard() -> None:
    texts: list[str] = []
    for locale in LOCALES:
        gain = report.LOCKED_GAINS_ACCOUNT[locale]["multiplicity"]
        line = LABELS[locale]["ch_size_balance_declared"]
        if locale != "en":
            assert gain != report.LOCKED_GAINS_ACCOUNT["en"]["multiplicity"]
            assert line != LABELS["en"]["ch_size_balance_declared"]
        assert set(report.LOCKED_GAINS_ACCOUNT[locale]) <= set(report.LOCKED_GAINS[locale])
        assert FILE_DECLARES[locale] in line and "{balance}" in line
        texts += [gain, line]
    for text in texts:
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
        assert not NOT_AN_ACCOUNT.search(text) and not ROBOT_ANYWHERE.search(text), text
