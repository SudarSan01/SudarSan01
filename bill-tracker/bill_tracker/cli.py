"""Command-line interface: run the web app, send reminders, manage bills."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import closing
from datetime import date

from . import store
from .db import connect, default_db_path
from .formatting import format_due, format_inr
from .notifiers import NOTIFIERS, get_notifier
from .reminders import send_reminders
from .store import ValidationError


def cmd_serve(args) -> int:
    from .web import create_app

    app = create_app(args.db)
    if not app.config["PASSWORD"]:
        print("Note: no BILL_TRACKER_PASSWORD set, so anyone on your network can open the app.")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_remind(args) -> int:
    today = date.fromisoformat(args.today) if args.today else date.today()
    with closing(connect(args.db)) as conn:
        result = send_reminders(
            conn,
            get_notifier(args.channel),
            today=today,
            app_url=os.environ.get("BILL_TRACKER_URL"),
            dry_run=args.dry_run,
        )
    for member, items in result.sent:
        verb = "Would send" if args.dry_run else "Sent"
        print(f"{verb} {len(items)} reminder(s) to {member.name}")
    for member, reason in result.skipped:
        print(f"Skipped {member.name}: {reason}")
    for member, error in result.failed:
        print(f"FAILED for {member.name}: {error} (will retry next run)", file=sys.stderr)
    if not (result.sent or result.skipped or result.failed):
        print("No reminders due.")
    return 1 if result.failed else 0


def cmd_list(args) -> int:
    today = date.today()
    with closing(connect(args.db)) as conn:
        bills = store.list_bills(conn)
    if not bills:
        print("No bills yet. Add one with: python -m bill_tracker add-bill")
        return 0
    for b in bills:
        amount = format_inr(b.amount)
        owner = f"  [{b.owner_name}]" if b.owner_name else ""
        print(f"{b.id:>4}  {b.due_date}  {format_due(b.due_date, today):<18} {b.icon} {b.title}  {amount}{owner}")
    return 0


def cmd_add_member(args) -> int:
    with closing(connect(args.db)) as conn:
        member_id = store.add_member(conn, {"name": args.name, "phone": args.phone, "callmebot_key": args.key})
    print(f"Added {args.name} (id {member_id})")
    return 0


def cmd_add_bill(args) -> int:
    with closing(connect(args.db)) as conn:
        owner_id = None
        if args.owner:
            owner = store.find_member(conn, args.owner)
            if owner is None:
                print(f"No family member named '{args.owner}'", file=sys.stderr)
                return 1
            owner_id = owner.id
        bill_id = store.add_bill(
            conn,
            {
                "title": args.title,
                "category": args.category,
                "amount": args.amount,
                "due_date": args.due,
                "repeat_unit": args.unit,
                "repeat_every": args.every,
                "remind_days": args.remind,
                "owner_id": owner_id,
                "reference": args.reference,
            },
        )
    print(f"Added {args.title} (id {bill_id})")
    return 0


def cmd_pay(args) -> int:
    with closing(connect(args.db)) as conn:
        bill = store.get_bill(conn, args.bill_id)
        if bill is None or not bill.active:
            print(f"No active bill with id {args.bill_id}", file=sys.stderr)
            return 1
        paid_by = None
        if args.by:
            member = store.find_member(conn, args.by)
            if member is None:
                print(f"No family member named '{args.by}'", file=sys.stderr)
                return 1
            paid_by = member.id
        next_due = date.fromisoformat(args.next_due) if args.next_due else bill.next_due()
        store.record_payment(
            conn,
            bill,
            paid_on=date.fromisoformat(args.on) if args.on else date.today(),
            amount=store.parse_amount(args.amount) if args.amount else bill.amount,
            paid_by=paid_by,
            next_due_date=next_due,
        )
    print(f"Marked {bill.title} paid. " + (f"Next due {next_due}." if next_due else "Archived."))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bill_tracker", description="Family bill and renewal tracker")
    parser.add_argument("--db", default=default_db_path(), help="SQLite file (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="Run the web app")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 lets phones on your Wi-Fi connect")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("remind", help="Send due reminders (run daily from cron)")
    p.add_argument("--channel", choices=sorted(NOTIFIERS), default="whatsapp")
    p.add_argument("--dry-run", action="store_true", help="Print messages instead of sending")
    p.add_argument("--today", help="Pretend today is YYYY-MM-DD (for testing)")
    p.set_defaults(func=cmd_remind)

    p = sub.add_parser("list", help="List active bills by due date")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add-member", help="Add a family member")
    p.add_argument("name")
    p.add_argument("--phone", default="", help="WhatsApp number, e.g. +919876543210")
    p.add_argument("--key", default="", help="CallMeBot API key for this number")
    p.set_defaults(func=cmd_add_member)

    p = sub.add_parser("add-bill", help="Add a bill or renewal")
    p.add_argument("title")
    p.add_argument("--due", required=True, help="Due date, YYYY-MM-DD")
    p.add_argument("--category", default="other")
    p.add_argument("--amount")
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--unit", choices=["day", "month", "year", "none"], default="month")
    p.add_argument("--remind", default="", help="Days before, e.g. '7,3,1,0' (default depends on category)")
    p.add_argument("--owner", help="Family member's name")
    p.add_argument("--reference", default="", help="Account / policy / vehicle number")
    p.set_defaults(func=cmd_add_bill)

    p = sub.add_parser("pay", help="Mark a bill paid and move it to its next due date")
    p.add_argument("bill_id", type=int)
    p.add_argument("--amount")
    p.add_argument("--on", help="Date paid, YYYY-MM-DD (default today)")
    p.add_argument("--by", help="Family member's name")
    p.add_argument("--next-due", help="Override the next due date, YYYY-MM-DD")
    p.set_defaults(func=cmd_pay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
