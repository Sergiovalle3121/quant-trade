"""The HTML says what the JSON says, escapes what the client typed, and passes the guard."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from audit_fixtures import (
    best_of_n_walks,
    csv_bytes,
    positive_drift,
    spiked,
    trades_frame,
    variants_bytes,
)

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import AuditReportError, find_claims
from quant_trade.audit.report import DISCLAIMER, guard_texts, render, render_html, result_sha256
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _result(locale: str = "es", description: str = "", **files):
    inputs = build_inputs(
        csv_bytes(positive_drift(600)),
        DeclaredMetadata(
            trials=4,
            cost_bps_per_side=5,
            locale=locale,
            description=description,  # type: ignore[arg-type]
        ),
        **files,
    )
    return run_audit(inputs, now=NOW, audit_id="abc123", bootstrap_samples=200)


def test_html_carries_disclaimer_hashes_and_watermark_toggle() -> None:
    result = _result(trades_bytes=csv_bytes(trades_frame(20)))
    preview = render_html(result, watermark=True)
    full = render_html(result, watermark=False)
    assert DISCLAIMER["es"][:40] in preview
    assert "VISTA PREVIA" in preview
    assert "VISTA PREVIA" not in full
    for digest in result.inputs["digests"].values():
        assert digest in preview
    assert result_sha256(result) in preview
    assert "abc123" in preview
    assert "class='lockbox'" not in preview  # free mode locks nothing


def test_legacy_measured_cscv_without_effective_count_still_renders() -> None:
    winner, matrix = best_of_n_walks(trials=4, n=64)
    inputs = build_inputs(
        csv_bytes(winner),
        DeclaredMetadata(trials=4),
        variants_bytes=variants_bytes(matrix),
    )
    result = run_audit(
        inputs,
        now=NOW,
        audit_id="legacy-cscv",
        bootstrap_samples=50,
        risk_samples=50,
        challenge_samples=50,
    )
    assert result.cscv["status"] == "MEASURED"
    old_cscv = {key: value for key, value in result.cscv.items() if key != "effective_variants"}
    old_result = result.model_copy(update={"cscv": old_cscv})
    page = render_html(old_result, watermark=False)
    assert "parameter_variants=4" in page
    assert "effective_variants=" not in page


def test_paid_mode_locks_detail_until_paid() -> None:
    result = _result()
    unpaid = render_html(
        result,
        watermark=True,
        free_mode=False,
        price_usd=49,
        checkout_url="/audits/abc123/checkout",
    )
    assert "class='lockbox'" in unpaid
    assert "/audits/abc123/checkout" in unpaid
    assert "49" in unpaid
    paid = render_html(result, watermark=False, free_mode=False)
    assert "class='lockbox'" not in paid
    # Locked detail is not blurred: its numbers are absent from the page source.
    psr = f"{result.significance['psr']['value']:.2%}"
    cagr = f"{result.performance['cagr']['value']:.2%}"
    assert psr in paid and cagr in paid
    assert psr not in unpaid and cagr not in unpaid
    assert "PSR " not in unpaid
    # The verdict, the explanations and the charts stay free.
    for page in (unpaid, paid):
        assert "Qué significa para ti" in page
        assert "<svg" in page
        assert result.verdict.summary[:40] in page


def test_client_description_never_reaches_the_html() -> None:
    payload = "<script>alert(1)</script> estrategia rentable"
    result = _result(description=payload)
    html_text = render_html(result, watermark=True)
    assert "<script>" not in html_text
    assert "alert(1)" not in html_text
    assert "rentable" not in html_text
    assert result.declared["description"] == payload
    assert len(result.client_text_findings) == 1


@pytest.mark.parametrize("locale", ["es", "en"])
def test_rendered_reports_pass_the_guard(locale: str) -> None:
    winner, matrix = best_of_n_walks(trials=30, n=256)
    for frame in (positive_drift(600), spiked(spikes=5), winner):
        inputs = build_inputs(
            csv_bytes(frame),
            DeclaredMetadata(trials=30, locale=locale, description="makes money"),  # type: ignore[arg-type]
            trades_bytes=csv_bytes(trades_frame(15)),
        )
        result = run_audit(inputs, now=NOW, audit_id="x", bootstrap_samples=100)
        html_text, json_text = render(result, watermark=True)
        assert find_claims(html_text) == []
        assert json_text.endswith("\n")
        assert '"schema_version": 2' in json_text


def test_guard_refuses_an_injected_claim() -> None:
    result = _result()
    with pytest.raises(AuditReportError):
        guard_texts(result, "<p>this backtest is profitable</p>")


def test_platform_fields_and_flag_severities_read_in_the_report_language() -> None:
    from quant_trade.audit.report import platform_label

    assert platform_label("declared_total_deals", "es") == "Transacciones totales"
    assert platform_label("history_quality", "en") == "History quality"
    assert platform_label("some_new_field", "es") == "Some new field"
    inputs = build_inputs(csv_bytes(positive_drift(30)), DeclaredMetadata(trials=1))
    result = run_audit(inputs, bootstrap_samples=100)
    page = render_html(result, watermark=False, locale="es")
    assert {flag["severity"] for flag in result.red_flags} == {"FAIL", "WARN"}
    assert ">FAIL<" not in page and ">WARN<" not in page
    assert "Grave" in page and "Aviso" in page


def test_the_report_links_every_section_from_its_section_bar() -> None:
    import re

    from quant_trade.audit.sample import sample_result

    result = sample_result("es", bootstrap_samples=60)
    for locked in (False, True):
        page = render_html(
            result, watermark=locked, locale="es", free_mode=not locked, redeem_url="/r"
        )
        bar = page.split("class='report-toc", 1)[1].split("</nav>", 1)[0]
        targets = re.findall(r"href='#([\w-]+)'", bar)
        assert targets and len(targets) == len(set(targets))
        for target in targets:
            assert f"id='{target}'" in page, target
        assert ("unlock" in targets) is locked
    lead = result.verdict.summary.split(". ", 1)[0]
    assert f"<span class='verdict-lead'>{lead}.</span>" in page


def test_report_language_links_preserve_the_private_report_and_sample_paths() -> None:
    from quant_trade.audit.sample import sample_result

    result = sample_result("es", bootstrap_samples=60)
    private = "/audits/abc123?token=sample%2Btoken&lang=en"
    for locale in ("es", "en", "pt"):
        page = render_html(result, watermark=False, locale=locale, switch_url=private)
        assert "class='report-languages'" in page
        for target in {"es", "en", "pt"} - {locale}:
            assert (
                f"href='/audits/abc123?token=sample%2Btoken&amp;lang={target}' hreflang='{target}'"
            ) in page
        assert f"hreflang='{locale}'" not in page

    for locale, alternate in (
        ("es", "/sample?lang=en"),
        ("en", "/ejemplo?lang=es"),
        ("pt", "/ejemplo?lang=es"),
    ):
        page = render_html(result, watermark=False, locale=locale, switch_url=alternate)
        for target, path in (("es", "/ejemplo"), ("en", "/sample"), ("pt", "/pt/exemplo")):
            if target != locale:
                assert f"href='{path}' hreflang='{target}'" in page


def test_secondary_analysis_folds_without_hiding_alerts_or_pdf_content() -> None:
    from quant_trade.audit.pdf import _expand_details_for_pdf
    from quant_trade.audit.sample import sample_result
    from quant_trade.audit.theme import STYLE

    result = sample_result("es", bootstrap_samples=60)
    full = render_html(result, watermark=False, locale="es")
    assert full.count("<details open class='detail report-detail'") >= 10
    assert "<summary><h2>Rendimiento anualizado" in full
    assert "<section class='detail'" in full
    assert "<h2>Costes de operación</h2>" in full
    assert "<h2>Banderas rojas</h2>" in full
    assert "id='r-next'" in full and "id='r-flags'" in full
    assert "id='r-inputs'" in full and "<h2>No medido</h2>" in full
    assert ".report-detail:not([open])>.detail-body{display:block!important}" in STYLE
    # An older saved report with closed details is opened by the PDF renderer.
    closed = full.replace(
        "<details open class='detail report-detail", "<details class='detail report-detail"
    )
    pdf_html = _expand_details_for_pdf(closed)
    assert pdf_html.count("<details open class='detail report-detail'") == full.count(
        "<details open class='detail report-detail'"
    )
    assert "<details class='detail report-detail'" not in pdf_html


def test_reconciliation_and_forensic_signal_remain_visible_in_every_language() -> None:
    from quant_trade.audit.pdf import _expand_details_for_pdf

    def measured(value: float) -> dict[str, object]:
        return {"value": value, "evidence": "MEASURED", "note": ""}

    missing = {"value": None, "evidence": "NOT_MEASURED", "note": "not supplied"}
    recon = {
        "status": "CONTRADICTION",
        "reason": "printed balance contradicts deal amounts",
        "currency": "USD",
        "coverage": {
            "curve": "rebuilt from the platform deal rows",
            "closed_trades": 2,
            "trades_outside_curve": 0,
            "flows": "not supplied",
            "open_positions": "not valued separately",
            "currency": "USD",
        },
        "initial_capital": measured(10000.0),
        "cash_flows_after_start": missing,
        "gross_closed_pnl": measured(60.0),
        "itemised_costs": measured(10.0),
        "net_closed_pnl": measured(50.0),
        "open_position_value": missing,
        "expected_final": measured(10050.0),
        "observed_final": measured(11050.0),
        "difference": measured(1000.0),
        "tolerance": measured(1.0),
    }
    forensics = {
        "method_version": "forensics-1",
        "family": "mt5_tester",
        "rows_read": 2,
        "truncated": False,
        "checks": [
            {
                "id": "BALANCE_CHAIN",
                "status": "SIGNAL",
                "figures": [["broken_links", "1", "MEASURED"]],
                "calibration": [
                    ["n", "26"],
                    ["groups", "26"],
                    ["n_reserved", "13"],
                    ["unexplained", "0"],
                    ["cp95_upper_pct", "13.2"],
                    ["frozen", "2026-09-26"],
                ],
            },
            {"id": "FILE_TRACE", "status": "INFO", "calibration": [], "figures": []},
        ],
    }
    result = _result().model_copy(update={"reconciliation": recon, "forensics": forensics})
    assert result.model_dump(mode="json")["reconciliation"]["difference"]["value"] == 1000.0
    assert result.model_dump(mode="json")["forensics"]["checks"][0]["status"] == "SIGNAL"
    for locale, titles in (
        ("es", ("Conciliación monetaria", "Coherencia interna del archivo", "Cadena de saldos")),
        ("en", ("Money reconciliation", "Internal file consistency", "Balance chain")),
        ("pt", ("Conciliação monetária", "Coerência interna do arquivo", "Cadeia de saldos")),
    ):
        page = render_html(result, watermark=False, locale=locale)
        assert all(title in page for title in titles)
        assert "10,000.00" in page and "11,050.00" in page and "1,000.00" in page
        assert "forensics-1" in page and "2026-09-26" in page
        assert "BALANCE_CHAIN" in page and "broken links" in page
        assert page.index("id='r-reconciliation'") < page.index("<details open class='detail")
        assert page.index("id='r-forensics'") < page.index("<details open class='detail")
        pdf_html = _expand_details_for_pdf(page)
        assert "<details open class='detail report-detail forensic-all'" in pdf_html

    separate = {
        **recon,
        "currency": "UNKNOWN",
        "coverage": {
            **recon["coverage"],
            "curve": "separate upload",
            "currency": "not stated; same units assumed",
            "trade_currency": "USD",
            "curve_currency": "not supplied",
        },
    }
    separate_result = result.model_copy(update={"reconciliation": separate})
    for locale, statements in (
        (
            "es",
            (
                "USD según las operaciones",
                "Moneda indicada en operaciones",
                "Moneda indicada en la curva:",
            ),
        ),
        (
            "en",
            (
                "USD according to trades",
                "Currency stated by trades",
                "Currency stated by the curve:",
            ),
        ),
        (
            "pt",
            (
                "USD conforme as operações",
                "Moeda informada nas operações",
                "Moeda informada na curva:",
            ),
        ),
    ):
        page = render_html(separate_result, watermark=False, locale=locale)
        assert all(statement in page for statement in statements)


def test_metric_tables_share_columns_so_values_line_up() -> None:
    from quant_trade.audit.sample import sample_result

    page = render_html(sample_result("es", bootstrap_samples=60), watermark=False, locale="es")
    tables = page.count("<table class='metrics ev'>")
    assert tables >= 3
    # On phones each evidence row becomes a card: name and value, then label and note.
    assert ".metrics.ev tr{display:grid;" in page
    assert page.count("<col class='c-v'>") == tables
    assert page.count("<td class='val'>") >= 3 * tables


def test_stress_tables_mark_scenarios_that_fall_to_zero_or_below() -> None:
    from quant_trade.audit.sample import sample_result

    result = sample_result("es", bootstrap_samples=60)
    page = render_html(result, watermark=False, locale="es")
    tables = page.count("<table class='stress'>")
    assert tables >= 1 and page.count("<tr class='base'>") == tables
    stress = result.stress or {}
    below = sum(
        1
        for block in (stress.get("returns") or {}, stress.get("trades") or {})
        for row in block.get("rows", [])
        if row["result"]["value"] <= 0
    )
    shown = "".join(
        part.split("</table>", 1)[0] for part in page.split("<table class='stress'>")[1:]
    )
    assert shown.count("<td class='val neg' data-l=") == below


def test_locked_preview_links_the_full_sample_in_a_new_tab() -> None:
    result = _result()
    for locale, href, words in (
        ("es", "/ejemplo", "Ver cómo es un informe completo"),
        ("en", "/sample", "See what a full report looks like"),
    ):
        unpaid = render_html(
            result,
            watermark=True,
            free_mode=False,
            price_usd=29,
            redeem_url="/audits/abc123/redeem",
            contact_url="https://wa.me/5215550000000",
            locale=locale,
        )
        assert f"<a href='{href}' target='_blank' rel='noopener'>{words}" in unpaid
        assert "lee mal tu archivo" in unpaid if locale == "es" else "misreads your file" in unpaid
    assert "class='lock-sample'" not in render_html(result, watermark=False, free_mode=False)


def test_lockbox_lists_what_the_buyer_gets_in_plain_words() -> None:
    from quant_trade.audit.guard import find_claims
    from quant_trade.audit.report import LABELS, LOCKED_GAINS

    assert LOCKED_GAINS["es"].keys() == LOCKED_GAINS["en"].keys()
    assert set(LOCKED_GAINS["es"]) <= set(LABELS["es"])
    result = _result()
    for locale in ("es", "en"):
        unpaid = render_html(
            result,
            watermark=True,
            free_mode=False,
            price_usd=29,
            checkout_url="/audits/abc123/checkout",
            locale=locale,
        )
        box = unpaid.split("class='lockbox'", 1)[1].split("class='lock-sample'", 1)[0]
        assert LOCKED_GAINS[locale]["significance"] in box
        for technical in ("bootstrap", "multiplicity", "cscv", "rolling"):
            assert LABELS[locale][technical] not in box
        assert find_claims(box) == []
