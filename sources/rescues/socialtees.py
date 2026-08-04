"""Social Tees Animal Rescue — Manhattan, read through Adopt-a-Pet.

The first NYC rescue on this platform; every other Adopt-a-Pet subclass so far
is in Los Angeles. Nothing in the base is city-specific, so this is the same
subclass-and-a-shelter_path as the rest — `city` just stays the default.

Foster-based and no-kill, running out of the East Village since 2006, and one
of the NYC names an adopter is likely to already know.
"""
from ..adoptapet import AdoptAPetSource


class SocialTeesSource(AdoptAPetSource):
    name = "socialtees"
    label = "Social Tees Animal Rescue"
    priority = 17
    city = "NYC"
    shelter_path = "shelter/83349-social-tees-animal-rescue-manhattan-new-york"
    adopt_url = "https://www.socialteesnyc.org/adopt"
