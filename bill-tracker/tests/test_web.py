import os
import re
import tempfile
import unittest
from contextlib import closing
from datetime import date

from bill_tracker import store
from bill_tracker.db import connect
from bill_tracker.web import create_app

TODAY = date(2026, 10, 8)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, member, text):
        self.sent.append((member.name, text))


class WebTestCase(unittest.TestCase):
    password = ""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "bills.db")
        self.notifier = Notifier()
        self.app = create_app(self.db_path, password=self.password, today=lambda: TODAY,
                              notifier_factory=lambda: self.notifier)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def token(self, path="/"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, path, data, form_page=None):
        data = dict(data, csrf_token=self.token(form_page or path))
        return self.client.post(path, data=data)

    def db(self):
        return closing(connect(self.db_path))


class DashboardFlowTests(WebTestCase):
    def test_empty_dashboard(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("No bills yet", html)
        self.assertIn("Add family members", html)

    def test_add_bill_then_pay(self):
        resp = self.post("/bills/new", {
            "title": "TNEB electricity", "category": "electricity", "amount": "1,240",
            "due_date": "2026-10-10", "repeat_every": "1", "repeat_unit": "month",
        })
        self.assertEqual(resp.status_code, 302)

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Due this week", html)
        self.assertIn("TNEB electricity", html)
        self.assertIn("₹1,240", html)

        pay_form = self.client.get("/bills/1/pay").get_data(as_text=True)
        self.assertIn('value="2026-11-10"', pay_form)  # next due prefilled
        data = {"for_due": "2026-10-10", "paid_on": "2026-10-08", "amount": "1300", "next_due": "2026-11-10"}
        resp = self.post("/bills/1/pay", data)
        self.assertEqual(resp.status_code, 302)
        # A second submit of the same form must not skip another month.
        self.post("/bills/1/pay", data, form_page="/bills/1")
        with self.db() as conn:
            self.assertEqual(store.get_bill(conn, 1).due_date, date(2026, 11, 10))
            self.assertEqual(len(store.list_payments(conn, bill_id=1)), 1)

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Paid in the last 30 days", html)
        self.assertIn("Upcoming", html)

    def test_invalid_bill_shows_errors(self):
        resp = self.post("/bills/new", {"title": "", "due_date": "", "repeat_unit": "month"}, form_page="/bills/new")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Enter a name for the bill.", resp.get_data(as_text=True))

    def test_overdue_section(self):
        with self.db() as conn:
            store.add_bill(conn, {"title": "Rent", "category": "rent", "due_date": "2026-10-05"})
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Overdue", html)
        self.assertIn("overdue by 3 days", html)

    def test_edit_archive_and_delete(self):
        with self.db() as conn:
            store.add_bill(conn, {"title": "Netflix", "category": "subscription", "due_date": "2026-10-20"})
        resp = self.post("/bills/1/edit", {
            "title": "Netflix", "category": "subscription", "due_date": "2026-10-20", "repeat_unit": "month",
            "repeat_every": "1",
        })  # "active" unticked
        self.assertEqual(resp.status_code, 302)
        self.assertIn("Netflix", self.client.get("/archived").get_data(as_text=True))
        self.post("/bills/1/delete", {}, form_page="/bills/1")
        self.assertEqual(self.client.get("/bills/1").status_code, 404)

    def test_post_without_csrf_rejected(self):
        resp = self.client.post("/bills/new", data={"title": "x", "due_date": "2026-10-10"})
        self.assertEqual(resp.status_code, 400)


class MemberTests(WebTestCase):
    def test_add_and_test_member(self):
        resp = self.post("/members", {"name": "Amma", "phone": "+919800000002", "callmebot_key": "k", "notify": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("Amma", self.client.get("/members").get_data(as_text=True))
        self.post("/members/1/test", {}, form_page="/members")
        self.assertEqual(self.notifier.sent[0][0], "Amma")

    def test_bad_phone(self):
        resp = self.post("/members", {"name": "Amma", "phone": "9876543210"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("international format", resp.get_data(as_text=True))


class LoginTests(WebTestCase):
    password = "family123"

    def test_requires_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_wrong_then_right_password(self):
        resp = self.post("/login", {"password": "nope"})
        self.assertIn("Wrong password", resp.get_data(as_text=True))
        resp = self.post("/login?next=/members", {"password": "family123"}, form_page="/login")
        self.assertEqual(resp.headers["Location"], "/members")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_next_cannot_leave_the_site(self):
        resp = self.post("/login?next=//evil.example", {"password": "family123"}, form_page="/login")
        self.assertEqual(resp.headers["Location"], "/")


if __name__ == "__main__":
    unittest.main()
