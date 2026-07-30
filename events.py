"""In-person adoption events, read from an operator-maintained Google Sheet.

    .venv/bin/python events.py --print      # show what the sheet parses to
    .venv/bin/python events.py --sync       # parse it and cache it in SQLite

Why a sheet and not scrapers
----------------------------
A scan of all eleven rescues LUVD follows found exactly one — NYC Second Chance
— publishing events in a form anything can read. Korean K9 runs events and
answers 403 to every request, so their site can never be read. Muddy Paws and
Waggytail hide theirs behind an AddEvent widget. Five publish no events page at
all, and Los Angeles has effectively none. A scraped digest would therefore have
been confidently incomplete, which is worse than absent: the first subscriber who
knew about an event we left out would stop trusting the whole email.

A sheet inverts that. Whatever you learn — a rescue's newsletter, an Instagram
post, a scraper we add later — goes in one place, and the email is complete for
both cities from the first send. Scrapers can write into the same table when they
earn their keep; they are an optimisation, not the foundation.

The sheet
---------
``EVENTS_SHEET_CSV_URL`` is a Google Sheet published as CSV — the
``/export?format=csv&gid=...`` form, which needs no credentials because the URL
*is* the credential, exactly like ``SHEET_WEBHOOK_URL``. Unset it and events are
skipped entirely and nothing else changes.

Columns, matched case- and space-insensitively, so the sheet can be readable to
a human rather than shaped for a parser. Only ``city``, ``date`` and one of
``title``/``rescue`` are required:

    city | rescue | title | date | start | end | location | address | url | note

Dates are parsed forgivingly, because a person types them: "2026-08-01",
"8/1/2026", "Aug 1 2026" and "Saturday, August 1, 2026" all work. A row whose
date cannot be read is dropped and reported rather than guessed at — a wrong
date sends people to a place on a day nothing is happening.
"""
import argparse
import csv
import io
import os
import re
import sys
from datetime import date, datetime

import requests

import cities

CSV_URL_ENV = "EVENTS_SHEET_CSV_URL"
TIMEOUT = 30
USER_AGENT = "LUVD/1.0 (+https://luvd.com)"

# One header may be spelled several ways; first match wins. Keys are what the
# rest of the code uses, values are what a person might type.
_COLUMNS = {
    "city":     ("city", "market", "location city"),
    "rescue":   ("rescue", "organisation", "organization", "org", "shelter",
                 "host"),
    "title":    ("title", "event", "event name", "name", "what"),
    "date":     ("date", "day", "starts", "start date", "when"),
    "start":    ("start", "start time", "from", "time", "begins"),
    "end":      ("end", "end time", "to", "until", "ends"),
    "location": ("location", "venue", "place", "where"),
    "address":  ("address", "street", "addr"),
    "url":      ("url", "link", "more info", "rsvp"),
    "note":     ("note", "notes", "details", "description"),
}

_MONTHS = ("january february march april may june july august september "
           "october november december").split()

# An event a human has marked off rather than deleted. People edit a sheet by
# typing in it, not by removing rows — "CANCELLED" in the title or the notes is
# how a cancellation actually gets recorded — and mailing a few hundred people to
# an event that isn't happening is the worst thing this feature can do. Matched
# anywhere in the title or the note, both spellings, plus postponed and TBC:
# every one of them means "we are not sure this is on", and the instruction for
# that case is don't send.
_NOT_ON = re.compile(r"\b(cancel?led|canceled|cancelled|postponed|tbc|tba|"
                     r"to be confirmed|rain\s?date)\b", re.I)


def configured() -> bool:
    return bool(os.getenv(CSV_URL_ENV))


def _norm_header(text: str) -> str:
    return re.sub(r"[^a-z ]", "", (text or "").strip().lower()).strip()


def _map_headers(fieldnames) -> dict:
    """{our key: the sheet's actual column name}."""
    seen = {_norm_header(f): f for f in (fieldnames or []) if f}
    out = {}
    for key, spellings in _COLUMNS.items():
        for spelling in spellings:
            if spelling in seen:
                out[key] = seen[spelling]
                break
    return out


def parse_date(text: str, today: date = None):
    """A person's date, or None. Never guesses a year it wasn't given.

    A bare "Aug 1" is ambiguous — this year or next — and the wrong answer sends
    somebody out on a day nothing is happening, so it is refused rather than
    assumed. Every other common shape is accepted.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    # Drop a leading weekday: "Saturday, August 1, 2026"
    raw = re.sub(r"^\s*(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s*", "", raw,
                 flags=re.I)
    cleaned = raw.replace(",", " ").strip()

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
                "%B %d %Y", "%b %d %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(" ".join(cleaned.split()), fmt).date()
        except ValueError:
            continue

    # "August 1 2026" with an ordinal — "August 1st 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})$",
                 " ".join(cleaned.split()))
    if m:
        name = m.group(1).lower()
        month = next((i + 1 for i, mo in enumerate(_MONTHS)
                      if mo.startswith(name[:3])), None)
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                return None
    return None


def clean_time(text: str) -> str:
    """Tidy a typed time without reinterpreting it: "11AM" -> "11 am".

    Deliberately not parsed into a real time. These are read by a human in an
    email, the sheet may hold "11 am" or "11:30" or "doors at 11", and rewriting
    that into a timestamp would either lose what the rescue actually said or
    invent precision the sheet never had. Ordering uses the date alone.
    """
    t = " ".join((text or "").strip().split())
    if not t:
        return ""
    # "11AM", "11 A.M.", "2:30pm" -> "11 am", "11 am", "2:30 pm". The meridiem
    # is lowercased explicitly: a case-insensitive match captures whatever the
    # sheet typed, so echoing the group back gives "11 Am".
    return re.sub(
        r"(\d)\s*([ap])\.?\s*m\.?(?=\b|$)",
        lambda m: f"{m.group(1)} {m.group(2).lower()}m",
        t, flags=re.I)


def _uid(city: str, rescue: str, iso: str, title: str) -> str:
    """Stable identity for a row, so an edit updates rather than duplicates."""
    basis = "|".join((city, rescue.lower(), iso, title.lower()))
    return re.sub(r"[^a-z0-9|:-]+", "-", basis.lower()).strip("-")


def fetch_csv(url: str = None) -> str:
    url = url or os.getenv(CSV_URL_ENV) or ""
    if not url:
        raise RuntimeError(f"{CSV_URL_ENV} is not set")
    resp = requests.get(url, timeout=TIMEOUT,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    # A sheet that is not link-shared answers with Google's HTML sign-in page
    # and a 200, so the status code alone does not mean we got a sheet.
    text = resp.text
    if text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:400].lower():
        raise RuntimeError(
            "the sheet URL returned HTML, not CSV — it is probably not shared "
            "with 'anyone with the link'")
    return text


def parse(text: str, today: date = None):
    """(rows, problems) — rows ready for db.replace_events, and what was dropped.

    Problems are returned rather than raised so one bad row cannot cost the
    whole week's email, and are reported by the caller so they get fixed.
    """
    today = today or date.today()
    reader = csv.DictReader(io.StringIO(text))
    cols = _map_headers(reader.fieldnames)
    problems = []
    if "city" not in cols or "date" not in cols:
        got = ", ".join(f for f in (reader.fieldnames or []) if f) or "(none)"
        return [], [f"sheet needs at least 'city' and 'date' columns; got: {got}"]

    rows, seen = [], set()
    for n, raw in enumerate(reader, start=2):        # row 1 is the header
        def col(key):
            return (raw.get(cols[key]) or "").strip() if key in cols else ""

        city_raw = col("city")
        city = cities.canon(city_raw)
        title = col("title")
        rescue = col("rescue")
        if not any((city_raw, title, rescue, col("date"))):
            continue                                 # a blank spacer row
        if not city:
            problems.append(f"row {n}: unknown city {city_raw!r}")
            continue
        if not cities.is_live(city):
            problems.append(f"row {n}: {city} is not live yet")
            continue
        when = parse_date(col("date"), today)
        if not when:
            problems.append(f"row {n}: could not read the date "
                            f"{col('date')!r}")
            continue
        if not (title or rescue):
            problems.append(f"row {n}: needs a title or a rescue")
            continue

        marked_off = _NOT_ON.search(f"{title} {col('note')}")
        if marked_off:
            problems.append(f"row {n}: reads as {marked_off.group(0).lower()!r}, "
                            f"not sent")
            continue

        # Somewhere to go. An event with a day and no place is not something a
        # reader can act on, and telling several hundred people to turn up
        # without saying where is worse than not writing to them: they cannot go,
        # and the next email has already lost their attention. So a row missing
        # both a location and an address is treated as half-entered rather than
        # as an event, and reported so it gets finished.
        if not (col("location") or col("address")):
            problems.append(f"row {n}: no location or address, not sent")
            continue

        title = title or f"{rescue} adoption event"
        rescue = rescue or "LUVD"
        uid = _uid(city, rescue, when.isoformat(), title)
        if uid in seen:
            problems.append(f"row {n}: duplicate of an earlier row, skipped")
            continue
        seen.add(uid)
        rows.append({
            "uid": uid, "city": city, "rescue": rescue, "title": title,
            "starts_on": when.isoformat(),
            "starts_at": clean_time(col("start")),
            "ends_at": clean_time(col("end")),
            "location": col("location"), "address": col("address"),
            "url": col("url"), "note": col("note"),
        })
    return rows, problems


def sync(url: str = None, today: date = None):
    """Pull the sheet into SQLite. Returns (kept, problems)."""
    import db
    rows, problems = parse(fetch_csv(url), today)
    if not rows:
        return 0, problems or ["the sheet parsed to no usable rows"]
    return db.replace_events(rows), problems


def _main(argv=None):
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--print", action="store_true",
                   help="parse the sheet and print it; touches no database")
    p.add_argument("--sync", action="store_true", help="cache it in SQLite")
    p.add_argument("--url", default=None, help="override the sheet URL")
    args = p.parse_args(argv)

    if not (args.print or args.sync):
        p.error("choose --print or --sync")
    if not (args.url or configured()):
        print(f"{CSV_URL_ENV} is not set — nothing to read.")
        return 1

    rows, problems = parse(fetch_csv(args.url), date.today())
    for row in rows:
        when = row["starts_on"]
        clock = " ".join(x for x in (row["starts_at"],
                                     f"– {row['ends_at']}" if row["ends_at"]
                                     else "") if x)
        where = row["location"] or row["address"] or ""
        print(f"  {row['city']}  {when}  {clock or '(no time given)':<18} "
              f"{row['title']}  · {row['rescue']}" + (f"  · {where}" if where else ""))
    print(f"\n{len(rows)} event(s) parsed.")
    for problem in problems:
        print(f"  !! {problem}")
    if args.sync:
        import db
        db.init_db()
        kept = db.replace_events(rows)
        print(f"Cached {kept} event(s). Per city: {db.event_counts()}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
