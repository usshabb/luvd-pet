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
from .rescues.loveleo import LoveLeoSource
from .rescues.apurposeful import APurposefulSource
from .rescues.animalrescuemission import AnimalRescueMissionSource
from .rescues.outtathecage import OuttaTheCageSource
from .rescues.hitliving import HitLivingSource

# Rescues we scrape directly from their own sites.
_DIRECT: List[Source] = [
    MuddyPawsSource(),     # 10 — public JSON API
    AnimalHavenSource(),   # 11 — server-rendered HTML (Shelterluv-backed)
    PetConnectSource(),    # 14 — 24PetConnect / Sean Casey
]

# Rescues read through Petstablished's public search API. Korean K9's own site
# is behind a Cloudflare challenge; NYC Second Chance's adoptable page is just
# an iframe of this same widget; the four Los Angeles rescues are here because
# being on a platform LUVD already reads is what let each of them open within a
# day of being chosen.
#
# This note used to say Wagmor and Love Leo were "the only two", on the strength
# of a sweep of ~250 LA-area organisations that "found three with live dogs".
# That was wrong, and wrong in the expensive direction: it is the sentence that
# tells the next person not to bother looking. A resweep on 2026-07-30 — 16 ZIPs
# across the basin at 35 miles, paginated — found 364 distinct organisations and
# 36 with live dogs. The two figures do not measure the same area (35 miles from
# Long Beach or Sylmar reaches Orange County and Riverside, and one org in the
# results is actually in New Hampshire), so the counts are not comparable. The
# claim that Los Angeles itself held nothing else is what did not survive: A
# Purposeful Rescue is in Los Angeles with 53 records, and was there all along.
#
# Filtered to organisations actually in Los Angeles with a real roster, the
# sweep yielded the two added below. The rest of the 36 are mostly Orange County
# and Inland Empire, breed-specific (Basset Hound Rescue of Southern
# California), overseas-import (China Rescue Dogs), or down to one or two dogs.
# `scratchpad/sweep.py` in the session that added these is the script; the
# method is just the shelters endpoint documented in petstablished.py.
#
# Worth recording for whoever picks up the curated shortlist: none of MaeDay
# Rescue, the HIT Living Foundation, Outta the Cage or Yogi's House is on
# Petstablished. HIT Living and Outta the Cage are on Adopt a Pet, Yogi's House
# self-manages on Wix, and MaeDay publishes availability only on Instagram.
# Each needs a route of its own, and none of them is a subclass of this.
_VIA_PLATFORM: List[Source] = [
    KoreanK9Source(),               # 15
    NYCSecondChanceSource(),        # 16
    WagmorSource(),                 # 20 — Los Angeles
    LoveLeoSource(),                # 21 — Los Angeles
    APurposefulSource(),            # 22 — Los Angeles
    AnimalRescueMissionSource(),    # 23 — West Hollywood
]

# Rescues read through Adopt-a-Pet. Two of the four LA organisations the note
# above records as having no route are here — that note is what sent the next
# person looking, and Adopt-a-Pet is what they found. ~440 LA-area dog
# organisations list there, so this is the same kind of unlock Petstablished
# was, not a one-off.
#
# The other two still have no route and are not guesses either: Yogi's House
# self-manages on Wix and needs its own scraper; MaeDay Rescue publishes
# availability only on Instagram, which has no read path worth depending on.
_VIA_ADOPTAPET: List[Source] = [
    OuttaTheCageSource(),           # 24 — Encino
    HitLivingSource(),              # 25 — Van Nuys
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
    sources = _DIRECT + _VIA_PLATFORM + _VIA_ADOPTAPET + _try_optional()
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
