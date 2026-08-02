"""Adopt-a-Pet — the second platform LUVD reads, after Petstablished.

Roughly 440 Los Angeles-area dog organisations list here (22 pages of 20 on
``/dog-shelters/california/los-angeles``), including several that the
Petstablished sweep of 2026-07-30 had to reject for having no route. Like
``petstablished.py`` this is a base class: a rescue on Adopt-a-Pet costs a
subclass with one ``shelter_path``, not a new scraper.

There is no public API, but there is something nearly as good. The pages are
Next.js server components, so every field the page renders is already in the
HTML as React Flight data, split across a series of

    self.__next_f.push([1,"<escaped json fragment>"])

calls. Concatenating those fragments and unescaping them yields the pet record
the page was built from — ``petStory`` (the rescue's own write-up),
``petAttributes``, ``petTraits``, ``petPhotos``, and the rescue's own
application URL. That is richer than anything scraped out of the rendered
markup, and it does not break when they restyle a card.

Two requests per dog's worth of work: one for the shelter's roster page, then
one per dog for its record. The roster page carries only name, breed, sex and
age, and the write-up is what ``enrich.py`` reads to rate energy and apartment
fit — so a roster-only read would give every dog breed-baseline ratings and
nothing else.

Verified 2026-08-02 against Outta the Cage (7 listings) and The HIT Living
Foundation (5).
"""
import json
import re
import time
from typing import List, Optional

import requests

from .base import Dog, Source, clean_text
from .dates import listing_date

BASE = "https://www.adoptapet.com"
# A browser UA. Adopt-a-Pet serves the Flight payload to anything, but a bare
# python-requests UA is the kind of thing a WAF turns away on a bad day.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}

# Dogs are species 1. The roster page of a rescue that also does cats lists
# both, and a cat in a dog product is worse than a missing dog.
_SPECIES_DOG = 1

# Photos are addressed by id through their image CDN, which is what the site's
# own <img> tags use. 900px wide is about what the modal's hero needs.
_PHOTO = "https://media.adoptapet.com/image/upload/f_auto,q_auto,w_900/{id}"

_PET_HREF = re.compile(r'href="(https://www\.adoptapet\.com/pet/(\d+)-[^"]*)"')
_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
# A long string is not stored inline; Flight emits it as its own chunk and
# leaves a "$<id>" pointer where the value was. Half of the write-ups arrive
# this way, so a reader that stops at the pointer loses half the prose the
# ratings are derived from. The chunk announces its own length in hex bytes:
#     38:T31d,<the text>
_CHUNK = "(?m)^%s:T([0-9a-f]+),"

# Adopt-a-Pet's trait vocabulary -> the sentences normalize.py already
# classifies. Only the ones that mean something to an adopter; `purebred` is
# left out because it is a claim about pedigree, not about living with the dog.
_TRAITS = {
    "goodWithKids": "Good with kids",
    "goodWithDogs": "Good with dogs",
    "goodWithCats": "Good with cats",
    "housetrained": "House-trained",
    "spayedNeutered": "Spayed / neutered",
    "shotsCurrent": "Vaccinations up to date",
    "specialNeeds": "Special needs",
}
# The same flags when the rescue has explicitly said no. These are the ones an
# adopter needs before they apply rather than after, so a False is carried
# through rather than dropped as an absence.
_TRAITS_FALSE = {
    "goodWithKids": "Not good with kids",
    "goodWithDogs": "Not good with dogs",
    "goodWithCats": "Not good with cats",
}


def _flight_json(html: str) -> str:
    """The page's React Flight payload, concatenated and unescaped.

    The fragments are pieces of one JSON string that was chunked for streaming,
    so they have to be joined before unescaping — a fragment can split in the
    middle of an escape sequence, and unescaping them one at a time corrupts
    exactly those boundaries.
    """
    out = []
    for frag in _FLIGHT.findall(html):
        # Each fragment is itself a JSON string literal, so json.loads is the
        # decoder. Hand-rolled replaces are what a first pass reaches for and
        # they are wrong: turning every \\" into " also unquotes the quotes
        # inside a rescue's write-up, which ends the JSON string early and
        # loses the whole field.
        try:
            out.append(json.loads('"%s"' % frag))
        except Exception:
            continue
    return "".join(out)


def _field(blob: str, key: str) -> Optional[str]:
    """One JSON string value out of the payload, by key.

    A regex rather than json.loads because the payload is a stream of several
    concatenated documents, not one parseable object.
    """
    m = re.search(r'"%s":"((?:[^"\\]|\\.)*)"' % re.escape(key), blob)
    if not m:
        return None
    try:
        val = json.loads('"%s"' % m.group(1))
    except Exception:
        val = m.group(1)
    # React Flight escapes a literal "$" by doubling it, and uses a single
    # leading "$" for a reference to another chunk. "$$800" is an adoption fee;
    # "$38" is a pointer, and printing it would put "$38" on the page as though
    # it were one.
    if val.startswith("$$"):
        return val[1:]
    if re.fullmatch(r"\$[0-9a-fA-F]{1,4}", val):
        return _chunk(blob, val[1:])
    return val


def _chunk(blob: str, cid: str) -> Optional[str]:
    """The text of Flight chunk `cid`, or None if this page didn't ship it.

    The declared length is in UTF-8 bytes, not characters, so the slice is done
    on the encoded form — a write-up with an emoji in it is otherwise cut a few
    characters short, which is exactly the kind of truncation nobody notices
    until it is on the page.
    """
    m = re.search(_CHUNK % re.escape(cid), blob)
    if not m:
        return None
    raw = blob[m.end():].encode("utf-8", "surrogatepass")
    try:
        return raw[:int(m.group(1), 16)].decode("utf-8", "ignore")
    except ValueError:
        return None


def _int_field(blob: str, key: str) -> Optional[int]:
    m = re.search(r'"%s":(\d+)' % re.escape(key), blob)
    return int(m.group(1)) if m else None


def _json_array(blob: str, key: str) -> list:
    """The array value at `key`, brace-matched out of the surrounding stream."""
    i = blob.find('"%s":[' % key)
    if i < 0:
        return []
    start = blob.index("[", i)
    depth, j = 0, start
    while j < len(blob):
        if blob[j] == "[":
            depth += 1
        elif blob[j] == "]":
            depth -= 1
            if depth == 0:
                break
        j += 1
    try:
        return json.loads(blob[start:j + 1])
    except Exception:
        return []


def _blank(v: str) -> str:
    """The site renders an en dash for a field the rescue never filled in."""
    v = (v or "").strip()
    return "" if v in {"-", "\u2013", "\u2014", "--", "N/A", "Unknown"} else v


def _attrs(blob: str) -> dict:
    """petAttributes is a label/content list — Breed, Color, Age, Sex, Size."""
    out = {}
    for a in _json_array(blob, "petAttributes"):
        label = (a.get("label") or "").strip()
        content = (a.get("content") or "").strip()
        if label and content:
            out[label.lower()] = content
    return out


class AdoptAPetSource(Source):
    """Subclass with a `shelter_path`; see rescues/outtathecage.py."""

    shelter_path = ""             # "shelter/104110-..." or "adoption_rescue/..."
    priority = 300
    # Politeness gap between the per-dog requests. These rosters are small
    # (single digits), so this costs seconds, not minutes.
    pause = 0.4

    def _get(self, url: str) -> Optional[str]:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  {self.name}: {url.rsplit('/', 1)[-1][:40]} — "
                  f"{type(e).__name__}: {e}")
            return None

    def _pet_urls(self, html: str) -> List[str]:
        """Every distinct dog listing linked from the roster page.

        Ordered rather than a bare set: the roster is the rescue's own order and
        it costs nothing to keep it. The page also links each dog from a
        "similar pets" rail, hence the dedupe.
        """
        seen, out = set(), []
        for url, pid in _PET_HREF.findall(html):
            if pid in seen:
                continue
            seen.add(pid)
            out.append(url)
        return out

    def _to_dog(self, blob: str, url: str) -> Optional[Dog]:
        pid = _int_field(blob, "petId")
        name = _field(blob, "petName")
        if not pid or not name:
            return None
        if _int_field(blob, "petSpeciesId") != _SPECIES_DOG:
            return None
        # "available" is the only state that belongs on the page. Adopted and
        # on-hold records stay reachable at their own URLs.
        if (_field(blob, "petState") or "").lower() != "available":
            return None

        a = _attrs(blob)
        # petAttributes' Age reads "2 years 2 months old, Young" — the phrase
        # before the comma is the real one; the word after it is the bucket,
        # which page.py derives itself.
        age = (a.get("age") or "").split(",")[0].replace(" old", "").strip()

        photos = [_PHOTO.format(id=p["sourcePhotoId"])
                  for p in _json_array(blob, "petPhotos")
                  if p.get("sourcePhotoId")]
        if not photos:
            thumb = _field(blob, "petThumbnailUrl")
            if thumb:
                photos = [thumb]

        attributes = []
        for t in (_json_array(blob, "petTraits")
                  + _json_array(blob, "petHealthTraits")):
            kind, status = t.get("type"), t.get("status")
            if status is True and kind in _TRAITS:
                attributes.append(_TRAITS[kind])
            elif status is False and kind in _TRAITS_FALSE:
                attributes.append(_TRAITS_FALSE[kind])
        # "Goofy", "Playful" — the rescue's own words for the dog, and the only
        # personality signal on a record whose write-up may be boilerplate.
        for t in _json_array(blob, "petPersonalityTraits"):
            if t.get("name"):
                attributes.append(t["name"])

        story = clean_text(_field(blob, "petStory") or "")
        fee = (_field(blob, "adoptionCost") or "").strip() or None

        return Dog(
            id=f"{self.name}:{pid}",
            name=name.strip(),
            source=self.name,
            source_label=self.label,
            url=url,
            photos=photos,
            breed=(_field(blob, "petBreed") or a.get("breed") or "").strip(),
            age=age,
            sex=_blank(a.get("sex")),
            size=_blank(a.get("size")),
            weight=_blank((a.get("weight") or "").replace("(current)", "")),
            location=_blank(a.get("location")),
            description=story,
            attributes=attributes,
            fee=fee,
            # The rescue's own application page when the record names one, which
            # is the step they actually want an adopter to take.
            adopt_url=(_field(blob, "adoptionApplicationUrl")
                       or self.adopt_url or url),
            listed_since=listing_date(_field(blob, "petCreatedAt")),
        )

    def fetch(self, prefs: dict) -> List[Dog]:
        if not self.shelter_path:
            raise NotImplementedError(f"{self.name}: set shelter_path")
        roster = self._get(f"{BASE}/{self.shelter_path.lstrip('/')}")
        if not roster:
            return []
        urls = self._pet_urls(roster)
        dogs = []
        for i, url in enumerate(urls):
            if i:
                time.sleep(self.pause)
            page = self._get(url)
            if not page:
                continue
            try:
                dog = self._to_dog(_flight_json(page), url)
            except Exception as e:
                print(f"  {self.name}: could not read {url.rsplit('/', 1)[-1]}"
                      f" — {type(e).__name__}: {e}")
                continue
            if dog:
                dogs.append(dog)
        return dogs
