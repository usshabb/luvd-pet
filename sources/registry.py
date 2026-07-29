"""Registry of all sources, in priority order.

Rescues we scrape from their own sites come first (priority 0-899). Rescues
whose own site can't be read are pulled from the platform they actually adopt
on, which is the same data their site renders.

There is no city-wide fallback any more: that was the Petfinder API, which was
decommissioned on 2 December 2025 and replaced with an embed-only widget. Every
rescue is therefore explicit here, and adding one is a deliberate act.
``sources/petfinder.py`` is kept unregistered for reference only.
"""
from typing import List

from .base import Source
from .petstablished import PetstablishedSource
from .rescues.muddypaws import MuddyPawsSource
from .rescues.animalhaven import AnimalHavenSource
from .rescues.petconnect import PetConnectSource
from .rescues.koreank9 import KoreanK9Source
from .rescues.nycsecondchance import NYCSecondChanceSource
from .rescues.wagmor import WagmorSource

# Rescues we scrape directly from their own sites.
_DIRECT: List[Source] = [
    MuddyPawsSource(),     # 10 — public JSON API
    AnimalHavenSource(),   # 11 — server-rendered HTML (Shelterluv-backed)
    PetConnectSource(),    # 14 — 24PetConnect / Sean Casey
]

# Rescues read through Petstablished's public search API. Korean K9's own site
# is behind a Cloudflare challenge; NYC Second Chance's adoptable page is just
# an iframe of this same widget; Wagmor is Los Angeles, and being on a platform
# LUVD already reads is why it could open the same day it was chosen.
_VIA_PLATFORM: List[Source] = [
    KoreanK9Source(),          # 15
    NYCSecondChanceSource(),   # 16
    WagmorSource(),            # 20 — Los Angeles
]


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
    sources = _DIRECT + _VIA_PLATFORM + _try_optional()
    return sorted(sources, key=lambda s: s.priority)


def sources_for_city(city: str) -> List[Source]:
    """The sources whose dogs belong to one city, in the same priority order.

    A nightly run takes this rather than all_sources(), which is what keeps the
    cities genuinely separate: Los Angeles shelters cannot appear in, or be
    deduped against, a New York run. Every source above declares its city on
    itself (`Source.city`, default NYC), so there is no second lookup table to
    forget to update — the registry stays the one list.
    """
    return [s for s in all_sources() if s.city == city]


def direct_sources() -> List[Source]:
    """Everything except a broad city-wide search. Currently every source."""
    return [s for s in all_sources() if s.priority < 900]
