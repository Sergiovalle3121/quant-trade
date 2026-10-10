"""Pulido 1: the report says plainly what three buyers misread, in es, en and pt.

Each test reproduces one case the buyers found (the sample report, a Myfxbook
account, the upload form left as it came, the institutional page) and checks
the page now says it the honest way. Classes, figures and evidence labels do
not change, except a value the client never wrote, which is no longer tagged
DECLARED. Everything runs offline.
"""

from __future__ import annotations

import copy
import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import i18n, ownership, report_pt  # noqa: E402
from quant_trade.audit.costs import reference_note  # noqa: E402
from quant_trade.audit.crises import symbol_market, traded_markets  # noqa: E402
from quant_trade.audit.engine import DEFAULT_NOT_DECLARED, run_audit  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.institutional import COPY as REVIEW_COPY  # noqa: E402
from quant_trade.audit.institutional import REVIEW_PATHS  # noqa: E402
from quant_trade.audit.pages import _UI, upload_page  # noqa: E402
from quant_trade.audit.plan import (  # noqa: E402
    _multiplicity_step,
    _significance_step,
    improvement_plan,
)
from quant_trade.audit.report import (  # noqa: E402
    INTEGRITY_TEXT,
    KEY_LABELS,
    LABELS,
    LOCKED_GAINS,
    _crises_html,
    _kpi_list,
    _period_unit,
    _traded_symbols,
    evidence_label,
    render_html,
    report_kind,
)
from quant_trade.audit.sample import sample_result, synthetic_live_statement  # noqa: E402
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.verdict import meaning, trials_phrase  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 10, 9, tzinfo=UTC)
#: The plan's sentence for a DSR already below 0.5 at a single trial (PR 469).
#: An account's trials are the accounts or signals behind it, not configurations.
ONE_TRIAL = {
    "es": "Ya con 1 cuenta, el caso más favorable, queda por debajo de 0.5: aquí decide la "
    "falta de significación, no el número de intentos.",
    "en": "Even at 1 account, the most favourable case, it is below 0.5: what decides here "
    "is the lack of significance, not the number of trials.",
    "pt": "Já com 1 conta, o caso mais favorável, fica abaixo de 0.5: aqui quem decide é a "
    "falta de significância, não o número de tentativas.",
}
#: Wording that calls an account history a backtest.
ACCOUNT_AS_BACKTEST = (
    "posterior al backtest",
    "from after the backtest",
    "posterior ao backtest",
    "El resultado del backtest depende",
    "The backtest result depends",
    "O resultado do backtest depende",
)


def _text(page: str) -> str:
    bare = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", bare)).split())


def _page(data: dict[str, Any], locale: str) -> str:
    result = AuditResult.model_validate(data)
    return render_html(result, watermark=False, free_mode=False, locale=locale)


def _section(page: str, title: str) -> str:
    """The text of the report section titled ``title``, up to the next heading."""
    text = html.unescape(page)
    start = text.index(f"<h2>{title}</h2>")
    end = text.find("<h2", start + 4)
    return _text(text[start : end if end != -1 else len(text)])


@pytest.fixture(scope="module")
def sample_data() -> dict[str, Any]:
    """The public sample: an EA on AUDUSD and EURUSD, 120 trials declared and counted."""
    return sample_result("es", bootstrap_samples=200).model_dump(mode="json")


@pytest.fixture(scope="module")
def account_data() -> dict[str, Any]:
    """The sample's Myfxbook statement audited on its own, nothing declared."""
    inputs = build_inputs(
        None,
        DeclaredMetadata(trials_declared=False),
        report_bytes=synthetic_live_statement(),
        report_filename="statement.csv",
        now=NOW,
    )
    result = run_audit(
        inputs,
        bootstrap_samples=200,
        now=NOW,
        audit_id="clear-account",
        risk_samples=200,
        challenge_samples=200,
    )
    data = result.model_dump(mode="json")
    assert report_kind(data) == "account"
    return data


# 1 · "para aprobar esta dimensión" ------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_luck_line_says_pass_not_approve(sample_data: dict[str, Any], locale: str) -> None:
    text = _text(_page(sample_data, locale))
    expected = {
        "es": "para superar esta dimensión pedimos 95%",
        "en": "passing this dimension needs 95%",
        "pt": "para superar esta dimensão exigimos 95%",
    }[locale]
    assert expected in text
    assert not re.search(r"\b(aprob|aprov)\w*", text, flags=re.IGNORECASE)
    assert find_claims(text) == []
    # No fixed text of the report says "aprobar" or "aprovar" in any language.
    for value in LABELS[locale].values():
        assert not re.search(r"\b(aprob|aprov)\w*", str(value), flags=re.IGNORECASE), value


# 2 · large whole numbers without a separator -----------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_large_counts_read_with_the_reports_thousands_separator(
    sample_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(sample_data, locale))
    plan = {
        "es": "Con 16,384 o más configuraciones probadas",
        "en": "With 16,384 or more configurations tried",
        "pt": "Com 16,384 ou mais configurações testadas",
    }[locale]
    shuffle = {"es": "en {} órdenes", "en": "in {} random", "pt": "em {} ordens"}[locale]
    tail = {"es": "(65 de {})", "en": "(65 of {})", "pt": "(65 de {})"}[locale]
    copy_ = INTEGRITY_TEXT[locale]
    for shown, bare in (
        (plan, plan.replace("16,384", "16384")),
        (shuffle.format("1,000"), shuffle.format("1000")),
        (tail.format("1,282"), tail.format("1282")),
        (f"{copy_['recon_trades']}: 1,282", f"{copy_['recon_trades']}: 1282"),
        # 2,573 table rows plus the header's History Quality and two equity drawdown rows.
        (f"{copy_['forensic_rows']}: 2,576", f"{copy_['forensic_rows']}: 2576"),
    ):
        assert shown in text and bare not in text, shown


def test_trial_counts_and_observations_read_with_a_separator() -> None:
    assert trials_phrase(16384, "MEASURED", "es").startswith("16,384 intentos")
    assert trials_phrase(16384, "DECLARED", "en") == "16,384 declared trials"
    assert trials_phrase(16384, "MEASURED", "pt").startswith("16,384 tentativas")
    data = {
        "significance": {
            "status": "MEASURED",
            "observations": {"value": 1282, "evidence": "MEASURED"},
            "min_track_record_length": {"value": 4100.2, "evidence": "MEASURED"},
            "psr": {"value": 0.9, "evidence": "MEASURED"},
        },
        "inputs": {"periods_per_year": {"value": 261.0}},
    }
    for locale, words in (("es", "1,282 observaciones"), ("en", "1,282 observations")):
        finding, _ = _significance_step(data, "WEAK", locale)
        assert words in finding and "1282" not in finding


# 3 · known crises in markets the strategy never traded ---------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_crises_of_other_markets_do_not_apply_to_a_currency_ea(
    sample_data: dict[str, Any], locale: str
) -> None:
    assert _traded_symbols(sample_data) == ["AUDUSD", "EURUSD"]
    page = _page(sample_data, locale)
    section = _section(page, LABELS[locale]["crises"])
    line = {
        "es": "No aplica a este historial: las crisis que cubre la curva son caídas de acciones "
        "de EE. UU. y de bitcoin, y ninguno de los símbolos operados (AUDUSD, EURUSD) es de "
        "esos mercados.",
        "en": "Does not apply to this history: the crises the curve covers are falls in US "
        "equities and in bitcoin, and none of the symbols traded (AUDUSD, EURUSD) belongs to "
        "those markets.",
        "pt": "Não se aplica a este histórico: as crises que a curva cobre são quedas de ações "
        "dos EUA e do bitcoin, e nenhum dos símbolos operados (AUDUSD, EURUSD) é desses "
        "mercados.",
    }[locale]
    assert line in section
    for market in ("S&P 500", "Nasdaq", "Bitcoin"):
        assert market not in section
    assert "class='timing crises'" not in html.unescape(page)
    assert find_claims(line) == []


def test_symbols_are_read_with_the_audits_own_classification() -> None:
    known = {
        "EURUSD": "fx",
        "audusd.m": "fx",
        "XAUUSD": "metal",
        "US500.cash": "us_equity",
        "NAS100m": "us_equity",
        "NQ 12-24": "us_equity",
        "BTCUSDT": "crypto",
        "BINANCE:BTCUSDT": "crypto",
    }
    for name, market in known.items():
        assert symbol_market(name) == market, name
    for name in ("US30", "GER40", "ETHUSDT", "AAPL", "USDMXN", ""):
        assert symbol_market(name) is None, name
    assert traded_markets(["EURUSD", "AUDUSD"]) == {"fx"}
    assert traded_markets(["XAUUSD", "US500"]) == {"metal", "us_equity"}
    # One uncertain name and nothing is left out.
    assert traded_markets(["EURUSD", "US30"]) is None


def test_the_symbols_come_from_the_stored_result(sample_data: dict[str, Any]) -> None:
    account = {
        "instruments": {"status": "NOT_MEASURED"},
        "inputs": {"report_metadata": {"symbol": "EURUSD, GBPUSD"}},
        "costs": {},
    }
    assert _traded_symbols(account) == ["EURUSD", "GBPUSD"]
    partial = copy.deepcopy(sample_data)
    partial["instruments"]["instruments"]["value"] = 5
    assert _traded_symbols(partial) == []
    assert _traded_symbols({"inputs": {}}) == []


def test_crises_keep_only_the_falls_of_the_markets_traded(sample_data: dict[str, Any]) -> None:
    labels = LABELS["en"]
    stress = sample_data["crises"]
    equities = _text(_crises_html(stress, labels, symbols=["US500.cash", "EURUSD"]))
    assert labels["fund_stress_covid"] in equities and "S&P 500" in equities
    assert labels["fund_stress_crypto_2022"] not in equities and "Bitcoin" not in equities
    crypto = _text(_crises_html(stress, labels, symbols=["BTCUSDT"]))
    assert labels["fund_stress_crypto_2022"] in crypto and "Bitcoin" in crypto
    assert "S&P 500" not in crypto
    # Without any symbol in the file the section is the one it always was.
    unknown = _crises_html(stress, labels)
    assert unknown == _crises_html(stress, labels, symbols=[])
    assert unknown == _crises_html(stress, labels, symbols=["EURUSD", "US30"])
    assert all(market in _text(unknown) for market in ("S&P 500", "Nasdaq", "Bitcoin"))
    # The data and the calculation of the crises are untouched.
    assert [row["key"] for row in stress["windows"]] == ["covid", "rates_2022", "crypto_2022"]


def _only(stress: dict[str, Any], *keys: str) -> dict[str, Any]:
    """The same crises with only the windows ``keys`` covered."""
    stress = copy.deepcopy(stress)
    stress["windows"] = [row for row in stress["windows"] if row["key"] in keys]
    return stress


@pytest.mark.parametrize("locale", LOCALES)
def test_a_bitcoin_curve_that_misses_2022_is_told_so(
    sample_data: dict[str, Any], locale: str
) -> None:
    """A bitcoin backtest whose curve covers covid but not the 2022 crypto fall."""
    text = _text(
        _crises_html(_only(sample_data["crises"], "covid"), LABELS[locale], symbols=["BTCUSD"])
    )
    line = {
        "es": "No aplica a este historial: las crisis que cubre la curva son caídas de acciones "
        "de EE. UU.; los símbolos operados (BTCUSD) incluyen bitcoin, pero la curva no cubre "
        "ninguna de las crisis de ese mercado.",
        "en": "Does not apply to this history: the crises the curve covers are falls in US "
        "equities; the symbols traded (BTCUSD) include bitcoin, but the curve covers none of "
        "that market's crises.",
        "pt": "Não se aplica a este histórico: as crises que a curva cobre são quedas de ações "
        "dos EUA; os símbolos operados (BTCUSD) incluem bitcoin, mas a curva não cobre nenhuma "
        "das crises desse mercado.",
    }[locale]
    assert line in text
    for wrong in ("es de esos mercados", "belongs to those markets", "é desses mercados"):
        assert wrong not in text
    assert find_claims(line) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_currency_curve_with_equity_falls_only_does_not_name_bitcoin(
    sample_data: dict[str, Any], locale: str
) -> None:
    stress = _only(sample_data["crises"], "covid", "rates_2022")
    text = _text(_crises_html(stress, LABELS[locale], symbols=["EURUSD"]))
    line = {
        "es": "No aplica a este historial: las crisis que cubre la curva son caídas de acciones "
        "de EE. UU., y ninguno de los símbolos operados (EURUSD) es de ese mercado.",
        "en": "Does not apply to this history: the crises the curve covers are falls in US "
        "equities, and none of the symbols traded (EURUSD) belongs to that market.",
        "pt": "Não se aplica a este histórico: as crises que a curva cobre são quedas de ações "
        "dos EUA, e nenhum dos símbolos operados (EURUSD) é desse mercado.",
    }[locale]
    assert line in text
    assert "bitcoin" not in text.lower()
    assert find_claims(line) == []


def _with_index(data: dict[str, Any], symbols: tuple[str, str]) -> dict[str, Any]:
    """The sample traded on ``symbols``, with a client benchmark that fell less
    than the curve in each of its three covered crises."""
    data = copy.deepcopy(data)
    for row, name in zip(data["instruments"]["rows"], symbols, strict=True):
        row["key"] = name
    data["instruments"]["best"]["key"] = symbols[0]
    data["inputs"]["report_metadata"]["symbol"] = ",".join(symbols)
    data["costs"].pop("pip_symbol", None)
    stress = data["crises"]
    for row, (fund, index) in zip(
        stress["windows"], ((-0.278, -0.098), (-0.307, -0.086), (-0.35, -0.10)), strict=True
    ):
        row["fund"]["value"] = fund
        row["benchmark"] = {"value": index, "evidence": "MEASURED", "note": ""}
    stress["findings"] = ["fell_more_in_crises"]
    stress["worse_than_benchmark"] = {"value": 3, "evidence": "MEASURED", "note": ""}
    stress["compared"] = {"value": 3, "evidence": "MEASURED", "note": ""}
    return data


@pytest.mark.parametrize("locale", LOCALES)
def test_falling_more_than_the_index_survives_the_market_filter(
    sample_data: dict[str, Any], locale: str
) -> None:
    """US500 over 2021-11..2022-12: the bitcoin window goes, the warning stays,
    counted on the two equity windows still shown."""
    data = _with_index(sample_data, ("US500", "NAS100"))
    assert _traded_symbols(data) == ["US500", "NAS100"]
    section = _section(_page(data, locale), LABELS[locale]["crises"])
    # The sample declares whose strategy it is: the warning speaks in that voice.
    labels = ownership.labels_for(LABELS[locale], locale, ownership.role_of(data))
    assert labels["crises_worse"].format(worse=2, n=2) in section
    assert labels["fund_stress_covid"] in section and labels["fund_stress_rates_2022"] in section
    assert labels["fund_stress_crypto_2022"] not in section
    assert find_claims(section) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_clients_own_index_keeps_the_crises_of_other_markets(
    sample_data: dict[str, Any], locale: str
) -> None:
    """A currency EA compared with the client's own index: the comparison and
    its warning stay, it is not reduced to "does not apply"."""
    data = _with_index(sample_data, ("AUDUSD", "EURUSD"))
    section = _section(_page(data, locale), LABELS[locale]["crises"])
    labels = ownership.labels_for(LABELS[locale], locale, ownership.role_of(data))
    assert labels["crises_worse"].format(worse=3, n=3) in section
    assert labels["fund_stress_index"] in section
    for key in ("covid", "rates_2022", "crypto_2022"):
        assert labels[f"fund_stress_{key}"] in section
    for wrong in ("No aplica", "Does not apply", "Não se aplica"):
        assert wrong not in section


def test_a_warning_the_shown_windows_do_not_support_is_not_shown(
    sample_data: dict[str, Any],
) -> None:
    """Only one equity window compared: fewer than the two the rule needs."""
    data = _with_index(sample_data, ("US500", "NAS100"))
    stress = data["crises"]
    del stress["windows"][1]["benchmark"]
    text = _text(_crises_html(stress, LABELS["en"], symbols=["US500"]))
    assert LABELS["en"]["crises_worse"].format(worse=1, n=1) not in text
    assert "To ask" not in text


@pytest.mark.parametrize("locale", LOCALES)
def test_the_locked_view_does_not_sell_crises_that_do_not_apply(
    sample_data: dict[str, Any], locale: str
) -> None:
    gain = LOCKED_GAINS[locale]["crises"]
    result = AuditResult.model_validate(sample_data)
    locked = _text(render_html(result, watermark=True, free_mode=False, locale=locale))
    assert LABELS[locale]["locked_intro"] in locked
    assert gain not in locked
    for promise in ("2008, el covid", "2008, covid", "2008, na covid"):
        assert promise not in locked
    # Where the crises apply, the lockbox still lists them.
    equities = AuditResult.model_validate(_with_index(sample_data, ("US500", "NAS100")))
    assert gain in _text(render_html(equities, watermark=True, free_mode=False, locale=locale))


@pytest.mark.parametrize("locale", LOCALES)
def test_the_landing_card_says_crises_of_other_markets_are_left_out(locale: str) -> None:
    text = next(text for icon, _, text in _UI[locale]["diffs"] if icon == "chart")
    expected = {
        "es": "se mide por separado, salvo las de mercados que no operas",
        "en": "is measured on its own, except those of markets you do not trade",
        "pt": "é medida à parte, exceto as de mercados que você não opera",
    }[locale]
    assert expected in text
    assert find_claims(expected) == []


# 4 · a share of more than 100 % -------------------------------------------------


def _over_100(data: dict[str, Any]) -> dict[str, Any]:
    """Thursdays and 16:00-19:59 earn more than the whole net result."""
    data = copy.deepcopy(data)
    timing = data["timing"]
    for rows, best_key, best_net in (
        (timing["weekdays"], 3, 1750.0),
        (timing["blocks"], 4, 1600.0),
    ):
        others = [row for row in rows if row["key"] != best_key]
        for row in rows:
            row["net"]["value"] = (
                best_net if row["key"] == best_key else (1000.0 - best_net) / len(others)
            )
    timing["net"]["value"] = 1000.0
    timing["best_weekday"] = {"key": 3, "share": {"value": 1.75, "evidence": "MEASURED"}}
    timing["best_block"] = {"key": 4, "share": {"value": 1.6, "evidence": "MEASURED"}}
    return data


@pytest.mark.parametrize("locale", LOCALES)
def test_a_share_above_100_percent_says_what_the_rest_takes_away(
    sample_data: dict[str, Any], locale: str
) -> None:
    section = _section(_page(_over_100(sample_data), locale), LABELS[locale]["timing"])
    day = {
        "es": "Los jueves suman el 175% del resultado neto: los demás días, juntos, restan "
        "750.00 (el 75%).",
        "en": "Thursdays add up to 175% of the net result: the other days together take away "
        "750.00 (75%).",
        "pt": "As operações de quinta-feira somam 175% do resultado líquido: os demais dias, "
        "juntos, subtraem 750.00 (75%).",
    }[locale]
    block = {
        "es": "La franja 16:00–19:59 suma el 160% del resultado neto: las demás franjas, "
        "juntas, restan 600.00 (el 60%).",
        "en": "The 16:00–19:59 session adds up to 160% of the net result: the other sessions "
        "together take away 600.00 (60%).",
        "pt": "A faixa 16:00–19:59 soma 160% do resultado líquido: as demais faixas, juntas, "
        "subtraem 600.00 (60%).",
    }[locale]
    assert day in section and block in section
    old = {"es": "El 175% del resultado neto sale", "en": "175% of the net result comes"}
    assert old.get(locale, "do resultado líquido sai") not in section
    assert find_claims(section) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_without_the_rest_figure_no_misleading_percentage(
    sample_data: dict[str, Any], locale: str
) -> None:
    data = _over_100(sample_data)
    del data["timing"]["net"]
    section = _section(_page(data, locale), LABELS[locale]["timing"])
    assert LABELS[locale]["timing_best_day_over_plain"].format(day="x").split("x")[-1] in section
    assert "175% del" not in section and "175% of" not in section and "175% do" not in section


@pytest.mark.parametrize("locale", LOCALES)
def test_one_instrument_above_100_percent_gives_the_others_figure(
    sample_data: dict[str, Any], locale: str
) -> None:
    data = copy.deepcopy(sample_data)
    review = data["instruments"]
    nets = {"AUDUSD": 1500.0, "EURUSD": -500.0}
    for row in review["rows"]:
        row["net"]["value"] = nets[row["key"]]
    review["best"] = {"key": "AUDUSD", "share": {"value": 1.5, "evidence": "MEASURED"}}
    review["findings"] = ["one_carries"]
    section = _section(_page(data, locale), LABELS[locale]["instruments"])
    line = {
        "es": "Más que el resultado neto viene de AUDUSD: los demás juntos restan 500.00 (el 50%)",
        "en": "More than the net result comes from AUDUSD: the others together subtract 500.00 "
        "(50%)",
        "pt": "Mais do que o resultado líquido vem de AUDUSD: os demais juntos subtraem 500.00 "
        "(50%)",
    }[locale]
    assert f"150% {line}" in section
    assert find_claims(line) == []


def test_a_share_up_to_100_percent_reads_as_before(sample_data: dict[str, Any]) -> None:
    section = _section(_page(sample_data, "es"), LABELS["es"]["timing"])
    assert "El 36% del resultado neto sale de los jueves." in section


# 5 · time under water: its unit, in whole periods ---------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_time_under_water_has_a_unit_and_whole_numbers(
    sample_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(sample_data, locale))
    label = LABELS[locale]["risk_underwater"].format(unit=LABELS[locale]["unit_daily_trading"])
    found = re.search(re.escape(label) + r": \S+ (\S+) \S+ , .*? 20 (\S+) ", text)
    assert found is not None, label
    assert found.group(1) == "72" and found.group(2) == "186"
    assert "186.05" not in text
    assert find_claims(label) == []
    # A density close to a calendar spacing names it; any other says the curve's periods.
    labels = LABELS[locale]
    for ppy, key in (
        (12.0, "unit_monthly"),
        (52.18, "unit_weekly"),
        (252.0, "unit_daily_trading"),
        (261.0, "unit_daily_trading"),
        (365.25, "unit_daily_calendar"),
        (6262.0, "unit_hourly"),
        (8766.0, "unit_hourly"),
        (None, "unit_periods"),
    ):
        assert _period_unit(ppy, labels) == labels[key], ppy
    assert _period_unit(26.0, labels) == labels["unit_periods_days"].format(n="14")
    assert _period_unit(100.0, labels) == labels["unit_periods_days"].format(n="3.7")
    assert _period_unit(1560.0, labels) == labels["unit_periods_hours"].format(n="5.6")


@pytest.mark.parametrize("locale", LOCALES)
def test_an_irregular_curve_is_not_counted_in_hours(
    sample_data: dict[str, Any], locale: str
) -> None:
    """One row per trade, about 500 a year: the density of "hourly", not hours."""
    data = copy.deepcopy(sample_data)
    data["inputs"]["periods_per_year"]["value"] = 500.0
    data["inputs"]["frequency_label"] = "hourly"
    text = _text(_page(data, locale))
    labels = LABELS[locale]
    unit = {
        "es": "periodos de la curva (de media, 18 horas de calendario cada uno)",
        "en": "curve periods (on average 18 calendar hours each)",
        "pt": "períodos da curva (em média, 18 horas corridas cada um)",
    }[locale]
    assert labels["risk_underwater"].format(unit=unit) in text
    assert labels["risk_underwater"].format(unit=labels["unit_hourly"]) not in text
    assert find_claims(unit) == []
    # A daily return series of 365 days a year counts calendar days.
    data["inputs"]["periods_per_year"]["value"] = 365.0
    data["inputs"]["frequency_label"] = "daily_trading"
    text = _text(_page(data, locale))
    assert labels["risk_underwater"].format(unit=labels["unit_daily_calendar"]) in text


# 6 · already below 0.5 at a single trial ----------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_below_half_at_one_trial_blames_the_signal_not_the_search(
    account_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(account_data, locale))
    assert ONE_TRIAL[locale] in text
    for wrong in ("Con 1 o más", "With 1 or more", "Com 1 ou mais"):
        assert wrong not in text
    step = next(s for s in improvement_plan(account_data, locale) if s.dimension == "multiplicity")
    assert ONE_TRIAL[locale] in step.finding
    # The actions follow: nothing about fewer or counted trials, which cannot lift the class.
    for wrong in ("reducen el número de intentos", "mean fewer trials", "reduzem o número"):
        assert wrong not in text
    for wrong in ("intentos pasa a ser medido", "count becomes measured", "passa a ser medido"):
        assert all(wrong not in action for action in step.actions)
    assert all("XML" not in action for action in step.actions)
    # What counts is the same account's history, not optimising a robot further.
    signal = {
        "es": "Lo que cuenta es más historial de la misma cuenta",
        "en": "What counts is more history of the same account",
        "pt": "O que conta é mais histórico da mesma conta",
    }[locale]
    assert any(signal in action for action in step.actions)
    assert signal in text
    assert all(find_claims(action) == [] for action in step.actions)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_fund_below_half_at_one_trial_is_not_asked_for_its_count(locale: str) -> None:
    data = {
        "fund": {"track_record": True},
        "multiplicity": {
            "status": "MEASURED",
            "trials_used": {"value": 1, "evidence": "MEASURED"},
            "dsr_at_trials_used": {"value": 0.3, "evidence": "MEASURED"},
            "trials_to_half": {"value": 1, "evidence": "MEASURED"},
        },
    }
    finding, actions = _multiplicity_step(data, "FAIL", locale)
    assert "0.5" in finding
    text = " ".join(actions)
    for wrong in ("decláralo", "declare it", "declare isso"):
        assert wrong not in text
    assert {
        "es": "más historial del mismo fondo",
        "en": "more history of the same fund",
        "pt": "mais histórico do mesmo fundo",
    }[locale] in text
    assert find_claims(text) == []


# 7 · two identical DSR rows ------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_same_trials_declared_and_used_show_one_dsr_row(
    sample_data: dict[str, Any], locale: str
) -> None:
    keys = KEY_LABELS[locale]
    section = _section(_page(sample_data, locale), LABELS[locale]["multiplicity"])
    assert f"{keys['dsr_at_declared_used']} 90.49%" in section
    # The other 90.49% is the 120-trial line of the sensitivity table below the rows.
    assert section.count("90.49%") == 2
    assert f"{keys['dsr_at_trials_used']} 90" not in section
    assert f"{keys['dsr_at_declared']} 90" not in section
    assert find_claims(keys["dsr_at_declared_used"]) == []


def test_undeclared_trials_keep_only_the_row_of_the_trials_used(
    account_data: dict[str, Any],
) -> None:
    keys = KEY_LABELS["es"]
    section = _section(_page(account_data, "es"), LABELS["es"]["multiplicity"])
    assert f"{keys['dsr_at_trials_used']} " in section
    assert keys["dsr_at_declared"] not in section
    assert keys["dsr_at_declared_used"] not in section


def test_different_trial_counts_keep_both_rows(sample_data: dict[str, Any]) -> None:
    data = copy.deepcopy(sample_data)
    data["declared"]["trials"]["value"] = 50
    keys = KEY_LABELS["en"]
    section = _section(_page(data, "en"), LABELS["en"]["multiplicity"])
    assert f"{keys['dsr_at_declared']} " in section and f"{keys['dsr_at_trials_used']} " in section
    assert keys["dsr_at_declared_used"] not in section


# 8 · a value the client never wrote is not "Declared" ----------------------------


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _upload(client: TestClient, **form: str) -> str:
    response = client.post(
        "/audits",
        files={"report": ("statement.csv", synthetic_live_statement(), "text/csv")},
        data={"consent": "on", "locale": "es", **form},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:500]
    return response.headers["location"]


def _json(client: TestClient, location: str) -> dict[str, Any]:
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1].split("&")[0]
    response = client.get(f"/audits/{audit_id}.json?token={token}")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def uploads(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, str, str]]:
    """The same statement sent with the form untouched, and with both answers given."""
    client = _client(tmp_path_factory.mktemp("informe-claro"))
    with client:
        blank = _upload(client)
        answered = _upload(client, cost_bps="2", benchmark_applicable="no")
        yield client, blank, answered


@pytest.mark.parametrize("locale", LOCALES)
def test_a_form_left_as_it_came_is_not_declared(
    uploads: tuple[TestClient, str, str], locale: str
) -> None:
    client, blank, _ = uploads
    declared = _json(client, blank)["declared"]
    for key, default in (("cost_bps_per_side", 0.0), ("benchmark_applicable", True)):
        assert declared[key] == {
            "value": default,
            "evidence": "NOT_MEASURED",
            "note": DEFAULT_NOT_DECLARED,
        }
    page = client.get(f"{blank}&lang={locale}").text
    section = _section(page, LABELS[locale]["declared"])
    note = i18n.localize(DEFAULT_NOT_DECLARED, locale)
    assert (
        note
        == {
            "es": "valor por defecto, no declarado",
            "en": "default value, not declared",
            "pt": "valor padrão, não declarado",
        }[locale]
    )
    keys = KEY_LABELS[locale]
    not_measured = evidence_label("NOT_MEASURED", locale)
    assert f"{keys['cost_bps_per_side']} 0.00 {not_measured} {note}" in section
    assert (
        f"{keys['benchmark_applicable']} {LABELS[locale]['yes']} {not_measured} {note}" in section
    )
    rows = section.removeprefix(LABELS[locale]["declared"]).split(keys["initial_balance"])[0]
    assert evidence_label("DECLARED", locale) not in rows
    # The cost section no longer says the client declared a zero cost.
    text = _text(page)
    for wrong in ("el cliente declaró costo cero", "client declared zero cost", "declarou custo"):
        assert wrong not in text
    assert find_claims(note) == []


def test_answers_the_client_gave_stay_declared(uploads: tuple[TestClient, str, str]) -> None:
    client, _, answered = uploads
    declared = _json(client, answered)["declared"]
    assert declared["cost_bps_per_side"]["evidence"] == "DECLARED"
    assert declared["cost_bps_per_side"]["value"] == 2.0
    assert declared["benchmark_applicable"] == {
        "value": False,
        "evidence": "DECLARED",
        "note": "",
    }


def test_the_cost_note_keeps_its_old_words_when_zero_was_declared() -> None:
    assert reference_note(True, False) == "assumed: client declared zero cost"
    assert reference_note(True, False, cost_declared=False) == "assumed: no cost declared"
    assert "no cost was declared" in reference_note(True, True, cost_declared=False)


@pytest.mark.parametrize("locale", LOCALES)
def test_an_assumed_reference_cost_is_never_declared(
    uploads: tuple[TestClient, str, str], locale: str
) -> None:
    """The cost left blank: Rigor assumed 0.5 bps of slippage, so the cost
    table, the challenge ladder and the public JSON never say Declared."""
    client, blank, _ = uploads
    result = _json(client, blank)
    reference = result["costs"]["reference_bps"]
    assert reference["value"] == 0.5 and reference["evidence"] == "NOT_MEASURED"
    assert reference["note"].startswith("assumed slippage: no cost was declared")
    costs = next(d for d in result["verdict"]["dimensions"] if d["name"] == "costs")
    assert costs["inputs"]["reference_bps_per_side"] == {
        "value": 0.5,
        "evidence": "NOT_MEASURED",
        "note": reference["note"],
    }
    text = _text(client.get(f"{blank}&lang={locale}").text)
    not_measured = evidence_label("NOT_MEASURED", locale)
    declared = evidence_label("DECLARED", locale)
    row = KEY_LABELS[locale]["reference_bps"]
    ladder = LABELS[locale]["ch_ladder_cost"].format(bps="0.5")
    assert f"{row} 0.5000 {not_measured}" in text
    assert f"{ladder} {not_measured}" in text
    for name in (row, ladder):
        assert not re.search(re.escape(name) + r" \S+ " + re.escape(declared), text)
        assert f"{name} {declared}" not in text
    for wrong in ("client declared zero cost", "el cliente declaró costo cero", "declarou custo"):
        assert wrong not in text


def test_a_zero_cost_declared_keeps_its_note_but_not_the_label(
    account_data: dict[str, Any],
) -> None:
    """0 written by the client: the 0.5 the costs use is still Rigor's assumption."""
    reference = account_data["costs"]["reference_bps"]
    assert reference["evidence"] == "NOT_MEASURED"
    assert "the client declared zero cost" in reference["note"]
    # The figure the costs and the tiles use does not change with the label.
    as_declared = copy.deepcopy(account_data)
    as_declared["costs"]["reference_bps"]["evidence"] = "DECLARED"
    for locale in LOCALES:
        assert _kpi_list(account_data, LABELS[locale]) == _kpi_list(as_declared, LABELS[locale])


def test_a_cost_the_client_wrote_stays_declared(uploads: tuple[TestClient, str, str]) -> None:
    client, _, answered = uploads
    result = _json(client, answered)
    assert result["costs"]["reference_bps"]["evidence"] == "DECLARED"
    assert result["costs"]["reference_bps"]["value"] == 2.0
    costs = next(d for d in result["verdict"]["dimensions"] if d["name"] == "costs")
    assert costs["inputs"]["reference_bps_per_side"]["evidence"] == "DECLARED"


def _benchmark_select(page: str) -> str:
    found = re.search(r"<select name='benchmark_applicable'[^>]*>(.*?)</select>", page, re.S)
    assert found is not None
    return found.group(1)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_benchmark_question_starts_unanswered(locale: str) -> None:
    select = _benchmark_select(upload_page(locale=locale))
    first, rest = select.split("</option>", 1)
    assert first.startswith("<option value='' selected>")
    assert " selected" not in rest
    label = {
        "es": "Sin respuesta (cuenta como sí)",
        "en": "No answer (counts as yes)",
        "pt": "Sem resposta (conta como sim)",
    }[locale]
    assert html.unescape(first).endswith(label)
    assert find_claims(label) == []
    # An answer carried back after a refusal stays selected.
    chosen = _benchmark_select(upload_page(locale=locale, carried={"benchmark_applicable": "yes"}))
    assert "<option value='yes' selected>" in chosen and "value='' selected" not in chosen


def test_an_explicit_yes_is_declared(uploads: tuple[TestClient, str, str]) -> None:
    client, _, _ = uploads
    declared = _json(client, _upload(client, benchmark_applicable="yes"))["declared"]
    assert declared["benchmark_applicable"] == {"value": True, "evidence": "DECLARED", "note": ""}


# 9 · forensics that no calibrated check could read -------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_uncalibrated_forensics_say_no_signal_either_way(
    account_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(account_data, locale))
    copy_ = INTEGRITY_TEXT[locale]
    assert copy_["forensic_none_uncalibrated"] in text
    assert copy_["forensic_none"] not in text
    either = {
        "es": "no hay señal ni a favor ni en contra",
        "en": "no signal either for or against",
        "pt": "não há sinal nem a favor nem contra",
    }[locale]
    assert either in copy_["forensic_none_uncalibrated"]
    assert find_claims(copy_["forensic_none_uncalibrated"]) == []


# 10 · an account is never called a backtest ---------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_an_account_report_does_not_call_it_a_backtest(
    account_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(account_data, locale))
    for phrase in ACCOUNT_AS_BACKTEST:
        assert phrase not in text, (locale, phrase)
    costs = next(d for d in account_data["verdict"]["dimensions"] if d["name"] == "costs")
    assert costs["status"] == "FAIL"
    assert meaning("costs", "FAIL", locale, account=True) in text
    step = next(
        s
        for s in improvement_plan(account_data, locale)
        if s.dimension == "statistical_significance"
    )
    for action in step.actions:
        assert "backtest" not in action
        assert find_claims(action) == []


# 11 · what the holdout seal's date proves ------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_seal_date_says_what_it_is_and_what_it_proves(
    sample_data: dict[str, Any], locale: str
) -> None:
    text = _text(_page(sample_data, locale))
    assert f"{KEY_LABELS[locale]['sealed_at_utc']} 2026-09-24" in text
    assert LABELS[locale]["seal_scope"] in text
    for old in ("Sellado (UTC)", "Sealed at (UTC)", "Selado em (UTC)"):
        assert old not in text
    assert find_claims(LABELS[locale]["seal_scope"]) == []


# 12 · /revision-institucional ------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_institutional_page_names_the_label_correctly(
    uploads: tuple[TestClient, str, str], locale: str
) -> None:
    client, _, _ = uploads
    text = _text(client.get(REVIEW_PATHS[locale]).text)
    expected = {
        "es": "Estos datos llevan la etiqueta «Declarado»",
        "en": "These details carry the Declared label",
        "pt": "Estes dados levam a etiqueta «Declarado»",
    }[locale]
    assert expected in text
    for wrong in ("son Declarado", "are Declared:", "são Declarado"):
        assert wrong not in text
    assert find_claims(REVIEW_COPY[locale]["note"]) == []


# Every new text passes the claims guard -----------------------------------------------


def test_every_new_text_passes_the_guard() -> None:
    keys = (
        "crises_not_applicable",
        "crises_not_covered",
        "crises_falls_us_equity",
        "crises_falls_crypto",
        "crises_falls_both",
        "crises_traded_us_equity",
        "crises_traded_crypto",
        "crises_that_market",
        "crises_those_markets",
        "unit_periods_days",
        "unit_periods_hours",
        "timing_best_day_over",
        "timing_best_day_over_plain",
        "timing_best_block_over",
        "timing_best_block_over_plain",
        "ins_best_over",
        "ins_best_over_plain",
        "risk_underwater",
        "seal_scope",
        "unit_daily_trading",
        "unit_periods",
        "luck_narrow",
    )
    for locale in LOCALES:
        for key in keys:
            assert find_claims(LABELS[locale][key]) == [], (locale, key)
        for key in ("dsr_at_declared_used", "sealed_at_utc"):
            assert find_claims(KEY_LABELS[locale][key]) == [], (locale, key)
        assert find_claims(INTEGRITY_TEXT[locale]["forensic_none_uncalibrated"]) == []
    for english, spanish in i18n._RULES_SOURCE:
        if "no cost" in english or english == DEFAULT_NOT_DECLARED:
            assert find_claims(english) == [] and find_claims(spanish) == []
    for english, portuguese in report_pt.RULES:
        if "no cost" in str(english) or english == DEFAULT_NOT_DECLARED:
            assert find_claims(str(portuguese)) == []
