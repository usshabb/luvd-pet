"""Common Dog model and Source interface for LUVD.

Every source (a direct rescue scraper, Petfinder, etc.) returns a list of Dog
objects in ONE normalized shape. The UI renders the same modal regardless of
where a dog came from — fields that are missing simply don't render, so a
sparse source never produces a broken-looking card.

Sources are tried in PRIORITY ORDER (lowest number first). Direct rescue
listings are preferred; Petfinder is the fallback.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from cities import DEFAULT_CITY


@dataclass
class Dog:
    # --- identity (required) ---
    id: str                       # stable, source-prefixed: "muddypaws:2754"
    name: str
    source: str                   # machine key: "muddypaws"
    source_label: str             # display name: "Muddy Paws Rescue"
    url: str                      # link to this dog's listing

    # --- the headline facts (shown on the card) ---
    photos: List[str] = field(default_factory=list)
    breed: str = ""
    age: str = ""
    sex: str = ""
    size: str = ""

    # --- modal detail (all optional; render only what exists) ---
    weight: str = ""
    location: str = ""
    description: str = ""
    attributes: List[str] = field(default_factory=list)  # e.g. "Good with cats"
    traits: List[dict] = field(default_factory=list)     # [{text, kind}] from normalize
    fee: Optional[str] = None

    # --- the CTA: where to actually inquire about this dog ---
    adopt_url: str = ""           # rescue's adopt/contact page; falls back to url

    # --- placement programs that aren't a plain adoption ---
    # Some rescues place dogs through a named program with a different
    # application and a different commitment. Korean K9's foster-to-adopt dogs
    # are still in South Korea, so "apply and go meet the dog" is wrong for
    # them. When set, the UI leads with this instead of the usual apply button.
    program: str = ""             # machine key, e.g. "foster-to-adopt"
    program_label: str = ""       # chip text, e.g. "Foster-to-adopt"
    program_note: str = ""        # what the adopter is committing to

    # --- filled in by the pipeline, not by sources ---
    # Which city's shelters this dog belongs to, as a cities.py code. Stamped in
    # check.py's collect() from the source's own `city`, so a scraper only sets
    # it when one rescue places dogs in more than one city.
    #
    # Deliberately NOT Dog.location: that is free-text modal detail and it is
    # New-York-baked, several sources falling back to "New York, NY" when the
    # feed has no city (sources/rescues/animalhaven.py, muddypaws.py,
    # petconnect.py, petstablished.py, waggytail.py) and normalize.py rewriting
    # anything New-York-shaped into a borough. A Los Angeles rescue on the
    # Petstablished platform would come out reading "New York, NY", so location
    # cannot be the thing that decides who gets mailed.
    city: str = ""
    first_seen: str = ""          # YYYY-MM-DD the dog first appeared on LUVD
    listed_since: str = ""        # YYYY-MM-DD the RESCUE published it, when known
    scores: dict = field(default_factory=dict)      # energy/apartment/experience, 1-5
    quip: str = ""                # playful first-person card line, grounded in the bio
    breed_key: Optional[str] = None
    breed_info: dict = field(default_factory=dict)
    size_outlook: dict = field(default_factory=dict)
    monthly_cost: dict = field(default_factory=dict)

    def primary_photo(self) -> str:
        return self.photos[0] if self.photos else ""

    def cta_url(self) -> str:
        return self.adopt_url or self.url

    def dedupe_key(self) -> str:
        """Secondary guard against the same dog appearing across two sources."""
        return f"{self.name.strip().lower()}|{self.breed.strip().lower()[:20]}"

    def reprint_key(self) -> str:
        """One dog entered twice in a single rescue's own feed.

        Far stricter than dedupe_key, because within a source we normally trust
        the id and two dogs may legitimately share a name. A shared cover photo
        *and* a shared name is a re-entered record rather than a coincidence,
        and it's the only within-source match safe enough to act on. Empty when
        there's no photo to compare, which means "don't guess".
        """
        photo = self.primary_photo()
        return f"{self.name.strip().lower()}|{photo}" if photo else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "source": self.source,
            "source_label": self.source_label, "url": self.url,
            "photos": self.photos, "breed": self.breed, "age": self.age,
            "sex": self.sex, "size": self.size, "weight": self.weight,
            "location": self.location, "description": self.description,
            "attributes": self.attributes, "traits": self.traits, "fee": self.fee,
            "first_seen": self.first_seen, "listed_since": self.listed_since,
            "cta_url": self.cta_url(), "quip": self.quip,
            "program": self.program, "program_label": self.program_label,
            "program_note": self.program_note,
            "scores": self.scores, "breed_info": self.breed_info,
            "size_outlook": self.size_outlook,
            "monthly_cost": self.monthly_cost,
        }


class Source:
    """Base class. Subclass and implement fetch()."""

    name: str = "unnamed"
    label: str = "Unnamed Rescue"
    priority: int = 100           # lower = checked first / preferred
    adopt_url: str = ""           # rescue's general adopt/contact page
    # Which city this rescue's dogs belong to, as a cities.py code. Every
    # existing rescue inherits New York, so adding cities changed none of the
    # seven scrapers; a new city's scraper sets `city = "LA"` on one line beside
    # `name` and `label`, where its author is already typing.
    city: str = DEFAULT_CITY

    def fetch(self, prefs: dict) -> List[Dog]:
        raise NotImplementedError

    def enabled(self, prefs: dict) -> bool:
        return True

    def recheck_photos(self, dogs) -> int:
        """Second chance for dogs that came back without a photo.

        Detail-page enrichment is best-effort, so one timeout can leave a dog
        looking photoless when a photo exists. Sources that fetch photos from a
        detail page should retry just those dogs here. Returns how many gained
        a photo. Default: nothing to retry.
        """
        return 0


def clean_text(s: str, limit: int = 4000) -> str:
    """Normalize whitespace and strip stray HTML entities from descriptions."""
    import re
    import html as _html
    if not s:
        return ""
    s = _html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("﻿", "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[:limit]
