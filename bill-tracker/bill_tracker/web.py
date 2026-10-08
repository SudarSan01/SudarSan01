"""Phone-friendly web app for the household's shared bill list."""

from __future__ import annotations

import os
import secrets
from datetime import date, timedelta

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

from . import categories, store
from .db import connect, default_db_path, secret_key
from .formatting import format_date, format_due, format_inr
from .notifiers import WhatsAppNotifier
from .recurrence import describe
from .store import ValidationError, format_remind_days


def create_app(db_path: str | None = None, password: str | None = None, today=None, notifier_factory=None) -> Flask:
    """Build the app.

    ``password`` defaults to BILL_TRACKER_PASSWORD; when empty, no login is
    required. ``today`` and ``notifier_factory`` are for tests.
    """
    app = Flask(__name__)
    db_path = db_path or default_db_path()
    conn = connect(db_path)
    try:
        app.secret_key = secret_key(conn)
    finally:
        conn.close()
    app.config.update(
        DB_PATH=db_path,
        PASSWORD=os.environ.get("BILL_TRACKER_PASSWORD", "") if password is None else password,
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
        SESSION_COOKIE_SAMESITE="Lax",
    )
    today_func = today or date.today
    make_notifier = notifier_factory or WhatsAppNotifier

    def db():
        if "db" not in g:
            g.db = connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.before_request
    def guard():
        if app.config["PASSWORD"] and not session.get("authed") and request.endpoint not in ("login", "static"):
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not token or not secrets.compare_digest(token, session.get("csrf", "")):
                abort(400, "Form expired, go back and try again.")

    @app.context_processor
    def helpers():
        today_ = today_func()
        return {
            "csrf_token": csrf_token,
            "today": today_,
            "inr": format_inr,
            "fdate": lambda d: format_date(d, today_),
            "fdue": lambda d: format_due(d, today_),
            "categories": categories.CATEGORIES,
            "default_remind": {k: format_remind_days(categories.default_remind_days(k)) for k in categories.CATEGORIES},
            "describe": describe,
        }

    def get_bill_or_404(bill_id: int) -> store.Bill:
        bill = store.get_bill(db(), bill_id)
        if bill is None:
            abort(404)
        return bill

    # --- login --------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if secrets.compare_digest(request.form.get("password", ""), app.config["PASSWORD"]):
                session.permanent = True
                session["authed"] = True
                target = request.args.get("next", "")
                # Only follow local paths, never another site.
                if not target.startswith("/") or target.startswith("//"):
                    target = url_for("dashboard")
                return redirect(target)
            error = "Wrong password."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # --- dashboard ----------------------------------------------------------

    @app.get("/")
    def dashboard():
        today_ = today_func()
        bills = store.list_bills(db())
        week_end = today_ + timedelta(days=7)
        return render_template(
            "dashboard.html",
            overdue=[b for b in bills if b.due_date < today_],
            this_week=[b for b in bills if today_ <= b.due_date <= week_end],
            later=[b for b in bills if b.due_date > week_end],
            month_total=sum(b.amount or 0 for b in bills if b.due_date <= today_ + timedelta(days=30)),
            recent=store.list_payments(db(), since=today_ - timedelta(days=30), limit=10),
            has_members=bool(store.list_members(db())),
            archived_count=len(store.list_bills(db(), active=False)),
        )

    @app.get("/archived")
    def archived():
        return render_template("archived.html", bills=store.list_bills(db(), active=False))

    # --- bills --------------------------------------------------------------

    def bill_form_values(bill: store.Bill | None) -> dict:
        if bill is None:
            return {
                "category": "electricity",
                "due_date": today_func().isoformat(),
                "repeat_every": "1",
                "repeat_unit": "month",
                "active": True,
            }
        return {
            "title": bill.title,
            "category": bill.category,
            "amount": "" if bill.amount is None else f"{bill.amount:g}",
            "due_date": bill.due_date.isoformat(),
            "repeat_every": str(bill.repeat_every),
            "repeat_unit": bill.repeat_unit,
            "remind_days": format_remind_days(bill.remind_days),
            "owner_id": str(bill.owner_id or ""),
            "reference": bill.reference,
            "link": bill.link,
            "notes": bill.notes,
            "active": bill.active,
        }

    def render_bill_form(bill, values, errors=None):
        return render_template(
            "bill_form.html", bill=bill, values=values, errors=errors or {}, members=store.list_members(db())
        )

    @app.route("/bills/new", methods=["GET", "POST"])
    def new_bill():
        if request.method == "POST":
            values = request.form.to_dict()
            try:
                bill_id = store.add_bill(db(), values)
            except ValidationError as exc:
                return render_bill_form(None, values, exc.errors), 400
            flash(f"Added {values['title'].strip()}.", "ok")
            return redirect(url_for("bill_detail", bill_id=bill_id))
        return render_bill_form(None, bill_form_values(None))

    @app.route("/bills/<int:bill_id>/edit", methods=["GET", "POST"])
    def edit_bill(bill_id: int):
        bill = get_bill_or_404(bill_id)
        if request.method == "POST":
            values = request.form.to_dict()
            values["active"] = "active" in request.form
            try:
                store.update_bill(db(), bill_id, values)
            except ValidationError as exc:
                return render_bill_form(bill, values, exc.errors), 400
            flash("Saved.", "ok")
            return redirect(url_for("bill_detail", bill_id=bill_id))
        return render_bill_form(bill, bill_form_values(bill))

    @app.get("/bills/<int:bill_id>")
    def bill_detail(bill_id: int):
        bill = get_bill_or_404(bill_id)
        return render_template("bill_detail.html", bill=bill, payments=store.list_payments(db(), bill_id=bill_id))

    @app.post("/bills/<int:bill_id>/delete")
    def delete_bill(bill_id: int):
        bill = get_bill_or_404(bill_id)
        store.delete_bill(db(), bill_id)
        flash(f"Deleted {bill.title}.", "ok")
        return redirect(url_for("dashboard"))

    @app.route("/bills/<int:bill_id>/pay", methods=["GET", "POST"])
    def pay_bill(bill_id: int):
        bill = get_bill_or_404(bill_id)
        if not bill.active:
            flash(f"{bill.title} is archived. Edit it and tick Active to track it again.", "warn")
            return redirect(url_for("bill_detail", bill_id=bill_id))
        if request.method == "GET":
            next_due = bill.next_due()
            values = {
                "paid_on": today_func().isoformat(),
                "amount": "" if bill.amount is None else f"{bill.amount:g}",
                "paid_by": str(session.get("member_id", "")),
                "next_due": next_due.isoformat() if next_due else "",
            }
            return render_pay_form(bill, values)

        values = request.form.to_dict()
        # The form names the due date it was opened for; a second submit
        # (double tap, back button) must not skip another cycle.
        if values.get("for_due") != bill.due_date.isoformat():
            flash(f"{bill.title} was already marked paid.", "warn")
            return redirect(url_for("dashboard"))
        errors = {}
        try:
            paid_on = store.parse_date(values.get("paid_on"))
        except ValueError:
            errors["paid_on"] = "Enter the date it was paid."
        try:
            amount = store.parse_amount(values.get("amount"))
        except ValueError:
            errors["amount"] = "Enter the amount as a number."
        try:
            paid_by = int(values["paid_by"]) if values.get("paid_by") else None
        except ValueError:
            errors["paid_by"] = "Pick who paid."
        try:
            next_due = store.parse_date(values["next_due"]) if values.get("next_due") else None
        except ValueError:
            errors["next_due"] = "Enter a date, or leave it empty to stop tracking this bill."
        if not errors:
            try:
                store.record_payment(
                    db(), bill, paid_on=paid_on, amount=amount, paid_by=paid_by,
                    next_due_date=next_due, note=values.get("note", ""),
                )
            except ValidationError as exc:
                errors = exc.errors
        if errors:
            return render_pay_form(bill, values, errors), 400
        if paid_by:
            session["member_id"] = paid_by
        if next_due:
            flash(f"✓ {bill.title} paid. Next due {format_date(next_due, today_func())}.", "ok")
        else:
            flash(f"✓ {bill.title} paid and archived.", "ok")
        return redirect(url_for("dashboard"))

    def render_pay_form(bill, values, errors=None):
        return render_template(
            "pay.html", bill=bill, values=values, errors=errors or {}, members=store.list_members(db())
        )

    # --- family members -----------------------------------------------------

    @app.route("/members", methods=["GET", "POST"])
    def members():
        values, errors = {"notify": True}, {}
        if request.method == "POST":
            values = request.form.to_dict()
            values["notify"] = "notify" in request.form
            try:
                store.add_member(db(), values)
            except ValidationError as exc:
                errors = exc.errors
            else:
                flash(f"Added {values['name'].strip()}.", "ok")
                return redirect(url_for("members"))
        status = 400 if errors else 200
        return render_template("members.html", members=store.list_members(db()), values=values, errors=errors), status

    @app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
    def edit_member(member_id: int):
        member = store.get_member(db(), member_id) or abort(404)
        errors = {}
        if request.method == "POST":
            values = request.form.to_dict()
            values["notify"] = "notify" in request.form
            try:
                store.update_member(db(), member_id, values)
            except ValidationError as exc:
                errors = exc.errors
            else:
                flash("Saved.", "ok")
                return redirect(url_for("members"))
        else:
            values = {
                "name": member.name,
                "phone": member.phone,
                "callmebot_key": member.callmebot_key,
                "notify": member.notify,
            }
        return render_template("member_form.html", member=member, values=values, errors=errors), 400 if errors else 200

    @app.post("/members/<int:member_id>/delete")
    def delete_member(member_id: int):
        member = store.get_member(db(), member_id) or abort(404)
        store.delete_member(db(), member_id)
        flash(f"Removed {member.name}.", "ok")
        return redirect(url_for("members"))

    @app.post("/members/<int:member_id>/test")
    def test_member(member_id: int):
        member = store.get_member(db(), member_id) or abort(404)
        try:
            make_notifier().send(member, "✅ Family Bill Tracker: WhatsApp reminders are working.")
        except Exception as exc:  # noqa: BLE001 - shown to the user
            flash(f"Couldn't send to {member.name}: {exc}", "error")
        else:
            flash(f"Test message sent to {member.name}. Check WhatsApp.", "ok")
        return redirect(url_for("members"))

    return app
