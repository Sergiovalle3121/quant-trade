"""Coherencia del archivo: a deterministic battery of file-consistency checks.

The battery reads the uploaded report a second time, read-only, and asks
whether the rows still carry the traces a trading platform leaves when it
writes them: running balances that add up, tickets in the server's order,
prices printed with one precision per symbol, no trade on a closed market.
It never re-imports, never touches a class, never names who edited what.
Its answers are codes and numbers without language; the sentences live in
the web layer.

Every check answers one status: ``CLEAN`` (the traces reviewed were not
found), ``SIGNAL`` (a trace was found and the check is calibrated on at
least twenty real public files of that family with no unexplained signal),
``INFO`` (a trace or figure with no calibrated claim behind it) or
``NOT_MEASURED`` (the check could not run, with a reason code).
"""

from __future__ import annotations

from quant_trade.audit.forensics.calibration import CALIBRATION, SIGNAL_CAPABLE
from quant_trade.audit.forensics.families import FAMILIES, FAMILY_OF, family_of
from quant_trade.audit.forensics.results import (
    DECLARED,
    EVIDENCE,
    MEASURED,
    NOT_MEASURED,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    STATUSES,
    CheckResult,
    ForensicResult,
)
from quant_trade.audit.forensics.review import CHECK_ORDER, METHOD_VERSION, decide, review

__all__ = [
    "CALIBRATION",
    "CHECK_ORDER",
    "DECLARED",
    "EVIDENCE",
    "FAMILIES",
    "FAMILY_OF",
    "MEASURED",
    "METHOD_VERSION",
    "NOT_MEASURED",
    "SIGNAL_CAPABLE",
    "STATUSES",
    "STATUS_CLEAN",
    "STATUS_INFO",
    "STATUS_NOT_MEASURED",
    "STATUS_SIGNAL",
    "CheckResult",
    "ForensicResult",
    "decide",
    "family_of",
    "review",
]
