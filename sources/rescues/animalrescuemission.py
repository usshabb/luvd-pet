"""The Animal Rescue Mission — West Hollywood, read through Petstablished.

The third LA rescue, and the third on Petstablished, so another thin subclass of
``sources/petstablished.py`` rather than a new scraper.

They are shelter 2330596 — taken from their own site rather than on trust:
theanimalrescuemission.org/adopt is a Petstablished embed and the page carries
that same org id, which is the check Love Leo set the precedent for. Verified
2026-07-30: one page, 19 records, every one status Available and none flagged
no_longer_available, 18 with a write-up, 17 with a date of birth, 12 with a
weight, 18 with a sex.

``fetch_traits`` is on, decided on this rescue's own fill rate: 17 of the 19 end
up with at least one chip. It is a quieter feed than A Purposeful Rescue's —
is_ok_with_other_dogs is True on 14 and never explicitly False, and the only
Noes anywhere are one is_housebroken and one is_spayed — so the request per dog
buys less here than it does there. It still earns itself on is_hypoallergenic,
which they answer either way (True on 2, False on 7) and which nobody else in
LUVD fills in at all.

``listed_since`` lands on all 19: ``created_at`` is set on every detail record,
and none carries a previous_status of Adopted, so nothing is deliberately left
undated the way eight of Wagmor's and four of Love Leo's are.

``route_by_location`` stays off, and for the same reason it is off for the other
two: 16 of the 19 ``current_location`` values are blank and the three that are
not are foster carers' first names and neighbourhoods ("karina", "humble k9",
"Soyoung in HIghland Park"). That is not ours to publish, and nothing here reads
it. The displayed location comes from the listing's own city/state, which they
fill in correctly — all 19 say West Hollywood, CA — so no override like Love
Leo's is needed.

They are a 501(c)(3) founded in 2018 and a Best Friends Animal Society network
partner, which is the outside corroboration that this is a real, working rescue
rather than a Petstablished account with dogs on it.
"""
from ..petstablished import PetstablishedSource


class AnimalRescueMissionSource(PetstablishedSource):
    name = "animalrescuemission"
    label = "The Animal Rescue Mission"
    priority = 23
    city = "LA"
    org_id = "2330596"
    # A real page on the rescue's own domain, unlike Love Leo's, whose nav points
    # straight at the raw Petstablished form. Preferred wherever a rescue has
    # one: it is the link they would give an adopter themselves.
    adopt_url = "https://www.theanimalrescuemission.org/adoptionapplication"
    fetch_traits = True
