"""The HTML says what the JSON says, escapes what the client typed, and passes the guard."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from audit_fixtures import best_of_n_walks, csv_bytes, positive_drift, spiked, trades_frame

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


def test_metric_tables_share_columns_so_values_line_up() -> None:
    from quant_trade.audit.sample import sample_result

    page = render_html(sample_result("es", bootstrap_samples=60), watermark=False, locale="es")
    tables = page.count("<table class='metrics'>")
    assert tables >= 3
    assert page.count("<col class='c-v'>") == tables
    assert page.count("<td class='val'>") >= 3 * tables
