"""What the file declares about itself: currency, report date, margin mode.

The account number and the name are never fields here: ``has_account`` is
the only trace that a header was seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from quant_trade.audit import importers
from quant_trade.audit.forensics import families
from quant_trade.audit.forensics.rows import RawTable

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
    for name in (name, name[:3])
}
_MT4_DATE = re.compile(r"^(\d{4})\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{1,2}):(\d{2})$")


@dataclass(frozen=True)
class Header:
    currency: str = ""
    report_date: datetime | None = None
    report_date_source: str = ""
    """``header`` (a printed date), ``period_end`` (a tester's period), ``""``."""
    margin_mode: str = ""
    """``hedge``, ``netting`` or ``""`` when the file does not say."""
    account_type: str = ""
    """``demo``, ``real``, ``contest`` or ``""``."""
    has_account: bool = False


def read_header(table: RawTable, currency_hint: str | None = None) -> Header:
    family = table.family
    currency = (currency_hint or table.label("Currency") or "").strip().upper()
    report_date: datetime | None = None
    source = ""
    margin_mode = ""
    account_type = ""
    if family == families.MT4_STATEMENT:
        first = table.rows[0].texts if table.rows else ()
        for text in first:
            found = _mt4_date(text)
            if found is not None:
                report_date, source = found, "header"
    elif family == families.MT5_HISTORY:
        stamp = table.label("Date")
        if stamp:
            parsed = importers._one_time(stamp.strip())
            if parsed is not None:
                report_date, source = parsed.replace(tzinfo=None), "header"
        account = table.label("Account") or ""
        parts = [part.strip().lower() for part in account.split("(", 1)[-1].rstrip(")").split(",")]
        if not currency and parts and re.fullmatch(r"[a-z]{3}", parts[0] or ""):
            currency = parts[0].upper()
        for part in parts:
            if part in {"hedge", "netting", "exchange"}:
                margin_mode = part
            elif part in {"demo", "real", "contest"}:
                account_type = part
    elif family in families.TESTER_FAMILIES:
        period = table.label("Period") or ""
        dates = importers._period_dates(period)
        if dates is not None:
            parsed = importers._one_time(dates[1].replace("-", "."))
            if parsed is not None:
                report_date, source = parsed.replace(tzinfo=None), "period_end"
    return Header(
        currency=currency,
        report_date=report_date,
        report_date_source=source,
        margin_mode=margin_mode,
        account_type=account_type,
        has_account=table.account_label_present,
    )


def _mt4_date(text: str) -> datetime | None:
    match = _MT4_DATE.match(text.strip())
    if match is None:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    try:
        return datetime(
            int(match.group(1)),
            month,
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
        )
    except ValueError:
        return None
