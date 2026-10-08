"""JSON-file persistence for subscriptions and sent-notification history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set

from .models import Subscription


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.subscriptions: List[Subscription] = []
        self.sent: Set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        self.subscriptions = [Subscription.from_dict(s) for s in data.get("subscriptions", [])]
        self.sent = set(data.get("sent", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "subscriptions": [s.to_dict() for s in self.subscriptions],
            "sent": sorted(self.sent),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, sub: Subscription) -> Subscription:
        self.subscriptions.append(sub)
        self.save()
        return sub

    def remove(self, subscription_id: str) -> bool:
        before = len(self.subscriptions)
        self.subscriptions = [s for s in self.subscriptions if s.subscription_id != subscription_id]
        self.sent = {k for k in self.sent if not k.startswith(f"{subscription_id}:")}
        changed = len(self.subscriptions) != before
        if changed:
            self.save()
        return changed

    @staticmethod
    def sent_key(subscription_id: str, showtime_id: str) -> str:
        return f"{subscription_id}:{showtime_id}"
