"""Matches showtimes against subscriptions and dispatches notifications."""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Tuple

from .models import Showtime, Subscription
from .notifiers import Notifier, get_notifier
from .providers import ShowtimeProvider
from .store import Store

log = logging.getLogger(__name__)


class Watcher:
    def __init__(
        self,
        provider: ShowtimeProvider,
        store: Store,
        notifier_factory: Callable[[str], Notifier] = get_notifier,
    ):
        self.provider = provider
        self.store = store
        self.notifier_factory = notifier_factory

    def check_once(self) -> List[Tuple[Subscription, Showtime]]:
        """Run one check; returns the (subscription, showtime) pairs notified."""
        showtimes = self.provider.fetch()
        delivered = []
        for sub in self.store.subscriptions:
            for show in showtimes:
                key = Store.sent_key(sub.subscription_id, show.showtime_id)
                if key in self.store.sent or not sub.matches(show):
                    continue
                try:
                    self.notifier_factory(sub.channel).send(sub, show)
                except Exception as exc:  # keep going; retry on the next check
                    log.error("Failed to notify %s via %s: %s", sub.target, sub.channel, exc)
                    continue
                self.store.sent.add(key)
                delivered.append((sub, show))
        if delivered:
            self.store.save()
        return delivered

    def run_forever(self, interval: float = 300.0) -> None:
        log.info("Watching for tickets every %s seconds (Ctrl+C to stop)", interval)
        while True:
            try:
                count = len(self.check_once())
                log.info("Check complete: %d notification(s) sent", count)
            except Exception as exc:
                log.error("Check failed: %s", exc)
            time.sleep(interval)
