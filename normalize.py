"""Central normalization pass — runs on every dog from every source.

The product promise is that a dog looks the same whether it came from a rich
JSON API or a scraped HTML page. Enforcing that per-scraper means six places to
get it wrong, so it happens once, here, after fetch.
"""
import re
from typing import List
from urllib.parse import urlsplit

import cities
from sources.base import Dog

# Chips are for *traits of the dog*. Shelter contact details, colors and other
# listing metadata leak in from some sources — drop them rather than render a
# phone number next to "Good with cats".
_CHIP_NOISE = re.compile(
    # "Shelter address: ..." puts a word between the keyword and the colon, so
    # allow for it — otherwise contact details render as if they were traits.
    r"^\s*(shelter|adoption|contact|phone|address|e-?mail|location|color|id|fee)"
    r"\b[^:]{0,24}[:#]",
    re.I,
)

# Marketing prose sneaks into these fields ("You won't find me at adoption
# events—reach out to meet me!"). A trait is a label, not a sentence.
_CHIP_PROSE = re.compile(r"[!?]|—|\breach out\b|\bcontact us\b|\bemail us\b", re.I)

_AGE_TIDY = [
    (re.compile(r"\s*old\s*$", re.I), ""),        # "13 years old" -> "13 years"
    (re.compile(r"\byrs?\b", re.I), "years"),
    (re.compile(r"\bmos?\b", re.I), "months"),
    (re.compile(r"\s{2,}"), " "),
]

# Verbose location strings like "Sean Casey Animal Rescue - Windsor Terrace,
# Brooklyn" repeat the rescue name we already show. Reduce to a neighbourhood or
# city, using the dog's own city's list — New York's boroughs are not useful for
# a dog in Los Angeles, and matching against every city's areas at once would let
# one city's place name rewrite another's.


def _tidy_age(age: str) -> str:
    a = (age or "").strip()
    for pat, rep in _AGE_TIDY:
        a = pat.sub(rep, a)
    return a.strip(" ,")


def _tidy_location(loc: str, source_label: str, city: str = None) -> str:
    l = (loc or "").strip()
    if not l:
        return ""
    c = cities.resolve(city)
    # Strip a leading "<Rescue Name> - " prefix.
    if source_label and l.lower().startswith(source_label.lower()):
        l = l[len(source_label):].lstrip(" -–—,")
    for area in c.areas:
        if area.lower() in l.lower():
            return f"{area}, {c.state}"
    if l.lower() in c.aliases:
        return c.location
    return l


# Traits split three ways so the UI can colour them honestly: a green tick for
# things that make adopting easier, an amber warning for things to plan around,
# and neutral grey for anything we can't confidently call either way. Guessing
# wrong here misleads someone about a real animal, so unmatched text stays grey.
_CAUTION = re.compile(
    r"(adult[- ]only|adult home|no (cats|dogs|kids|children|small)|"
    r"not good with|cannot live|can't live|only (dog|pet)|"
    r"experienced (owner|home|adopter|handler)|no first[- ]time|"
    r"special needs|medical|behavioral|reactive|resource guard|bite|"
    r"separation anxiety|escape|flight risk|fearful|anxious|shy|"
    r"sheds a lot|heavy shed|needs a yard|not house|"
    r"without (small|other)|special (diet|dietary|needs)|"
    r"home preferred|prefers to be|only (home|pet))", re.I)

_GOOD = re.compile(
    r"(good with|gets along|house[- ]?trained|housebroken|potty[- ]trained|"
    r"crate[- ]?trained|spayed|neutered|vaccinat|microchip|"
    r"up to date|low[- ]shed|sheds a little|hypoallergenic|"
    r"friendly|kid[- ]friendly|dog[- ]friendly|cat[- ]friendly|"
    r"leash[- ]?trained|well[- ]mannered|easy)", re.I)


def classify_attribute(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "info"
    # Caution wins: "good with dogs, no cats" must not read as purely positive.
    if _CAUTION.search(t):
        return "caution"
    if _GOOD.search(t):
        return "good"
    return "info"


def _tidy_chips(attrs: List[str]) -> List[str]:
    out, seen = [], set()
    for a in attrs or []:
        a = re.sub(r"\s+", " ", (a or "")).strip(" .")
        # A chip is a glance, not a sentence. Parenthetical caveats belong in
        # the write-up: "Adult home preferred (may consider older children)"
        # becomes "Adult home preferred".
        a = re.sub(r"\s*\([^)]*\)", "", a).strip(" .,")
        if not a or _CHIP_NOISE.match(a) or _CHIP_PROSE.search(a) or len(a) > 38:
            continue
        k = a.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(a)
    return out


def _tidy_weight(w: str) -> str:
    w = (w or "").strip()
    if not w:
        return ""
    m = re.search(r"([\d.]+)", w)
    if not m:
        return w
    try:
        n = float(m.group(1))
    except ValueError:
        return w
    return f"{int(n)} lbs" if n == int(n) else f"{n:.1f} lbs"


# Petstablished lets a video be uploaded down an .../uploads/image/image/...
# path, so the URL looks like a photo and only the extension gives it away. One
# of those reached a dog's og:image, where iMessage could not render it and fell
# back to the site icon, and reached the grid, where the card drew broken — in
# Chrome. WebKit paints the first frame of an mp4 inside an <img>, so the same
# listing looked fine in Safari, which is the worst way for it to fail.
#
# So they are separated rather than dropped: `photos` is what anything needing a
# still picture uses, `videos` is what the gallery offers as a clip.
#
# What plays is a narrower set than what is merely "not an image": .mp4 and .m4v
# are safe everywhere, .webm outside Safari, and .mov is a container that
# usually holds H.264 and usually plays. Anything else is neither — a PDF or an
# audio file is not a photo and not a clip, and belongs in neither list.
_VIDEO = (".mp4", ".m4v", ".mov", ".webm", ".ogv")
_NOT_A_PHOTO = _VIDEO + (".avi", ".mkv", ".mpg", ".mpeg", ".3gp",
                         ".mp3", ".wav", ".pdf")


def _ext_is(url: str, exts: tuple) -> bool:
    return urlsplit(url).path.lower().endswith(exts)


def _is_image(url: str) -> bool:
    return not _ext_is(url, _NOT_A_PHOTO)


def _is_video(url: str) -> bool:
    return _ext_is(url, _VIDEO)


def normalize(dogs: List[Dog]) -> List[Dog]:
    for d in dogs:
        d.name = re.sub(r"\s+", " ", (d.name or "")).strip() or "Unknown"
        d.age = _tidy_age(d.age)
        d.sex = (d.sex or "").strip().rstrip(".").capitalize()
        d.breed = re.sub(r"\s+", " ", (d.breed or "")).strip()
        d.weight = _tidy_weight(d.weight)
        d.location = _tidy_location(d.location, d.source_label, d.city)
        d.attributes = _tidy_chips(d.attributes)
        # Grouped by kind so the colours read as blocks instead of confetti.
        order = {"good": 0, "caution": 1, "info": 2}
        d.traits = sorted(
            ({"text": a, "kind": classify_attribute(a)} for a in d.attributes),
            key=lambda t: order[t["kind"]],
        )
        d.attributes = [t["text"] for t in d.traits]
        # One pass over whatever the source called photos, split by what the
        # file actually is. Videos already in d.videos are kept and de-duped.
        media = [p for p in list(d.photos or []) + list(d.videos or [])
                 if p and p.startswith("http")]
        seen = set()
        media = [p for p in media if not (p in seen or seen.add(p))]
        d.photos = [p for p in media if _is_image(p)]
        d.videos = [p for p in media if _is_video(p)]
        if not d.adopt_url:
            d.adopt_url = d.url
    return dogs
