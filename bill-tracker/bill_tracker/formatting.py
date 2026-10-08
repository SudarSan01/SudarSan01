"""Display helpers shared by the web pages and the WhatsApp messages."""

from __future__ import annotations

from datetime import date


def format_inr(amount: float | None) -> str:
    """Format rupees with Indian digit grouping: 123456.5 -> ₹1,23,456.50."""
    if amount is None:
        return ""
    paise_total = round(abs(amount) * 100)
    whole, paise = divmod(paise_total, 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{digits}" + (f".{paise:02d}" if paise else "")


def format_date(d: date, today: date | None = None) -> str:
    """'Thu 08 Oct', with the year added when it isn't the current one."""
    today = today or date.today()
    if d.year == today.year:
        return d.strftime("%a %d %b")
    return d.strftime("%a %d %b %Y")


def format_due(due: date, today: date) -> str:
    """'due today', 'due tomorrow', 'due in 5 days', 'overdue by 2 days'."""
    days = (due - today).days
    if days == 0:
        return "due today"
    if days == 1:
        return "due tomorrow"
    if days >= 730:
        return f"due in {days // 365} years"
    if days >= 60:
        return f"due in {round(days / 30.44)} months"
    if days > 1:
        return f"due in {days} days"
    if days == -1:
        return "overdue by 1 day"
    return f"overdue by {-days} days"
