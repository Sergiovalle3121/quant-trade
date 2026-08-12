"""The collector policy hashes must resolve for the provenance guard.

A doc citing a policy hash is naming the rule a dataset was collected under.
That citation is only worth anything while the code still declares that rule,
so the guard recomputes the hash rather than trusting a register entry — and
these tests pin both halves: the digests resolve today, and they stop resolving
the moment a policy changes. Without the second half, adding the digests to the
guard would be indistinguishable from whitelisting them.
"""

from __future__ import annotations

from quant_trade.data.deathlist import DEATHLIST_POLICY, DEATHLIST_POLICY_SHA256
from quant_trade.data.universe import UNIVERSE_POLICY, UNIVERSE_POLICY_SHA256
from quant_trade.data.venue_klines import VENUE_POLICIES, VENUE_POLICY_SHA256
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.evidence.provenance_guard import computed_content_digests


def test_every_collector_policy_digest_resolves() -> None:
    known = computed_content_digests()
    assert UNIVERSE_POLICY_SHA256 in known
    assert DEATHLIST_POLICY_SHA256 in known
    for venue, digest in VENUE_POLICY_SHA256.items():
        assert digest in known, f"{venue} policy digest does not resolve"


def test_each_venue_has_its_own_policy_digest() -> None:
    assert len(set(VENUE_POLICY_SHA256.values())) == len(VENUE_POLICIES)


def test_a_changed_policy_stops_resolving() -> None:
    """The property that makes recomputation different from whitelisting."""
    known = computed_content_digests()
    for policy in (UNIVERSE_POLICY, DEATHLIST_POLICY, *VENUE_POLICIES.values()):
        altered = {**policy, "page_limit": "tampered"}
        assert sha256_of_text(canonical_dumps(altered)) not in known


def test_digests_match_a_fresh_hash_of_the_declared_policy() -> None:
    assert sha256_of_text(canonical_dumps(UNIVERSE_POLICY)) == UNIVERSE_POLICY_SHA256
    assert sha256_of_text(canonical_dumps(DEATHLIST_POLICY)) == DEATHLIST_POLICY_SHA256
    for venue, policy in VENUE_POLICIES.items():
        assert VENUE_POLICY_SHA256[venue] == sha256_of_text(canonical_dumps(policy))
