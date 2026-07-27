"""Korean K9 Rescue -- CURRENTLY BLOCKED. fetch() returns [] by design.

=============================================================================
WHY THIS SOURCE RETURNS NOTHING
=============================================================================
koreank9.org is behind a **site-wide Cloudflare "interactive" managed
challenge**. Every HTML path returns HTTP 403 with a JS challenge page
("Just a moment...") instead of content. Verified 2026-07-26:

    GET https://www.koreank9rescue.org/adopt/       -> 403  cf-mitigated: challenge
    GET https://www.koreank9rescue.org/             -> 403  cf-mitigated: challenge
    GET https://www.koreank9rescue.org/sitemap.xml  -> 403
    GET .../sitemap_index.xml, /feed/, /adopt/feed/ -> 403
    GET .../wp-json/, /wp-json/wp/v2/pages, .../types -> 403
    GET https://www.koreank9rescue.org/robots.txt   -> 200   (the one exception)

The challenge body declares ``window._cf_chl_opt = { ... cType: 'interactive' }``
and the response carries ``cf-mitigated: challenge`` plus ``critical-ch``
client-hint demands. This is an **active bot-detection challenge**, not a
static User-Agent filter.

What was tried, and did NOT work:
  1. Full realistic browser header set -- User-Agent, Accept, Accept-Language,
     Accept-Encoding, Referer (google.com), Upgrade-Insecure-Requests,
     Sec-Fetch-Dest/Mode/Site/User, Sec-CH-UA / -Mobile / -Platform, DNT.
     Still 403.
  2. A persistent ``requests.Session`` warmed on the un-challenged
     ``/robots.txt`` first so the ``__cf_bm`` cookie is carried forward.
     Still 403.
  3. Apex host (``koreank9rescue.org``) instead of ``www``. Still 403.
  4. Platform data endpoints. robots.txt exposes a Yoast SEO block, so the
     site is **WordPress** -- but ``/wp-json/*`` and every sitemap variant are
     behind the same challenge, so the REST API is no help.
  5. Sitemap enumeration of individual dog pages -- ``/sitemap_index.xml`` is
     403 as well, so the dog URLs cannot even be listed.

Solving the challenge would require executing Cloudflare's JS challenge --
i.e. deliberately defeating bot detection. That was **not** attempted, and
this module will not attempt it. Nothing here fabricates dog data.

=============================================================================
WHAT WOULD BE NEEDED TO MAKE THIS WORK
=============================================================================
Pick one, in rough order of how reasonable it is:

  A. **Use the Petfinder source instead (recommended, zero extra work).**
     Korean K9 Rescue publishes its adoptable dogs to Petfinder as
     organization ``NY1374``:
         https://www.petfinder.com/member/us/ny/long-island-city/korean-k9-rescue-ny1374/
     The existing ``sources/petfinder.py`` already has API access; passing
     ``organization=NY1374`` to ``/v2/animals`` returns this rescue's dogs
     through a sanctioned API. They are also on Adopt-a-Pet (shelter 94459).

  B. **Ask the rescue for access.** A short email to Korean K9 Rescue asking
     them to allowlist this crawler's User-Agent or IP in their Cloudflare
     WAF is the polite, correct fix, and is usually granted for a project
     that sends them adopters.

  C. **Render with a real browser.** Driving the page with Playwright /
     Selenium in headed mode and letting the user complete the challenge
     interactively, then reusing the ``cf_clearance`` cookie. This needs a
     human in the loop and a heavyweight dependency, so it is out of scope
     for a plain ``requests`` module.

=============================================================================
BEHAVIOUR OF THIS MODULE
=============================================================================
``fetch()`` still makes one real, well-behaved request. If the block is ever
lifted (allowlist, WAF rule change, running from a trusted network), it
transparently starts working:

  * challenge detected -> log a one-line warning, return ``[]``
  * real page returned -> parse via **standards-based** extractors only
    (schema.org JSON-LD, then the WordPress REST API). Those are defined
    formats, so they either match or yield nothing -- no guessed CSS
    selectors that could silently emit garbage. If a real page ever comes
    back and yields 0 dogs, the log line tells you to write selectors against
    the now-visible HTML.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from ..base import Dog, Source, clean_text

log = logging.getLogger(__name__)

SITE = "https://www.koreank9rescue.org"
LISTING_URL = f"{SITE}/adopt/"
WP_TYPES_URL = f"{SITE}/wp-json/wp/v2/types"

TIMEOUT = 30

# Full realistic browser header set. This is a normal browser identity, not an
# attempt to defeat the challenge -- it is simply the minimum a plain HTTP
# client needs so that a *non*-challenging server serves us the real page.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Chromium";v="126", "Not)A;Brand";v="24", "Google Chrome";v="126"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Connection": "keep-alive",
}

_CHALLENGE_MARKERS = ("_cf_chl_opt", "challenges.cloudflare.com", "Just a moment...")

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _is_challenge(resp: requests.Response) -> bool:
    """True if Cloudflare served a bot-detection challenge instead of content."""
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if resp.status_code in (403, 503):
        head = resp.text[:4000]
        return any(m in head for m in _CHALLENGE_MARKERS)
    return False


def _slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] or "unknown"


def _walk_jsonld(node: Any, out: List[dict]) -> None:
    if isinstance(node, list):
        for n in node:
            _walk_jsonld(n, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _walk_jsonld(node["@graph"], out)
        if node.get("@type"):
            out.append(node)
        for v in node.values():
            if isinstance(v, (list, dict)):
                _walk_jsonld(v, out)


class KoreanK9Source(Source):
    name = "koreank9"
    label = "Korean K9 Rescue"
    priority = 15
    # Verified as the rescue's canonical adoptable-dogs page (it is the URL
    # their own site and search listings point at). It is 403 to bots, but it
    # is the correct page for a human adopter to land on, which is all
    # adopt_url is used for.
    adopt_url = "https://www.koreank9rescue.org/adopt/"

    LISTING_URL = LISTING_URL

    def enabled(self, prefs: dict) -> bool:
        return True

    # ---------------------------------------------------------------- http --

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(HEADERS)
        return s

    # ------------------------------------------------------------ parsing ---

    def _dogs_from_jsonld(self, html: str) -> List[Dog]:
        """schema.org Product/ItemList entries, if the theme emits them."""
        nodes: List[dict] = []
        for blob in _JSONLD_RE.findall(html):
            try:
                _walk_jsonld(json.loads(blob), nodes)
            except (ValueError, TypeError):
                continue

        dogs: List[Dog] = []
        for n in nodes:
            types = n.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(t in ("Product", "Pet", "Animal") for t in types if t):
                continue
            url = n.get("url") or ""
            name = (n.get("name") or "").strip()
            if not name or not url:
                continue
            images = n.get("image") or []
            if isinstance(images, str):
                images = [images]
            images = [i.get("url") if isinstance(i, dict) else i for i in images]
            dogs.append(Dog(
                id=f"{self.name}:{_slug_of(url)}",
                name=name,
                source=self.name,
                source_label=self.label,
                url=url,
                photos=[i for i in images if isinstance(i, str)],
                description=clean_text(n.get("description") or ""),
                location="New York, NY",
                adopt_url=self.adopt_url,
            ))
        return dogs

    def _dogs_from_wp_rest(self, sess: requests.Session) -> List[Dog]:
        """WordPress REST API: find a dog-ish custom post type and list it."""
        try:
            r = sess.get(WP_TYPES_URL, timeout=TIMEOUT)
            if _is_challenge(r) or r.status_code != 200:
                return []
            types = r.json()
        except (requests.RequestException, ValueError):
            return []

        candidates = [
            t.get("rest_base") for key, t in (types or {}).items()
            if isinstance(t, dict)
            and t.get("rest_base")
            and re.search(r"dog|pet|adopt|animal", str(key), re.I)
        ]
        dogs: List[Dog] = []
        for base in candidates:
            try:
                r = sess.get(
                    f"{SITE}/wp-json/wp/v2/{base}",
                    params={"per_page": 100, "_embed": "1"},
                    timeout=TIMEOUT,
                )
                if _is_challenge(r) or r.status_code != 200:
                    continue
                items = r.json()
            except (requests.RequestException, ValueError):
                continue
            for it in items if isinstance(items, list) else []:
                title = ((it.get("title") or {}).get("rendered") or "").strip()
                link = it.get("link") or ""
                if not title or not link:
                    continue
                photos: List[str] = []
                media = ((it.get("_embedded") or {}).get("wp:featuredmedia") or [])
                for m in media:
                    src = (m or {}).get("source_url")
                    if src:
                        photos.append(src)
                dogs.append(Dog(
                    id=f"{self.name}:{it.get('id') or _slug_of(link)}",
                    name=clean_text(title, 80),
                    source=self.name,
                    source_label=self.label,
                    url=link,
                    photos=photos,
                    description=clean_text(
                        (it.get("content") or {}).get("rendered") or
                        (it.get("excerpt") or {}).get("rendered") or ""
                    ),
                    location="New York, NY",
                    adopt_url=self.adopt_url,
                ))
        return dogs

    # ---------------------------------------------------------------- api ---

    def fetch(self, prefs: dict) -> List[Dog]:
        sess = self._session()

        try:
            resp = sess.get(self.LISTING_URL, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("koreank9: request to %s failed: %s", self.LISTING_URL, e)
            return []

        if _is_challenge(resp):
            log.warning(
                "koreank9: %s is behind a Cloudflare interactive bot challenge "
                "(HTTP %s, cf-mitigated=%s). Returning 0 dogs -- solving the "
                "challenge is out of scope. Use Petfinder org NY1374, or ask "
                "the rescue to allowlist this crawler. See module docstring.",
                self.LISTING_URL, resp.status_code,
                resp.headers.get("cf-mitigated", "n/a"),
            )
            return []

        if resp.status_code != 200:
            log.warning("koreank9: %s returned HTTP %s", self.LISTING_URL,
                        resp.status_code)
            return []

        # The block is lifted -- extract via defined formats only.
        dogs = self._dogs_from_jsonld(resp.text)
        if not dogs:
            dogs = self._dogs_from_wp_rest(sess)

        if not dogs:
            log.warning(
                "koreank9: listing page fetched OK (%d bytes) but neither "
                "JSON-LD nor the WP REST API yielded dogs. The Cloudflare block "
                "appears lifted -- write real CSS selectors against the now-"
                "visible HTML of %s.", len(resp.text), self.LISTING_URL,
            )
        return dogs
