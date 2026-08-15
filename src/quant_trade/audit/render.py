"""Dependency-free, fully escaped HTML renderer for audit bundles."""

from __future__ import annotations

from html import escape

from quant_trade.audit.models import AuditBundle


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def render_html(bundle: AuditBundle) -> str:
    """Render only escaped dynamic fields; no scripts or external resources."""
    rows = []
    for check in bundle.checks:
        evidence = "<br>".join(_e(item) for item in check.evidence) or "&mdash;"
        rows.append(
            "<tr>"
            f'<td class="code">{_e(check.code)}</td>'
            f"<td>{_e(check.category)}</td>"
            f"<td>{_e(check.finding_class.value)}</td>"
            f'<td class="{_e(check.status.value.lower())}">{_e(check.status.value)}</td>'
            f"<td>{_e(check.summary)}</td>"
            f"<td>{evidence}</td>"
            "</tr>"
        )
    reasons = "".join(f"<li>{_e(reason)}</li>" for reason in bundle.verdict.reasons)
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Quant Research Audit</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#17202a}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd1d1;"
        "padding:.55rem;text-align:left;vertical-align:top}th{background:#f4f6f7}"
        ".pass{color:#176b35;font-weight:700}.no_go{color:#a11;font-weight:700}"
        ".insufficient_evidence{color:#8a5a00;font-weight:700}.code{font-family:monospace}"
        ".warning{padding:1rem;background:#fff4d6;border-left:5px solid #d89b00}"
        "</style></head><body>"
        "<h1>Quant Research Audit</h1>"
        f"<p><strong>Verdict:</strong> {_e(bundle.verdict.status.value)}</p>"
        '<p class="warning"><strong>Research evidence only.</strong> '
        "This report does not establish expected profit and never authorizes "
        "real-money trading.</p>"
        f"<p><strong>Job:</strong> {_e(bundle.job.job_id)}<br>"
        "<strong>Bundle digest:</strong> "
        f'<span class="code">{_e(bundle.bundle_digest)}</span></p>'
        f"<ul>{reasons}</ul>"
        "<p><strong>DEFECT</strong> is an error in how a result was produced. "
        "<strong>RESULT</strong> is a correctly measured property of the result "
        "itself, such as not beating a benchmark. Both can block; only the first "
        "is a flaw in the method.</p>"
        "<table><thead><tr><th>Check</th><th>Category</th><th>Class</th><th>Status</th>"
        "<th>Summary</th><th>Evidence</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>\n"
    )
