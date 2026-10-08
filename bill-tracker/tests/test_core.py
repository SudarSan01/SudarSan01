import io
import os
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from datetime import date
from unittest import mock

from bill_tracker import store
from bill_tracker.cli import main
from bill_tracker.db import connect
from bill_tracker.formatting import format_due, format_inr
from bill_tracker.notifiers import WhatsAppNotifier
from bill_tracker.recurrence import describe, next_due
from bill_tracker.reminders import format_message, pending_reminders, reminder_stage, send_reminders
from bill_tracker.store import ValidationError


class RecordingNotifier:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, member, text):
        if member.name in self.fail_for:
            raise RuntimeError("network down")
        self.sent.append((member.name, text))


def bill_data(**overrides):
    data = {
        "title": "TNEB electricity",
        "category": "electricity",
        "amount": "1240",
        "due_date": "2026-10-15",
        "repeat_unit": "month",
        "repeat_every": "1",
    }
    data.update(overrides)
    return data


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "bills.db")
        self.conn = connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()


class RecurrenceTests(unittest.TestCase):
    def test_monthly(self):
        self.assertEqual(next_due(date(2026, 10, 15), "month", 1), date(2026, 11, 15))

    def test_month_end_clamps_then_recovers(self):
        feb = next_due(date(2027, 1, 31), "month", 1, anchor_day=31)
        self.assertEqual(feb, date(2027, 2, 28))
        self.assertEqual(next_due(feb, "month", 1, anchor_day=31), date(2027, 3, 31))

    def test_quarterly_across_year(self):
        self.assertEqual(next_due(date(2026, 11, 30), "month", 3), date(2027, 2, 28))

    def test_prepaid_days(self):
        self.assertEqual(next_due(date(2026, 10, 8), "day", 28), date(2026, 11, 5))

    def test_yearly_leap_day(self):
        self.assertEqual(next_due(date(2028, 2, 29), "year", 1), date(2029, 2, 28))
        self.assertEqual(next_due(date(2029, 2, 28), "year", 3, anchor_day=29), date(2032, 2, 29))

    def test_one_time(self):
        self.assertIsNone(next_due(date(2026, 10, 8), "none", 1))

    def test_describe(self):
        self.assertEqual(describe("month", 1), "Monthly")
        self.assertEqual(describe("month", 3), "Quarterly")
        self.assertEqual(describe("day", 28), "Every 28 days")
        self.assertEqual(describe("none", 1), "One-time")


class FormattingTests(unittest.TestCase):
    def test_inr_grouping(self):
        self.assertEqual(format_inr(1240), "₹1,240")
        self.assertEqual(format_inr(123456.5), "₹1,23,456.50")
        self.assertEqual(format_inr(10000000), "₹1,00,00,000")
        self.assertEqual(format_inr(999), "₹999")
        self.assertEqual(format_inr(None), "")

    def test_due_text(self):
        today = date(2026, 10, 8)
        self.assertEqual(format_due(date(2026, 10, 8), today), "due today")
        self.assertEqual(format_due(date(2026, 10, 9), today), "due tomorrow")
        self.assertEqual(format_due(date(2026, 10, 15), today), "due in 7 days")
        self.assertEqual(format_due(date(2026, 10, 5), today), "overdue by 3 days")
        self.assertEqual(format_due(date(2026, 12, 20), today), "due in 2 months")
        self.assertEqual(format_due(date(2031, 3, 14), today), "due in 4 years")


class StoreTests(DbTestCase):
    def test_default_reminders_depend_on_category(self):
        a = store.get_bill(self.conn, store.add_bill(self.conn, bill_data()))
        b = store.get_bill(self.conn, store.add_bill(self.conn, bill_data(title="Car insurance", category="insurance")))
        self.assertEqual(a.remind_days, [7, 3, 1, 0])
        self.assertEqual(b.remind_days, [30, 15, 7, 1, 0])

    def test_validation(self):
        with self.assertRaises(ValidationError) as ctx:
            store.add_bill(self.conn, bill_data(title=" ", amount="abc", due_date="", link="javascript:alert(1)"))
        self.assertEqual(set(ctx.exception.errors), {"title", "amount", "due_date", "link"})

    def test_amount_accepts_rupee_formatting(self):
        bill = store.get_bill(self.conn, store.add_bill(self.conn, bill_data(amount="₹1,24,000.50")))
        self.assertEqual(bill.amount, 124000.5)

    def test_member_phone_must_be_international(self):
        with self.assertRaises(ValidationError):
            store.add_member(self.conn, {"name": "Amma", "phone": "98765 43210"})
        member_id = store.add_member(self.conn, {"name": "Amma", "phone": "+91 98765-43210"})
        self.assertEqual(store.get_member(self.conn, member_id).phone, "+919876543210")

    def test_payment_moves_bill_to_next_cycle(self):
        bill = store.get_bill(self.conn, store.add_bill(self.conn, bill_data(due_date="2027-01-31")))
        store.record_payment(self.conn, bill, paid_on=date(2027, 1, 30), amount=1300, paid_by=None,
                             next_due_date=bill.next_due())
        bill = store.get_bill(self.conn, bill.id)
        self.assertEqual(bill.due_date, date(2027, 2, 28))
        self.assertEqual(bill.anchor_day, 31)
        self.assertEqual(bill.next_due(), date(2027, 3, 31))
        [payment] = store.list_payments(self.conn, bill_id=bill.id)
        self.assertEqual((payment.due_date, payment.amount), (date(2027, 1, 31), 1300))

    def test_custom_next_due_becomes_new_anchor(self):
        bill = store.get_bill(self.conn, store.add_bill(self.conn, bill_data(due_date="2026-10-15")))
        store.record_payment(self.conn, bill, paid_on=date(2026, 10, 10), amount=None, paid_by=None,
                             next_due_date=date(2026, 11, 20))
        self.assertEqual(store.get_bill(self.conn, bill.id).next_due(), date(2026, 12, 20))

    def test_payment_without_next_due_archives(self):
        bill = store.get_bill(self.conn, store.add_bill(self.conn, bill_data(repeat_unit="none")))
        store.record_payment(self.conn, bill, paid_on=date(2026, 10, 10), amount=None, paid_by=None,
                             next_due_date=None)
        self.assertEqual(store.list_bills(self.conn), [])
        self.assertEqual(len(store.list_bills(self.conn, active=False)), 1)

    def test_next_due_must_move_forward(self):
        bill = store.get_bill(self.conn, store.add_bill(self.conn, bill_data()))
        with self.assertRaises(ValidationError):
            store.record_payment(self.conn, bill, paid_on=date(2026, 10, 10), amount=None, paid_by=None,
                                 next_due_date=bill.due_date)


class ReminderTests(DbTestCase):
    def setUp(self):
        super().setUp()
        store.add_member(self.conn, {"name": "Appa", "phone": "+919800000001", "callmebot_key": "k1"})
        store.add_member(self.conn, {"name": "Amma", "phone": "+919800000002", "callmebot_key": "k2"})
        self.bill_id = store.add_bill(self.conn, bill_data(due_date="2026-10-15"))  # reminders 7, 3, 1, 0

    def run_on(self, day, notifier=None):
        notifier = notifier or RecordingNotifier()
        result = send_reminders(self.conn, notifier, today=day)
        return notifier, result

    def test_stage(self):
        bill = store.get_bill(self.conn, self.bill_id)
        self.assertIsNone(reminder_stage(bill, date(2026, 10, 7)))
        self.assertEqual(reminder_stage(bill, date(2026, 10, 8)), "before:7")
        self.assertEqual(reminder_stage(bill, date(2026, 10, 10)), "before:7")
        self.assertEqual(reminder_stage(bill, date(2026, 10, 12)), "before:3")
        self.assertEqual(reminder_stage(bill, date(2026, 10, 15)), "before:0")
        self.assertEqual(reminder_stage(bill, date(2026, 10, 17)), "overdue:2026-10-17")

    def test_everyone_gets_each_stage_once(self):
        notifier, _ = self.run_on(date(2026, 10, 8))
        self.assertEqual(sorted(n for n, _ in notifier.sent), ["Amma", "Appa"])
        notifier, _ = self.run_on(date(2026, 10, 9))
        self.assertEqual(notifier.sent, [])
        notifier, _ = self.run_on(date(2026, 10, 12))
        self.assertEqual(len(notifier.sent), 2)

    def test_missed_run_sends_latest_stage_only(self):
        notifier, _ = self.run_on(date(2026, 10, 13))  # 2 days left: stages 7 and 3 both passed
        self.assertEqual(len(notifier.sent), 2)
        self.assertEqual(pending_reminders(self.conn, date(2026, 10, 13)), {})

    def test_overdue_repeats_daily_until_paid(self):
        for day in (16, 17):
            notifier, _ = self.run_on(date(2026, 10, day))
            self.assertEqual(len(notifier.sent), 2)
            self.assertIn("OVERDUE", notifier.sent[0][1])
        bill = store.get_bill(self.conn, self.bill_id)
        store.record_payment(self.conn, bill, paid_on=date(2026, 10, 17), amount=None, paid_by=None,
                             next_due_date=bill.next_due())
        notifier, _ = self.run_on(date(2026, 10, 18))
        self.assertEqual(notifier.sent, [])

    def test_failed_send_is_retried(self):
        notifier, result = self.run_on(date(2026, 10, 8), RecordingNotifier(fail_for={"Amma"}))
        self.assertEqual([m.name for m, _ in result.failed], ["Amma"])
        notifier, _ = self.run_on(date(2026, 10, 9))
        self.assertEqual([n for n, _ in notifier.sent], ["Amma"])

    def test_members_with_reminders_off_or_no_phone(self):
        store.add_member(self.conn, {"name": "Kid", "phone": "", "notify": True})
        store.add_member(self.conn, {"name": "Paati", "phone": "+919800000003", "notify": False})
        notifier, result = self.run_on(date(2026, 10, 8))
        self.assertEqual(sorted(n for n, _ in notifier.sent), ["Amma", "Appa"])
        self.assertEqual([m.name for m, _ in result.skipped], ["Kid"])

    def test_one_message_lists_all_due_bills(self):
        store.add_bill(self.conn, bill_data(title="Jio recharge", category="mobile", amount="", due_date="2026-10-09"))
        notifier, _ = self.run_on(date(2026, 10, 8))
        self.assertEqual(len(notifier.sent), 2)
        text = notifier.sent[0][1]
        self.assertIn("Jio recharge", text)
        self.assertIn("TNEB electricity · ₹1,240 · due in 7 days", text)
        self.assertLess(text.index("Jio"), text.index("TNEB"))

    def test_dry_run_records_nothing(self):
        with redirect_stdout(io.StringIO()):
            send_reminders(self.conn, RecordingNotifier(), today=date(2026, 10, 8), dry_run=True)
        self.assertEqual(len(pending_reminders(self.conn, date(2026, 10, 8))), 2)

    def test_message_includes_link(self):
        bill = store.get_bill(self.conn, self.bill_id)
        from bill_tracker.reminders import DueReminder
        text = format_message([DueReminder(bill, "before:7")], date(2026, 10, 8), "http://192.168.1.5:8000/")
        self.assertTrue(text.endswith("Mark paid: http://192.168.1.5:8000/"))


class WhatsAppNotifierTests(unittest.TestCase):
    def test_builds_callmebot_url_with_members_key(self):
        member = store.Member(1, "Amma", "+919800000002", "k2", True)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"Message queued."
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            WhatsAppNotifier().send(member, "hello & bye")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(urlopen.call_args[0][0]).query)
        self.assertEqual(query, {"phone": ["+919800000002"], "text": ["hello & bye"], "apikey": ["k2"]})

    def test_invalid_key_raises(self):
        member = store.Member(1, "Amma", "+919800000002", "bad", True)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"APIKey is invalid."
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                WhatsAppNotifier().send(member, "hi")

    def test_missing_key_raises(self):
        member = store.Member(1, "Amma", "+919800000002", "", True)
        with mock.patch.dict(os.environ, {"CALLMEBOT_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                WhatsAppNotifier().send(member, "hi")


class CliTests(DbTestCase):
    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--db", self.db_path, *args])
        return code, out.getvalue()

    def test_add_list_pay_remind(self):
        self.assertEqual(self.cli("add-member", "Appa", "--phone", "+919800000001", "--key", "k")[0], 0)
        code, _ = self.cli("add-bill", "Bike PUC", "--category", "puc", "--due", "2026-10-20",
                           "--every", "6", "--unit", "month", "--owner", "appa", "--reference", "TN09 AB 1234")
        self.assertEqual(code, 0)
        code, out = self.cli("remind", "--channel", "console", "--today", "2026-10-08")
        self.assertEqual(code, 0)
        self.assertIn("Bike PUC", out)  # 12 days left, inside the 15-day stage
        self.assertIn("Ref TN09 AB 1234 · Appa", out)
        code, out = self.cli("pay", "1", "--by", "Appa", "--amount", "100")
        self.assertEqual(code, 0)
        self.assertIn("Next due 2027-04-20", out)
        self.assertIn("2027-04-20", self.cli("list")[1])

    def test_unknown_owner(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            code, _ = self.cli("add-bill", "Rent", "--due", "2026-11-01", "--owner", "Nobody")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
