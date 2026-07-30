"""Monday morning: this week's in-person events, one email per city.

  .venv/bin/python check_events.py --city NYC --dry-run   # print, send nothing
  .venv/bin/python check_events.py --city NYC             # sync sheet, send

A run belongs to exactly one city: it syncs the shared events sheet, takes only
that city's events for the coming week, and mails only that city's subscribers.
An LA subscriber can never be told to turn up in Brooklyn.

**Why this is a separate email from the dog digest.** `check.py` returns before
mailing when nothing new arrived overnight (`if not new_today: return`), so
folding events into it would make them hostage to whether a dog turned up — and
a quiet Monday is exactly when an event matters most. Two sends, each skipping on
its own terms.

**The week** runs from the city's today through six days later, so a Monday run
covers Monday to Sunday. Events already past are not mailed, and an event further
out waits for the Monday it belongs to.

**Nothing to say means nothing sent.** No events for a city this week and the run
exits without mailing, the same rule the dog digest follows. "This week's events:
none" is worse than silence — it teaches people to ignore the next one.
"""
import argparse
import sys
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

import cities
import db
import events as events_sheet

# Monday to Sunday inclusive: today plus six more days.
WEEK_DAYS = 7


def run(city: str = None, dry_run: bool = False, skip_sync: bool = False) -> int:
    city = cities.canon(city) or cities.default_run_city()
    today = cities.today(city)
    end = today + timedelta(days=WEEK_DAYS - 1)

    # The sheet is shared by every city, so any city's run refreshes all of it.
    # Cheap, and it means a city whose own run failed still has current data for
    # the next one.
    if skip_sync:
        print("Sheet sync skipped.")
    elif not events_sheet.configured():
        print(f"{events_sheet.CSV_URL_ENV} is not set — using whatever is "
              f"already cached.")
    else:
        try:
            kept, problems = events_sheet.sync(today=today)
            print(f"Sheet synced: {kept} event(s) cached. "
                  f"Per city: {db.event_counts()}")
            for problem in problems:
                print(f"  !! sheet: {problem}")
        except Exception as e:
            # Never fatal. A sheet that will not load must leave the previous
            # week's cache in place rather than cancelling the email — the same
            # instinct as a failed scrape leaving the previous page served.
            print(f"  !! sheet sync failed ({type(e).__name__}: {e}) — "
                  f"falling back to the cache")

    week = db.events_between(city, today.isoformat(), end.isoformat())
    print(f"\n{city}: {len(week)} event(s) between {today} and {end}.")
    for ev in week:
        when = " ".join(x for x in (ev["starts_at"], ev["ends_at"]) if x)
        print(f"  {ev['starts_on']}  {when or '(no time)':<16} "
              f"{ev['title']}  · {ev['rescue']}")

    if not week:
        print("Nothing on this week — no email sent (by design).")
        return 0

    if dry_run:
        print("(dry run: no email sent)")
        return 0

    recipients = db.list_subscribers(city)
    prefs = db.get_prefs()
    if prefs.get("email") and prefs["email"] not in recipients:
        recipients.append(prefs["email"])
    if not recipients:
        print(f"No {city} subscribers yet — nothing to send.")
        return 0

    import emailer
    if not emailer.email_configured():
        print("MANDRILL_API_KEY unset — nothing sent.")
        return 0

    sent = 0
    for addr in recipients:
        try:
            emailer.send_events_digest(addr, week, city=city)
            sent += 1
        except Exception as e:
            print(f"  email to {addr} failed: {type(e).__name__}: {e}")
    print(f"Emailed {sent}/{len(recipients)} {city} subscriber(s).")
    return 0


def _main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", default=None, metavar="CODE",
                   help="which city's events and which city's list")
    p.add_argument("--dry-run", action="store_true",
                   help="sync and print, send nothing")
    p.add_argument("--skip-sync", action="store_true",
                   help="use the cached table, don't touch the sheet")
    args = p.parse_args(argv)
    if args.city and not cities.canon(args.city):
        p.error(f"unknown city {args.city!r}; known: {', '.join(cities.all_codes())}")
    db.init_db()
    return run(args.city, dry_run=args.dry_run, skip_sync=args.skip_sync)


if __name__ == "__main__":
    sys.exit(_main())
