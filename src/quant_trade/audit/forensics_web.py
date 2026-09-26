"""The private "Coherencia del archivo" page, behind ``FORENSICS_ENABLED``.

``register`` is called once from ``web.create_app`` with the app's own
closures (report loading, sessions, cross-site check, signed-in actions
and the panel's attempt log), so no security logic is copied here. While
the switch is off nothing is registered and every path answers 404.
"""

from __future__ import annotations

from typing import Any

#: A constant, not a Railway variable: the page ships hidden and is turned
#: on by a change in the repository, after its reviews.
FORENSICS_ENABLED = False


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
    """Mount the page on ``app``; returns whether anything was mounted."""
    if not FORENSICS_ENABLED:
        return False
    return False  # pragma: no cover - the routes arrive with the battery


__all__ = ["FORENSICS_ENABLED", "register"]
