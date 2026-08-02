"""The HIT Living Foundation — Van Nuys, read through Adopt-a-Pet.

The second of the four LA rescues sources/registry.py listed as unreachable.
Same route as Outta the Cage, so the same base class.

Verified 2026-08-02: 5 listings on the roster. The foundation's own material
talks about a far larger foster population than this; what is here is what they
have actually published as adoptable, which is the only number LUVD can stand
behind.
"""
from ..adoptapet import AdoptAPetSource


class HitLivingSource(AdoptAPetSource):
    name = "hitliving"
    label = "The HIT Living Foundation"
    priority = 25
    city = "LA"
    shelter_path = "shelter/104110-the-hit-living-foundation-van-nuys-california"
    adopt_url = "https://www.thehitlivingfoundation.org/adopt"
