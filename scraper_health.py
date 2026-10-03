"""Persistent scraper checks and an independent, throttled operator watchdog.

No subscriber mail. Run --watch beside the scheduler so a hung/crashed job can
be noticed even while the web process continues serving the previous roster.
An external monitor should also poll /health/scrapers to detect a whole outage.
"""
from contextlib import contextmanager
import json
import os
import sqlite3
import time

import cities
import db

STALE_SECONDS = 45 * 60
ALERT_INTERVAL = 6 * 60 * 60


@contextmanager
def _connect():
    conn = sqlite3.connect(db.DB_PATH.with_suffix(".health.db"), timeout=40)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS scraper_health ('
                 'city TEXT PRIMARY KEY, checked REAL, published REAL, failures TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS scraper_alerts ('
                 'key TEXT PRIMARY KEY, sent REAL NOT NULL)')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def checked(city, failures, now=None):
    with _connect() as conn:
        conn.execute('INSERT INTO scraper_health(city, checked, failures) VALUES (?, ?, ?) '
                     'ON CONFLICT(city) DO UPDATE SET checked=excluded.checked, '
                     'failures=excluded.failures',
                     (city, time.time() if now is None else now, json.dumps(failures)))


def published(city, now=None):
    with _connect() as conn:
        conn.execute('UPDATE scraper_health SET published=? WHERE city=?',
                     (time.time() if now is None else now, city))


def status(now=None):
    now = time.time() if now is None else now
    with _connect() as conn:
        rows = {r['city']: dict(r) for r in conn.execute('SELECT * FROM scraper_health')}
    result = {}
    for city in cities.live_codes():
        row = rows.get(city, {})
        checked_at = row.get('checked')
        published_at = row.get('published')
        failures = json.loads(row.get('failures') or '[]')
        stale = not checked_at or not published_at or now - min(checked_at, published_at) > STALE_SECONDS
        result[city] = {'ok': not stale and not failures, 'stale': stale,
                        'checked': checked_at, 'published': published_at,
                        'failed_sources': len(failures)}
    import emailer
    alerts_configured = bool((os.getenv('ALERT_EMAIL') or os.getenv('OPERATOR_EMAIL'))
                             and emailer.email_configured())
    return {'ok': all(r['ok'] for r in result.values()), 'cities': result,
            'alerts_configured': alerts_configured}


def alert(subject, body, key=None):
    """At most one successful notification per issue every six hours."""
    import emailer
    recipient = os.getenv('ALERT_EMAIL') or os.getenv('OPERATOR_EMAIL')
    if not recipient or not emailer.email_configured():
        print('  (operator alert not configured)', flush=True)
        return False
    key = key or subject
    now = time.time()
    # Serialize check/send/save so the scheduler and watchdog cannot double-send.
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT sent FROM scraper_alerts WHERE key=?', (key,)).fetchone()
        if previous and now - previous['sent'] < ALERT_INTERVAL:
            return False
        try:
            emailer.send_email(recipient, subject, text_body=body)
        except Exception as exc:
            print(f'  operator alert failed: {type(exc).__name__}', flush=True)
            return False
        conn.execute('INSERT INTO scraper_alerts VALUES (?, ?) '
                     'ON CONFLICT(key) DO UPDATE SET sent=excluded.sent', (key, now))
    return True


def watchdog_once(now=None, started=0):
    now = time.time() if now is None else now
    snapshot = status(now)
    for city, result in snapshot['cities'].items():
        if result['ok']:
            with _connect() as conn:
                conn.execute('DELETE FROM scraper_alerts WHERE key=?', ('health:' + city,))
            continue
        if (not result['published'] and not result['failed_sources']
                and now - started < STALE_SECONDS):
            # A city can finish checking before the combined city pages publish.
            # Keep the initial grace period through that intermediate state.
            # Real source failures and already-published stale data still alert.
            continue
        print(f'scraper health: {city}: {json.dumps(result)}', flush=True)
        alert(f'LUVD {city}: listings need attention',
              f'{city} scraper health: {json.dumps(result)}\n'
              'Check the scraper logs. Existing listings may be retained from an earlier run.',
              key='health:' + city)
    return snapshot


def watch():
    started = time.time()
    while True:
        try:
            watchdog_once(started=started)
        except Exception as exc:
            print(f'scraper watchdog failed: {type(exc).__name__}: {exc}', flush=True)
        time.sleep(300)


if __name__ == '__main__':
    import sys
    if '--watch' in sys.argv:
        watch()
    else:
        print(json.dumps(status(), indent=2))
