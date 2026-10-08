"""Ways of delivering a reminder message to a family member."""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from .store import Member


class Notifier(ABC):
    @abstractmethod
    def send(self, member: Member, text: str) -> None:
        """Deliver ``text`` to ``member``; raise on failure."""


class ConsoleNotifier(Notifier):
    def send(self, member: Member, text: str) -> None:
        print(f"[to {member.name} {member.phone}]\n{text}\n")


class WhatsAppNotifier(Notifier):
    """Sends a WhatsApp message through CallMeBot (https://www.callmebot.com).

    CallMeBot issues one API key per phone number, saved on each family
    member. CALLMEBOT_API_KEY is used for a member without their own key.
    """

    API_URL = "https://api.callmebot.com/whatsapp.php"

    def __init__(self):
        self.api_key = os.environ.get("CALLMEBOT_API_KEY")

    def send(self, member: Member, text: str) -> None:
        if not member.phone:
            raise RuntimeError(f"{member.name} has no phone number")
        key = member.callmebot_key or self.api_key
        if not key:
            raise RuntimeError(f"{member.name} has no CallMeBot API key")
        query = urllib.parse.urlencode({"phone": member.phone, "text": text, "apikey": key})
        with urllib.request.urlopen(f"{self.API_URL}?{query}", timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
        # CallMeBot answers 200 even for a wrong key; the body says what happened.
        if "APIKey is invalid" in body:
            raise RuntimeError(f"CallMeBot refused the message: {body.strip()[:200]}")


NOTIFIERS = {
    "whatsapp": WhatsAppNotifier,
    "console": ConsoleNotifier,
}


def get_notifier(channel: str) -> Notifier:
    try:
        return NOTIFIERS[channel]()
    except KeyError:
        raise ValueError(f"Unknown channel '{channel}'. Choose from: {', '.join(NOTIFIERS)}")
