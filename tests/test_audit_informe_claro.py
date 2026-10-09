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

from quant_trade.audit import i18n, report_pt  # noqa: E402
from quant_trade.audit.costs import reference_note  # noqa: E402
from quant_trade.audit.crises import symbol_market, traded_markets  # noqa: E402
from quant_trade.audit.engine import DEFAULT_NOT_DECLARED, run_audit  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.institutional import COPY as REVIEW_COPY  # noqa: E402
from quant_trade.audit.institutional import REVIEW_PATHS  # noqa: E402
from quant_trade.audit.plan import _significance_step, improvement_plan  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    INTEGRITY_TEXT,
    KEY_LABELS,
    LABELS,
    _crises_html,
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
ONE_TRIAL = {
    "es": "Ya con 1 configuración, el caso más favorable, queda por debajo de 0.5: aquí "
    "decide la falta de significación, no el número de intentos.",
    "en": "Even at 1 configuration, the most favourable case, it is below 0.5: what decides "
    "here is the lack of significance, not the number of trials.",
    "pt": "Já com 1 configuração, o caso mais favorável, fica abaixo de 0.5: aqui quem decide "
    "é a falta de significância, não o número de tentativas.",
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
        (f"{copy_['forensic_rows']}: 2,573", f"{copy_['forensic_rows']}: 2573"),
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
    line = LABELS[locale]["crises_not_applicable"].format(symbols="AUDUSD, EURUSD")
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
    # Each spacing of the curve names its own period; an unnamed one says so.
    assert _period_unit("monthly", LABELS[locale]) == LABELS[locale]["unit_monthly"]
    assert _period_unit("intraday", LABELS[locale]) == LABELS[locale]["unit_periods"]


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
