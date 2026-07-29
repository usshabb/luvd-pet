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

import db


def configured() -> bool:
    return bool(os.getenv("SHEET_WEBHOOK_URL"))


def sync_subscribers():
    """Push the whole subscribers table (active and not) to the sheet.

    Raises on failure — callers decide whether that matters; the web app fires
    this from a daemon thread and the nightly run wraps it in try/except.
    """
    url = os.environ["SHEET_WEBHOOK_URL"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT email, active, created FROM subscribers ORDER BY created"
        ).fetchall()
    # Apps Script answers through a 302 to script.googleusercontent.com;
    # requests follows it, and the final body carries the JSON status.
    resp = requests.post(
        url,
        json={"subscribers": [dict(r) for r in rows]},
        timeout=30,
    )
    resp.raise_for_status()
