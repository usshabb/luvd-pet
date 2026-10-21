"""spcaLA — Los Angeles: location-specific public Adopt-a-Pet roster.

Verified 2026-10-20. Uses the shared paginated, dog-only available-pet parser.
Other branches of this organization are not included in this source.
"""
from ..adoptapet import AdoptAPetSource


class SpcaLASource(AdoptAPetSource):
    name = "spcala"
    label = "spcaLA — Los Angeles"
    priority = 32
    city = "LA"
    shelter_path = "shelter/218170-spcala-los-angeles-los-angeles-california"
    adopt_url = "https://spcala.com/adoptable/"
