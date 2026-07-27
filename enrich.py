"""Attach the three at-a-glance scores and breed context to each dog.

The three things a NYC adopter actually needs to know up front:
  ENERGY      — can I meet this dog's exercise needs?
  APARTMENT   — will this work in a small space with shared walls?
  EXPERIENCE  — is this a first dog, or a project?

Scores start from breed tendencies (breeds.json) and are then adjusted by what
the rescue actually wrote about THIS dog, which is the stronger signal — a third
of our dogs have breed "Unknown" but almost all have a real bio.

These are ESTIMATES, surfaced as such in the UI. The rescue is the source of
truth about any individual animal.
"""
import json
import re
from pathlib import Path
from typing import List, Optional

from sources.base import Dog

_DATA = json.loads((Path(__file__).parent / "breeds.json").read_text())
_BREEDS = _DATA["breeds"]
_DEFAULT = _DATA["_default"]

# Longest keys first so "american pit bull terrier" wins over "terrier".
_BREED_KEYS = sorted(_BREEDS.keys(), key=len, reverse=True)

_SIZE_HINT = re.compile(r"\((small|medium|large|x-?large)\)", re.I)

# --- description signals -----------------------------------------------------
# (regex, energy_delta, apartment_delta, experience_delta, alone_delta)
_ALONE_SIGNALS = [
    # Whether this dog can be left while you're at work — the constraint that
    # quietly rules out most NYC adopters, and not implied by energy level.
    (r"\b(separation anxiety|cannot be left|can'?t be left|needs someone home|"
     r"velcro|shadow|follows? (me|you) everywhere|hates being alone|"
     r"dislikes being (left|alone)|not be left alone|destructive when)\b", -2),
    (r"\b(crate[- ]?trained|house[- ]?trained|housebroken|independent|"
     r"does well (alone|on (his|her|their) own)|content (alone|on)|"
     r"settles|self[- ]sufficient|low[- ]maintenance)\b", +1),
    (r"\b(puppy|puppies|months old|not yet house)\b", -1),
    (r"\b(senior|older (gal|guy|girl|boy|dog)|calm|mellow|"
     r"couch potato|loves? to (lounge|nap|sleep))\b", +1),
]

_SIGNALS = [
    # calm / low energy
    (r"\b(couch potato|low[- ]energy|mellow|laid[- ]back|calm|lazy|relaxed|"
     r"loves? to (?:lounge|nap|sleep)|gentle giant|easygoing|low key)\b", -1, +1, 0),
    (r"\b(senior|older (?:gal|guy|girl|boy|dog))\b", -1, +1, 0),
    # high energy
    (r"\b(high[- ]energy|energetic|active|athletic|needs? (?:a lot of|lots of|plenty of) "
     r"exercise|zoomies|playful pup|bundle of energy|loves? to run)\b", +1, -1, 0),
    (r"\b(puppy|puppies|months old)\b", +1, -1, +1),
    # apartment positives
    (r"\b(apartment|city dog|house[- ]?trained|housebroken|potty[- ]trained|"
     r"crate[- ]?trained|quiet|does(?:n't| not) bark|good in the home|"
     r"well[- ]mannered in the home)\b", 0, +1, 0),
    # apartment negatives
    (r"\b(barks? a lot|vocal|reactive|leash reactive|pulls? on (?:the )?leash|"
     r"needs? a yard|needs? space|destructive|escape artist|separation anxiety)\b",
     0, -1, +1),
    # experience needed
    (r"\b(experienced (?:owner|home|adopter|handler)|no first[- ]time|"
     r"needs? (?:structure|training|work|a confident)|behavioral|"
     r"resource guard|bite history|fearful|anxious|shy|slow to warm|"
     r"decompress|project|underdog)\b", 0, 0, +1),
    # experience easy
    (r"\b(great first dog|first[- ]time (?:owner|adopter)|easy|adaptable|"
     r"goes with the flow|loves everyone|friendly with everyone)\b", 0, 0, -1),
]


# What the rescue actually wrote outranks any breed generalisation, so the
# breed guide leads with their words. We pull real sentences out of the bio per
# topic and attribute them, rather than paraphrasing (which would invent facts).
_TOPIC_CUES = {
    "temperament": r"\b(friendly|sweet|shy|anxious|nervous|confident|social|gentle|"
                   r"affectionate|cuddl|calm|goofy|loving|timid|bold|"
                   r"good with|gets along|loves people|snuggl|personality|"
                   r"independent|smart|clever|easygoing|mellow)\b",
    "exercise": r"\b(walk|walks|run|running|exercise|hike|fetch|zoomies|romp|"
                r"active|high[- ]energy|low[- ]energy|couch potato|lounge|"
                r"tired|sniff|adventur|play ?time|energy level)\b",
    "grooming": r"\b(coat|groom|brush|shed|fur|bath|nail|matt)\b",
    "nyc": r"\b(apartment|city|crate|house[- ]?train|housebroken|potty|stairs|"
           r"elevator|leash|alone|bark|neighbor|subway|building|quiet|"
           r"street|sidewalk|urban)\b",
}

# Cuteness filler matches topic words by accident ("this energetic pup is
# adorable") without telling an adopter anything. Down-weight it.
_FLUFF = re.compile(r"\b(adorable|cute|precious|handsome|gorgeous|sweetest|"
                    r"you are right|wins the|look at (that|those)|melt)\b", re.I)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _tighten(s: str, limit: int = 150) -> str:
    """One short, clean sentence — the guide has to be skimmable."""
    s = re.sub(r"\s+", " ", s).strip()
    # Drop lead-ins that read oddly out of context.
    s = re.sub(r"^(and|but|so|also|plus|then|first things first[,:]?)\s+", "", s, flags=re.I)
    if len(s) <= limit:
        return s[:1].upper() + s[1:]
    cut = s[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return (cut[:1].upper() + cut[1:]).rstrip(",;:") + "…"


def _rescue_notes(description: str) -> dict:
    """The single most relevant sentence the rescue wrote, per topic.

    One sentence, not two: this feeds a scannable summary, and the full write-up
    is one tab away for anyone who wants it.
    """
    out = {}
    if not description:
        return out
    sentences = [s.strip() for s in _SENT_SPLIT.split(description) if s.strip()]
    # Skip boilerplate that most rescues append to every listing.
    boiler = re.compile(
        r"(available for adoption through|begin the registration|already a registered|"
        r"please email us|learn more about our|click to learn|application|"
        r"microchipped and up to date|breed is unknown as we have not|"
        r"reach out to|interested in adopting|www\.|@)", re.I)
    sentences = [s for s in sentences if not boiler.search(s) and 25 < len(s) < 260]

    used = set()
    for topic, cue in _TOPIC_CUES.items():
        best, best_score = None, 0
        for s in sentences:
            if s in used:
                continue
            hits = len(set(m.group(0).lower()
                           for m in re.finditer(cue, s, re.I)))
            if not hits:
                continue
            score = hits * 2
            if _FLUFF.search(s):        # cute but uninformative
                score -= 3
            if len(s) < 45:             # too thin to be useful
                score -= 1
            if score > best_score:
                best, best_score = s, score
        if best and best_score > 0:
            out[topic] = _tighten(best)
            used.add(best)
    return out


def _clamp(n: float) -> int:
    return max(1, min(5, int(round(n))))


def _match_breed(breed: str) -> Optional[str]:
    b = (breed or "").lower()
    if not b or "unknown" in b:
        return None
    # "Terrier, American Staffordshire" -> "american staffordshire terrier"
    if "," in b:
        parts = [p.strip() for p in b.split("/")[0].split(",")]
        if len(parts) == 2:
            flipped = f"{parts[1]} {parts[0]}"
            for k in _BREED_KEYS:
                if k in flipped:
                    return k
    for k in _BREED_KEYS:
        if k in b:
            return k
    return None


def _size_from_breed_string(breed: str) -> str:
    m = _SIZE_HINT.search(breed or "")
    return m.group(1).lower() if m else ""


# NYC-specific monthly costs. Deliberately a range, and deliberately excluding
# one-off adoption fees and emergencies — this is "what does this dog cost me
# every month", which is the question that actually stops adoptions.
_FOOD_PER_LB_MONTH = (0.55, 0.95)     # quality kibble, scaled by body weight
_BASE_INSURANCE = (35, 60)            # NYC pet insurance, mixed breed adult
_BASE_VET = (25, 45)                  # routine care amortised monthly
_BASE_SUPPLIES = (15, 30)             # toys, treats, poop bags, replacements


def _parse_age_years(age: str):
    """Rough age in years from strings like '2 years', '3 months', 'Senior'."""
    if not age:
        return None
    a = age.lower()
    m = re.search(r"([\d.]+)\s*year", a)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s*month", a)
    if m:
        return float(m.group(1)) / 12
    if "senior" in a:
        return 9.0
    if "adult" in a:
        return 4.0
    if "young" in a:
        return 1.5
    if "baby" in a or "puppy" in a:
        return 0.4
    return None


def _weight_lbs(dog):
    m = re.search(r"([\d.]+)", dog.weight or "")
    return float(m.group(1)) if m else None


def _size_outlook(dog, base, age_years, lbs):
    """Will this dog get bigger, and how big. Says nothing we can't support."""
    rng = base.get("adult_lbs")
    adult_mid = sum(rng) / 2 if rng else None
    grown = age_years is not None and age_years >= 1.5

    if grown:
        if lbs:
            return {"status": "grown",
                    "line": f"Fully grown at about {int(lbs)} lbs.",
                    "now": lbs, "adult": lbs}
        if adult_mid:
            return {"status": "grown",
                    "line": f"Fully grown. This breed typically settles "
                            f"around {rng[0]}–{rng[1]} lbs.",
                    "now": None, "adult": adult_mid}
        return {"status": "grown", "line": "Fully grown.",
                "now": None, "adult": None}

    if age_years is None:
        return None

    # Still growing.
    if rng:
        line = (f"Still growing. This breed usually reaches "
                f"{rng[0]}–{rng[1]} lbs.")
        if lbs:
            line = (f"About {int(lbs)} lbs now and still growing — this breed "
                    f"usually reaches {rng[0]}–{rng[1]} lbs.")
        return {"status": "growing", "line": line, "now": lbs,
                "adult": adult_mid}
    if lbs:
        return {"status": "growing",
                "line": f"About {int(lbs)} lbs now and still growing. Ask "
                        f"the rescue how big they expect this one to get.",
                "now": lbs, "adult": None}
    return {"status": "growing",
            "line": "Still growing. Ask the rescue about expected adult size.",
            "now": None, "adult": None}


def _monthly_cost(dog, base, adult_lbs, grooming_text):
    """A monthly range for THIS dog, scaled by the size it will actually be."""
    w = adult_lbs or 40
    lo = hi = 0.0
    food_lo = max(18, w * _FOOD_PER_LB_MONTH[0])
    food_hi = max(30, w * _FOOD_PER_LB_MONTH[1])
    lo += food_lo; hi += food_hi

    ins_lo, ins_hi = _BASE_INSURANCE
    if w >= 70:                       # large breeds cost more to insure
        ins_lo, ins_hi = ins_lo + 12, ins_hi + 25
    lo += ins_lo; hi += ins_hi

    vet_lo, vet_hi = _BASE_VET
    lo += vet_lo; hi += vet_hi
    lo += _BASE_SUPPLIES[0]; hi += _BASE_SUPPLIES[1]

    # Professional grooming is the biggest swing between breeds.
    g = (grooming_text or "").lower()
    groom_lo = groom_hi = 0
    if any(k in g for k in ("high maintenance", "mats", "professional grooming",
                            "hand-stripping", "clipping")):
        groom_lo, groom_hi = 55, 100
    elif "brush" in g and "easy" not in g:
        groom_lo, groom_hi = 10, 30
    lo += groom_lo; hi += groom_hi

    return {
        "low": int(round(lo / 5) * 5),
        "high": int(round(hi / 5) * 5),
        "items": [
            ("Food", int(food_lo), int(food_hi)),
            ("Insurance", int(ins_lo), int(ins_hi)),
            ("Routine vet", int(vet_lo), int(vet_hi)),
            ("Supplies", int(_BASE_SUPPLIES[0]), int(_BASE_SUPPLIES[1])),
        ] + ([("Grooming", groom_lo, groom_hi)] if groom_hi else []),
    }


def enrich(dogs: List[Dog]) -> List[Dog]:
    for d in dogs:
        key = _match_breed(d.breed)
        base = _BREEDS.get(key, _DEFAULT) if key else _DEFAULT

        energy = float(base.get("energy", 3))
        apartment = float(base.get("apartment", 3))
        experience = float(base.get("experience", 2))
        alone = float(base.get("alone", 3))

        text = f"{d.description}\n{' '.join(d.attributes)}".lower()
        for pattern, de, da, dx in _SIGNALS:
            if re.search(pattern, text):
                energy += de
                apartment += da
                experience += dx
        for pattern, dal in _ALONE_SIGNALS:
            if re.search(pattern, text):
                alone += dal

        # Size nudges apartment fit when we have a real number.
        size = (d.size or _size_from_breed_string(d.breed)).lower()
        wm = re.search(r"([\d.]+)", d.weight or "")
        lbs = float(wm.group(1)) if wm else None
        if lbs is not None:
            if lbs >= 70:
                apartment -= 1
            elif lbs <= 25:
                apartment += 1
        elif size in ("large", "xlarge"):
            apartment -= 1
        elif size == "small":
            apartment += 1

        d.scores = {
            "energy": _clamp(energy),
            "apartment": _clamp(apartment),
            "experience": _clamp(experience),
            "alone": _clamp(alone),
        }
        d.breed_key = key
        d.breed_info = {
            "name": key.title() if key else "Mixed / Unknown breed",
            "known": bool(key),
            "temperament": base.get("temperament", _DEFAULT["temperament"]),
            "exercise": base.get("exercise", _DEFAULT["exercise"]),
            "grooming": base.get("grooming", _DEFAULT["grooming"]),
            "nyc": base.get("nyc", _DEFAULT["nyc"]),
            # The rescue's own words, quoted and attributed, per topic.
            "from_rescue": _rescue_notes(d.description),
            "rescue_name": d.source_label,
        }

        age_years = _parse_age_years(d.age)
        lbs = _weight_lbs(d)
        d.size_outlook = _size_outlook(d, base, age_years, lbs) or {}
        adult_lbs = (d.size_outlook.get("adult")
                     or lbs
                     or (sum(base["adult_lbs"]) / 2 if base.get("adult_lbs") else None))
        d.monthly_cost = _monthly_cost(d, base, adult_lbs, base.get("grooming"))
    return dogs
