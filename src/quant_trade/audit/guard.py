"""The profit-claim guard, extended to Spanish, applied to every report.

The repository already refuses English profit language in rendered
documents (``v9/economic_status.PROFIT_CLAIM_PATTERNS``). An audit sold to
Spanish-speaking clients needs the same refusal in Spanish, or the guard is
decoration. Both lists are applied to the report's own text and the report
is refused on any hit: a report that promises money is a bug, whatever the
verdict says.

The client's free-text description is scanned too, but never blocks: it is
their claim, reported back to them as a finding, and kept out of the HTML.
"""

from __future__ import annotations

import re
from typing import Any

from quant_trade.v9.economic_status import scan_for_unsupported_claims

#: Spanish equivalents of the V9 patterns. Word boundaries keep
#: "rentabilidad" (a neutral noun the report may need) out of the match.
SPANISH_CLAIM_PATTERNS: tuple[str, ...] = (
    r"\brentable\b",
    r"\bgaranti[sz]a(?:do|da|dos|das|mos|n)?\b",
    r"\bganancias?\s+(?:asegurad|garantizad)",
    r"\bbeneficios?\s+(?:asegurad|garantizad)",
    r"\bsin\s+riesgo\b",
    r"\blibre\s+de\s+riesgo\b",
    r"\bhazte\s+rico\b",
    r"\bdinero\s+seguro\b",
    r"\bgenera(?:r|rá|rán|n)?\s+(?:dinero|ganancias|ingresos|beneficios)\b",
    r"\bva(?:s|n)?\s+a\s+ganar\b",
)

CONTEXT = "in_sample_backtest"
SOURCE = "audit_report"


class AuditReportError(RuntimeError):
    """Raised when the audit's own text contains a profit claim."""


def _spanish_findings(text: str, *, source: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered = text.lower()
    for pattern in SPANISH_CLAIM_PATTERNS:
        for match in re.finditer(pattern, lowered):
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            findings.append(
                {
                    "text": text[start:end].replace("\n", " ").strip(),
                    "pattern": pattern,
                    "context": CONTEXT,
                    "reason": (
                        f"{source}: a profit claim (Spanish) appears in a {CONTEXT} context, "
                        "which carries no realized, reconciled money"
                    ),
                }
            )
    return findings


def find_claims(text: str, *, source: str = SOURCE) -> list[dict[str, Any]]:
    """Every English or Spanish profit claim in ``text``."""
    english = [
        finding.to_dict()
        for finding in scan_for_unsupported_claims(text, source=source, context=CONTEXT)
    ]
    return english + _spanish_findings(text, source=source)


def assert_report_clean(*texts: str) -> None:
    """Refuse a report whose own wording asserts money was or will be made."""
    hits: list[str] = []
    for text in texts:
        hits.extend(finding["pattern"] for finding in find_claims(text))
    if hits:
        raise AuditReportError(
            "the audit report contains profit-claim language that a backtest cannot support: "
            f"{sorted(set(hits))}"
        )


def scan_client_text(description: str) -> list[dict[str, Any]]:
    """The client's own claims, reported and never blocking."""
    if not description.strip():
        return []
    return find_claims(description, source="client_description")


__all__ = [
    "CONTEXT",
    "SPANISH_CLAIM_PATTERNS",
    "AuditReportError",
    "assert_report_clean",
    "find_claims",
    "scan_client_text",
]
