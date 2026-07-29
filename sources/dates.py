"""Turning a rescue feed's timestamp into the ``YYYY-MM-DD`` ``listed_since`` wants.

Five adoption platforms spell a date five ways, and one rescue spells it two
ways in the same response, so every source funnels through here:

    2026-02-24T23:18:33.620-05:00   Petstablished, offset-aware ISO
    2026-07-20T15:45:20.368Z        Petstablished again, same field, UTC
    2026-03-14T17:25:16             WordPress, naive ISO
    2026.05.10                      Petango's grid
    May 10, 2026                    Petango's detail prose
    1785266606                      not seen in the wild yet, cheap to accept

``listed_since`` drives a visible claim — "⏳ Listed 84 days" — so a value we
can't stand behind has to become an empty string rather than a number. Nothing
here raises: a malformed date costs a dog its badge, not the whole fetch.
"""
import re
from datetime import date, datetime

# Below this a date is a bug, not a listing: unset columns arrive as the epoch
# or as a placeholder year, and no adoption platform here predates it.
EARLIEST = date(2005, 1, 1)
# And above this it stops describing a dog. Twelve years is past a large dog's
# whole life, so a "listing" that old is a broken record rather than a long wait.
MAX_LISTING_YEARS = 12
# Feeds mix UTC with local offsets, so a record created tonight can read as
# tomorrow. One day of slack keeps it; page.py floors the wait at zero anyway.
FUTURE_SLACK_DAYS = 1

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]|$)")
_DOTTED = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})$")
_US_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_MONTH_NAME = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$")
_EPOCH = re.compile(r"^\d{9,13}$")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Epoch seconds vs milliseconds: 1e11 seconds is the year 5138, so anything
# larger is milliseconds.
_MILLIS_FLOOR = 10 ** 11


def _build(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


def _years_ago(today: date, years: int) -> date:
    """`today` minus whole years, surviving 29 February."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


def _from_epoch(seconds: float):
    try:
        if abs(seconds) >= _MILLIS_FLOOR:
            seconds /= 1000.0
        return datetime.utcfromtimestamp(seconds).date()
    except (OverflowError, OSError, ValueError):
        return None


def parse_date(value):
    """Any shape above -> a ``date``, or None. Never raises.

    Deliberately no ``dateutil``-style guessing: an unrecognised shape is a
    field we haven't looked at yet, and inventing a reading of it is how a dog
    ends up with a confidently wrong wait.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))

    text = str(value or "").strip()
    if not text:
        return None

    for pattern, order in ((_ISO, (1, 2, 3)), (_DOTTED, (1, 2, 3)),
                           (_COMPACT, (1, 2, 3)), (_US_SLASH, (3, 1, 2))):
        match = pattern.match(text)
        if match:
            return _build(*(match.group(i) for i in order))

    match = _MONTH_NAME.match(text)
    if match:
        month = _MONTHS.get(match.group(1)[:3].lower())
        return _build(match.group(3), month, match.group(2)) if month else None

    # Checked last so that 20260510 reads as a date, not as 1970.
    if _EPOCH.match(text):
        return _from_epoch(float(text))
    return None


def listing_date(value, born=None, today=None) -> str:
    """A ``listed_since`` string we're willing to print, or ``""``.

    Rejects what a wait can't be: unparseable, in the future, near the epoch,
    older than a dog lives, or — when the feed also tells us when the dog was
    born — before the dog existed. That last one catches a listing page reused
    for a second dog of the same name, which no format check would.
    """
    parsed = parse_date(value)
    if parsed is None:
        return ""

    today = today or date.today()
    if (parsed - today).days > FUTURE_SLACK_DAYS:
        return ""
    if parsed < EARLIEST or parsed < _years_ago(today, MAX_LISTING_YEARS):
        return ""

    birth = parse_date(born)
    if birth is not None and EARLIEST <= birth <= today and parsed < birth:
        return ""
    return parsed.isoformat()
