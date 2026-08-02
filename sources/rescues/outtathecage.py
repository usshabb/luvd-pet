"""Outta the Cage — Encino, read through Adopt-a-Pet.

Named in sources/registry.py as one of four LA rescues the Petstablished sweep
of 2026-07-30 had to reject for having no route. Adopt-a-Pet is that route, and
``sources/adoptapet.py`` speaks it, so this is a subclass and nothing more.

Verified 2026-08-02: 7 listings on the roster, of which the cats are dropped by
the species check in the base. Their records are well filled in — write-ups are
real prose rather than the organisation's adoption-process boilerplate, and the
trait flags carry goodWithKids, goodWithDogs, housetrained and spayedNeutered.
"""
from ..adoptapet import AdoptAPetSource


class OuttaTheCageSource(AdoptAPetSource):
    name = "outtathecage"
    label = "Outta the Cage"
    priority = 24
    city = "LA"
    shelter_path = "adoption_rescue/149817-outta-the-cage-los-angeles-california"
    adopt_url = "https://www.outtathecage.org/applications"
