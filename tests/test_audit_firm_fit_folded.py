"""The firm table folds the programs its history's markets leave out: one
counted summary over the rows without a figure, the ranked rows untouched,
the PDF and the browser's print showing them open under that summary. Offline."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import firmfit
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.prop_presets import PRESETS
from quant_trade.audit.report import LABELS, _firm_fit_html, render_html
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs
from quant_trade.audit.theme import STATIC_DIR

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 10, 10, tzinfo=UTC)
FOLD = "<details class='ff-fold'>"
OPEN_FOLD = "<details open class='ff-fold'>"
OUT_ROW = "<tr class='ff-out'>"
NEW_LABELS = ("ff_fold_many", "ff_fold_one", "ff_intro_counts", "ff_programs", "ff_program_one")
#: The futures-only programs of the sample's table (PR 489, 493 and 495).
FUTURES_ONLY = [
    key
    for key, rules in PRESETS.items()
    if rules.markets == ("futures",) and rules.source_url.startswith("https://")
]
#: The programs whose pages name no crypto and no futures (Alpha Capital Group).
NO_CRYPTO = sorted(
    {
        (rules.firm, rules.program)
        for rules in PRESETS.values()
        if rules.markets is not None and not {"crypto", "futures"} & set(rules.markets)
    }
)
#: The words these texts never use, in the three languages.
FORBIDDEN = re.compile(
    r"\b(aprobar\w*|aprobad\w*|pasar|pasas?|passar\w*|pass|passed|passes|passing|aprovar\w*|"
    r"aprovad\w*|verific\w*|verified|certificad\w*|certified|garantiza\w*|guarantee\w*|"
    r"garantid\w*|rentables?|profitable|lucrativ\w*|approved|recomend\w*|recommend\w*)\b",
    re.IGNORECASE,
)
NINJATRADER_HEADER = (
    "Trade number,Instrument,Account,Strategy,Market pos.,Qty,Entry price,Exit price,Entry time,"
    "Exit time,Entry name,Exit name,Profit,Cum. net profit,Commission,Clearing Fee,Exchange Fee,"
    "IP Fee,NFA Fee,MAE,MFE,ETD,Bars,"
)


@pytest.fixture(scope="module")
def sample() -> AuditResult:
    return sample_result("es", bootstrap_samples=50)


@pytest.fixture(scope="module")
def pages(sample: AuditResult) -> dict[str, str]:
    return {locale: render_html(sample, watermark=False, locale=locale) for locale in LOCALES}


def _daily(seed: int = 3, n: int = 400) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0012, 0.008, n)


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def _folds(page: str) -> list[tuple[str, str]]:
    """(summary, body) of every fold, closed by its own tag past the rules
    folded inside each row (``<details open class='ff-rules'>``)."""
    out: list[tuple[str, str]] = []
    position = 0
    while (start := page.find(FOLD, position)) >= 0:
        depth, index = 1, start + len(FOLD)
        while depth:
            opened, closed = page.find("<details", index), page.find("</details>", index)
            assert closed >= 0
            if 0 <= opened < closed:
                depth, index = depth + 1, opened + len("<details")
            else:
                depth, index = depth - 1, closed + len("</details>")
        chunk = page[start:index]
        head, body = chunk.split("</summary>", 1)
        out.append((html.unescape(head.split("<summary>", 1)[1]), body[: -len("</details>")]))
        position = index
    return out


def _ranked_names(page: str, labels: dict[str, str]) -> list[str]:
    """The programs of the ranked table (the one under the firm title: the
    ladder's table shares its class), in its order."""
    section = page[page.index(html.escape(labels["ff_title"])) :]
    table = section[section.index("<table class='timing firms'><thead>") :]
    body = table[table.index("<tbody>") : table.index("</tbody>")]
    assert OUT_ROW not in body
    return [html.unescape(name) for name in re.findall(r"<tr><td>(.*?)<br>", body)]


def _name(row: dict[str, object]) -> str:
    return f"{row['firm']} · {row['program']}"


def _summary(labels: dict[str, str], count: int, allowed: list[str], history: list[str]) -> str:
    def joined(items: list[str]) -> str:
        return (
            items[0]
            if len(items) == 1
            else f"{', '.join(items[:-1])} {labels['ff_and']} {items[-1]}"
        )

    key = "ff_fold_one" if count == 1 else "ff_fold_many"
    return labels[key].format(
        n=count,
        markets=joined([labels[f"ff_mk_{m}"] for m in allowed]),
        history=joined([labels[f"ff_hist_{m}"] for m in history]),
    )


def _counts(labels: dict[str, str], compared: int, left: int) -> str:
    def programs(count: int) -> str:
        return labels["ff_program_one"] if count == 1 else labels["ff_programs"].format(n=count)

    return labels["ff_intro_counts"].format(compared=programs(compared), left=programs(left))


def _ninjatrader_trades(n: int = 220, seed: int = 3) -> bytes:
    """A NinjaTrader trades grid (``tests/fixtures/audit_imports/ninjatrader.csv``)
    with one ES trade a day for ``n`` business days."""
    rng = np.random.default_rng(seed)
    rows = [NINJATRADER_HEADER]
    total = 0.0

    def money(value: float) -> str:
        return f"(${abs(value):,.2f})" if value < 0 else f"${value:,.2f}"

    for number, day in enumerate(pd.bdate_range("2025-01-06", periods=n), 1):
        points = float(rng.normal(0.6, 6.0))
        entry = 6000 + float(rng.normal(0, 40))
        side = "Long" if rng.random() < 0.5 else "Short"
        exit_price = entry + points if side == "Long" else entry - points
        profit = points * 50 - 5.08
        total += profit
        stamp = f"{day.month}/{day.day}/{day.year}"
        rows.append(
            f"{number},ES 03-26,Backtest,DemoStrategy,{side},1,{entry:.2f},{exit_price:.2f},"
            f"{stamp} 9:35:00 AM,{stamp} 10:05:00 AM,{side},Exit,{money(profit)},{money(total)},"
            "$5.08,$0.00,$0.00,$0.00,$0.00,$62.50,$325.00,$17.58,6,"
        )
    return ("\n".join(rows) + "\n").encode()


# ------------------------------------------------ 1. the sample: /ejemplo, /sample, /pt/exemplo


@pytest.mark.parametrize("locale", LOCALES)
def test_the_sample_folds_its_nineteen_rows_without_a_figure(
    sample: AuditResult, pages: dict[str, str], locale: str
) -> None:
    labels = LABELS[locale]
    assert sample.challenge is not None
    fit = sample.challenge["firm_fit"]
    ranked = [row for row in fit["firms"] if row.get("pass")]
    left = [row for row in fit["firms"] if not row.get("pass")]
    assert (len(ranked), len(left)) == (20, 19) and len(left) == len(FUTURES_ONLY)
    page = pages[locale]
    folds = _folds(page)
    assert len(folds) == 1
    summary, body = folds[0]
    assert summary == _summary(labels, 19, ["futures"], ["fx"])
    assert "%" not in summary and FORBIDDEN.search(summary) is None
    # The 19 rows, as before, are all inside the fold and nowhere else.
    assert body.count(OUT_ROW) == 19 == page.count(OUT_ROW)
    for row in left:
        assert html.escape(_name(row)) in body
    assert html.escape(labels["ff_market_skip"]) in body
    # The 20 with a figure keep their order in the ranked table, before the fold.
    assert _ranked_names(page, labels) == [_name(row) for row in ranked]
    title = page.index(html.escape(labels["ff_title"]))
    assert title < page.index("</table>", title) < page.index(FOLD)
    # The introduction counts both.
    assert _counts(labels, 20, 19) in html.unescape(page)
    assert labels["ff_intro"] in html.unescape(page)
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_pdf_prints_the_fold_open_under_its_summary(pages: dict[str, str], locale: str) -> None:
    labels = LABELS[locale]
    page = pages[locale]
    expanded = pdf_lib._expand_details_for_pdf(page)
    assert FOLD not in expanded and expanded.count(OPEN_FOLD) == 1
    summary = html.escape(_summary(labels, 19, ["futures"], ["fx"]))
    start = expanded.index(OPEN_FOLD)
    assert expanded[start:].startswith(f"{OPEN_FOLD}<summary>{summary}</summary>")
    assert expanded.count(OUT_ROW) == 19 and expanded.index(OUT_ROW) > start
    # Nothing else of the page moves.
    assert _visible(expanded) == _visible(page)


# -------------------------------------------------- 2. the summary comes from the rows


@pytest.mark.parametrize("locale", LOCALES)
def test_the_summary_counts_and_names_what_the_rows_say(locale: str) -> None:
    labels = LABELS[locale]
    daily = _daily()
    # Forex and gold: the futures-only programs, both markets named.
    fit = firmfit.firm_fit(daily, samples=100, seed=7, symbols=["XAUUSD", "EURUSD"])
    page = _firm_fit_html(fit, labels, locale=locale)
    folds = _folds(page)
    assert [summary for summary, _ in folds] == [
        _summary(labels, len(FUTURES_ONLY), ["futures"], ["fx", "metal"])
    ]
    assert folds[0][1].count(OUT_ROW) == len(FUTURES_ONLY) == page.count(OUT_ROW)
    ranked = [row for row in fit["firms"] if row.get("pass")]
    assert _ranked_names(page, labels) == [_name(row) for row in ranked]
    assert _counts(labels, len(ranked), len(FUTURES_ONLY)) in html.unescape(page)
    # A bitcoin pair: two sets of pages, one fold each, in the table's order.
    fit = firmfit.firm_fit(daily, samples=100, seed=7, symbols=["BTCUSD"])
    page = _firm_fit_html(fit, labels, locale=locale)
    folds = _folds(page)
    allowed = list(PRESETS["alpha-pro-8-phase1"].markets or ())
    assert [summary for summary, _ in folds] == [
        _summary(labels, len(FUTURES_ONLY), ["futures"], ["crypto"]),
        _summary(labels, len(NO_CRYPTO), allowed, ["crypto"]),
    ]
    assert [body.count(OUT_ROW) for _, body in folds] == [len(FUTURES_ONLY), len(NO_CRYPTO)]
    for firm, program in NO_CRYPTO:
        assert html.escape(f"{firm} · {program}") in folds[1][1]
    left = len(FUTURES_ONLY) + len(NO_CRYPTO)
    assert _counts(labels, len(fit["firms"]) - left, left) in html.unescape(page)
    # One program left out reads in the singular.
    one = next(
        row
        for row in fit["firms"]
        if not row.get("pass") and row["market"]["allowed"] != ["futures"]
    )
    single = {**fit, "firms": [row for row in fit["firms"] if row.get("pass")] + [one]}
    page = _firm_fit_html(single, labels, locale=locale)
    assert [summary for summary, _ in _folds(page)] == [_summary(labels, 1, allowed, ["crypto"])]
    assert _counts(labels, len(single["firms"]) - 1, 1) in html.unescape(page)
    assert find_claims(_visible(page)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_every_program_passing_folds_the_lines_too(locale: str) -> None:
    labels = LABELS[locale]
    daily = 0.01 + np.random.default_rng(2).normal(0, 0.0005, 300)
    fit = firmfit.firm_fit(daily, samples=100, symbols=["EURUSD"])
    assert fit["uniform"] == "all_pass"
    page = _firm_fit_html(fit, labels, locale=locale)
    assert "<table" not in page
    folds = _folds(page)
    assert len(folds) == 1
    summary, body = folds[0]
    assert summary == _summary(labels, len(FUTURES_ONLY), ["futures"], ["fx"])
    assert body.count("<p class='muted'>") == len(FUTURES_ONLY)
    assert _counts(labels, len(fit["firms"]) - len(FUTURES_ONLY), len(FUTURES_ONLY)) in (
        html.unescape(page)
    )


# ------------------------------------------- 3. a futures history, a mixed history


def test_a_futures_history_folds_nothing_and_a_mixed_one_only_what_is_not_simulated() -> None:
    labels = LABELS["es"]
    # A NinjaTrader export of ES: every program's page takes it, so nothing folds.
    inputs = build_inputs(
        None,
        DeclaredMetadata(),
        report_bytes=_ninjatrader_trades(),
        report_filename="ninjatrader.csv",
    )
    assert set(inputs.trade_symbols or []) == {"ES 03-26"}
    result = run_audit(
        inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=100
    )
    assert result.challenge is not None
    fit = result.challenge["firm_fit"]
    assert fit["status"] == "MEASURED" and fit["history_markets"] == ["us_equity"]
    assert len(fit["firms"]) == len(firmfit.firm_fit(_daily(), samples=50)["firms"])
    assert all(row.get("pass") and not row.get("market") for row in fit["firms"])
    for locale in LOCALES:
        page = render_html(result, watermark=False, locale=locale)
        assert FOLD not in page and OUT_ROW not in page
        assert LABELS[locale]["ff_intro_counts"].split("{", 1)[0] not in html.unescape(page)
        assert find_claims(_visible(page)) == []
    # A bitcoin future (a bare root fits futures too) folds the pages that take
    # neither crypto nor futures, and no futures program.
    fit = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=["BTC"])
    page = _firm_fit_html(fit, labels)
    folds = _folds(page)
    allowed = list(PRESETS["alpha-pro-8-phase1"].markets or ())
    assert [summary for summary, _ in folds] == [
        _summary(labels, len(NO_CRYPTO), allowed, ["crypto"])
    ]
    assert all(row["pass"] for row in fit["firms"] if row["keys"][0] in FUTURES_ONLY)
    assert all(html.escape(f"{firm} · {program}") in folds[0][1] for firm, program in NO_CRYPTO)
    # Forex and an index future: only the futures-only pages fold; every
    # program that is simulated stays in the ranked table.
    fit = firmfit.firm_fit(_daily(), samples=100, seed=7, symbols=["EURUSD", "NQZ4"])
    assert fit["history_markets"] == ["fx", "us_equity"]
    page = _firm_fit_html(fit, labels)
    ranked = [row for row in fit["firms"] if row.get("pass")]
    folds = _folds(page)
    assert [summary for summary, _ in folds] == [
        _summary(labels, len(FUTURES_ONLY), ["futures"], ["fx"])
    ]
    assert _ranked_names(page, labels) == [_name(row) for row in ranked]
    assert len(ranked) == len(fit["firms"]) - len(FUTURES_ONLY)
    assert not any(html.escape(_name(row)) in folds[0][1] for row in ranked)


# ------------------------------------------------------------------- 4. the texts


@pytest.mark.parametrize("locale", LOCALES)
def test_the_new_texts_are_clean_and_translated(locale: str) -> None:
    labels = LABELS[locale]
    for key in NEW_LABELS:
        text = labels[key]
        assert find_claims(text) == [], (locale, key)
        assert FORBIDDEN.search(text) is None, (locale, key)
        if locale != "en":
            assert text != LABELS["en"][key], (locale, key)
    for example in (
        _summary(labels, 15, ["futures"], ["fx", "metal"]),
        _summary(labels, 1, ["fx", "metals", "indices", "energy"], ["crypto"]),
        _counts(labels, 20, 19),
        _counts(labels, 38, 1),
    ):
        assert find_claims(example) == [] and FORBIDDEN.search(example) is None, example
        assert "{" not in example and "}" not in example


# ------------------------------------------------- 5. the browser prints it open


def test_the_browser_opens_the_fold_to_print_it() -> None:
    """A closed ``<details>`` prints nothing, so the page's script opens the
    fold (and the challenge's, PR 489) on ``beforeprint`` and puts it back
    afterwards; on screen and on load it stays closed, as the ranked table's
    rules do. The server's PDF opens the same three kinds."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    selector = 'd.querySelectorAll("details.ff-fold, details.unseen-open")'
    assert selector in script
    before = script.index('window.addEventListener("beforeprint"')
    after = script.index('window.addEventListener("afterprint"')
    assert script.index(selector) < before < after
    opened = "printDetails.forEach(function (item) { item.open = true; });"
    restored = "printDetails.forEach(function (item, i) { item.open = openBeforePrint[i]; });"
    assert opened in script[before:after] and restored in script[after:]
    # The on-load fold of the rules does not touch it: that list keeps its own selector.
    assert 'd.querySelectorAll("details.report-detail, details.ff-rules")' in script
    assert "ff-fold" not in script[: script.index(selector)]
    expander = pdf_lib._expand_details_for_pdf
    for kind in ("detail report-detail", "unseen-open", "ff-fold"):
        assert f"<details open class='{kind}'>x" in expander(f"<details class='{kind}'>x</details>")
