"""Core data models."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def name_matches(wanted: str, actual: str) -> bool:
    """True if the words of `wanted` appear, in order, in `actual`.

    Lets "Jailer 2" match "Jailer 2 (Tamil)" and "PVR S2" match
    "PVR: S2 Perambur, Chennai", ignoring case and punctuation.
    """
    w, a = _words(wanted), _words(actual)
    return bool(w) and any(a[i:i + len(w)] == w for i in range(len(a) - len(w) + 1))


@dataclass(frozen=True)
class Showtime:
    """A single screening of a movie at a theater."""

    showtime_id: str
    movie: str
    theater: str
    city: str
    starts_at: datetime
    seats_available: int
    booking_open: bool
    price: Optional[float] = None
    booking_url: Optional[str] = None

    @property
    def is_bookable(self) -> bool:
        return self.booking_open and self.seats_available > 0

    @classmethod
    def from_dict(cls, data: dict) -> "Showtime":
        return cls(
            showtime_id=str(data["showtime_id"]),
            movie=data["movie"],
            theater=data["theater"],
            city=data["city"],
            starts_at=datetime.fromisoformat(data["starts_at"]),
            seats_available=int(data.get("seats_available", 0)),
            booking_open=bool(data.get("booking_open", False)),
            price=data.get("price"),
            booking_url=data.get("booking_url"),
        )


@dataclass
class Subscription:
    """A user's request to be notified about a movie."""

    movie: str
    city: str
    channel: str  # "console", "email", "webhook" or "whatsapp"
    target: str  # email address / webhook URL / phone number / display name
    theater: Optional[str] = None
    min_seats: int = 1
    subscription_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def matches(self, show: Showtime) -> bool:
        if not name_matches(self.movie, show.movie):
            return False
        if not name_matches(self.city, show.city):
            return False
        if self.theater and not name_matches(self.theater, show.theater):
            return False
        return show.is_bookable and show.seats_available >= self.min_seats

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Subscription":
        return cls(**data)
