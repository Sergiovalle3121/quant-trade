"""The profit-claim guard, extended to Spanish, applied to every report.

The repository already refuses English profit language in rendered
documents (``v9/economic_status.PROFIT_CLAIM_PATTERNS``). An audit sold to
Spanish-speaking clients needs the same refusal in Spanish, or the guard is
decoration. Both lists are applied to the report's own text and the report
is refused on any hit: a report that promises money is a bug, whatever the
verdict says.

The client's free-text description is scanned too, but never blocks: it is
their claim, reported back to them as a finding, and kept out of the HTML.

Endorsement words ("verificado", "certificado", "aprobado", "certified")
are refused as well: an audit of supplied data cannot certify a track record
or approve a robot. A small set of patterns (``NEGATABLE_PATTERNS``) is
allowed when directly negated, so the fixed disclaimers "no verificados con
el bróker" and "no garantiza resultados" pass while "resultados verificados"
does not.
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
    r"\bverificad[oa]s?\b",
    r"\bcertificad[oa]s?\b",
    r"\bcertificado\s+de\s+rentabilidad\b",
    r"\baprobad[oa]s?\b",
    r"\bpasar[áa]s\b",
    r"\bsuperar[áa]s\b",
    r"\bva(?:s|n)?\s+a\s+(?:pasar|superar|aprobar)\b",
)

#: English endorsement and pass-the-challenge wording the V9 list lacks.
ENGLISH_ENDORSEMENT_PATTERNS: tuple[str, ...] = (
    r"\bverified\s+(?:track\s+record|results?|returns?|profits?|performance)\b",
    r"\bcertified\b",
    r"\bapproved\b",
    r"\byou(?:'ll|\s+will)\s+pass\b",
    r"\bguaranteed\s+to\s+pass\b",
)

#: Patterns that do not count when one of the two preceding words is a
#: negation: the claim is being denied, not made.
NEGATABLE_PATTERNS: frozenset[str] = frozenset(
    {
        r"\bgaranti[sz]a(?:do|da|dos|das|mos|n)?\b",
        r"\bverificad[oa]s?\b",
        r"\bcertificad[oa]s?\b",
        r"\baprobad[oa]s?\b",
        r"\bcertified\b",
        r"\bapproved\b",
    }
)
NEGATIONS: frozenset[str] = frozenset({"no", "not", "never", "nunca", "sin", "ni", "nor"})

CONTEXT = "in_sample_backtest"
SOURCE = "audit_report"


class AuditReportError(RuntimeError):
    """Raised when the audit's own text contains a profit claim."""


def _negated(lowered: str, start: int) -> bool:
    preceding = re.findall(r"[^\W\d_]+", lowered[max(0, start - 40) : start])
    return any(word in NEGATIONS for word in preceding[-2:])


def _pattern_findings(
    text: str, patterns: tuple[str, ...], *, source: str, language: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered = text.lower()
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            if pattern in NEGATABLE_PATTERNS and _negated(lowered, match.start()):
                continue
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            findings.append(
                {
                    "text": text[start:end].replace("\n", " ").strip(),
                    "pattern": pattern,
                    "context": CONTEXT,
                    "reason": (
                        f"{source}: a profit claim ({language}) appears in a {CONTEXT} context, "
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
    english += _pattern_findings(
        text, ENGLISH_ENDORSEMENT_PATTERNS, source=source, language="English"
    )
    return english + _pattern_findings(
        text, SPANISH_CLAIM_PATTERNS, source=source, language="Spanish"
    )


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
    "ENGLISH_ENDORSEMENT_PATTERNS",
    "NEGATABLE_PATTERNS",
    "SPANISH_CLAIM_PATTERNS",
    "AuditReportError",
    "assert_report_clean",
    "find_claims",
    "scan_client_text",
]
