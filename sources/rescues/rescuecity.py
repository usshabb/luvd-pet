"""Rescue City: location-specific public Adopt-a-Pet roster.

Verified 2026-10-20. Uses the shared paginated, dog-only available-pet parser.
Other branches of this organization are not included in this source.
"""
from ..adoptapet import AdoptAPetSource


class RescueCitySource(AdoptAPetSource):
    name = "rescuecity"
    label = "Rescue City"
    priority = 31
    city = "NYC"
    shelter_path = "shelter/91552-rescue-city-brooklyn-new-york"
    adopt_url = "https://www.rescuecity.nyc/adopt/"
