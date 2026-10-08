"""Working out when a repeating bill is next due."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# "none" means a one-time bill.
REPEAT_UNITS = ("none", "day", "month", "year")


def add_months(d: date, months: int, anchor_day: int) -> date:
    """Move ``d`` forward by ``months``, landing on ``anchor_day`` or the month's last day.

    Keeping the original day separately means a bill due on the 31st goes
    31 Jan -> 28 Feb -> 31 Mar instead of drifting to the 28th for good.
    """
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def next_due(due: date, unit: str, every: int, anchor_day: int | None = None) -> date | None:
    """The due date after ``due``, or None for a one-time bill."""
    if unit == "none":
        return None
    if every < 1:
        raise ValueError("every must be at least 1")
    anchor_day = anchor_day or due.day
    if unit == "day":
        return due + timedelta(days=every)
    if unit == "month":
        return add_months(due, every, anchor_day)
    if unit == "year":
        return add_months(due, 12 * every, anchor_day)
    raise ValueError(f"Unknown repeat unit '{unit}'")


def describe(unit: str, every: int) -> str:
    if unit == "none":
        return "One-time"
    if every == 1:
        return {"day": "Daily", "month": "Monthly", "year": "Yearly"}[unit]
    if unit == "month" and every == 3:
        return "Quarterly"
    if unit == "month" and every == 6:
        return "Every 6 months"
    return f"Every {every} {unit}s"
