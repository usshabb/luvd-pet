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


# The card hover bubble clamps to two lines at 12.5px, so anything past roughly
# 80 characters gets truncated mid-joke. Keep every line short.
_QUIP_MAX = 80

# Lines any dog can truthfully say. The last resort, so that a dog whose better
# options are all taken still gets to say something.
_QUIP_ANY = [
    "Adoptable, delightful, and extremely available.",
    "Still here, still hopeful, still extremely good.",
    "Ready to be somebody's favorite decision.",
    "Looking for one human. Standards: low. Loyalty: high.",
    "Available now, affectionate always.",
    "I don't have a resume, just excellent vibes.",
    "Here for the long haul, ideally on your couch.",
    "Will trade eye contact for a walk.",
    "Ready for a door with my name on it.",
    "One good human is all I'm after.",
    "Small ask: a name, a bed, and you.",
    "Prepared to love you unreasonably.",
    "Vacancy in my life, roughly your size.",
    "I come with a wag and zero baggage claims.",
    "Interviewing humans. You seem promising.",
    "Would very much like to go home now.",
    "New leash on life, pending your signature.",
    "Yours, if you'll have me.",
]


def _breed_word(d: Dog) -> str:
    """A short breed noun that reads naturally mid-sentence, or "".

    "Mixed Breed (Medium)" -> "mutt", "Retriever, Labrador/Mix" -> "retriever".
    Returns "" when the rescue didn't record a usable breed, which is common —
    roughly a third of dogs come through as "Unknown".
    """
    raw = (d.breed or "").split("/")[0].split(",")[0]
    raw = re.sub(r"\([^)]*\)", "", raw).strip().lower()
    raw = re.sub(r"\b(dog|mix|mixed)\b", "", raw).strip(" -")
    if not raw or "unknown" in raw:
        return ""
    if raw in ("breed", "domestic", "other"):
        return "mutt"
    return raw if len(raw) <= 22 else ""


def _quip_tiers(d: Dog) -> List[tuple]:
    """(priority, lines) for every claim this dog's own listing supports.

    Priority ranks how well-grounded a line is: an explicit shelter label beats
    a phrase in the rescue's prose, which beats age, size and breed generics.
    """
    desc = (d.description or "").lower()
    traits = " ".join(t["text"].lower() for t in (d.traits or []))
    hay = f"{desc} {traits}"
    age_years = _parse_age_years(d.age)
    lbs = _weight_lbs(d)
    size = (d.size or _size_from_breed_string(d.breed)).lower()
    is_big = (lbs is not None and lbs >= 70) or size in ("large", "xlarge")
    is_small = (lbs is not None and lbs <= 20) or size == "small"
    breed = _breed_word(d)

    def has(pat):
        return re.search(pat, hay) is not None

    rules = [
        (9, has(r"good with (kids|children)|kid[- ]friendly|great with children"),
         ["Kids? Adore 'em. I'm basically a fuzzy babysitter.",
          "Great with little humans — I even share my toys.",
          "Certified kid-approved. The small ones are my people.",
          "Good with kids, excellent at being tackled.",
          "I let the children win. Every time.",
          "Built for birthday parties and backyard chaos.",
          "The kids can climb me. I've signed off on it.",
          "Family dog, fully vetted by small critics."]),
        (9, has(r"good with (other )?dogs|dog[- ]friendly|gets along with dogs"),
         ["I make friends at the dog run in about four seconds.",
          "Other dogs? Instant best friends. Bring the whole pack.",
          "Good with dogs, great at group naps.",
          "I've never met a dog I didn't like. Streak intact.",
          "Happy to share the park. And the water bowl.",
          "Plays well with others. Ask any of them.",
          "Bring your dog. We'll sort it out in seconds.",
          "I speak fluent dog and I'm very polite about it.",
          "Sidekick available; existing dog welcome.",
          "Dog park regular, no notes.",
          "The more dogs the better, honestly.",
          "I do my best work in a pack.",
          "Fine with a canine roommate. Encouraged, even.",
          "Social butterfly, four legs, no wings.",
          "Every dog here is a friend I haven't sniffed yet.",
          "Good with dogs, and modest about it."]),
        (9, has(r"good with cats|cat[- ]friendly|fine with cats"),
         ["Yep, I'm cool with cats. Very diplomatic of me.",
          "I'll share the couch with the cat. Treaty signed.",
          "Cat-approved, which is a high bar.",
          "The cat and I have an understanding.",
          "Cats? Coexistence achieved. Peace held.",
          "I don't chase cats. I respect them.",
          "Feline roommate? No objections filed.",
          "Good with cats, better with people.",
          "I've made peace with the cat lobby.",
          "Cat-friendly and quietly proud of it.",
          "Will ignore your cat with total professionalism.",
          "The cat can keep the windowsill."]),
        (8, has(r"house[- ]?trained|housebroken|potty[- ]?trained"),
         ["Already house-trained — your rugs are safe with me.",
          "House-trained and proud. I take my business outside.",
          "Housebroken. Your floors and I are on great terms.",
          "I know where the bathroom is. It's outside.",
          "Fully house-trained, zero accidents to report.",
          "No puddles, no drama. House-trained already.",
          "Your security deposit is safe with me.",
          "House-trained, so we can skip that chapter.",
          "I ask to go out. Politely, usually.",
          "Trained indoors, thrilled outdoors.",
          "Rugs: respected. Floors: unbothered.",
          "House-trained and holding it like a champ.",
          "One less thing to teach me. You're welcome.",
          "I've mastered doors and what's on the other side."]),
        (8, has(r"crate[- ]?trained"),
         ["Crate-trained, so I've got my own little studio apartment.",
          "My crate is my castle. Trained and settled.",
          "Crate-trained: I nap where I'm told.",
          "I have a bedroom already. It's the crate.",
          "Crate-trained, so alone time isn't a crisis.",
          "Happy in my crate. It's got great light."]),
        (7, has(r"couch potato|low[- ]energy|loves? to (lounge|nap|sleep)|mellow|"
                r"laid[- ]back|lazy|calm|relaxed|easygoing|gentle giant"),
         ["Professional couch loafer. References available.",
          "My cardio is walking to the food bowl. It's plenty.",
          "Here to nap and steal the warm spot. Both going great.",
          "Low energy, high devotion.",
          "I've never once been in a hurry.",
          "Mellow to the bone. Ask anyone.",
          "I treat the sofa as a full-time position.",
          "Calm is my whole personality.",
          "Naps: expertly executed. Daily.",
          "Easygoing, unbothered, deeply horizontal.",
          "I don't need much. Mostly a blanket.",
          "Quiet company, always available.",
          "Laid-back roommate, minimal opinions.",
          "Slow mornings are my specialty.",
          "I peak at rest.",
          "Chill by nature, not by training."]),
        (7, has(r"high[- ]energy|energetic|athletic|loves? to run|zoomies|"
                r"bundle of energy|active|loves? to play|playful"),
         ["Two speeds: zoomies, or asleep on your feet.",
          "Will work for one (1) tennis ball. Forever.",
          "Part dog, part personal trainer. Cardio buddy wanted.",
          "I have energy. Lots. Bring shoes.",
          "Ball. Ball? Ball!",
          "Runner seeking running partner. Pace negotiable.",
          "I play hard and sleep harder.",
          "Long walks are the love language here.",
          "Batteries fully charged, always.",
          "Let's go. Anywhere. Now.",
          "Playtime is my job and I'm excellent at it.",
          "Energetic, enthusiastic, extremely available.",
          "I'll out-walk you. Kindly.",
          "Fetch is not a game to me. It's a calling.",
          "Zoomies scheduled hourly.",
          "Adventure buddy, ready immediately."]),
        (7, has(r"cuddl|snuggl|affectionate|loves? to be held|lap dog|velcro|"
                r"follows? (me|you) everywhere"),
         ["Part dog, part weighted blanket.",
          "Your new shadow — I come with the apartment.",
          "I give hugs whether you asked for one or not.",
          "Professional snuggler, no off switch.",
          "I will be touching you at all times.",
          "Lap space required. Non-negotiable.",
          "Affection is the whole product here.",
          "I follow you room to room. It's a feature.",
          "Cuddles on arrival, cuddles on demand.",
          "Velcro dog. You've been warned.",
          "I lean. Heavily. Lovingly.",
          "Personal space is a concept I reject.",
          "Built for couch piles and long hugs.",
          "I'd like to be held now, please.",
          "Warm, heavy, extremely devoted.",
          "Snuggling is my cardio.",
          "I save my very best sleeping for on top of you.",
          "Attached at the hip, immediately."]),
        (6, has(r"goofy|silly|clown|derp|wiggle|happy[- ]go[- ]lucky"),
         ["I'm 60% wiggle, 40% goofball, 100% yours.",
          "Certified goofball. Dignity sold separately.",
          "Clown energy, excellent intentions.",
          "I trip over my own feet and I own it.",
          "Silly by default, sweet by design.",
          "My whole body wags. Not just the tail.",
          "Comic relief, four legs, no shame.",
          "Happy-go-lucky and slightly ridiculous.",
          "I make a fool of myself daily. Worth it.",
          "Goofy, wiggly, thoroughly delightful.",
          "Grace: none. Joy: enormous.",
          "I'm a lot of dog and none of it serious."]),
        (6, has(r"shy|timid|nervous|slow to warm|fearful|decompress|underdog"),
         ["A little shy at first, then completely, utterly yours.",
          "Slow to trust, worth every minute of the wait.",
          "Quiet at first. Devoted forever.",
          "Give me a week. I'll give you everything.",
          "Shy, not sad. There's a big heart in here.",
          "I warm up slowly and love permanently.",
          "Patience gets you the real me.",
          "Nervous on day one, glued to you by day ten.",
          "I need a minute, then I'm all in.",
          "Gentle soul, still finding my feet.",
          "Soft-spoken and hoping you're patient.",
          "The underdog. Literally."]),
        (6, has(r"smart|clever|intelligent|quick learner|knows? (his|her|their) "
                r"(commands|sit)|trainable"),
         ["Smart enough to learn tricks, smarter about getting treats.",
          "I already know 'sit.' Negotiating 'stay' for snacks.",
          "Quick learner, quicker at spotting the treat bag.",
          "Clever enough to be a minor problem.",
          "Trainable, and fully aware of the leverage.",
          "I learn fast. I negotiate faster.",
          "Give me a puzzle. Then a snack.",
          "Smart dog seeking someone to keep up.",
          "I know several words and I'm bluffing about more.",
          "Sharp, willing, mildly opinionated.",
          "Teach me anything. Bring currency.",
          "Intelligent, obedient, occasionally strategic."]),
        (6, has(r"loves? (food|treats|snacks|to eat)|foodie|food motivated"),
         ["I work exclusively for snacks. Rates are very reasonable.",
          "Food-motivated is an understatement.",
          "I would do anything for a treat. Anything.",
          "Dinner is my favorite time of day. And breakfast.",
          "Highly trainable, entirely for snacks.",
          "Every meal is the best meal.",
          "Is that food? It's food, isn't it.",
          "Treats accepted in any quantity."]),
        (5, age_years is not None and age_years < 1,
         ["Basically a toddler with paws — chaos included, free.",
          "Small everything, big plans. Still mastering stairs.",
          "Puppy. Everything is new and I'm thrilled.",
          "Brand new here. Teach me the rules.",
          "I chew things. We're working on it.",
          "Growing fast, learning faster.",
          "Puppy energy, puppy breath, puppy everything.",
          "Still figuring out my own legs.",
          "Young, delighted, occasionally a disaster.",
          "Everything is a toy until told otherwise.",
          "I nap hard between adventures.",
          "Baby dog seeking patient human.",
          "Fresh out of the box.",
          "Tiny now. Ask me again in a year."]),
        (5, age_years is not None and age_years >= 8,
         ["Old enough to know naps are a lifestyle, not a phase.",
          "Distinguished, grey around the edges, expert cuddler.",
          "Senior discount on energy, none on love.",
          "I've done the wild years. Now I'd like a couch.",
          "Grey muzzle, gold heart.",
          "Older, wiser, softer.",
          "I know exactly what I want: this, but indoors.",
          "Low mileage on trouble, high mileage on love.",
          "Retired from chaos. Available for company.",
          "Seasoned, settled, still very good.",
          "Older model, fully loaded.",
          "Slow walks, deep naps, total devotion.",
          "I've got years left and stories to tell.",
          "Dignified, mostly. Ask about dinner."]),
        (4, is_big,
         ["Big enough to hog the whole bed. Willing to share. Mostly.",
          "Gentle giant and part-time weighted blanket.",
          "Large dog, larger heart.",
          "I'm a lap dog. The lap is a formality.",
          "Big, soft, and convinced I'm portable.",
          "Takes up half the couch, earns all of it.",
          "Substantial. In every sense.",
          "I lean like furniture and love like family.",
          "Big paws, bigger opinions about bedtime.",
          "Room for one more? I'll need most of it.",
          "Full-size dog, full-size affection.",
          "I don't know my own size and won't be told.",
          "Heavyweight cuddler, undefeated.",
          "More dog per dog."]),
        (4, is_small,
         ["Small dog, tiny footprint, enormous opinions.",
          "Pocket-sized and fully prepared to run your household.",
          "Compact, portable, extremely in charge.",
          "Little dog, loud feelings.",
          "I fit anywhere. Especially your lap.",
          "Small enough to carry, stubborn enough to walk.",
          "Tiny body, enormous personality.",
          "Apartment-sized and thrilled about it.",
          "I'm small. My presence is not.",
          "Big dog energy, travel size.",
          "Fits in a bag. Would prefer the couch.",
          "Short legs, long list of demands.",
          "Little, loyal, lightly bossy.",
          "Sized for city living."]),
        (3, bool(breed),
         [f"One part {breed}, one part couch companion.",
          f"Mostly {breed}. The rest is pure personality.",
          f"Certified {breed}, minor in professional napping.",
          f"They say {breed}. I say devastatingly charming.",
          f"Half {breed}, half 'is that food?'",
          f"Pedigree says {breed}. Vibe says your best friend.",
          f"{breed.capitalize()} on paper, menace to squeaky toys in practice.",
          f"{breed.capitalize()} by breed, opportunist by trade.",
          f"Part {breed}, part shadow, all yours.",
          f"{breed.capitalize()}, allegedly. Sweetheart, definitely."]),
    ]
    return [(pri, lines) for pri, matched, lines in rules if matched]


def _quip_candidates(d: Dog) -> List[str]:
    """Every line this dog could truthfully say, best-grounded first.

    Within a tier the order is rotated by the dog's id, so two dogs matching the
    same tiers don't both reach for the same line first — otherwise the
    assignment below degrades into whoever is processed first taking line one.
    """
    import hashlib

    seed = int(hashlib.md5(d.id.encode("utf-8")).hexdigest(), 16)
    tiers = sorted(_quip_tiers(d), key=lambda t: -t[0])
    out, seen = [], set()
    for _, lines in tiers + [(0, _QUIP_ANY)]:
        lines = [ln for ln in lines if len(ln) <= _QUIP_MAX]
        if not lines:
            continue
        offset = seed % len(lines)
        for line in lines[offset:] + lines[:offset]:
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def _assign_quips(dogs: List[Dog]) -> None:
    """Give every dog a line no other dog on the page is using.

    Uniqueness has to be decided globally, not per dog: with 200+ dogs and a
    tier bank of a dozen lines, a purely local choice put the same sentence on
    49 cards. Dogs are served most-constrained first — one matching a single
    tier has far fewer options than one matching six, so it picks before the
    flexible dogs can take what it needed. Deterministic, so the same roster
    always renders the same page.

    A dog with nothing left says nothing: the bubble simply doesn't render,
    which is better than repeating a line two cards apart.
    """
    candidates = {d.id: _quip_candidates(d) for d in dogs}
    used = set()
    for d in sorted(dogs, key=lambda x: (len(candidates[x.id]), x.id)):
        d.quip = next((ln for ln in candidates[d.id] if ln not in used), "")
        if d.quip:
            used.add(d.quip)


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

    # After the loop: the hover lines have to be unique across the whole page,
    # so they can't be chosen one dog at a time.
    _assign_quips(dogs)
    return dogs
