# Family Bill Tracker

One shared list of the household's bills and renewals (electricity, rent, recharges, insurance,
vehicle PUC, licence renewals) with WhatsApp reminders before each due date.

- **Phone-friendly web app.** Everyone in the family opens it from their phone's browser over home Wi-Fi.
- **Mark paid, move on.** Marking a bill paid records who paid, when and how much, then moves the bill to its
  next due date: monthly, quarterly, every 28 days, yearly, every 20 years or one-time.
- **WhatsApp reminders** through [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) (free).
  Everyone gets one combined message a day listing what is coming up and what is overdue.
- **Sensible defaults.** Most bills are reminded 7, 3 and 1 days before and on the day. Insurance, PUC, licence and
  tax renewals start 30 days ahead. Overdue bills get a reminder every day until someone marks them paid.
- **Runs on a home PC or Raspberry Pi** with SQLite. Flask is the only dependency.

## Set up

```bash
cd bill-tracker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

export BILL_TRACKER_PASSWORD='choose-a-household-password'   # optional, see below
.venv/bin/python -m bill_tracker serve
```

Open `http://<computer's IP>:8000` on any phone on the same Wi-Fi (find the IP with `hostname -I`).
Then:

1. **Family:** add each person with their WhatsApp number in international format (`+919876543210`)
   and their CallMeBot key (see below). Tap **Send test** to check it works.
2. **+ Add bill:** add each bill with its next due date and how often it repeats.

Tip: on the phone, use the browser's "Add to Home screen" so it opens like an app.

### Getting each person's CallMeBot key

CallMeBot gives one free API key per WhatsApp number, so each family member does this once on their own phone:

1. Save **+34 644 51 95 23** as a contact (check the CallMeBot page above in case the number has changed).
2. Send it this WhatsApp message: `I allow callmebot to send me messages`
3. It replies with an API key. Enter it on the Family page next to their number.

CallMeBot is a free, unofficial service, so a message can occasionally be delayed. Failed sends are retried on the next run.

## Daily reminders (cron)

Reminders are sent by `python -m bill_tracker remind`. Run it once a day with cron (`crontab -e`):

```cron
# 8:00 every morning
0 8 * * * cd /home/pi/SudarSan01/bill-tracker && BILL_TRACKER_URL=http://192.168.1.20:8000/ .venv/bin/python -m bill_tracker remind >> remind.log 2>&1
```

- `BILL_TRACKER_URL` is optional. It adds a "Mark paid" link to the bottom of each message.
- Each reminder stage goes to each person once. If the computer was off on a reminder day, the next run sends
  the latest stage it missed.
- Overdue bills are reminded every day until marked paid.
- Make sure the computer's time zone is right (`timedatectl set-timezone Asia/Kolkata`).

Try it without sending anything:

```bash
.venv/bin/python -m bill_tracker remind --dry-run
.venv/bin/python -m bill_tracker remind --dry-run --today 2026-11-01   # pretend it's another day
```

Example message:

```
🔔 Bill reminders · Thu 08 Oct

⚠️ ⚡ TNEB electricity · ₹1,240 · OVERDUE by 3 days (Mon 05 Oct)
    Ref 04-123-456 · Appa
🟠 📱 Jio recharge · ₹349 · due tomorrow
🟡 🛡️ Car insurance · ₹14,250 · due in 25 days (Mon 02 Nov)
    Ref TN09 AB 1234

Mark paid: http://192.168.1.20:8000/
```

## Start the web app at boot (Raspberry Pi / Linux)

Create `/etc/systemd/system/bill-tracker.service`:

```ini
[Unit]
Description=Family Bill Tracker
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/SudarSan01/bill-tracker
Environment=BILL_TRACKER_PASSWORD=choose-a-household-password
ExecStart=/home/pi/SudarSan01/bill-tracker/.venv/bin/python -m bill_tracker serve
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then run `sudo systemctl enable --now bill-tracker`.

## Security notes

- Set `BILL_TRACKER_PASSWORD` so only the family can open the app. Without it, anyone on your Wi-Fi can.
  A login lasts 180 days on each phone.
- The app is built for a home network. Don't expose port 8000 to the internet directly.
- Everything, including CallMeBot keys, is stored in `bill_tracker.db`. Back up that one file
  (e.g. `cp bill_tracker.db bill_tracker.backup.db`). Use `--db PATH` or `BILL_TRACKER_DB` to keep it elsewhere.

## Command line

The same database can be managed from the terminal:

```bash
python -m bill_tracker add-member Appa --phone +919876543210 --key 123456
python -m bill_tracker add-bill "TNEB electricity" --category electricity --due 2026-10-15 --amount 1240 --every 2 --owner Appa
python -m bill_tracker add-bill "Jio recharge" --category mobile --due 2026-10-20 --every 28 --unit day
python -m bill_tracker add-bill "Car insurance" --category insurance --due 2027-03-02 --unit year --reference "TN09 AB 1234"
python -m bill_tracker list
python -m bill_tracker pay 1 --by Appa --amount 1310
```

Categories: `electricity rent mobile internet water gas insurance puc licence tax emi school subscription other`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```
