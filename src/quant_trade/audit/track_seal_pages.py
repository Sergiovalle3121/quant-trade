"""The continuous track record's pages, behind ``TRACK_SEAL_ENABLED``.

Account pages (open, upload, publish, unpublish, end, delete, badge code),
the public page with its badge and ``chain.json``, the synthetic examples
and the owner's ``/panel/historiales``. ``register`` receives the app's own
closures from ``web.create_app``; while the switch is off nothing is
registered and every path answers 404.

On screen this feature is never called a seal: "sello" is the ``/v`` badge.
"""

from __future__ import annotations

from typing import Any

#: A constant, not a Railway variable. The private use (account pages) and
#: the public page each wait for their own go-ahead.
TRACK_SEAL_ENABLED = False
#: The public page, badge and chain: after the legal review.
TRACK_SEAL_PUBLIC_ENABLED = False
#: The public page in Portuguese: after a review in Brazil.
TRACK_SEAL_PUBLIC_PT_ENABLED = False


def register(
    app: Any,
    *,
    load: Any,
    session: Any,
    cross_site: Any,
    signed_in_action: Any,
    panel_failures: Any,
    settings: Any,
    store: Any,
    slots: Any,
) -> bool:
    """Mount the pages on ``app``; returns whether anything was mounted."""
    if not TRACK_SEAL_ENABLED:
        return False
    return False  # pragma: no cover - the routes arrive with the core


__all__ = [
    "TRACK_SEAL_ENABLED",
    "TRACK_SEAL_PUBLIC_ENABLED",
    "TRACK_SEAL_PUBLIC_PT_ENABLED",
    "register",
]
