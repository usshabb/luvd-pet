"""Animal Haven (NYC) — HTML scraper.

The listing at https://animalhaven.org/adopt/dogs is fully server-rendered, so
a plain GET is enough. Each dog is an <article> whose class attribute is
bracket-decorated ("[ pet-preview ] [ stack ] [  ]"), so every selector here
matches on class *tokens* rather than exact class strings.

The listing card only carries name / age / sex / photo, so we follow each
dog's link to pick up the description, breed, weight, fee and gallery photos.
Detail fetches are polite (shared session, small delay) and best-effort: a dog
whose detail page fails is still returned with its listing data.

NO LISTING DATE (checked 2026-07-28)
------------------------------------
``listed_since`` is deliberately left empty: there is no date anywhere in this
feed. The pages are HubSpot dynamic pages over a HubDB table synced from
ShelterLuv, and the row's own createdAt is the only candidate — table 6527631
answers "not publicly available" without a portal token, and neither the
listing markup, the detail markup, the meta tags nor sitemap.xml carries a
date. ``first_seen`` therefore carries these dogs, which for Animal Haven is
not a bad fit: their write-ups say "I just arrived at Animal Haven!" while the
photos are still pending, so most of this roster is genuinely new.
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Optional

from ..base import Dog, Source, clean_text

SITE = "https://animalhaven.org"
LISTING_URL = f"{SITE}/adopt/dogs"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

DETAIL_DELAY_SECONDS = 0.3
TIMEOUT = 30

# Dogs with no real photo fall back to a stock image — the listing card uses
# animalhaven.org/.../placeholder--dog.png, while the detail gallery uses
# ShelterLuv's .../profile_photo/default_dog.png. Better to have no photo than
# a fake one, so both are dropped and `photos` is left empty.
_PLACEHOLDER_RE = re.compile(r"placeholder|default_dog|profile_photo/default", re.I)
_ID_RE = re.compile(r"/(\d+)-")

_SIZE_BUCKETS = ((25, "small"), (60, "medium"), (100, "large"))

# Breed strings often carry the shelter's own adult-size class, e.g.
# "Retriever/Mixed Breed (Medium)". That beats inferring from current weight,
# which badly understates puppies.
_SIZE_HINT_RE = re.compile(r"\((small|medium|large|x-?large)\)", re.I)


_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _classes(tag) -> List[str]:
    return tag.get("class") or []


def _has_class(tag, token: str) -> bool:
    """True if `token` is one of the tag's class tokens.

    Animal Haven writes class="[ pet-preview ] [ stack ]", which BeautifulSoup
    splits into ['[', 'pet-preview', ']', ...] — so token membership works, but
    exact string equality never would.
    """
    return token in _classes(tag)


def _find_all_by_class(root, token: str, name=None):
    return [t for t in root.find_all(name or True) if _has_class(t, token)]


def _find_by_class(root, token: str, name=None):
    for tag in root.find_all(name or True):
        if _has_class(tag, token):
            return tag
    return None


def _collapse(text: str) -> str:
    """'3\\n        years' -> '3 years'."""
    return " ".join((text or "").split())


def _size_from_weight(pounds: Optional[float]) -> str:
    if pounds is None:
        return ""
    for limit, label in _SIZE_BUCKETS:
        if pounds < limit:
            return label
    return "xlarge"


def _size_from_breed(breed: str) -> str:
    match = _SIZE_HINT_RE.search(breed or "")
    if not match:
        return ""
    return match.group(1).lower().replace("-", "")


def _fmt_number(text: str) -> str:
    """'27.0' -> '27', '49.3' -> '49.3'."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(value)) if value.is_integer() else str(value)


class AnimalHavenSource(Source):
    name = "animalhaven"
    label = "Animal Haven"
    priority = 11
    adopt_url = "https://animalhaven.org/adopt"

    def enabled(self, prefs: dict) -> bool:
        return True

    def fetch(self, prefs: dict) -> List[Dog]:
        session = requests.Session()
        session.headers.update(_HEADERS)

        resp = session.get(LISTING_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = [a for a in soup.find_all("article") if _has_class(a, "pet-preview")]

        dogs: List[Dog] = []
        for card in cards:
            dog = self._from_card(card)
            if dog is None:
                continue
            # Enrich from the detail page; failures leave listing data intact.
            self._enrich(session, dog)
            time.sleep(DETAIL_DELAY_SECONDS)
            dogs.append(dog)
        return dogs

    # --- listing card --------------------------------------------------

    def _from_card(self, card) -> Optional[Dog]:
        link = _find_by_class(card, "pet-preview__link", name="a")
        href = link.get("href") if link else ""
        if not href:
            return None

        path = href.split("?")[0].split("#")[0]
        match = _ID_RE.search(path)
        if not match:
            return None
        dog_id = match.group(1)

        name_el = _find_by_class(card, "pet-preview__name")
        name = _collapse(name_el.get_text(" ", strip=True)) if name_el else ""

        age_el = _find_by_class(card, "pet-preview__age")
        age = _collapse(age_el.get_text(" ", strip=True)) if age_el else ""

        # The gender <div> holds an sr-only "Female." — scope to that div, since
        # the card's <a> also has an sr-only label ("View X's adoption info.").
        sex = ""
        gender_el = _find_by_class(card, "pet-preview__gender")
        if gender_el:
            sr = gender_el.find(class_="sr-only")
            if sr:
                sex = _collapse(sr.get_text(" ", strip=True)).rstrip(".")

        photos = []
        img = _find_by_class(card, "pet-preview__photo", name="img")
        src = img.get("src") if img else ""
        if src and not _PLACEHOLDER_RE.search(src):
            photos.append(src)

        return Dog(
            id=f"{self.name}:{dog_id}",
            name=name or "Unknown",
            source=self.name,
            source_label=self.label,
            url=f"{SITE}{path}" if path.startswith("/") else path,
            photos=photos,
            age=age,
            sex=sex,
            location="New York, NY",
            adopt_url=self.adopt_url,
        )

    def recheck_photos(self, dogs) -> int:
        """Retry the detail page for dogs still missing a photo.

        Cheap — it's a handful of dogs — and it recovers both transient
        failures and genuine new uploads between runs.
        """
        targets = [d for d in dogs if d.source == self.name and not d.photos]
        if not targets:
            return 0
        gained = 0
        with requests.Session() as session:
            session.headers.update(_HEADERS)
            for dog in targets:
                try:
                    self._enrich(session, dog)
                    if dog.photos:
                        gained += 1
                except Exception:
                    pass
                time.sleep(0.35)
        return gained

    # --- detail page ---------------------------------------------------

    def _enrich(self, session: requests.Session, dog: Dog) -> None:
        try:
            resp = session.get(dog.url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return  # keep the listing-only dog
        try:
            self._apply_detail(dog, BeautifulSoup(resp.text, "html.parser"))
        except Exception:
            return  # never let one malformed page kill the run

    def _apply_detail(self, dog: Dog, soup: BeautifulSoup) -> None:
        profile = _find_by_class(soup, "pet-profile", name="section") or soup

        desc_el = _find_by_class(profile, "pet-profile__description-text")
        if desc_el:
            description = clean_text(desc_el.get_text("\n", strip=True))
            if description:
                dog.description = description

        # Subtitle <ul>: [sex, breed, age]. Breed is the item that isn't the
        # gender item and doesn't lead with the bullet used for age.
        subtitle = _find_by_class(profile, "pet-profile__subtitle", name="ul")
        if subtitle:
            for item in subtitle.find_all("li"):
                text = _collapse(item.get_text(" ", strip=True))
                if not text or _has_class(item, "pet-profile__subtitle-item--gender"):
                    continue
                if text.startswith("•"):
                    continue  # age, already taken from the listing card
                dog.breed = text
                break

        # Property blocks: Weight / Adoption Fee / Location.
        for prop in _find_all_by_class(profile, "pet-profile__property"):
            parts = [_collapse(c.get_text(" ", strip=True))
                     for c in prop.find_all(recursive=False)]
            parts = [p for p in parts if p]
            if len(parts) < 2:
                continue
            key, value = parts[0].rstrip(":").lower(), parts[1]
            if key == "weight":
                num = re.search(r"[\d.]+", value)
                if num:
                    dog.weight = f"{_fmt_number(num.group())} lbs"
                    dog.size = (_size_from_breed(dog.breed)
                                or _size_from_weight(float(num.group())))
                else:
                    dog.weight = value
            elif "fee" in key:
                dog.fee = value

        # Dogs with no listed weight can still get a size from the breed hint.
        if not dog.size:
            dog.size = _size_from_breed(dog.breed)

        # Gallery photos (main image + thumbnails), appended after the card photo.
        gallery = []
        for img in (_find_all_by_class(profile, "pet-gallery__image", name="img")
                    + _find_all_by_class(profile, "pet-gallery__thumbnail-image",
                                         name="img")):
            src = img.get("src")
            if src and not _PLACEHOLDER_RE.search(src):
                gallery.append(src)

        seen = set(dog.photos)
        for src in gallery:
            if src not in seen:
                seen.add(src)
                dog.photos.append(src)
