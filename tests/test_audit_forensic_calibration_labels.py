"""Customer labels must distinguish observed from signal-granted cells."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quant_trade.audit import importers, report
from quant_trade.audit.forensics import review

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"


def _balance_row(name: str, locale: str) -> str:
    data = (FIXTURES / name).read_bytes()
    result = review(data, source_format=importers.detect_format(data))
    html = report._forensics_html(result.as_dict(), locale)
    found = re.search(r"<tr><th scope='row'><code>BALANCE_CHAIN</code>.*?</tr>", html)
    assert found is not None
    return found.group()


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_insufficient_mt5_history_calibration_is_not_labeled_granted(locale: str) -> None:
    row = _balance_row("mt5_history.html", locale)
    copy = report.INTEGRITY_TEXT[locale]
    assert copy["forensic_uncalibrated"] in row
    assert copy["forensic_calibrated"] not in row


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_granted_mt5_tester_balance_cell_keeps_its_label(locale: str) -> None:
    row = _balance_row("mt5_tester.html", locale)
    copy = report.INTEGRITY_TEXT[locale]
    assert copy["forensic_calibrated"] in row
    assert copy["forensic_uncalibrated"] not in row
