"""Angel City Pit Bulls — Los Angeles, read through Adopt-a-Pet.

3/4 on Charity Navigator, founded 2010 against the euthanasia rate for bully
breeds in LA county shelters. Worth having for a reason beyond its rating: pit
bull type is already the largest breed group on the NYC page, and it is the
group most often filtered out elsewhere.
"""
from ..adoptapet import AdoptAPetSource


class AngelCityPitsSource(AdoptAPetSource):
    name = "angelcitypits"
    label = "Angel City Pit Bulls"
    priority = 27
    city = "LA"
    shelter_path = "shelter/81822-angel-city-pit-bulls-los-angeles-california"
    adopt_url = "https://www.angelcitypits.org/adopt"
