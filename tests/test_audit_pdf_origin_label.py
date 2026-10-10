"""A PDF statement keeps its file-format label after column mapping."""

from __future__ import annotations

from quant_trade.audit.compare import comparison_body
from quant_trade.audit.importers import PDF_ROWS_WARNING
from quant_trade.audit.pages import verification_page
from quant_trade.audit.report import LABELS, render_html, source_name
from quant_trade.audit.sample import sample_result
from quant_trade.audit.store import public_view


def test_pdf_origin_survives_report_public_allowlist_and_comparison() -> None:
    csv = {"source_format": "universal_trades_csv", "parse_warnings": []}
    assert source_name(csv) == "CSV / Excel"
    assert source_name({**csv, "parse_warnings": [PDF_ROWS_WARNING]}) == "PDF"
    assert source_name({**csv, "parse_warnings": [f"report: {PDF_ROWS_WARNING}"]}) == "PDF"
    assert source_name({}, "CSV") == "CSV"

    result = sample_result("es", bootstrap_samples=60)
    result.inputs["source_format"] = "universal_trades_csv"
    result.inputs["parse_warnings"] = [f"report: {PDF_ROWS_WARNING}"]
    public, digest = public_view(result.model_dump_json())
    assert public["inputs"]["source_is_pdf"] is True
    assert "parse_warnings" not in public["inputs"]
    data = result.model_dump(mode="json")
    for locale in ("es", "en", "pt"):
        report = render_html(result, watermark=False, locale=locale)
        verified = verification_page(
            public,
            public_id="a1b2c3d4e5",
            published_at="2026-09-25T12:00:00Z",
            result_sha256=digest,
            base_url="https://example.test",
            locale=locale,
        )
        compared = comparison_body([data, data], hrefs=["/audits/a", "/audits/b"], locale=locale)
        three = comparison_body(
            [data, data, data], hrefs=["/audits/a", "/audits/b", "/audits/c"], locale=locale
        )
        assert f"{LABELS[locale]['report_source']}: PDF</p>" in report
        assert "CSV / Excel" not in report
        assert "<td>PDF</td>" in verified
        assert "CSV / Excel" not in verified
        assert compared.count(": PDF</p>") == 2
        assert "CSV / Excel" not in compared
        assert three.count(": PDF</p>") == 3
        assert "CSV / Excel" not in three
