"""Muddy Paws Rescue (NYC) — public JSON API source.

Muddy Paws publishes its adoptable dogs through a public, unauthenticated JSON
endpoint that their own website consumes, so there is no HTML to scrape:

    GET https://mpr-public-api.uk.r.appspot.com/dogs  ->  JSON array of records

We filter to Status == "Available" AND ShowOnWebsite, then normalize into Dog.
"""
import requests
from typing import List, Optional

from ..base import Dog, Source, clean_text

API_URL = "https://mpr-public-api.uk.r.appspot.com/dogs"
SITE = "https://www.muddypawsrescue.org"
LISTING_URL = f"{SITE}/adoptable-dogs"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Weight -> size bucket, using the same vocabulary Petfinder returns
# (small/medium/large/xlarge) so the matcher sees one consistent scale.
_SIZE_BUCKETS = ((25, "small"), (60, "medium"), (100, "large"))


def _fmt_number(value) -> str:
    """120.0 -> '120', 55.5 -> '55.5'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _size_from_weight(pounds) -> str:
    if not isinstance(pounds, (int, float)):
        return ""
    for limit, label in _SIZE_BUCKETS:
        if pounds < limit:
            return label
    return "xlarge"


class MuddyPawsSource(Source):
    name = "muddypaws"
    label = "Muddy Paws Rescue"
    priority = 10
    adopt_url = "https://www.muddypawsrescue.org/adopt"

    def enabled(self, prefs: dict) -> bool:
        return True  # public API, no credentials needed

    def fetch(self, prefs: dict) -> List[Dog]:
        resp = requests.get(
            API_URL,
            timeout=30,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        resp.raise_for_status()
        records = resp.json()
        if not isinstance(records, list):
            return []

        dogs: List[Dog] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if rec.get("Status") != "Available" or not rec.get("ShowOnWebsite"):
                continue
            dog = self._to_dog(rec)
            if dog is not None:
                dogs.append(dog)
        return dogs

    # --- record -> Dog -------------------------------------------------

    def _to_dog(self, rec: dict) -> Optional[Dog]:
        # `ID` is a legacy key that is null on most current records (only the
        # oldest, pre-Salesforce dogs still carry one), while `Animal_ID` is
        # present and unique on every record. Prefer ID when it exists so those
        # dogs keep their historical id, else fall back to Animal_ID. Because a
        # record never gains an ID later, this stays stable run-to-run.
        raw_id = rec.get("ID") or rec.get("Animal_ID")
        if not raw_id:
            return None

        name = clean_text(rec.get("Name") or "") or "Unknown"

        photos = self._photos(rec)

        weight = ""
        pounds = rec.get("CurrentWeightPounds")
        if isinstance(pounds, (int, float)):
            weight = f"{_fmt_number(pounds)} lbs"

        fee = None
        raw_fee = rec.get("Fee")
        if isinstance(raw_fee, (int, float)):
            fee = f"${_fmt_number(raw_fee)}"
        elif isinstance(raw_fee, str) and raw_fee.strip():
            raw = raw_fee.strip()
            fee = raw if raw.startswith("$") else f"${raw}"

        # Attributes arrive with inline markup, e.g.
        # "Adult home preferred <br>(may consider older children)".
        attributes = []
        for attr in rec.get("Attributes") or []:
            if not isinstance(attr, str):
                continue
            cleaned = clean_text(attr).replace("\n", " ").strip()
            cleaned = " ".join(cleaned.split())
            if cleaned:
                attributes.append(cleaned)

        return Dog(
            id=f"{self.name}:{raw_id}",
            name=name,
            source=self.name,
            source_label=self.label,
            url=self._dog_url(rec),
            photos=photos,
            breed=clean_text(rec.get("Breed") or ""),
            age=clean_text(rec.get("Age") or ""),
            sex=clean_text(rec.get("Sex") or ""),
            size=_size_from_weight(pounds),
            weight=weight,
            location="New York, NY",
            description=clean_text(rec.get("Description") or ""),
            attributes=attributes,
            fee=fee,
            adopt_url=self.adopt_url,
        )

    @staticmethod
    def _photos(rec: dict) -> List[str]:
        """Photos list, with CoverPhoto guaranteed first."""
        photos = [p for p in (rec.get("Photos") or []) if isinstance(p, str) and p]
        cover = rec.get("CoverPhoto")
        if isinstance(cover, str) and cover:
            if cover in photos:
                photos.remove(cover)
            photos.insert(0, cover)
        # de-dupe, preserving order
        seen = set()
        unique = []
        for p in photos:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    @staticmethod
    def _dog_url(rec: dict) -> str:
        """Per-dog page URL.

        The adoptable-dogs grid on muddypawsrescue.org builds each card link as
        `/adoptable?dog=${allDogs[i].Animal_ID}` (confirmed in that page's
        source), and that URL resolves 200 with the dog rendered client-side.
        If Animal_ID is missing we fall back to the full listing page.
        """
        animal_id = rec.get("Animal_ID")
        if animal_id:
            return f"{SITE}/adoptable?dog={animal_id}"
        return LISTING_URL
