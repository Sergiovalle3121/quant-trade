"""Review of the firm simulator: the average lot is the file balance's and is
scaled to the account a program names; a program whose page does not take the
history names only what it does not take, with gold and bitcoin pairs treated
alike; the chosen program keeps its figures and says so in every part of its
section; each row of the firm table warns when the platform's drawdown with
open trades reaches its own limit; the wording of the full-history column, of
the uniform sentence and of a one-phase size table; results stored before the
average lot; the rules open for print; the PDF cover keeps the Sharpe. Offline."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from quant_trade.audit import engine, firmfit
from quant_trade.audit.engine import (
    SIZING_ACCOUNT_LOT_NOTE,
    SIZING_ACCOUNT_LOT_ROW_NOTE,
    SIZING_NO_ACCOUNT,
    SIZING_NO_ACCOUNT_BEFORE,
    SIZING_NO_SIZE_BEFORE,
    run_audit,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.prop_presets import ACCOUNT_SIZES, TOPSTEP_PRODUCTS_URL
from quant_trade.audit.report import (
    LABELS,
    _challenge_sizing_html,
    _cover_kpis,
    _firm_fit_html,
    _kpi_list,
    _market_text,
    _rule_pct,
    render_html,
)
from quant_trade.audit.sample import _sample_report, sample_result
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs
from quant_trade.audit.theme import STATIC_DIR

NOW = datetime(2026, 10, 1, tzinfo=UTC)
LOCALES = ("es", "en", "pt")
TOPSTEP = ("topstep-50k-combine", "topstep-100k-combine", "topstep-150k-combine")
#: Every program whose page says it is futures only, in the presets' order.
FUTURES_ONLY = (*TOPSTEP, "e8-zero-100k")
CHOSEN = "topstep-100k-combine"
#: Words the new texts must never use, in any of its languages.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable", "recomend")


def _audit(challenge: str | None) -> tuple[Any, AuditResult]:
    declared = DeclaredMetadata(
        trials=120, cost_bps_per_side=1.0, oos_start="2024-06-03", challenge=challenge
    )
    inputs = build_inputs(
        None,
        declared,
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
        now=NOW,
    )
    return inputs, run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=500
    )


@pytest.fixture(scope="module")
def topstep() -> tuple[Any, AuditResult]:
    return _audit(CHOSEN)


@pytest.fixture(scope="module")
def ftmo() -> tuple[Any, AuditResult]:
    return _audit("ftmo-2step-phase1")


@pytest.fixture(scope="module")
def sample() -> AuditResult:
    return sample_result("es", bootstrap_samples=50)


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _challenge(result: AuditResult) -> dict[str, Any]:
    assert result.challenge is not None
    return result.challenge


def _row(fit: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return next(row for row in fit["firms"] if row["keys"] == keys)


def _cell(page: str, row: dict[str, Any]) -> str:
    """The program's name cell of the firm table, unescaped."""
    start = page.index(html.escape(f"{row['firm']} · {row['program']}"))
    return html.unescape(page[start : page.index("</td>", start)])


def _daily(seed: int = 3, n: int = 400) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0012, 0.008, n)


def _size_block(text: str, labels: dict[str, str]) -> str:
    start = text.rindex(labels["ch_size_title"])
    return text[start : text.index(labels["ff_title"], start)]


# ---------------------------------------------- 1. the lot and its balance


def test_the_lots_are_the_file_balance_and_scale_to_the_program_account(
    topstep: tuple[Any, AuditResult],
) -> None:
    _, result = topstep
    sizing = _challenge(result)["sizing"]
    # The sample report states a 10,000 balance; Topstep 100K names a 100,000 account.
    assert sizing["starting_balance"]["value"] == 10_000.0
    assert sizing["starting_balance"]["evidence"] == "DECLARED"
    assert ACCOUNT_SIZES[CHOSEN] == 100_000.0
    assert sizing["size_per_trade"]["value"] == 0.5
    note = SIZING_ACCOUNT_LOT_NOTE.format(account="100,000", balance="10,000")
    # The same daily shares on ten times the balance take ten times the lots.
    assert sizing["size_per_trade_account"] == {
        "value": 5.0,
        "evidence": "MEASURED",
        "note": note,
    }
    assert [row["average_lot_account"]["value"] for row in sizing["rows"]] == [2.5, 5.0, 7.5, 10.0]
    assert {row["average_lot_account"]["note"] for row in sizing["rows"]} == {
        SIZING_ACCOUNT_LOT_ROW_NOTE
    }
    assert [row["average_lot"]["value"] for row in sizing["rows"]] == [0.25, 0.5, 0.75, 1.0]
    assert untranslated(result.model_dump(mode="json")) == []
    for text in (note, SIZING_ACCOUNT_LOT_ROW_NOTE):
        for locale in ("es", "pt"):
            assert localize(text, locale) != text and find_claims(localize(text, locale)) == []


def test_no_account_lot_without_a_measured_lot_an_account_or_a_known_balance() -> None:
    lot = {"value": 0.5, "evidence": "MEASURED", "note": "x"}
    balance = {"value": 10_000.0, "evidence": "DECLARED", "note": "x"}
    assert engine._account_lot(lot, balance, 100_000.0)["value"] == 5.0
    # An assumed balance makes the proportion a guess: no figure.
    assumed = {**balance, "evidence": "NOT_MEASURED"}
    assert engine._account_lot(lot, assumed, 100_000.0) is None
    assert engine._account_lot(lot, balance, None) is None
    unknown = {"value": None, "evidence": "NOT_MEASURED", "note": "x"}
    assert engine._account_lot(unknown, balance, 100_000.0) is None


@pytest.mark.parametrize("locale", LOCALES)
def test_the_size_table_says_which_balance_its_lots_are_on(
    topstep: tuple[Any, AuditResult], ftmo: tuple[Any, AuditResult], locale: str
) -> None:
    labels = LABELS[locale]
    lots = labels["ch_size_lots"].format(lots="0.50")
    for result, account in ((topstep[1], "100,000"), (ftmo[1], "")):
        text = _visible(render_html(result, watermark=False, locale=locale))
        block = _size_block(text, labels)
        assert labels["ch_size_lots_on"].format(lots=lots, balance="10,000") in block
        assert labels["ch_size_lot_col_on"].format(balance="10,000") in block
        if account:
            line = labels["ch_size_lot_account"].format(
                lots="5.00", base="0.50", size=account, balance="10,000"
            )
            assert line in block
            assert labels["ch_size_lot_col_account"].format(size=account) in block
            assert labels["ch_size_no_account_lots"].format(balance="10,000") not in block
        else:
            # The shares sentence, then the lots: they are the file balance's.
            assert labels["ch_size_no_account_lots"].format(balance="10,000") in block
            assert labels["ch_size_lot_col_account"].split("{")[0] not in block
        assert find_claims(block) == []
    challenge = _challenge(topstep[1])
    page = html.unescape(
        _challenge_sizing_html(
            challenge["sizing"], locale, labels, rules=challenge["rules"], horizon=250
        )
    )
    on_file = labels["ch_size_lot_col_on"].format(balance="10,000")
    on_account = labels["ch_size_lot_col_account"].format(size="100,000")
    for size, base, scaled in (("0.5x", "0.25", "2.50"), ("2x", "1.00", "10.00")):
        assert (
            f"<tr><td>{size}</td><td class='val' data-l='{on_file}'>{base}</td>"
            f"<td class='val' data-l='{on_account}'>{scaled}</td>"
        ) in page


def test_the_account_notes_say_the_shares_do_not_depend_on_it_and_the_lots_do() -> None:
    for locale, shares in (
        ("es", "los porcentajes de la tabla no dependen"),
        ("en", "the table's shares do not depend"),
        ("pt", "as porcentagens da tabela não dependem"),
    ):
        labels = LABELS[locale]
        assert shares in labels["ch_size_no_account"]
        assert shares in labels["ch_size_no_account_lots"]
        assert shares in localize(SIZING_NO_ACCOUNT, locale)
        assert "× " in labels["ch_size_no_account_lots"]
        for key in (
            "ch_size_no_account",
            "ch_size_no_account_lots",
            "ch_size_lot_account",
            "ch_size_lots_on",
            "ch_size_lot_col_on",
            "ch_size_lot_col_account",
        ):
            assert find_claims(labels[key]) == [], (locale, key)
            assert not [word for word in BANNED if word in labels[key].lower()], (locale, key)


# ---------------------------------------------------------- 2. the markets


def test_every_pair_against_a_currency_is_spot_or_cfd() -> None:
    assert firmfit.symbol_venues("EURUSD") == {"fx"}
    assert firmfit.symbol_venues("XAUUSD") == {"metals"}
    # Bitcoin written as a pair is spot or CFD, like gold's XAUUSD.
    for pair in ("BTCUSD", "BTCUSDT", "XBTUSD", "BTCUSD.m", "BINANCE:BTCUSDT"):
        assert firmfit.symbol_venues(pair) == {"crypto"}, pair
    # A bare root or a perpetual can be a future; so can an index name.
    for either in ("BTC", "BTCPERP", "BTCUSDTPERP"):
        assert firmfit.symbol_venues(either) == {"crypto", "futures"}, either
    assert firmfit.symbol_venues("NQZ4") == {"indices", "futures"}
    assert firmfit.symbol_venues("AAPL") is None


@pytest.mark.parametrize("locale", LOCALES)
def test_gold_and_bitcoin_pairs_leave_topstep_out_alike(locale: str) -> None:
    labels = LABELS[locale]
    for symbol, market in (("XAUUSD", "metal"), ("BTCUSD", "crypto")):
        fit = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=[symbol])
        for key in TOPSTEP:
            row = _row(fit, [key])
            assert "pass" not in row
            assert row["market"] == {
                "allowed": ["futures"],
                "history": [market],
                "symbols": [symbol],
                "symbol_count": 1,
                "spot": True,
                "source_url": TOPSTEP_PRODUCTS_URL,
                "as_of": row["market"]["as_of"],
            }
        page = _visible(_firm_fit_html(fit, labels, locale=locale))
        why = labels["ff_market_why_spot"].format(
            history=labels[f"ff_hist_{market}"], symbols=symbol
        )
        assert f"{why}; {labels['ff_market_skip']}." in page
        assert find_claims(page) == []
    # A bare coin root can be the exchange future: Topstep is simulated.
    root = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=["BTC"])
    assert all(_row(root, [key])["pass"] for key in TOPSTEP)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_forex_and_index_history_names_only_the_forex(locale: str) -> None:
    labels = LABELS[locale]
    symbols = ["EURUSD"] * 3 + ["NQZ4"] * 5 + ["GBPUSD"] * 4
    fit = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=symbols)
    assert fit["history_markets"] == ["fx", "us_equity"]
    market = _row(fit, [TOPSTEP[0]])["market"]
    # Only what the program does not take, the most traded first.
    assert market["history"] == ["fx"] and market["spot"] is True
    assert market["symbols"] == ["GBPUSD", "EURUSD"] and market["symbol_count"] == 2
    page = _visible(_firm_fit_html(fit, labels, locale=locale))
    only = labels["ff_market_only"].format(markets=labels["ff_mk_futures"])
    why = labels["ff_market_why_spot"].format(
        history=labels["ff_hist_fx"], symbols="GBPUSD, EURUSD"
    )
    assert page.count(f"{only}: {why}; {labels['ff_market_skip']}.") == len(FUTURES_ONLY)
    assert labels["ff_hist_us_equity"] not in page
    # The5ers' pages take forex and indices: simulated.
    assert _row(fit, ["the5ers-hyper-growth"])["pass"]["evidence"] == "MEASURED"


def test_many_symbols_are_cut_after_the_most_traded() -> None:
    pairs = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD"]
    symbols = [pair for i, pair in enumerate(pairs) for _ in range(len(pairs) - i)]
    market = firmfit.market_fit(TOPSTEP[0], symbols)
    assert market is not None
    assert market["symbols"] == pairs[: firmfit.MARKET_SYMBOLS] and market["symbol_count"] == 6
    assert "(EURUSD, GBPUSD, USDJPY, AUDUSD, …)" in _market_text(market, LABELS["en"])
    # Every program that names no markets, or a symbol that says nothing, restricts nothing.
    assert firmfit.market_fit("ftmo-1step", symbols) is None
    assert firmfit.market_fit(TOPSTEP[0], [*symbols, "AAPL"]) is None


# ---------------------------------------- 3. the chosen program and its market


def test_the_chosen_program_keeps_its_figures_and_its_market(
    topstep: tuple[Any, AuditResult],
) -> None:
    inputs, result = topstep
    challenge = _challenge(result)
    market = challenge["market"]
    assert market["allowed"] == ["futures"] and market["history"] == ["fx"]
    assert market["spot"] is True and set(market["symbols"]) == set(inputs.trade_symbols)
    fit = challenge["firm_fit"]
    row = _row(fit, [CHOSEN])
    assert row["market"] == market
    rungs = {rung["key"]: rung for rung in challenge["scenarios"]["rows"]}
    # Its figures are its section's and the ladder's.
    assert row["pass"] == rungs["full"]["pass"]
    assert row["pass"]["value"] == challenge["probability"]["pass"]["value"]
    for name in firmfit.SCENARIO_COLUMNS:
        assert row["scenarios"][name]["pass"] == rungs[name]["pass"]
    # The futures-only programs it did not choose are still left out, last.
    others = [key for key in FUTURES_ONLY if key != CHOSEN]
    for key in others:
        assert "pass" not in _row(fit, [key])
    tail = [r["keys"] for r in fit["firms"][-len(others) :]]
    assert tail == [[key] for key in others]
    # Another choice puts no market on the section.
    assert "market" not in _challenge(_audit("ftmo-1step")[1])


@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_never_says_the_chosen_program_was_not_simulated(
    topstep: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = topstep
    challenge = _challenge(result)
    labels = LABELS[locale]
    page = render_html(result, watermark=False, locale=locale)
    text = _visible(page)
    chosen = _market_text(challenge["market"], labels, chosen=True)
    skipped = _market_text(challenge["market"], labels)
    ladder = text.rindex(labels["ch_ladder_title"])
    size = text.rindex(labels["ch_size_title"])
    firms = text.rindex(labels["ff_title"])
    # The section, the ladder, the size table and the chosen row each say it once.
    places = [m.start() for m in re.finditer(re.escape(chosen), text)]
    assert len(places) == 4
    assert places[0] < ladder < places[1] < size < places[2] < firms < places[3]
    # Only the futures-only programs it did not choose read "not simulated".
    assert text.count(skipped) == len(FUTURES_ONLY) - 1
    assert labels["hero_challenge_market"] in text
    rows = re.findall(r"<tr(?: class='ff-out')?>(.*?)</tr>", page, flags=re.S)
    mine = next(r for r in rows if html.escape("Topstep · Trading Combine 100K") in r)
    assert "class='val'" in mine and html.escape(chosen) in mine
    assert find_claims(text) == []
    for key in ("ff_market_chosen", "hero_challenge_market", "ff_market_why_spot"):
        assert not [word for word in BANNED if word in labels[key].lower()], (locale, key)


# --------------------------------------------- 4. open losses, row by row


@pytest.mark.parametrize("locale", LOCALES)
def test_each_row_warns_when_the_platform_drawdown_reaches_its_limit(
    sample: AuditResult, locale: str
) -> None:
    labels = LABELS[locale]
    dd = float(sample.performance["platform_equity_drawdown"]["value"])
    assert dd == pytest.approx(-0.0876, abs=5e-4)
    challenge = _challenge(sample)
    # The generic programme's 10 % limit is not reached: no table-wide warning.
    assert challenge["rules"]["max_total_loss"] > abs(dd)
    fit = challenge["firm_fit"]
    page = _firm_fit_html(fit, labels, ladder=True, locale=locale, platform_dd=dd)
    flagged: set[str] = set()
    for row in fit["firms"]:
        limit = min(float(phase["max_total_loss"]) for phase in row["rules"])
        note = labels["ff_open_loss"].format(dd=f"{abs(dd):.1%}", limit=_rule_pct(limit))
        shown = note in _cell(page, row)
        assert shown == (bool(row.get("pass")) and abs(dd) >= limit), row["program"]
        if shown:
            flagged.add(f"{row['firm']} · {row['program']}")
    # Every simulated program whose total loss limit is at or under 8.76 %; E8 Markets'
    # Zero 100K (3 %) is futures only and left out for this forex sample.
    assert flagged == {
        "The5ers · Hyper Growth",
        "FundedNext · Stellar 1-Step",
        "FundedNext · Stellar Lite",
        "The5ers · Bootcamp",
        "FundingPips · 2-Step Pro",
        "Alpha Capital Group · Alpha Pro 8%",
        "Alpha Capital Group · Alpha Pro 6%",
        "E8 Markets · Signature 100K",
        "FXIFY · Three Phase",
        "Maven Trading · 3-Step",
    }
    assert labels["ff_optimistic"] not in page
    # The public sample page shows them.
    text = _visible(render_html(sample, watermark=False, locale=locale))
    lead = labels["ff_open_loss"].split("{limit}")[0].format(dd=f"{abs(dd):.1%}")
    assert text.count(lead) == len(flagged)
    assert find_claims(text) == []
    assert find_claims(labels["ff_open_loss"]) == []


# ------------------------------------------------------------ 5. wording


def test_the_full_history_column_keeps_the_costs_the_file_carries() -> None:
    for locale, without, wrong in (
        ("es", "sin el costo declarado o de referencia", "y sin costo"),
        ("en", "without the declared or reference cost", "without costs"),
        ("pt", "sem o custo declarado ou de referência", "e sem custo"),
    ):
        text = LABELS[locale]["ff_basis_columns"]
        assert without in text and wrong not in text, locale
        assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_every_program_passing_counts_only_the_simulated_ones(locale: str) -> None:
    labels = LABELS[locale]
    daily = 0.01 + np.random.default_rng(2).normal(0, 0.0005, 300)
    fit = firmfit.firm_fit(daily, samples=200, symbols=["EURUSD"])
    assert fit["uniform"] == "all_pass"
    page = html.unescape(_firm_fit_html(fit, labels, locale=locale))
    assert labels["ff_all_pass_simulated"] in page and labels["ff_all_pass"] not in page
    assert "<table" not in page
    left = [row for row in fit["firms"] if not row.get("pass")]
    assert len(left) == len(FUTURES_ONLY)
    for row in left:
        reason = _market_text(row["market"], labels)
        assert f"{row['firm']} · {row['program']} — {reason}" in page
    plain = html.unescape(_firm_fit_html(firmfit.firm_fit(daily, samples=200), labels))
    assert labels["ff_all_pass"] in plain and labels["ff_all_pass_simulated"] not in plain
    tiny = 0.00001 + np.random.default_rng(2).normal(0, 0.00002, 300)
    fail = firmfit.firm_fit(tiny, samples=200, symbols=["EURUSD"])
    assert fail["uniform"] == "all_fail"
    risk = labels[f"ff_risk_{fail['common_risk']}"].lower()
    page = html.unescape(_firm_fit_html(fail, labels, locale=locale))
    assert labels["ff_all_fail_simulated"].format(risk=risk) in page
    for key in ("ff_all_pass_simulated", "ff_all_fail_simulated"):
        assert find_claims(labels[key]) == [], (locale, key)
    # The Portuguese sentence says "almost none", as the others do.
    assert "1 %" in LABELS["pt"]["ff_all_fail"] and "quase" in LABELS["pt"]["ff_all_fail"]


@pytest.mark.parametrize("locale", LOCALES)
def test_a_one_phase_size_table_counts_no_phases(
    sample: AuditResult, ftmo: tuple[Any, AuditResult], locale: str
) -> None:
    labels = LABELS[locale]
    every = {"es": "contando todas las fases", "en": "counting every phase"}.get(
        locale, "contando todas as fases"
    )
    assert every in labels["ch_size_intro"] and every not in labels["ch_size_intro_one"]
    assert find_claims(labels["ch_size_intro_one"]) == []
    for result, phases in ((sample, 1), (ftmo[1], 2)):
        challenge = _challenge(result)
        assert challenge["sizing"]["program"]["phases"] == phases
        page = html.unescape(
            _challenge_sizing_html(
                challenge["sizing"], locale, labels, rules=challenge["rules"], horizon=250
            )
        )
        assert (every in page) == (phases > 1)


# --------------------------------------------- 6. results stored before


@pytest.mark.parametrize("locale", LOCALES)
def test_a_result_stored_before_the_average_lot_reads_in_its_language(
    ftmo: tuple[Any, AuditResult], locale: str
) -> None:
    _, result = ftmo
    data = result.model_dump(mode="json")
    sizing = data["challenge"]["sizing"]
    sizing["size_per_trade"] = {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": SIZING_NO_SIZE_BEFORE,
    }
    sizing["account_size"] = {
        "value": None,
        "evidence": "NOT_MEASURED",
        "note": SIZING_NO_ACCOUNT_BEFORE,
    }
    for row in sizing["rows"]:
        row.pop("average_lot", None)
    stored = AuditResult.model_validate_json(AuditResult.model_validate(data).model_dump_json())
    assert untranslated(stored.model_dump(mode="json")) == []
    labels = LABELS[locale]
    block = _size_block(_visible(render_html(stored, watermark=False, locale=locale)), labels)
    reason = localize(SIZING_NO_SIZE_BEFORE, locale)
    assert labels["ch_size_lot_before"] in block and reason in block
    assert labels["ch_size_lot"] not in block
    assert labels["ch_size_no_account"] in block
    if locale != "en":
        assert reason != SIZING_NO_SIZE_BEFORE
        assert "keeps neither" not in block and "does not depend" not in block
        assert localize(SIZING_NO_ACCOUNT_BEFORE, locale) != SIZING_NO_ACCOUNT_BEFORE
    assert find_claims(block) == []


# --------------------------------------------- 7. print and the PDF cover


def test_the_rules_are_open_as_served_and_folded_only_by_the_script(
    ftmo: tuple[Any, AuditResult],
) -> None:
    page = render_html(ftmo[1], watermark=False, locale="es")
    rows = _challenge(ftmo[1])["firm_fit"]["firms"]
    assert page.count("<details open class='ff-rules'>") == len(rows)
    assert "<details class='ff-rules'>" not in page
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'd.querySelectorAll("details.report-detail, details.ff-rules")' in script
    assert 'window.addEventListener("beforeprint"' in script


@pytest.mark.parametrize("locale", LOCALES)
def test_the_pdf_cover_keeps_the_sharpe_next_to_the_platform_drawdown(
    sample: AuditResult, locale: str
) -> None:
    labels = LABELS[locale]
    data = sample.model_dump(mode="json")
    shown = [label for label, _, _ in _cover_kpis(data, labels)]
    assert shown == [
        labels["kpi_return"],
        labels["kpi_drawdown_closed"],
        labels["kpi_dd_platform"],
        labels["kpi_sharpe"],
    ]
    page = render_html(sample, watermark=False, locale=locale)
    cover = page.split("<section class='pdf-cover'>", 1)[1].split("</section>", 1)[0]
    sharpe = float(sample.performance["sharpe"]["value"])
    assert f"<b>{sharpe:.2f}</b>" in cover and round(sharpe, 1) == 1.8
    # Without the platform's drawdown the cover is the first four, the p95 among them.
    plain = {**data, "performance": dict(data["performance"])}
    plain["performance"].pop("platform_equity_drawdown")
    assert _cover_kpis(plain, labels) == _kpi_list(plain, labels)[:4]
    assert labels["kpi_dd_p95_closed"] in [label for label, _, _ in _cover_kpis(plain, labels)]
