"""Sources of showtime data."""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from .models import Showtime


class ShowtimeProvider(ABC):
    @abstractmethod
    def fetch(self) -> List[Showtime]:
        """Return the current list of showtimes."""


class JsonFileProvider(ShowtimeProvider):
    """Reads showtimes from a local JSON file (useful for demos and tests)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self) -> List[Showtime]:
        with self.path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        return [Showtime.from_dict(item) for item in payload.get("showtimes", [])]


class HttpJsonProvider(ShowtimeProvider):
    """Fetches showtimes from an HTTP endpoint returning {"showtimes": [...]}."""

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url
        self.timeout = timeout

    def fetch(self) -> List[Showtime]:
        with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return [Showtime.from_dict(item) for item in payload.get("showtimes", [])]


def provider_from_source(source: str) -> ShowtimeProvider:
    if source.startswith(("http://", "https://")):
        return HttpJsonProvider(source)
    return JsonFileProvider(source)
