"""The trial count decides whether multiplicity can pass (verdict.assess_multiplicity), so
the upload form asks for it up front, and the landing mock is a class the rules can give."""

from __future__ import annotations

import html

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import _COPY, landing

LOCALES = ("es", "en", "pt")


@pytest.mark.parametrize("locale", LOCALES)
def test_the_form_asks_for_trials_outside_the_advanced_options(locale: str) -> None:
    page = html.unescape(landing(locale=locale, free_mode=False))
    field = page.index("name='trials'")
    assert field < page.index("<details class='adv'>")
    words = _COPY[locale]
    assert words["trials"] in page and words["trials_help"] in page
    assert find_claims(f"{words['trials']} {words['trials_help']}") == []


def test_the_landing_mock_is_a_class_the_rules_can_give() -> None:
    from quant_trade.audit.pages import _MOCK_STATUSES
    from quant_trade.audit.schema import Dimension
    from quant_trade.audit.verdict import Thresholds, overall_class

    dimensions = [
        Dimension(name=name, status=status, reasons=[], inputs={})  # type: ignore[arg-type]
        for name, status in _MOCK_STATUSES
    ]
    assert overall_class(dimensions) == "B"
    # The mock's deflated Sharpe tile must be one that lets multiplicity pass.
    for locale in LOCALES:
        from quant_trade.audit.pages import _UI

        value = float(_UI[locale]["mock_kpis"][0][0].replace(",", "."))
        assert value >= Thresholds().dsr_pass
