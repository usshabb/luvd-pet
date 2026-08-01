"""The cities LUVD publishes, and what each one means.

One definition per city — its code, its display name, the timezone its day is
measured in, and whether it is live — read by everything that used to hardcode
New York: the nightly clock (`check.py`), the sources (`sources/base.py`), the
subscriber lists (`db.py`), the signup endpoint (`app.py`) and the overnight
schedule (`fly-start.sh`).

Two states, and the difference matters:

  * **registered** — the city exists here, so its code is a legal value, its
    dogs can be recorded and its subscribers can be stored. Nothing runs.
  * **live** — the city also has a nightly run, and `POST /subscribe` accepts
    it. This is the switch an operator flips, and it should only be flipped
    once that city has scrapers registered in ``sources/registry.py``.

`live = False` is therefore the safe state for a city being built: everything
downstream tolerates its code, but nobody can be signed up for a list that
would never receive anything, and no empty scrape can run.

`DEFAULT_CITY` is what every row that predates cities means, what an unstamped
dog and an unstamped subscriber fall back to, and the city whose page is served
at the site root. It is New York because New York is the whole product's
history.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

# The hour the nightly run starts, in each city's OWN local time. 05:30 local
# is what New York has always run at; a second city wants the same local hour,
# not the same instant, because "today's dogs" is a local idea.
RUN_HOUR = 5
RUN_MINUTE = 30


@dataclass(frozen=True)
class City:
    code: str          # stored value and wire value: short, uppercase, stable
    name: str          # how a human sees it: "New York City"
    short: str         # how the copy says it: "NYC", "LA"
    state: str         # postal code for the location line: "NY", "CA"
    tz: str            # IANA zone; the city's day, and its 05:30, are measured here
    lat: float         # the page's dark mode follows the sun over the city, so
    lon: float         # each one needs its own coordinates
    path: str          # the URL its page is published at: "/", "/la"
    file: str          # the file in public/ that serves that path
    live: bool         # does it run nightly, and can you subscribe to it
    # Neighbourhoods worth collapsing a verbose listing location down to.
    # normalize.py turns "Sean Casey Animal Rescue - Windsor Terrace, Brooklyn"
    # into "Brooklyn, NY" with these.
    areas: Tuple[str, ...] = ()
    # What a rescue might call the city itself, lowercase, so a location that is
    # just the city name comes out in one canonical form.
    aliases: Tuple[str, ...] = ()
    # Heading over the breed guide's apartment note. Spelled out per city rather
    # than assembled, because the article depends on how the short form is said
    # aloud ("a NYC apartment", "an LA apartment") and guessing it from the
    # letters gets New York wrong.
    apartment_label: str = "In a city apartment"

    @property
    def location(self) -> str:
        """The "City, ST" a source falls back to when a feed has no location."""
        return f"{self.name if self.code != 'NYC' else 'New York'}, {self.state}"

    @property
    def rescues_path(self) -> str:
        """Where this city's rescue index is published.

        "/rescues" for the city at the root, "/la/rescues" for the rest. One page
        per city rather than a combined one, because that page exists to answer
        "which dog rescues are in Los Angeles?" — a local question, and a single
        page trying to serve every city's version of it can only be titled
        something like "Dog rescues in NYC and LA", which ranks worse for either
        than a dedicated page does for its own. It also degrades as cities are
        added, where a page each does not.
        """
        return "/rescues" if self.path == "/" else f"{self.path}/rescues"

    @property
    def rescues_file(self) -> str:
        """The file in public/ that serves rescues_path."""
        return self.rescues_path.lstrip("/") + ".html"

    @property
    def title(self) -> str:
        """The <title>. No brand suffix — Google renders the site name itself.

        Every result already carries a site-name line above the title, so
        "Adopt a dog in NYC — LUVD" under a heading that reads LUVD said the
        brand twice and spent characters doing it. Same reasoning as
        `share_title`, which dropped the suffix for og:site_name.

        The city stays at the FRONT. The leading words carry the most relevance
        weight and are what a person scans; "Adopt a dog in NYC" is a phrase
        people search and "LUVD" is not one yet, so leading with the brand would
        spend the best position on the least useful word.
        """
        return f"Adopt a dog in {self.short}"

    @property
    def share_title(self) -> str:
        """The same headline without the brand, for og:title and twitter:title.

        A share card is not a search result. Slack, iMessage and the rest render
        og:site_name as its own line above the title, and og:site_name is already
        "LUVD" — so "Adopt a dog in NYC — LUVD" under a heading that says LUVD
        says the brand twice and spends the title's width doing it.

        `title` keeps the suffix, because a <title> has no site_name beside it:
        in a search result the brand is the only thing telling you whose page
        this is.

        The root URL names no city. luvd.com is the address people paste without
        thinking about it, often to someone who does not live where they do — and
        "Adopt a dog in NYC" tells that person this is not for them, when the
        header's city picker is right there. A city path is chosen deliberately,
        so /la keeps its city and says so.

        Keyed on the path rather than on being DEFAULT_CITY: what matters is that
        this URL is the generic front door, not which city happens to be served
        at it. Move the default elsewhere and the rule still holds.
        """
        if self.path == "/":
            return "Adopt a dog"
        return f"Adopt a dog in {self.short}"


# Order is display order. Codes are the values that reach the database, the JSON
# payloads and the backup spreadsheet's tab names, so they are deliberately
# short and free of the characters Google rejects in a tab name.
#
# Every string here that appears in New York's published page is exactly what
# that page said before cities existed — the parameterisation has to be a no-op
# for New York, and the byte-for-byte diff of index.html is how that is checked.
CITIES = {
    c.code: c
    for c in (
        City(code="NYC", name="New York City", short="NYC", state="NY",
             tz="America/New_York", lat=40.7128, lon=-74.0060,
             path="/", file="index.html", live=True,
             areas=("Manhattan", "Brooklyn", "Queens", "Bronx",
                    "Staten Island"),
             aliases=("new york", "nyc", "new york city"),
             apartment_label="In a NYC apartment"),
        City(code="LA", name="Los Angeles", short="LA", state="CA",
             tz="America/Los_Angeles", lat=34.0522, lon=-118.2437,
             path="/la", file="la.html", live=True,
             areas=("Downtown", "Hollywood", "Studio City", "Sherman Oaks",
                    "Van Nuys", "Pasadena", "Santa Monica", "Long Beach",
                    "Burbank", "Glendale"),
             aliases=("los angeles", "la", "l.a.", "los angeles, ca"),
             apartment_label="In an LA apartment"),
    )
}

# Which rescues belong to a city is deliberately NOT listed here. Each Source
# declares its own `city` (sources/base.py) and sources/registry.py derives the
# per-city list from that, so registering a rescue is one edit rather than two.
# A second list here would be a thing to forget, and forgetting it drops a whole
# shelter out of its city's page and digest without anything failing.

# Every dog, subscriber and seen_dogs row that predates cities is this one.
DEFAULT_CITY = "NYC"


def canon(code: str) -> Optional[str]:
    """A known city's code, or None.

    Case- and whitespace-insensitive on the way in, exact on the way out, so a
    city can only ever be stored one way. `NYC` and `nyc` arriving as two
    different values would give one person two rows in `subscriber_cities` and
    therefore two identical emails.
    """
    if not code:
        return None
    key = code.strip().upper()
    return key if key in CITIES else None


def get(code: str) -> Optional[City]:
    return CITIES.get(canon(code) or "")


def resolve(code: str) -> City:
    """The city, or the default one. For renderers, which must always have one.

    Deliberately forgiving where `get()` is strict: a page has to be built from
    something, and an unrecognised code there means a bug upstream, not an
    attacker — every path that stores or mails a city validates with `canon()`
    first.
    """
    return get(code) or CITIES[DEFAULT_CITY]


def name(code: str) -> str:
    c = get(code)
    return c.name if c else (code or "")


def zone(code: str) -> ZoneInfo:
    c = get(code)
    return ZoneInfo(c.tz if c else CITIES[DEFAULT_CITY].tz)


def is_live(code: str) -> bool:
    c = get(code)
    return bool(c and c.live)


def all_codes() -> List[str]:
    return list(CITIES)


def live_codes() -> List[str]:
    return [c.code for c in CITIES.values() if c.live]


def default_run_city() -> str:
    """The city a bare `check.py` means.

    New York while it is live, because that is what running the job with no
    arguments has always done. The scheduler always passes `--city` explicitly,
    so this only covers a human typing the command.
    """
    if is_live(DEFAULT_CITY):
        return DEFAULT_CITY
    live = live_codes()
    return live[0] if live else DEFAULT_CITY


def today(code: str) -> date:
    """The date it is *there*.

    SQLite's datetime('now') is UTC, and after 8pm Eastern that is already
    tomorrow — which would make the evening's arrivals invisible. Each city
    dates off its own clock, so a Los Angeles dog listed at 9pm Pacific is
    still a Los Angeles Tuesday.
    """
    return datetime.now(zone(code)).date()


def next_run(now: Optional[float] = None) -> Tuple[int, List[str]]:
    """(seconds to wait, the city codes due then) for the next nightly run.

    Computed for every live city in its own zone and reduced to the soonest,
    because the container's TZ is fixed (`Dockerfile`, TZ=America/New_York) and
    "05:30" read off the ambient clock would run Los Angeles at 02:30 Pacific.
    Ties come back together so two cities sharing an instant both run.

    A target that has already passed — including exactly now — moves to the
    next day, matching what the shell loop did when New York was the only
    city, and making a zero-second sleep impossible.
    """
    now = float(datetime.now().timestamp() if now is None else now)
    due = {}
    for code in live_codes():
        tz = zone(code)
        local = datetime.fromtimestamp(now, tz)
        target = datetime.combine(local.date(), time(RUN_HOUR, RUN_MINUTE), tz)
        if target.timestamp() <= now:
            target = datetime.combine(
                local.date() + timedelta(days=1), time(RUN_HOUR, RUN_MINUTE), tz
            )
        due[code] = int(target.timestamp())
    if not due:
        # No live city at all. Sleep an hour and look again rather than
        # spinning; an operator mid-edit should not get a busy loop.
        return 3600, []
    soonest = min(due.values())
    return max(0, soonest - int(now)), sorted(k for k, v in due.items()
                                              if v == soonest)


if __name__ == "__main__":
    import sys

    # Two tiny outputs for fly-start.sh, which has no way to read this module
    # otherwise. Kept to one line each so the shell can parse them without
    # tools that may not be in the image.
    if "--next" in sys.argv:
        # "<seconds> <CODE> [CODE ...]" — space-separated so `for city in $due`
        # iterates it, which a comma-joined list would not.
        wait, codes = next_run()
        print(f"{wait} {' '.join(codes)}")
    elif "--default" in sys.argv:
        print(DEFAULT_CITY)
    elif "--live" in sys.argv:
        for code in live_codes():
            print(f"{code}\t{CITIES[code].tz}")
    else:
        for c in CITIES.values():
            print(f"{c.code}\t{c.name}\t{c.tz}\t{'live' if c.live else 'off'}")
