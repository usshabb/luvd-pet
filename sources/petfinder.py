"""Petfinder API source.

Two uses:
  1. PetfinderOrgSource — pull ONE specific rescue's dogs through the sanctioned
     API. Used for rescues whose own site blocks scraping (e.g. Korean K9 Rescue
     sits behind a Cloudflare challenge, but publishes to Petfinder as NY1374).
     These count as *direct* sources, so they get a low priority number.
  2. PetfinderSource — the broad city-wide fallback, checked last.

Docs: https://www.petfinder.com/developers/v2/docs/
Auth is OAuth2 client-credentials -> short-lived bearer token.
"""
import os
import time
import requests
from typing import List, Optional

from .base import Dog, Source, clean_text

TOKEN_URL = "https://api.petfinder.com/v2/oauth2/token"
ANIMALS_URL = "https://api.petfinder.com/v2/animals"

_token_cache = {"token": None, "expires": 0}


def _get_token() -> str:
    """Shared token across all Petfinder-backed sources."""
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("PETFINDER_KEY"),
            "client_secret": os.getenv("PETFINDER_SECRET"),
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def _animal_to_dog(a: dict, source: str, source_label: str, adopt_url: str) -> Dog:
    photos = [p.get("full") or p.get("large") or p.get("medium")
              for p in a.get("photos", [])]
    photos = [p for p in photos if p]
    if not photos and a.get("primary_photo_cropped"):
        pc = a["primary_photo_cropped"].get("full") or a["primary_photo_cropped"].get("large")
        if pc:
            photos = [pc]

    addr = (a.get("contact", {}) or {}).get("address", {}) or {}
    loc = ", ".join(x for x in [addr.get("city"), addr.get("state")] if x)

    # Petfinder exposes booleans for environment/traits — turn them into chips.
    attrs = []
    env = a.get("environment", {}) or {}
    if env.get("children"):
        attrs.append("Good with kids")
    if env.get("dogs"):
        attrs.append("Good with dogs")
    if env.get("cats"):
        attrs.append("Good with cats")
    at = a.get("attributes", {}) or {}
    if at.get("house_trained"):
        attrs.append("House-trained")
    if at.get("special_needs"):
        attrs.append("Special needs")
    if at.get("spayed_neutered"):
        attrs.append("Spayed/neutered")

    breeds = a.get("breeds", {}) or {}
    breed = breeds.get("primary") or ""
    if breeds.get("secondary"):
        breed = f"{breed}/{breeds['secondary']}"
    if breeds.get("mixed") and breed and "mix" not in breed.lower():
        breed += " mix"

    # published_at is a real listing date — far better than "when LUVD first
    # saw it" for working out how long a dog has actually been waiting.
    published = (a.get("published_at") or "")[:10]

    return Dog(
        id=f"{source}:{a['id']}",
        listed_since=published,
        name=a.get("name", "Unknown"),
        source=source,
        source_label=source_label,
        url=a.get("url", ""),
        photos=photos,
        breed=breed,
        age=a.get("age", ""),
        sex=a.get("gender", ""),
        size=(a.get("size") or "").lower(),
        location=loc,
        description=clean_text(a.get("description") or ""),
        attributes=attrs,
        adopt_url=adopt_url or a.get("url", ""),
    )


def _query(params: dict) -> List[dict]:
    resp = requests.get(
        ANIMALS_URL,
        headers={"Authorization": f"Bearer {_get_token()}"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("animals", [])


class PetfinderOrgSource(Source):
    """One specific rescue, pulled through the Petfinder API."""

    def __init__(self, org_id: str, name: str, label: str, priority: int,
                 adopt_url: str = ""):
        self.org_id = org_id
        self.name = name
        self.label = label
        self.priority = priority
        self.adopt_url = adopt_url

    def enabled(self, prefs: dict) -> bool:
        return bool(os.getenv("PETFINDER_KEY") and os.getenv("PETFINDER_SECRET"))

    def fetch(self, prefs: dict) -> List[Dog]:
        animals = _query({
            "type": "dog",
            "status": "adoptable",
            "organization": self.org_id,
            "sort": "recent",
            "limit": 100,
        })
        return [_animal_to_dog(a, self.name, self.label, self.adopt_url)
                for a in animals]


class PetfinderSource(Source):
    """Broad city-wide fallback — everything else adoptable near you."""

    name = "petfinder"
    label = "Petfinder"
    priority = 900
    adopt_url = ""

    def enabled(self, prefs: dict) -> bool:
        return bool(os.getenv("PETFINDER_KEY") and os.getenv("PETFINDER_SECRET"))

    def fetch(self, prefs: dict) -> List[Dog]:
        params = {
            "type": "dog",
            "status": "adoptable",
            "sort": "recent",
            "limit": 100,
        }
        if prefs.get("zip"):
            params["location"] = prefs["zip"]
            params["distance"] = min(int(prefs.get("radius_miles") or 50), 500)
        animals = _query(params)
        dogs = []
        for a in animals:
            org = (a.get("organization_name")
                   or (a.get("contact", {}) or {}).get("name")
                   or "Petfinder")
            dogs.append(_animal_to_dog(a, self.name, org, ""))
        return dogs
