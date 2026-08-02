"""Wags & Walks — Los Angeles, read through Adopt-a-Pet.

The strongest name on the LA list and the only 4/4 on Charity Navigator among
the rescues considered: founded 2011, 16,500+ placements across Los Angeles and
Nashville, and the one an Angeleno is most likely to have heard of.
"""
from ..adoptapet import AdoptAPetSource


class WagsAndWalksSource(AdoptAPetSource):
    name = "wagsandwalks"
    label = "Wags & Walks"
    priority = 26
    city = "LA"
    shelter_path = "shelter/84852-wags-walks-los-angeles-los-angeles-california"
    adopt_url = "https://www.wagsandwalks.org/adopt"
