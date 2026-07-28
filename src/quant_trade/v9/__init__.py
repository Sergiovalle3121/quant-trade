"""V9: profitability evidence, autonomous paper, rented-hashrate shadow.

V8 shipped a pipeline that could not lie about *provenance*. V9 closes the
gaps where it could still lie about *economics*: a canary that passed with a
failed reconciliation, a paper session whose P&L was whatever the caller
said it was, and a candidate that could exist while the status file reported
none.

Everything here is read-only research and simulation. No module submits an
order, buys hashrate, moves funds, signs a wallet transaction, or creates a
cloud resource, and tests assert those verbs are structurally absent.
"""

from __future__ import annotations

#: Bumped when an artifact schema or a normalized-bytes path changes.
V9_SCHEMA_VERSION = 1

__all__ = ["V9_SCHEMA_VERSION"]
