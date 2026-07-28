"""V8: real-alpha evidence acquisition, campaign execution and paper launch.

Everything in this package is read-only research tooling. No module here
submits an order, moves funds, provisions cloud capacity, or starts a miner —
several tests assert the absence of those verbs.

The V8 thesis is narrow and testable: a strategy may only be promoted from
evidence that can be *rebuilt byte-for-byte by a third party*. So the package
is organised around a single pipeline:

``backfill`` (official public endpoints, resumable) → ``evidence_pack``
(content-addressed, verifiable) → ``campaigns`` (pre-registered, gated) →
``paper_launch`` (only with a passing candidate) → ``canary`` (always blocked
until a human supplies budget, venue and limits).
"""

from __future__ import annotations

#: Bumped whenever a parser or the evidence layout changes in a way that
#: alters normalized bytes. Recorded in every receipt and manifest.
V8_SCHEMA_VERSION = 1

__all__ = ["V8_SCHEMA_VERSION"]
