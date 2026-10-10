"""The size table: the chosen program at 0.5x, 1x, 1.5x and 2x the history's
size, under the challenge ladder. Offline."""

from __future__ import annotations

import html
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, signed_in

from quant_trade.audit import analytics, engine, firmfit
from quant_trade.audit.engine import (
    RETURNS_NOT_MONEY,
    SIZING_ACCOUNT_LOT_NOTE,
    SIZING_ACCOUNT_LOT_ROW_NOTE,
    SIZING_ACCOUNT_NOTE,
    SIZING_BALANCE_ASSUMED,
    SIZING_BALANCE_CURVE,
    SIZING_BALANCE_NOTE,
    SIZING_LOT_NOTE,
    SIZING_LOT_ROW_NOTE,
    SIZING_MULTIPLIERS,
    SIZING_NO_ACCOUNT,
    SIZING_NO_ACCOUNT_BEFORE,
    SIZING_NO_SIZE,
    SIZING_NO_SIZE_BEFORE,
    SIZING_NOTE,
    run_audit,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.prop_presets import ACCOUNT_SIZES, PRESETS, get_preset
from quant_trade.audit.report import (
    LABELS,
    LOCKED_GAINS,
    _badge,
    _challenge_sizing_html,
    render_html,
)
from quant_trade.audit.sample import _sample_report, synthetic_mt5_report
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
    SIZING_BALANCE_NOTE,
    SIZING_BALANCE_CURVE,
    SIZING_BALANCE_ASSUMED,
    SIZING_LOT_ROW_NOTE,
    SIZING_LOT_NOTE.format(lots="641.00", count="1,282", traded="1,282.00"),
    SIZING_ACCOUNT_LOT_NOTE.format(account="100,000", balance="10,000"),
    SIZING_ACCOUNT_LOT_ROW_NOTE,
    # Stored results keep these; their rules stay.
    SIZING_NO_SIZE_BEFORE,
    SIZING_NO_ACCOUNT_BEFORE,
    firmfit.OUTCOME_NOTE,
)
#: The importer's own warning when the file states no starting balance.
ASSUMED_WARNING = (
    "the file does not state a starting balance; 10,000 was assumed, which scales every "
    "return and drawdown"
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


def test_the_average_lot_adds_up_by_hand(audited: tuple[Any, AuditResult]) -> None:
    inputs, result = audited
    sizing = _sizing(result)
    # The sample robot trades 0.5 lots on every one of its 1,282 trades.
    lots = inputs.trade_lots
    assert lots is not None and len(lots) == len(inputs.trades.trades) == 1282
    assert set(lots) == {0.5}
    by_hand = sum(lots) / len(lots)
    assert by_hand == 0.5
    note = SIZING_LOT_NOTE.format(lots="641.00", count="1,282", traded="1,282.00")
    assert sizing["size_per_trade"] == {"value": by_hand, "evidence": "MEASURED", "note": note}
    # The cost section divides by the lots traded counting entries and exits: twice as many.
    per_lot = result.costs["break_even_per_lot"]
    assert per_lot["evidence"] == "MEASURED" and "1,282.00 lots traded" in per_lot["note"]
    for row in sizing["rows"]:
        assert row["average_lot"] == {
            "value": pytest.approx(by_hand * row["multiplier"]),
            "evidence": "MEASURED",
            "note": SIZING_LOT_ROW_NOTE,
        }
    assert [row["average_lot"]["value"] for row in sizing["rows"]] == [0.25, 0.5, 0.75, 1.0]


def test_the_average_lot_follows_lots_that_vary() -> None:
    # Three lot sizes over a short history: the average is their mean, by hand.
    report = synthetic_mt5_report(120, lots=0.3, seed=11)
    inputs = build_inputs(
        None, _declared(oos_start=None), report_bytes=report, report_filename="r.html", now=NOW
    )
    assert inputs.trade_lots and set(inputs.trade_lots) == {0.3}
    per_lot = {"value": 1.0, "evidence": "MEASURED", "note": "x"}
    lot = engine._average_lot(inputs, per_lot)
    assert lot["value"] == pytest.approx(0.3) and lot["evidence"] == "MEASURED"
    varied = replace(inputs, trade_lots=[0.1, 0.2, 0.6] * 40)
    assert engine._average_lot(varied, per_lot)["value"] == pytest.approx(0.3)
    # Without the cost per lot measured, the lots are not summable: not measured.
    mixed = {"value": None, "evidence": "NOT_MEASURED", "note": engine.PER_LOT_MIXED}
    assert engine._average_lot(inputs, mixed) == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": engine.PER_LOT_MIXED,
    }
    assert engine._average_lot(inputs, None)["note"] == SIZING_NO_SIZE


def test_lot_and_account_are_never_invented(no_balance: AuditResult) -> None:
    # A plain trade list is not a MetaTrader report: its volume is not read as lots.
    sizing = _sizing(no_balance)
    assert sizing["size_per_trade"] == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": SIZING_NO_SIZE,
    }
    assert all("average_lot" not in row for row in sizing["rows"])
    # The reason no longer says the audit keeps no lot: it names where lots are read.
    assert "keeps neither the lot" not in SIZING_NO_SIZE and "MetaTrader 4 and 5" in SIZING_NO_SIZE
    _, result = _audit()
    sizing = _sizing(result)
    # FTMO's rules are shares of the balance: no account size either.
    assert sizing["account_size"]["evidence"] == "NOT_MEASURED"
    assert sizing["account_size"]["note"] == SIZING_NO_ACCOUNT
    topstep = _chosen("topstep-100k-combine")["sizing"]["account_size"]
    assert topstep == {"value": 100_000.0, "evidence": "DECLARED", "note": SIZING_ACCOUNT_NOTE}


def test_account_sizes_are_the_presets_own_dollar_conversions() -> None:
    # Topstep and E8 Markets state their limits in dollars at the size the program names.
    named = {k for k in PRESETS if k.startswith(("topstep-", "e8-"))}
    assert set(ACCOUNT_SIZES) == named
    dollars = {"topstep-50k-combine": 2_000, "topstep-100k-combine": 3_000}
    dollars["topstep-150k-combine"] = 4_500
    dollars |= {"e8-signature-100k": 3_000, "e8-zero-100k": 3_000}
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
    # 22 since ch_size_balance_declared (#489): the 1x line of an account names the file's balance.
    assert len(keys) == 22
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
    lot_note = SIZING_LOT_NOTE.format(lots="641.00", count="1,282", traded="1,282.00")
    for needed in (
        labels["ch_size_one"],
        labels["ch_size_lot"],
        labels["ch_size_lots_on"].format(
            lots=labels["ch_size_lots"].format(lots="0.50"), balance="10,000"
        ),
        localize(lot_note, locale),
        labels["ch_size_lot_col_on"].format(balance="10,000"),
        labels["ch_size_no_account_lots"].format(balance="10,000"),
        labels["ch_ladder_pass"],
        labels["fail_daily_loss"],
        labels["fail_total_loss"],
        # FTMO 2-Step: the simulator's cap, the ladder's words, once per phase.
        labels["ch_size_unfinished_phase"].format(days=250),
        labels["ch_size_cap"],
        # The sample report states its balance: 1x is measured on it.
        labels["ch_size_balance"].format(balance="10,000"),
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
        lot = f"{float(row['average_lot']['value']):.2f}"
        head = labels["ch_size_lot_col_on"].format(balance="10,000")
        lots = f"<td class='val' data-l='{head}'>{lot}</td>"
        cell = f"<td class='val' data-l='{labels['ch_ladder_pass']}'>{shown}</td>"
        assert f"<tr><td>{row['key']}</td>{lots}{cell}" in page
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


# ------------------------------------------------------- what 1x and the cap mean


def test_half_size_loses_passes_to_the_cap_not_to_the_limits(
    audited: tuple[Any, AuditResult],
) -> None:
    """Why the table says whose cap it is: at 0.5x FTMO 2-Step reaches the
    target less often only because more paths run out of simulated days."""
    _, result = audited
    rows = _rows(_sizing(result))
    half, one = rows["0.5x"], rows["1x"]
    assert float(half["pass"]["value"]) < float(one["pass"]["value"])
    assert float(half["unfinished"]["value"]) > float(one["unfinished"]["value"])
    for limit in ("fail_daily_loss", "fail_total_loss"):
        assert float(half[limit]["value"]) <= float(one[limit]["value"]), limit


@pytest.mark.parametrize("locale", LOCALES)
def test_the_cap_column_says_it_is_the_simulation_cap_per_phase(
    audited: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = audited
    assert result.challenge is not None
    labels = LABELS[locale]
    rules = result.challenge["rules"]
    two = html.unescape(
        _challenge_sizing_html(_sizing(result), locale, labels, rules=rules, horizon=250)
    )
    assert labels["ch_size_unfinished_phase"].format(days=250) in two
    # The intro says the target column counts only what arrives within the cap.
    intro = two.split("</p>", 1)[0]
    assert labels["ch_size_cap"] in intro and labels["ch_size_intro"].split("(")[0] in intro
    # One phase: the ladder's own words, with no "per phase".
    single = _chosen("ftmo-1step")
    one = html.unescape(
        _challenge_sizing_html(single["sizing"], locale, labels, rules=single["rules"], horizon=250)
    )
    assert labels["unfinished_cap"].format(days=250) in one and labels["ch_size_cap"] in one
    assert labels["ch_size_unfinished_phase"].format(days=250) not in one
    # A deadline the rules set is no simulator cap: neither sentence applies.
    deadline = {**rules, "time_limit_days": 30}
    timed = html.unescape(
        _challenge_sizing_html(_sizing(result), locale, labels, rules=deadline, horizon=21)
    )
    assert f"data-l='{labels['unfinished']}'" in timed
    assert labels["ch_size_cap"] not in timed
    assert labels["ch_size_unfinished_phase"].format(days=21) not in timed
    for text in (labels["ch_size_cap"], labels["ch_size_unfinished_phase"]):
        assert find_claims(text) == []


def _no_balance_trades(n: int = 300, seed: int = 3) -> bytes:
    """A trade list that states no balance anywhere: the importer assumes 10,000."""
    rng = np.random.default_rng(seed)
    lines = ["Symbol,Side,Quantity,Entry Time,Exit Time,Entry Price,Exit Price,Profit"]
    day = datetime(2023, 1, 2, 10, 0)
    for _ in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        move = float(rng.normal(0.0003, 0.003))
        close = day + timedelta(hours=2)
        lines.append(
            f"EURUSD,Buy,1,{day:%Y-%m-%d %H:%M:%S},{close:%Y-%m-%d %H:%M:%S},"
            f"1.10000,{1.1 + move:.5f},{move * 100_000:.2f}"
        )
        day += timedelta(days=1)
    return ("\n".join(lines) + "\n").encode()


def _no_balance_inputs(**changes: Any) -> Any:
    values: dict[str, Any] = {"challenge": "topstep-50k-combine", "oos_start": None}
    values.update(changes)
    return build_inputs(
        None,
        _declared(**values),
        report_bytes=_no_balance_trades(),
        report_filename="trades.csv",
        now=NOW,
    )


@pytest.fixture(scope="module")
def no_balance() -> AuditResult:
    inputs = _no_balance_inputs()
    assert inputs.initial_balance == 10_000.0
    assert f"report: {ASSUMED_WARNING}" in inputs.warnings
    return run_audit(inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=300)


def test_an_assumed_balance_is_named_and_never_declared(no_balance: AuditResult) -> None:
    sizing = _sizing(no_balance)
    assert sizing["status"] == "MEASURED"
    assert sizing["starting_balance"] == {
        "value": 10_000.0,
        "evidence": "NOT_MEASURED",
        "note": SIZING_BALANCE_ASSUMED,
    }
    # The program still names its own account: the two are not the same base.
    assert sizing["account_size"]["value"] == 50_000.0
    assert untranslated(no_balance.model_dump(mode="json")) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_says_1x_rests_on_an_assumed_balance(
    no_balance: AuditResult, locale: str
) -> None:
    assert no_balance.challenge is not None
    labels = LABELS[locale]
    text = _visible(render_html(no_balance, watermark=False, locale=locale))
    block = _size_block(text, labels)
    assumed = labels["ch_size_balance_assumed"].format(balance="10,000")
    assert assumed in block
    # On the 1x line, before the lot and the program's account.
    assert block.index(labels["ch_size_one"]) < block.index(assumed)
    assert block.index(assumed) < block.index(labels["ch_size_lot"])
    assert block.index(assumed) < block.index(labels["ch_size_account"].split("{")[0])
    assert labels["ch_size_balance"].split("{")[0] not in block
    page = html.unescape(
        _challenge_sizing_html(
            _sizing(no_balance),
            locale,
            labels,
            rules=no_balance.challenge["rules"],
            horizon=250,
        )
    )
    assert f"{assumed} {html.unescape(_badge('NOT_MEASURED'))}" in page
    assert find_claims(text) == []
    assert not [word for word in ADVICE if word in assumed.lower()], (locale, assumed)


def test_the_balance_1x_is_measured_on_follows_the_curve_it_comes_from() -> None:
    # Declared on the form, the importer builds the curve from it.
    declared_balance = engine._challenge(
        _no_balance_inputs(initial_balance=50_000), samples=200, seed=1
    )["sizing"]["starting_balance"]
    assert declared_balance == {
        "value": 50_000.0,
        "evidence": "DECLARED",
        "note": SIZING_BALANCE_NOTE,
    }
    # An uploaded curve carries its own shares: its first value, measured.
    curve = csv_bytes(positive_drift(400))
    inputs = build_inputs(curve, _declared(oos_start=None), now=NOW)
    first = float(inputs.equity.frame["equity"].iloc[0])
    sizing = engine._challenge(inputs, samples=200, seed=1)["sizing"]
    assert sizing["starting_balance"] == {
        "value": first,
        "evidence": "MEASURED",
        "note": SIZING_BALANCE_CURVE,
    }
    # Uploaded beside a report that states no balance, the curve still rules.
    both = build_inputs(
        curve,
        _declared(oos_start=None),
        report_bytes=_no_balance_trades(),
        report_filename="trades.csv",
        now=NOW,
    )
    assert f"report: {ASSUMED_WARNING}" in both.warnings and not both.balance_only
    assert engine._sizing_balance(both)["evidence"] == "MEASURED"
    # The column mapping builds the curve itself from the assumed balance.
    mapped = replace(inputs, warnings=[f"report: {ASSUMED_WARNING}", *inputs.warnings])
    assert engine._sizing_balance(mapped) == {
        "value": first,
        "evidence": "NOT_MEASURED",
        "note": SIZING_BALANCE_ASSUMED,
    }
    # A live statement's assumption is not the backtest's.
    live = replace(inputs, warnings=[f"live: {ASSUMED_WARNING}"])
    assert engine._sizing_balance(live)["evidence"] == "MEASURED"


def test_the_notes_say_what_scales_and_what_the_rules_fix() -> None:
    # Costs that grow with the size, not the same money per trade.
    assert "in proportion to the size (the same cost per lot)" in SIZING_NOTE
    assert "costs per trade" not in SIZING_NOTE
    assert "en proporción al tamaño (el mismo costo por lote)" in localize(SIZING_NOTE, "es")
    assert "na proporção do tamanho (o mesmo custo por lote)" in localize(SIZING_NOTE, "pt")
    # The firms sell named sizes; the simulated rules fix none, and some are
    # shares of the day's balance (The5ers High Stakes).
    assert "names no account" not in SIZING_NO_ACCOUNT
    assert get_preset("the5ers-high-stakes-step1").daily_loss_basis == "start_of_day"
    for locale, day in (("es", "del día"), ("en", "of the day's"), ("pt", "do dia")):
        assert day in LABELS[locale]["ch_size_no_account"], locale
        assert day in localize(SIZING_NO_ACCOUNT, locale), locale
    sizing = _chosen("the5ers-high-stakes-step1")["sizing"]
    assert sizing["status"] == "MEASURED"
    assert sizing["account_size"] == {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": SIZING_NO_ACCOUNT,
    }
