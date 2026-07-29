"""Mirrors the subscribers table to a Google Sheet, as an offsite backup.

The sheet is a mirror, never a store: SQLite on the Fly volume remains the
source of truth, and every sync POSTs the FULL table to a Google Apps Script
webhook (SHEET_WEBHOOK_URL) that rewrites the sheet from scratch. Sending
everything each time means a missed webhook heals on the next sync — no
append/dedup bookkeeping on either side — and the table is small enough that
this stays cheap for years.

Unset SHEET_WEBHOOK_URL disables the mirror entirely. The URL is the secret:
anyone holding it can overwrite the sheet, so it lives in Fly secrets, not in
the repo.
"""

import os

import requests

import cities
import db


def configured() -> bool:
    return bool(os.getenv("SHEET_WEBHOOK_URL"))


def sync_subscribers():
    """Push the whole subscribers table (active and not) to the sheet.

    Raises on failure — callers decide whether that matters; the web app fires
    this from a daemon thread and the nightly run wraps it in try/except.

    Each row now carries its city, and the payload carries the full set of
    cities the sheet should have a tab for. The list matters for a case that is
    otherwise a silent bug: a city whose subscribers all leave sends no rows at
    all, so a script iterating only the rows it received would leave that tab
    holding stale addresses forever.

    The live Apps Script (see sheet_webhook.gs, which is a reference copy — the
    deployed code lives inside the spreadsheet) reads only `email`, `active` and
    `created` and writes them all to the first tab. It ignores the extra field
    and the extra key, so shipping this changes nothing until a human pastes the
    per-tab version.
    """
    url = os.environ["SHEET_WEBHOOK_URL"]
    with db.connect() as conn:
        # LEFT JOIN, not JOIN: consent lives on `subscribers`, so an address
        # somehow missing its city row must still reach the backup. An inner join
        # would silently drop it from the only offsite copy of the list.
        rows = conn.execute(
            "SELECT s.email, s.active, s.created, COALESCE(c.city, ?) AS city "
            "FROM subscribers s "
            "LEFT JOIN subscriber_cities c ON c.email = s.email "
            "ORDER BY city, s.created",
            (cities.DEFAULT_CITY,),
        ).fetchall()
    rows = [dict(r) for r in rows]
    # Live cities plus any city actually present, so a tab is never created for a
    # city that has not opened yet and never missed for one that has people in it.
    tabs = sorted(set(cities.live_codes()) | {r["city"] for r in rows})
    # Apps Script answers through a 302 to script.googleusercontent.com;
    # requests follows it, and the final body carries the JSON status.
    resp = requests.post(
        url,
        json={"subscribers": rows, "cities": tabs},
        timeout=30,
    )
    resp.raise_for_status()
