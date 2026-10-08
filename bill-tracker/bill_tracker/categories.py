"""Bill categories and their default reminder schedules."""

from __future__ import annotations

# key -> (label, icon)
CATEGORIES = {
    "electricity": ("Electricity", "⚡"),
    "rent": ("Rent", "🏠"),
    "mobile": ("Mobile recharge", "📱"),
    "internet": ("Broadband / DTH", "📡"),
    "water": ("Water", "🚰"),
    "gas": ("Gas / LPG", "🔥"),
    "insurance": ("Insurance", "🛡️"),
    "puc": ("Vehicle PUC", "🚗"),
    "licence": ("Licence / RC renewal", "🪪"),
    "tax": ("Property / other tax", "🏛️"),
    "emi": ("Loan EMI / credit card", "💳"),
    "school": ("School / tuition fees", "🎒"),
    "subscription": ("Subscription", "📺"),
    "other": ("Other", "📌"),
}

# Renewals that take paperwork or a visit get reminders well in advance.
LONG_RENEWALS = {"insurance", "puc", "licence", "tax"}

DEFAULT_REMIND_DAYS = [7, 3, 1, 0]
LONG_RENEWAL_REMIND_DAYS = [30, 15, 7, 1, 0]


def default_remind_days(category: str) -> list[int]:
    return list(LONG_RENEWAL_REMIND_DAYS if category in LONG_RENEWALS else DEFAULT_REMIND_DAYS)


def label(category: str) -> str:
    return CATEGORIES.get(category, CATEGORIES["other"])[0]


def icon(category: str) -> str:
    return CATEGORIES.get(category, CATEGORIES["other"])[1]
