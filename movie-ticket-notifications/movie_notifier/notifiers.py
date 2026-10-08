"""Notification channels."""

from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from abc import ABC, abstractmethod
from email.message import EmailMessage

from .models import Showtime, Subscription


def format_message(sub: Subscription, show: Showtime) -> str:
    lines = [
        f"Tickets available for '{show.movie}'!",
        f"Theater : {show.theater} ({show.city})",
        f"Showtime: {show.starts_at:%a %d %b %Y, %I:%M %p}",
        f"Seats   : {show.seats_available}",
    ]
    if show.price is not None:
        lines.append(f"Price   : {show.price:.2f}")
    if show.booking_url:
        lines.append(f"Book now: {show.booking_url}")
    return "\n".join(lines)


class Notifier(ABC):
    @abstractmethod
    def send(self, sub: Subscription, show: Showtime) -> None:
        """Deliver a notification; raise on failure."""


class ConsoleNotifier(Notifier):
    def send(self, sub: Subscription, show: Showtime) -> None:
        print(f"[notify -> {sub.target}]\n{format_message(sub, show)}\n")


class EmailNotifier(Notifier):
    """Sends email via SMTP. Configured with SMTP_* environment variables."""

    def __init__(self):
        self.host = os.environ.get("SMTP_HOST", "localhost")
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ.get("SMTP_USER")
        self.password = os.environ.get("SMTP_PASSWORD")
        self.sender = os.environ.get("SMTP_FROM", self.user or "noreply@movie-notifier.local")
        self.use_tls = os.environ.get("SMTP_TLS", "true").lower() != "false"

    def send(self, sub: Subscription, show: Showtime) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"Tickets open: {show.movie} at {show.theater}"
        msg["From"] = self.sender
        msg["To"] = sub.target
        msg.set_content(format_message(sub, show))
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


class WebhookNotifier(Notifier):
    """POSTs a JSON payload (Slack/Discord-compatible "text" field) to a URL."""

    def send(self, sub: Subscription, show: Showtime) -> None:
        text = format_message(sub, show)
        body = json.dumps({"text": text, "content": text}).encode("utf-8")
        req = urllib.request.Request(
            sub.target, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10):
            pass


NOTIFIERS = {
    "console": ConsoleNotifier,
    "email": EmailNotifier,
    "webhook": WebhookNotifier,
}


def get_notifier(channel: str) -> Notifier:
    try:
        return NOTIFIERS[channel]()
    except KeyError:
        raise ValueError(f"Unknown channel '{channel}'. Choose from: {', '.join(NOTIFIERS)}")
