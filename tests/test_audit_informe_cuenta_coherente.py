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

No figure, class or tag changes: every test reads the stored result as the
engine wrote it. Nothing reaches the network.
"""

from __future__ import annotations

import copy
import html
import re
from functools import cache
from typing import Any

import pytest

from quant_trade.audit import ownership, psr_names, report
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.report import (
    INTEGRITY_TEXT,
    KEY_LABELS,
    LABELS,
    declared_open_value,
    evidence_label,
    platform_label,
    render_html,
    unseen_open_loss,
)
from quant_trade.audit.sample import sample_result, signal_sample_result
from quant_trade.audit.schema import AuditResult, declared, measured, not_measured
from quant_trade.audit.verdict import meaning as verdict_meaning
from quant_trade.audit.verdict import trials_undeclared

LOCALES = ("es", "en", "pt")
#: The words the brief keeps out of every text.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable")
#: Robot and optimiser words an account or signal report must not use.
ROBOT = re.compile(r"\b(robot|robô|EA|XML|optimi[sz]ation|optimización|otimização)\b", re.I)
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
    labels = ownership.labels_for(LABELS[locale], locale, voice)
    keep = labels["next_keep_account"]
    assert not ROBOT.search(keep)
    page = _visible(render_html(AuditResult.model_validate(data), watermark=False, locale=locale))
    for shown in (oos, search, keep):
        assert shown in page
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
    warning = labels["ch_unseen_open"].format(share=f"{abs(share):.0%}")
    head = section[: section.index(fold)]
    # The warning comes before any simulated figure: no table and no value cell above it.
    assert html.escape(warning, quote=True) in head
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
    assert labels["platform_period_note"].format(first=first, last=last) in text
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
    net = live["backtest"]["avg_win"]["value"]
    gross = stats["average_win"]["value"]
    assert f"{net:,.2f}" != f"{gross:,.2f}"
    labels, keys = LABELS[locale], KEY_LABELS[locale]
    assert NET[locale] in labels["live_avg_win"] and GROSS[locale] in keys["average_win_gross"]
    text = _visible(render_html(_backtest_result(locale), watermark=False, locale=locale))
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
    "live_avg_win",
    "live_avg_loss",
    "data_period",
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
        for key in ("multiplicity.WEAK.account", "multiplicity.WEAK.undeclared.account"):
            texts.extend(voices[locale] for voices in ownership.MEANING[key].values())
        texts.extend(voices[locale] for voices in ownership.LABELS["next_keep_account"].values())
        texts.append(verdict_meaning("multiplicity", "WEAK", locale, account=True))
        texts.append(localize(psr_names.CLASS_NOTE, locale))
        if locale != "en":
            assert localize(psr_names.CLASS_NOTE, locale) != psr_names.CLASS_NOTE
    for text in texts:
        assert find_claims(text) == [], text
        assert not [word for word in BANNED if word in text.lower()], text
