"""Much Love Animal Rescue — Los Angeles, read through Adopt-a-Pet.

3/4 on Charity Navigator, running since 1999, entirely foster-based — no
kennels, so every write-up is someone describing a dog living in their house.
That is the kind of text enrich.py rates best from.
"""
from ..adoptapet import AdoptAPetSource


class MuchLoveSource(AdoptAPetSource):
    name = "muchlove"
    label = "Much Love Animal Rescue"
    priority = 29
    city = "LA"
    shelter_path = "shelter/71901-much-love-animal-rescue-los-angeles-california"
    adopt_url = "https://www.muchlove.org/adopt"
