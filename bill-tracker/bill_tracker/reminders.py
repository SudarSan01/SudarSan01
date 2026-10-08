"""Deciding which reminders are due and sending them.

Run once a day (cron). For each active bill:

* Before the due date, a reminder goes out when the bill reaches one of its
  ``remind_days`` (e.g. 7, 3, 1 and 0 days before). If a run was missed, the
  next run still sends the most recent stage reached, once.
* After the due date, an overdue reminder goes out every day until the bill
  is marked paid.

Every family member with reminders turned on gets all reminders, combined
into one message per run. A reminder is recorded as sent only after the
message is delivered, so a failed send is retried on the next run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from . import store
from .formatting import format_date, format_due, format_inr
from .notifiers import Notifier
from .store import Bill, Member


def reminder_stage(bill: Bill, today: date) -> str | None:
    """The reminder stage ``bill`` is at today, or None if no reminder is due."""
    days_left = bill.days_left(today)
    if days_left < 0:
        return f"overdue:{today.isoformat()}"
    reached = [d for d in bill.remind_days if days_left <= d]
    if not reached:
        return None
    return f"before:{min(reached)}"


@dataclass
class DueReminder:
    bill: Bill
    stage: str


@dataclass
class RunResult:
    sent: list[tuple[Member, list[DueReminder]]] = field(default_factory=list)
    failed: list[tuple[Member, str]] = field(default_factory=list)
    skipped: list[tuple[Member, str]] = field(default_factory=list)


def _already_sent(conn: sqlite3.Connection, bill: Bill, stage: str, member: Member) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reminders_sent WHERE bill_id = ? AND due_date = ? AND stage = ? AND member_id = ?",
        (bill.id, bill.due_date.isoformat(), stage, member.id),
    ).fetchone()
    return row is not None


def pending_reminders(conn: sqlite3.Connection, today: date) -> dict[int, tuple[Member, list[DueReminder]]]:
    """Reminders not yet delivered, grouped by family member id."""
    members = [m for m in store.list_members(conn) if m.notify]
    due = [(b, reminder_stage(b, today)) for b in store.list_bills(conn)]
    due = [(b, s) for b, s in due if s]
    pending: dict[int, tuple[Member, list[DueReminder]]] = {}
    for member in members:
        items = [DueReminder(b, s) for b, s in due if not _already_sent(conn, b, s, member)]
        if items:
            pending[member.id] = (member, items)
    return pending


def format_message(items: list[DueReminder], today: date, app_url: str | None = None) -> str:
    lines = [f"🔔 Bill reminders · {format_date(today, today)}", ""]
    for item in sorted(items, key=lambda i: i.bill.due_date):
        bill = item.bill
        days_left = bill.days_left(today)
        marker = "⚠️" if days_left < 0 else "🔴" if days_left == 0 else "🟠" if days_left <= 3 else "🟡"
        parts = [f"{marker} {bill.icon} {bill.title}"]
        if bill.amount is not None:
            parts.append(format_inr(bill.amount))
        when = format_due(bill.due_date, today)
        if days_left < 0 or days_left > 1:
            when += f" ({format_date(bill.due_date, today)})"
        parts.append(when.replace("overdue", "OVERDUE"))
        line = " · ".join(parts)
        extras = [x for x in (bill.reference and f"Ref {bill.reference}", bill.owner_name) if x]
        if extras:
            line += f"\n    {' · '.join(extras)}"
        lines.append(line)
    if app_url:
        lines += ["", f"Mark paid: {app_url}"]
    return "\n".join(lines)


def send_reminders(
    conn: sqlite3.Connection,
    notifier: Notifier,
    today: date | None = None,
    app_url: str | None = None,
    dry_run: bool = False,
) -> RunResult:
    today = today or date.today()
    result = RunResult()
    for member, items in pending_reminders(conn, today).values():
        if not member.phone:
            result.skipped.append((member, "no phone number"))
            continue
        text = format_message(items, today, app_url)
        if dry_run:
            print(f"--- would send to {member.name} ({member.phone}) ---\n{text}\n")
            result.sent.append((member, items))
            continue
        try:
            notifier.send(member, text)
        except Exception as exc:  # noqa: BLE001 - report and retry next run
            result.failed.append((member, str(exc)))
            continue
        sent_at = datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            "INSERT OR IGNORE INTO reminders_sent (bill_id, due_date, stage, member_id, sent_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(i.bill.id, i.bill.due_date.isoformat(), i.stage, member.id, sent_at) for i in items],
        )
        conn.commit()
        result.sent.append((member, items))
    return result
