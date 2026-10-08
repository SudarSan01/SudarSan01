"""Reading and changing family members, bills and payments."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from . import categories
from .recurrence import REPEAT_UNITS, describe, next_due


class ValidationError(ValueError):
    """Bad user input; ``errors`` maps each field name to a message."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


@dataclass
class Member:
    id: int
    name: str
    phone: str
    callmebot_key: str
    notify: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Member":
        return cls(row["id"], row["name"], row["phone"], row["callmebot_key"], bool(row["notify"]))


@dataclass
class Bill:
    id: int
    title: str
    category: str
    amount: float | None
    due_date: date
    repeat_unit: str
    repeat_every: int
    anchor_day: int
    remind_days: list[int]
    owner_id: int | None
    owner_name: str | None
    reference: str
    link: str
    notes: str
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Bill":
        return cls(
            id=row["id"],
            title=row["title"],
            category=row["category"],
            amount=row["amount"],
            due_date=date.fromisoformat(row["due_date"]),
            repeat_unit=row["repeat_unit"],
            repeat_every=row["repeat_every"],
            anchor_day=row["anchor_day"],
            remind_days=parse_remind_days(row["remind_days"]),
            owner_id=row["owner_id"],
            owner_name=row["owner_name"],
            reference=row["reference"],
            link=row["link"],
            notes=row["notes"],
            active=bool(row["active"]),
        )

    @property
    def icon(self) -> str:
        return categories.icon(self.category)

    @property
    def category_label(self) -> str:
        return categories.label(self.category)

    @property
    def repeats(self) -> bool:
        return self.repeat_unit != "none"

    @property
    def schedule(self) -> str:
        return describe(self.repeat_unit, self.repeat_every)

    def next_due(self) -> date | None:
        return next_due(self.due_date, self.repeat_unit, self.repeat_every, self.anchor_day)

    def days_left(self, today: date) -> int:
        return (self.due_date - today).days


@dataclass
class Payment:
    id: int
    bill_id: int
    bill_title: str
    due_date: date
    paid_on: date
    amount: float | None
    paid_by_name: str | None
    note: str


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- parsing helpers ------------------------------------------------------


def parse_remind_days(text: str) -> list[int]:
    """'7, 3, 1, 0' -> [7, 3, 1, 0]. Raises ValueError for anything else."""
    days = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        value = int(part)
        if not 0 <= value <= 365:
            raise ValueError(part)
        days.add(value)
    return sorted(days, reverse=True)


def format_remind_days(days: list[int]) -> str:
    return ", ".join(str(d) for d in days)


def parse_amount(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        text = text.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
        if not text:
            return None
        value = float(text)
    if value < 0:
        raise ValueError("negative amount")
    return value


def parse_date(text) -> date:
    if isinstance(text, date):
        return text
    return date.fromisoformat((text or "").strip())


def _optional_id(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


PHONE_RE = re.compile(r"^\+\d{8,15}$")


def normalise_phone(text: str) -> str:
    return re.sub(r"[\s\-()]", "", text or "")


# --- members --------------------------------------------------------------


def clean_member(raw: dict) -> dict:
    errors = {}
    name = (raw.get("name") or "").strip()
    if not name:
        errors["name"] = "Enter a name."
    phone = normalise_phone(raw.get("phone", ""))
    if phone and not PHONE_RE.match(phone):
        errors["phone"] = "Use international format with country code, e.g. +919876543210."
    if errors:
        raise ValidationError(errors)
    return {
        "name": name,
        "phone": phone,
        "callmebot_key": (raw.get("callmebot_key") or "").strip(),
        "notify": 1 if raw.get("notify", True) else 0,
    }


def list_members(conn: sqlite3.Connection) -> list[Member]:
    rows = conn.execute("SELECT * FROM members ORDER BY name COLLATE NOCASE").fetchall()
    return [Member.from_row(r) for r in rows]


def get_member(conn: sqlite3.Connection, member_id: int) -> Member | None:
    row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    return Member.from_row(row) if row else None


def find_member(conn: sqlite3.Connection, name: str) -> Member | None:
    row = conn.execute("SELECT * FROM members WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()
    return Member.from_row(row) if row else None


def add_member(conn: sqlite3.Connection, raw: dict) -> int:
    data = clean_member(raw)
    cur = conn.execute(
        "INSERT INTO members (name, phone, callmebot_key, notify) VALUES (:name, :phone, :callmebot_key, :notify)",
        data,
    )
    conn.commit()
    return cur.lastrowid


def update_member(conn: sqlite3.Connection, member_id: int, raw: dict) -> None:
    data = clean_member(raw)
    data["id"] = member_id
    conn.execute(
        "UPDATE members SET name = :name, phone = :phone, callmebot_key = :callmebot_key,"
        " notify = :notify WHERE id = :id",
        data,
    )
    conn.commit()


def delete_member(conn: sqlite3.Connection, member_id: int) -> None:
    conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
    conn.commit()


# --- bills ----------------------------------------------------------------


def clean_bill(raw: dict) -> dict:
    errors = {}

    title = (raw.get("title") or "").strip()
    if not title:
        errors["title"] = "Enter a name for the bill."

    category = raw.get("category") or "other"
    if category not in categories.CATEGORIES:
        errors["category"] = "Pick a category."

    amount = None
    try:
        amount = parse_amount(raw.get("amount"))
    except ValueError:
        errors["amount"] = "Enter the amount as a number, e.g. 1240 or 1240.50."

    due_date = None
    try:
        due_date = parse_date(raw.get("due_date"))
    except ValueError:
        errors["due_date"] = "Enter the due date."

    repeat_unit = raw.get("repeat_unit") or "month"
    if repeat_unit not in REPEAT_UNITS:
        errors["repeat_unit"] = "Pick how often it repeats."
    repeat_every = 1
    if repeat_unit != "none":
        try:
            repeat_every = int(raw.get("repeat_every") or 1)
            if not 1 <= repeat_every <= 3650:
                raise ValueError
        except ValueError:
            errors["repeat_every"] = "Enter a whole number, e.g. 1, 3 or 28."

    remind_text = (raw.get("remind_days") or "").strip()
    try:
        remind_days = parse_remind_days(remind_text) if remind_text else categories.default_remind_days(category)
    except ValueError:
        remind_days = []
        errors["remind_days"] = "List days before the due date, e.g. 7, 3, 1, 0 (0 = on the day)."

    try:
        owner_id = _optional_id(raw.get("owner_id"))
    except ValueError:
        owner_id = None
        errors["owner_id"] = "Pick a family member."

    link = (raw.get("link") or "").strip()
    if link and not re.match(r"^https?://", link, re.IGNORECASE):
        errors["link"] = "Links must start with http:// or https://."

    if errors:
        raise ValidationError(errors)
    return {
        "title": title,
        "category": category,
        "amount": amount,
        "due_date": due_date.isoformat(),
        "repeat_unit": repeat_unit,
        "repeat_every": repeat_every,
        "anchor_day": due_date.day,
        "remind_days": format_remind_days(remind_days),
        "owner_id": owner_id,
        "reference": (raw.get("reference") or "").strip(),
        "link": link,
        "notes": (raw.get("notes") or "").strip(),
        "active": 1 if raw.get("active", True) else 0,
    }


_BILL_SELECT = "SELECT b.*, m.name AS owner_name FROM bills b LEFT JOIN members m ON m.id = b.owner_id"


def list_bills(conn: sqlite3.Connection, active: bool = True) -> list[Bill]:
    rows = conn.execute(
        f"{_BILL_SELECT} WHERE b.active = ? ORDER BY b.due_date, b.title COLLATE NOCASE",
        (1 if active else 0,),
    ).fetchall()
    return [Bill.from_row(r) for r in rows]


def get_bill(conn: sqlite3.Connection, bill_id: int) -> Bill | None:
    row = conn.execute(f"{_BILL_SELECT} WHERE b.id = ?", (bill_id,)).fetchone()
    return Bill.from_row(row) if row else None


def add_bill(conn: sqlite3.Connection, raw: dict) -> int:
    data = clean_bill(raw)
    data["created_at"] = _now()
    cur = conn.execute(
        "INSERT INTO bills (title, category, amount, due_date, repeat_unit, repeat_every, anchor_day,"
        " remind_days, owner_id, reference, link, notes, active, created_at)"
        " VALUES (:title, :category, :amount, :due_date, :repeat_unit, :repeat_every, :anchor_day,"
        " :remind_days, :owner_id, :reference, :link, :notes, :active, :created_at)",
        data,
    )
    conn.commit()
    return cur.lastrowid


def update_bill(conn: sqlite3.Connection, bill_id: int, raw: dict) -> None:
    data = clean_bill(raw)
    data["id"] = bill_id
    current = get_bill(conn, bill_id)
    if current and current.due_date.isoformat() == data["due_date"]:
        # Same due date: keep the original day of month (e.g. 31st while due 28 Feb).
        data["anchor_day"] = current.anchor_day
    conn.execute(
        "UPDATE bills SET title = :title, category = :category, amount = :amount, due_date = :due_date,"
        " repeat_unit = :repeat_unit, repeat_every = :repeat_every, anchor_day = :anchor_day,"
        " remind_days = :remind_days, owner_id = :owner_id, reference = :reference, link = :link,"
        " notes = :notes, active = :active WHERE id = :id",
        data,
    )
    conn.commit()


def delete_bill(conn: sqlite3.Connection, bill_id: int) -> None:
    conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
    conn.commit()


# --- payments -------------------------------------------------------------


def record_payment(
    conn: sqlite3.Connection,
    bill: Bill,
    *,
    paid_on: date,
    amount: float | None,
    paid_by: int | None,
    next_due_date: date | None,
    note: str = "",
) -> None:
    """Record that ``bill``'s current due date was paid and move it on.

    With ``next_due_date`` None the bill is archived (a one-time bill, or one
    the family no longer pays).
    """
    if next_due_date is not None and next_due_date <= bill.due_date:
        raise ValidationError({"next_due": "The next due date must be after the current one."})
    conn.execute(
        "INSERT INTO payments (bill_id, due_date, paid_on, amount, paid_by, note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bill.id, bill.due_date.isoformat(), paid_on.isoformat(), amount, paid_by, note.strip(), _now()),
    )
    if next_due_date is None:
        conn.execute("UPDATE bills SET active = 0 WHERE id = ?", (bill.id,))
    else:
        # A date other than the usual cycle becomes the new day of month.
        anchor_day = bill.anchor_day if next_due_date == bill.next_due() else next_due_date.day
        conn.execute(
            "UPDATE bills SET due_date = ?, anchor_day = ? WHERE id = ?",
            (next_due_date.isoformat(), anchor_day, bill.id),
        )
    conn.commit()


def list_payments(
    conn: sqlite3.Connection, bill_id: int | None = None, since: date | None = None, limit: int = 50
) -> list[Payment]:
    sql = (
        "SELECT p.*, b.title AS bill_title, m.name AS paid_by_name FROM payments p"
        " JOIN bills b ON b.id = p.bill_id LEFT JOIN members m ON m.id = p.paid_by WHERE 1 = 1"
    )
    params: list = []
    if bill_id is not None:
        sql += " AND p.bill_id = ?"
        params.append(bill_id)
    if since is not None:
        sql += " AND p.paid_on >= ?"
        params.append(since.isoformat())
    sql += " ORDER BY p.paid_on DESC, p.id DESC LIMIT ?"
    params.append(limit)
    return [
        Payment(
            id=r["id"],
            bill_id=r["bill_id"],
            bill_title=r["bill_title"],
            due_date=date.fromisoformat(r["due_date"]),
            paid_on=date.fromisoformat(r["paid_on"]),
            amount=r["amount"],
            paid_by_name=r["paid_by_name"],
            note=r["note"],
        )
        for r in conn.execute(sql, params).fetchall()
    ]
