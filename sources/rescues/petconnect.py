"""Sean Casey Animal Rescue, via the 24PetConnect / Petango platform.

HOW THIS SOURCE WORKS
---------------------
Sean Casey Animal Rescue (nyanimalrescue.org) does not host its own adoptable
list. Its /adopt page just links out to 24PetConnect (HLP Inc's "Petango"
platform), shelter code **PP1296**:

    https://24petconnect.com/PP1296?at=DOG

Investigation notes (verified 2026-07-26):

* The listing page is **fully server-rendered HTML** -- no JS, no XHR needed.
  Each animal is a ``<div class="gridResult" id="Result_<animalId>">`` block
  containing ``<span class="text_Name">``, ``text_Gender``, ``text_Breed``,
  ``text_Age``, ``text_Locatedat`` spans plus an ``<img>`` served from
  ``g.petango.com/photos/606/<uuid>.jpg``.
* There is NO public JSON endpoint on 24petconnect.com. The page's only AJAX
  calls are ``/Contact/SendRequestEmail`` and ``/PetHarbor/SubmitWebInterest``
  (both write-only contact forms). The legacy ``ws.petango.com`` /
  ``adoptableSearch.ashx`` webservices are key-gated and are not referenced by
  this page at all. Scraping the server-rendered HTML is therefore both the
  simplest and the most reliable route.
* Per-dog detail page. The grid's ``onclick`` is
  ``Details('PP1296','PP1296','<id>')`` -> ``/PP1296/Details/PP1296/<id>``,
  but the page also exposes a canonical shareable permalink used by its own
  share buttons / "copy link" box:

      https://24petconnect.com/DetailsMain/PP1296/<animalId>

  That one is a standalone page (~1/3 the size) and is what we link to and
  scrape for detail. It carries the long adopter-facing bio under
  ``line_MoreInfo``, all photo thumbnails, and the shelter address/phone.
* Pagination is ``?index=<n>&at=DOG`` (from the page's own ``createURLString``
  helper). Currently there is a single page, but we follow extra pages if the
  rescue ever lists more animals than fit on one.

Detail pages are fetched one extra request per dog (capped, and failures are
non-fatal -- we still return the grid-level data).
"""
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from ..base import Dog, Source, clean_text

BASE = "https://24petconnect.com"
SHELTER_CODE = "PP1296"
LISTING_URL = f"{BASE}/{SHELTER_CODE}?at=DOG"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30
MAX_PAGES = 10
MAX_DETAIL_FETCHES = 40      # safety valve: don't hammer them if the list explodes

# "Devlin (60233598)" -> "Devlin"
_NAME_ID_RE = re.compile(r"^\s*(.*?)\s*\((\d+)\)\s*$")
_FEE_RE = re.compile(r"adoption fee is\s*\$?([\d,]+(?:\.\d{2})?)", re.I)


def _txt(node, selector: str) -> str:
    """Text of the first child matching `selector`, or ''."""
    el = node.select_one(selector)
    return el.get_text(" ", strip=True) if el else ""


def _html_of(node, selector: str) -> str:
    el = node.select_one(selector)
    return el.decode_contents() if el else ""


class PetConnectSource(Source):
    name = "seancasey"
    label = "Sean Casey Animal Rescue"
    priority = 14
    # Verified: nyanimalrescue.org IS Sean Casey Animal Rescue, and /adopt is
    # the page that links out to this 24PetConnect listing.
    adopt_url = "https://www.nyanimalrescue.org/adopt"

    LISTING_URL = LISTING_URL

    def enabled(self, prefs: dict) -> bool:
        return True

    # ---------------------------------------------------------------- http --

    def _get(self, url: str) -> Optional[str]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        return resp.text

    # ------------------------------------------------------------- parsing --

    def detail_url(self, animal_id: str) -> str:
        return f"{BASE}/DetailsMain/{SHELTER_CODE}/{animal_id}"

    def _parse_listing(self, html: str) -> List[Dog]:
        soup = BeautifulSoup(html, "html.parser")
        dogs: List[Dog] = []

        for card in soup.select("div.gridResult"):
            card_id = card.get("id") or ""
            animal_id = card_id.replace("Result_", "").strip()

            raw_name = _txt(card, ".text_Name")
            m = _NAME_ID_RE.match(raw_name)
            if m:
                name = m.group(1)
                animal_id = animal_id or m.group(2)
            else:
                name = raw_name

            if not animal_id:
                continue
            if not name:
                name = "Unknown"

            img = card.select_one("img")
            src = img.get("src") if img else ""
            photos = [src] if src and "petango.com" in src else []

            dogs.append(Dog(
                id=f"{self.name}:{animal_id}",
                name=name,
                source=self.name,
                source_label=self.label,
                url=self.detail_url(animal_id),
                photos=photos,
                breed=_txt(card, ".text_Breed"),
                age=_txt(card, ".text_Age"),
                sex=_txt(card, ".text_Gender"),
                location=_txt(card, ".text_Locatedat") or "Brooklyn, NY",
                adopt_url=self.adopt_url,
            ))
        return dogs

    def _next_page_indexes(self, html: str) -> List[int]:
        """Page indexes referenced by the pager's MoreAnimals('<i>', ...) calls."""
        return sorted({
            int(i) for i in re.findall(r"MoreAnimals\(\s*'(\d+)'", html) if int(i) > 0
        })

    def _enrich(self, dog: Dog) -> None:
        """Pull description / extra photos / fee from the dog's detail page."""
        html = self._get(dog.url)
        if not html:
            return
        soup = BeautifulSoup(html, "html.parser")

        box = soup.select_one(".animalDetailsInfoBoxes") or soup

        # The adopter-facing bio lives in line_MoreInfo (prefixed with a
        # "I have been at the shelter since ..." sentence). line_Description is
        # a one-line auto-generated blurb; use it as the fallback.
        more = _html_of(box, ".line_MoreInfo .text_MoreInfo")
        desc = _html_of(box, ".line_Description .text_Description")
        body = clean_text(more) or clean_text(desc)
        if more and desc:
            short = clean_text(desc)
            # Keep the auto-blurb only when it adds something.
            if short and short.split("\n")[0] not in body:
                body = f"{short}\n\n{body}"
        if body:
            dog.description = body

        # Every thumbnail in the picture box (dedupe, keep order).
        photos: List[str] = list(dog.photos)
        for img in soup.select("#PictureBoxThumbs img, #FullImage"):
            src = img.get("src") or ""
            if "petango.com" in src and src not in photos:
                photos.append(src)
        dog.photos = photos

        located = _txt(box, ".line_LocatedAt .text_LocatedAt")
        if located:
            dog.location = located

        addr = _txt(soup, ".line_Address .text_Address")
        if addr:
            dog.attributes.append(f"Shelter address: {' '.join(addr.split())}")
        phone = _txt(soup, ".line_PhoneNumber .text_PhoneNumber")
        if phone:
            dog.attributes.append(f"Shelter phone: {phone}")

        fee = _FEE_RE.search(dog.description or "")
        if fee:
            dog.fee = f"${fee.group(1)}"

    # ---------------------------------------------------------------- api ---

    def fetch(self, prefs: dict) -> List[Dog]:
        html = self._get(self.LISTING_URL)
        if not html:
            return []

        dogs = self._parse_listing(html)
        seen: Dict[str, Dog] = {d.id: d for d in dogs}

        for idx in self._next_page_indexes(html)[:MAX_PAGES]:
            page = self._get(f"{BASE}/{SHELTER_CODE}?index={idx}&at=DOG")
            if not page:
                break
            for d in self._parse_listing(page):
                seen.setdefault(d.id, d)

        dogs = list(seen.values())

        for dog in dogs[:MAX_DETAIL_FETCHES]:
            try:
                self._enrich(dog)
            except Exception:
                pass          # detail is a bonus; never let it sink the source
            time.sleep(0.3)   # be polite to a small rescue's platform

        return dogs
