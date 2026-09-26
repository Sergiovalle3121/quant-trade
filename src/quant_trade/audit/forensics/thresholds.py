"""Every constant a check compares against, in one place, frozen together.

A test pins the SHA-256 of this module: changing a constant is changing the
method, and the method's version must move with it.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

#: The date these constants were frozen; the calibration tables refer to it.
FREEZE_DATE = "2026-09-26"

#: Two printed money cells compare equal within this (per comparison).
MONEY_TOLERANCE = Decimal("0.011")
#: Ratios printed with two decimals compare equal within this.
RATIO_TOLERANCE = Decimal("0.005")

#: A close earlier than its open by up to this is a clock adjustment, not a hit.
CLOSE_BEFORE_OPEN_ALLOWED = timedelta(minutes=60)
#: A row later than the report's own date by more than this is a hit
#: (server clocks run up to 14 h ahead of the terminal's clock).
AFTER_REPORT_DATE_ALLOWED = timedelta(hours=14, seconds=60)
#: Adjacent tickets whose times run backwards by more than this are inversions.
TICKET_TIME_BACKWARDS_ALLOWED = timedelta(seconds=60)
#: An order's fill time may differ from its deal's time by this much.
ORDER_FILL_DRIFT = timedelta(seconds=1)

#: Weekend closure counted as a hit, server clock, with a one-hour edge
#: inside the core window [Saturday 12:00, Sunday 09:00) that is closed
#: under every server offset in [-12 h, +14 h] and both DST regimes.
WEEKEND_CORE = ((5, 12), (6, 9))
WEEKEND_COUNTED = ((5, 13), (6, 8))
WEEKEND_WINDOW_CODE = "sat13_sun08"
#: Offsets tried, in minutes, when inferring the server clock (INFO only).
OFFSET_STEP_MINUTES = 30
OFFSET_RANGE_MINUTES = (-12 * 60, 14 * 60)

#: Price-implied P&L: contract multipliers tried and the share of rows the
#: best one must explain before any row counts.
CONTRACT_MULTIPLIERS = (1, 10, 100, 1000, 10000, 100000)
IMPLIED_PNL_MIN_FIT = Decimal(2) / Decimal(3)

#: TradingView cumulative P&L: rounded rows accumulate at most this drift.
TV_CUMULATIVE_SLACK_PER_ROW = Decimal("0.006")
TV_CUMULATIVE_SLACK_BASE = Decimal("0.01")

#: Monthly tables need this many values before digit statistics mean anything.
MONTHLY_MIN_VALUES = 60
#: A value repeated at least this often is counted.
MONTHLY_REPEAT_MIN = 3

#: Genuine files a cell needs before its check may answer SIGNAL.
CALIBRATION_MIN_FILES = 20
#: ...from at least this many distinct accounts or strategies: forty daily
#: exports of one account are one account.
CALIBRATION_MIN_GROUPS = 10
