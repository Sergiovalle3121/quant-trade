"""The permitted economic vocabulary, and a guard that enforces it.

Every previous sprint drifted the same way: a status that meant "we could not
measure this" started being read as "we measured this and it lost". V9 fixes
the vocabulary itself. There is one enumeration of legal economic states, they
are ordered by how much evidence each requires, and a claim can never skip a
rung.

The second half of this module exists because prose leaks. A report that calls
a Monte Carlo run "profitable", or a fixture "revenue producing", has made a
claim the evidence does not support even if every JSON field is correct.
:func:`scan_for_unsupported_claims` checks generated text against the evidence
class it was generated from, so the guard runs where the drift happens.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: Legal economic states, weakest evidence first. A campaign, a paper session
#: or a mining route reports exactly one of these.
ECONOMIC_STATES = (
    "NOT_MEASURED",
    "BLOCKED_EVIDENCE",
    "MEASURED_REJECTED",
    "BACKTEST_CANDIDATE",
    "PAPER_RUNNING",
    "PAPER_REJECTED",
    "PAPER_VALIDATED",
    "CANARY_REQUIRES_HUMAN_AUTHORISATION",
    "LIVE_CANARY_RECONCILED",
    "DEPLOYMENT_CANDIDATE",
)

#: How much evidence each state asserts. Used to reject a claim that outranks
#: what was actually observed.
STATE_RANK = {state: index for index, state in enumerate(ECONOMIC_STATES)}

#: The only state that may ever assert realized money, and V9 cannot produce it.
REALIZED_PROFIT_STATE = "REALIZED_LIVE_PROFIT_RECONCILED"

#: States V9 is authorised to emit. Anything beyond paper needs a human.
V9_PERMITTED_STATES = (
    "NOT_MEASURED",
    "BLOCKED_EVIDENCE",
    "MEASURED_REJECTED",
    "BACKTEST_CANDIDATE",
    "PAPER_RUNNING",
    "PAPER_REJECTED",
    "PAPER_VALIDATED",
    "CANARY_REQUIRES_HUMAN_AUTHORISATION",
)

#: Mining-route states. Separate ladder because "shadow" has no trading analogue.
MINING_STATES = (
    "BLOCKED_EVIDENCE",
    "SHADOW_MARKET_ONLY",
    "SHADOW_COLLECTING",
    "SHADOW_CANDIDATE",
)

#: Evidence classes, weakest first. Only the strongest may support a promotion.
EVIDENCE_CLASSES = (
    "SYNTHETIC",
    "ASSUMPTION",
    "RECORDED_TEST",
    "REAL_PUBLIC_RETAIL",
    "REAL_ACCOUNT_SPECIFIC",
)

#: Classes a V9 promotion may rest on.
PROMOTABLE_EVIDENCE_CLASSES = ("REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC")

#: Words that assert money was or will be made. Banned unless the supporting
#: evidence is realized, reconciled, live money — which V9 never has.
PROFIT_CLAIM_PATTERNS = (
    r"\bprofitable\b",
    r"\bprofitability proven\b",
    r"\brevenue[- ]producing\b",
    r"\bgenerates? (?:money|income|revenue|profit)\b",
    r"\bmakes? money\b",
    r"\bguaranteed returns?\b",
    r"\brisk[- ]free\b",
    r"\bwill earn\b",
    r"\bis earning\b",
)

#: Contexts in which a profit claim is never supportable, whatever the wording.
UNSUPPORTABLE_CONTEXTS = (
    "fixture",
    "synthetic",
    "in_sample_backtest",
    "negative_holdout",
    "incomplete_paper",
    "unsettled_pnl",
    "mining_without_payout",
    "monte_carlo",
)


class IllegalEconomicState(ValueError):
    """A status outside the permitted vocabulary, or above what V9 may emit."""


def validate_state(state: str, *, permitted: tuple[str, ...] = V9_PERMITTED_STATES) -> str:
    """Return ``state`` if legal, else raise.

    ``REALIZED_LIVE_PROFIT_RECONCILED`` is rejected explicitly rather than
    falling through the generic message, because it is the one state whose
    accidental appearance would be a claim about real money.
    """
    if state == REALIZED_PROFIT_STATE:
        raise IllegalEconomicState(
            f"{REALIZED_PROFIT_STATE} requires realized money reconciled against "
            "external balances; V9 is not authorised to produce it"
        )
    if state not in ECONOMIC_STATES and state not in MINING_STATES:
        raise IllegalEconomicState(
            f"{state!r} is not a permitted economic state; legal values are "
            f"{ECONOMIC_STATES} (trading) or {MINING_STATES} (mining)"
        )
    if state not in permitted and state not in MINING_STATES:
        raise IllegalEconomicState(
            f"{state!r} is a legal state but outside what this sprint may emit ({permitted})"
        )
    return state


def state_at_most(observed: str, ceiling: str) -> str:
    """Cap a claimed state at what the evidence supports."""
    if observed not in STATE_RANK or ceiling not in STATE_RANK:
        raise IllegalEconomicState(f"cannot compare {observed!r} with {ceiling!r}")
    return observed if STATE_RANK[observed] <= STATE_RANK[ceiling] else ceiling


@dataclass
class ClaimFinding:
    text: str
    pattern: str
    context: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProfitClaimGuardReport:
    scanned_sources: list[str] = field(default_factory=list)
    findings: list[ClaimFinding] = field(default_factory=list)
    contexts_checked: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "PROFIT_CLAIM_GUARD",
            "schema_version": 1,
            "scanned_sources": sorted(self.scanned_sources),
            "contexts_checked": sorted(self.contexts_checked),
            "findings": [f.to_dict() for f in self.findings],
            "clean": self.clean,
            "banned_patterns": list(PROFIT_CLAIM_PATTERNS),
            "unsupportable_contexts": list(UNSUPPORTABLE_CONTEXTS),
            "realized_profit_state_present": False,
            "note": (
                "A profit claim is only supportable by realized money reconciled "
                "against external balances. No V9 artifact carries that evidence, "
                "so every match is a finding regardless of intent."
            ),
        }


def scan_for_unsupported_claims(text: str, *, source: str, context: str) -> list[ClaimFinding]:
    """Flag profit language that the given context cannot support."""
    findings: list[ClaimFinding] = []
    lowered = text.lower()
    for pattern in PROFIT_CLAIM_PATTERNS:
        for match in re.finditer(pattern, lowered):
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            findings.append(
                ClaimFinding(
                    text=text[start:end].replace("\n", " ").strip(),
                    pattern=pattern,
                    context=context,
                    reason=(
                        f"{source}: a profit claim appears in a {context} context, "
                        "which carries no realized, reconciled money"
                    ),
                )
            )
    return findings


def guard_artifacts(payloads: dict[str, Any]) -> ProfitClaimGuardReport:
    """Scan generated artifact payloads for unsupportable profit language."""
    from quant_trade.evidence.canonical_json import canonical_dumps

    report = ProfitClaimGuardReport(contexts_checked=list(UNSUPPORTABLE_CONTEXTS))
    for name, payload in sorted(payloads.items()):
        report.scanned_sources.append(name)
        rendered = canonical_dumps(payload)
        if REALIZED_PROFIT_STATE in rendered:
            report.findings.append(
                ClaimFinding(
                    text=REALIZED_PROFIT_STATE,
                    pattern=REALIZED_PROFIT_STATE,
                    context="artifact",
                    reason=f"{name}: asserts realized live profit, which V9 cannot have",
                )
            )
        report.findings.extend(
            scan_for_unsupported_claims(rendered, source=name, context="artifact")
        )
    return report


__all__ = [
    "ECONOMIC_STATES",
    "EVIDENCE_CLASSES",
    "MINING_STATES",
    "PROFIT_CLAIM_PATTERNS",
    "PROMOTABLE_EVIDENCE_CLASSES",
    "REALIZED_PROFIT_STATE",
    "STATE_RANK",
    "UNSUPPORTABLE_CONTEXTS",
    "V9_PERMITTED_STATES",
    "ClaimFinding",
    "IllegalEconomicState",
    "ProfitClaimGuardReport",
    "guard_artifacts",
    "scan_for_unsupported_claims",
    "state_at_most",
    "validate_state",
]
