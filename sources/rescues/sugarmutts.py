"""Sugar Mutts Rescue — direct scraper.

Site: WordPress (theme "sugarmutts"), listing at
  https://www.sugarmuttsrescue.com/sugar-mutts-rescue/our-dogs/

HOW THE DATA IS REACHED
-----------------------
The WP REST API *is* reachable (a plain curl gets HTTP 406 from mod_security;
sending a real browser User-Agent + Accept headers gets HTTP 200), but it is
NOT useful as the primary source here:

  * /wp-json/wp/v2/types has no custom "dog" post type — only the stock
    post/page/attachment/... set.
  * The listing lives on page id 35, whose REST `content.rendered` is EMPTY
    (the theme builds the markup from a custom PHP template, not post content).

So the listing page HTML is the real source. Each dog is a
`div.container` holding `div.row > div.col-6` (photo column) +
`div.col-6` (text column with `h1` name, a "Quick Facts" `ul`, an optional
"Description" `p`, and a "View Dog" `button`).

Two things the markup does that a naive scraper gets wrong:

 1. EVERY dog is rendered TWICE — once in a mobile block (`div.container.d-lg-none`)
    and once in a desktop block (bare `div.container`). We de-duplicate on the
    WordPress post id.
 2. Adopted dogs stay on the page with the status appended to the name
    (e.g. "Frida - ADOPTED!"). Those are excluded.

The "View Dog" button carries the WP post id
(`location.href='...?post_type=post&p=1366'`), which gives us a STABLE id that
survives renames. We optionally upgrade those to pretty permalinks
(e.g. /oakley/) with one batched REST call; if that call fails we keep the
`?post_type=post&p=<id>` form, which resolves fine on its own.
"""
import re
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

from ..base import Dog, Source, clean_text

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30

# Words that mean "this dog is no longer available".
_UNAVAILABLE = re.compile(
    r"\b(adopted|pending|on hold|no longer available|not available|rehomed)\b",
    re.I,
)

# location.href='https://www.sugarmuttsrescue.com/?post_type=post&p=1366'
_POST_ID = re.compile(r"[?&]p=(\d+)")

# Quick Facts spell size in title case and sometimes straddle two buckets
# ("Medium/Large"). Normalize onto the small/medium/large/xlarge scale the
# other sources and the matcher already share; take the larger of a pair so we
# never undersell a big dog to someone filtering for small.
_SIZE_WORDS = (("x-large", "xlarge"), ("xlarge", "xlarge"),
               ("extra large", "xlarge"), ("large", "large"),
               ("medium", "medium"), ("small", "small"))


def _normalize_size(raw: str) -> str:
    text = (raw or "").strip().lower()
    for word, bucket in _SIZE_WORDS:
        if word in text:
            return bucket
    return ""


class SugarMuttsSource(Source):
    name = "sugarmutts"
    label = "Sugar Mutts Rescue"
    priority = 13
    # NOTE: the /adopt/ path 404s. The real adoption page is "how-to-adopt".
    adopt_url = "https://www.sugarmuttsrescue.com/sugar-mutts-rescue/how-to-adopt"

    LISTING_URL = "https://www.sugarmuttsrescue.com/sugar-mutts-rescue/our-dogs/"
    REST_POSTS = "https://www.sugarmuttsrescue.com/wp-json/wp/v2/posts"
    BASE = "https://www.sugarmuttsrescue.com"

    def enabled(self, prefs: dict) -> bool:
        return True

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _card_root(col):
        """Nearest enclosing `div.container` — the whole card for one dog.

        Both layouts nest the text column two levels below it
        (desktop  `div.container > div.row > div.col-6`,
         mobile   `div.container.d-lg-none > div.row > div.col-10`),
        and neither text column itself carries the `container` class, so the
        first match walking up is always the card. Bounded so that a markup
        change can never walk us all the way out to <body> and hand every
        image on the page to a single dog.
        """
        node = col
        for _ in range(4):
            node = node.parent
            if node is None or node.name == "body":
                return None
            if "container" in (node.get("class") or []):
                return node
        return None

    def _quick_facts(self, col) -> Dict[str, str]:
        """Parse the 'Quick Facts' <ul> into {label: value}."""
        facts: Dict[str, str] = {}
        for ul in col.find_all("ul"):
            for li in ul.find_all("li"):
                txt = clean_text(li.get_text(" ", strip=True))
                if ":" not in txt:
                    continue
                key, _, val = txt.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key and val:
                    facts[key] = val
        return facts

    def _description(self, col) -> str:
        """Text of the <p> blocks that follow the 'Description' heading."""
        parts: List[str] = []
        for h in col.find_all(["h4", "h5", "h6"]):
            if "description" not in h.get_text(strip=True).lower():
                continue
            for sib in h.find_next_siblings():
                if sib.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    break
                if sib.name == "p":
                    parts.append(sib.get_text(" ", strip=True))
            break
        if not parts:  # fall back to any paragraph in the column
            parts = [p.get_text(" ", strip=True) for p in col.find_all("p")]
        text = "\n\n".join(p for p in parts if p)
        # Paragraph bodies are authored with Windows line endings; drop the
        # carriage returns so clean_text can collapse the blank lines.
        return clean_text(text.replace("\r\n", "\n").replace("\r", "\n"))

    def _photos(self, container) -> List[str]:
        """Main photo first, then the thumbnail strip; de-duplicated."""
        photos: List[str] = []

        def add(src: str) -> None:
            if not src:
                return
            src = requests.compat.urljoin(self.BASE, src.strip())
            if src not in photos:
                photos.append(src)

        for img in container.select("img.main-img"):
            add(img.get("src", ""))
        for img in container.select("img.thumbnail-img"):
            # the thumb's data-main-img-src is the full-size hero image
            add(img.get("data-main-img-src", ""))
            add(img.get("src", ""))
        if not photos:
            for img in container.find_all("img"):
                add(img.get("src", ""))
        return photos

    def _pretty_links(self, post_ids: List[str]) -> Dict[str, str]:
        """Best-effort: batch-resolve WP post ids to pretty permalinks."""
        if not post_ids:
            return {}
        try:
            resp = requests.get(
                self.REST_POSTS,
                params={
                    "include": ",".join(post_ids),
                    "per_page": 100,
                    "_fields": "id,link",
                },
                headers={**HEADERS, "Accept": "application/json"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return {
                str(item["id"]): item["link"]
                for item in resp.json()
                if item.get("id") and item.get("link")
            }
        except Exception:
            return {}  # non-fatal: the ?p=<id> URL works fine

    # ------------------------------------------------------------------ fetch

    def fetch(self, prefs: dict) -> List[Dog]:
        try:
            resp = requests.get(self.LISTING_URL, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        raw: List[dict] = []
        seen_ids = set()

        # Anchor on each dog's name heading; the surrounding .container is the card.
        for h1 in soup.find_all("h1"):
            col = h1.parent
            if col is None:
                continue
            container = self._card_root(col)
            if container is None:
                continue

            heading = clean_text(h1.get_text(" ", strip=True))
            if not heading:
                continue

            facts = self._quick_facts(col)
            btn = col.find("button")
            onclick = btn.get("onclick", "") if btn else ""
            m = _POST_ID.search(onclick)

            # A real dog card has Quick Facts and/or a View Dog link.
            if not facts and not m:
                continue

            # --- availability filter -------------------------------------
            # Only look at the NAME and the quick-facts block. The free-text
            # description can innocently contain the word "adopted".
            status_text = heading + " " + " ".join(facts.values())
            if _UNAVAILABLE.search(status_text):
                continue

            post_id = m.group(1) if m else ""
            # Strip any trailing status decoration from the display name.
            dog_name = re.split(r"\s*[-–—]\s*", heading)[0].strip() or heading

            stable = post_id or re.sub(r"[^a-z0-9]+", "-", dog_name.lower()).strip("-")
            if not stable or stable in seen_ids:
                continue  # mobile/desktop duplicate
            seen_ids.add(stable)

            raw.append({
                "post_id": post_id,
                "stable": stable,
                "name": dog_name,
                "facts": facts,
                "description": self._description(col),
                "photos": self._photos(container),
            })

        links = self._pretty_links([r["post_id"] for r in raw if r["post_id"]])

        dogs: List[Dog] = []
        for r in raw:
            facts = r["facts"]
            if r["post_id"]:
                url = links.get(
                    r["post_id"],
                    f"{self.BASE}/?post_type=post&p={r['post_id']}",
                )
            else:
                url = self.LISTING_URL

            attributes = []
            if facts.get("color"):
                attributes.append(f"Color: {facts['color']}")

            dogs.append(Dog(
                id=f"{self.name}:{r['stable']}",
                name=r["name"],
                source=self.name,
                source_label=self.label,
                url=url,
                photos=r["photos"],
                breed=facts.get("breed", ""),
                age=facts.get("age", ""),
                sex=facts.get("sex", ""),
                size=_normalize_size(facts.get("size", "")),
                weight=facts.get("weight", ""),
                location=facts.get("location", ""),
                description=r["description"],
                attributes=attributes,
                adopt_url=self.adopt_url,
            ))
        return dogs
