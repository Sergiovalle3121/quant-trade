"""The firm table, useful to decide a challenge: the ladder's out-of-sample and
cost scenarios for every program, each program's rules with their source and
reading date, programs whose markets the history does not trade left last, one
phase against several in the target column, and the MT5 sample's header read
in full (the platform's drawdown with open trades and the modelling mode).
Offline."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import analytics, engine, firmfit, ownership
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.prop_presets import (
    ALPHA_ASSETS_URL,
    E8_OVERVIEW_URL,
    FUNDINGPIPS_STANDARD_URL,
    MARKETS,
    MAVEN_FAQ_URL,
    PRESETS,
    TOPSTEP_PRODUCTS_URL,
    ChallengeRules,
)
from quant_trade.audit.report import (
    KEY_LABELS,
    LABELS,
    _challenge_ladder_html,
    _challenge_sizing_html,
    _firm_fit_html,
    render_html,
)
from quant_trade.audit.sample import _sample_report, sample_result
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

NOW = datetime(2026, 10, 1, tzinfo=UTC)
LOCALES = ("es", "en", "pt")
TOPSTEP = ("topstep-50k-combine", "topstep-100k-combine", "topstep-150k-combine")
#: Every program whose page says it is futures only: Topstep's and E8 Markets' Zero,
#: in the order the presets list them (the order the left-out rows keep).
FUTURES_ONLY = (*TOPSTEP, "e8-zero-100k")
#: Advice the new texts must never give, in any of its languages.
ADVICE = (
    "aprobar",
    "aprueba",
    "pasar seguro",
    "pasarás",
    "recomend",
    "te conviene",
    "approve",
    "you will pass",
    "should use",
    "aprovar",
    "garantiza",
    "verificado",
    "certificado",
    "rentable",
)
#: Every preset's numeric rules: the markets field must not move any of them.
NUMERIC = {
    "generic-2step-phase1": (0.10, 0.05, 0.10, 4, None),
    "ftmo-2step-phase1": (0.10, 0.05, 0.10, 4, None),
    "ftmo-2step-phase2": (0.05, 0.05, 0.10, 4, None),
    "ftmo-1step": (0.10, 0.03, 0.10, 0, 0.50),
    "fundednext-stellar-2step-phase1": (0.08, 0.05, 0.10, 5, None),
    "fundednext-stellar-2step-phase2": (0.05, 0.05, 0.10, 5, None),
    "fundednext-stellar-1step": (0.10, 0.03, 0.06, 2, None),
    "fundednext-stellar-lite-phase1": (0.08, 0.04, 0.08, 5, None),
    "fundednext-stellar-lite-phase2": (0.04, 0.04, 0.08, 5, None),
    "the5ers-high-stakes-step1": (0.10, 0.05, 0.10, 3, None),
    "the5ers-high-stakes-step2": (0.05, 0.05, 0.10, 3, None),
    "the5ers-hyper-growth": (0.10, None, 0.06, 0, None),
    "the5ers-bootcamp-step": (0.06, None, 0.05, 0, None),
    "topstep-50k-combine": (0.06, None, 0.04, 2, 0.55),
    "topstep-100k-combine": (0.06, None, 0.03, 2, 0.55),
    "topstep-150k-combine": (0.06, None, 0.03, 2, 0.55),
    "fundingpips-2step-standard-phase1": (0.08, 0.05, 0.10, 3, None),
    "fundingpips-2step-standard-phase2": (0.05, 0.05, 0.10, 3, None),
    "fundingpips-2step-pro-phase1": (0.06, 0.03, 0.06, 0, None),
    "fundingpips-2step-pro-phase2": (0.06, 0.03, 0.06, 0, None),
    "fundingpips-2step-flex-phase1": (0.10, 0.04, 0.12, 1, None),
    "fundingpips-2step-flex-phase2": (0.08, 0.04, 0.12, 1, None),
    "fundingpips-1step-flex": (0.12, 0.03, 0.12, 0, None),
    "alpha-pro-8-phase1": (0.08, 0.04, 0.08, 3, None),
    "alpha-pro-8-phase2": (0.05, 0.04, 0.08, 3, None),
    "alpha-pro-10-phase1": (0.10, 0.05, 0.10, 3, None),
    "alpha-pro-10-phase2": (0.05, 0.05, 0.10, 3, None),
    "alpha-pro-6-phase1": (0.06, 0.03, 0.06, 3, None),
    "alpha-pro-6-phase2": (0.06, 0.03, 0.06, 3, None),
    "alpha-swing-phase1": (0.10, 0.05, 0.10, 3, None),
    "alpha-swing-phase2": (0.05, 0.05, 0.10, 3, None),
    "e8-signature-100k": (0.06, None, 0.03, 0, None),
    "e8-zero-100k": (0.065, None, 0.03, 0, 0.40),
    "fxify-2phase-classic-phase1": (0.05, 0.04, 0.10, 5, None),
    "fxify-2phase-classic-phase2": (0.10, 0.04, 0.10, 5, None),
    "fxify-3phase-step": (0.05, 0.05, 0.05, 5, None),
    "maven-3step-step": (0.03, 0.02, 0.03, 0, None),
}


def _declared(**changes: Any) -> DeclaredMetadata:
    values: dict[str, Any] = {
        "trials": 120,
        "cost_bps_per_side": 1.0,
        "oos_start": "2024-06-03",
        "challenge": "ftmo-2step-phase1",
    }
    values.update(changes)
    return DeclaredMetadata(**values)


def _audit(**changes: Any) -> tuple[Any, AuditResult]:
    inputs = build_inputs(
        None,
        _declared(**changes),
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
        now=NOW,
    )
    result = run(inputs)
    return inputs, result


def run(inputs: Any) -> AuditResult:
    return engine.run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=500
    )


@pytest.fixture(scope="module")
def ftmo() -> tuple[Any, AuditResult]:
    return _audit()


@pytest.fixture(scope="module")
def sample() -> AuditResult:
    return sample_result("es")


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _row(fit: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return next(row for row in fit["firms"] if row["keys"] == keys)


# ------------------------------------------------------------ 1. the columns


@pytest.mark.parametrize("key", ["ftmo-2step-phase1", "ftmo-1step"])
def test_the_chosen_program_columns_are_the_ladder_rungs(
    ftmo: tuple[Any, AuditResult], key: str
) -> None:
    inputs, result = ftmo if key == "ftmo-2step-phase1" else _audit(challenge=key)
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    rungs = {row["key"]: row for row in result.challenge["scenarios"]["rows"]}
    row = _row(fit, firmfit.program_keys(key))
    assert [column["key"] for column in fit["scenarios"]] == list(firmfit.SCENARIO_COLUMNS)
    for name in firmfit.SCENARIO_COLUMNS:
        rung = rungs[name]
        assert rung["pass"]["evidence"] == "MEASURED"
        figures = row["scenarios"][name]
        assert figures["pass"] == rung["pass"]
        assert figures["main_risk"] == rung["main_risk"]
        assert figures.get("pass_within_best_day") == rung.get("pass_within_best_day")
    # The columns are named as the ladder names its rungs.
    columns = {column["key"]: column for column in fit["scenarios"]}
    assert columns["out_of_sample"]["from"] == rungs["out_of_sample"]["from"] == "2024-06-03"
    assert (
        columns["reference_cost"]["cost_bps_per_side"]
        == rungs["reference_cost"]["cost_bps_per_side"]
    )
    assert columns["reference_cost"]["cost_bps_per_side"]["evidence"] == "DECLARED"
    # The full-history column did not move: it is still the ladder's full rung.
    assert row["pass"] == rungs["full"]["pass"]
    assert inputs is not None


def test_the_other_programs_run_the_same_series_as_the_ladder(
    ftmo: tuple[Any, AuditResult],
) -> None:
    inputs, result = ftmo
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    outside = daily[daily.index >= pd.Timestamp("2024-06-03", tz=daily.index.tz)]
    other = firmfit.program_keys("fundednext-stellar-2step-phase1")
    again = firmfit.program_pass(outside, other[0], samples=500, seed=12345)
    figures = _row(fit, other)["scenarios"]["out_of_sample"]
    assert figures["pass"] == again["pass"]
    assert figures["main_risk"] == again["main_risk"]
    # With the cost and out of sample the figure falls, as the ladder says it can.
    for row in fit["firms"]:
        if not row.get("pass"):
            continue
        assert float(row["scenarios"]["reference_cost"]["pass"]["value"]) <= float(
            row["pass"]["value"]
        )


def test_a_rung_the_ladder_cannot_measure_says_why_in_the_firm_table() -> None:
    _, result = _audit(oos_start=None)
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    columns = {column["key"]: column for column in fit["scenarios"]}
    rung = next(r for r in result.challenge["scenarios"]["rows"] if r["key"] == "out_of_sample")
    assert columns["out_of_sample"]["pass"] == rung["pass"]
    assert columns["out_of_sample"]["pass"]["evidence"] == "NOT_MEASURED"
    assert all("out_of_sample" not in (row.get("scenarios") or {}) for row in fit["firms"])
    for locale in LOCALES:
        labels = LABELS[locale]
        page = html.unescape(_firm_fit_html(fit, labels, ladder=True, locale=locale))
        reason = localize(str(rung["pass"]["note"]), locale)
        assert f"{labels['ch_ladder_low_out_of_sample'][:1].upper()}" in page
        assert reason in page
        assert labels["ch_ladder_cost_declared"].format(bps="1") in page
        assert find_claims(_visible(page)) == []


def test_the_columns_use_the_firm_table_sample_count() -> None:
    # Measured on the sample and with FTMO chosen: well under 2 s each, so the
    # columns keep the firm table's paths per phase.
    assert engine.FIRM_SCENARIO_SAMPLES == firmfit.SAMPLES


# ------------------------------------------------- 2. rules, source and date


def test_every_row_carries_its_rules_from_prop_presets(ftmo: tuple[Any, AuditResult]) -> None:
    _, result = ftmo
    assert result.challenge is not None
    for row in result.challenge["firm_fit"]["firms"]:
        first = PRESETS[row["keys"][0]]
        assert row["source_url"] == first.source_url and row["as_of"] == first.as_of
        expected = [
            {field: PRESETS[key].to_dict()[field] for field in firmfit.RULE_FIELDS}
            for key in row["keys"]
        ]
        assert row["rules"] == expected


@pytest.mark.parametrize("locale", LOCALES)
def test_the_rules_line_shows_what_each_program_has(
    ftmo: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = ftmo
    assert result.challenge is not None
    labels = LABELS[locale]
    fit = result.challenge["firm_fit"]
    page = _firm_fit_html(fit, labels, ladder=True, locale=locale)
    for row in fit["firms"]:
        start = page.index(html.escape(f"{row['firm']} · {row['program']}"))
        cell = html.unescape(page[start : page.index("</td>", start)])
        assert labels["ff_rules"] in cell
        assert labels["ff_rule_read"].format(date=row["as_of"]) in cell
        assert f"href='{row['source_url']}'" in cell
        phase = row["rules"][0]
        daily = phase["max_daily_loss"]
        # A field the program does not have is not shown.
        assert (labels["ff_rule_daily_initial"].split("}")[1] in cell) == (
            daily is not None and phase["daily_loss_basis"] == "initial_balance"
        )
        assert (labels["ff_rule_daily_day"].split("}")[1] in cell) == (
            phase["daily_loss_basis"] == "start_of_day"
        )
        days = phase["min_trading_days"]
        # One day reads in the singular (FundingPips 2-Step Flex asks for 1).
        wanted = labels["ff_rule_day"] if days == 1 else labels["ff_rule_days"].format(n=days)
        assert (wanted in cell) == (days > 0)
        assert labels["ff_rule_days"].format(n=1) not in cell
        best = phase["best_day_limit"]
        assert (f"{best * 100:g}%" in cell) if best else True
        # A program whose page lists its markets says which, when read and where.
        markets = PRESETS[row["keys"][0]].markets_as_of
        shown = labels["ff_rule_markets"].split("{")[0].capitalize()
        assert (shown in cell) == (markets is not None)
        if markets is not None:
            assert f"href='{PRESETS[row['keys'][0]].markets_source}'" in cell
    ftmo_cell = html.unescape(page[page.index("FTMO · FTMO Challenge 2-Step") :])
    ftmo_cell = ftmo_cell[: ftmo_cell.index("</td>")]
    for value, phase in (("10%", 1), ("5%", 2)):
        assert labels["ff_rule_in_phase"].format(value=value, n=phase) in ftmo_cell
    assert labels["ff_rule_total_static"].format(value="10%") in ftmo_cell
    one_step = html.unescape(page[page.index("FTMO · FTMO Challenge 1-Step") :])
    one_step = one_step[: one_step.index("</td>")]
    assert labels["ff_rule_total_trailing"].format(value="10%") in one_step
    assert labels["ff_rule_best_positive"].format(value="50%") in one_step
    assert find_claims(_visible(page)) == []


# ------------------------------------------------------------- 3. markets


def test_only_programs_whose_pages_name_their_markets_have_them() -> None:
    named = {key for key, rules in PRESETS.items() if rules.markets is not None}
    alpha = {key for key, rules in PRESETS.items() if rules.firm == "Alpha Capital Group"}
    assert named == {
        *TOPSTEP,
        "the5ers-high-stakes-step1",
        "the5ers-high-stakes-step2",
        "the5ers-hyper-growth",
        "fundingpips-2step-standard-phase1",
        "fundingpips-2step-standard-phase2",
        *alpha,
        "e8-zero-100k",
        "maven-3step-step",
    }
    # Each from the page that says so: Alpha's assets list has no crypto.
    for key in alpha:
        assert PRESETS[key].markets_source == ALPHA_ASSETS_URL
        assert "crypto" not in (PRESETS[key].markets or ())
    assert PRESETS["e8-zero-100k"].markets == ("futures",)
    assert PRESETS["e8-zero-100k"].markets_source == E8_OVERVIEW_URL
    assert PRESETS["fundingpips-2step-standard-phase1"].markets_source == FUNDINGPIPS_STANDARD_URL
    assert PRESETS["maven-3step-step"].markets_source == MAVEN_FAQ_URL
    assert [key for key in PRESETS if PRESETS[key].markets == ("futures",)] == list(FUTURES_ONLY)
    for key in TOPSTEP:
        rules = PRESETS[key]
        assert rules.markets == ("futures",) and rules.markets_source == TOPSTEP_PRODUCTS_URL
        assert rules.markets_as_of
    assert all(set(PRESETS[key].markets or ()) <= set(MARKETS) for key in PRESETS)
    with pytest.raises(ValueError):
        ChallengeRules(**{**_fields("ftmo-1step"), "markets": ("stocks",)})
    with pytest.raises(ValueError):
        ChallengeRules(**{**_fields("ftmo-1step"), "markets": ("fx",)})


def _fields(key: str) -> dict[str, Any]:
    rules = PRESETS[key]
    return {name: getattr(rules, name) for name in rules.__dataclass_fields__}


def test_the_markets_field_moves_no_numeric_rule() -> None:
    assert set(NUMERIC) == set(PRESETS)
    for key, (target, daily, total, days, best) in NUMERIC.items():
        rules = PRESETS[key]
        assert (
            rules.profit_target,
            rules.max_daily_loss,
            rules.max_total_loss,
            rules.min_trading_days,
            rules.best_day_limit,
        ) == pytest.approx((target, daily, total, days, best)), key


def _daily(seed: int = 3, n: int = 400) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0012, 0.008, n)


def test_topstep_goes_last_and_marked_with_a_forex_history() -> None:
    fit = firmfit.firm_fit(_daily(), samples=300, seed=7, symbols=["EURUSD", "GBPUSD"])
    assert fit["history_markets"] == ["fx"]
    rows = fit["firms"]
    tail = rows[-len(FUTURES_ONLY) :]
    assert [row["keys"] for row in tail] == [[key] for key in FUTURES_ONLY]
    for row in tail:
        assert "pass" not in row and "main_risk" not in row
        assert row["market"] == {
            "allowed": ["futures"],
            "history": ["fx"],
            "symbols": ["EURUSD", "GBPUSD"],
            "symbol_count": 2,
            "spot": True,
            "source_url": PRESETS[row["keys"][0]].markets_source,
            "as_of": PRESETS[row["keys"][0]].markets_as_of,
        }
    head = rows[: -len(FUTURES_ONLY)]
    assert all(row.get("pass") and not row.get("market") for row in head)
    figures = [(row.get("pass_within_best_day") or row["pass"])["value"] for row in head]
    assert figures == sorted(figures, reverse=True)
    # A metal pair is no futures contract either; a symbol the audit cannot place restricts nothing.
    gold = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=["XAUUSD"])
    assert all(_row(gold, [key]).get("market") for key in TOPSTEP)
    assert _row(gold, [TOPSTEP[0]])["market"]["history"] == ["metal"]
    unknown = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=["EURUSD", "AAPL"])
    assert "history_markets" not in unknown
    assert not any(row.get("market") for row in unknown["firms"])


def test_topstep_keeps_its_place_with_a_futures_history() -> None:
    plain = firmfit.firm_fit(_daily(), samples=300, seed=7)
    futures = firmfit.firm_fit(_daily(), samples=300, seed=7, symbols=["NQZ4", "ESH5"])
    assert futures["history_markets"] == ["us_equity"]
    assert futures["firms"] == plain["firms"]
    for key in TOPSTEP:
        row = _row(futures, [key])
        assert row["pass"]["evidence"] == "MEASURED" and "market" not in row
    # The ranking puts Topstep among the others by its figure, not at the end.
    figures = [(row.get("pass_within_best_day") or row["pass"])["value"] for row in plain["firms"]]
    assert figures == sorted(figures, reverse=True)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_left_out_row_says_why_and_shows_no_figure(locale: str) -> None:
    labels = LABELS[locale]
    fit = firmfit.firm_fit(_daily(), samples=200, seed=7, symbols=["EURUSD", "GBPUSD"])
    page = _firm_fit_html(fit, labels, locale=locale)
    rows = re.findall(r"<tr class='ff-out'>(.*?)</tr>", page, flags=re.S)
    assert len(rows) == len(FUTURES_ONLY)
    only = labels["ff_market_only"].format(markets=labels["ff_mk_futures"])
    why = labels["ff_market_why_spot"].format(
        history=labels["ff_hist_fx"], symbols="EURUSD, GBPUSD"
    )
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
        assert len(cells) == 2
        reason = html.unescape(cells[1])
        assert reason == f"{only}: {why}; {labels['ff_market_skip']}."
        assert "%" not in reason and "class='val'" not in row
    # The rules line names the page that says so and when it was read.
    assert f"href='{TOPSTEP_PRODUCTS_URL}'" in page and f"href='{E8_OVERVIEW_URL}'" in page
    assert page.rindex("ff-out") > page.index("<tbody>")
    text = _visible(page)
    assert find_claims(text) == []
    new = " ".join(
        labels[key] for key in labels if key.startswith(("ff_rule", "ff_mk", "ff_market"))
    )
    assert not [word for word in ADVICE if word in new.lower()]
    for key in (
        "ff_market_only",
        "ff_market_skip",
        "ff_market_why",
        "ff_market_why_spot",
        "ff_market_chosen",
        "ff_rule_markets",
        "ff_mk_futures",
    ):
        assert find_claims(labels[key]) == [], (locale, key)


def test_the_signal_sample_puts_topstep_last() -> None:
    from quant_trade.audit.sample import signal_sample_result

    result = signal_sample_result("en", bootstrap_samples=50)
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    assert fit["history_markets"] == ["fx"]
    tail = fit["firms"][-len(FUTURES_ONLY) :]
    assert [row["keys"] for row in tail] == [[k] for k in FUTURES_ONLY]
    head = fit["firms"][: -len(FUTURES_ONLY)]
    assert all(row["keys"][0] not in FUTURES_ONLY for row in head)
    # Its ladder cannot take the cost off a curve with deposits: neither can the table.
    columns = {column["key"]: column for column in fit["scenarios"]}
    assert columns["reference_cost"]["pass"]["evidence"] == "NOT_MEASURED"
    assert columns["out_of_sample"]["pass"]["evidence"] == "NOT_MEASURED"


# ------------------------------------------------- 5. one phase or several


@pytest.mark.parametrize("locale", LOCALES)
def test_one_phase_reaches_the_target_several_reach_it_in_every_phase(
    ftmo: tuple[Any, AuditResult], locale: str
) -> None:
    labels = LABELS[locale]
    one_label, all_label = labels["ch_ladder_pass_one"], labels["ch_ladder_pass"]
    assert one_label != all_label and all_label.startswith(one_label)
    _, two = ftmo
    _, generic = _audit(challenge=None)
    assert two.challenge is not None and generic.challenge is not None
    assert generic.challenge["preset"] == "generic-2step-phase1"
    assert generic.challenge["scenarios"]["program"]["phases"] == 1
    for result, wanted, unwanted in ((two, all_label, None), (generic, one_label, all_label)):
        assert result.challenge is not None
        ladder = html.unescape(
            _challenge_ladder_html(result.challenge["scenarios"], locale, labels)
        )
        sizing = html.unescape(
            _challenge_sizing_html(
                result.challenge["sizing"],
                locale,
                labels,
                rules=result.challenge["rules"],
                horizon=250,
            )
        )
        for page in (ladder, sizing):
            assert f"data-l='{wanted}'" in page
            if unwanted:
                assert unwanted not in page
    title = _visible(render_html(generic, watermark=False, locale=locale))
    assert all_label not in title


# ------------------------------------------------------------ 6. MT5 sample


def test_the_sample_header_states_the_platform_drawdown_and_real_ticks(
    sample: AuditResult,
) -> None:
    perf = sample.performance
    platform = perf["platform_equity_drawdown"]
    assert platform["evidence"] == "DECLARED"
    # Open trades only deepen the fall: the platform's is below the closed-trade one.
    assert float(platform["value"]) < float(perf["max_drawdown"]["value"]) < 0
    capital = sample.capital or {}
    assert float(capital["fall_platform"]["value"]) >= float(capital["fall_history"]["value"])
    review = sample.test_data or {}
    assert review["tick_model"] == {
        "value": "real ticks",
        "evidence": "DECLARED",
        "note": "the tester's modelling mode, as printed in the report header",
    }
    assert review["data_quality"]["value"] == 1.0 and review["clean"] is True
    # The modelling question is answered for the developer's own robot.
    data = sample.model_dump(mode="json")
    codes = [q["code"] for q in ownership.open_questions(data, ownership.OWN)]
    assert not [code for code in codes if code.startswith("modelling")]
    assert untranslated(data) == []


def test_the_sample_class_flags_and_landing_figures_hold(sample: AuditResult) -> None:
    assert sample.verdict.overall == "C"
    assert sample.red_flags == []
    assert round(float(sample.performance["sharpe"]["value"]), 1) == 1.8
    assert sample.multiplicity["trials_used"]["value"] == 120
    assert sample.live is not None and sample.live["outcome"] == "INCONSISTENT"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_sample_report_shows_the_platform_drawdown_in_every_language(locale: str) -> None:
    result = sample_result(locale)
    text = _visible(render_html(result, watermark=False, locale=locale))
    assert KEY_LABELS[locale]["platform_equity_drawdown"] in text
    unread = localize("the report does not state a modelling mode we recognise", locale)
    assert unread not in text
    assert find_claims(text) == []
    labels = LABELS[locale]
    # The firm table: rules, the two ladder columns and Topstep last.
    block = text[text.index(labels["ff_title"]) :]
    assert labels["ff_basis_columns"] in block
    assert labels["ch_ladder_out_of_sample"].format(date="2024-06-03") in block
    assert labels["ch_ladder_cost_declared"].format(bps="1") in block
    only = labels["ff_market_only"].format(markets=labels["ff_mk_futures"])
    assert block.index(only) > block.index("FTMO · FTMO Challenge 2-Step")
    # The size table gives the average lot.
    assert labels["ch_size_lots"].format(lots="0.50") in text
    new = " ".join(labels[key] for key in ("ff_basis_columns", "ff_clean_short", "ch_size_lot"))
    assert not [word for word in ADVICE if word in new.lower()]
