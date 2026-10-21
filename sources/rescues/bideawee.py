"""Bideawee — New York: location-specific public Adopt-a-Pet roster.

Verified 2026-10-20. Uses the shared paginated, dog-only available-pet parser.
Other branches of this organization are not included in this source.
"""
from ..adoptapet import AdoptAPetSource


class BideaweeSource(AdoptAPetSource):
    name = "bideawee"
    label = "Bideawee — New York"
    priority = 30
    city = "NYC"
    shelter_path = "shelter/73580-bideawee-new-york-new-york-new-york"
    adopt_url = "https://www.bideawee.org/programs/adoption/"
