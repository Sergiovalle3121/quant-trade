"""The size table: the chosen program at 0.5x, 1x, 1.5x and 2x the history's
size, under the challenge ladder. Offline."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, signed_in

from quant_trade.audit import analytics, engine, firmfit
from quant_trade.audit.engine import (
    RETURNS_NOT_MONEY,
    SIZING_ACCOUNT_NOTE,
    SIZING_MULTIPLIERS,
    SIZING_NO_ACCOUNT,
    SIZING_NO_SIZE,
    SIZING_NOTE,
    run_audit,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.prop_presets import ACCOUNT_SIZES, PRESETS, get_preset
from quant_trade.audit.report import (
    LABELS,
    LOCKED_GAINS,
    _challenge_sizing_html,
    render_html,
)
from quant_trade.audit.sample import _sample_report
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

NOW = datetime(2026, 10, 1, tzinfo=UTC)
KEY = "ftmo-2step-phase1"
LOCALES = ("es", "en", "pt")
SIZES = ["0.5x", "1x", "1.5x", "2x"]
OUTCOMES = ("pass", "fail_daily_loss", "fail_total_loss", "unfinished")
#: The ladder's full row: the 1x row repeats every one of these fields.
FULL_FIELDS = ("days", "pass", "main_risk", "pass_within_best_day")
NEW_NOTES = (
    SIZING_NOTE,
    SIZING_NO_SIZE,
    SIZING_ACCOUNT_NOTE,
    SIZING_NO_ACCOUNT,
    firmfit.OUTCOME_NOTE,
)
#: Advice the table must never give, in any of its languages.
ADVICE = (
    "aprobar",
    "aprueba",
    "pasar seguro",
    "pasarás",
    "recomend",
    "usa 0.5x",
    "te conviene",
    "óptimo",
    "recommend",
    "approve",
    "you will pass",
    "should use",
    "aprovar",
    "use 0.5x",
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


def _inputs(**changes: Any) -> Any:
    return build_inputs(
        None,
        _declared(**changes),
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
        now=NOW,
    )


def _audit(**changes: Any) -> tuple[Any, AuditResult]:
    inputs = _inputs(**changes)
    result = run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=500
    )
    return inputs, result


@pytest.fixture(scope="module")
def audited() -> tuple[Any, AuditResult]:
    return _audit()


def _sizing(result: AuditResult) -> dict[str, Any]:
    assert result.challenge is not None
    return result.challenge["sizing"]


def _rows(sizing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in sizing["rows"]}


def _chosen(key: str, samples: int = 300) -> dict[str, Any]:
    """The challenge section for ``key`` on the sample history."""
    return engine._challenge(_inputs(challenge=key), samples=samples, seed=12345)


# ------------------------------------------------------------------ engine


def test_one_row_per_size_with_the_ladder_program(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    sizing = _sizing(result)
    assert sizing["status"] == "MEASURED" and sizing["note"] == SIZING_NOTE
    assert [row["key"] for row in sizing["rows"]] == SIZES
    assert [row["multiplier"] for row in sizing["rows"]] == list(SIZING_MULTIPLIERS)
    assert sizing["program"] == result.challenge["scenarios"]["program"]
    for row in sizing["rows"]:
        assert all(row[key]["evidence"] == "MEASURED" for key in OUTCOMES)


@pytest.mark.parametrize(
    "key", ["ftmo-2step-phase1", "ftmo-1step", "the5ers-bootcamp-step", "topstep-50k-combine"]
)
def test_the_1x_row_is_the_ladder_full_row(key: str) -> None:
    challenge = _chosen(key)
    full = next(row for row in challenge["scenarios"]["rows"] if row["key"] == "full")
    one = _rows(challenge["sizing"])["1x"]
    for field in FULL_FIELDS:
        assert one.get(field) == full.get(field), (key, field)
    # A program with a best-day rule keeps it in every row, as the ladder does.
    best_day = PRESETS[key].best_day_limit is not None
    assert all(("pass_within_best_day" in row) == best_day for row in challenge["sizing"]["rows"])


def test_the_1x_row_of_the_audit_is_the_ladder_full_row(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    assert result.challenge is not None
    full = result.challenge["scenarios"]["rows"][0]
    assert full["key"] == "full"
    one = _rows(_sizing(result))["1x"]
    assert {field: one.get(field) for field in FULL_FIELDS} == {
        field: full.get(field) for field in FULL_FIELDS
    }


@pytest.mark.parametrize(
    "key",
    ["ftmo-2step-phase1", "the5ers-bootcamp-step", "topstep-100k-combine", "generic-2step-phase1"],
)
def test_the_four_outcomes_of_every_row_sum_to_one(key: str) -> None:
    for row in _chosen(key)["sizing"]["rows"]:
        total = sum(float(row[outcome]["value"]) for outcome in OUTCOMES)
        assert total == pytest.approx(1.0, abs=1e-12), (key, row["key"])
        assert all(0.0 <= float(row[outcome]["value"]) <= 1.0 for outcome in OUTCOMES)


def test_program_outcomes_keep_program_pass_for_every_program() -> None:
    daily = analytics.daily_returns_from_equity(_inputs().equity.frame)
    for key in {firmfit.program_keys(k)[0] for k in PRESETS}:
        plain = firmfit.program_pass(daily, key, samples=200, seed=7)
        full = firmfit.program_outcomes(daily, key, samples=200, seed=7)
        assert {k: v for k, v in full.items() if k not in OUTCOMES[1:]} == plain, key
        total = float(full["pass"]["value"]) + sum(
            float(full[outcome]["value"]) for outcome in OUTCOMES[1:]
        )
        assert total == pytest.approx(1.0, abs=1e-12), key
    short = firmfit.program_outcomes([0.01, -0.01], KEY, samples=50, seed=0)
    assert short["status"] == "NOT_MEASURED" and short["reason"]


def test_double_size_breaks_the_total_loss_at_least_as_often(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    rows = _rows(_sizing(result))
    double = float(rows["2x"]["fail_total_loss"]["value"])
    single = float(rows["1x"]["fail_total_loss"]["value"])
    assert double >= single
    assert double > 0


def test_the_size_table_is_deterministic(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    _, again = _audit()
    assert _sizing(again) == _sizing(result)


def test_lot_and_account_are_never_invented(audited: tuple[Any, AuditResult]) -> None:
    _, result = audited
    sizing = _sizing(result)
    # The importers fold lots into units and read no stop loss: no lot is given.
    assert sizing["size_per_trade"] == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": SIZING_NO_SIZE,
    }
    # FTMO's rules are shares of the balance: no account size either.
    assert sizing["account_size"]["evidence"] == "NOT_MEASURED"
    assert sizing["account_size"]["note"] == SIZING_NO_ACCOUNT
    topstep = _chosen("topstep-100k-combine")["sizing"]["account_size"]
    assert topstep == {"value": 100_000.0, "evidence": "DECLARED", "note": SIZING_ACCOUNT_NOTE}


def test_account_sizes_are_the_presets_own_dollar_conversions() -> None:
    assert set(ACCOUNT_SIZES) == {k for k in PRESETS if k.startswith("topstep-")}
    dollars = {"topstep-50k-combine": 2_000, "topstep-100k-combine": 3_000}
    dollars["topstep-150k-combine"] = 4_500
    for key, account in ACCOUNT_SIZES.items():
        assert get_preset(key).max_total_loss * account == pytest.approx(dollars[key])
        assert get_preset(key).program.endswith(f"{int(account) // 1000}K")


def test_coarse_data_leaves_the_table_out_with_the_challenge_reason() -> None:
    weekly = positive_drift(200)
    weekly["timestamp"] = pd.date_range("2018-01-05", periods=200, freq="W-FRI", tz="UTC")
    inputs = build_inputs(csv_bytes(weekly), _declared(oos_start=None), now=NOW)
    challenge = engine._challenge(inputs, samples=100, seed=1)
    assert challenge["status"] == "NOT_MEASURED"
    assert challenge["sizing"] == {"status": "NOT_MEASURED", "reason": challenge["reason"]}


def test_too_few_days_leave_the_table_out_with_the_simulator_reason() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(30)), _declared(oos_start=None), now=NOW)
    challenge = engine._challenge(inputs, samples=100, seed=1)
    assert challenge["status"] == "NOT_MEASURED" and "29 supplied" in challenge["reason"]
    assert challenge["sizing"] == {"status": "NOT_MEASURED", "reason": challenge["reason"]}
    assert "scenarios" not in challenge


def test_an_unmeasured_full_rung_leaves_the_table_out_with_its_reason(
    audited: tuple[Any, AuditResult],
) -> None:
    inputs, result = audited
    assert result.challenge is not None
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    reason = "needs at least 30 daily returns that are not all identical; 2 supplied"
    scenarios = {
        **result.challenge["scenarios"],
        "rows": [
            {"key": "full", "pass": {"value": None, "evidence": "NOT_MEASURED", "note": reason}}
        ],
    }
    sizing = engine._challenge_sizing(inputs, daily, KEY, {}, scenarios, samples=100, seed=12345)
    assert sizing == {"status": "NOT_MEASURED", "reason": reason}


def test_returns_are_not_money_in_the_ladder_words(audited: tuple[Any, AuditResult]) -> None:
    inputs, result = audited
    returns = replace(inputs, equity=replace(inputs.equity, source="returns"))
    recon, _ = engine._reconciliation(returns)
    challenge = engine._challenge(
        returns,
        samples=300,
        seed=12345,
        holdout=result.holdout,
        reference=result.costs["reference_bps"],
        money_curve=False,
        luck=result.luck,
        reconciliation=recon,
    )
    cost = next(row for row in challenge["scenarios"]["rows"] if row["key"] == "reference_cost")
    assert recon["reason"] == RETURNS_NOT_MONEY == cost["pass"]["note"]
    assert challenge["sizing"] == {"status": "NOT_MEASURED", "reason": RETURNS_NOT_MONEY}
    # A returns file uploaded as such says the same.
    upload = build_inputs(csv_bytes(returns_frame(400)), _declared(oos_start=None), now=NOW)
    assert upload.equity.source == "returns"
    alone = engine._challenge(upload, samples=100, seed=1)
    assert alone["status"] == "MEASURED"
    assert alone["sizing"] == {"status": "NOT_MEASURED", "reason": RETURNS_NOT_MONEY}


def test_the_class_and_the_challenge_figures_do_not_move(
    audited: tuple[Any, AuditResult],
) -> None:
    inputs, result = audited
    assert result.challenge is not None
    daily = analytics.daily_returns_from_equity(inputs.equity.frame)
    alone = analytics.simulate_challenge(daily, get_preset(KEY), samples=500, seed=12345)
    assert result.challenge["probability"] == alone["probability"]
    firm = next(
        row
        for row in result.challenge["firm_fit"]["firms"]
        if row["keys"] == [KEY, "ftmo-2step-phase2"]
    )
    assert firm["pass"] == result.challenge["scenarios"]["rows"][0]["pass"]


# ------------------------------------------------------------------ texts


def test_new_sentences_read_in_every_language_and_pass_the_guard(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    assert untranslated(result.model_dump(mode="json")) == []
    for text in NEW_NOTES:
        assert find_claims(text) == []
        for locale in ("es", "pt"):
            shown = localize(text, locale)
            assert shown != text and find_claims(shown) == [], (locale, text)
    keys = [key for key in LABELS["es"] if key.startswith("ch_size_")]
    assert len(keys) == 9
    for locale in LOCALES:
        texts = [LABELS[locale][key] for key in keys] + [LOCKED_GAINS[locale]["ch_size_title"]]
        for key in keys:
            if locale == "pt":
                assert LABELS["pt"][key] != LABELS["en"][key], key
        for text in texts:
            assert find_claims(text) == [], (locale, text)
            assert not [word for word in ADVICE if word in text.lower()], (locale, text)
        # The lockbox names the table by its own title.
        assert LOCKED_GAINS[locale]["ch_size_title"].startswith(LABELS[locale]["ch_size_title"])


# ------------------------------------------------------------------ report


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _open_losses(result: AuditResult, value: float) -> AuditResult:
    """The same result with the platform's drawdown with open trades at ``value``."""
    data = result.model_dump(mode="json")
    drawdown = {"value": value, "evidence": "DECLARED", "note": "x"}
    data["performance"] = {**result.performance, "platform_equity_drawdown": drawdown}
    return AuditResult.model_validate(data)


def _size_block(text: str, labels: dict[str, str]) -> str:
    """The page text from the size table's title to the firm table's."""
    start = text.index(labels["ch_size_title"])
    return text[start : text.index(labels["ff_title"], start)]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_shows_the_size_table_and_the_open_loss_warning(
    audited: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = audited
    labels = LABELS[locale]
    text = _visible(render_html(result, watermark=False, locale=locale))
    ladder = text.index(labels["ch_ladder_title"])
    assert text.index(labels["ch_size_title"]) > ladder
    block = _size_block(text, labels)
    for needed in (
        labels["ch_size_one"],
        labels["ch_size_lot"],
        localize(SIZING_NO_SIZE, locale),
        labels["ch_size_no_account"],
        labels["ch_ladder_pass"],
        labels["fail_daily_loss"],
        labels["fail_total_loss"],
        labels["ch_size_unfinished"].format(days=250),
        *SIZES,
    ):
        assert needed in block, (locale, needed)
    assert labels["ff_optimistic"] not in block
    assert find_claims(text) == []
    # The platform's drawdown with open trades breaks FTMO's 10 % total loss.
    deep = _visible(render_html(_open_losses(result, -0.15), watermark=False, locale=locale))
    assert labels["ff_optimistic"] in _size_block(deep, labels)
    assert find_claims(deep) == []


def test_the_table_prints_the_ladder_formats_and_the_rules_it_has(
    audited: tuple[Any, AuditResult],
) -> None:
    _, result = audited
    assert result.challenge is not None
    labels = LABELS["es"]
    rules = result.challenge["rules"]
    page = html.unescape(
        _challenge_sizing_html(_sizing(result), "es", labels, rules=rules, horizon=250)
    )
    for row in _sizing(result)["rows"]:
        value = float(row["pass"]["value"])
        shown = "≥99%" if value >= 0.99 else f"{value:.0%}"
        cell = f"<td class='val' data-l='{labels['ch_ladder_pass']}'>{shown}</td>"
        assert f"<tr><td>{row['key']}</td>{cell}" in page
    assert labels["ff_clean"] not in page and labels["ff_no_rule"] not in page
    # Topstep: a best-day rule, no daily limit and an account size the program names.
    topstep = _chosen("topstep-100k-combine")
    shown = html.unescape(
        _challenge_sizing_html(topstep["sizing"], "es", labels, rules=topstep["rules"], horizon=250)
    )
    assert labels["ff_clean"] in shown and labels["ff_no_rule"] in shown
    assert labels["ch_size_account"].format(size="100,000") in shown
    assert labels["ch_size_no_account"] not in shown


@pytest.mark.parametrize("locale", LOCALES)
def test_a_table_not_measured_says_why(locale: str) -> None:
    labels = LABELS[locale]
    sizing = {"status": "NOT_MEASURED", "reason": RETURNS_NOT_MONEY}
    page = html.unescape(_challenge_sizing_html(sizing, locale, labels, rules={}, horizon=250))
    assert labels["ch_size_title"] in page and localize(RETURNS_NOT_MONEY, locale) in page
    assert "<table" not in page
    assert _challenge_sizing_html(None, locale, labels, rules={}, horizon=250) == ""


@pytest.mark.parametrize("locale", LOCALES)
def test_the_locked_preview_lists_the_size_table(
    audited: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = audited
    unpaid = render_html(
        result,
        watermark=True,
        free_mode=False,
        price_usd=29,
        checkout_url="/audits/abc123/checkout",
        locale=locale,
    )
    box = html.unescape(unpaid.split("class='lockbox'", 1)[1].split("class='lock-sample'", 1)[0])
    gains = LOCKED_GAINS[locale]
    assert LABELS[locale]["ch_size_title"] in box
    assert box.index(gains["challenge"]) < box.index(gains["ch_size_title"])
    assert find_claims(box) == []
    # The size table is not in the preview itself.
    assert LABELS[locale]["ch_size_one"] not in html.unescape(unpaid)
    # Without figures the lockbox does not offer it.
    data = result.model_dump(mode="json")
    data["challenge"] = {
        **data["challenge"],
        "sizing": {"status": "NOT_MEASURED", "reason": RETURNS_NOT_MONEY},
    }
    bare = render_html(
        AuditResult.model_validate(data),
        watermark=True,
        free_mode=False,
        price_usd=29,
        checkout_url="/audits/abc123/checkout",
        locale=locale,
    )
    assert gains["ch_size_title"] not in html.unescape(bare)


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


def test_an_upload_shows_the_size_table_in_its_language(tmp_path: Path) -> None:
    client = _client(tmp_path)
    data = {
        "consent": "on",
        "locale": "pt",
        "trials": "120",
        "cost_bps": "1",
        "oos_start": "2024-06-03",
        "challenge": KEY,
    }
    files = {"report": ("SyntheticSampleEA.html", _sample_report(), "text/html")}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    text = _visible(page.text)
    block = _size_block(text, LABELS["pt"])
    assert LABELS["pt"]["ch_size_one"] in block and all(size in block for size in SIZES)
    assert find_claims(text) == []
