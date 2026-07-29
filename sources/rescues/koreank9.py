"""Korean K9 Rescue — read through Petstablished, the platform they adopt on.

Their own site can't be scraped: koreank9rescue.org sits behind a site-wide
Cloudflare interactive bot challenge, so every HTML path (including
/sitemap.xml and /wp-json/*) answers 403 with a JS challenge instead of
content. Verified again 2026-07-28. Solving that challenge would mean
deliberately defeating bot detection, which this project doesn't do.

They used to be read via the Petfinder API as org NY1374. That API was
decommissioned on 2 December 2025, so this now goes to the platform their own
adoption forms point at instead: Petstablished, where they are shelter
1956188 (found via the shelters endpoint; it's also the suffix of the
``ps_<pet>-1956188`` ids their listings carry on Adopt-a-Pet).

Their roster spans two programs, which is why this source routes by location.
Petstablished hands back every adoptable dog in one list, but their site splits
them across /adopt and /foster-to-adopt, and ``current_location`` is what says
which is which. That distinction is not cosmetic: the foster-to-adopt dogs are
still in South Korea, and sending someone to the standard adoption application
for a dog that hasn't landed yet is the wrong ask. Location codes seen
2026-07-28 — 14 dogs "2: East Coast Dogs", 15 "5: Foster First", 2 blank.

Trait flags are left at Petstablished's "Not Sure" default across their whole
roster, so ``fetch_traits`` stays off — it would spend a request per dog to
learn nothing. Everything they do tell adopters is in the write-up, which
enrich.py reads.
"""
from typing import List

from ..base import Dog
from ..petstablished import PetstablishedSource

FOSTER_FIRST = "5: Foster First"
FOSTER_TO_ADOPT_URL = "https://www.koreank9rescue.org/foster-to-adopt/"

# Their own terms, condensed. Every clause here is a commitment an adopter
# would want before they click, and none of it is true of a normal listing.
FOSTER_TO_ADOPT_NOTE = (
    "This dog is still in South Korea. Rather than meeting first, you take "
    "them home for a 7-day trial: pickup is at Korean K9's Astoria office the "
    "day their flight lands, and if it isn't a fit they ask you to keep "
    "fostering for about three weeks while they find a permanent home. "
    "Applications close 48 hours before each arrival date."
)


class KoreanK9Source(PetstablishedSource):
    name = "koreank9"
    label = "Korean K9 Rescue"
    priority = 15
    org_id = "1956188"
    adopt_url = "https://www.koreank9rescue.org/adoption-application/"
    fetch_traits = False
    route_by_location = True

    # Every non-blank ``current_location`` this run handed us, so the check
    # after the walk can name what it actually saw instead of just complaining.
    _locations_seen: List[str] = None

    def fetch(self, prefs: dict) -> List[Dog]:
        self._locations_seen = []
        dogs = super().fetch(prefs)
        self._check_foster_split(dogs)
        return dogs

    def route(self, dog: Dog, location: str) -> bool:
        """Send each dog down the path its own rescue lists it under.

        A blank location means the record is on neither of their public pages,
        so we drop it — those are leftovers, and every one seen so far was
        either a stale duplicate or a dog they'd stopped showing. An
        unrecognised code is kept as a normal adoption, because a new code is
        more likely to be a new location than a new program, and quietly
        deleting dogs is the worse failure.
        """
        if not location:
            return False
        if self._locations_seen is not None:
            self._locations_seen.append(location)
        if location == FOSTER_FIRST:
            dog.program = "foster-to-adopt"
            dog.program_label = "Foster-to-adopt"
            dog.program_note = FOSTER_TO_ADOPT_NOTE
            # Their foster-to-adopt page, not the raw form: the arrival date
            # each application is timed against is only published there.
            dog.adopt_url = FOSTER_TO_ADOPT_URL
        return True

    def _check_foster_split(self, dogs: List[Dog]) -> None:
        """Say something if the one string this whole split hangs on stops matching.

        ``FOSTER_FIRST`` is compared exactly, against a label a human types into
        Petstablished. If they rename it, `route` keeps every dog — which is the
        right call — but all 15 foster-to-adopt dogs quietly become standard
        adoptions: no program pill, no 7-day-trial note, and an apply button
        pointing at the ordinary application for a dog still in South Korea.
        Nothing else in the pipeline would notice, so this does.

        Deliberately a warning and not an error: zero foster-to-adopt dogs is a
        legitimate state (they can place all of them), so this asks a question
        rather than declaring a fault.
        """
        # Only ask when there is something to ask about. An empty fetch is
        # already reported by check.py as "returned 0 dogs", and a second
        # warning about one failure just buries the first.
        if not dogs or not self._locations_seen:
            return
        if any(d.program == "foster-to-adopt" for d in dogs):
            return
        codes = ", ".join(repr(c) for c in sorted(set(self._locations_seen)))
        print(f"  WARN  {self.name:<14} no dog matched {FOSTER_FIRST!r} — check "
              f"whether their location code changed. Saw: {codes}")
