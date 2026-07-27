"""TEMPLATE for a direct rescue scraper. Copy this per rescue.

Fill in `name`, `priority` (0..899, lower = more preferred), `LISTING_URL`,
and the parsing logic in fetch(). The goal: return a list of Dog objects with a
STABLE id (so 'already seen' dedup works run-to-run) and at least name + url.
"""
import requests
from bs4 import BeautifulSoup
from typing import List

from ..base import Dog, Source


class TemplateRescueSource(Source):
    name = "example-rescue"
    priority = 100
    LISTING_URL = "https://example-rescue.org/adoptable-dogs"

    def enabled(self, prefs: dict) -> bool:
        return True  # direct sources run regardless of API keys

    def fetch(self, prefs: dict) -> List[Dog]:
        resp = requests.get(self.LISTING_URL, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0 (DogFinder)"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        dogs: List[Dog] = []
        # EXAMPLE selector logic — adjust to the real site:
        for card in soup.select(".dog-card"):
            link = card.select_one("a")
            href = link["href"] if link else ""
            slug = href.rstrip("/").split("/")[-1] or "unknown"
            img = card.select_one("img")
            photos = [img["src"]] if img and img.get("src") else []
            dogs.append(Dog(
                id=f"{self.name}:{slug}",
                name=(card.select_one(".name").get_text(strip=True)
                      if card.select_one(".name") else "Unknown"),
                source=self.name,
                url=href,
                breed="",
                description=(card.get_text(" ", strip=True)),
                photos=photos,
            ))
        return dogs
