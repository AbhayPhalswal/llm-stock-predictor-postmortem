"""
NSE MARKET CALENDAR  ·  TRADING-DAY GATE

Shared by 1_fire_morning.py and 2_fire_afternoon.py.

Why this module exists
──────────────────────
The V5 time gates only checked the clock (09:15 / 15:30 IST), never the date.
Running ignition on a Saturday therefore passed the gate, and yfinance happily
returned Friday's daily candle. The result was a phantom ledger row keyed to a
non-trading date, anchored to a stale price, that could never settle — exactly
what happened to 2026-06-06 in trading_firm_memory.db.

The weekend rule below is exact. The holiday list is NOT self-maintaining: NSE
publishes its trading holidays by circular each year, so HOLIDAYS must be
updated annually against the official list. An out-of-date holiday list fails
open (the run proceeds), so a missed entry costs you one junk row, not a crash.
"""

from datetime import date

# ── NSE equity-segment trading holidays ───────────────────────────────────────
# Source of truth: NSE holiday circular for the relevant year.
# VERIFY AND UPDATE ANNUALLY — entries here are a convenience, not an authority.
HOLIDAYS: set[date] = set()

# Populate as: HOLIDAYS.add(date(2026, 1, 26))  # Republic Day
# Left deliberately empty rather than seeded with unverified dates; the weekend
# rule catches the large majority of non-trading days on its own.


def is_trading_day(day: date) -> tuple[bool, str]:
    """
    Returns (is_open, reason).

    reason is a human-readable explanation suitable for direct logging when the
    market is shut, and an empty string when it is open.
    """
    if day.weekday() >= 5:
        return False, f"{day.strftime('%A')} — NSE equity segment is closed at weekends."

    if day in HOLIDAYS:
        return False, f"{day.isoformat()} is a listed NSE trading holiday."

    return True, ""
