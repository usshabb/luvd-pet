"""Two cities, simulated end to end, against the things that can actually hurt.

Run it:

    .venv/bin/python tests/test_multicity.py

No pytest, no new dependency — plain asserts and a runner at the bottom, because
the value here is that it runs before a deploy without anyone installing
anything.

What it is guarding, in order of how much damage it prevents:

1. `forget_missing()` deletes every row it was not just handed. One city's
   nightly run must not be able to delete the other city's history — and, worse
   than the deletion, the deleted dogs come back the next morning with the next
   morning's date, so `new_today` becomes the whole roster and every subscriber
   is mailed a digest announcing ~230 "new" dogs. So: row counts and specific
   ids before and after, and `first_seen` dates asserted explicitly.
2. The digest must be city-scoped on both sides — the dogs in it and the people
   it goes to.
3. The migration must be idempotent, must run against the schema that is in
   production right now rather than a fresh one, and must not touch `welcomed`.
4. Subscribing with no city must still work and land in New York; an unknown
   city must be refused rather than stored.
5. With one live city the nightly schedule must compute exactly what the old
   single-city shell loop computed.

The Los Angeles source here is a fake defined in this file. It is never
registered in `sources/registry.py`, so nothing in production can reach it.
"""
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cities                                                  # noqa: E402
import db                                                      # noqa: E402
from sources.base import Dog, Source                            # noqa: E402

FAILURES = []
TMP = Path(tempfile.mkdtemp(prefix="luvd-multicity-"))

# check.run() rebuilds the share card and the welcome montage, which write into
# the real public/ directory. A test must not touch the published site, so they
# are stubbed here rather than in each test — check.py imports them inside the
# function, so replacing the attribute is enough.
import montage                                                 # noqa: E402
import og_image                                                # noqa: E402

og_image.build = lambda *a, **k: "(share card stubbed by the test)"
montage.build = lambda *a, **k: "(montage stubbed by the test)"


# --------------------------------------------------------------------- helpers


def fresh_db(name="t.db"):
    """A database created by init_db(), i.e. the current schema."""
    path = TMP / name
    if path.exists():
        path.unlink()
    db.DB_PATH = path
    db.init_db()
    return path


def legacy_db(name="legacy.db"):
    """A database with the schema as it stands in production, pre-cities.

    Built with raw SQL rather than by calling init_db(), because the whole point
    is to migrate a file that does NOT already have the new table and column.
    `welcomed` and `unsubscribed` are here as ALTER-added columns, which is how
    they exist on the Fly volume.
    """
    path = TMP / name
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE seen_dogs (
            dog_id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT, url TEXT,
            matched INTEGER DEFAULT 0,
            first_seen TEXT DEFAULT (datetime('now')),
            had_photo INTEGER DEFAULT 0);
        CREATE TABLE subscribers (
            email TEXT PRIMARY KEY, active INTEGER DEFAULT 1,
            created TEXT DEFAULT (datetime('now')));
        CREATE TABLE counters (key TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE dog_views (dog_id TEXT PRIMARY KEY,
            views INTEGER NOT NULL DEFAULT 0,
            updated TEXT DEFAULT (datetime('now')));
        CREATE TABLE interest (id INTEGER PRIMARY KEY AUTOINCREMENT,
            species TEXT NOT NULL, city TEXT NOT NULL, email TEXT,
            created TEXT DEFAULT (datetime('now')));
        CREATE TABLE outbound (id INTEGER PRIMARY KEY AUTOINCREMENT,
            dog_id TEXT NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now')));
        ALTER TABLE subscribers ADD COLUMN welcomed TEXT;
        ALTER TABLE subscribers ADD COLUMN unsubscribed TEXT;
        """
    )
    conn.commit()
    conn.close()
    db.DB_PATH = path
    return path


def dog(source, ident, name, city=""):
    d = Dog(id=f"{source}:{ident}", name=name, source=source,
            source_label=f"{source.title()} Rescue",
            url=f"https://example.org/{source}/{ident}")
    d.photos = [f"https://example.org/{ident}.jpg"]
    d.breed = "Mixed Breed"
    d.city = city
    return d


NYC_DOGS = [dog("muddypaws", 1, "Aria", "NYC"),
            dog("muddypaws", 2, "Bo", "NYC"),
            dog("animalhaven", 3, "Cleo", "NYC")]
LA_DOGS = [dog("wagmor", 10, "Duke", "LA"),
           dog("wagmor", 11, "Ember", "LA")]


class FakeLASource(Source):
    """A Los Angeles rescue that exists only in this test file.

    Deliberately not in sources/registry.py: production must have no way to
    reach it, and a test that registered it would be testing a different app.
    """

    name = "wagmor"
    label = "Wagmor Rescue"
    priority = 20
    city = "LA"

    def __init__(self, dogs):
        self._dogs = dogs

    def fetch(self, prefs):
        return [d for d in self._dogs]


class FakeNYCSource(FakeLASource):
    name = "muddypaws"
    label = "Muddypaws Rescue"
    priority = 10
    city = "NYC"


def seed(dogs, city, when):
    """Record `dogs` for `city` with a known first_seen date."""
    db.record_seen(dogs, when)
    with db.connect() as conn:
        conn.execute("UPDATE seen_dogs SET first_seen = ? WHERE city = ?",
                     (when, city))


def rows(city=None):
    with db.connect() as conn:
        if city is None:
            r = conn.execute("SELECT dog_id, city, date(first_seen) d "
                             "FROM seen_dogs ORDER BY dog_id").fetchall()
        else:
            r = conn.execute("SELECT dog_id, city, date(first_seen) d "
                             "FROM seen_dogs WHERE city = ? ORDER BY dog_id",
                             (city,)).fetchall()
    return {x["dog_id"]: x["d"] for x in r}


def eq(label, got, want):
    if got == want:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}\n        got  {got!r}\n        want {want!r}")
        FAILURES.append(label)


# ----------------------------------------------------------------------- tests


def test_forget_missing_is_city_scoped():
    """An LA run must not delete NYC's rows, and vice versa."""
    fresh_db("forget.db")
    seed(NYC_DOGS, "NYC", "2026-07-01")
    seed(LA_DOGS, "LA", "2026-07-02")

    before = rows()
    eq("both cities recorded", len(before), 5)
    eq("NYC ids recorded", sorted(rows("NYC")),
       ["animalhaven:3", "muddypaws:1", "muddypaws:2"])
    eq("LA ids recorded", sorted(rows("LA")), ["wagmor:10", "wagmor:11"])

    # An LA run: it only knows about LA dogs, and one of them has gone.
    deleted = db.forget_missing([LA_DOGS[0].id], city="LA")
    eq("LA run deleted exactly its own missing dog", deleted, 1)
    eq("NYC rows untouched by the LA run", rows("NYC"),
       {"muddypaws:1": "2026-07-01", "muddypaws:2": "2026-07-01",
        "animalhaven:3": "2026-07-01"})
    eq("NYC row count untouched", len(rows("NYC")), 3)
    eq("LA now holds only the listed dog", sorted(rows("LA")), ["wagmor:10"])

    # And the other direction: an NYC run must not touch what's left of LA.
    deleted = db.forget_missing([d.id for d in NYC_DOGS[:2]], city="NYC")
    eq("NYC run deleted exactly its own missing dog", deleted, 1)
    eq("LA rows untouched by the NYC run", rows("LA"),
       {"wagmor:10": "2026-07-02"})


def test_first_seen_survives_the_other_citys_run():
    """The mass-mailing trigger: NYC's dates must not move when LA runs."""
    fresh_db("dates.db")
    seed(NYC_DOGS, "NYC", "2026-06-15")
    seed(LA_DOGS, "LA", "2026-07-20")
    nyc_before = rows("NYC")

    # A full LA run, twice, with LA's roster changing underneath it.
    db.record_seen(LA_DOGS, "2026-07-29")
    db.forget_missing([d.id for d in LA_DOGS], city="LA")
    db.record_seen([LA_DOGS[0]], "2026-07-29")
    db.forget_missing([LA_DOGS[0].id], city="LA")

    eq("NYC first_seen dates unchanged after two LA runs", rows("NYC"),
       nyc_before)
    eq("NYC dates are still June", sorted(set(rows("NYC").values())),
       ["2026-06-15"])
    # The specific failure this prevents: if NYC's rows had been deleted, the
    # next NYC run would re-insert them with today's date and mail the lot.
    seen = db.record_seen(NYC_DOGS, "2026-07-29")
    eq("a later NYC run does not re-date its dogs",
       sorted(set(seen.values())), ["2026-06-15"])


def test_record_seen_stamps_the_city():
    fresh_db("stamp.db")
    db.record_seen(NYC_DOGS + LA_DOGS, "2026-07-29")
    eq("cities stored per dog",
       {k: v for k, v in
        sorted((d["dog_id"], d["city"]) for d in _all_rows())},
       {"muddypaws:1": "NYC", "muddypaws:2": "NYC", "animalhaven:3": "NYC",
        "wagmor:10": "LA", "wagmor:11": "LA"})
    eq("count_seen is per city", (db.count_seen("NYC"), db.count_seen("LA"),
                                 db.count_seen()), (3, 2, 5))
    # A dog nobody stamped is New York, because everything that predates cities
    # is New York.
    db.record_seen([dog("mystery", 99, "Nobody")], "2026-07-29")
    eq("an unstamped dog defaults to NYC", db.count_seen("NYC"), 4)


def _all_rows():
    with db.connect() as conn:
        return [dict(r) for r in
                conn.execute("SELECT dog_id, city FROM seen_dogs")]


def test_collect_stamps_from_the_source():
    """No scraper sets a city; collect() does it from the source's own value."""
    import check
    fresh_db("collect.db")
    original = check.sources_for_city
    try:
        plain_la = [dog("wagmor", 10, "Duke"), dog("wagmor", 11, "Ember")]
        check.sources_for_city = lambda c: (
            [FakeLASource(plain_la)] if c == "LA" else [])
        dogs, failures = check.collect({}, "LA", verbose=False)
        eq("LA source's dogs come back", len(dogs), 2)
        eq("every dog stamped LA", sorted({d.city for d in dogs}), ["LA"])
        eq("no failures", failures, [])
    finally:
        check.sources_for_city = original

    eq("Source defaults to the default city", Source.city, cities.DEFAULT_CITY)
    from sources.registry import sources_for_city
    eq("no registered source claims a city that isn't live",
       sorted({s.city for s in sources_for_city("NYC")}), ["NYC"])


def test_digest_is_city_scoped():
    """NYC subscribers get only NYC dogs; LA subscribers only LA dogs."""
    import check
    import emailer
    fresh_db("digest.db")

    db.add_subscriber("nyc-only@example.com", "NYC")
    db.add_subscriber("la-only@example.com", "LA")
    db.add_subscriber("both@example.com", "NYC")
    db.add_subscriber("both@example.com", "LA")

    sent = []
    saved = (check.sources_for_city, emailer.send_digest, check.page.write,
             check.normalize, check.enrich, check._alert)
    try:
        check.sources_for_city = lambda c: (
            [FakeLASource(LA_DOGS)] if c == "LA" else [FakeNYCSource(NYC_DOGS)])
        emailer.send_digest = lambda addr, dogs, *a, **k: sent.append(
            (addr, sorted(d.id for d in dogs)))
        check.page.write = lambda pages, for_date=None: Path("/dev/null")
        check.normalize = lambda dogs: dogs
        check.enrich = lambda dogs: dogs
        check._alert = lambda *a, **k: None

        check.run(city="NYC")
        nyc_sent = sorted(sent)
        sent.clear()
        check.run(city="LA")
        la_sent = sorted(sent)
    finally:
        (check.sources_for_city, emailer.send_digest, check.page.write,
         check.normalize, check.enrich, check._alert) = saved

    eq("NYC digest went to NYC subscribers only",
       [a for a, _ in nyc_sent], ["both@example.com", "nyc-only@example.com"])
    eq("NYC digest carried only NYC dogs",
       sorted({tuple(d) for _, d in nyc_sent}),
       [("animalhaven:3", "muddypaws:1", "muddypaws:2")])
    eq("LA digest went to LA subscribers only",
       [a for a, _ in la_sent], ["both@example.com", "la-only@example.com"])
    eq("LA digest carried only LA dogs",
       sorted({tuple(d) for _, d in la_sent}),
       [("wagmor:10", "wagmor:11")])
    eq("both cities' dogs survived both runs",
       (db.count_seen("NYC"), db.count_seen("LA")), (3, 2))


def test_a_full_la_run_leaves_nyc_alone():
    """The integration case: run both cities for real and diff the NYC rows."""
    import check
    import emailer
    fresh_db("integration.db")

    saved = (check.sources_for_city, emailer.send_digest, check.page.write,
             check.normalize, check.enrich, check._alert)
    try:
        check.sources_for_city = lambda c: (
            [FakeLASource(LA_DOGS)] if c == "LA" else [FakeNYCSource(NYC_DOGS)])
        emailer.send_digest = lambda *a, **k: None
        check.page.write = lambda pages, for_date=None: Path("/dev/null")
        check.normalize = lambda dogs: dogs
        check.enrich = lambda dogs: dogs
        check._alert = lambda *a, **k: None

        check.run(city="NYC")
        with db.connect() as conn:
            conn.execute("UPDATE seen_dogs SET first_seen = '2026-05-01' "
                         "WHERE city = 'NYC'")
        nyc_before = rows("NYC")

        check.run(city="LA")
        eq("NYC rows identical after a full LA run", rows("NYC"), nyc_before)

        # An LA rescue loses a dog. NYC still must not move.
        check.sources_for_city = lambda c: (
            [FakeLASource(LA_DOGS[:1])] if c == "LA"
            else [FakeNYCSource(NYC_DOGS)])
        check.run(city="LA")
        eq("NYC rows identical after LA loses a dog", rows("NYC"), nyc_before)
        eq("LA pruned to what it listed", sorted(rows("LA")), ["wagmor:10"])
    finally:
        (check.sources_for_city, emailer.send_digest, check.page.write,
         check.normalize, check.enrich, check._alert) = saved


def test_forget_floor_blocks_a_mass_prune():
    """Most of a city vanishing is a broken scraper, not 200 adoptions."""
    import check
    import emailer
    fresh_db("floor.db")
    many = [dog("muddypaws", i, f"Dog{i}", "NYC") for i in range(20)]

    alerts = []
    saved = (check.sources_for_city, emailer.send_digest, check.page.write,
             check.normalize, check.enrich, check._alert)
    try:
        check.sources_for_city = lambda c: (
            [FakeNYCSource(many)] if c == "NYC" else [])
        emailer.send_digest = lambda *a, **k: None
        check.page.write = lambda pages, for_date=None: Path("/dev/null")
        check.normalize = lambda dogs: dogs
        check.enrich = lambda dogs: dogs
        check._alert = lambda subject, body: alerts.append(subject)

        check.run(city="NYC")
        eq("20 dogs recorded", db.count_seen("NYC"), 20)

        # Now the scraper breaks and returns 3 of 20.
        check.sources_for_city = lambda c: (
            [FakeNYCSource(many[:3])] if c == "NYC" else [])
        check.run(city="NYC")
        eq("the prune was refused", db.count_seen("NYC"), 20)
        eq("and it alerted", [a for a in alerts if "prune skipped" in a],
           ["LUVD NYC: prune skipped, sources look broken"])

        # A normal night — 18 of 20 — still prunes.
        check.sources_for_city = lambda c: (
            [FakeNYCSource(many[:18])] if c == "NYC" else [])
        check.run(city="NYC")
        eq("a normal night still prunes", db.count_seen("NYC"), 18)
    finally:
        (check.sources_for_city, emailer.send_digest, check.page.write,
         check.normalize, check.enrich, check._alert) = saved


def test_migration_is_idempotent_on_the_current_schema():
    """Three runs against a production-shaped file, and `welcomed` untouched."""
    legacy_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO subscribers(email, active, created, welcomed) "
                     "VALUES('old@example.com', 1, '2026-01-01', "
                     "'2026-01-01 09:00:00')")
        # welcomed NULL is the real state of some production rows, and is
        # treated as "already welcomed" by design.
        conn.execute("INSERT INTO subscribers(email, active, created) "
                     "VALUES('nullwelcome@example.com', 1, '2026-02-02')")
        conn.execute("INSERT INTO subscribers(email, active, created, "
                     "unsubscribed) VALUES('gone@example.com', 0, "
                     "'2026-03-03', '2026-04-04')")
        for i, src in enumerate(("muddypaws", "animalhaven", "waggytail")):
            conn.execute("INSERT INTO seen_dogs(dog_id, source, name, url, "
                         "first_seen) VALUES(?, ?, ?, ?, ?)",
                         (f"{src}:{i}", src, f"Dog{i}",
                          f"https://example.org/{i}", "2026-05-05"))

    def snapshot():
        with db.connect() as conn:
            subs = [dict(r) for r in conn.execute(
                "SELECT email, active, created, welcomed, unsubscribed "
                "FROM subscribers ORDER BY email")]
            pairs = [(r["email"], r["city"]) for r in conn.execute(
                "SELECT email, city FROM subscriber_cities "
                "ORDER BY email, city")]
            dogs = [(r["dog_id"], r["city"], r["first_seen"]) for r in
                    conn.execute("SELECT dog_id, city, first_seen "
                                 "FROM seen_dogs ORDER BY dog_id")]
        return subs, pairs, dogs

    with db.connect() as conn:
        welcomed_before = [dict(r) for r in conn.execute(
            "SELECT email, welcomed FROM subscribers ORDER BY email")]
        eq("no city column before the migration",
           "city" in {c["name"] for c in
                      conn.execute("PRAGMA table_info(seen_dogs)")}, False)

    db.init_db()
    first = snapshot()
    db.init_db()
    second = snapshot()
    db.init_db()
    third = snapshot()

    eq("every existing subscriber assigned to NYC", first[1],
       [("gone@example.com", "NYC"), ("nullwelcome@example.com", "NYC"),
        ("old@example.com", "NYC")])
    eq("including the inactive one",
       ("gone@example.com", "NYC") in first[1], True)
    eq("every existing dog backfilled to NYC",
       sorted({c for _, c, _ in first[2]}), ["NYC"])
    eq("first_seen dates untouched by the migration",
       sorted({d for _, _, d in first[2]}), ["2026-05-05"])
    eq("run 2 identical to run 1", second, first)
    eq("run 3 identical to run 1", third, first)
    eq("no duplicate city rows after three runs", len(third[1]), 3)

    with db.connect() as conn:
        welcomed_after = [dict(r) for r in conn.execute(
            "SELECT email, welcomed FROM subscribers ORDER BY email")]
    eq("welcomed untouched by three migrations", welcomed_after,
       welcomed_before)
    eq("nobody gained a welcomed timestamp",
       sum(1 for r in welcomed_after if r["welcomed"]), 1)

    # The backfill must fill gaps, never overrule a choice. Someone who signed up
    # for Los Angeles alone must not be handed a New York row by the next boot:
    # they would then receive New York's digest, which is the failure this whole
    # change exists to prevent. init_db() runs on import in every gunicorn
    # worker, so "the next boot" means within the hour.
    db.add_subscriber("la-only@example.com", "LA")
    db.init_db()
    db.init_db()
    eq("an LA-only subscriber is not backfilled into NYC",
       db.subscriber_cities("la-only@example.com"), ["LA"])
    eq("and so never appears on the NYC list",
       "la-only@example.com" in db.list_subscribers("NYC"), False)
    eq("while a genuinely city-less row still gets New York",
       db.subscriber_cities("old@example.com"), ["NYC"])


def test_subscribe_defaults_and_rejects():
    fresh_db("subscribe.db")
    eq("no city lands in NYC",
       (db.add_subscriber("a@example.com"), db.subscriber_cities("a@example.com")),
       (True, ["NYC"]))
    eq("an explicit city is honoured",
       (db.add_subscriber("b@example.com", "LA"),
        db.subscriber_cities("b@example.com")), (True, ["LA"]))
    eq("case is canonicalised",
       (db.add_subscriber("c@example.com", "  la  "),
        db.subscriber_cities("c@example.com")), (True, ["LA"]))
    eq("re-subscribing the same city sends no second welcome",
       db.add_subscriber("a@example.com", "NYC"), False)
    eq("adding a second city is worth confirming",
       db.add_subscriber("a@example.com", "LA"), True)
    eq("and both cities are kept", db.subscriber_cities("a@example.com"),
       ["LA", "NYC"])
    eq("one email is still one row",
       len(db.list_subscribers()), 3)
    eq("an unknown city cannot create a phantom list",
       (db.add_subscriber("d@example.com", "Atlantis"),
        db.subscriber_cities("d@example.com")), (True, ["NYC"]))

    # Unsubscribe is global, and stays global: it zeroes the one consent flag
    # rather than removing city rows, so it stops every city at once and the
    # HMAC over the bare address keeps working untouched.
    eq("unsubscribe takes them off everything",
       (db.deactivate_subscriber("a@example.com"),
        db.list_subscribers("NYC"), db.list_subscribers("LA")),
       (True, ["d@example.com"], ["b@example.com", "c@example.com"]))
    eq("the city rows survive an unsubscribe",
       db.subscriber_cities("a@example.com"), ["LA", "NYC"])
    eq("a second unsubscribe sends no second goodbye",
       db.deactivate_subscriber("a@example.com"), False)


def test_schedule_matches_the_old_single_city_loop():
    """With one live city, the next run must be exactly what the shell computed.

    The old loop was `date -d "today 05:30"` in the container's fixed timezone,
    pushed a day if it had passed. This reproduces that and compares.
    """
    nyc = ZoneInfo("America/New_York")

    def shell_equivalent(now_epoch):
        local = datetime.fromtimestamp(now_epoch, nyc)
        target = datetime.combine(local.date(), time(5, 30), nyc)
        if target.timestamp() <= now_epoch:
            target = datetime.combine(local.date() + timedelta(days=1),
                                      time(5, 30), nyc)
        return int(target.timestamp()) - int(now_epoch)

    saved = cities.CITIES
    try:
        cities.CITIES = {"NYC": saved["NYC"],
                         "LA": cities.City(**{**saved["LA"].__dict__,
                                              "live": False})}
        probes = [
            datetime(2026, 7, 29, 15, 10, tzinfo=nyc),      # this afternoon
            datetime(2026, 7, 29, 5, 30, tzinfo=nyc),       # exactly 05:30
            datetime(2026, 7, 29, 5, 29, 59, tzinfo=nyc),   # a second before
            datetime(2026, 7, 30, 2, 0, tzinfo=nyc),        # small hours
            datetime(2026, 3, 8, 1, 0, tzinfo=nyc),         # spring forward
            datetime(2026, 11, 1, 1, 0, tzinfo=nyc),        # fall back
            datetime(2026, 12, 31, 23, 59, tzinfo=nyc),     # year end
        ]
        for p in probes:
            now = p.timestamp()
            wait, codes = cities.next_run(now)
            eq(f"schedule matches the old loop at {p:%Y-%m-%d %H:%M %Z}",
               (wait, codes), (shell_equivalent(now), ["NYC"]))
    finally:
        cities.CITIES = saved


def test_schedule_runs_each_city_on_its_own_clock():
    """Two live cities: two runs a day, each at 05:30 where it actually is.

    Both cities are forced live here rather than read from the registry, so this
    keeps testing the two-city schedule regardless of which cities are currently
    open — the arithmetic is what's under test, not today's roster.
    """
    nyc = ZoneInfo("America/New_York")
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 7, 29, 15, 10, tzinfo=nyc).timestamp()

    saved = cities.CITIES
    try:
        cities.CITIES = {
            code: cities.City(**{**c.__dict__, "live": True})
            for code, c in saved.items()
        }
        wait, codes = cities.next_run(now)
        when = datetime.fromtimestamp(now + wait, nyc)
        eq("the soonest run is New York's", codes, ["NYC"])
        eq("and it is 05:30 in New York", when.strftime("%H:%M %Z"), "05:30 EDT")

        # Step just past it and the next one due is Los Angeles, same morning.
        wait2, codes2 = cities.next_run(now + wait + 1)
        la_when = datetime.fromtimestamp(now + wait + 1 + wait2, la)
        eq("the next run after that is Los Angeles", codes2, ["LA"])
        eq("and it is 05:30 in Los Angeles", la_when.strftime("%H:%M %Z"),
           "05:30 PDT")
        eq("the two are three hours apart", round(wait2 / 3600, 2), 3.0)
        eq("neither ever sleeps zero seconds", min(wait, wait2) > 0, True)
    finally:
        cities.CITIES = saved


def test_a_city_dropping_out_keeps_its_pages():
    """page.write() must never delete a city it wasn't handed.

    This is the shape of the original bug. public/dog/ and sitemap.xml are shared
    between cities, so the naive fix — call write() once per city — had each city
    delete the other's dog pages and publish a sitemap covering half the site.
    check.py leaves a city out when its sources return nothing, so "not in this
    pass" is a thing that will really happen, on a morning when a rescue's site is
    down rather than never.
    """
    import page
    out = TMP / "pages"
    saved_out = page.OUT_DIR
    try:
        page.OUT_DIR = out
        os.environ["SITE_URL"] = "https://luvd.com"
        today = date(2026, 7, 29)
        iso = today.isoformat()
        for d in NYC_DOGS + LA_DOGS:
            d.first_seen = iso

        def sitemap():
            return re.findall(r"<loc>(.*?)</loc>",
                              (out / "sitemap.xml").read_text())

        page.write({"NYC": [(iso, NYC_DOGS)], "LA": [(iso, LA_DOGS)]}, today)
        both = sitemap()
        la_page = (out / "la.html").read_text()
        la_urls = sorted(u for u in both if "wagmor" in u)
        eq("both cities published", (out / "la.html").exists()
           and (out / "index.html").exists(), True)
        eq("LA's dog pages exist",
           len(list((out / "dog" / "wagmor-rescue").iterdir())), 2)
        eq("sitemap covers both", ("https://luvd.com/" in both,
                                   "https://luvd.com/la" in both), (True, True))

        # LA's scrapers fail: check.py hands over New York alone.
        page.write({"NYC": [(iso, NYC_DOGS)]}, today)
        after = sitemap()
        eq("LA's page survived", (out / "la.html").read_text(), la_page)
        eq("LA's dog pages survived",
           len(list((out / "dog" / "wagmor-rescue").iterdir())), 2)
        eq("LA's sitemap URLs were carried",
           sorted(u for u in after if "wagmor" in u), la_urls)
        eq("New York's are all still there",
           len([u for u in after if "/dog/" in u]), 5)
        eq("and nothing is listed twice", len(after) - len(set(after)), 0)

        # LA comes back with one dog gone: the stale page and URL must go.
        page.write({"NYC": [(iso, NYC_DOGS)], "LA": [(iso, LA_DOGS[:1])]}, today)
        back = sitemap()
        eq("the adopted dog's page is gone",
           len(list((out / "dog" / "wagmor-rescue").iterdir())), 1)
        eq("and its URL with it",
           len([u for u in back if "/dog/wagmor-rescue/" in u]), 1)
        eq("no duplicates after the round trip",
           len(back) - len(set(back)), 0)

        # A sitemap left over from a different SITE_URL must not be republished:
        # every later run would carry it again, forever.
        (out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>http://localhost:8000/dog/wagmor-rescue/x-1</loc></url>"
            "</urlset>", encoding="utf-8")
        page.write({"NYC": [(iso, NYC_DOGS)]}, today)
        eq("another origin's URLs are not carried",
           [u for u in sitemap() if "localhost" in u], [])
    finally:
        page.OUT_DIR = saved_out
        import shutil
        shutil.rmtree(out, ignore_errors=True)


def test_sources_are_partitioned_by_city():
    from sources.registry import all_sources, sources_for_city
    every = {s.name for s in all_sources()}
    per_city = set()
    for code in cities.all_codes():
        per_city |= {s.name for s in sources_for_city(code)}
    eq("every registered source belongs to exactly one known city",
       per_city, every)
    eq("no source is in two cities",
       sum(len(sources_for_city(c)) for c in cities.all_codes()), len(every))


def test_events_are_city_scoped_and_bounded_to_the_week():
    """The Monday events mail, on both axes that can send someone to the wrong place.

    A subscriber in one city must never be told to turn up in the other, and an
    event outside this week must not be announced as being in it — a date that is
    wrong by a fortnight sends somebody to a car park.
    """
    import events as sheet
    fresh_db("events.db")
    monday = date(2026, 7, 27)
    sunday = monday + timedelta(days=6)

    csv_text = (
        "City,Rescue,Title,Date,Start,End,Location,Address,URL,Note\n"
        'NYC,NYC Second Chance,Adoption Event,"Saturday, August 1, 2026",'
        "11AM,1 PM,JustFoodForDogs,45 Christopher St,,\n"
        "NYC,Korean K9,Meet the Dogs,7/29/2026,2 pm,5 pm,Petco,815 Hutch,,\n"
        "NYC,Muddy Paws,Too Far Out,2026-08-20,10 am,,Prospect Park,,,\n"
        "NYC,Muddy Paws,Already Gone,2026-07-20,10 am,,Prospect Park,,,\n"
        "LA,Wagmor Pets,Meet & Greet,2026-07-30,10 am,2 pm,Studio City,,,\n"
        "CHI,Nobody,Not Live,2026-07-29,,,,,,\n"
        "NYC,Muddy Paws,Unreadable Date,next Saturday,,,,,,\n"
    )
    rows, problems = sheet.parse(csv_text, monday)
    eq("every readable row is kept", len(rows), 5)
    eq("a city that is not live is refused",
       any("CHI" in p for p in problems), True)
    eq("a date a human cannot pin down is refused, not guessed",
       any("could not read the date" in p for p in problems), True)

    # "If you are not certain the event is real, don't send it." A sheet is
    # edited by typing, so a cancellation arrives as a word in a cell rather
    # than as a deleted row — and an event with no place is not one a reader
    # can act on.
    doubtful = (
        "City,Rescue,Title,Date,Start,End,Location,Address,URL,Note\n"
        "NYC,Real Rescue,Adoption Event,2026-07-29,11 am,1 pm,Petco,815 Hutch,,\n"
        "NYC,Off Rescue,Adoption Event CANCELLED,2026-07-29,11 am,,Petco,,,\n"
        "NYC,Off Rescue,Yard Day,2026-07-30,10 am,,Prospect Park,,,Postponed - TBA\n"
        "NYC,Vague Rescue,Mystery Meetup,2026-07-31,11 am,,,,,\n"
        "NYC,Maybe Rescue,Pop-up,2026-07-31,11 am,,Silver Lake,,,rain date if wet\n"
    )
    kept, said = sheet.parse(doubtful, monday)
    eq("only the unambiguous event survives", [r["title"] for r in kept],
       ["Adoption Event"])
    eq("a cancelled row is not sent",
       any("cancelled" in p for p in said), True)
    eq("a postponed row is not sent",
       any("postponed" in p for p in said), True)
    eq("a rain date is not sent", any("rain date" in p for p in said), True)
    eq("an event with nowhere to go is not sent",
       any("no location or address" in p for p in said), True)

    db.replace_events(rows)
    eq("rows land under the right cities", db.event_counts(), {"LA": 1, "NYC": 4})

    nyc = db.events_between("NYC", monday.isoformat(), sunday.isoformat())
    la = db.events_between("LA", monday.isoformat(), sunday.isoformat())
    eq("NYC gets only its own week", [e["title"] for e in nyc],
       ["Meet the Dogs", "Adoption Event"])
    eq("LA gets only its own week", [e["title"] for e in la], ["Meet & Greet"])
    eq("no event is in both cities' answers",
       set(e["uid"] for e in nyc) & set(e["uid"] for e in la), set())
    eq("an event a fortnight out is not announced as this week",
       any(e["title"] == "Too Far Out" for e in nyc), False)
    eq("an event that already happened is not announced",
       any(e["title"] == "Already Gone" for e in nyc), False)
    eq("soonest first", [e["starts_on"] for e in nyc],
       sorted(e["starts_on"] for e in nyc))

    # An unreadable sheet must leave the cache alone rather than cancel the week.
    eq("an empty parse never empties the table", db.replace_events([]), 0)
    eq("the cache survives it", db.event_counts(), {"LA": 1, "NYC": 4})

    # Re-syncing the same sheet must not duplicate anything.
    db.replace_events(rows)
    eq("re-syncing is idempotent", db.event_counts(), {"LA": 1, "NYC": 4})


def test_events_email_points_at_its_own_city():
    """Each city's events mail links to that city's page, not the default one."""
    import emailer
    fresh_db("events_mail.db")
    monday = date(2026, 7, 27)
    db.replace_events([{
        "uid": "la|wagmor|2026-07-30|meet", "city": "LA", "rescue": "Wagmor Pets",
        "title": "Meet & Greet", "starts_on": "2026-07-30", "starts_at": "10 am",
        "ends_at": "2 pm", "location": "Studio City", "address": "",
        "url": "", "note": "",
    }, {
        "uid": "nyc|kk9|2026-07-29|meet", "city": "NYC", "rescue": "Korean K9",
        "title": "Meet the Dogs", "starts_on": "2026-07-29", "starts_at": "2 pm",
        "ends_at": "", "location": "Petco", "address": "", "url": "", "note": "",
    }])
    os.environ["SITE_URL"] = "https://luvd.com"
    week = (monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    for city, want in (("NYC", "https://luvd.com"), ("LA", "https://luvd.com/la")):
        evs = db.events_between(city, *week)
        html_body = emailer.build_events_html(evs, city)
        links = {u for u in re.findall(r'href="(https://luvd\.com[^"]*)"', html_body)
                 if "unsubscribe" not in u}
        # Only the links that name a city — the mail also links individual dogs
        # and the rescue's own page, which are city-agnostic URLs. The claim
        # being made is that no city page OTHER than this one is ever linked.
        homes = {c.path if c.path == "/" else c.path
                 for c in cities.CITIES.values()}
        city_links = {u for u in links
                      if (u[len("https://luvd.com"):] or "/") in homes}
        eq(f"{city}'s events mail links {city}'s page", city_links, {want})
        text_body = emailer.build_events_text(evs, city)
        eq(f"{city}'s text part does too", want in text_body, True)

    # One link per event, and never one that goes nowhere. `rescue` is a display
    # label, so the sheet can name an organisation LUVD publishes no page for —
    # in which case the row gets no link rather than a 404.
    base = {"uid": "x", "city": "NYC", "title": "Adoption Event",
            "starts_on": "2026-07-29", "starts_at": "11 am", "ends_at": "",
            "location": "Petco", "address": "", "note": ""}
    own_url = dict(base, rescue="Muddy Paws Rescue",
                   url="https://example.org/event")
    with_url = emailer.build_events_html([own_url], "NYC")
    eq("an event with its own url offers its details",
       "View Event Details" in with_url, True)
    eq("and not the rescue fallback too",
       "See Adoptable Dogs" in with_url, False)

    no_url = dict(base, rescue="Muddy Paws Rescue", url="")
    fallback = emailer.build_events_html([no_url], "NYC")
    eq("no url falls back to that rescue's dogs",
       "See Adoptable Dogs" in fallback, True)

    unknown = dict(base, rescue="An Org LUVD Does Not Follow", url="")
    body = emailer.build_events_html([unknown], "NYC")
    eq("an unknown organisation gets no button at all",
       ("View Event Details" in body) or ("See Adoptable Dogs" in body), False)


def test_dog_page_css_not_double_escaped():
    """Every generated page must emit CSS the browser can actually parse.

    The dog pages shipped for a long time with four braces per rule in the
    source. An f-string turns four into two, so the browser received
    `body{{...}}`, treated every rule as malformed, and rendered the page as
    unstyled HTML — Times New Roman and blue links. It was reported by someone
    following a shared link, which is the worst place for it: a dog page is
    exactly what a share resolves to.

    Nothing in the pipeline formats these strings twice, so a doubled brace in
    the output is always a bug. Asserted on the rendered CSS of every page kind
    rather than on the source, because the source is where the escaping is easy
    to get wrong and the output is where it matters.
    """
    from datetime import date as _date
    import page as _page
    from sources.base import Dog as _Dog

    d = _Dog(id="t:1", name="Test", source="t", source_label="T Rescue",
             url="https://example.org/1", photos=["https://example.org/p.jpg"],
             breed="Mixed breed", age="2 years", sex="Male", weight="20 lbs",
             location="New York, NY", description="A good dog.")
    d.city = "NYC"
    d.first_seen = "2026-07-31"
    today = _date(2026, 7, 31)

    pages = {
        "city page": _page.render([("2026-07-31", [d])], today, "NYC"),
        "dog page": _page._dog_page(d, "https://luvd.com", today),
    }
    for label, html_out in pages.items():
        blocks = re.findall(r"<style>(.*?)</style>", html_out, re.S)
        eq(f"{label} has a stylesheet", bool(blocks), True)
        css = "\n".join(blocks)
        # `{{` only. A doubled CLOSING brace is ordinary valid CSS — it is how a
        # nested at-rule ends, e.g. `@keyframes x{from{...}to{...}}` — and the
        # city page has three of them legitimately. Two adjacent OPENING braces
        # never occur in valid CSS, which makes them an exact signal for an
        # f-string that escaped one level too many.
        eq(f"{label} CSS has no doubled opening braces", css.count("{{"), 0)
        # A malformed rule can also leave the braces unbalanced, which is the
        # other way a stylesheet silently stops applying.
        eq(f"{label} CSS braces balance",
           css.count("{") == css.count("}"), True)


def test_filter_menus_cannot_be_clipped():
    """An open filter menu must never sit inside a clipping ancestor.

    This shipped twice, both times reported as "the menus open behind the dogs on
    Safari". The menus are position:fixed. WebKit clips a fixed descendant to any
    *scrolling* ancestor's box, and makes a containing block out of any ancestor
    carrying transform, filter, backdrop-filter, perspective, contain or
    will-change. The pill row scrolls sideways on a phone, so while the menus were
    its children each one was cut down to the row's own height.

    The first fix removed -webkit-overflow-scrolling:touch and added a z-index.
    The bug returned from the plain overflow-x:auto left behind, because z-index
    settles paint order and this is clipping — no stacking value lifts content out
    of an ancestor's clip rect.

    So there are two acceptable shapes and this test accepts either:

      * the row does not scroll or transform, so nothing clips; or
      * the row may do as it likes, because an open menu is moved out of it into
        a body-level layer.

    What it refuses is the combination that broke: a scrolling row with the menus
    still inside it. Asserted against the real rendered page, so it holds however
    the code is rewritten.
    """
    import page as _page
    css = _page_css()
    src = _page.__file__ and open(_page.__file__, encoding="utf-8").read()

    clips = ("overflow", "mask-image", "transform", "filter", "backdrop-filter",
             "perspective", "contain:", "will-change",
             "-webkit-overflow-scrolling")
    rules = _rules_for(css, ".fbar-pills")
    eq("the pill row has rules to check", bool(rules), True)
    found = sorted({p for _, body in rules for p in clips if p in body})

    html = _page_html()
    has_layer = 'id="fmenu-layer"' in html
    # The layer is only an escape hatch if something actually moves the menu into
    # it, so the test asks for the move as well as the container.
    # Asserted on the contract, not on one expression: that the mover is defined
    # and that the open path calls it. Pinning this to a literal like
    # `menuLayer.appendChild` made the test fail the moment the lookup was made
    # lazy, which is churn rather than protection.
    moves_menu = ("function openMenuInLayer" in src
                  and "openMenuInLayer(pill, menu)" in src
                  and "openMenuInLayer" in html)

    if found:
        eq(f"the row clips ({', '.join(found)}), so a menu layer must exist",
           has_layer, True)
        eq("...and an open menu must be moved into it", moves_menu, True)
        # And the layer itself must not reintroduce the problem it exists to fix.
        layer_rules = _rules_for(css, ".fmenu-layer")
        eq("the layer has rules to check", bool(layer_rules), True)
        layer_bad = sorted({p for _, body in layer_rules for p in clips
                            if p in body})
        eq("the layer itself clips nothing", layer_bad, [])
    else:
        eq("the row clips nothing, so no layer is required", True, True)

    # The premise the whole test rests on. If the menus stop being fixed this is
    # measuring the wrong thing, and it should say so rather than pass quietly.
    eq("the menus are still position:fixed somewhere",
       "position:fixed" in "".join(b for _, b in _rules_for(css, ".fmenu")), True)


def test_no_page_sends_a_visitor_to_another_citys_rescue_index():
    """Every rescue-index link on a city's pages points at THAT city's index.

    This has been reported twice: on the LA page, "All rescues" went to New
    York's list. The mechanism both times was a hardcoded "/rescues" — easy to
    write, and invisible unless you load the second city's page. So the check is
    against rendered markup for every live city, over the city page, its rescue
    pages and its index, and it fails on ANY href pointing at a foreign index.

    The one deliberate exception is the cross-city row at the foot of an index
    ("Also in Los Angeles →"), which is the whole-site view. It is recognised by
    its "Also in" label rather than exempted wholesale, so a stray link cannot
    hide behind the exemption.
    """
    from datetime import date as _date
    import page as _page
    from sources.base import Dog as _Dog

    # Every path that serves a rescue index, so a link to any of them can be
    # identified as "an index link" without guessing at the URL shape.
    index_paths = {c.rescues_path: c.code for c in cities.CITIES.values()}
    eq("more than one index to confuse", len(index_paths) > 1, True)

    checked = 0
    for code in cities.live_codes():
        c = cities.CITIES[code]
        d = _Dog(id=f"t:{code}", name="Test", source="t", source_label="T Rescue",
                 url="https://example.org/1", photos=["https://example.org/p.jpg"],
                 breed="Terrier", city=code)
        d.first_seen = "2026-07-31"
        dated = [("2026-07-31", [d])]
        pages = {
            f"{code} city page": _page.render(dated, _date(2026, 7, 31), code),
            f"{code} rescue page": _page._rescue_page(
                "T Rescue", [d], "https://luvd.com"),
            f"{code} rescue index": _page._rescues_page(
                {"T Rescue": [d]}, "https://luvd.com", _date(2026, 7, 31), code),
        }
        for what, markup in pages.items():
            # Anchors only: an href is what a visitor follows. JSON-LD is
            # checked separately below.
            for href, label in re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                                          markup, re.S):
                path = href.split("://")[-1]
                path = path[path.index("/"):] if "://" in href else href
                owner = index_paths.get(path.rstrip("/") or "/")
                if owner is None:
                    continue                      # not an index link at all
                checked += 1
                if owner != code and "Also in" in label:
                    continue                      # the deliberate cross-link
                eq(f"{what}: {href} belongs to", owner, code)

        # And the breadcrumb trail, which is the same claim made to a crawler.
        ld = json.loads(html.unescape(re.search(
            r'application/ld\+json">(.*?)</script>',
            pages[f"{code} rescue page"], re.S).group(1)))
        trail = [n for n in ld["@graph"]
                 if n["@type"] == "BreadcrumbList"][0]["itemListElement"]
        crumb = [i for i in trail if str(i.get("item", "")).endswith("rescues")]
        eq(f"{code} breadcrumb names one index", len(crumb), 1)
        eq(f"{code} breadcrumb index", crumb[0]["item"],
           f"https://luvd.com{c.rescues_path}")

    # The premise: if the link vanished entirely the loop above would pass
    # having examined nothing.
    eq("index links actually found", checked >= 2 * len(cities.live_codes()), True)


def _page_css() -> str:
    """Every <style> block from a real rendered page."""
    from datetime import date as _date
    import page as _page
    from sources.base import Dog as _Dog
    d = _Dog(id="t:1", name="Test", source="t", source_label="T",
             url="https://example.org/1", photos=["https://example.org/p.jpg"],
             breed="Terrier")
    d.first_seen = "2026-07-31"
    html_out = _page.render([("2026-07-31", [d])], _date(2026, 7, 31), "NYC")
    return "\n".join(re.findall(r"<style>(.*?)</style>", html_out, re.S))


def _page_html() -> str:
    """A real rendered page, for asserting on markup and script as shipped."""
    from datetime import date as _date
    import page as _page
    from sources.base import Dog as _Dog
    d = _Dog(id="t:1", name="Test", source="t", source_label="T",
             url="https://example.org/1", photos=["https://example.org/p.jpg"],
             breed="Terrier")
    d.first_seen = "2026-07-31"
    return _page.render([("2026-07-31", [d])], _date(2026, 7, 31), "NYC")


def _rules_for(css: str, selector: str):
    """[(selector, body)] for every rule whose selector mentions `selector`."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(sel.split())
        if selector in sel:
            out.append((sel, " ".join(body.split())))
    return out


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    real_db = db.DB_PATH
    try:
        for t in TESTS:
            print(f"\n=== {t.__name__} ===")
            t()
    finally:
        db.DB_PATH = real_db
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    print("\n" + ("ALL PASS" if not FAILURES
                  else f"{len(FAILURES)} FAILURE(S): {FAILURES}"))
    sys.exit(1 if FAILURES else 0)
