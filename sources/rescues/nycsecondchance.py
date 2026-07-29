"""NYC Second Chance Rescue — read through Petstablished.

A Queens-based 501(c)(3) (EIN 26-4835303) running since 2009, focused on dogs
and cats needing critical medical care. Their own adoptable-dogs page is just
an iframe of the Petstablished widget for organization 83716, so we read that
organization's records directly rather than parsing their WordPress page.

Unlike Korean K9, this rescue fills in Petstablished's trait flags — whether a
dog is house-trained, good with other dogs, and so on — so ``fetch_traits`` is
worth the extra request per dog. Those flags are the most reliable signal we
get about how a dog actually lives, and they feed the chips and the scores.

They list roughly as many cats as dogs; ``animal=Dog`` in the shared fetch
keeps this to dogs, which is all LUVD covers today.
"""
from ..petstablished import PetstablishedSource


class NYCSecondChanceSource(PetstablishedSource):
    name = "nycsecondchance"
    label = "NYC Second Chance Rescue"
    priority = 16
    org_id = "83716"
    adopt_url = "https://nycsecondchancerescue.org/dog-adoption-application/"
    fetch_traits = True
