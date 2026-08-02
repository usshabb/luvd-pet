"""The LaBelle Foundation — Los Angeles, read through Adopt-a-Pet.

Named in the same top three as Wags & Walks and Angel City Pit Bulls.
"""
from ..adoptapet import AdoptAPetSource


class LaBelleSource(AdoptAPetSource):
    name = "labelle"
    label = "The LaBelle Foundation"
    priority = 28
    city = "LA"
    shelter_path = "shelter/190858-the-labelle-foundation-los-angeles-california"
    adopt_url = "https://www.labellefoundation.org/adopt"
