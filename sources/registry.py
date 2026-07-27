"""Registry of all sources, in priority order.

Direct rescue listings (priority 0-899) are preferred and checked first.
Petfinder's city-wide search (900) is the fallback that catches everything else.
"""
from typing import List

from .base import Source
from .petfinder import PetfinderSource, PetfinderOrgSource
from .rescues.muddypaws import MuddyPawsSource
from .rescues.animalhaven import AnimalHavenSource
from .rescues.petconnect import PetConnectSource

# Rescues we scrape directly from their own sites.
_DIRECT: List[Source] = [
    MuddyPawsSource(),     # 10 — public JSON API
    AnimalHavenSource(),   # 11 — server-rendered HTML (Shelterluv-backed)
    PetConnectSource(),    # 14 — 24PetConnect / Sean Casey
]

# Rescues whose own site blocks scraping, pulled via the sanctioned Petfinder API.
# Korean K9 Rescue sits behind a Cloudflare challenge; they publish as org NY1374.
_DIRECT_VIA_API: List[Source] = [
    PetfinderOrgSource(
        org_id="NY1374",
        name="koreank9",
        label="Korean K9 Rescue",
        priority=15,
        adopt_url="https://www.koreank9rescue.org/adopt/",
    ),
]

_FALLBACK: List[Source] = [PetfinderSource()]


def _try_optional():
    """Scrapers still being built land here without breaking the app."""
    extra = []
    try:
        from .rescues.waggytail import WaggytailSource
        extra.append(WaggytailSource())
    except Exception:
        pass
    try:
        from .rescues.sugarmutts import SugarMuttsSource
        extra.append(SugarMuttsSource())
    except Exception:
        pass
    return extra


def all_sources() -> List[Source]:
    sources = _DIRECT + _DIRECT_VIA_API + _try_optional() + _FALLBACK
    return sorted(sources, key=lambda s: s.priority)


def direct_sources() -> List[Source]:
    """Everything except the broad Petfinder fallback."""
    return [s for s in all_sources() if s.priority < 900]
