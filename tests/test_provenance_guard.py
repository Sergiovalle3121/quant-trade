"""The provenance guard, proved against the fourteen stubs it exists to catch.

Each case below reconstructs one class-B stub exactly as it appeared before the
integrity sweep. A guard that misses any of them is not worth running, so the
acceptance test asserts all fourteen, by name, in one place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.evidence.provenance_guard import (
    guard_repository,
    repository_digests,
    scan_payload,
    scan_prose,
)

# A digest that no file hashes to. Used where the stubs carried fabricated ones.
FABRICATED = "7fc049917826aca4574dee2019efabe9a40685817155941854b6c926bfc3c176"

#: The fourteen, reconstructed. Name -> the payload fragment as it shipped.
STUBS: dict[str, dict] = {
    "B-1 test baseline": {
        "artifact": "DEFECT_REPRODUCTION_MATRIX",
        "baseline": {"platform": "Windows", "python": "3.12.13", "passed": 617, "failed": 25},
    },
    "B-2 defect closures": {
        "artifact": "DEFECT_REPRODUCTION_MATRIX",
        "defects": [{"id": "V7-001", "priority": "P0-A", "status": "FIXED_GREEN"}],
    },
    "B-3 evidence census": {
        "artifact": "DATA_PROVENANCE_REPORT",
        "evidence_counts": {"REAL": 5, "RECORDED_RESPONSE": 1, "FIXTURE": 0},
    },
    "B-4 raw captures": {
        "artifact": "DATA_PROVENANCE_REPORT",
        "real_raw_data_captured": 5,
    },
    "B-5 settlements verified": {
        "artifact": "DATA_PROVENANCE_REPORT",
        "real_settlements_verified": 6,
    },
    "B-6 fabricated capture": {
        "artifact": "DATA_PROVENANCE_REPORT",
        "real_local_uncommitted_capture": {
            "raw_pages": 5,
            "panel_rows": 41,
            "settlements": 6,
            "clean_rebuild": True,
            "receipt_provenance": "real",
            "panel_sha256": FABRICATED,
            "committed_to_repository": False,
            "promotion_eligible": False,
        },
        "backfill_attempts": [
            {
                "path": "data/carry/panel/bybit_btc/backfill_attempts.jsonl",
                "last_record": json.dumps(
                    {"settlements": 0, "panel_rows": 0, "status": "NOT_RUN_NETWORK_BLOCKED"}
                ),
            }
        ],
    },
    "B-7 unit audit": {
        "artifact": "MINING_UNIT_AUDIT",
        "universal_th_divisor_present": False,
    },
    "B-8 promotable": {
        "artifact": "PROMOTION_REPRODUCIBILITY",
        "real_evidence_promotable": False,
    },
    "B-9 candidate count": {
        "artifact": "PROMOTION_REPRODUCIBILITY",
        "paper_candidate_count": 0,
    },
    "B-10 cash measured": {
        "artifact": "UNIFIED_OPPORTUNITY_BOARD",
        "rows": [
            {
                "opportunity_id": "cash",
                "kind": "CASH",
                "measured": True,
                "expected_return_over_horizon": 0.04,
                "allocation_weight": 1.0,
            }
        ],
    },
    "B-11 hypothesis register": {
        "artifact": "REAL_TRADING_CAMPAIGNS",
        "additional_hypotheses": {"registered": ["H6", "H7"], "executed": []},
    },
    "B-12 invented venue budget": {
        "artifact": "MINING_EVIDENCE_INDEX",
        "status": "BLOCKED_EVIDENCE",
        "market_quotes": 0,
        "canary_manifest": {
            "terms": {
                "max_budget_btc": 0.00109,
                "budget_derivation": {
                    "max_budget_btc": 0.00109,
                    "spend_floor_btc": 0.001,
                    "fee_floor_btc": 9e-05,
                },
            }
        },
    },
    "B-13 invented ceilings": {
        "artifact": "MINING_EVIDENCE_INDEX",
        "status": "BLOCKED_EVIDENCE",
        "canary_manifest": {"terms": {"price_ceiling_btc": 0.001, "max_budget_usd": 65.4}},
    },
    "B-14 erratum closed": {
        "artifact": "H3_LEDGER_RECONCILIATION",
        "state": "NOT_MEASURED",
        "v8_defect_closed": "E6",
    },
}


@pytest.fixture(scope="module")
def known_digests() -> frozenset[str]:
    return repository_digests(Path("."))


@pytest.mark.parametrize("name", sorted(STUBS))
def test_each_of_the_fourteen_stubs_is_caught(name: str, known_digests) -> None:
    findings = scan_payload(STUBS[name], source=name, known_digests=known_digests)
    assert findings, f"{name} slipped through the guard"


def test_all_fourteen_are_caught_together(known_digests) -> None:
    """The acceptance criterion, asserted as one number so it cannot drift."""
    caught = {
        name
        for name, payload in STUBS.items()
        if scan_payload(payload, source=name, known_digests=known_digests)
    }
    missed = sorted(set(STUBS) - caught)
    assert len(STUBS) == 14
    assert not missed, f"guard missed {len(missed)} of 14: {missed}"
    assert len(caught) == 14


def test_the_fabricated_digest_is_caught_in_prose_too(known_digests) -> None:
    """The blind spot: a JSON-only guard left this claim standing in docs/."""
    text = f"Its panel SHA-256 is `{FABRICATED}`."
    findings = scan_prose(text, source="docs/example.md", known_digests=known_digests)
    assert [f.rule for f in findings] == ["R2-digest"]


def test_a_real_digest_in_prose_is_accepted(tmp_path: Path, known_digests) -> None:
    """A digest that resolves to committed bytes must not be flagged."""
    target = Path("AGENTS.md")
    import hashlib

    real = hashlib.sha256(target.read_bytes()).hexdigest()
    assert not scan_prose(f"AGENTS.md is {real}", source="d.md", known_digests=known_digests)


def test_an_honestly_declared_placeholder_is_not_a_finding(known_digests) -> None:
    """NOT_MEASURED beside a zero asserts nothing and must stay quiet."""
    payload = {
        "artifact": "PAPER_DAEMON_STATUS",
        "state": "NOT_MEASURED",
        "events_processed": 0,
        "sessions": 0,
    }
    assert not scan_payload(payload, source="honest", known_digests=known_digests)


#: Provenance findings outstanding across the committed artifacts, measured on
#: 2026-08-03. The repository declares an evidence class in a handful of places
#: and nowhere else, so R1 fires broadly. This is a ratchet, not a pass: the
#: number may fall, never rise. Lowering it requires declaring evidence classes
#: on the artifacts, which is a decision about the artifacts, not about the guard.
PROVENANCE_DEBT_CEILING = 871


def test_the_repository_provenance_debt_does_not_grow() -> None:
    """A ratchet on the outstanding debt, so new undeclared claims cannot land.

    The guard is not clean against the repository yet and this test does not
    pretend otherwise. What it prevents is regression: any newly added claim
    without a declared class pushes the count over the ceiling and fails.
    """
    report = guard_repository(Path("."))
    assert report.scanned, "the guard scanned nothing, which means it is misconfigured"
    assert len(report.findings) <= PROVENANCE_DEBT_CEILING, (
        f"provenance debt rose to {len(report.findings)} (ceiling {PROVENANCE_DEBT_CEILING}).\n"
        + "\n".join(f"{f.rule} {f.source}:{f.path} - {f.detail}" for f in report.findings[:15])
    )


def test_the_guard_still_fires_on_the_repository() -> None:
    """Guards that pass trivially rot. This asserts the scan is doing work."""
    report = guard_repository(Path("."))
    assert len(report.scanned) > 40
    assert report.findings, "a guard reporting nothing at all is a broken guard"
