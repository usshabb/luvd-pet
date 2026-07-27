"""Waggytail Rescue (NYC) — Petstablished/Wagtopia public JSON API source.

HOW THE DATA IS REACHED
-----------------------
waggytailrescue.org is a Wix site and its /adoptable-animals page renders NO
dog markup server-side — the body text is literally just the nav plus the
heading "Our Adoptable Animals". The inline `<script id="wix-warmup-data">`
holds only component/type metadata (no collection), and there is no Wix Data
collection behind the page. The listing is an embed, reached in four hops:

  1. The page's Wix component map marks `comp-kme3t4x5` as an `HtmlComponent`.
  2. That component's props live in the page-data JSON on
     siteassets.parastorage.com, which gives its iframe document URL:
     https://www-waggytailrescue-org.filesusr.com/html/ffde22_42fd...fb.html
  3. That document is a single line:
     <iframe src='https://awo.petstablished.com/organization/3856/widget/animals'>
  4. That widget is a Vue SPA (Wagtopia). Its bundle calls a public,
     unauthenticated JSON API — the one we use here:

     GET https://petstablished.com/api/v2/public/search/shelter_pets/3856
         ?animal=Dog&page=N            -> {"pets": [...], "total_page": N}
     GET https://petstablished.com/api/v2/public/search/pet/<pet_id>
         -> {"pet": {...}} with the richer per-animal record

So we skip the Wix page entirely at runtime and hit the API directly. The
Wix -> filesusr -> widget chain above is documented so that if Waggytail ever
re-points the embed, the ORG_ID below is the one thing to re-derive.

ORG_ID 3856 is confirmed as Waggytail: the sibling `shelter_show/3856`
endpoint returns organization_name "Waggytail Rescue", New York NY 10003,
adopt@waggytailrescue.org.

AVAILABILITY: the widget lists dogs in foster homes as adoptable, so
"Fostered" stays. We drop anything flagged `no_longer_available`, hidden from
public search, or whose status reads adopted/hold/pending.

PRIVACY: the detail endpoint also exposes internal fields (foster home street
addresses, intake and medical notes, microchip numbers). We deliberately read
only the public-facing subset and never copy `current_location` & friends into
a Dog.
"""
import re
from typing import List, Optional

import requests

from ..base import Dog, Source, clean_text

API = "https://petstablished.com/api/v2/public/search"
ORG_ID = "3856"

SITE = "https://www.waggytailrescue.org"
# The rescue has no per-dog page of its own — the Wix page is one iframe — so a
# dog's canonical listing is its Wagtopia profile. `public_url` on each record
# points at petstablished.com/public/search/pet/<id>, which 302s to this.
PET_PAGE = "https://www.wagtopia.com/search/pet?id={}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30
MAX_PAGES = 10          # guard against a runaway/looping total_page

# Statuses that mean "don't show this dog", even if no_longer_available is
# unset. Plain "Fostered" is fine — those dogs are still up for adoption.
_UNAVAILABLE_STATUS = re.compile(
    r"\b(adopted|hold|pending|deceased|transferred|returned)\b", re.I
)

# Values that mean "nobody filled this in" and must not reach the card.
_PLACEHOLDERS = {"not available", "unknown", "n/a", "na", "none", "-"}

# Petstablished size vocabulary -> the small/medium/large/xlarge scale the
# matcher and the Petfinder source already share.
_SIZES = {
    "small": "small",
    "medium": "medium",
    "large": "large",
    "x-large": "xlarge",
    "xlarge": "xlarge",
    "extra large": "xlarge",
}


class WaggytailSource(Source):
    name = "waggytail"
    label = "Waggytail Rescue"
    priority = 12
    adopt_url = f"{SITE}/adopt-a-waggytail"

    def enabled(self, prefs: dict) -> bool:
        return True  # public API, no credentials needed

    # ------------------------------------------------------------------ fetch

    def fetch(self, prefs: dict) -> List[Dog]:
        session = requests.Session()
        session.headers.update(HEADERS)
        try:
            records = self._listing(session)
        except (requests.RequestException, ValueError):
            # ValueError covers a 200 that isn't JSON (an error/interstitial
            # page). Either way the source is simply unavailable this run.
            return []

        dogs: List[Dog] = []
        seen = set()
        for rec in records:
            pet_id = rec.get("id") or rec.get("pet_id")
            if not pet_id or pet_id in seen:
                continue
            seen.add(pet_id)
            if not self._is_available(rec):
                continue
            # Best-effort enrichment; the listing record alone is enough.
            detail = self._detail(session, pet_id)
            dogs.append(self._to_dog(pet_id, rec, detail))
        return dogs

    def _listing(self, session: requests.Session) -> List[dict]:
        """All pages of `animal=Dog` for this organization."""
        records: List[dict] = []
        page = 1
        while page <= MAX_PAGES:
            resp = session.get(
                f"{API}/shelter_pets/{ORG_ID}",
                params={"animal": "Dog", "page": page},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                break
            pets = payload.get("pets")
            if not isinstance(pets, list) or not pets:
                break
            records.extend(p for p in pets if isinstance(p, dict))

            total = payload.get("total_page")
            if not isinstance(total, int) or page >= total:
                break
            page += 1
        return records

    def _detail(self, session: requests.Session, pet_id) -> dict:
        """Per-pet record: adds fee, weight, and the good-with flags.

        Non-fatal — a failure here just means a slightly sparser card, so we
        swallow everything rather than lose the whole source to one bad id.
        """
        try:
            resp = session.get(f"{API}/pet/{pet_id}", timeout=TIMEOUT)
            resp.raise_for_status()
            pet = resp.json().get("pet")
            return pet if isinstance(pet, dict) else {}
        except (requests.RequestException, ValueError):
            return {}

    # -------------------------------------------------------------- filtering

    @staticmethod
    def _is_available(rec: dict) -> bool:
        if rec.get("no_longer_available"):
            return False
        if rec.get("dont_show_in_public_search") or rec.get("hidden_by_petlover"):
            return False
        status = rec.get("status")
        if isinstance(status, str) and _UNAVAILABLE_STATUS.search(status):
            return False
        return True

    # ------------------------------------------------------- record -> Dog

    def _to_dog(self, pet_id, rec: dict, detail: dict) -> Dog:
        def pick(key, default=""):
            """Detail wins when it has a value, else the listing record."""
            for src in (detail, rec):
                val = src.get(key)
                if val not in (None, "", []):
                    return val
            return default

        raw_name = clean_text(str(pick("name", ""))) or "Unknown"
        # Volunteers decorate names with status shouts, e.g.
        # "Eden **FOSTER / FOSTER-TO-ADOPT**". Keep the plain name.
        name = re.sub(r"\s*\*{2}.*?\*{2}\s*", " ", raw_name).strip() or raw_name

        city = str(pick("city", "")).strip()
        state = str(pick("state", "")).strip().upper()
        location = ", ".join(p for p in (city, state) if p) or "New York, NY"

        return Dog(
            id=f"{self.name}:{pet_id}",
            name=name,
            source=self.name,
            source_label=self.label,
            url=PET_PAGE.format(pet_id),
            photos=self._photos(rec, detail),
            breed=self._breed(pick("primary_breed", ""),
                              pick("secondary_breed", ""),
                              pick("mix", False)),
            age=clean_text(str(pick("age", ""))),
            sex=clean_text(str(pick("sex", ""))),
            size=_SIZES.get(str(pick("size", "")).strip().lower(), ""),
            weight=self._weight(pick("weight", "")),
            location=location,
            # Descriptions are pasted-in HTML with Windows line endings; strip
            # the carriage returns before clean_text collapses blank lines.
            description=clean_text(
                str(pick("description", "")).replace("\r\n", "\n").replace("\r", "\n")
            ),
            attributes=self._attributes(detail),
            fee=self._fee(detail.get("adoption_fee")),
            adopt_url=self.adopt_url,
        )

    @staticmethod
    def _photos(rec: dict, detail: dict) -> List[str]:
        """Full-size photos in display order, cover image first.

        The detail record's `photos[]` carries `main_photo_url` plus an
        explicit `position`; the listing's `images[]` only has `thumb_url`.
        Prefer the former and fall back to the latter.
        """
        urls: List[str] = []

        photos = detail.get("photos")
        if isinstance(photos, list):
            ordered = sorted(
                (p for p in photos if isinstance(p, dict)),
                key=lambda p: p.get("position") or 0,
            )
            for p in ordered:
                url = p.get("main_photo_url") or p.get("thumb_url")
                if isinstance(url, str) and url:
                    urls.append(url)

        if not urls:
            for src in ([rec.get("thumb_url")] +
                        list(rec.get("images") or [])):
                url = src.get("thumb_url") if isinstance(src, dict) else src
                if isinstance(url, str) and url:
                    urls.append(url)

        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    @staticmethod
    def _breed(primary, secondary, is_mix) -> str:
        primary = clean_text(str(primary or ""))
        secondary = clean_text(str(secondary or ""))
        if primary.lower() in _PLACEHOLDERS:
            primary = ""
        if secondary.lower() in _PLACEHOLDERS:
            secondary = ""
        if primary and secondary and secondary != primary:
            return f"{primary} / {secondary}"
        if primary and is_mix:
            return f"{primary} Mix"
        return primary

    @staticmethod
    def _weight(value) -> str:
        """'5.0 pounds' -> '5 lbs'; '8lb' -> '8 lbs'."""
        text = str(value or "").strip()
        if not text:
            return ""
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)?\s*$", text, re.I)
        if not m:
            return clean_text(text)
        num = float(m.group(1))
        return f"{int(num) if num.is_integer() else num} lbs"

    @staticmethod
    def _fee(value) -> Optional[str]:
        text = str(value if value is not None else "").strip()
        if not text or text in ("0", "0.0"):
            return None
        if text.startswith("$"):
            return text
        try:
            num = float(text)
        except ValueError:
            return text
        return f"${int(num) if num.is_integer() else num}"

    @staticmethod
    def _attributes(detail: dict) -> List[str]:
        """Only the tri-state flags that are explicitly True/False.

        These are null on plenty of records, and "unknown" must not be shown
        as "not good with kids".
        """
        out: List[str] = []
        flags = (
            ("is_ok_with_other_dogs", "Good with dogs", "Not good with dogs"),
            ("is_ok_with_other_cats", "Good with cats", "Not good with cats"),
            ("is_ok_with_other_kids", "Good with kids", "Not good with kids"),
            ("is_housebroken", "House-trained", ""),
            ("is_spayed", "Spayed / neutered", ""),
            ("shots_up_to_date", "Vaccinations up to date", ""),
            ("is_hypoallergenic", "Hypoallergenic", ""),
        )
        for key, yes, no in flags:
            val = detail.get(key)
            if val is True and yes:
                out.append(yes)
            elif val is False and no:
                out.append(no)

        if detail.get("has_special_need"):
            need = clean_text(str(detail.get("special_needs") or ""))
            out.append(f"Special needs: {need}" if need else "Special needs")

        # `shedding` is a free-text-ish field ("Sheds a little") that also
        # carries placeholder values from the shelter's own UI.
        shedding = clean_text(str(detail.get("shedding") or ""))
        if shedding and shedding.lower() not in _PLACEHOLDERS:
            out.append(shedding)
        return out
