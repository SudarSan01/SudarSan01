# Movie Ticket Notifications

A small Python service that watches movie showtimes and notifies you when
ticket booking opens (and enough seats are available) for the movies you care about.

- **Subscriptions** – movie + city, optionally a specific theater and a minimum seat count
- **Channels** – console, email (SMTP) or webhook (Slack/Discord compatible)
- **Sources** – a local JSON file or any HTTP endpoint returning the same JSON shape
- **No duplicates** – each subscription is notified once per showtime; failed deliveries are retried on the next check
- **No dependencies** – Python 3.9+ standard library only

## Quick start

```bash
cd movie-ticket-notifications

# 1. Subscribe
python -m movie_notifier subscribe --movie "Dune: Part Three" --city Chennai --target "Sudarsan"

# 2. Check the sample showtimes once
python -m movie_notifier check --source data/sample_showtimes.json

# 3. Or keep watching (every 2 minutes)
python -m movie_notifier watch --source data/sample_showtimes.json --interval 120
```

Other commands:

```bash
python -m movie_notifier list
python -m movie_notifier unsubscribe <subscription_id>
python -m movie_notifier subscribe --movie "Avengers: Doomsday" --city Bengaluru \
    --theater "SPI Cinemas" --min-seats 2 --channel webhook --target https://hooks.slack.com/services/...
```

State (subscriptions and sent history) is stored in `notifier_state.json`; use `--store PATH` to change it.

## Showtime data format

```json
{
  "showtimes": [
    {
      "showtime_id": "pvr-chn-1001",
      "movie": "Dune: Part Three",
      "theater": "PVR Grand Mall",
      "city": "Chennai",
      "starts_at": "2026-12-18T19:30:00",
      "seats_available": 42,
      "booking_open": true,
      "price": 250.0,
      "booking_url": "https://example.com/book/pvr-chn-1001"
    }
  ]
}
```

`price` and `booking_url` are optional. To use a real ticketing site, implement a
`ShowtimeProvider` subclass in `movie_notifier/providers.py` that returns `Showtime` objects.

## Email configuration

| Variable        | Default      |
|-----------------|--------------|
| `SMTP_HOST`     | `localhost`  |
| `SMTP_PORT`     | `587`        |
| `SMTP_USER`     | –            |
| `SMTP_PASSWORD` | –            |
| `SMTP_FROM`     | `SMTP_USER`  |
| `SMTP_TLS`      | `true`       |

## Project layout

```
movie_notifier/
  models.py      Showtime and Subscription
  providers.py   Showtime sources (JSON file, HTTP)
  notifiers.py   Console, email and webhook channels
  store.py       JSON persistence for subscriptions and sent history
  watcher.py     Matching, de-duplication and the polling loop
  cli.py         Command-line interface
data/            Sample showtimes
tests/           Unit tests
```

## Tests

```bash
python -m unittest discover -s tests -v
```
