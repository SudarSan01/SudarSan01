import tempfile
import os
import unittest
import urllib.parse
from unittest import mock
from datetime import datetime
from pathlib import Path

from movie_notifier.cli import main
from movie_notifier.notifiers import WhatsAppNotifier, get_notifier
from movie_notifier.models import Showtime, Subscription
from movie_notifier.providers import JsonFileProvider, ShowtimeProvider
from movie_notifier.store import Store
from movie_notifier.watcher import Watcher

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_showtimes.json"


def make_show(**overrides):
    base = dict(
        showtime_id="s1",
        movie="Dune: Part Three",
        theater="PVR Grand Mall",
        city="Chennai",
        starts_at=datetime(2026, 12, 18, 19, 30),
        seats_available=10,
        booking_open=True,
    )
    base.update(overrides)
    return Showtime(**base)


class StaticProvider(ShowtimeProvider):
    def __init__(self, shows):
        self.shows = shows

    def fetch(self):
        return list(self.shows)


class RecordingNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, sub, show):
        if self.fail:
            raise RuntimeError("boom")
        self.sent.append((sub.subscription_id, show.showtime_id))


class SubscriptionMatchTests(unittest.TestCase):
    def setUp(self):
        self.sub = Subscription(movie="dune: part three", city="CHENNAI", channel="console", target="me")

    def test_matches_case_insensitively(self):
        self.assertTrue(self.sub.matches(make_show()))

    def test_requires_booking_open(self):
        self.assertFalse(self.sub.matches(make_show(booking_open=False)))

    def test_respects_min_seats(self):
        self.sub.min_seats = 20
        self.assertFalse(self.sub.matches(make_show(seats_available=10)))

    def test_theater_filter(self):
        self.sub.theater = "INOX Marina"
        self.assertFalse(self.sub.matches(make_show()))

    def test_other_city_does_not_match(self):
        self.assertFalse(self.sub.matches(make_show(city="Mumbai")))


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmp.name) / "state.json"
        self.store = Store(self.store_path)
        self.sub = self.store.add(
            Subscription(movie="Dune: Part Three", city="Chennai", channel="console", target="me")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_notifies_once_per_showtime(self):
        notifier = RecordingNotifier()
        watcher = Watcher(StaticProvider([make_show()]), self.store, lambda _: notifier)
        self.assertEqual(len(watcher.check_once()), 1)
        self.assertEqual(len(watcher.check_once()), 0)
        self.assertEqual(notifier.sent, [(self.sub.subscription_id, "s1")])

    def test_dedupe_survives_reload(self):
        notifier = RecordingNotifier()
        Watcher(StaticProvider([make_show()]), self.store, lambda _: notifier).check_once()
        reloaded = Store(self.store_path)
        self.assertEqual(Watcher(StaticProvider([make_show()]), reloaded, lambda _: notifier).check_once(), [])

    def test_failed_delivery_is_retried(self):
        watcher = Watcher(StaticProvider([make_show()]), self.store, lambda _: RecordingNotifier(fail=True))
        with self.assertLogs("movie_notifier.watcher", level="ERROR"):
            self.assertEqual(watcher.check_once(), [])
        ok = RecordingNotifier()
        watcher.notifier_factory = lambda _: ok
        self.assertEqual(len(watcher.check_once()), 1)

    def test_sample_file_provider(self):
        shows = JsonFileProvider(SAMPLE).fetch()
        notifier = RecordingNotifier()
        Watcher(StaticProvider(shows), self.store, lambda _: notifier).check_once()
        self.assertEqual([s for _, s in notifier.sent], ["pvr-chn-1001"])


class WhatsAppNotifierTests(unittest.TestCase):
    def _send(self, target, env):
        sub = Subscription(movie="Dune: Part Three", city="Chennai", channel="whatsapp", target=target)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("movie_notifier.notifiers.urllib.request.urlopen") as urlopen:
            get_notifier("whatsapp").send(sub, make_show())
        url = urlopen.call_args[0][0]
        self.assertTrue(url.startswith(WhatsAppNotifier.API_URL + "?"))
        return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    def test_uses_env_api_key(self):
        params = self._send("+919876543210", {"CALLMEBOT_API_KEY": "123456"})
        self.assertEqual(params["phone"], ["+919876543210"])
        self.assertEqual(params["apikey"], ["123456"])
        self.assertIn("Dune: Part Three", params["text"][0])

    def test_per_target_api_key_overrides_env(self):
        params = self._send("+919876543210:999", {"CALLMEBOT_API_KEY": "123456"})
        self.assertEqual(params["phone"], ["+919876543210"])
        self.assertEqual(params["apikey"], ["999"])

    def test_missing_api_key_raises(self):
        sub = Subscription(movie="x", city="y", channel="whatsapp", target="+919876543210")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                WhatsAppNotifier().send(sub, make_show())


class CliTests(unittest.TestCase):
    def test_subscribe_list_unsubscribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "state.json")
            self.assertEqual(main(["--store", state, "subscribe", "--movie", "Dune: Part Three",
                                   "--city", "Chennai", "--target", "me"]), 0)
            sub_id = Store(state).subscriptions[0].subscription_id
            self.assertEqual(main(["--store", state, "check", "--source", str(SAMPLE)]), 0)
            self.assertEqual(main(["--store", state, "unsubscribe", sub_id]), 0)
            self.assertEqual(Store(state).subscriptions, [])
            self.assertEqual(main(["--store", state, "unsubscribe", sub_id]), 1)


if __name__ == "__main__":
    unittest.main()
