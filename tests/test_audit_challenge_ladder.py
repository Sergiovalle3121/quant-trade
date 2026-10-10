"""The challenge ladder: the chosen program on parts of the history and with
what the report discounts, next to the full-history figure. Offline."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in, trades_following

from quant_trade.audit import analytics, firmfit
from quant_trade.audit.engine import (
    LADDER_FLOWS,
    LADDER_NO_SEARCH,
    LADDER_NOT_MONEY,
    LADDER_NOT_SHOWN,
    LADDER_NOT_SHOWN_WHY,
    LADDER_NOTE,
    LADDER_RUIN,
    LADDER_UNDECLARED,
    _challenge_scenarios,
    _not_money_reason,
    run_audit,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.prop_presets import PRESETS, get_preset
from quant_trade.audit.report import (
    LABELS,
    _challenge_ladder_html,
    _firm_fit_html,
    _hero_challenge,
    _hidden_loss_note,
    render_html,
)
from quant_trade.audit.sample import _sample_report, synthetic_live_statement
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

NOW = datetime(2026, 10, 1, tzinfo=UTC)
KEY = "ftmo-2step-phase1"
ROWS = ["full", "in_sample", "out_of_sample", "reference_cost", "luck_haircut"]
LOCALES = ("es", "en", "pt")
HERO = {"es": "Reto elegido", "en": "Chosen challenge", "pt": "Desafio escolhido"}
OLD_UNFINISHED = {
    "es": "No termina a tiempo",
    "en": "Does not finish in time",
    "pt": "Não termina a tempo",
}
#: The reasons a reconciliation that was not measured gives for a separate curve.
UNRECONCILED = (
    "trades extend outside the curve dates",
    "closed trades do not cover the final part of the curve",
    "flows, currency conversion or open positions could explain the difference",
)
NEW_REASONS = (
    LADDER_NOTE,
    LADDER_NO_SEARCH,
    LADDER_UNDECLARED,
    LADDER_FLOWS,
    LADDER_NOT_MONEY,
    LADDER_NOT_SHOWN,
    *(LADDER_NOT_SHOWN_WHY.format(why=why) for why in UNRECONCILED),
    LADDER_RUIN,
)


def _declared(**changes: Any) -> DeclaredMetadata:
    values: dict[str, Any] = {
        "trials": 120,
        "cost_bps_per_side": 1.0,
        "oos_start": "2024-06-03",
        "challenge": KEY,
    }
    values.update(changes)
    return DeclaredMetadata(**values)


def _audit(
    declared: DeclaredMetadata,
    report: bytes | None = None,
    name: str = "SyntheticSampleEA.html",
) -> tuple[Any, AuditResult]:
    inputs = build_inputs(
        None,
        declared,
        report_bytes=report if report is not None else _sample_report(),
        report_filename=name,
        now=NOW,
    )
    result = run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=500
    )
    return inputs, result


@pytest.fixture(scope="module")
def audited() -> tuple[Any, AuditResult]:
    return _audit(_declared())


def _rows(result: AuditResult) -> dict[str, dict[str, Any]]:
    assert result.challenge is not None
    return {row["key"]: row for row in result.challenge["scenarios"]["rows"]}


def test_every_rung_is_measured_in_order(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    assert result.challenge is not None
    scenarios = result.challenge["scenarios"]
    assert scenarios["status"] == "MEASURED" and scenarios["note"] == LADDER_NOTE
    assert [row["key"] for row in scenarios["rows"]] == ROWS
    assert all(row["pass"]["evidence"] == "MEASURED" for row in scenarios["rows"])
    program = scenarios["program"]
    assert program["keys"] == firmfit.program_keys(KEY) == [KEY, "ftmo-2step-phase2"]
    assert program["phases"] == 2 and program["firm"] == "FTMO"


def test_the_full_rung_is_the_firm_table_row(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    assert result.challenge is not None
    firm_row = next(
        row
        for row in result.challenge["firm_fit"]["firms"]
        if row["keys"] == firmfit.program_keys(KEY)
    )
    assert _rows(result)["full"]["pass"]["value"] == firm_row["pass"]["value"]


def test_the_sides_split_the_days_at_the_declared_start(
    audited: tuple[Any, AuditResult],
) -> None:
    inputs, result = audited
    rows = _rows(result)
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    oos = int((daily.index >= pd.Timestamp("2024-06-03", tz="UTC")).sum())
    assert rows["out_of_sample"]["days"] == oos
    assert rows["in_sample"]["days"] == len(daily) - oos
    assert rows["full"]["days"] == len(daily)
    assert rows["in_sample"]["until"] == "2024-06-02"
    assert rows["out_of_sample"]["from"] == "2024-06-03"


def test_out_of_sample_and_cost_fall_below_the_full_history(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    rows = _rows(result)
    full = rows["full"]["pass"]["value"]
    assert rows["out_of_sample"]["pass"]["value"] < full
    assert rows["reference_cost"]["pass"]["value"] < full
    cost = rows["reference_cost"]["cost_bps_per_side"]
    assert cost["value"] == 1.0 and cost["evidence"] == "DECLARED"


def test_the_haircut_uses_the_luck_section(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    assert result.luck is not None
    row = _rows(result)["luck_haircut"]
    assert row["sharpe_after"]["value"] == result.luck["sharpe_after"]["value"]
    assert row["sharpe"]["value"] == result.luck["sharpe"]["value"]
    assert row["trials"]["value"] == 120 and row["trials"]["evidence"] == "DECLARED"


def test_the_ladder_is_deterministic(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    _, again = _audit(_declared())
    assert result.challenge is not None and again.challenge is not None
    assert again.challenge["scenarios"] == result.challenge["scenarios"]


def test_the_chosen_challenge_keeps_its_own_figures(audited: tuple[Any, AuditResult]) -> None:
    inputs, result = audited
    assert result.challenge is not None
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    alone = analytics.simulate_challenge(daily, get_preset(KEY), samples=500, seed=12345)
    assert result.challenge["probability"] == alone["probability"]
    assert result.challenge["pass_probability_ci95"] == alone["pass_probability_ci95"]


def test_a_one_phase_program_shows_the_section_figure_on_the_full_rung() -> None:
    _, result = _audit(_declared(challenge=None))
    assert result.challenge is not None
    assert result.challenge["preset"] == "generic-2step-phase1"
    rows = _rows(result)
    assert rows["full"]["pass"]["value"] == result.challenge["probability"]["pass"]["value"]
    assert rows["out_of_sample"]["pass"]["value"] < rows["full"]["pass"]["value"]


def test_the_intro_counts_phases_only_for_a_program_with_several(
    audited: tuple[Any, AuditResult],
) -> None:
    """The generic reference is named after its phase ("..., phase 1"), so the
    intro does not add "1 phase" after it; a two-phase program keeps its count."""
    _, one = _audit(_declared(challenge=None))
    _, two = audited
    assert one.challenge is not None and two.challenge is not None
    for locale in LOCALES:
        labels = LABELS[locale]
        single = html.unescape(_challenge_ladder_html(one.challenge["scenarios"], locale, labels))
        double = html.unescape(_challenge_ladder_html(two.challenge["scenarios"], locale, labels))
        assert labels["ch_ladder_title"] in single and labels["ch_ladder_title"] in double
        assert f", {labels['ff_phase']})" not in single
        assert f", {labels['ff_phases'].format(n=2)})" in double


def test_without_a_start_the_sides_are_not_measured() -> None:
    _, result = _audit(_declared(oos_start=None))
    rows = _rows(result)
    assert rows["full"]["pass"]["evidence"] == "MEASURED"
    for key in ("in_sample", "out_of_sample"):
        assert rows[key]["pass"]["evidence"] == "NOT_MEASURED"
        assert rows[key]["pass"]["note"] == "no out-of-sample start declared"


def test_without_a_declared_trial_count_the_haircut_says_the_count_is_missing() -> None:
    # Computed with 1, the most favourable case: not evidence that nothing was
    # searched, so the row does not say "fewer than 2 trials".
    _, result = _audit(_declared(trials_declared=False))
    assert result.luck is not None and not result.luck["counted"]
    row = _rows(result)["luck_haircut"]
    assert row["pass"]["evidence"] == "NOT_MEASURED"
    assert row["pass"]["note"] == LADDER_UNDECLARED


def test_one_declared_trial_has_no_search_to_discount() -> None:
    _, result = _audit(_declared(trials=1))
    assert result.luck is not None and not result.luck["counted"]
    row = _rows(result)["luck_haircut"]
    assert row["pass"]["evidence"] == "NOT_MEASURED"
    assert row["pass"]["note"] == LADDER_NO_SEARCH


def test_flows_inside_the_history_leave_the_cost_rung_out() -> None:
    _, result = _audit(_declared(), synthetic_live_statement(), "SyntheticSampleLive.csv")
    row = _rows(result)["reference_cost"]
    assert row["pass"]["evidence"] == "NOT_MEASURED"
    assert row["pass"]["note"] == LADDER_FLOWS


def test_a_curve_that_is_not_money_or_a_cost_that_ruins_it_leaves_the_rung_out(
    audited: tuple[Any, AuditResult],
) -> None:
    inputs, result = audited
    assert result.challenge is not None
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    sim = analytics.simulate_challenge(daily, get_preset(KEY), samples=500, seed=12345)

    def cost_row(
        reference: dict[str, Any], money_curve: bool, recon: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        scenarios = _challenge_scenarios(
            inputs,
            daily,
            KEY,
            sim,
            samples=500,
            seed=12345,
            holdout=result.holdout,
            reference=reference,
            money_curve=money_curve,
            luck=result.luck,
            reconciliation=recon,
        )
        return next(row for row in scenarios["rows"] if row["key"] == "reference_cost")

    declared = result.costs["reference_bps"]
    # Only a contradiction says the curve and the trades do not reconcile.
    contradiction = {
        "status": "CONTRADICTION",
        "reason": "printed balance contradicts deal amounts",
    }
    assert cost_row(declared, False, contradiction)["pass"]["note"] == LADDER_NOT_MONEY
    for why in UNRECONCILED:
        unmeasured = cost_row(declared, False, {"status": "NOT_MEASURED", "reason": why})
        assert unmeasured["pass"]["note"] == LADDER_NOT_SHOWN_WHY.format(why=why)
    assert cost_row(declared, False)["pass"]["note"] == LADDER_NOT_SHOWN
    ruin = cost_row({**declared, "value": 1_000_000.0}, True)
    assert ruin["pass"] == {"value": None, "evidence": "NOT_MEASURED", "note": LADDER_RUIN}
    same = cost_row(declared, True)
    assert same == _rows(result)["reference_cost"]


def _separate_upload(trades: pd.DataFrame, curve: pd.DataFrame) -> AuditResult:
    inputs = build_inputs(
        csv_bytes(curve),
        _declared(oos_start=None),
        trades_bytes=csv_bytes(trades),
        now=NOW,
    )
    return run_audit(inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=300)


def test_an_unmeasured_reconciliation_is_not_called_a_mismatch() -> None:
    curve = positive_drift(601)
    # Exact P&L, but only over the first half of the curve.
    tail = _separate_upload(trades_following(curve.iloc[:300], every=10), curve)
    # Every row covered, the money doubled: an unexplained gap, not a finding.
    doubled = trades_following(curve, every=25)
    doubled["quantity"] = doubled["quantity"] * 2
    gap = _separate_upload(doubled, curve)
    for result, why in (
        (tail, "closed trades do not cover the final part of the curve"),
        (gap, "flows, currency conversion or open positions could explain the difference"),
    ):
        assert result.reconciliation is not None
        assert result.reconciliation["status"] == "NOT_MEASURED"
        assert result.reconciliation["reason"] == why
        row = _rows(result)["reference_cost"]
        assert row["pass"]["evidence"] == "NOT_MEASURED"
        assert row["pass"]["note"] == LADDER_NOT_SHOWN_WHY.format(why=why)
        assert untranslated(result.model_dump(mode="json")) == []
        assert result.challenge is not None
        for locale in LOCALES:
            page = html.unescape(
                _challenge_ladder_html(result.challenge["scenarios"], locale, LABELS[locale])
            )
            assert localize(LADDER_NOT_SHOWN_WHY.format(why=why), locale) in page
            assert localize(why, locale) in page
            assert localize(LADDER_NOT_MONEY, locale) not in page
            assert find_claims(page) == []
    # The same curve with trades that realise it exactly is money.
    exact = _separate_upload(trades_following(curve, every=25), curve)
    assert exact.reconciliation is not None and exact.reconciliation["status"] == "MATCH"
    assert _rows(exact)["reference_cost"]["pass"]["evidence"] == "MEASURED"


def test_returns_are_not_money_in_their_own_words() -> None:
    inputs = build_inputs(
        None, _declared(), report_bytes=_sample_report(), report_filename="a.html", now=NOW
    )
    returns = replace(inputs, equity=replace(inputs.equity, source="returns"))
    recon = {"status": "NOT_MEASURED", "reason": "uploaded returns are not money"}
    assert _not_money_reason(returns, recon) == "uploaded returns are not money"
    assert _not_money_reason(inputs, None) == LADDER_NOT_SHOWN


def test_program_pass_matches_the_firm_table_for_every_program() -> None:
    daily = analytics.daily_returns_from_equity(
        build_inputs(
            None, _declared(), report_bytes=_sample_report(), report_filename="a.html", now=NOW
        ).equity.frame
    )
    fit = firmfit.firm_fit(daily, samples=300, seed=5)
    for row in fit["firms"]:
        again = firmfit.program_pass(daily, row["keys"][0], samples=300, seed=5)
        assert again["status"] == "MEASURED"
        assert again["pass"] == row["pass"] and again["keys"] == row["keys"]
    assert firmfit.program_keys("generic-2step-phase1") == ["generic-2step-phase1"]
    assert all(firmfit.program_keys(key)[0] in PRESETS for key in PRESETS)
    short = firmfit.program_pass([0.01, -0.01], KEY, samples=50, seed=0)
    assert short["status"] == "NOT_MEASURED" and short["reason"]


def test_new_sentences_read_in_every_language_and_pass_the_guard() -> None:
    for text in NEW_REASONS:
        assert find_claims(text) == []
        for locale in ("es", "pt"):
            shown = localize(text, locale)
            assert shown != text and find_claims(shown) == [], (locale, text)
    keys = [key for key in LABELS["es"] if key.startswith("ch_ladder_")]
    keys += ["hero_challenge", "hero_challenge_full", "hero_challenge_link", "unfinished_cap"]
    keys += ["hero_challenge_optimistic"]
    keys += ["ff_basis", "ff_risk_unfinished"]
    assert len(keys) > 15
    for locale in LOCALES:
        for key in keys:
            assert find_claims(LABELS[locale][key]) == [], (locale, key)
    for word in ("pasarás", "aprobar", "garantiza", "recomendado", "óptimo"):
        assert all(word not in LABELS["es"][key].lower() for key in keys)


def test_the_ladder_html_reads_not_measured_rows_with_their_reason() -> None:
    _, result = _audit(_declared(oos_start=None, trials_declared=False))
    assert result.challenge is not None
    assert untranslated(result.model_dump(mode="json")) == []
    for locale in LOCALES:
        labels = LABELS[locale]
        page = html.unescape(
            _challenge_ladder_html(result.challenge["scenarios"], locale, labels, optimistic=True)
        )
        assert labels["ch_ladder_title"] in page and labels["ff_optimistic"] in page
        assert localize("no out-of-sample start declared", locale) in page
        assert localize(LADDER_UNDECLARED, locale) in page
        assert localize(LADDER_NO_SEARCH, locale) not in page
        low = labels["ch_ladder_low_in_sample"]
        assert low[:1].upper() + low[1:] in page
        assert find_claims(page) == []
    fit = _firm_fit_html(result.challenge["firm_fit"], LABELS["es"], ladder=True)
    # The cost column is measured, so the basis names the columns; the
    # out-of-sample one is not, and says why with the ladder's own reason.
    assert LABELS["es"]["ff_basis_columns"] in html.unescape(fit)
    assert localize("no out-of-sample start declared", "es") in html.unescape(fit)
    assert LABELS["es"]["ff_basis_columns"] not in html.unescape(
        _firm_fit_html(result.challenge["firm_fit"], LABELS["es"])
    )


def _with_open_losses(result: AuditResult, **changes: Any) -> dict[str, Any]:
    data = result.model_dump(mode="json")
    data.update(changes)
    return data


def _platform_dd(result: AuditResult, value: float) -> dict[str, Any]:
    # The performance block with the platform's drawdown with open trades.
    drawdown = {"value": value, "evidence": "DECLARED", "note": "x"}
    return {**result.performance, "platform_equity_drawdown": drawdown}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_hero_line_repeats_the_open_loss_warning(
    audited: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = audited
    labels = LABELS[locale]
    warning = labels["hero_challenge_optimistic"]
    plain = html.unescape(_hero_challenge(result.model_dump(mode="json"), labels, "x"))
    assert HERO[locale] in plain and warning not in plain
    # The platform's drawdown with open trades breaks FTMO's 10 % total loss.
    deep = _with_open_losses(result, performance=_platform_dd(result, -0.15))
    line = html.unescape(_hero_challenge(deep, labels, "x"))
    assert HERO[locale] in line and warning in line
    assert find_claims(line) == []
    # Inside the limit, no warning.
    inside = _with_open_losses(result, performance=_platform_dd(result, -0.05))
    assert warning not in html.unescape(_hero_challenge(inside, labels, "x"))
    # Open losses the red flags found behind a balance-only file.
    flag = {"code": "HIDDEN_FLOATING_DRAWDOWN", "severity": "FAIL", "detail": "x"}
    hidden = _with_open_losses(result, red_flags=[*result.red_flags, flag])
    note = _hidden_loss_note(hidden, labels)
    assert note
    assert warning in html.unescape(_hero_challenge(hidden, labels, "x", note))


def test_the_report_puts_the_warning_next_to_the_hero_figure(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    deep = AuditResult.model_validate(
        _with_open_losses(result, performance=_platform_dd(result, -0.15))
    )
    text = _visible(render_html(deep, watermark=False, locale="es"))
    hero = text.index(HERO["es"])
    assert text.index(LABELS["es"]["hero_challenge_optimistic"]) < text.index(
        LABELS["es"]["hero_challenge_link"], hero
    )
    assert LABELS["es"]["open_loss_badge"] in text
    assert find_claims(text) == []


# --------------------------------------------------------------------- web


def _client(tmp_path: Path) -> Any:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
    )
    store = make_store(settings.database_url)
    return signed_in(TestClient(create_app(settings, store)))


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _report(client: Any, locale: str, *, challenge: str | None = KEY) -> tuple[str, str]:
    data = {
        "consent": "on",
        "locale": locale,
        "trials": "120",
        "cost_bps": "1",
        "oos_start": "2024-06-03",
    }
    if challenge:
        data["challenge"] = challenge
    files = {"report": ("SyntheticSampleEA.html", _sample_report(), "text/html")}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    location = response.headers["location"]
    page = client.get(location)
    assert page.status_code == 200
    return location, page.text


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_shows_the_ladder_and_the_hero_line(tmp_path: Path, locale: str) -> None:
    client = _client(tmp_path)
    location, page = _report(client, locale)
    text = _visible(page)
    labels = LABELS[locale]
    assert labels["ch_ladder_title"] in text
    # Two phases: the full history's figure is the firm table's, not phase 1's above.
    assert labels["ch_ladder_full_program"] in text
    assert labels["ch_ladder_in_sample"].format(date="2024-06-02") in text
    assert labels["ch_ladder_out_of_sample"].format(date="2024-06-03") in text
    assert labels["ch_ladder_cost_declared"].format(bps="1") in text
    assert labels["ch_ladder_haircut"].split("{")[0] in text
    assert HERO[locale] in text and labels["hero_challenge_link"] in text
    assert OLD_UNFINISHED[locale] not in text
    assert labels["unfinished_cap"].format(days=250) in text
    assert find_claims(text) == []
    if locale == "es":
        # The ladder stays in the private report: never on the public page.
        audit_id = location.split("/audits/")[1].split("?")[0]
        token = location.split("token=")[1]
        published = client.post(f"/audits/{audit_id}/publish?token={token}", follow_redirects=False)
        public = client.get(published.headers["location"]).text
        assert labels["ch_ladder_title"] not in public and HERO["es"] not in public


def test_the_default_challenge_shows_the_ladder_without_the_hero_line(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _, page = _report(client, "es", challenge=None)
    text = _visible(page)
    assert LABELS["es"]["ch_ladder_title"] in text
    # The generic preset is one phase: its full-history figure is the one above.
    assert LABELS["es"]["ch_ladder_full"] in text
    assert HERO["es"] not in text
    assert find_claims(text) == []
