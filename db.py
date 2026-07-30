"""SQLite storage for preferences and the 'already seen' dog log."""
import json
import os
import sqlite3
from pathlib import Path

import cities

# In production the database lives on a mounted volume — a container's own
# filesystem is wiped on every deploy, which would reset the whole timeline.
DB_PATH = Path(os.getenv("LUVD_DB") or (Path(__file__).parent / "dogfinder.db"))

DEFAULT_PREFS = {
    "email": "",
    "description": "",
    "breeds": "",        # comma-separated, optional
    "size": "",          # any | small | medium | large | xlarge
    "age": "",           # any | baby | young | adult | senior
    "zip": "",
    "radius_miles": 50,
    "active": 1,
}


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prefs (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS seen_dogs (
                dog_id TEXT PRIMARY KEY,   -- source-prefixed stable id, e.g. 'petfinder:12345'
                source TEXT NOT NULL,
                name TEXT,
                url TEXT,
                matched INTEGER DEFAULT 0, -- 1 if it matched and was emailed
                first_seen TEXT DEFAULT (datetime('now')),
                had_photo INTEGER DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS subscribers (
                email TEXT PRIMARY KEY,
                active INTEGER DEFAULT 1,
                created TEXT DEFAULT (datetime('now'))
            )"""
        )
        # Which city lists an address is on. A separate table rather than a
        # column on subscribers, because someone can legitimately want both New
        # York and Los Angeles — and because `subscribers` staying one row per
        # person is what add_subscriber()'s and deactivate_subscriber()'s
        # claim-by-write both depend on, and what the unsubscribe HMAC (an
        # address, nothing else) already assumes.
        #
        # `subscribers.active` remains the single global consent flag: it says
        # whether we may mail this person at all. These rows only say which
        # lists. So a city's digest is `active = 1 AND city = <that city>`, and
        # unsubscribing zeroes `active` and stops everything, exactly as the
        # link and the confirmation page have always promised.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS subscriber_cities (
                email TEXT NOT NULL,
                city TEXT NOT NULL,
                created TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (email, city)
            )"""
        )
        # A lifetime tally that only ever increments. Deriving the headline
        # number from SUM(dog_views) made it fall whenever a dog was pruned —
        # a counter that can go down is worse than no counter.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS counters (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS dog_views (
                dog_id TEXT PRIMARY KEY,
                views INTEGER NOT NULL DEFAULT 0,
                updated TEXT DEFAULT (datetime('now'))
            )"""
        )
        # Which species/city people actually pick. A "coming soon" that only
        # apologises teaches you nothing; this turns the dead end into demand
        # data for deciding what to build next.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS interest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                species TEXT NOT NULL,
                city TEXT NOT NULL,
                email TEXT,
                created TEXT DEFAULT (datetime('now'))
            )"""
        )
        # Outbound clicks — the number that actually shows a rescue what LUVD
        # is worth to them. Views mean interest; this means someone went.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS outbound (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dog_id TEXT NOT NULL,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,        -- apply | email | listing | share
                created TEXT DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_created "
            "ON outbound(created)"
        )
        # In-person adoption events, for the Monday digest. A cache of an
        # operator-maintained sheet, never a store: `replace_events()` rewrites
        # the whole table from the sheet every sync, the same bargain
        # sheet_sync.py makes in the other direction. So nothing here needs
        # append/dedup bookkeeping and a failed sync heals on the next one.
        #
        # Why a sheet rather than scrapers: of eleven rescues, one publishes
        # events in a form anything can read. Korean K9 runs them and their site
        # answers 403 to everyone, five have no events page at all, and Los
        # Angeles has effectively none — so a scraped digest would have been
        # wrong in a way subscribers could see. Scrapers can write into this
        # table later; they are an optimisation, not the source of truth.
        #
        # `uid` is the sheet's own identity for a row (city + rescue + date +
        # title, slugified) so the same event surviving an edit stays one row.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                uid TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                rescue TEXT NOT NULL,      -- display label, not a source key:
                                           -- an event may be run by a rescue
                                           -- LUVD does not scrape
                title TEXT NOT NULL,
                starts_on TEXT NOT NULL,   -- ISO date, local to the city
                starts_at TEXT,            -- "11 am", free text as written
                ends_at TEXT,
                location TEXT,
                address TEXT,
                url TEXT,
                note TEXT,
                synced TEXT DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_city_date "
            "ON events(city, starts_on)"
        )
        _migrate(conn)
        # seed defaults if empty
        cur = conn.execute("SELECT COUNT(*) AS n FROM prefs")
        if cur.fetchone()["n"] == 0:
            for k, v in DEFAULT_PREFS.items():
                conn.execute("INSERT INTO prefs(key, value) VALUES(?, ?)", (k, json.dumps(v)))


def _migrate(conn):
    """Additive column adds for databases created before the column existed.

    CREATE TABLE IF NOT EXISTS above only ever helps a fresh file — the
    production database on the Fly volume predates anything added here, so new
    columns need an explicit ALTER. Every step must be safe to run on every
    boot, and safe to lose a race with the other gunicorn worker doing the same
    thing, hence the duplicate-column tolerance.
    """
    for table, column, decl in (
        # When the signup confirmation was sent. NULL for anyone who subscribed
        # before welcome mail existed; they are treated as already welcomed so
        # the change can never mail the back catalogue.
        ("subscribers", "welcomed", "TEXT"),
        # When they left, and NULL while they are subscribed. A record, not the
        # lock — deactivate_subscriber() claims the unsubscribe with the
        # active = 1 test on the UPDATE itself, so this column existing or not
        # can never decide whether a goodbye goes out.
        ("subscribers", "unsubscribed", "TEXT"),
        # Which city's shelters this dog belongs to. This is what makes
        # forget_missing() safe to scope: it deletes everything it was not just
        # told about, so one city's nightly run, unscoped, would wipe the other
        # city's entire timeline — and every one of those dogs would come back
        # the next morning reading as new, mailing the whole roster to the whole
        # list. NULL means a row recorded before the column existed, which by
        # definition means New York; the backfill below settles it, and every
        # read COALESCEs so a half-migrated file still answers correctly.
        ("seen_dogs", "city", "TEXT"),
    ):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column in cols:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Anyone with no city at all subscribed before cities existed, which means
    # they did it when New York was the only city — so that is what they are.
    #
    # The NOT EXISTS is load-bearing and it is not the obvious way to write this.
    # `INSERT OR IGNORE ... SELECT email, 'NYC' FROM subscribers` looks
    # equivalent, and is idempotent in the sense that it inserts nothing new on a
    # second run — but it is idempotent about the wrong thing. It would give a
    # New York row to EVERY subscriber, on every boot, including someone who
    # signed up for Los Angeles alone. They would then be on the New York list
    # forever, and receive New York dogs, which is the exact failure this whole
    # change exists to prevent. Scoping it to "has no city yet" means it can only
    # ever fill a gap, never contradict a choice.
    #
    # It touches only subscriber_cities. `welcomed` is neither read nor written
    # here, and mail is only ever sent from a live HTTP request in app.py, so
    # this cannot re-welcome anybody however many times it runs. It is also safe
    # to lose the race with the other gunicorn worker running it at the same
    # moment, which is the contract every step above keeps.
    #
    # Inactive rows are included deliberately: someone who opted out and later
    # opts back in should land in the city they came from rather than in none,
    # and the sheet mirror carries inactive rows too, so they need a city to be
    # filed under.
    conn.execute(
        "INSERT OR IGNORE INTO subscriber_cities(email, city) "
        "SELECT s.email, ? FROM subscribers s WHERE NOT EXISTS ("
        "SELECT 1 FROM subscriber_cities c WHERE c.email = s.email)",
        (cities.DEFAULT_CITY,),
    )
    # Every dog recorded before the column existed is a New York dog. Idempotent
    # by the IS NULL test, and it MUST stay ahead of the first non-New-York
    # source being registered or it would stamp that city's dogs as New York.
    conn.execute(
        "UPDATE seen_dogs SET city = ? WHERE city IS NULL", (cities.DEFAULT_CITY,)
    )
    # Every per-city read of seen_dogs — the scoped delete, the floor that
    # guards it, the count behind it — filters on this.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_dogs_city ON seen_dogs(city)")


def get_prefs():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM prefs").fetchall()
    prefs = dict(DEFAULT_PREFS)
    for r in rows:
        prefs[r["key"]] = json.loads(r["value"])
    return prefs


def save_prefs(new_prefs: dict):
    with connect() as conn:
        for k, v in new_prefs.items():
            conn.execute(
                "INSERT INTO prefs(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v)),
            )


def already_seen(dog_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_dogs WHERE dog_id = ?", (dog_id,)
        ).fetchone()
    return row is not None


def first_seen_map(dog_ids) -> dict:
    """{dog_id: 'YYYY-MM-DD'} for ids we've already recorded."""
    ids = list(dog_ids)
    if not ids:
        return {}
    out = {}
    with connect() as conn:
        for i in range(0, len(ids), 400):     # stay under SQLite's var limit
            chunk = ids[i:i + 400]
            q = ("SELECT dog_id, date(first_seen) AS d FROM seen_dogs "
                 f"WHERE dog_id IN ({','.join('?' * len(chunk))})")
            for r in conn.execute(q, chunk):
                out[r["dog_id"]] = r["d"]
    return out


def record_seen(dogs, today_iso: str) -> dict:
    """Insert any dog we haven't recorded, then return the full first-seen map.

    The date is passed in rather than defaulted, because SQLite's datetime('now')
    is UTC — after 8pm Eastern that rolls to tomorrow and today's arrivals stop
    counting as new. Everything here runs on one New York clock.
    """
    with connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_dogs(dog_id, source, name, url, matched, "
            "first_seen, city) VALUES(?, ?, ?, ?, 1, ?, ?)",
            [(d.id, d.source, d.name, d.url, today_iso,
              getattr(d, "city", "") or cities.DEFAULT_CITY) for d in dogs],
        )
    return first_seen_map(d.id for d in dogs)


def count_seen(city: str = None) -> int:
    """How many dogs we have on record, optionally for one city.

    Read before a scoped delete, to compare what a run just found against what
    that city already has — see the floor in check.py.
    """
    with connect() as conn:
        if city is None:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM seen_dogs"
            ).fetchone()["n"]
        return conn.execute(
            "SELECT COUNT(*) AS n FROM seen_dogs WHERE COALESCE(city, ?) = ?",
            (cities.DEFAULT_CITY, cities.canon(city) or city),
        ).fetchone()["n"]


def forget_missing(current_ids, city: str = None) -> int:
    """Drop dogs no rescue lists any more — they've been adopted or pulled.

    Without this the table grows forever and a dog relisted months later would
    be filed under its original date instead of reading as new.

    `city` is the blast radius, and it is not optional in practice. This deletes
    every row it was NOT just handed, so a Los Angeles run that passed only its
    own ids would otherwise delete all ~230 New York dogs — losing every
    first_seen date the page is built around, and then re-inserting the lot
    tomorrow with tomorrow's date, which mails the entire roster to every
    subscriber as "new". Scoped, a run can only ever forget its own city.

    A NULL city counts as the default city: those are rows written before the
    column existed, so New York's run must still be able to prune them, and
    another city's run must not be able to touch them. The COALESCE says exactly
    that, and holds even if the backfill has not run yet.
    """
    current = set(current_ids)
    with connect() as conn:
        if city is None:
            rows = conn.execute("SELECT dog_id FROM seen_dogs").fetchall()
        else:
            rows = conn.execute(
                "SELECT dog_id FROM seen_dogs WHERE COALESCE(city, ?) = ?",
                (cities.DEFAULT_CITY, cities.canon(city) or city),
            ).fetchall()
        gone = [r["dog_id"] for r in rows if r["dog_id"] not in current]
        for i in range(0, len(gone), 400):
            chunk = gone[i:i + 400]
            conn.execute(
                f"DELETE FROM seen_dogs WHERE dog_id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
    return len(gone)


def photo_state(dog_ids) -> dict:
    """{dog_id: bool} — did this dog have a photo last time we looked?"""
    ids = list(dog_ids)
    if not ids:
        return {}
    out = {}
    with connect() as conn:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            q = ("SELECT dog_id, had_photo FROM seen_dogs "
                 f"WHERE dog_id IN ({','.join('?' * len(chunk))})")
            for r in conn.execute(q, chunk):
                out[r["dog_id"]] = bool(r["had_photo"])
    return out


def update_photo_state(dogs):
    with connect() as conn:
        conn.executemany(
            "UPDATE seen_dogs SET had_photo = ? WHERE dog_id = ?",
            [(1 if d.photos else 0, d.id) for d in dogs],
        )


def record_view(dog_id: str) -> int:
    """Count a real click into a dog's detail modal. Returns this dog's total."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO dog_views(dog_id, views) VALUES(?, 1) "
            "ON CONFLICT(dog_id) DO UPDATE SET views = views + 1, "
            "updated = datetime('now')",
            (dog_id,),
        )
        conn.execute(
            "INSERT INTO counters(key, value) VALUES('total_views', 1) "
            "ON CONFLICT(key) DO UPDATE SET value = value + 1"
        )
        row = conn.execute(
            "SELECT views FROM dog_views WHERE dog_id = ?", (dog_id,)
        ).fetchone()
    return row["views"] if row else 1


def record_outbound(dog_id: str, source: str, kind: str):
    with connect() as conn:
        conn.execute(
            "INSERT INTO outbound(dog_id, source, kind) VALUES(?, ?, ?)",
            (dog_id[:120], source[:40], kind[:16]),
        )
        conn.execute(
            "INSERT INTO counters(key, value) VALUES('total_outbound', 1) "
            "ON CONFLICT(key) DO UPDATE SET value = value + 1"
        )


def weekly_report(days: int = 7) -> dict:
    """Per-rescue activity for the last N days, for the operator digest."""
    since = f"-{int(days)} days"
    with connect() as conn:
        rescues = {}
        for r in conn.execute(
            "SELECT source, COUNT(*) n FROM seen_dogs GROUP BY source"
        ):
            rescues[r["source"]] = {"source": r["source"], "dogs": r["n"],
                                    "views": 0, "clicks": 0, "by_kind": {}}

        # Views are lifetime per dog; join to attribute them to a rescue.
        for r in conn.execute(
            "SELECT s.source, COALESCE(SUM(v.views),0) n FROM seen_dogs s "
            "LEFT JOIN dog_views v ON v.dog_id = s.dog_id GROUP BY s.source"
        ):
            rescues.setdefault(r["source"], {"source": r["source"], "dogs": 0,
                                             "views": 0, "clicks": 0,
                                             "by_kind": {}})
            rescues[r["source"]]["views"] = r["n"]

        for r in conn.execute(
            f"SELECT source, kind, COUNT(*) n FROM outbound "
            f"WHERE created >= datetime('now', '{since}') GROUP BY source, kind"
        ):
            e = rescues.setdefault(r["source"], {"source": r["source"],
                                                 "dogs": 0, "views": 0,
                                                 "clicks": 0, "by_kind": {}})
            e["clicks"] += r["n"]
            e["by_kind"][r["kind"]] = r["n"]

        top = [dict(r) for r in conn.execute(
            f"SELECT o.source, s.name, COUNT(*) n FROM outbound o "
            f"LEFT JOIN seen_dogs s ON s.dog_id = o.dog_id "
            f"WHERE o.created >= datetime('now', '{since}') "
            f"GROUP BY o.dog_id ORDER BY n DESC LIMIT 8"
        )]
        subs = conn.execute(
            f"SELECT COUNT(*) n FROM subscribers "
            f"WHERE created >= datetime('now', '{since}')"
        ).fetchone()["n"]

    return {"rescues": sorted(rescues.values(), key=lambda x: -x["clicks"]),
            "top_dogs": top, "new_subscribers": subs,
            "total_subscribers": len(list_subscribers()),
            "total_views": total_views()}


def total_views() -> int:
    """Lifetime views. Never decreases, survives dogs being pruned."""
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM counters WHERE key = 'total_views'"
        ).fetchone()
        if row:
            return row["value"]
        # First run after the upgrade: seed from whatever per-dog data exists.
        seed = conn.execute(
            "SELECT COALESCE(SUM(views), 0) AS n FROM dog_views"
        ).fetchone()["n"]
        conn.execute(
            "INSERT OR REPLACE INTO counters(key, value) VALUES('total_views', ?)",
            (seed,),
        )
        return seed


def get_views() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT dog_id, views FROM dog_views").fetchall()
    return {r["dog_id"]: r["views"] for r in rows}


def record_interest(species: str, city: str, email: str = None):
    with connect() as conn:
        conn.execute(
            "INSERT INTO interest(species, city, email) VALUES(?, ?, ?)",
            (species[:24], city[:40], (email or None)),
        )


def interest_counts():
    """What people are asking for, most-wanted first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT species, city, COUNT(*) n, "
            "SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) emails "
            "FROM interest GROUP BY species, city ORDER BY n DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def add_subscriber(email: str, city: str = None) -> bool:
    """Record a signup for one city. Returns True if this should be confirmed.

    True for an address we've never seen, and for someone who had unsubscribed
    and is now opting back in — they chose to hear from us again, so confirming
    it is right. False for an address that is already an active subscriber of
    this same city, so re-submitting the form (or double-clicking it) never
    sends a second welcome.

    The claim is made by the write itself rather than by a read-then-write, so
    two simultaneous posts of the same address can only produce one True: the
    INSERT is ignored for the loser, and the UPDATE's active = 0 test no longer
    holds once the winner has committed. Adding cities does not weaken that:
    `email` is still the primary key of `subscribers`, and the city row is a
    second, independent claim on `subscriber_cities`' composite key.

    The third case is new. An address that is already active and asks for a city
    it is NOT yet on is a real change worth confirming — they picked a city and
    deserve to hear that it worked — so it returns True and `welcomed` widens
    from "first ever contact" to "when we last confirmed a subscription". With
    one live city this branch is unreachable: everyone is already on New York.
    """
    email = email.strip().lower()
    city = cities.canon(city) or cities.DEFAULT_CITY
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO subscribers(email, active, welcomed) "
            "VALUES(?, 1, datetime('now'))",
            (email,),
        )
        fresh = bool(cur.rowcount)
        # The city row goes in either way, and its own rowcount is what
        # distinguishes "already on this list" from "adding a list".
        cur_city = conn.execute(
            "INSERT OR IGNORE INTO subscriber_cities(email, city) VALUES(?, ?)",
            (email, city),
        )
        new_city = bool(cur_city.rowcount)
        if fresh:
            return True
        # unsubscribed is cleared on the way back in: it means "when they left",
        # and a live subscriber carrying a leaving date would read as one.
        cur = conn.execute(
            "UPDATE subscribers SET active = 1, welcomed = datetime('now'), "
            "unsubscribed = NULL WHERE email = ? AND active = 0",
            (email,),
        )
        if cur.rowcount:
            return True
        if new_city:
            conn.execute(
                "UPDATE subscribers SET welcomed = datetime('now')"
                " WHERE email = ?",
                (email,),
            )
            return True
        return False


def deactivate_subscriber(email: str) -> bool:
    """Unsubscribe an address. Returns True if this call is the one that took
    them off the list — i.e. the row was active until now.

    That return is what makes the goodbye email arrive exactly once. Same shape
    as add_subscriber(): the claim is the write. The active = 1 test lives in
    the UPDATE, so of two clicks on the same link — or a client firing the
    one-click endpoint after the reader already used the footer link — only the
    first can come back with a row changed. A read-then-write would leave a gap
    between the check and the update wide enough for both to pass.

    False for an address that was already unsubscribed, and for one we have
    never seen. Both are unsubscribed by the time we answer, which is all the
    caller promised.
    """
    with connect() as conn:
        cur = conn.execute(
            "UPDATE subscribers SET active = 0, unsubscribed = datetime('now') "
            "WHERE email = ? AND active = 1",
            (email.strip().lower(),),
        )
        return bool(cur.rowcount)


def list_subscribers(city: str = None):
    """Active subscriber addresses; `city=None` means everyone, on any list.

    None being "everyone" is what keeps every pre-city caller correct — the
    weekly report's total and the /subscribers endpoint both mean people, not
    memberships. A city narrows it to that list, and it can only ever narrow:
    the composite primary key on subscriber_cities means one row per person per
    city, so nobody can appear twice and be mailed twice.

    An address with no city row at all still shows up in the unscoped answer.
    That is deliberate: consent lives on `subscribers`, so a missing city row
    must never look like a missing subscriber.
    """
    with connect() as conn:
        if city is None:
            rows = conn.execute(
                "SELECT email FROM subscribers WHERE active = 1 ORDER BY created"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.email FROM subscribers s "
                "JOIN subscriber_cities c ON c.email = s.email "
                "WHERE s.active = 1 AND c.city = ? ORDER BY s.created",
                (cities.canon(city) or city,),
            ).fetchall()
    return [r["email"] for r in rows]


def subscriber_cities(email: str):
    """Which city lists one address is on."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT city FROM subscriber_cities WHERE email = ? ORDER BY city",
            (email.strip().lower(),),
        ).fetchall()
    return [r["city"] for r in rows]


def replace_events(rows) -> int:
    """Rewrite the events table from the sheet. Returns the row count kept.

    Wholesale, inside one transaction, because the sheet is the source of truth
    and a partial table is worse than a stale one: an event deleted from the
    sheet has to disappear here too, or a cancelled event keeps being mailed
    out. Same reasoning as sheet_sync.py POSTing the whole subscriber table
    rather than a diff.

    Empty input is refused rather than obeyed. A sheet that fails to load, or
    loads as nothing because it was renamed or unshared, is indistinguishable
    from "no events" at this layer — and the safe reading of an unreadable
    sheet is "I don't know", not "cancel everything". The caller decides
    whether that is an error; the table keeps what it had.
    """
    rows = list(rows or [])
    if not rows:
        return 0
    with connect() as conn:
        conn.execute("DELETE FROM events")
        conn.executemany(
            "INSERT OR REPLACE INTO events(uid, city, rescue, title, starts_on,"
            " starts_at, ends_at, location, address, url, note)"
            " VALUES(:uid,:city,:rescue,:title,:starts_on,:starts_at,:ends_at,"
            ":location,:address,:url,:note)",
            rows,
        )
    return len(rows)


def events_between(city: str, start_iso: str, end_iso: str):
    """One city's events in a date window, soonest first.

    Inclusive of both ends: a week runs Monday to Sunday and an event on either
    boundary belongs to it. Scoped to a city for the same reason the digest is —
    an LA subscriber must never be told to turn up in Brooklyn.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE city = ? AND starts_on >= ? "
            "AND starts_on <= ? ORDER BY starts_on, rescue, title",
            (cities.canon(city) or city, start_iso, end_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def event_counts() -> dict:
    """{city: rows} — for the operator endpoints and a quick sanity check."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT city, COUNT(*) AS n FROM events GROUP BY city ORDER BY city"
        ).fetchall()
    return {r["city"]: r["n"] for r in rows}


def subscriber_city_counts() -> dict:
    """{city: active subscribers} — for the weekly report and quick checks."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.city, COUNT(*) AS n FROM subscriber_cities c "
            "JOIN subscribers s ON s.email = c.email "
            "WHERE s.active = 1 GROUP BY c.city ORDER BY c.city"
        ).fetchall()
    return {r["city"]: r["n"] for r in rows}


if __name__ == "__main__":
    init_db()
    print("DB initialized at", DB_PATH)
