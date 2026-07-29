"""Love Leo Rescue — Los Angeles, read through Petstablished.

The second LA rescue, and the second one on Petstablished, so this is another
thin subclass of ``sources/petstablished.py`` rather than a new scraper.

They are shelter 2349259 — confirmed from their own site rather than taken on
trust: loveleorescue.org embeds ``wagtopia.com/search/org?id=2349259``, which is
the same organisation this reads. Verified 2026-07-29: two pages, 38 records, 36
of them dogs, all with a breed and a photo, 35 with a write-up.

Note the domain is **.org**. loveleorescue.com does not resolve at all — no A
record — so anything pointing at the .com is a dead link.

``fetch_traits`` is on, decided on this rescue's own evidence rather than copied
from Wagmor. Across the 38 detail records: shots_up_to_date True on 24,
is_ok_with_other_dogs True on 23 and explicitly False on 1, is_housebroken True
on 18 and False on 4, is_spayed True on 21 and False on 5. Less complete than
Wagmor's, but the shape is the same — a rescue answering the questions, with real
Noes in there. The explicit Falses are the reason the request per dog is worth
paying for.

``route_by_location`` stays off, for the same reason it is off for Wagmor: 34 of
the 38 ``current_location`` values are blank, and the four that aren't are foster
carers' names and home addresses. Nothing here reads that field.

``listed_since`` is the best of any source so far — ``created_at`` is set on all
38, and so is ``date_of_birth``, which is the sanity check the platform base
dates against. Four dogs have a previous_status of Adopted and are deliberately
left undated: their record is from the first time round.
"""
import re
from typing import Optional

import cities

from ..base import Dog
from ..petstablished import PetstablishedSource

# Two of the 38 records are not animals: "Foster Needed - Adult Dogs" and
# "Foster Needed - Puppies". They are recruitment posts that borrow a listing
# because Petstablished has nowhere else to put them — a real breed and photo, so
# they render as a perfectly plausible dog, and then an adopter applies for an
# animal that does not exist.
#
# Two independent signals are required to drop one, because either alone could be
# wrong about a real dog. The name has to announce itself as an appeal, AND the
# record has to carry none of the facts that only exist about an actual animal.
# On this feed each test alone identifies exactly these two records; needing both
# means a dog genuinely called "Foster Needed" would still be listed if the
# rescue filled her details in, and a dog with a thin record is never dropped for
# thinness alone.
_FOSTER_APPEAL = re.compile(r"^\s*fosters?\s+needed\b", re.I)


def is_foster_appeal(rec: dict) -> bool:
    if not _FOSTER_APPEAL.match(str(rec.get("name") or "")):
        return False
    return not any(str(rec.get(f) or "").strip()
                   for f in ("sex", "weight", "date_of_birth", "size"))


class LoveLeoSource(PetstablishedSource):
    name = "loveleo"
    label = "Love Leo Rescue"
    priority = 21
    city = "LA"
    org_id = "2349259"
    # What their nav's "ADOPTION APPLICATION" points at. Their own /adopt page is
    # the Wagtopia embed, which needs JavaScript and shows a spinner to anything
    # that doesn't run it, so it is no use as a link for a human.
    adopt_url = ("https://petstablished.com/adoptions/personal-information"
                 "?application_type=Adopt&donation_section=false&form_id=36515"
                 "&form_type=generic&generic_form_id=36515&pet_id=1226244"
                 "&section=1&selected_pets=false")
    fetch_traits = True

    def _to_dog(self, rec: dict) -> Optional[Dog]:
        if is_foster_appeal(rec):
            return None
        dog = super()._to_dog(rec)
        if dog is not None:
            dog.location = self._location(rec)
        return dog

    def _location(self, rec: dict) -> str:
        """Where the dog is, ignoring the account address on every record.

        All 38 records say "Eugene, or" — Love Leo is a Los Angeles rescue, so
        that is a stale field on their Petstablished account, not 38 dogs in
        Oregon. Left alone it would print "Eugene, OR" under every dog on the LA
        page, which is worse than saying nothing: an adopter filtering by
        neighbourhood would rule out the whole rescue. The four real locations
        this feed does carry are foster homes in Los Angeles, Whittier and
        Beverly Hills, which is where the dogs actually are.

        Written as "not this city's state" rather than "not Eugene" so it heals
        itself if they fix the account, and so a genuine Californian city on a
        record is still used. Kept in this subclass rather than the platform base
        because a New York rescue fostering a dog in New Jersey is ordinary and
        true, and a rule up there would throw that away.
        """
        c = cities.resolve(self.city)
        town = (rec.get("city") or "").strip()
        state = (rec.get("state") or "").strip().upper()
        if town and state == c.state:
            return f"{town}, {state}"
        return c.location
