"""Three reports side by side: the same rules per report, two stay as they were."""

from __future__ import annotations

import html
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, signed_in, trades_frame

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, comparison_delta, pricing  # noqa: E402
from quant_trade.audit.compare import (  # noqa: E402
    COPY,
    MAX_COMPARED,
    _card,
    _e,
    _figure_cell,
    _kpi_cells,
    _status_cell,
    compare_form,
    comparison_body,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import PAGE_DESCRIPTIONS  # noqa: E402
from quant_trade.audit.report import LABELS, _dimension_title  # noqa: E402
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.settings import PACK_CREDITS, AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.verdict import DIMENSION_ORDER  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

LOCALES = ("es", "en", "pt")
PATHS = {"es": "/comparar", "en": "/compare", "pt": "/pt/comparar"}
ACCOUNT = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _stored() -> dict[str, Any]:
    return {
        "inputs": {
            "first_timestamp": "2024-01-01T00:00:00Z",
            "last_timestamp": "2024-12-31T00:00:00Z",
            "frequency_label": "daily",
            "periods_per_year": {"evidence": "MEASURED", "value": 252},
            "balance_only": False,
            "source_format": "csv",
        },
        "performance": {
            "sharpe": {"evidence": "MEASURED", "value": 0.5},
            "max_drawdown": {"evidence": "MEASURED", "value": -0.1},
        },
        "verdict": {"overall": "D", "dimensions": [{"name": "costs", "status": "FAIL"}]},
        "red_flags": [],
    }


def _two_columns(a: dict[str, Any], b: dict[str, Any], href_a: str, href_b: str, locale: str):
    """The two-report body exactly as it was built before three were possible."""
    copy, labels = COPY[locale], LABELS[locale]
    head = (
        "<div class='cmp-head'>"
        + _card(a, copy["report_a"], href_a, locale)
        + _card(b, copy["report_b"], href_b, locale)
        + "</div>"
    )
    dims_a = {d["name"]: d["status"] for d in a["verdict"]["dimensions"]}
    dims_b = {d["name"]: d["status"] for d in b["verdict"]["dimensions"]}
    dim_rows = "".join(
        f"<tr><td>{_e(_dimension_title(name, locale))}</td>"
        f"<td>{_status_cell(dims_a.get(name, 'NOT_MEASURED'), locale)}</td>"
        f"<td>{_status_cell(dims_b.get(name, 'NOT_MEASURED'), locale)}</td></tr>"
        for name in DIMENSION_ORDER
    )
    kpis_a, kpis_b = [_kpi_cells(data, labels) for data in (a, b)]
    order = list(kpis_a) + [label for label in kpis_b if label not in kpis_a]
    figure_rows = "".join(
        f"<tr><td>{_e(label)}</td>"
        f"{_figure_cell(kpis_a.get(label), locale, kpis_a.get(label) != kpis_b.get(label))}"
        f"{_figure_cell(kpis_b.get(label), locale, kpis_a.get(label) != kpis_b.get(label))}</tr>"
        for label in order
    )
    header = f"<tr><th></th><th>{_e(copy['report_a'])}</th><th>{_e(copy['report_b'])}</th></tr>"
    return (
        head
        + comparison_delta.change_summary(a, b, locale)
        + f"<h2>{_e(copy['dimensions'])}</h2><table class='cmp'>{header}{dim_rows}</table>"
        + f"<h2>{_e(copy['figures'])}</h2><table class='cmp'>{header}{figure_rows}</table>"
        + f"<p class='muted'>{_e(copy['note'])}</p>"
    )


def _pairs(locale: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    sample = sample_result(locale, bootstrap_samples=60).model_dump(mode="json")
    changed = deepcopy(sample)
    changed["performance"]["sharpe"]["value"] = 0.123
    changed["verdict"]["overall"] = "B"
    declared, missing = _stored(), _stored()
    declared["performance"]["sharpe"]["evidence"] = "DECLARED"
    missing["performance"]["max_drawdown"] = {"evidence": "MEASURED", "value": None}
    broken = _stored()
    broken["inputs"] = "private-context"
    later = _stored()
    later["inputs"]["first_timestamp"] = "2024-01-02T00:00:00Z"
    return [
        (sample, changed),
        (sample, sample),
        (declared, missing),
        (_stored(), broken),
        (_stored(), later),
        (_stored(), sample),
    ]


@pytest.mark.parametrize("locale", LOCALES)
def test_two_reports_give_the_same_html_as_before(locale: str) -> None:
    for a, b in _pairs(locale):
        before = deepcopy((a, b))
        body = comparison_body([a, b], hrefs=["/x?token=t&lang=es", "/y"], locale=locale)
        assert body == _two_columns(a, b, "/x?token=t&lang=es", "/y", locale)
        assert "cmp3" not in body and "cmp-scroll" not in body
        assert (a, b) == before


def test_a_comparison_takes_two_or_three_results_each_with_its_link() -> None:
    one = _stored()
    with pytest.raises(ValueError):
        comparison_body([one], hrefs=["/a"], locale="es")
    with pytest.raises(ValueError):
        comparison_body([one] * (MAX_COMPARED + 1), hrefs=["/a"] * 4, locale="es")
    with pytest.raises(ValueError):
        comparison_body([one, one, one], hrefs=["/a", "/b"], locale="es")


def _figure_row(body: str, label: str) -> list[str]:
    row = re.search(rf"<tr><td>{re.escape(html.escape(label))}</td>(.*?)</tr>", body, re.S)
    assert row is not None, label
    return re.findall(r"<td[^>]*>.*?</td>", row.group(1), re.S)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_figure_is_different_unless_it_is_the_same_in_all_three(locale: str) -> None:
    a, b, c = _stored(), _stored(), _stored()
    c["performance"]["sharpe"]["value"] = 0.8
    body = comparison_body([a, b, c], hrefs=["/a", "/b", "/c"], locale=locale)
    sharpe = _figure_row(body, LABELS[locale]["kpi_sharpe"])
    drawdown = _figure_row(body, LABELS[locale]["kpi_drawdown"])
    assert len(sharpe) == len(drawdown) == 3
    # Two equal and one apart: the row is marked in every column.
    assert all(cell.startswith("<td class=diff>") for cell in sharpe)
    assert ">0.50<" in sharpe[0] and ">0.50<" in sharpe[1] and ">0.80<" in sharpe[2]
    assert not any("diff" in cell for cell in drawdown)
    # The header, the cards and both tables carry three reports.
    keys = ("report_a", "report_b", "report_c")
    header = "".join(f"<th>{COPY[locale][key]}</th>" for key in keys)
    assert body.count(f"<tr><th></th>{header}</tr>") == 2
    assert body.count("class='cmp-card'") == 3 and "<div class='cmp-head cmp3'>" in body
    assert body.count("<div class='cmp-scroll'><table class='cmp cmp3'>") == 2
    assert find_claims(body) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_three_show_the_change_summary_only_for_versions_of_one_strategy(locale: str) -> None:
    a, b, c = _stored(), _stored(), _stored()
    b["verdict"]["overall"], c["verdict"]["overall"] = "C", "B"
    c["inputs"] = "private-context"
    words = comparison_delta.COPY[locale]
    apart = comparison_body([a, b, c], hrefs=["/a", "/b", "/c"], locale=locale)
    assert html.escape(COPY[locale]["summary_three"]) in apart
    assert "<section class='cmp-summary'" not in apart
    assert words["title"] not in html.unescape(apart)
    versions = comparison_body([a, b, c], hrefs=["/a", "/b", "/c"], locale=locale, same_system=True)
    text = html.unescape(versions)
    assert COPY[locale]["summary_three"] not in text
    assert words["title_pair"].format(a=1, b=2) in text
    assert words["title_pair"].format(a=2, b=3) in text
    assert words["delta_pair"].format(a=2, b=3) in text
    assert words["class"].format(a="D", b="C") in text
    assert words["class"].format(a="C", b="B") in text
    # The third report's broken context is named as report 3, not as report 2.
    reason = comparison_delta.REASONS[locale]["context_invalid"]
    assert f"{words['report'].format(n=3)}: {reason}" in text
    assert f"{words['report'].format(n=2)}: {reason}" not in text
    # Each summary keeps its own ids, so the page has no duplicate.
    ids = re.findall(r"id='([^']+)'", versions)
    assert len(ids) == len(set(ids)) and "comparison-changes-2-3" in ids
    assert "private-context" not in versions
    assert find_claims(text) == [] and find_claims(html.unescape(apart)) == []


def _client(tmp_path: Path, **overrides: Any) -> tuple[TestClient, Any]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    store = make_store(settings.database_url)
    return signed_in(TestClient(create_app(settings, store))), store


def _upload(client: TestClient, frame, *, trades: bool = True) -> str:
    files = {"equity": ("equity.csv", csv_bytes(frame), "text/csv")}
    if trades:
        files["trades"] = ("trades.csv", csv_bytes(trades_frame(20)), "text/csv")
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303
    return "https://rigor.example" + response.headers["location"]


def _three(client: TestClient) -> list[str]:
    return [
        _upload(client, positive_drift(500)),
        _upload(client, returns_frame(300, mean=0.0, seed=4), trades=False),
        _upload(client, positive_drift(400)),
    ]


def _audit_id(link: str) -> str:
    return link.split("/audits/")[1].split("?")[0]


def _columns(page: str, locale: str) -> None:
    words = COPY[locale]
    header = "".join(f"<th>{words[key]}</th>" for key in ("report_a", "report_b", "report_c"))
    assert page.count(f"<tr><th></th>{header}</tr>") == 2
    assert page.count("class='cmp-card'") == 3
    assert "<td class=diff>" in page


def test_three_reports_compare_over_http_in_every_language(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    links = _three(client)
    for locale in LOCALES:
        data = {"link_a": links[0], "link_b": links[1], "link_c": links[2], "lang": locale}
        page = client.post(PATHS[locale], data=data)
        assert page.status_code == 200, page.text[:300]
        _columns(page.text, locale)
        assert f"<html lang='{locale}'" in page.text
        assert f"<title>{COPY[locale]['title_three']}" in page.text
        # Not filed in one strategy: no change summary, and a line says why.
        assert html.escape(COPY[locale]["summary_three"]) in page.text
        assert "<section class='cmp-summary'" not in page.text
        for link in links:
            assert link.split("rigor.example", 1)[1] + f"&amp;lang={locale}" in page.text
        assert "noindex" in page.text
        assert find_claims(page.text) == []
    # The third field left empty compares two, as before.
    two = client.post("/comparar", data={"link_a": links[0], "link_b": links[1], "link_c": " "})
    assert two.status_code == 200 and "<div class='cmp-head'>" in two.text
    assert f"<title>{COPY['es']['title']}" in two.text
    assert "<section class='cmp-summary'" in two.text


def test_the_form_offers_an_optional_third_link(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    for locale in LOCALES:
        page = client.get(PATHS[locale]).text
        assert f"<title>{COPY[locale]['title_form']}" in page
        field = page.split("name='link_c'", 1)[1].split(">", 1)[0]
        assert "required" not in field
        assert COPY[locale]["link_c"] in html.unescape(page)
        assert find_claims(page) == []
    assert "required" not in compare_form("es").split("name='link_c'", 1)[1].split(">", 1)[0]


def test_a_locked_report_among_three_gets_todays_402(tmp_path: Path) -> None:
    client, store = _client(
        tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0"
    )
    links = _three(client)
    for n, link in enumerate(links[:2]):
        store.mark_paid(_audit_id(link), stripe_session_id=f"cs-three-{n}", at=NOW)
    # Two unlocked compare; the locked third, in any position, gets the 402.
    two = client.post("/comparar", data={"link_a": links[0], "link_b": links[1]})
    assert two.status_code == 200
    for order in ((0, 1, 2), (2, 0, 1), (0, 2, 1)):
        data = dict(zip(("link_a", "link_b", "link_c"), (links[i] for i in order), strict=True))
        for locale in LOCALES:
            page = client.post(PATHS[locale], data={**data, "lang": locale})
            assert page.status_code == 402
            assert html.escape(COPY[locale]["locked"]) in page.text
            assert "class='cmp-card'" not in page.text and "<td class=diff>" not in page.text


def test_a_repeated_or_unreadable_third_link_is_refused(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    links = _three(client)
    path_only = links[0].split("rigor.example", 1)[1]
    for third in (links[0], links[1], path_only):
        page = client.post(
            "/compare", data={"link_a": links[0], "link_b": links[1], "link_c": third}
        )
        assert page.status_code == 400
        assert COPY["en"]["same"] in page.text
    bad = client.post("/comparar", data={"link_a": links[0], "link_b": links[1], "link_c": "hola"})
    assert bad.status_code == 400 and COPY["es"]["bad_link"] in html.unescape(bad.text)
    forged = links[2].split("token=")[0] + "token=" + "A" * 43
    data = {"link_a": links[0], "link_b": links[1], "link_c": forged}
    wrong = client.post("/comparar", data=data)
    assert wrong.status_code == 404


def _file(store: Any, ids: list[str]) -> None:
    account = store.find_account("tester@example.com")
    strategy = store.create_strategy(account.id, "EA Oro", at=NOW)
    for audit_id in ids:
        assert store.file_report(account.id, audit_id, strategy, at=NOW)


def test_versions_of_one_strategy_show_what_changed_between_each_pair(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    links = _three(client)
    ids = [_audit_id(link) for link in links]
    _file(store, ids)
    data = {"link_a": links[0], "link_b": links[1], "link_c": links[2]}
    page = html.unescape(client.post("/comparar", data=data).text)
    words = comparison_delta.COPY["es"]
    assert words["title_pair"].format(a=1, b=2) in page
    assert words["title_pair"].format(a=2, b=3) in page
    assert COPY["es"]["summary_three"] not in page
    shown = html.unescape(client.get("/cuenta/comparar?" + "&".join(f"id={i}" for i in ids)).text)
    assert words["title_pair"].format(a=2, b=3) in shown
    # Someone who did not file them sees the three columns without the summary.
    other = signed_in(TestClient(client.app), email="otra@example.com")
    apart = other.post("/comparar", data=data)
    assert apart.status_code == 200
    assert html.escape(COPY["es"]["summary_three"]) in apart.text
    assert "<section class='cmp-summary'" not in apart.text
    # Two of them filed and the third elsewhere: no summary either.
    account = store.find_account("tester@example.com")
    assert store.file_report(account.id, ids[2], "", at=NOW)
    loose = client.post("/comparar", data=data).text
    assert "<section class='cmp-summary'" not in loose


def test_the_account_lets_the_customer_pick_three(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    ids = [_audit_id(link) for link in _three(client)]
    page = client.get("/cuenta").text
    picker = page.split("action='/cuenta/comparar'", 1)[1].split("</form>", 1)[0]
    assert all(f"name='id' value='{audit_id}'" in picker for audit_id in ids)
    assert html.escape(account_pages.COPY["es"]["compare_help"]) in picker
    query = "&".join(f"id={audit_id}" for audit_id in ids)
    for locale in LOCALES:
        shown = client.get(f"{ACCOUNT[locale]}/comparar?{query}")
        assert shown.status_code == 200
        _columns(shown.text, locale)
        assert f"<title>{COPY[locale]['title_three']}" in shown.text
        assert html.escape(account_pages.COPY[locale]["compare_lead_three"]) in shown.text
        for audit_id in ids:
            assert f"/audits/{audit_id}?lang={locale}" in shown.text
        assert "token=" not in shown.text
        # The shareable address in the other languages carries the three reports.
        for other in set(LOCALES) - {locale}:
            assert f"{ACCOUNT[other]}/comparar?{query.replace('&', '&amp;')}" in shown.text
        assert find_claims(re.sub(r"<[^>]+>", " ", shown.text)) == []
    # That address opens the same comparison again, from another language too.
    again = client.get(f"/pt/conta/comparar?{query}")
    assert again.status_code == 200
    _columns(again.text, "pt")

    def refused(query: str) -> bool:
        answer = client.get(f"/cuenta/comparar?{query}", follow_redirects=False)
        return answer.status_code == 303 and "error=compare_pick" in answer.headers["location"]

    fourth = _audit_id(_upload(client, positive_drift(450)))
    assert refused(f"{query}&id={fourth}")  # four
    assert refused(f"id={ids[0]}&id={ids[1]}&id={ids[0]}")  # one report twice
    assert refused(f"id={ids[0]}&id={ids[1]}&id=nope")  # not on the list
    assert not refused(f"id={ids[0]}&id={fourth}")


def test_the_pack_card_mentions_the_comparison_while_it_fits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AuditSettings.from_env(
        {
            "AUDIT_FREE_MODE": "false",
            "AUDIT_ACCESS_CODES": "true",
            "AUDIT_PRICE_USD_CENTS": "2900",
            "AUDIT_PACK_PRICE_USD_CENTS": "6900",
        }
    )
    assert settings.pack_price_usd and PACK_CREDITS <= MAX_COMPARED
    for locale in LOCALES:
        words = pricing.PRICING_COPY[locale]
        page = html.unescape(pricing.pricing_page(settings, locale=locale))
        assert words["pack_text"].format(n=PACK_CREDITS) in page
        assert words["compare"] in page and words["compare_note"] in page
    # A larger pack than one comparison holds keeps the plain sentence.
    monkeypatch.setattr("quant_trade.audit.pricing.PACK_CREDITS", MAX_COMPARED + 2)
    for locale in LOCALES:
        words = pricing.PRICING_COPY[locale]
        page = html.unescape(pricing.pricing_page(settings, locale=locale))
        assert words["pack_text_plain"].format(n=MAX_COMPARED + 2) in page
        assert words["pack_text"].format(n=MAX_COMPARED + 2) not in page


def test_every_new_sentence_passes_the_claim_guard_in_every_language() -> None:
    for locale in LOCALES:
        texts = [
            COPY[locale][key]
            for key in ("title_three", "title_form", "lead", "link_c", "report_c", "same")
        ]
        texts.append(COPY[locale]["summary_three"])
        texts += [
            comparison_delta.COPY[locale][f"{key}_pair"].format(a=2, b=3)
            for key in ("title", "added", "removed", "delta")
        ]
        texts += [
            account_pages.COPY[locale][key]
            for key in ("compare_button", "compare_help", "compare_pick", "compare_lead_three")
        ]
        words = pricing.PRICING_COPY[locale]
        texts += [
            words["pack_text"].format(n=3),
            words["pack_text_plain"].format(n=3),
            words["compare"],
            words["compare_note"],
            PAGE_DESCRIPTIONS["compare"][locale],
        ]
        for text in texts:
            assert find_claims(text) == [], text
            for word in ("verificado", "certificado", "aprobado", "garantiza", "rentable"):
                assert word not in text.lower(), text
