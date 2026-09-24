"""The launch playbook sells the audit, so it obeys the audit's own rules.

``docs/AUDIT_LAUNCH_PLAYBOOK.md`` holds messages the owner copies into
WhatsApp, forums and direct messages. A template that promises money or a
passed challenge would break AGENTS.md Phase 16 the moment it is sent, so
every template, and the playbook as a whole, must pass the profit-claim guard
in English and Spanish. The tests are offline: they only read the file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quant_trade.audit.guard import assert_report_clean, find_claims

PLAYBOOK = Path(__file__).resolve().parents[1] / "docs" / "AUDIT_LAUNCH_PLAYBOOK.md"

#: A template heading is ``#### <id> · ES|EN · <title>``; the fenced block
#: right after it is the text the owner sends.
TEMPLATE_RE = re.compile(
    r"^#### (?P<id>[A-Z]\d+) · (?P<lang>ES|EN) · [^\n]+\n+```text\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)

#: Stricter than the report guard: a sales message must not talk about
#: earning, winning or passing at all, even in phrasings the guard allows.
TEMPLATE_ONLY_PATTERNS: tuple[str, ...] = (
    r"\bganar",
    r"\bganancia",
    r"\bgenera\w*\s+(?:dinero|ingresos)",
    r"\bsupera\w*\s+(?:el|tu|un|los|tus)\s+retos?",
    r"\bpasa\w*\s+(?:el|tu|un|los|tus)\s+retos?",
    r"\bearn",
    r"\bprofits?\b(?!\s+factor)",
    r"\bmake\s+money\b",
    r"\bpass\s+(?:the|your|a)\s+challenge",
    r"\bfunded\s+for\s+sure\b",
)


def _playbook() -> str:
    return PLAYBOOK.read_text(encoding="utf-8")


def _templates() -> list[re.Match[str]]:
    return list(TEMPLATE_RE.finditer(_playbook()))


def test_playbook_exists_and_whole_text_passes_the_guard() -> None:
    text = _playbook()
    assert find_claims(text) == []
    assert_report_clean(text)


def test_playbook_has_templates_in_both_languages() -> None:
    templates = _templates()
    assert len(templates) >= 8
    by_id: dict[str, set[str]] = {}
    for match in templates:
        by_id.setdefault(match["id"], set()).add(match["lang"])
    missing = {key: langs for key, langs in by_id.items() if langs != {"ES", "EN"}}
    assert missing == {}


@pytest.mark.parametrize("match", _templates(), ids=lambda m: f"{m['id']}-{m['lang']}")
def test_every_template_passes_the_guard(match: re.Match[str]) -> None:
    body = match["body"]
    assert body.strip()
    assert find_claims(body) == []
    lowered = body.lower()
    hits = [pattern for pattern in TEMPLATE_ONLY_PATTERNS if re.search(pattern, lowered)]
    assert hits == []


def test_template_only_patterns_catch_the_obvious_pitches() -> None:
    pitches = [
        "Con este robot vas a ganar cada mes",
        "Te ayudo a superar el reto de FTMO",
        "Our audit helps you pass the challenge",
        "Stop losing and start to earn",
    ]
    for pitch in pitches:
        assert any(re.search(pattern, pitch.lower()) for pattern in TEMPLATE_ONLY_PATTERNS)


def test_vendor_templates_carry_the_badge_notice() -> None:
    vendor = [match for match in _templates() if match["id"].startswith("V")]
    assert vendor
    for match in vendor:
        body = match["body"].lower()
        if match["lang"] == "ES":
            assert "no garantiza resultados" in body
        else:
            assert "not a performance guarantee" in body


def test_every_community_row_has_a_url_and_a_check_date() -> None:
    rows = [
        line
        for line in _playbook().splitlines()
        if line.startswith("| ") and "https://" in line and "2026-" in line
    ]
    assert len(rows) >= 8
    for row in rows:
        assert re.search(r"\b2026-\d{2}-\d{2}\b", row)
