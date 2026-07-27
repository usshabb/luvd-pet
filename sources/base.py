"""Common Dog model and Source interface for LUVD NYC.

Every source (a direct rescue scraper, Petfinder, etc.) returns a list of Dog
objects in ONE normalized shape. The UI renders the same modal regardless of
where a dog came from — fields that are missing simply don't render, so a
sparse source never produces a broken-looking card.

Sources are tried in PRIORITY ORDER (lowest number first). Direct rescue
listings are preferred; Petfinder is the fallback.
"""
from dataclasses import dataclass, field
from typing import List, Optional


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

    # --- filled in by the pipeline, not by sources ---
    first_seen: str = ""          # YYYY-MM-DD the dog first appeared on LUVD
    listed_since: str = ""        # YYYY-MM-DD the RESCUE published it, when known
    scores: dict = field(default_factory=dict)      # energy/apartment/experience, 1-5
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

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "source": self.source,
            "source_label": self.source_label, "url": self.url,
            "photos": self.photos, "breed": self.breed, "age": self.age,
            "sex": self.sex, "size": self.size, "weight": self.weight,
            "location": self.location, "description": self.description,
            "attributes": self.attributes, "traits": self.traits, "fee": self.fee,
            "first_seen": self.first_seen, "listed_since": self.listed_since,
            "cta_url": self.cta_url(),
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
