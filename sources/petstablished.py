"""Petstablished — the public pet-search API that backs Wagtopia.

Several NYC rescues run their adoptions on Petstablished. Its public search
(the one embedded as ``awo.petstablished.com/organization/<id>/widget/dogs``,
which now redirects to wagtopia.com) is served by an unauthenticated JSON API:

    GET /api/v2/public/search/shelter_pets/<org_id>?animal=Dog&page=N
        -> {"pets": [...], "total_page": N}
    GET /api/v2/public/search/pet/<pet_id>
        -> {"pet": {...}}   # the same dog with the shelter's own trait flags
    GET /api/v2/public/search/shelters?zip=11101&geo_range=35&animal=Dog
        -> {"shelters": [...]}   # how the org_id below was found

This is the sanctioned read path for a rescue's own listings, so it replaces
the Petfinder API that was decommissioned on 2 December 2025. It needs no
credentials — unlike ``/api/v2/public/pets``, which is the same data behind a
per-organization ``public_key`` we'd have to ask each rescue for.

Subclass with an ``org_id`` per rescue; see rescues/koreank9.py.
"""
import re
import time
from datetime import date
from typing import List, Optional

import requests

from .base import Dog, Source, clean_text
from .dates import listing_date

API_ROOT = "https://petstablished.com/api/v2/public/search"
# Where public_url resolves. Linking straight there skips a redirect hop.
PET_PAGE = "https://www.wagtopia.com/search/pet?id={pet_id}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

TIMEOUT = 30
PAGE_DELAY_SECONDS = 0.25
DETAIL_DELAY_SECONDS = 0.25
# The API reports total_page, so this only guards against a malformed response
# sending us into an unbounded loop.
MAX_PAGES = 40

# "Fostered" means living in a foster home, not adopted — those dogs are still
# looking. Anything else (Adopted, Pending, Hold) is not ours to advertise.
_ADOPTABLE_STATUSES = {"available", "fostered"}

# Petstablished stores its own size vocabulary; map it onto the small/medium/
# large/xlarge scale the rest of the pipeline scores against.
_SIZE_MAP = {
    "small": "small",
    "medium": "medium",
    "large": "large",
    "x-large": "xlarge",
    "xlarge": "xlarge",
    "extra large": "xlarge",
}

# The shelter's own yes/no/unknown flags. Only an explicit answer becomes a
# chip: "Not Sure" is Petstablished's unknown, and inventing a claim about a
# real animal is worse than saying nothing. An explicit False is an assertion
# in its own right, so it earns a caution chip rather than silence.
_TRAIT_FLAGS = [
    ("is_housebroken", "House-trained", "Not house-trained"),
    ("is_ok_with_other_dogs", "Good with dogs", "Not good with other dogs"),
    ("is_ok_with_other_cats", "Good with cats", "Not good with cats"),
    ("is_ok_with_other_kids", "Good with kids", "Adult home preferred"),
    ("is_spayed", "Spayed/neutered", None),
    ("shots_up_to_date", "Vaccinations up to date", None),
    ("is_hypoallergenic", "Hypoallergenic", None),
    ("has_special_need", "Special needs", None),
]

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}

# A dog whose last status was Adopted has come back, and its record long
# predates the listing an adopter is looking at now. Petstablished only keeps
# the one previous status, so this catches the returns it can still see and
# misses any dog that has changed status again since — see _listed_since.
_PLACED_BEFORE = re.compile(r"adopted", re.I)

_URL = r"(?:https?://|www\.)\S+"
_URL_LINE = re.compile(rf"^{_URL}$", re.I)
# "• Donate: www.example.org/donate" — a label whose whole payload is a link.
_LABEL_URL_LINE = re.compile(rf"^[\u2022*\-\s]*[^:]{{1,40}}:\s*{_URL}$", re.I)
# Listing chrome, e.g. "Meet Rinda | Apply Here | Videos". Gated on being short
# so a rescue that writes "apply here" inside a real paragraph keeps its words.
_APPLY_LINE = re.compile(r"apply here", re.I)
_APPLY_LINE_MAX = 90
# "Learn more about our adoption process:" — a heading, once its links are gone.
_LABEL_LINE_MAX = 60


def _flag(value) -> Optional[bool]:
    """True / False / None, from Petstablished's mixed bool-or-string flags."""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None                            # "Not Sure", "", None


def _is_placeholder(url: str) -> bool:
    """Petstablished hands out its own grey silhouette for dogs with no photo.

    Carrying it as a real photo dresses an empty listing up as a photographed
    one — the "Photo coming soon" treatment is both honest and better looking.
    """
    return "placeholder" in url.rsplit("/", 1)[-1].lower()


def _fmt_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _clean_description(html_text: str) -> str:
    """The write-up, minus the listing chrome around it.

    Petstablished descriptions are rescue-authored HTML that usually opens with
    a "Meet Rosie | Apply Here" link and closes with bare donation and
    application URLs. Those are navigation, not the dog — and LUVD renders its
    own apply button — so link-only lines go, along with any heading left
    stranded above them. Anything the rescue wrote about the animal, including
    where to meet them, is kept as-is.
    """
    text = clean_text(html_text)
    if not text:
        return ""

    # Rescues paste from word processors, so these arrive CRLF-delimited.
    lines = [ln.strip() for ln in text.replace("\r\n", "\n")
             .replace("\r", "\n").split("\n")]

    def is_chrome(line: str) -> bool:
        if _URL_LINE.match(line) or _LABEL_URL_LINE.match(line):
            return True
        return len(line) <= _APPLY_LINE_MAX and bool(_APPLY_LINE.search(line))

    dropped = {i for i, ln in enumerate(lines) if ln and is_chrome(ln)}

    # A heading whose entire body was links now introduces nothing.
    for i, line in enumerate(lines):
        if i in dropped or not line.endswith(":") or len(line) > _LABEL_LINE_MAX:
            continue
        following = next((j for j in range(i + 1, len(lines)) if lines[j]), None)
        if following is None or following in dropped:
            dropped.add(i)

    kept = "\n".join(ln for i, ln in enumerate(lines) if i not in dropped)
    return re.sub(r"\n{3,}", "\n\n", kept).strip()


def _age_from_dob(dob: str) -> str:
    """'2023-10-29T00:00:00.000-04:00' -> '2 years'.

    The birthday beats Petstablished's Puppy/Young/Adult/Senior bucket, which
    rescues set once and rarely revisit — several yearlings are still filed as
    "Adult". This matches what Petstablished itself renders from the same date,
    and the bucket is only used when no birthday was recorded. Ages are floored
    the way rescues write them ("1 year", "7 months").
    """
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(dob or ""))
    if not match:
        return ""
    year, month, day = (int(g) for g in match.groups())
    try:
        born = date(year, month, day)
    except ValueError:
        return ""
    today = date.today()
    if born > today:
        return ""
    months = (today.year - born.year) * 12 + (today.month - born.month)
    if today.day < born.day:
        months -= 1
    months = max(months, 0)
    if months < 12:
        return "1 month" if months == 1 else f"{months} months"
    years = months // 12
    return "1 year" if years == 1 else f"{years} years"


class PetstablishedSource(Source):
    """A rescue whose adoptable list lives on Petstablished.

    Subclasses set ``name``, ``label``, ``priority``, ``adopt_url`` and the
    ``org_id`` from the shelters endpoint.
    """

    org_id: str = ""
    # Per-dog detail fetches cost one request each, and only pay for
    # themselves at rescues that actually fill the trait flags in — so it's
    # opt-in rather than on by default. See each subclass.
    fetch_traits: bool = False
    # Some rescues use Petstablished's ``current_location`` to say which of
    # their own pages a dog belongs on. That field is detail-only, so routing
    # costs a request per dog and is likewise opt-in. See ``route``.
    route_by_location: bool = False
    # ``created_at`` is detail-only too, and it's the closest thing this API
    # has to a listing date. On by default because every rescue here already
    # walks the detail records for another reason, so it's free today.
    fetch_listed_since: bool = True

    def enabled(self, prefs: dict) -> bool:
        return bool(self.org_id)           # public API, no credentials needed

    def route(self, dog: Dog, location: str) -> bool:
        """Place one dog into the rescue's own program, from its location code.

        Only called when ``route_by_location`` is set, and only with a location
        we actually read — a failed detail call leaves the dog alone rather
        than risking a whole program disappearing on a bad network day.

        Return False to drop a dog the rescue lists nowhere. The default treats
        every dog as a plain adoption.
        """
        return True

    # ---------------------------------------------------------------- http --

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(_HEADERS)
        return session

    def _get(self, session: requests.Session, path: str, **params) -> dict:
        resp = session.get(f"{API_ROOT}/{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}

    # --------------------------------------------------------------- fetch --

    def fetch(self, prefs: dict) -> List[Dog]:
        session = self._session()

        records, seen_ids, page, total_pages = [], set(), 1, 1
        while page <= min(total_pages, MAX_PAGES):
            payload = self._get(session, f"shelter_pets/{self.org_id}",
                                animal="Dog", page=page)
            batch = payload.get("pets") or []
            if not batch:
                break
            total_pages = max(int(payload.get("total_page") or 1), 1)
            for rec in batch:
                # Pagination can repeat a record if the roster shifts between
                # requests; the id is authoritative.
                rec_id = str((rec or {}).get("id") or "")
                if not rec_id or rec_id in seen_ids:
                    continue
                seen_ids.add(rec_id)
                records.append(rec)
            page += 1
            if page <= total_pages:
                time.sleep(PAGE_DELAY_SECONDS)

        dogs = []
        for rec in records:
            dog = self._to_dog(rec)
            if dog is not None:
                dogs.append(dog)

        if self.fetch_traits or self.route_by_location or self.fetch_listed_since:
            dogs = self._walk_details(session, dogs)
        return dogs

    def _walk_details(self, session: requests.Session,
                      dogs: List[Dog]) -> List[Dog]:
        """One detail call per dog, for traits, a listing date and/or routing."""
        kept = []
        for dog in dogs:
            pet = self._detail(session, dog)
            if pet is not None:
                if self.fetch_traits:
                    self._apply_detail(dog, pet)
                if self.fetch_listed_since:
                    dog.listed_since = self._listed_since(pet)
                if self.route_by_location and not self.route(
                        dog, str(pet.get("current_location") or "").strip()):
                    continue
            kept.append(dog)
            time.sleep(DETAIL_DELAY_SECONDS)
        return kept

    # ------------------------------------------------------- record -> Dog --

    def _to_dog(self, rec: dict) -> Optional[Dog]:
        if not isinstance(rec, dict):
            return None
        pet_id = str(rec.get("id") or rec.get("pet_id") or "")
        if not pet_id:
            return None
        if rec.get("no_longer_available"):
            return None
        status = str(rec.get("status") or "").strip().lower()
        if status and status not in _ADOPTABLE_STATUSES:
            return None

        city = (rec.get("city") or "").strip()
        state = (rec.get("state") or "").strip().upper()
        location = ", ".join(p for p in (city, state) if p) or "New York, NY"

        return Dog(
            id=f"{self.name}:{pet_id}",
            name=clean_text(rec.get("name") or "", 80) or "Unknown",
            source=self.name,
            source_label=self.label,
            url=PET_PAGE.format(pet_id=pet_id),
            photos=self._photos(rec),
            breed=self._breed(rec),
            age=_age_from_dob(rec.get("date_of_birth")) or clean_text(
                rec.get("age") or "", 40),
            sex=clean_text(rec.get("sex") or "", 20),
            size=_SIZE_MAP.get(str(rec.get("size") or "").strip().lower(), ""),
            weight=str(rec.get("weight") or "").strip(),
            location=location,
            description=_clean_description(rec.get("description") or ""),
            fee=self._fee(rec.get("adoption_fee")),
            adopt_url=self.adopt_url,
        )

    @staticmethod
    def _photos(rec: dict) -> List[str]:
        """Gallery order, with the record's own cover image first."""
        urls = []
        cover = rec.get("thumb_url")
        if isinstance(cover, str) and cover:
            urls.append(cover)
        for image in rec.get("images") or []:
            if isinstance(image, dict):
                src = image.get("thumb_url") or image.get("main_photo_url")
                if isinstance(src, str) and src:
                    urls.append(src)
        unique, seen = [], set()
        for src in urls:
            if src not in seen and not _is_placeholder(src):
                seen.add(src)
                unique.append(src)
        return unique

    @staticmethod
    def _breed(rec: dict) -> str:
        """'German Shepherd Dog' + 'Mixed Breed' -> 'German Shepherd Dog/Mixed Breed'."""
        parts, seen = [], set()
        for key in ("primary_breed", "secondary_breed", "mixed_breed"):
            value = (rec.get(key) or "").strip()
            if value and value.lower() not in seen:
                seen.add(value.lower())
                parts.append(value)
        return "/".join(parts)

    @staticmethod
    def _fee(raw) -> Optional[str]:
        """'200.00 - Adult' -> '$200'. The trailing label is the rescue's own
        tier name, which duplicates the age we already show."""
        if isinstance(raw, (int, float)):
            return f"${_fmt_number(raw)}"
        match = re.search(r"[\d.]+", str(raw or ""))
        if not match:
            return None
        try:
            return f"${_fmt_number(float(match.group()))}"
        except ValueError:
            return None

    # -------------------------------------------------------------- detail --

    def _detail(self, session: requests.Session, dog: Dog) -> Optional[dict]:
        """The dog's full record, or None if we couldn't read it.

        The None is meaningful: callers that decide a dog's fate from detail
        fields have to be able to tell "the rescue says nothing here" from "we
        failed to ask".
        """
        pet_id = dog.id.split(":", 1)[-1]
        try:
            return (self._get(session, f"pet/{pet_id}") or {}).get("pet") or {}
        except (requests.RequestException, ValueError):
            return None

    @staticmethod
    def _listed_since(pet: dict) -> str:
        """When this dog's record was created on Petstablished.

        Read honestly: ``created_at`` is a record-creation date, not a
        publication date — Petstablished has no field for the latter. It is the
        best proxy available because these rescues create the record as the dog
        comes in: across all three orgs it sits within a couple of days of
        ``date_aquired`` (the intake date), sometimes just before, when a
        transport is entered ahead of arrival. Preferred over ``date_aquired``
        itself because a listing cannot precede the record that carries it, and
        a handful of records were created months after intake.

        Skipped for a dog whose previous status was Adopted: its record dates
        from the first time round, and counting from there would claim years of
        waiting for a dog that came back last month. ``date_of_birth`` is the
        other guard — a record cannot predate the animal in it.
        """
        if _PLACED_BEFORE.search(str(pet.get("previous_status") or "")):
            return ""
        return listing_date(pet.get("created_at"), born=pet.get("date_of_birth"))

    def _apply_detail(self, dog: Dog, pet: dict) -> None:
        """Add the shelter's structured trait flags, and any photos we missed."""
        attributes = list(dog.attributes)
        for key, yes_label, no_label in _TRAIT_FLAGS:
            state = _flag(pet.get(key))
            label = yes_label if state is True else (no_label if state is False
                                                    else None)
            if label and label not in attributes:
                attributes.append(label)
        dog.attributes = attributes

        if not dog.fee:
            dog.fee = self._fee(pet.get("adoption_fee"))

        detail_photos = [
            p.get("main_photo_url") or p.get("thumb_url")
            for p in (pet.get("photos") or []) if isinstance(p, dict)
        ]
        for src in detail_photos:
            if (isinstance(src, str) and src and src not in dog.photos
                    and not _is_placeholder(src)):
                dog.photos.append(src)

    def recheck_photos(self, dogs) -> int:
        """Second look at the detail record for dogs the listing had no photo for."""
        targets = [d for d in dogs if d.source == self.name and not d.photos]
        if not targets:
            return 0
        gained = 0
        with self._session() as session:
            for dog in targets:
                try:
                    pet = self._detail(session, dog)
                    if pet:
                        self._apply_detail(dog, pet)
                    if dog.photos:
                        gained += 1
                except Exception:
                    pass
                time.sleep(DETAIL_DELAY_SECONDS)
        return gained
