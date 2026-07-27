"""SQLite storage for preferences and the 'already seen' dog log."""
import json
import os
import sqlite3
from pathlib import Path

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
        # seed defaults if empty
        cur = conn.execute("SELECT COUNT(*) AS n FROM prefs")
        if cur.fetchone()["n"] == 0:
            for k, v in DEFAULT_PREFS.items():
                conn.execute("INSERT INTO prefs(key, value) VALUES(?, ?)", (k, json.dumps(v)))


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
            "first_seen) VALUES(?, ?, ?, ?, 1, ?)",
            [(d.id, d.source, d.name, d.url, today_iso) for d in dogs],
        )
    return first_seen_map(d.id for d in dogs)


def forget_missing(current_ids) -> int:
    """Drop dogs no rescue lists any more — they've been adopted or pulled.

    Without this the table grows forever and a dog relisted months later would
    be filed under its original date instead of reading as new.
    """
    current = set(current_ids)
    with connect() as conn:
        rows = conn.execute("SELECT dog_id FROM seen_dogs").fetchall()
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


def add_subscriber(email: str):
    with connect() as conn:
        conn.execute(
            "INSERT INTO subscribers(email) VALUES(?) "
            "ON CONFLICT(email) DO UPDATE SET active = 1",
            (email,),
        )


def list_subscribers():
    with connect() as conn:
        rows = conn.execute(
            "SELECT email FROM subscribers WHERE active = 1 ORDER BY created"
        ).fetchall()
    return [r["email"] for r in rows]


if __name__ == "__main__":
    init_db()
    print("DB initialized at", DB_PATH)
