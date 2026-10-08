"""Command-line interface.

Examples:
    python -m movie_notifier subscribe --movie "Dune: Part Three" --city Chennai \
        --channel email --target you@example.com
    python -m movie_notifier list
    python -m movie_notifier check --source data/sample_showtimes.json
    python -m movie_notifier watch --source https://example.com/showtimes.json --interval 120
"""

from __future__ import annotations

import argparse
import logging
import sys

from .models import Subscription
from .notifiers import NOTIFIERS
from .providers import provider_from_source
from .store import Store
from .watcher import Watcher

DEFAULT_STORE = "notifier_state.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="movie_notifier", description="Movie ticket notifications")
    p.add_argument("--store", default=DEFAULT_STORE, help="Path to state file")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("subscribe", help="Get notified when tickets open for a movie")
    s.add_argument("--movie", required=True)
    s.add_argument("--city", required=True)
    s.add_argument("--theater", help="Restrict to a single theater")
    s.add_argument("--min-seats", type=int, default=1)
    s.add_argument("--channel", choices=sorted(NOTIFIERS), default="console")
    s.add_argument("--target", required=True, help="Email address, webhook URL, WhatsApp number or name")

    sub.add_parser("list", help="List subscriptions")

    u = sub.add_parser("unsubscribe", help="Remove a subscription")
    u.add_argument("subscription_id")

    for name, help_text in (("check", "Check once"), ("watch", "Check repeatedly")):
        c = sub.add_parser(name, help=help_text)
        c.add_argument("--source", required=True, help="Showtimes JSON file path or URL")
        if name == "watch":
            c.add_argument("--interval", type=float, default=300.0, help="Seconds between checks")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(args.store)

    if args.command == "subscribe":
        if args.min_seats < 1:
            print("--min-seats must be at least 1", file=sys.stderr)
            return 2
        sub = store.add(
            Subscription(
                movie=args.movie,
                city=args.city,
                theater=args.theater,
                min_seats=args.min_seats,
                channel=args.channel,
                target=args.target,
            )
        )
        print(f"Subscribed ({sub.subscription_id}): {sub.movie} in {sub.city} via {sub.channel}")
    elif args.command == "list":
        if not store.subscriptions:
            print("No subscriptions.")
        for s in store.subscriptions:
            where = f"{s.theater}, {s.city}" if s.theater else s.city
            print(f"{s.subscription_id}  {s.movie}  @ {where}  min_seats={s.min_seats}  "
                  f"{s.channel} -> {s.target}")
    elif args.command == "unsubscribe":
        if not store.remove(args.subscription_id):
            print(f"No subscription with id {args.subscription_id}", file=sys.stderr)
            return 1
        print(f"Unsubscribed {args.subscription_id}")
    elif args.command == "check":
        sent = Watcher(provider_from_source(args.source), store).check_once()
        print(f"{len(sent)} notification(s) sent.")
    elif args.command == "watch":
        try:
            Watcher(provider_from_source(args.source), store).run_forever(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0
