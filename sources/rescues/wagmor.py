"""Wagmor Pets — Los Angeles, read through Petstablished.

LUVD's first city outside New York. Wagmor is a Studio City rescue (11939 Ventura
Blvd) with a large, actively worked roster, and they run adoptions on
Petstablished, which ``sources/petstablished.py`` already speaks — so this is a
subclass and a name cleaner rather than a new scraper.

They are shelter 2122847. Verified 2026-07-29: three pages, 53 dogs, every one
status Available and none flagged no_longer_available, all 53 with a photo and a
breed, 35 with a write-up.

``fetch_traits`` is on, unlike Korean K9's, because Wagmor actually fills the
flags in. Across all 53: shots_up_to_date True on 52, is_ok_with_other_dogs True
on 46 and explicitly False on 3, is_spayed True on 37 and False on 15,
is_ok_with_other_kids False on 18. 52 of 53 dogs end up with at least one chip,
so the extra request per dog buys real information — and the explicit Falses
matter most, since "not good with kids" is the thing an adopter needs before they
apply, not after.

``route_by_location`` stays off, and not only because there is no program split
to model: 49 of the 53 ``current_location`` values are blank, and the four that
aren't are foster carers' names and home addresses. That field is not ours to
publish. Nothing here reads it, and the dog's displayed location comes from the
listing's own city/state — which Wagmor leaves empty on every record, so it falls
back to the city on this source (see PetstablishedSource._to_dog).

``listed_since`` lands on 45 of 53. The other eight have a previous_status of
Adopted, so the platform base deliberately declines to date them: their record
dates from the first time round, and counting from there would claim years of
waiting for a dog who came back last month.
"""
import re
from typing import Optional

from ..base import Dog
from ..petstablished import PetstablishedSource

# "Ashley #2368" — a hash and a number at the end of the name. Unambiguous: it is
# the shelter's own id, and no adopter ever says it.
_HASH_ID = re.compile(r"\s*#\s*\d+\s*$")

# "Chavelle 2272" — the same id typed without the hash. Eight of the 53 names
# arrive this way, and their numbers (2094, 2272, 2755, 5526, 6411, 9441, 9447)
# sit in exactly the same range as the hashed ids, which is what identifies them.
#
# One of the eight is "Luna 2024", and 2024 is year-shaped. It is worth being
# explicit that this rule strips it anyway, because the obvious defensive move —
# exempt anything that could be a year — would be the wrong call here. On this
# feed's evidence a trailing four-digit number in this position is an id: the
# other seven plainly are, and no name in the roster uses a year for anything.
# Both readings also lead to the same place, since an intake year is no more part
# of a dog's name than a record number is.
#
# Bounded at 3-5 digits and required to be the whole final token, so nothing that
# is part of a name can be caught by it. It leaves "Cosmic Crisp", "McIntosh Red"
# and "Stella McCartney" alone, and it cannot touch "Raven FKA Florida" — a
# formerly-known-as an adopter may have seen elsewhere, which stays.
_BARE_ID = re.compile(r"\s+\d{3,5}\s*$")


def strip_shelter_id(name: str) -> str:
    """"Ashley #2368" -> "Ashley". The rescue's filing number, not her name.

    Deliberately conservative in one direction only: if removing the number would
    leave nothing, the original is kept. A dog whose whole name is a number is
    presumably named that in their file too, and showing a number is much better
    than showing a blank space where a real animal's name goes.
    """
    original = (name or "").strip()
    cleaned = _BARE_ID.sub("", _HASH_ID.sub("", original)).strip()
    return cleaned or original


class WagmorSource(PetstablishedSource):
    name = "wagmor"
    label = "Wagmor Pets"
    priority = 20
    city = "LA"
    org_id = "2122847"
    adopt_url = "https://www.wagmorpets.org/adoption-application/"
    fetch_traits = True

    def _to_dog(self, rec: dict) -> Optional[Dog]:
        dog = super()._to_dog(rec)
        if dog is not None:
            dog.name = strip_shelter_id(dog.name)
        return dog
