"""A Purposeful Rescue — Los Angeles, read through Petstablished.

A thin subclass of ``sources/petstablished.py`` plus one filter, which is the
whole reason this file is longer than Wagmor's.

They are shelter 3204319. Verified 2026-07-30: three pages, 53 records, 52
status Available and one Fostered, none flagged no_longer_available, 52 with a
write-up, all 53 with a sex.

**Two thirds of the roster is theirs.** 21 of the 53 records are courtesy posts —
dogs belonging to other people or other organisations that this rescue is only
advertising — and one is a test record. Both are dropped; see ``is_not_ours``.
That leaves 31 dogs, which is still a larger roster than any other LA rescue
here.

``fetch_traits`` is on, and this is the feed that most repays it: all 40 records
sampled came back with at least one chip, and the answers include real Noes —
is_housebroken False on 2, is_ok_with_other_cats False on 4, is_ok_with_other_dogs
False on 1, is_ok_with_other_kids False on 1. "Not good with cats" is the thing
an adopter needs before they apply rather than after, so the request per dog is
worth paying for here even though it is the largest roster to walk.

``listed_since`` works: ``created_at`` was set on all 40 sampled, and no record
carries a previous_status of Adopted, so none is deliberately left undated.

Two things this feed does *not* have, both of which make its cards thinner than
Animal Rescue Mission's, and neither of which is worth a workaround:

  * **No dates of birth at all** — 0 of 53. Ages therefore fall back to
    Petstablished's Puppy/Young/Adult/Senior bucket, which the platform base
    only uses when there is no birthday. The bucket is what the rescue actually
    maintains here, so it is the honest answer rather than a degraded one.
  * **No weights** — 0 of 53.

``route_by_location`` stays off: all 40 sampled ``current_location`` values are
blank, so there is no program split to model and nothing to leak. The listing's
own city/state is filled in correctly on every record — all 53 say Los Angeles,
CA — so Love Leo's location override is not needed.

One caveat worth knowing before trusting this feed further. **Petstablished is
not where their own site sends adopters.** apurposefulrescue.org/adopt and
/adoptable-dogs are both Shelterluv embeds (GID 609), so the roster a visitor to
their site sees is Shelterluv's, and this one is a second list they also keep.
It is plainly maintained — 52 of 53 Available, write-ups on all but one — but a
second list is a list that can drift, and the failure that would cause is
showing a dog who has already been adopted. If this rescue ever goes stale,
read Shelterluv instead: ``rescues/animalhaven.py`` already reads a
Shelterluv-backed rescue, so the path exists.
"""
import re
from typing import Optional

from ..base import Dog
from ..petstablished import PetstablishedSource

# "Alma *Courtesy Post*", "Luca * Courtesy Post*", "Oso *COURTESY POST" — the
# rescue marks these itself, in the name, and the marker is not punctuated
# consistently: the asterisks may be spaced, unbalanced or missing the closing
# one, and the case varies. Matched anywhere in the name rather than anchored,
# because it appears mid-name on "Cinderella aka Cindy *Courtesy Post*".
_COURTESY = re.compile(r"courtesy\s*post", re.I)

# "TEST DOG" is in the live roster with a real breed and photo, so it renders as
# a perfectly plausible dog.
_TEST_RECORD = re.compile(r"^\s*test[\s_-]*dog\b", re.I)


def is_not_ours(rec: dict) -> bool:
    """Should this record never appear under this rescue's name?

    Unlike Love Leo's foster appeals, one signal is enough for both of these,
    and deliberately so: the test there had to be doubled because "Foster
    Needed" is a phrase a real dog could plausibly be called, so dropping on
    the name alone risked a real animal. Neither of these is that. No dog is
    named "Courtesy Post" — it is the rescue's own word for a listing that
    isn't theirs — and none is named "TEST DOG".

    Courtesy posts are dropped rather than relabelled because LUVD cannot
    honestly attribute them. Every dog on the page carries one rescue's name
    and one apply button, and for these two the dog belongs to somebody the
    listing does not identify: an adopter who applied to A Purposeful Rescue
    for one would be writing to the wrong people about an animal they don't
    have. Showing 31 dogs that are really theirs is worth more than 52 that
    might not be.
    """
    name = str(rec.get("name") or "")
    return bool(_COURTESY.search(name) or _TEST_RECORD.match(name))


class APurposefulSource(PetstablishedSource):
    name = "apurposeful"
    label = "A Purposeful Rescue"
    priority = 22
    city = "LA"
    org_id = "3204319"
    # Their own site publishes no application link — /adopt and /adoptable-dogs
    # are the Shelterluv listing, and the FAQ says only "You must start by
    # filling out an adoption application" without pointing anywhere. So this is
    # their Petstablished form (adoption_form_id 53142, the same on every
    # record), which is the application their listings themselves open. Same
    # situation as Love Leo, same resolution.
    adopt_url = ("https://petstablished.com/adoptions/personal-information"
                 "?application_type=Adopt&donation_section=false&form_id=53142"
                 "&form_type=generic&generic_form_id=53142"
                 "&section=1&selected_pets=false")
    fetch_traits = True

    def _to_dog(self, rec: dict) -> Optional[Dog]:
        if is_not_ours(rec):
            return None
        return super()._to_dog(rec)
