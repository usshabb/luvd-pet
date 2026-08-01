"""Render the LUVD daily page.

One job: show every adoptable dog across a city's rescues, beautifully, and get
out of the way. Click a dog -> modal with everything we know -> one button out to
that rescue's own adopt page.

One page per city, each server-rendered with its own title, description,
canonical, social tags and structured data, and carrying only its own city's
dogs. `write()` authors every city in one pass — see the comment on it, because
doing it once per city would delete the other city's dog pages.

One flat grid, newest arrival first, with a NEW marker on the dogs that landed
today. Above it, four filter pills and a sort — deliberately the smallest set
that answers a real question, because Petfinder's wall of facets is the thing
we're not building. Every pill is a fact the rescues actually record, every
option carries a live count, and each pill's options are total over the roster,
so no dog is unreachable and no click leads to an empty page.
"""
import html
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import List
from urllib.parse import quote, urlsplit

import cities
from sources.base import Dog

OUT_DIR = Path(__file__).parent / "public"
CONTACT_EMAIL = "cory@luvd.com"


def _city_of(dogs, default: str = None) -> str:
    """Which city a group of dogs belongs to.

    Used by the per-dog and per-rescue pages, which are handed dogs rather than a
    city. A rescue's dogs are all one city, so the first stamped one settles it;
    an unstamped list means a run that predates the stamp, which is New York.
    """
    for d in dogs or ():
        if getattr(d, "city", ""):
            return d.city
    return default or cities.DEFAULT_CITY


def _terms_html(email: str, for_date) -> str:
    """Plain-language Terms of Use, written around what LUVD actually does:
    aggregate public rescue listings and point people to the rescues. The aim is
    to make clear we're an information tool, not a party to any adoption."""
    upd = for_date.strftime("%B %-d, %Y")
    return f"""
      <p class="upd">Last updated {upd}</p>
      <p>LUVD (&ldquo;LUVD,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;) is a free
        service that gathers publicly listed adoptable dogs from independent New
        York City animal rescues and shows them on one page each morning. By using
        LUVD you agree to these terms. If you don&rsquo;t agree, please don&rsquo;t
        use the site.</p>

      <h3>1. What LUVD is — and isn&rsquo;t</h3>
      <p>LUVD is an information and discovery tool. We are not an animal shelter,
        rescue, breeder, or adoption agency. We do not own, foster, house,
        transport, evaluate, or rehome any animal, and we are not a party to any
        adoption. Every adoption is handled entirely by the rescue that lists the
        dog, under that rescue&rsquo;s own process and terms.</p>

      <h3>2. Information is provided &ldquo;as is&rdquo;</h3>
      <p>Listings, photos, descriptions, ages, weights, breeds, and our estimated
        ratings (energy, apartment fit, experience needed) and breed guides are
        gathered from the rescues&rsquo; own listings and other third-party
        sources. They may be incomplete, out of date, or inaccurate. Our ratings
        are automated estimates for general guidance only — not professional,
        veterinary, training, or behavioral advice. The rescue is always the
        source of truth for any individual animal, and you should confirm every
        detail with them before making a decision.</p>

      <h3>3. No affiliation</h3>
      <p>LUVD is not affiliated with, endorsed by, or sponsored by any rescue,
        Petfinder, or other organization named on the site. All names, logos, and
        photos belong to their respective owners and are shown to help you find
        and contact the rescue directly.</p>

      <h3>4. Links to other sites</h3>
      <p>LUVD links out to rescue websites, applications, and listings. We
        don&rsquo;t control those sites and aren&rsquo;t responsible for their
        content, availability, accuracy, or practices.</p>

      <h3>5. Acceptable use</h3>
      <p>Use LUVD for your own personal, non-commercial search for a pet.
        Please don&rsquo;t scrape, copy, or republish the site, interfere with its
        operation, or misuse the contact and sharing features.</p>

      <h3>6. No warranties</h3>
      <p>LUVD is provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo;
        without warranties of any kind, express or implied, including accuracy,
        availability, or fitness for a particular purpose. We do not guarantee
        that any dog shown is still available.</p>

      <h3>7. Limitation of liability</h3>
      <p>To the fullest extent permitted by law, LUVD and its creator are not
        liable for any damages arising out of your use of (or inability to use)
        the site, your reliance on any information here, any interaction or
        adoption with a rescue, or the temperament, health, or condition of any
        animal.</p>

      <h3>8. Changes</h3>
      <p>We may update these terms or the site at any time. Continued use of LUVD
        means you accept the current version.</p>

      <h3>9. Contact</h3>
      <p>Questions about these terms? Email
        <a href="mailto:{email}?subject=LUVD">{email}</a>.</p>"""


def _privacy_html(email: str, for_date) -> str:
    """Plain-language Privacy Policy. LUVD collects almost nothing: an email for
    the digest, anonymous open counts, and optional interest requests. Saved dogs
    live in the browser and never reach us."""
    upd = for_date.strftime("%B %-d, %Y")
    return f"""
      <p class="upd">Last updated {upd}</p>
      <p>This explains what LUVD collects and how we use it. The short version:
        we collect as little as possible, and we never sell your data.</p>

      <h3>1. What we collect</h3>
      <ul>
        <li><b>Your email address</b> — only if you sign up for the morning
          digest. We use it to send you that email, and nothing else.</li>
        <li><b>Anonymous usage counts</b> — for example, how many times a
          dog&rsquo;s card has been opened. These are stored without any personal
          identifier, so we can show which dogs are getting attention.</li>
        <li><b>Optional requests</b> — if you tell us a species or city
          you&rsquo;d like us to cover, along with an email if you want a reply.</li>
      </ul>

      <h3>2. Your saved dogs stay on your device</h3>
      <p>The dogs you heart are stored locally in your browser. That list never
        leaves your device and is never sent to us.</p>

      <h3>3. How we use it</h3>
      <p>To send the digest you asked for, to understand which dogs draw interest,
        and to decide what to build next. That&rsquo;s it.</p>

      <h3>4. What we don&rsquo;t do</h3>
      <p>We don&rsquo;t sell, rent, or trade your information. We don&rsquo;t run
        advertising or third-party ad-tracking cookies. We don&rsquo;t share your
        email with anyone except the provider that delivers our email.</p>

      <h3>5. Service providers</h3>
      <p>We use a third-party email service to send the digest. Rescue links and
        photos may load from the rescues&rsquo; own sites and from Petfinder;
        those third parties have their own privacy practices, which we
        don&rsquo;t control.</p>

      <h3>6. Unsubscribe</h3>
      <p>Every email includes a one-click unsubscribe link, and we honor it
        immediately. You can also email us anytime to be removed.</p>

      <h3>7. Data retention</h3>
      <p>We keep your email until you unsubscribe. Anonymous counts may be kept
        indefinitely, since they contain no personal information.</p>

      <h3>8. Children</h3>
      <p>LUVD is intended for adults. We don&rsquo;t knowingly collect information
        from children under 13.</p>

      <h3>9. Contact</h3>
      <p>Questions or requests about your data? Email
        <a href="mailto:{email}?subject=LUVD">{email}</a>.</p>"""

# How each rescue actually wants to be approached, verified against their own
# pages. Most require an application FIRST — Muddy Paws says outright that only
# registered adopters may email them — so a blanket "email the rescue" button
# would send people down the wrong path and waste the rescue's time.
_CONTACTS_FILE = Path(__file__).parent / "rescue_contacts.json"
try:
    RESCUE_CONTACTS = json.loads(_CONTACTS_FILE.read_text())
except Exception:
    RESCUE_CONTACTS = {}


def rescue_home(source: str) -> str:
    """The rescue's own homepage, from whatever URL we hold on file for them.

    The contact page is preferred over the application URL because several
    rescues host their forms on a platform (Petstablished, Salesforce) whose
    origin isn't theirs. rescueHome() in the client script does the same for the
    modal byline; this is the equivalent for the static pages.
    """
    contact = RESCUE_CONTACTS.get(source) or {}
    for key in ("contact_url", "apply_url"):
        parts = urlsplit(contact.get(key) or "")
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return ""


# Chrome for the static crawlable pages (/rescue/*, /rescues). A plain constant
# rather than CSS inlined into an f-string: braces there need doubling, the last
# version was one short, and every rescue page shipped `body{{...}}` — invalid,
# so they all rendered unstyled.
_STATIC_PAGE_CSS = """
  :root{--bg:#fbfbfd;--surface:#fff;--text:#1d1d1f;--muted:#6e6e73;
    --accent:#FF002E;--hair:rgba(0,0,0,.1);}
  @media (prefers-color-scheme:dark){:root{--bg:#000;--surface:#1c1c1e;
    --text:#f5f5f7;--muted:#98989d;--hair:rgba(255,255,255,.14);}}
  *{box-sizing:border-box;}
  body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",
    Roboto,sans-serif;max-width:760px;margin:0 auto;
    padding:26px 20px 72px;line-height:1.6;background:var(--bg);
    color:var(--text);-webkit-font-smoothing:antialiased;}
  a{color:var(--accent);text-decoration:none;}
  a:hover{text-decoration:underline;}
  .back{font-size:14px;color:var(--muted);}
  h1{font-size:clamp(28px,5vw,38px);letter-spacing:-.03em;line-height:1.1;
    margin:22px 0 10px;}
  h2{font-size:20px;letter-spacing:-.02em;margin:0 0 4px;}
  .lead{color:var(--muted);font-size:16.5px;margin:0 0 26px;}
  .out{display:inline-block;font-size:14px;font-weight:600;margin-bottom:26px;}
  .card{background:var(--surface);border:1px solid var(--hair);
    border-radius:16px;padding:18px 20px;margin-bottom:14px;}
  .card .meta{color:var(--muted);font-size:14px;margin:0;}
  .card .links{font-size:14px;margin:10px 0 0;}
  ul.dogs{list-style:none;padding:0;margin:0;}
  ul.dogs li{padding:11px 0;border-top:1px solid var(--hair);font-size:16px;}
  ul.dogs li .b{color:var(--muted);font-size:14px;}
  footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--hair);
    color:var(--muted);font-size:13.5px;}
"""


# The four ratings, their icons and the words at each of the five stops.
# Python rather than a JS literal because two renderers need them now: the
# modal builds them in the browser, and the per-dog page builds the same rows
# server-side. Two copies of these words would drift, and the words are the
# whole point — they were rewritten once already for being unclear.
SCALE = {
    "energy": {"icon": "⚡", "label": "Energy level",
               "words": ["Couch potato", "Low key", "Middle of the road",
                         "Active", "Zoomies"]},
    "apartment": {"icon": "🏙️", "label": "Apartment fit",
                  "words": ["Needs a yard", "Tight in a flat", "Workable",
                            "Good fit", "Fine in a studio"]},
    "experience": {"icon": "🎓", "label": "Experience needed",
                   "words": ["Great first dog", "Beginner friendly",
                             "Some experience", "Experienced home",
                             "Needs experience"]},
    "alone": {"icon": "🏠", "label": "Home alone",
              "words": ["Needs company", "Short days only", "Half a day",
                        "Most of a workday", "Fine all day"]},
}


# The before-paint theme bootstrap. A module constant with %LAT%/%LON% holes
# rather than an f-string, because the script is full of JS braces and
# doubling every one of them to survive an f-string is how the dog page CSS
# ended up with four braces per rule and no styling at all.
_THEME_SCRIPT = """<script>
// Dark mode follows the sun over the city this page is for, not a fixed clock.
// A 7pm/7am window is wrong for most of the year: NYC sunrise swings from
// 5:25am in June to 7:20am in January. Standard NOAA solar position, run before
// paint so there is no flash of the wrong theme.
(function () {
  try {
    var LAT = %LAT%, LON = %LON%, RAD = Math.PI / 180;
    var now = new Date();
    var start = Date.UTC(now.getUTCFullYear(), 0, 0);
    var doy = Math.floor((now.getTime() - start) / 86400000);
    var g = (2 * Math.PI / 365) * (doy - 1 + (now.getUTCHours() - 12) / 24);

    var eq = 229.18 * (0.000075 + 0.001868 * Math.cos(g)
      - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g)
      - 0.040849 * Math.sin(2 * g));
    var decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g)
      - 0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g)
      - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);

    // 90.833° accounts for refraction and the sun's disc.
    var cosHa = Math.cos(90.833 * RAD) / (Math.cos(LAT * RAD) * Math.cos(decl))
      - Math.tan(LAT * RAD) * Math.tan(decl);
    var theme;
    if (cosHa >= 1) { theme = 'dark'; }          // sun never rises
    else if (cosHa <= -1) { theme = 'light'; }   // sun never sets
    else {
      var ha = Math.acos(cosHa) / RAD;
      var sunrise = 720 - 4 * (LON + ha) - eq;    // minutes UTC
      var sunset  = 720 - 4 * (LON - ha) - eq;
      var mins = now.getUTCHours() * 60 + now.getUTCMinutes();
      theme = (mins >= sunrise && mins < sunset) ? 'light' : 'dark';
    }
    document.documentElement.setAttribute('data-theme', theme);
  } catch (e) { /* fall back to the OS preference */ }
})();
</script>"""


def _theme_script(c) -> str:
    """The theme bootstrap for one city, for any page that wants it.

    Shared rather than copied: a per-dog page needs the same palette as its
    city page, and a second copy would be a second place for the city's
    coordinates to go stale.
    """
    return (_THEME_SCRIPT.replace("%LAT%", f"{c.lat:.4f}")
                         .replace("%LON%", f"{c.lon:.4f}"))


def logo_img(cls: str = "brand-logo") -> str:
    """One logo in both themes — the white sticker outline is the brand."""
    return (f'<img class="{cls}" src="assets/luvd-logo.png" '
            f'alt="LUVD" width="1400" height="607">')


LOGO_SVG = logo_img()


# Breed groups for the filter pill, widest-net-first. Rescues write breed as
# free text ("Lab Mix", "German Shepherd Dog mix", "Shepherd (Unknown Type)
# Mix"), so the raw field has 44 spellings across 223 dogs with 20 of them
# appearing once — a dropdown of that is the DMV form we're trying not to build.
# Order matters: the first pattern to match wins, so specific beats generic.
_BREED_GROUPS = (
    ("Pit bull type", r"staffordshire|pit ?bull|american bully|\bbully\b"),
    ("Jindo", r"jindo"),
    ("Retriever", r"retriever|\blab\b|labrador|golden"),
    ("Shepherd", r"shepherd|malinois|collie|cattle dog|heeler"),
    ("Terrier", r"terrier|feist"),
    ("Hound", r"hound|beagle|coonhound|plott"),
    ("Husky", r"husky|siberian|malamute"),
    ("Small & fluffy",
     r"chihuahua|shih ?tzu|maltese|pomeranian|poodle|cockapoo|yorkie|pinscher|"
     r"papillon|bichon|havanese|schnauzer|pekingese|dachshund|pug\b|shiba"),
    ("Bulldog & mastiff", r"bulldog|boxer|mastiff|tosa"),
)

# Named rather than numeric, because "puppy" and "senior" are what people
# actually search for, and a slider over an age we often only know as "Adult"
# would imply precision we don't have.
_AGE_BUCKETS = (
    ("Puppy", 0, 12),
    ("Young", 12, 36),
    ("Adult", 36, 96),
    ("Senior", 96, 10_000),
)


def breed_group(dog: Dog) -> str:
    """Which breed pill a dog answers to.

    Mixed and unknown are one visible group rather than being hidden: they're a
    third of the roster, and a filter that silently drops 76 dogs teaches people
    the list is shorter than it is.
    """
    text = (dog.breed or "").lower()
    for name, pattern in _BREED_GROUPS:
        if re.search(pattern, text):
            return name
    if not text.strip() or "unknown" in text or "mixed" in text:
        return "Mixed / unknown"
    return "Other"


def age_months(raw: str) -> int:
    """Best-effort months from however the rescue wrote the age.

    Handles "3 months", "2 years", "2 years, 5 months", "6 Years", "a year",
    "approx 6 1/2 years", and the bare buckets ("Adult") that Petstablished
    hands back when no birthday was recorded. Returns -1 when there's nothing
    to read, which keeps a dog out of every age pill rather than guessing it
    into the wrong one.
    """
    text = (raw or "").strip().lower()
    if not text:
        return -1
    words = {"puppy": 6, "young": 18, "adult": 48, "senior": 108, "baby": 4,
             "a year": 12}
    if text in words:
        return words[text]
    years = re.search(r"([\d.]+)\s*(?:1/2\s*)?y", text)
    months = re.search(r"([\d.]+)\s*mo", text)
    try:
        if years:
            total = int(float(years.group(1)) * 12) + (6 if "1/2" in text else 0)
            return total + (int(float(months.group(1))) if months else 0)
        if months:
            return int(float(months.group(1)))
    except ValueError:
        return -1
    return -1


# Small / Medium / Large by the weight the dog will be GROWN, in pounds. Three
# buckets rather than four because the fourth was 1% of the roster, and the
# boundaries are stated on screen ("Medium · 25–50 lbs") rather than left for a
# reader to infer — "medium" on its own means whatever the last dog they met
# weighed.
#
# 25 and 50 are chosen against the actual distribution, not convention. The
# obvious 25/55 split put 54% of dogs in Medium, which is half the roster behind
# one option and a filter that barely filters. 25/50 gives 20/43/35.
_SIZE_BUCKETS = (
    ("Small", 0, 25),
    ("Medium", 25, 50),
    ("Large", 50, 10_000),
)


def _weight_lbs(text) -> float:
    """A rescue's typed weight in pounds, or 0. Handles "22 lbs", "6.6", "9 kg"."""
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    if not m:
        return 0.0
    try:
        value = float(m.group(1))
    except ValueError:
        return 0.0
    if re.search(r"\bkgs?\b", str(text), re.I):
        value *= 2.20462
    return value if 0 < value < 300 else 0.0


def adult_lbs(dog: Dog) -> float:
    """What this dog will weigh grown, in pounds, or 0 if we genuinely can't say.

    Grown weight rather than current, because a filter on current weight files a
    4-month shepherd under Small and sends somebody home with a dog four times
    the size they asked for. `enrich._size_outlook` already does the projecting;
    this adds the fallbacks it declines to make.

    Four sources, most trustworthy first:

      1. ``size_outlook.adult`` — the measured weight of a grown dog, or the
         midpoint of its breed's known adult range if it is still growing.
      2. The rescue's typed weight, when `_size_outlook` returned nothing at all.
         It does that whenever the age is unknown, since it cannot then say
         "fully grown" or "still growing" — but an unknown age does not make a
         real number on the page worthless, and most dogs in rescue are adults.
      3. The matched breed's adult range, when there is no weight either.
      4. Nothing. Deliberately NOT enrich's `_default` range of 30–45 lbs: that
         would file every unidentifiable dog under Medium on no evidence, which
         is a claim rather than a guess.

    Notably absent: the rescue's own `size` field. Measured against weight it is
    not usable — Animal Haven's "large" dogs have a median weight of 19 lbs
    against their own "medium" at 44, and across the roster 15 of 50 "small"
    dogs outweigh the lightest "large". Eleven rescues typing into four boxes
    with no shared definition.
    """
    outlook = getattr(dog, "size_outlook", None) or {}
    if outlook.get("adult"):
        try:
            return float(outlook["adult"])
        except (TypeError, ValueError):
            pass
    typed = _weight_lbs(getattr(dog, "weight", ""))
    if typed:
        return typed
    try:
        from enrich import _BREEDS, _match_breed
        key = _match_breed(dog.breed or "")
        rng = _BREEDS.get(key, {}).get("adult_lbs") if key else None
        if rng:
            return sum(rng) / 2
    except Exception:
        pass
    return 0.0


def size_bucket(dog: Dog) -> str:
    """Small / Medium / Large, or "Unknown" when there is nothing to go on.

    "Unknown" rather than "" for the same reason age_bucket does it: every dog
    lands in exactly one option, so the counts in the menu add up to "Any size"
    and no dog sits in the roster while being unreachable by clicking.
    """
    lbs = adult_lbs(dog)
    if lbs <= 0:
        return "Unknown"
    for name, low, high in _SIZE_BUCKETS:
        if low <= lbs < high:
            return name
    return "Unknown"


def age_bucket(dog: Dog) -> str:
    """Puppy / Young / Adult / Senior, or "Unknown" when the age is unreadable.

    Never "": every dog has to land in exactly one bucket, so that the counts in
    the age menu sum to its "Any age" total. A dog in "Any" and in no option is
    a dog you cannot reach by clicking, and the missing one makes the arithmetic
    on screen look wrong.
    """
    months = age_months(dog.age)
    if months < 0:
        return "Unknown"
    for name, low, high in _AGE_BUCKETS:
        if low <= months < high:
            return name
    return "Unknown"


def _chip_facts(dog: Dog):
    """The skimmable pills on the card face, as (text, kind) pairs.

    A placement program leads when there is one, then breed. Program first
    because it decides whether a dog is even a candidate — Korean K9's
    foster-to-adopt dogs haven't landed in the US yet, and that shouldn't be the
    fact the 3-pill (2 on mobile) cap cuts. Breed is next, being what adopters
    scan for otherwise.
    """
    out = []
    if dog.program_label:
        out.append((dog.program_label, "program"))
    if dog.breed and "unknown" not in dog.breed.lower():
        out.append((dog.breed.split("/")[0].split(",")[0].strip()[:22], "breed"))
    if dog.age:
        out.append((dog.age, ""))
    if dog.weight:
        out.append((dog.weight, ""))
    elif dog.size:
        out.append((dog.size.title(), ""))
    if dog.sex:
        out.append((dog.sex, ""))
    # Three max, one line: a wrapping second row makes that grid row taller than
    # its neighbours and the whole grid stops lining up.
    return out[:3]


def slugify(text: str) -> str:
    """URL-safe slug. Kept stable — these become indexed URLs."""
    t = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", t) or "dog"


def rescue_slug(dog: Dog) -> str:
    return slugify(dog.source_label)


def dog_slug(dog: Dog) -> str:
    """rescue/name-breed — the words people actually search, not just a name.

    The source id is appended so two dogs called Bella at one rescue can't
    collide, and so the URL survives a rename.
    """
    bits = [dog.name]
    if dog.breed and "unknown" not in dog.breed.lower():
        bits.append(dog.breed.split("/")[0].split(",")[0])
    ident = dog.id.split(":", 1)[-1]
    return f"{slugify('-'.join(bits))}-{slugify(ident)}"


def dog_path(dog: Dog) -> str:
    return f"/dog/{rescue_slug(dog)}/{dog_slug(dog)}"


# Only surface a wait once it means something. Below this it is noise, and for
# the first weeks after launch we simply have no history to show.
WAIT_BADGE_DAYS = 60

# The wait badge is off on the grid cards. Once the scrapers started supplying
# real listing dates, 60 days put it on 104 of 223 cards, and 86 of those were
# NYC Second Chance — three quarters of their roster. A badge on half the grid
# signals nothing, and concentrated in one rescue it reads as a verdict on them
# rather than a nudge about a dog. To revive it, raise WAIT_BADGE_DAYS first:
# 180 days is still 62 cards.
#
# Deliberately only the cards. The dog page and modal still show the wait, where
# you're reading one dog and it's a useful fact rather than a pattern across the
# grid, and waiting_days still powers the "Longest waiting" sort.
SHOW_WAIT_BADGE_ON_CARDS = False

# Cities in the headline picker that LUVD does not cover. Not in cities.py: that
# registry is what the app runs on, and these are demand signals — a name in a
# menu, an /interest row, and nothing else. Promoting one means adding it there
# with its scrapers, at which point it leaves this list.
SOON_CITIES = (("CHI", "Chicago"), ("BOS", "Boston"), ("SF", "San Francisco"))

# The NEW marker is unconditional: a dog first seen today is marked today, on
# every page, however many of them there are.
#
# There used to be a NEW_MARK_MAX_SHARE = 0.5 here that withheld the marker when
# today's arrivals were more than half the grid, on the reasoning that a marker
# on every card marks nothing. That reasoning is about how the page looks. It
# loses to what the marker is for: it is the answer to "what showed up today",
# which is the whole promise of the product and the one thing a returning visitor
# is scanning for. Withholding it on a busy day is withholding it exactly when
# there is most to say, and it fails silently — the badge simply is not there,
# which reads as "nothing new today" rather than "too much was new to tell you".
#
# It also made the marker impossible to trust: LA showed it on none of 89 dogs
# and New York on none of 234, so nobody could tell the feature from a bug.
#
# The case the old threshold really guarded against was a first_seen column full
# of today — a fresh database, or dates that got rewritten. That is a data
# problem, and hiding the marker hid the symptom instead of surfacing it.
#
# How recently the RESCUE must have listed a dog for "first seen today" to be
# believable. first_seen only knows when LUVD noticed a dog, so it says "new"
# for two things that are not the same: a dog that genuinely arrived, and a dog
# that was already waiting when we started watching its rescue. Adding a rescue
# backfills its entire roster as new — all 139 of LA's dogs on the day the third
# and fourth rescues landed — and a dog whose discovery date gets rewritten looks
# new again years into its wait.
#
# So the rescue's own publish date has to corroborate ours. Measured on live data
# the day this went in: of the 139 LA dogs first seen that day, 75 had been
# listed for over 180 days and 23 for one to six months; of New York's 148, 55
# were over 180 days old. None of those is news. Seven days is wide enough to
# survive the lag between a rescue listing a dog and our next run finding it —
# and wide enough that a rescue posting in a weekly batch still gets marked —
# while excluding every one of those long-waiting dogs.
#
# A dog whose rescue publishes no date at all is allowed through on our own
# sighting, because that is the only evidence there is and 12 LA and 11 New York
# dogs would otherwise never be markable. waiting_days() already falls back to
# first_seen for exactly this case, which makes it 0 here rather than unknown.
NEW_MARK_MAX_LISTED_DAYS = 7

# What that marker says. One string, because it appears on the grid card, in the
# modal and on the dog's own page, and three copies would drift.
NEW_MARK_LABEL = "New here"

# The "this opens a menu" chevron, on the two headline pickers, the three filter
# pills and the sort. Drawn, not the character ▾: that glyph is small for its
# font size, differently proportioned in every platform font, and — being text —
# it sat inside each button's accessible name, so a screen reader could announce
# "black down-pointing small triangle" after the label. One constant because six
# copies of a path drift. The viewBox is cropped to the ink so em sizing controls
# the chevron itself rather than the whitespace around it.
CHEVRON = ('<svg class="cv" viewBox="0 0 12 8" aria-hidden="true" '
           'focusable="false"><path d="m1 1.6 5 5 5-5"/></svg>')


def waiting_days(dog: Dog, today: date):
    """Days listed. Prefers the rescue's own publish date over our first sight.

    first_seen only knows when LUVD noticed a dog, so on its own it understates
    every dog that was already waiting before we started watching.
    """
    src = dog.listed_since or dog.first_seen
    if not src:
        return None
    try:
        return max(0, (today - date.fromisoformat(src)).days)
    except ValueError:
        return None


def _is_new_today(dog: Dog, today_iso: str, today: date) -> bool:
    """Did this dog actually arrive today, as opposed to being newly noticed?

    Two conditions, and both are needed. LUVD has to have seen it for the first
    time today, and the rescue's own publish date has to be recent enough to
    back that up — because "we saw it first today" is also true of every dog on
    a rescue's roster the day that rescue is added, and of any dog whose
    discovery date gets rewritten. See NEW_MARK_MAX_LISTED_DAYS.

    A dog with no publish date passes on our sighting alone: waiting_days()
    falls back to first_seen, which is 0 on the day we found it.
    """
    if not dog.first_seen or dog.first_seen != today_iso:
        return False
    return (waiting_days(dog, today) or 0) <= NEW_MARK_MAX_LISTED_DAYS


def _card(d: Dog, i: int, today: date, is_new: bool = False) -> str:
    photo = d.primary_photo()
    if photo:
        media = (f'<img class="ph" src="{html.escape(photo)}" '
                 f'alt="{html.escape(d.name)}" loading="lazy">')
    else:
        # Usually a litter the rescue hasn't photographed yet — worth showing,
        # so the tile is designed rather than broken.
        initial = html.escape(d.name.strip()[:1].upper() or "?")
        media = (f'<div class="ph noph"><span class="noph-i">{initial}</span>'
                 f'<span class="noph-t">Photo coming soon</span></div>')
    pills = "".join(
        f'<span class="pill{(" " + kind) if kind else ""}">'
        f'{html.escape(text)}</span>'
        for text, kind in _chip_facts(d))

    wait = ""
    if SHOW_WAIT_BADGE_ON_CARDS:
        wd = waiting_days(d, today)
        if wd is not None and wd >= WAIT_BADGE_DAYS:
            wait = f'<span class="waiting" title="Listed {wd} days">⏳ {wd} days</span>'

    quip = (f'<span class="quip"><span>{html.escape(d.quip)}</span></span>'
            if d.quip else "")

    # The daily-digest signal, which used to be the date heading a dog sat under.
    # It sits on the photo, in the corner the wait badge vacated. Whether a dog
    # earns it is _is_new_today()'s call: first seen today, and listed by its
    # rescue recently enough that "today" is about the dog rather than about when
    # we started watching.
    new_chip = (f'<span class="new-chip" title="New on LUVD today">'
                f'{html.escape(NEW_MARK_LABEL)}</span>' if is_new else "")

    # A real href so crawlers can reach every dog; JS intercepts the click and
    # opens the modal instead of navigating.
    return f"""
      <a class="card" href="{html.escape(dog_path(d))}" data-i="{i}"
         data-id="{html.escape(d.id)}">
        <div class="ph-wrap">{media}{quip}
          <span class="views" hidden><span class="eyes" aria-hidden="true">👀</span><b></b></span>
          {wait}{new_chip}
          <button class="save" data-id="{html.escape(d.id)}" type="button"
                  aria-pressed="false" aria-label="Save {html.escape(d.name)}">
            <svg class="hrt" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21C8
              18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 12 8C12.9 6 14.5
              4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 16 18 12 21Z"/></svg>
            <span class="burst" aria-hidden="true"></span>
          </button></div>
        <div class="meta">
          <div class="nm-row"><h3 class="nm">{html.escape(d.name)}</h3></div>
          <div class="pills">{pills}</div>
        </div>
      </a>"""


def _structured_data(flat, dated, site, for_date, rescues, meta_desc,
                     city: str = None) -> dict:
    """JSON-LD for search and answer engines.

    Three graphs: what the site is, the actual list of dogs (so an assistant can
    answer "what dogs are up for adoption in LA today" from real data), and the
    questions people actually ask. Facts here mirror the page — nothing is
    asserted that a visitor can't verify on screen.

    The page-level nodes are city-scoped, @id included, so the two cities'
    CollectionPage and FAQPage entities are distinct things rather than one
    entity described two contradictory ways. The site-wide WebSite and
    Organization nodes are shared, and the Organization serves every live city.
    """
    c = cities.resolve(city)
    page_url = f"{site}{c.path}" if c.path != "/" else f"{site}/"
    # Only live cities: an unopened city in areaServed is a claim we can't back
    # with a single dog.
    served = [cities.CITIES[k].name for k in cities.live_codes()]
    if len(served) > 1:
        served_phrase = ", ".join(served[:-1]) + f" and {served[-1]}"
    else:
        served_phrase = served[0] if served else c.name
    items = []
    for i, d in enumerate(flat[:60], 1):        # keep the payload sane
        about = {
            "@type": "Product",
            "name": d.name,
            "category": "Adoptable dog",
            "brand": {"@type": "Organization", "name": d.source_label},
        }
        if d.photos:
            about["image"] = d.photos[0]
        desc_bits = [b for b in (d.age, d.sex, d.breed, d.weight) if b]
        if desc_bits:
            about["description"] = " · ".join(desc_bits)
        # The dog's own page, not a fragment of this one. This used to be
        # `{page_url}#dog/{d.id}`, which is the id the modal opens on — but a
        # fragment is not a URL as far as a crawler is concerned: all 60 items
        # resolved to the same document, so the list asserted sixty things and
        # addressed one. Every dog already has a real page, written by the same
        # run and listed in sitemap.xml, and it is the only URL that can carry
        # its own title, description, photo and Product data. Pointing here is
        # what lets an answer engine cite an individual dog rather than the
        # roster it appeared on.
        dog_url = f"{site}{dog_path(d)}"
        about["url"] = dog_url
        items.append({
            "@type": "ListItem",
            "position": i,
            "url": dog_url,
            "item": about,
        })

    faq = [
        (f"How do I adopt a dog in {c.short}?",
         "Browse adoptable dogs on LUVD, open the dog you're interested in, "
         f"then use the button to contact that rescue directly. Some {c.short} "
         "rescues "
         "take email inquiries; most ask you to submit an adoption application "
         "first. LUVD links you to whichever step that rescue actually requires."),
        (f"Which {c.short} rescues does LUVD cover?",
         "LUVD currently follows " + ", ".join(rescues) + ". New arrivals from "
         + ("every one of them are" if len(rescues) > 1 else "them are")
         + " collected each morning."),
        (f"How much does it cost to adopt a dog in {c.name}?",
         "Adoption fees are set by each rescue and typically range from about "
         "$150 to $500, which usually covers spay/neuter, vaccinations and "
         "microchipping. The fee for each dog is shown on its page when the "
         "rescue publishes one."),
        ("Are these dogs good for apartments?",
         "Every dog on LUVD gets an apartment-fit rating alongside energy level "
         "and how much dog experience it needs. These are estimates based on the "
         "rescue's own write-up and breed tendencies — the rescue knows the "
         "individual dog best."),
        ("How often is LUVD updated?",
         "Every morning. Dogs stay listed for as long as their rescue still has "
         "them available, newest arrival first, and the dogs that appeared today "
         "are marked new."),
    ]

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{site}/#website",
                "url": f"{site}/",
                "name": "LUVD",
                # The SITE's description, not this page's. It used to be
                # meta_desc, which is city-specific — so one @id was described
                # as "228 dogs from 7 New York City rescues" on one page and
                # "138 from 4 Los Angeles rescues" on another. Same entity,
                # two contradictory claims, and a crawler merging the graph has
                # no way to pick. The page's own description belongs on the
                # CollectionPage below, and does still say it.
                "description": "Every new adoptable dog across "
                               f"{served_phrase} rescues, collected each "
                               "morning with the context listings leave out.",
                "inLanguage": "en-US",
                "publisher": {"@id": f"{site}/#org"},
            },
            {
                "@type": "Organization",
                "@id": f"{site}/#org",
                "name": "LUVD",
                "url": f"{site}/",
                # An ImageObject rather than a bare URL: Google's logo
                # guidance wants dimensions, and a bare string leaves it to
                # fetch and guess.
                "logo": {
                    "@type": "ImageObject",
                    "url": f"{site}/apple-touch-icon.png",
                    "width": 180,
                    "height": 180,
                },
                "email": CONTACT_EMAIL,
                "areaServed": [{"@type": "City", "name": n} for n in served]
                              if len(served) > 1
                              else {"@type": "City", "name": served_phrase},
                "description": "LUVD collects every new adoptable dog across "
                               f"{served_phrase} rescues into one page, "
                               "updated daily.",
            },
            {
                "@type": "CollectionPage",
                "@id": f"{page_url}#page",
                "url": page_url,
                "name": f"Adopt a dog in {c.short}",
                "description": meta_desc,
                "isPartOf": {"@id": f"{site}/#website"},
                "dateModified": for_date.isoformat(),
                "about": {"@type": "Thing", "name": f"Dog adoption in {c.name}"},
                "publisher": {"@id": f"{site}/#org"},
                # Every other page type declares a trail; the city pages are
                # the only ones that did not, which left the two cities looking
                # like unrelated roots rather than one site with a city under
                # it. The root's trail is one item — itself — which is what
                # tells a crawler this is the top rather than an orphan.
                "breadcrumb": {"@id": f"{page_url}#breadcrumb"},
                "mainEntity": {
                    "@type": "ItemList",
                    "name": f"Adoptable dogs in {c.name}",
                    "numberOfItems": len(flat),
                    "itemListElement": items,
                },
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{page_url}#breadcrumb",
                "itemListElement": (
                    [{"@type": "ListItem", "position": 1, "name": "LUVD",
                      "item": f"{site}/"}]
                    if c.path == "/" else
                    [{"@type": "ListItem", "position": 1, "name": "LUVD",
                      "item": f"{site}/"},
                     {"@type": "ListItem", "position": 2,
                      "name": f"Adopt a dog in {c.short}"}]
                ),
            },
            {
                "@type": "FAQPage",
                "@id": f"{page_url}#faq",
                "mainEntity": [
                    {"@type": "Question", "name": q,
                     "acceptedAnswer": {"@type": "Answer", "text": a}}
                    for q, a in faq
                ],
            },
        ],
    }


def render(dated, for_date: date = None, city: str = None) -> str:
    """`dated` is [(iso_date, [Dog, ...]), ...], newest day first.

    `city` is which city's page this is; it decides the copy, the canonical URL,
    the social tags, the structured data and which coordinates dark mode follows
    the sun over. It defaults to New York, so every pre-city caller is unchanged.

    The page itself is one flat grid, but the day grouping still comes in: it's
    how check.py already has the dogs, it's what tells us which cards get the
    NEW marker, and it puts the grid in newest-first order for free — the
    default sort. Flattening happens here rather than in every caller.
    """
    for_date = for_date or date.today()
    if dated and isinstance(dated[0], Dog):          # tolerate a flat list
        dated = [(for_date.isoformat(), list(dated))]

    flat: List[Dog] = [d for _, group in dated for d in group]
    c = cities.resolve(city or _city_of(flat))
    # The filter groupings are derived here, not in the browser: the breed
    # patterns and age parsing are fiddly enough to want testing, and the client
    # only needs the answer.
    # `path` is the dog's own page, and it comes from dog_path() rather than
    # being rebuilt in the browser on purpose: the same call writes the file, the
    # card's href and the sitemap entry, so a shared link cannot address a page
    # this run didn't write. Rebuilding the slug in JS would be a second
    # implementation of dog_slug() free to drift from the first.
    payload = json.dumps([
        dict(d.to_dict(), waiting_days=(waiting_days(d, for_date) or 0),
             breed_group=breed_group(d), age_bucket=age_bucket(d),
             size_bucket=size_bucket(d), adult_lbs=round(adult_lbs(d)) or None,
             path=dog_path(d))
        for d in flat
    ])
    subscribe_url = os.getenv("SUBSCRIBE_URL", "/subscribe")

    today_iso = for_date.isoformat()
    total = len(flat)

    # One grid, not a section per day. Day sections read well on a fresh
    # database where every dog arrived this morning, but in production the page
    # accumulates a section per day and only sheds one when a rescue delists a
    # dog — so within weeks a narrow filter scatters its handful of matches
    # across a dozen headings, each announcing "1 dog". The arrival date is
    # still here: it's the default sort, and today's dogs carry a NEW marker.
    # Today's genuine arrivals, all of them, however many there are: no share
    # threshold (see NEW_MARK_LABEL) but the rescue's own listing date has to
    # agree that the dog is new (see NEW_MARK_MAX_LISTED_DAYS).
    cards = []
    for i, d in enumerate(flat):
        cards.append(_card(d, i, for_date, is_new=_is_new_today(d, today_iso,
                                                               for_date)))
    grid = f'<div class="grid" id="grid">{"".join(cards)}</div>'

    site = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
    cache_bust = for_date.isoformat()
    page_url = f"{site}/" if c.path == "/" else f"{site}{c.path}"
    rescues = sorted({d.source_label for d in flat})
    meta_desc = (
        f"{total} adoptable dogs from {len(rescues)} {c.name} "
        f"rescue{'' if len(rescues) == 1 else 's'}, "
        f"updated every morning. Browse today's new arrivals with energy level, "
        f"apartment fit and breed guidance, then contact the rescue directly."
    )
    structured_data = json.dumps(_structured_data(flat, dated, site, for_date,
                                                  rescues, meta_desc, c.code))
    # A city whose scrapers all broke, or that launched before its first dog, must
    # not be published as an indexable page — a thin page on a real domain is a
    # lasting SEO liability, and it is not a page anybody should land on from a
    # search. `follow` so the links out of it still carry value.
    robots_meta = ("index, follow, max-image-preview:large" if flat
                   else "noindex, follow")

    # The city picker is plain links: choosing a city is an ordinary page load to
    # that city's own page. No JavaScript needed, cmd-click and "copy link" work,
    # and — the part that matters most today — it is a crawlable link, which is
    # how /la gets discovered at all. An instant client-side switch is a separate
    # piece of design and deliberately not this.
    #
    # Cities we don't cover stay buttons, because there is nowhere to send
    # anyone; those open the waitlist instead (see ALLOW_SOON below).
    opts = []
    for lc in cities.CITIES.values():
        if lc.live:
            current = ' aria-current="page"' if lc.code == c.code else ""
            opts.append(f'<a role="option" href="{lc.path}" data-v="{lc.code}" '
                        f'data-ok="1"{current}>{html.escape(lc.name)}</a>')
        else:
            # In the registry but not opened yet: still worth naming, because
            # seeing it listed as Soon is what makes the waitlist an answer
            # rather than a shrug. It becomes a link the day it goes live.
            opts.append(f'<button role="option" data-v="{lc.code}">'
                        f'{html.escape(lc.name)}</button>')
    for code, label in SOON_CITIES:
        opts.append(f'<button role="option" data-v="{code}">{label}</button>')
    city_options = "\n          ".join(opts)

    live_shorts = [cities.CITIES[k].short for k in cities.live_codes()]
    live_phrase = (" and ".join(live_shorts) if len(live_shorts) < 3
                   else ", ".join(live_shorts[:-1]) + f" and {live_shorts[-1]}")
    # Each rescue's own page targets a real search ("muddy paws rescue dogs"),
    # but nothing on the homepage linked to them — they were reachable only from
    # individual dog pages. Linking them here and in the footer is what gets
    # them crawled and gives them the homepage's authority.
    rescue_links = [f'<a href="/rescue/{slugify(label)}">{html.escape(label)}</a>'
                    for label in rescues]
    if len(rescue_links) > 1:
        rescue_sentence = ("LUVD follows " + ", ".join(rescue_links[:-1])
                           + f" and {rescue_links[-1]}.")
    else:
        rescue_sentence = (f"LUVD follows {rescue_links[0]}."
                           if rescue_links else "")
    footer_rescues = " &middot; ".join(rescue_links)

    scale_json = json.dumps(SCALE, ensure_ascii=False)

    # One checkbox per live city. The city whose page you are on starts ticked,
    # because that is the one you demonstrably came for — but the lists stay
    # separate, so ticking both is two subscriptions, not a merged one.
    def city_picks(prefix: str) -> str:
        return "".join(
            f'<label class="sub-city"><input type="checkbox"'
            f' name="{prefix}city" value="{o.code}"'
            f'{" checked" if o.code == c.code else ""}>'
            f'<span>{html.escape(o.short)}</span></label>'
            for o in (cities.CITIES[k] for k in cities.live_codes()))
    sub_picks = city_picks("")
    msub_picks = city_picks("m-")

    # Every city, as plain links, in the footer of every page. The only
    # crawlable route to /la was a single <a> inside the headline's city
    # dropdown — one link, from one page, inside a menu. A city is a top-level
    # section of this site and should be reachable from the foot of anything,
    # which is also the shape Google reads when it decides whether a site has
    # sections worth listing under the main result.
    foot_cities = " &middot; ".join(
        (f'<span class="foot-here">Dogs in {html.escape(o.short)}</span>'
         if o.code == c.code else
         f'<a href="{o.path}">Dogs in {html.escape(o.short)}</a>')
        + f' &middot; <a href="{o.rescues_path}">{html.escape(o.short)} rescues</a>'
        for o in (cities.CITIES[k] for k in cities.live_codes()))
    theme_script = _theme_script(c)

    empty = "" if flat else """
      <div class="empty">
        <div class="empty-emoji">🦴</div>
        <h2>Nothing listed right now</h2>
        <p>Every rescue we follow is empty at the moment. Check back tomorrow.</p>
      </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
{theme_script}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{c.title}</title>
<meta name="description" content="{meta_desc}">
<link rel="canonical" href="{page_url}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">

<!-- Social scrapers (iMessage, Slack, Twitter) reject relative image paths,
     so these are absolute. og.png is rebuilt nightly with real dog faces. -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="LUVD">
<meta property="og:url" content="{page_url}">
<meta property="og:title" content="{c.share_title}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{site}/og.png?v={cache_bust}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="LUVD — adoptable dogs across {c.name} rescues">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{c.share_title}">
<meta name="twitter:description" content="{meta_desc}">
<meta name="twitter:image" content="{site}/og.png?v={cache_bust}">
<meta name="theme-color" content="#FF002E">
<meta name="robots" content="{robots_meta}">

<!-- Structured data. The ItemList gives search and answer engines the actual
     dogs; the FAQ answers the questions people ask about adopting in NYC. -->
<script type="application/ld+json">{structured_data}</script>
<style>
  :root {{
    --bg:#fbfbfd; --surface:#fff; --text:#1d1d1f; --muted:#6e6e73;
    --hair:rgba(0,0,0,.08); --hair2:rgba(0,0,0,.045);
    --accent:#FF002E; --accent-soft:rgba(255,0,46,.1);
    --good:#1a8f3c; --good-soft:rgba(26,143,60,.12);
    --warn:#a86500; --warn-soft:rgba(168,101,0,.13);
    --shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.06);
    --shadow-lg:0 12px 48px rgba(0,0,0,.18);
    --nav:rgba(251,251,253,.72);
  }}
  /* Dark palette, applied either by the OS preference or by NYC clock time.
     The data-theme attribute is set before paint, so it wins over the media
     query in both directions and there's no flash. */
  @media (prefers-color-scheme:dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#000; --surface:#1c1c1e; --text:#f5f5f7; --muted:#98989d;
      --hair:rgba(255,255,255,.13); --hair2:rgba(255,255,255,.07);
      --accent-soft:rgba(255,0,46,.2);
      --good:#32d74b; --good-soft:rgba(50,215,75,.16);
      --warn:#ffb340; --warn-soft:rgba(255,179,64,.16);
      --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.5);
      --shadow-lg:0 12px 48px rgba(0,0,0,.7);
      --nav:rgba(0,0,0,.68);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#000; --surface:#1c1c1e; --text:#f5f5f7; --muted:#98989d;
    --hair:rgba(255,255,255,.13); --hair2:rgba(255,255,255,.07);
    --accent-soft:rgba(255,0,46,.2);
    --good:#32d74b; --good-soft:rgba(50,215,75,.16);
    --warn:#ffb340; --warn-soft:rgba(255,179,64,.16);
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.5);
    --shadow-lg:0 12px 48px rgba(0,0,0,.7);
    --nav:rgba(0,0,0,.68);
  }}
  *{{box-sizing:border-box;}}
  html{{-webkit-text-size-adjust:100%;scroll-behavior:smooth;}}
  /* Load-in. Everything starts settled if JS never runs, so a failed script
     can't leave the page invisible. */
  .boot .brand-wrap{{opacity:0;transform:scale(.94) translateY(8px);}}
  .boot h1,.boot .hero-cap{{opacity:0;transform:translateY(10px);}}
  .boot .card{{opacity:0;transform:translateY(14px);}}
  .ready .brand-wrap{{animation:riseIn .55s cubic-bezier(.2,.8,.25,1) both;}}
  .ready h1{{animation:riseIn .5s cubic-bezier(.2,.8,.25,1) .08s both;}}
  .ready .hero-cap{{animation:riseIn .5s cubic-bezier(.2,.8,.25,1) .16s both;}}
  .ready .card{{animation:riseIn .45s cubic-bezier(.2,.8,.25,1) both;
    animation-delay:calc(.22s + var(--i,0) * .035s);}}
  /* Retired once it has played. Re-sorting moves cards in the DOM, which would
     otherwise restart this animation and rise the whole grid in again. */
  .anim-done .card{{animation:none;}}
  @keyframes riseIn{{from{{opacity:0;transform:translateY(12px) scale(.99);}}
    to{{opacity:1;transform:none;}}}}
  @media (prefers-reduced-motion:reduce){{
    .boot .brand-wrap,.boot h1,.boot .hero-cap,.boot .card{{opacity:1;transform:none;}}
    .ready .brand-wrap,.ready h1,.ready .hero-cap,.ready .card{{animation:none;}}
    .card:hover .ph{{animation:none;transform:scale(1.045);}}
    .quip{{transition:opacity .2s ease;transform:none;}}
    .card:hover .quip{{transform:none;}}
  }}
  body{{margin:0;background:var(--bg);color:var(--text);line-height:1.47;
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;}}
  .wrap{{max-width:1120px;margin:0 auto;padding:0 24px;}}

  /* ---------- nav ---------- */
  nav{{position:sticky;top:0;z-index:50;background:var(--nav);
    backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);}}
  .nav-in{{position:relative;max-width:1120px;margin:0 auto;padding:0 24px;
    height:52px;display:flex;align-items:center;justify-content:space-between;
    gap:12px;}}
  .nav-date{{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis;}}
  .nav-date span{{color:var(--muted);font-weight:500;}}
  /* Every click into a dog is someone actually looking. Real number, live. */
  /* One centre slot holding both, so the swap reads as a transformation. */
  .nav-mid{{position:absolute;left:50%;transform:translateX(-50%);
    height:52px;display:grid;place-items:center;}}
  .nav-mid > *{{grid-area:1/1;}}
  .nav-logo{{opacity:0;transform:scale(.55) translateY(-6px);pointer-events:none;
    transition:opacity .28s ease,transform .38s cubic-bezier(.34,1.5,.6,1);
    display:block;}}
  .nav-logo img{{width:112px;height:auto;display:block;}}
  nav.shrunk .nav-logo{{opacity:1;transform:none;pointer-events:auto;}}
  nav.shrunk .nav-count{{opacity:0;transform:scale(.85);pointer-events:none;}}
  .nav-count{{display:flex;align-items:center;gap:7px;font-size:12.5px;
    transition:opacity .24s ease,transform .28s ease;
    color:var(--muted);white-space:nowrap;background:var(--hair2);
    border-radius:980px;padding:6px 13px;}}
  .nav-count[hidden]{{visibility:hidden;}}
  .nav-count b{{color:var(--text);font-weight:700;
    font-variant-numeric:tabular-nums;}}
  /* Room for seven figures without the bar reflowing. */
  .nav-count{{min-width:0;}}
  .nc-dot{{width:6px;height:6px;border-radius:50%;background:var(--good);
    box-shadow:0 0 0 0 var(--good);animation:pulse 2.4s ease-out infinite;}}
  @keyframes pulse{{
    0%{{box-shadow:0 0 0 0 rgba(50,215,75,.5);}}
    70%{{box-shadow:0 0 0 7px rgba(50,215,75,0);}}
    100%{{box-shadow:0 0 0 0 rgba(50,215,75,0);}}
  }}
  .nav-count b.bump{{animation:bump .45s cubic-bezier(.34,1.6,.64,1);}}
  @keyframes bump{{
    0%{{transform:scale(1);}} 45%{{transform:scale(1.35);color:var(--good);}}
    100%{{transform:scale(1);}}
  }}
  @media (max-width:860px){{ .nc-l{{display:none;}} }}
  @media (max-width:680px){{
    /* No room for the date or a centred mark. The saved-hearts chip is the
       thing people need to reach, so it takes the left edge. */
    .nav-date{{display:none;}}
    .nav-mid{{display:none;}}

  }}
  @media (prefers-reduced-motion:reduce){{
    .nc-dot,.nav-count b.bump{{animation:none;}}
  }}
  .logo{{font-size:14px;font-weight:800;letter-spacing:.2em;color:var(--accent);
    text-transform:uppercase;text-decoration:none;}}
  .nav-left{{display:flex;align-items:center;gap:12px;min-width:0;}}
  .nav-r{{display:flex;align-items:center;gap:8px;}}
  .nav-btn{{all:unset;box-sizing:border-box;cursor:pointer;font-size:13.5px;
    font-weight:500;color:var(--text);
    padding:7px 13px;border-radius:980px;transition:background .2s,opacity .2s;}}
  .nav-btn:hover{{background:var(--hair2);}}
  .nav-btn[hidden]{{display:none;}}
  .saved-chip{{color:var(--accent);font-weight:700;display:inline-flex;
    align-items:center;gap:6px;padding:7px 13px;border-radius:980px;
    background:var(--accent-soft);}}
  .saved-chip:hover{{background:var(--accent-soft);opacity:.85;}}
  .sc-hrt{{width:15px;height:15px;stroke:var(--accent);stroke-width:2;fill:none;
    transition:fill .2s ease;}}
  .saved-chip.has .sc-hrt{{fill:var(--accent);}}
  /* Nothing saved yet — present, but clearly not urgent. */
  .saved-chip.none{{color:var(--muted);background:var(--hair2);}}
  .saved-chip.none .sc-hrt{{stroke:var(--muted);}}
  /* Filtered state wins over both — must be unmistakable. */
  .saved-chip.active,.saved-chip.none.active{{background:var(--accent);
    color:#fff;}}
  .saved-chip.active .sc-hrt,.saved-chip.none.active .sc-hrt{{
    stroke:#fff;fill:#fff;}}
  .saved-chip.active:hover{{background:var(--accent);opacity:.9;}}
  .nav-cta{{background:var(--accent);color:#fff;font-weight:600;}}
  .nav-cta:hover{{background:var(--accent);opacity:.88;}}

  /* ---------- header ---------- */
  header{{text-align:center;padding:34px 0 8px;position:relative;z-index:40;}}
  h1{{font-size:clamp(34px,5.5vw,56px);line-height:1.14;letter-spacing:-.025em;
    font-weight:700;margin:0;position:relative;z-index:5;}}
  /* Two words in the headline become pickers. Everything stays real text, so
     the h1 still reads as one sentence to search engines and screen readers. */
  .pick{{position:relative;display:inline-block;z-index:45;}}
  .pick > button{{all:unset;cursor:pointer;font:inherit;color:var(--text);
    border-bottom:3px solid var(--hair);padding:0 2px;
    transition:border-color .2s;}}
  .pick > button:hover{{border-bottom-color:var(--accent);}}
  .pick > button:focus-visible{{outline:3px solid var(--accent);
    outline-offset:3px;border-radius:4px;}}
  /* Drawn, in the same idiom as the heart and the share icon: no fill, a
     currentColor stroke, round joins. See CHEVRON in page.py for why it stopped
     being a text character.
     Sized in em against whatever control holds it, so one declaration keeps the
     filter pills' chevrons in proportion across both breakpoints: 10.8px at the
     desktop 15px, 9.72px at the phone's 13.5px. Three hardcoded pixel sizes is
     what was here before, and they had already drifted: 9px on the pills
     against 13px on the sort. The two headline pickers and the sort each carry
     their own ratio against this one — see .pick .cv and .fpill.fsort .cv. */
  .cv{{width:.72em;height:.48em;flex:none;fill:none;stroke:currentColor;
    stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;
    color:var(--muted);display:inline-block;transition:transform .2s;}}
  /* The headline is up to 38px, where .72em would be a 27px chevron shouting at
     the word it belongs to. It takes its own ratio, which lands it at roughly
     the sort control's size — a chevron is a chevron whatever it hangs off.
     These two also sit inline in a sentence rather than in a flex button, so
     they need lifting off the baseline by hand. */
  .pick .cv{{width:.24em;height:.16em;margin-left:.14em;vertical-align:.14em;}}
  .pick.open .cv{{transform:rotate(180deg);}}
  .pick-menu{{position:absolute;top:calc(100% + 12px);left:50%;
    transform:translateX(-50%) translateY(-6px);z-index:48;
    background:var(--surface);border:1px solid var(--hair);border-radius:16px;
    box-shadow:0 1px 0 rgba(255,255,255,.06) inset,
               0 4px 12px rgba(0,0,0,.3),0 22px 60px rgba(0,0,0,.55);
    padding:6px;min-width:210px;
    display:flex;flex-direction:column;gap:2px;opacity:0;
    transition:opacity .18s ease,transform .22s cubic-bezier(.2,.8,.25,1);}}
  .pick-menu[hidden]{{display:none;}}
  .pick.open .pick-menu{{opacity:1;transform:translateX(-50%);}}
  /* A live city is an anchor, not a button: choosing one is an ordinary
     navigation to that city's own page, so it should behave like a link —
     middle-click, cmd-click and "copy link" all work, and it needs no
     JavaScript. The cities we don't cover yet stay buttons, because there is
     nowhere to send anyone and the click opens the waitlist instead. */
  .pick-menu button,.pick-menu a{{all:unset;cursor:pointer;font-size:16px;
    font-weight:500;
    padding:11px 14px;border-radius:10px;text-align:left;color:var(--text);
    display:flex;justify-content:space-between;align-items:center;gap:14px;}}
  .pick-menu button:hover,.pick-menu a:hover{{background:var(--hair2);}}
  .pick-menu button:disabled{{cursor:default;opacity:.45;}}
  .pick-menu button:disabled:hover{{background:transparent;}}
  .pick-menu [aria-current="page"]{{background:var(--hair2);}}
  .pick-menu button[data-ok]::after,
  .pick-menu a[data-ok]::after{{content:'Live';font-size:11px;
    font-weight:700;color:var(--good);letter-spacing:.04em;}}
  .pick-menu button:not([data-ok])::after{{content:'Soon';font-size:11px;
    font-weight:700;color:var(--muted);letter-spacing:.04em;}}

  /* A "coming soon" that only apologises is a dead end — capture the interest. */
  .soon{{max-width:460px;margin:20px auto 0;}}
  .soon[hidden]{{display:none;}}
  .soon p{{font-size:15.5px;color:var(--text);margin:0 0 14px;line-height:1.5;}}
  .soon p b{{color:var(--accent);}}
  /* Deliberately restrained: one row, no card, no heading of its own. The
     dogs stay the first real thing you see. */
  .hero-sub{{display:flex;gap:8px;max-width:432px;margin:26px auto 0;}}
  .hero-sub input{{flex:1;min-width:0;padding:12px 15px;font-size:15px;
    border-radius:11px;border:1px solid var(--hair);background:var(--surface);
    color:var(--text);font-family:inherit;}}
  .hero-sub input:focus{{outline:2px solid var(--accent);outline-offset:-1px;
    border-color:transparent;}}
  .hero-sub button{{all:unset;box-sizing:border-box;cursor:pointer;
    background:var(--accent);color:#fff;font-weight:600;font-size:15px;
    padding:12px 18px;border-radius:11px;white-space:nowrap;
    transition:opacity .2s;text-align:center;}}
  .hero-sub button:hover{{opacity:.88;}}
  .hero-note{{font-size:12.5px;color:var(--muted);margin-top:9px;}}
  /* The hero note rests empty; don't leave its margin behind holding space. */
  .hero-note:empty{{margin-top:0;}}
  .hero-note.ok{{color:var(--accent);font-weight:700;font-size:14px;}}
  .sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
    overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}}

  /* ---------- brand logo ---------- */
  .brand-wrap{{display:flex;justify-content:center;margin-bottom:10px;
    transition:opacity .3s ease,transform .3s ease;}}
  body.shrunk .brand-wrap{{opacity:0;transform:scale(.9) translateY(-10px);}}
  .brand-logo{{width:clamp(190px,27vw,330px);height:auto;cursor:pointer;display:block;
    transition:transform .45s cubic-bezier(.34,1.56,.64,1),filter .35s ease;
    will-change:filter,transform;transform:translateZ(0);
    /* Two soft drop-shadows: a tight one for the edge, a wide diffuse one so
       the mark lifts off the background rather than sitting flat on it. */
    filter:drop-shadow(0 2px 3px rgba(0,0,0,.14))
           drop-shadow(0 12px 26px rgba(0,0,0,.16));}}
  .brand-logo:hover{{animation:beat .72s cubic-bezier(.4,0,.6,1) infinite;
    filter:drop-shadow(0 3px 5px rgba(0,0,0,.18))
           drop-shadow(0 18px 38px rgba(0,0,0,.24));}}
  /* On black a dark shadow is invisible, so lift it with a faint glow instead. */
  :root[data-theme="dark"] .brand-logo{{
    filter:drop-shadow(0 2px 4px rgba(0,0,0,.6))
           drop-shadow(0 14px 32px rgba(255,255,255,.09));}}
  :root[data-theme="dark"] .brand-logo:hover{{
    filter:drop-shadow(0 3px 6px rgba(0,0,0,.7))
           drop-shadow(0 20px 44px rgba(255,255,255,.14));}}
  @keyframes beat{{
    0%,100%{{transform:scale(1) rotate(0deg);}}
    16%{{transform:scale(1.09) rotate(-1.6deg);}}
    32%{{transform:scale(1.01) rotate(0deg);}}
    50%{{transform:scale(1.06) rotate(1.2deg);}}
  }}
  .brand-logo.cheer,.nav-logo img.cheer{{
    animation:cheer .9s cubic-bezier(.34,1.5,.5,1) 1;}}
  @keyframes cheer{{
    0%{{transform:scale(1) rotate(0);}}
    22%{{transform:scale(1.22) rotate(-4deg);}}
    44%{{transform:scale(1.05) rotate(3deg);}}
    66%{{transform:scale(1.14) rotate(-2deg);}}
    100%{{transform:scale(1) rotate(0);}}
  }}
  @media (prefers-reduced-motion:reduce){{
    .brand-logo:hover{{animation:none;transform:scale(1.04);}}
    .brand-logo.cheer,.nav-logo img.cheer{{animation:none;}}
  }}
  /* Easter egg: paws drift up while you hover, and clicking sets off a burst. */
  .brand-wrap{{position:relative;}}
  .egg{{position:absolute;pointer-events:none;font-size:20px;left:50%;top:50%;
    will-change:transform,opacity;z-index:2;}}
  @keyframes drift{{
    0%{{transform:translate(-50%,-50%) scale(.4);opacity:0;}}
    22%{{opacity:.95;}}
    100%{{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy)))
          scale(var(--sc)) rotate(var(--rot));opacity:0;}}
  }}
  .woof{{position:absolute;left:50%;top:-6px;transform:translateX(-50%);
    background:var(--accent);color:#fff;font-size:12.5px;font-weight:700;
    padding:5px 12px;border-radius:980px;white-space:nowrap;pointer-events:none;
    animation:woofpop 1.5s cubic-bezier(.34,1.56,.64,1) forwards;z-index:3;}}
  @keyframes woofpop{{
    0%{{transform:translateX(-50%) scale(.3);opacity:0;}}
    18%{{transform:translateX(-50%) scale(1.12);opacity:1;}}
    30%{{transform:translateX(-50%) scale(1);}}
    78%{{opacity:1;}}
    100%{{transform:translateX(-50%) translateY(-14px) scale(.95);opacity:0;}}
  }}
  @media (prefers-reduced-motion:reduce){{ .egg{{display:none;}} }}

  /* Double-tap confirmation: a heart that punches in and fades. */
  .dbl-heart{{position:absolute;inset:0;display:grid;place-items:center;
    pointer-events:none;z-index:6;}}
  .dbl-heart svg{{width:34%;height:34%;fill:#fff;stroke:none;
    filter:drop-shadow(0 4px 16px rgba(0,0,0,.45));
    animation:dblpop .9s cubic-bezier(.2,.9,.3,1) forwards;}}
  @keyframes dblpop{{
    0%{{transform:scale(.3);opacity:0;}}
    18%{{transform:scale(1.15);opacity:.96;}}
    36%{{transform:scale(1);opacity:.96;}}
    100%{{transform:scale(1.08);opacity:0;}}
  }}
  @media (prefers-reduced-motion:reduce){{ .dbl-heart{{display:none;}} }}

  /* ---------- grid ---------- */
  .grid{{display:grid;gap:28px;padding:22px 0 8px;
    grid-template-columns:repeat(auto-fill,minmax(248px,1fr));}}
  .card{{all:unset;cursor:pointer;display:block;border-radius:20px;background:var(--surface);
    box-shadow:var(--shadow);overflow:hidden;
    transition:transform .3s cubic-bezier(.2,.8,.2,1),box-shadow .3s;}}
  .card:hover{{transform:translateY(-6px);box-shadow:var(--shadow-lg);}}
  .card:focus-visible{{outline:3px solid var(--accent);outline-offset:3px;}}
  .ph-wrap{{aspect-ratio:1/1;overflow:hidden;background:var(--hair);position:relative;}}
  .ph{{width:100%;height:100%;object-fit:cover;display:block;
    transition:transform .5s cubic-bezier(.2,.8,.2,1);}}
  /* A quick playful wiggle on hover, settling into a gentle zoom. The scale
     stays >1 throughout so the rotation never exposes the tile behind it. */
  .card:hover .ph{{animation:cardWiggle .55s cubic-bezier(.36,.07,.19,.97) both;}}
  @keyframes cardWiggle{{
    0%{{transform:scale(1) rotate(0);}}
    22%{{transform:scale(1.05) rotate(-2.4deg);}}
    44%{{transform:scale(1.05) rotate(1.9deg);}}
    64%{{transform:scale(1.05) rotate(-1.2deg);}}
    82%{{transform:scale(1.048) rotate(.6deg);}}
    100%{{transform:scale(1.045) rotate(0);}}
  }}
  /* The dog's own one-liner, in a little speech bubble that pops on hover.
     Hover-capable pointers only — on touch a stuck :hover would trap it open. */
  .quip{{display:none;}}
  @media (hover:hover) and (pointer:fine){{
    .quip{{display:block;position:absolute;left:12px;right:12px;bottom:12px;
      background:#fff;color:#1d1d1f;font-size:12.5px;font-weight:600;
      line-height:1.32;padding:9px 12px;border-radius:15px 15px 15px 4px;
      box-shadow:0 8px 22px rgba(0,0,0,.22);pointer-events:none;z-index:3;
      opacity:0;transform:translateY(8px) scale(.9);transform-origin:0 100%;
      transition:opacity .22s ease,transform .28s cubic-bezier(.34,1.56,.64,1);}}
    .quip span{{display:-webkit-box;-webkit-line-clamp:2;
      -webkit-box-orient:vertical;overflow:hidden;}}
    /* The tail — a little nib on the lower-left, so it reads as speech. */
    .quip::after{{content:"";position:absolute;left:14px;bottom:-6px;width:14px;
      height:14px;background:#fff;border-radius:0 0 0 3px;
      transform:rotate(45deg);box-shadow:-3px 3px 6px rgba(0,0,0,.06);}}
    .card:hover .quip{{opacity:1;transform:translateY(0) scale(1);}}
    /* The bubble lands on top of the badge, and "NEW HERE" is wide enough that
       its red ends stick out past both sides of the white — which reads as a
       rendering fault rather than two things overlapping. So the badge leaves
       while the bubble is up.
       Hidden rather than nudged out of the way: quips are per-dog strings of
       different lengths and some wrap to two lines, so any geometry that clears
       today's longest quip stops clearing it the next time the bubble grows or
       the card narrows. Nothing is lost — the bubble is what you're reading
       while you hover, and the badge is back the moment you leave.
       Inside this media query on purpose: on a phone there is no bubble, so
       there is nothing to hide behind and the badge must stay put. It fades on
       the bubble's own opacity curve so the two read as one move; the badge
       never transforms, so the reduced-motion block below has nothing to
       undo here. */
    .new-chip{{transition:opacity .22s ease;}}
    .card:hover .new-chip{{opacity:0;}}
  }}
  :root[data-theme="dark"] .quip{{background:#2b2b2e;color:#f2f2f2;}}
  :root[data-theme="dark"] .quip::after{{background:#2b2b2e;}}
  .noph{{display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:10px;height:100%;
    background:linear-gradient(150deg,var(--accent-soft),transparent 72%);}}
  .noph-i{{font-size:58px;font-weight:800;letter-spacing:-.04em;
    color:var(--accent);opacity:.55;line-height:1;}}
  .noph-t{{font-size:11.5px;font-weight:600;letter-spacing:.03em;
    color:var(--muted);}}
  /* Real click counts, fetched live. Hidden until a dog has genuine interest —
     never a fabricated number. */
  .views{{position:absolute;left:11px;top:11px;display:flex;align-items:center;gap:5px;
    font-size:13px;font-weight:700;padding:6px 11px;border-radius:980px;color:#fff;
    background:rgba(0,0,0,.55);backdrop-filter:blur(10px);
    -webkit-backdrop-filter:blur(10px);animation:pop .35s cubic-bezier(.34,1.56,.64,1);}}
  /* display:flex above would otherwise beat the [hidden] attribute. */
  .views[hidden]{{display:none;}}
  /* Eyes, not a flame. The number is how many people have opened this dog's
     card — a plain count of who looked, which is useful to an adopter deciding
     whether to hurry. A flame reads as "trending", which turns the same number
     into a popularity contest and quietly tells you the quiet dogs matter less.
     Every dog here is waiting; the badge should say "looked at", not "hot". */
  .views .eyes{{font-size:13px;line-height:1;}}
  @keyframes pop{{from{{transform:scale(.6);opacity:0;}}to{{transform:scale(1);opacity:1;}}}}
  .card{{text-decoration:none;color:inherit;}}
  .meta{{padding:15px 16px 17px;}}
  /* Rescue moves off the photo and sits beside the name, where it reads as
     attribution rather than a sticker. */


  /* Long-stay marker. Exception-based: most dogs never show it. */
  .waiting{{position:absolute;right:11px;bottom:11px;font-size:10.5px;
    font-weight:700;padding:5px 10px;border-radius:980px;color:#fff;
    background:rgba(168,101,0,.85);backdrop-filter:blur(10px);
    -webkit-backdrop-filter:blur(10px);}}

  /* Save — sits on the photo, only fully opaque once saved. */
  .save{{position:absolute;right:11px;top:11px;width:34px;height:34px;
    border:none;border-radius:50%;cursor:pointer;padding:0;
    background:rgba(0,0,0,.5);backdrop-filter:blur(10px);
    -webkit-backdrop-filter:blur(10px);display:grid;place-items:center;
    transition:transform .2s cubic-bezier(.34,1.6,.64,1),background .2s;}}
  .save:hover{{transform:scale(1.1);background:rgba(0,0,0,.68);}}
  .save:active{{transform:scale(.9);}}
  .hrt{{width:18px;height:18px;fill:none;stroke:rgba(255,255,255,.85);
    stroke-width:1.9;stroke-linejoin:round;
    transition:fill .18s ease,stroke .18s ease,transform .3s
      cubic-bezier(.34,1.8,.5,1);}}
  .save:hover .hrt{{stroke:#fff;}}
  .save.on .hrt{{fill:var(--accent);stroke:var(--accent);}}
  /* Overshoot on save, nothing on unsave — the reward belongs to one direction. */
  .save.pop .hrt{{animation:hrtpop .48s cubic-bezier(.34,1.7,.5,1);}}
  @keyframes hrtpop{{
    0%{{transform:scale(1);}} 30%{{transform:scale(1.45);}}
    55%{{transform:scale(.92);}} 100%{{transform:scale(1);}}
  }}
  /* A ring that expands and fades out from under the heart. */
  .burst{{position:absolute;inset:0;border-radius:50%;pointer-events:none;
    border:2px solid var(--accent);opacity:0;}}
  .save.pop .burst{{animation:ring .55s cubic-bezier(.2,.7,.3,1);}}
  @keyframes ring{{
    0%{{transform:scale(.7);opacity:.9;}}
    100%{{transform:scale(2.1);opacity:0;}}
  }}
  .fh{{position:fixed;pointer-events:none;z-index:200;color:var(--accent);
    transform:translate(-50%,-50%);will-change:transform,opacity;opacity:0;
    line-height:1;}}
  @keyframes floatheart{{
    0%{{transform:translate(-50%,-50%) scale(.4);opacity:0;}}
    25%{{opacity:1;}}
    100%{{transform:translate(calc(-50% + var(--dx)),calc(-50% + var(--dy)))
      scale(1.1) rotate(var(--rot));opacity:0;}}
  }}
  @media (prefers-reduced-motion:reduce){{
    .save.pop .hrt,.save.pop .burst{{animation:none;}}
    .fh{{display:none;}}
  }}
  .nm-row{{display:flex;align-items:center;gap:7px;margin:0 0 10px;}}
  .nm{{font-size:23px;font-weight:700;letter-spacing:-.02em;margin:0;min-width:0;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
  /* Arrived today. On a busy morning most cards carry this, so it's sized like
     the wait badge rather than the old day heading's chip — a marker you can
     scan past, not a sticker on every dog. */
  /* On the photo, bottom-right, the corner the wait badge used to hold. Solid
     accent rather than the old tinted pill: it has to hold up over a photo
     instead of a white card. The hover quip covers it on desktop, which is
     fine — that hover is a deliberate takeover of the tile. */
  .new-chip{{position:absolute;right:11px;bottom:11px;z-index:2;
    font-size:9.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
    color:#fff;background:var(--accent);padding:4px 9px;border-radius:980px;
    box-shadow:0 2px 10px rgba(0,0,0,.22);}}
  /* nowrap keeps every card the same height so the grid stays aligned */
  .pills{{display:flex;flex-wrap:nowrap;gap:5px;overflow:hidden;}}
  .pill{{font-size:11.5px;font-weight:500;padding:4px 9px;border-radius:980px;
    background:var(--hair2);color:var(--muted);white-space:nowrap;}}
  /* Breed leads and is tinted — the one fact most adopters scan for. */
  .pill.breed{{background:var(--accent-soft);color:var(--accent);font-weight:600;}}
  /* A different route to the same dog, so it borrows the warning tint rather
     than the brand one: read this before you get attached, it isn't a feature. */
  .pill.program{{background:var(--warn-soft);color:var(--warn);font-weight:600;}}


  .empty{{text-align:center;padding:90px 20px;}}
  .empty-emoji{{font-size:52px;margin-bottom:12px;}}
  .empty h2{{font-size:24px;margin:0 0 8px;letter-spacing:-.02em;}}
  .empty p{{color:var(--muted);margin:0;}}

  /* ---------- subscribe ---------- */
  .sub-sec{{background:var(--surface);border-radius:28px;padding:56px 32px;
    margin:56px 0 0;text-align:center;box-shadow:var(--shadow);}}
  .sub-sec h2{{font-size:clamp(26px,3.6vw,36px);letter-spacing:-.022em;margin:0 0 10px;}}
  /* Wide enough for the promise to land in two lines, balanced so it never
     drops a one-word orphan onto a third. */
  .sub-sec p{{color:var(--muted);font-size:16.5px;margin:0 auto 26px;max-width:470px;
    text-wrap:balance;}}
  .sub-form{{display:flex;gap:9px;max-width:430px;margin:0 auto;flex-wrap:wrap;}}
  .sub-form input{{flex:1;min-width:200px;padding:14px 17px;font-size:16px;border-radius:13px;
    border:1px solid var(--hair);background:var(--bg);color:var(--text);font-family:inherit;}}
  .sub-form input:focus{{outline:2px solid var(--accent);outline-offset:-1px;
    border-color:transparent;}}
  .sub-form button{{all:unset;box-sizing:border-box;cursor:pointer;
    background:var(--accent);color:#fff;font-weight:600;font-size:16px;
    padding:14px 26px;border-radius:13px;transition:opacity .2s;
    text-align:center;}}
  .sub-form button:hover{{opacity:.88;}}
  /* One row of city checkboxes under the field. Deliberately plain — this is a
     two-item choice, not a form, and anything more elaborate would outweigh the
     email field above it. */
  .sub-cities{{border:0;margin:12px 0 0;padding:0;display:flex;gap:8px;
    justify-content:center;flex-wrap:wrap;}}
  .sub-city{{display:inline-flex;align-items:center;gap:7px;cursor:pointer;
    font-size:14px;font-weight:600;padding:7px 14px;border-radius:980px;
    border:1px solid var(--hair);background:var(--surface);
    transition:border-color .18s,background .18s;}}
  .sub-city:hover{{border-color:var(--muted);}}
  .sub-city:has(input:checked){{border-color:var(--accent);
    background:var(--accent-soft);}}
  .sub-city input{{accent-color:var(--accent);width:15px;height:15px;
    margin:0;cursor:pointer;}}
  /* Visually hidden, still read out: the checkboxes need a group label. */
  .vh{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
    overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}}
  .sub-note{{font-size:13px;color:var(--muted);margin-top:14px;}}
  .sub-note a{{color:var(--accent);}}
  .sub-ok{{color:var(--accent);font-weight:600;margin-top:14px;font-size:15px;}}

  /* ---------- saved filter bar ---------- */
  .filter-bar{{display:flex;align-items:center;justify-content:space-between;
    gap:14px;background:var(--accent-soft);border:1px solid var(--accent);
    border-radius:14px;padding:12px 16px;margin:26px 0 0;}}
  .filter-bar[hidden]{{display:none;}}
  .fb-label{{display:flex;align-items:center;gap:9px;font-size:14.5px;
    font-weight:600;color:var(--accent);}}
  .fb-hrt{{width:16px;height:16px;fill:var(--accent);stroke:var(--accent);
    stroke-width:1.8;}}
  .fb-clear{{all:unset;box-sizing:border-box;cursor:pointer;font-size:13.5px;
    font-weight:600;color:var(--accent);padding:6px 12px;border-radius:980px;
    background:var(--surface);white-space:nowrap;}}
  .fb-clear:hover{{opacity:.8;}}
  /* The right-hand group: the URL, then the button. min-width:0 so the code
     element can actually shrink — a flex child will not ellipsis without it. */
  .fb-right{{display:flex;align-items:center;gap:12px;min-width:0;
    margin-left:auto;}}
  /* The link, shown rather than described. Monospace and muted: it is evidence,
     not a control, and it should not compete with the button beside it.
     Truncates from the right, host first. `direction:rtl` was tried to keep the
     tail visible and is wrong for a URL: it reorders the string at the bidi
     level rather than scrolling it, so "luvd.com/?saved=a,b" rendered as
     "…,b/luvd.com" — a URL nobody could verify, which defeats showing it. */
  .fb-url{{font:500 12.5px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;
    color:var(--accent);opacity:.72;background:rgba(255,255,255,.55);
    border-radius:8px;padding:5px 9px;max-width:340px;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
  .fb-url[hidden]{{display:none;}}
  /* White, matching the bar's other pill, with a drawn icon rather than 🔗 —
     that emoji renders as a different object on every platform and read as a
     smudge at this size. It is the only button in the bar now, so it does not
     need to shout to be found. */
  .fb-copy{{padding:7px 14px;display:inline-flex;align-items:center;gap:6px;
    flex:0 0 auto;box-shadow:0 1px 2px rgba(0,0,0,.07);}}
  .fb-copy:hover{{opacity:.85;}}
  .fb-copy svg{{width:14px;height:14px;flex:0 0 auto;fill:none;
    stroke:var(--accent);stroke-width:2;stroke-linecap:round;
    stroke-linejoin:round;}}
  .fb-copy[hidden]{{display:none;}}
  @media (max-width:680px){{
    /* No room for a URL beside a button on a phone, and the button is the part
       that does something. The link is still what gets shared — it is just not
       recited first. */
    .fb-url{{display:none;}}
    /* 44px, because this is now the only thing to press in this bar and it was
       coming out at 31. The label stays 13.5px; the height comes from padding,
       so the pill grows without the type shouting. */
    .fb-copy{{min-height:44px;padding:0 16px;}}
    .filter-bar{{padding:10px 12px;}}
  }}

  /* ---------- filter pills ---------- */
  /* One quiet row above the dogs, centred under the centred hero. No card, no
     heading, no sidebar: at ~220 dogs these are for narrowing a scroll, not for
     running a search. */
  .fbar{{margin:30px 0 -6px;}}
  /* These set display (via all:unset or flex), which would otherwise beat the
     UA rule behind the [hidden] attribute. */
  .fpill-t[hidden],.fb-clear[hidden]{{display:none;}}
  /* The pills own this row alone. Sort used to share it behind a hairline
     divider; it now sits on the results header below, where being a row apart
     separates it more plainly than the divider ever did. */
  .fbar-pills{{display:flex;align-items:center;justify-content:center;gap:8px;
    flex-wrap:wrap;}}
  /* An open menu is only above the grid for as long as nothing between it and
     the page root is a stacking context — and this row has now twice become one
     by accident. First the scroll fade's mask (paintPillFade stands it down for
     exactly this reason), then -webkit-overflow-scrolling:touch on iOS, which
     put every filter menu behind the dogs in mobile Safari. A menu's z-index:48
     is measured inside whichever context it lands in, so each time the row grew
     one, 48 stopped meaning "above the cards" and started meaning "above the
     other things in this row".
     So the row states its own order instead of relying on not having one: while
     a menu is open it *is* a stacking context, deliberately, and one that sits
     above the grid. 49 is one below nav's 50 — a menu should cover the dogs, not
     the bar you close it from. Toggled by paintPillFade(), which already knows
     when a menu is open. Anything added here that draws outside the row's box
     now stays correct without a third special case. */
  /* The layer that holds whichever menu is open. z-index 49 keeps it over the
     grid and under the sticky nav at 50 — a menu should cover the dogs, not the
     bar you close it from. inset:0 makes it exactly the viewport, so a menu's
     own left/right/top resolve as they did when it was fixed to the viewport
     directly. pointer-events pass through everywhere except the menu itself, so
     an empty layer cannot swallow a tap on the page beneath it. */
  .fmenu-layer{{position:fixed;inset:0;z-index:49;pointer-events:none;}}
  .fmenu-layer > .fmenu{{pointer-events:auto;}}
  /* The results header: count left, sort right, sitting on top of the grid.
     The count is always on the page, never toggled. It used to appear only once
     a filter was applied, which pushed the whole grid down at the exact moment
     you clicked — so the count arrived by shoving the thing you were looking at.
     Permanent means filtering just changes the number in place. Left, flush with
     the first card, so it reads as a heading for the grid, which is what it is
     now that the day headings are gone. */
  /* No reserved height here any more. This row used to carry a Clear link that
     came and went with the filter, so it needed a floor to stop the grid
     dropping 23px the moment you clicked a pill. Clear is gone and both things
     left — the count and the sort — are permanent and fixed-width, so the row
     is a constant height by construction. Its height is the sort pill's 44px
     touch target; see .fpill.fsort > button. */
  /* The negative bottom margin is doing optical work, not layout work. The row
     is a fixed 44px and the count is centred in it, so the type change from
     23px to 19px left ~3px of extra air between the count's ink and the first
     card without changing a single box. These margins put the ink back where it
     was: 24px below the pills, 15px above the cards. Measure from the numeral,
     not from the row, if you retune this. */
  .fbar-meta{{display:flex;align-items:center;justify-content:flex-start;
    gap:8px;margin:14px 0 -19px;}}
  /* 19px on desktop, 17px on phones — the phone step-down and its reason are in
     the mobile block. Desktop 19px is a step down from the retired day heading's
     23px: the count has that heading's job now the grid is flat, but at 23px it
     and the sort at the other end of the row read as two unrelated things rather
     than one header. Matching the filter pills' 15px control scale was tried and
     rejected: this is the page's only statement of how many dogs there are, and
     at control size it stops reading as a heading and becomes metadata. Numeral
     at full contrast, unit greyed: the same pairing the date and its "N dogs"
     had. */
  .fbar-n{{font-size:19px;font-weight:700;letter-spacing:-.022em;
    color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums;}}
  .fbar-n b{{font-weight:700;color:var(--text);}}
  /* Hard right, opposite the count: the heading states what you're looking at,
     the control at the other end changes its order. */
  .fbar-meta .fpill.fsort{{margin-left:auto;}}
  .fpill{{position:relative;}}
  /* 15px is the control scale, shared with the sort at the other end of the
     header below. One size for everything you can click up here, so the two
     rows read as one set of controls rather than two unrelated toolbars. The
     sort stays the quieter of the two on weight, colour and chrome instead of
     on size — see .fpill.fsort. */
  .fpill > button,.fpill-t{{all:unset;box-sizing:border-box;cursor:pointer;
    display:inline-flex;align-items:center;gap:5px;font-size:15px;
    font-weight:600;color:var(--text);background:var(--surface);
    border:1px solid var(--hair);border-radius:980px;padding:8px 14px;
    white-space:nowrap;transition:border-color .18s,background .18s,color .18s;}}
  .fpill > button:hover,.fpill-t:hover{{border-color:var(--muted);}}
  /* Drawn inside the pill, not around it. An offset outline was being sheared
     off by .fbar-pills' old overflow-x scroll container on phones, and on a pill
     already filled solid accent a red ring one gap away read as a broken double
     border. Inset can't be clipped; white reads as focus on a filled pill. */
  .fpill > button:focus-visible,.fpill-t:focus-visible{{
    outline:2px solid var(--accent);outline-offset:-2px;}}
  .fpill.on > button:focus-visible,.fpill-t.on:focus-visible{{outline-color:#fff;}}
  /* Active reads as filled brand, so the row tells you at a glance how narrow
     the list you're looking at is. */
  .fpill.on > button,.fpill-t.on{{background:var(--accent);border-color:var(--accent);
    color:#fff;}}
  .fpill.on .cv{{color:rgba(255,255,255,.75);}}
  .fpill-t b{{font-weight:700;opacity:.6;font-variant-numeric:tabular-nums;}}
  .fpill-t.on b{{opacity:.8;}}
  /* No size of its own: the em ratio on .cv already scales it with each pill,
     and the flex button centres it without a vertical-align nudge. */
  .fpill.open .cv{{transform:rotate(180deg);}}
  /* Sort is not a filter, so it deliberately looks unlike one: no pill, and a
     "Sort by" label that names the control instead of mirroring its value the
     way the filter pills do. It never fills either — something is always sorting, so a
     filled control here would claim you'd narrowed the list, and the pill row's
     filled state is how the page reports exactly that. The hairline divider it
     used to sit behind is gone with the move to its own row: a row apart is
     already a stronger separation than a 1px rule. */
  /* 17px, one value at every width — the only thing in the filter bar that
     doesn't step across the breakpoint, because it is a control and not type in
     a ladder. It spent a while at the count's 19px, on the theory that the two
     ends of the row should agree on size, and that made the least-used control
     on the page the loudest thing in its own row and louder than the filter
     pills above it, which is backwards. 17px still sits above the pills'
     control scale, so it reads as belonging to the heading row rather than to
     them, without shouting; it keeps the count's tracking for the same reason.
     Lighter than the count on everything else: weight 600 against 700, --muted
     against --text, no fill and no border. It reorders the list, it never
     narrows it, so it must never look like something you've switched on.
     min-height, not padding: this is the row's only touch target and the thing
     that sets the results header's height, so the row is 44px because this
     button is. The line-height is holding that up. At the body's 1.47 a 19px
     label measured 27.9px, which with padding and border came to 45.9 and took
     the height off min-height and onto the type — the row grew 2px and the
     floor stopped meaning anything. 1.2 keeps the floor in charge, with more
     room to spare at 17px than there ever was at 19. Nothing is clipped: the
     button centres its label in the full 44. */
  .fpill.fsort > button{{background:none;border-color:transparent;padding:8px;
    min-height:44px;font-size:17px;line-height:1.2;font-weight:600;
    letter-spacing:-.022em;color:var(--muted);}}
  .fpill.fsort > button:hover{{border-color:transparent;color:var(--text);}}
  /* Its own ratio, not the shared .72em, and deliberately not in proportion to
     its label. The arrow is the least informative mark in the row — it says
     "this opens", which you already know from everything else about the
     control — so it is the first thing that should give up size, and it should
     not swing every time the sort's type is retuned. .66em of 17px is 11.2px,
     which is a step down from the 13.7px it drew at the old 19px and only just
     above the pills' 10.8px: a hair larger, because the sort's label is larger,
     without the two reading as different icons. Height is two thirds of width,
     the viewBox's own ratio. */
  .fpill.fsort .cv{{width:.66em;height:.44em;}}
  /* Right-anchored: it's the last control in the row, so a left-anchored menu
     would hang off the edge on narrow screens. */
  .fpill.fsort .fmenu{{left:auto;right:0;}}
  .fmenu{{position:absolute;top:calc(100% + 8px);left:0;z-index:48;
    background:var(--surface);border:1px solid var(--hair);border-radius:14px;
    box-shadow:0 4px 12px rgba(0,0,0,.14),0 18px 48px rgba(0,0,0,.18);
    padding:6px;min-width:200px;max-height:min(60vh,420px);overflow-y:auto;
    display:flex;flex-direction:column;gap:1px;opacity:0;
    transform:translateY(-6px);
    transition:opacity .16s ease,transform .2s cubic-bezier(.2,.8,.25,1);}}
  :root[data-theme="dark"] .fmenu{{
    box-shadow:0 4px 12px rgba(0,0,0,.5),0 22px 60px rgba(0,0,0,.6);}}
  .fmenu[hidden]{{display:none;}}
  /* On the menu, not on `.fpill.open .fmenu`: an open menu is moved out of its
     pill into #fmenu-layer, so a descendant selector stops matching exactly when
     it is needed. */
  .fmenu.open{{opacity:1;transform:none;}}
  .fmenu button{{all:unset;cursor:pointer;font-size:14.5px;font-weight:500;
    padding:9px 12px;border-radius:9px;text-align:left;color:var(--text);
    display:flex;justify-content:space-between;align-items:center;gap:16px;}}
  /* One line per option, always. A wrapped row makes the menu look broken and
     the count float away from the label it belongs to. */
  .fmenu button > span{{white-space:nowrap;}}
  /* The label never wraps: a two-line row next to a right-aligned count reads
     as two options. The menu widens to the longest label instead — "Bulldog &
     mastiff" and "Mixed / unknown" are the widest we have. */
  .fmenu button > span{{white-space:nowrap;}}
  /* The pound range beside a size name. An <i> for brevity in the markup, so
     font-style has to be reset — it is a quieter register, not an emphasis.
     --muted against the row's --text is the same pairing the card facts and the
     dog count use for "the number under the thing it describes". */
  .fmenu .opt-d{{font-style:normal;font-weight:500;color:var(--muted);
    margin-left:7px;}}
  /* On the selected row the name turns accent; the range follows it rather than
     staying grey, or it reads as disabled next to a chosen label. */
  .fmenu button[aria-selected="true"] .opt-d{{color:var(--accent);opacity:.75;}}
  .fmenu button:hover{{background:var(--hair2);}}
  .fmenu button[aria-selected="true"]{{color:var(--accent);font-weight:700;}}
  /* Counted and dimmed rather than removed: seeing "Husky 0" is information,
     and it stops the menu reshuffling under the cursor as filters change. */
  .fmenu button:disabled{{cursor:default;opacity:.34;}}
  .fmenu button:disabled:hover{{background:transparent;}}
  .fmenu button b{{font-weight:600;color:var(--muted);font-size:13px;
    font-variant-numeric:tabular-nums;}}
  .fmenu button[aria-selected="true"] b{{color:var(--accent);}}

  /* ---------- saved empty state ---------- */
  .saved-empty{{text-align:center;padding:70px 20px 40px;max-width:420px;
    margin:0 auto;}}
  .saved-empty[hidden]{{display:none;}}
  .se-art svg{{width:60px;height:60px;fill:none;stroke:var(--accent);
    stroke-width:1.6;opacity:.5;animation:sePulse 2.6s ease-in-out infinite;}}
  @keyframes sePulse{{
    0%,100%{{transform:scale(1);opacity:.45;}}
    50%{{transform:scale(1.08);opacity:.75;}}
  }}
  .saved-empty h2{{font-size:24px;letter-spacing:-.02em;margin:16px 0 8px;}}
  .saved-empty p{{color:var(--muted);font-size:15px;margin:0 0 22px;
    line-height:1.55;}}
  .saved-empty .cta{{display:inline-block;width:auto;padding:12px 22px;
    margin-top:0;cursor:pointer;}}
  @media (prefers-reduced-motion:reduce){{ .se-art svg{{animation:none;}} }}

  /* ---------- faq ---------- */
  .faq{{max-width:720px;margin:56px auto 0;padding-top:40px;
    border-top:1px solid var(--hair2);}}
  .faq h2{{font-size:24px;letter-spacing:-.022em;margin:0 0 18px;}}
  .faq details{{border-bottom:1px solid var(--hair2);padding:14px 0;}}
  .faq summary{{cursor:pointer;font-size:16px;font-weight:600;list-style:none;
    display:flex;justify-content:space-between;align-items:center;gap:12px;}}
  .faq summary::-webkit-details-marker{{display:none;}}
  .faq summary::after{{content:'+';color:var(--muted);font-weight:400;
    font-size:20px;line-height:1;}}
  .faq details[open] summary::after{{content:'–';}}
  .faq p{{font-size:15px;line-height:1.6;color:var(--muted);margin:10px 0 0;}}
  /* The rescue names in the coverage answer link to their pages; without this
     they'd fall back to the UA's default blue. */
  .faq p a{{color:var(--text);text-decoration:underline;
    text-decoration-color:var(--hair);text-underline-offset:2px;
    white-space:nowrap;}}
  .faq p a:hover{{color:var(--accent);text-decoration-color:var(--accent);}}

  /* ---------- shared list bar ---------- */
  /* Sits above the grid rather than in the nav: it is about this visit, not a
     permanent control, and it has to be able to say two lines without pushing
     the nav around. Surface card on the page background, so it reads as a note
     laid on the page rather than a piece of chrome. */
  .shared-bar{{margin:22px 0 -4px;}}
  .shared-bar[hidden]{{display:none;}}
  .sb-in{{display:flex;align-items:center;gap:16px;background:var(--surface);
    border:1px solid var(--hair);border-radius:18px;padding:16px 18px;
    box-shadow:var(--shadow);}}
  .sb-text{{min-width:0;flex:1 1 auto;}}
  .sb-h{{font-size:17px;font-weight:700;letter-spacing:-.015em;color:var(--text);}}
  /* The honest line: how many of the shared dogs are still listed, and how many
     are not. A link outlives the dogs on it, so this is the difference between a
     stale link degrading into information and degrading into a blank page. */
  .sb-sub{{font-size:14px;color:var(--muted);margin-top:3px;}}
  /* .cta is the page's full-width block button — display:block, width:100%,
     margin-top:24px — which inside a flex row crushes the text beside it into a
     one-word column. Overridden rather than a new class so the colour, radius,
     focus ring and hover stay in one place. */
  /* `.sb-in .sb-save`, not `.sb-save`: .cta is declared further down the sheet,
     so at equal specificity it wins on source order and the button stays
     display:block/width:100%, crushing the text beside it into a one-word
     column. Two classes beats one regardless of order. */
  .sb-in .sb-save{{flex:0 0 auto;width:auto;display:inline-block;margin-top:0;
    padding:12px 20px;font-size:15.5px;white-space:nowrap;}}
  @media (max-width:680px){{
    .shared-bar{{margin:18px 0 -2px;}}
    /* Stacked on a phone: side by side, the button either wrapped to two lines
       or squeezed the count into an ellipsis. */
    .sb-in{{flex-direction:column;align-items:stretch;gap:13px;padding:15px 16px;}}
    /* min-height, not more padding: 12px top and bottom against a 19px line box
       came out at 43px, one short of the touch floor, and nudging the padding to
       fix a single pixel is the kind of number nobody can explain later. */
    .sb-in .sb-save{{width:100%;min-height:44px;}}
  }}

  /* ---------- footer ---------- */
  footer{{text-align:center;padding:52px 0 72px;color:var(--muted);font-size:13.5px;}}
  footer .date{{font-weight:600;color:var(--text);font-size:15px;}}
  footer a{{color:var(--muted);}}
  /* Terms/Privacy open modals, so they're buttons dressed as the Contact link. */
  .foot-link{{background:none;border:0;padding:0;margin:0;font:inherit;
    color:var(--muted);cursor:pointer;text-decoration:underline;
    text-underline-offset:2px;}}
  .foot-link:hover{{color:var(--text);}}
  .foot-rescues{{margin:20px auto 18px;max-width:600px;line-height:1.95;}}
  .foot-hd{{display:block;font-size:11px;font-weight:700;letter-spacing:.09em;
    text-transform:uppercase;opacity:.7;margin-bottom:1px;}}
  /* A rescue's name is one unit — don't break "Sean Casey Animal Rescue"
     across two lines. */
  .foot-rescues a{{white-space:nowrap;}}
  .foot-cities{{margin:0 auto 14px;max-width:600px;line-height:1.9;
    font-weight:600;}}
  .foot-cities a{{white-space:nowrap;}}
  .foot-cities a:hover{{color:var(--text);}}
  /* The city you are already on is named but not linked — a link to the page
     you are on is a link a crawler follows for nothing. */
  .foot-here{{white-space:nowrap;opacity:.55;}}
  .foot-rescues a:hover{{color:var(--text);}}
  .foot-all{{font-weight:600;}}

  /* ---------- modal shell ---------- */
  .scrim{{position:fixed;inset:0;background:rgba(0,0,0,.42);
    backdrop-filter:saturate(180%) blur(24px);-webkit-backdrop-filter:saturate(180%) blur(24px);
    display:none;align-items:center;justify-content:center;padding:24px;z-index:100;
    opacity:0;transition:opacity .28s ease;}}
  .scrim.on{{display:flex;}} .scrim.vis{{opacity:1;}}
  .modal{{position:relative;background:var(--surface);border-radius:26px;width:min(880px,100%);
    max-height:min(88vh,900px);overflow:visible;box-shadow:var(--shadow-lg);
    display:flex;flex-direction:column;
    transform:scale(.96) translateY(12px);
    transition:transform .34s cubic-bezier(.2,.9,.25,1);}}
  /* The contact button is the whole point of the page, so it never scrolls
     out of reach — the body scrolls beneath a pinned action bar. */
  .m-scroll{{overflow-y:auto;-webkit-overflow-scrolling:touch;flex:1 1 auto;
    border-radius:26px 26px 0 0;
    /* The default desktop scrollbar is a chunky grey slab against a rounded
       modal. Slim, translucent, and only as present as it needs to be. */
    scrollbar-width:thin;
    scrollbar-color:var(--hair) transparent;
    overscroll-behavior:contain;}}
  .m-scroll::-webkit-scrollbar{{width:7px;}}
  .m-scroll::-webkit-scrollbar-track{{background:transparent;}}
  .m-scroll::-webkit-scrollbar-thumb{{background:var(--hair);
    border-radius:980px;border:2px solid transparent;background-clip:content-box;}}
  .m-scroll::-webkit-scrollbar-thumb:hover{{background:var(--muted);
    border:2px solid transparent;background-clip:content-box;}}
  /* No footer (about, share, contact) means the scroller owns all four. */
  .modal:not(:has(.m-foot)) .m-scroll{{border-radius:26px;}}
  .m-foot{{flex:0 0 auto;padding:14px 28px 18px;border-top:1px solid var(--hair);
    background:var(--surface);border-radius:0 0 26px 26px;}}
  .m-foot .cta{{margin-top:0;}}
  .m-foot .cta-sub{{margin-top:9px;}}
  .foot-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .act-note{{font-size:12.5px;color:var(--muted);text-align:center;
    margin-bottom:10px;}}
  /* Program terms are several sentences of real commitment, so they get a box
     and a left edge to read down — centred prose that long is a wall. */
  .act-note.prog{{text-align:left;line-height:1.55;background:var(--hair2);
    border-radius:12px;padding:10px 12px;}}
  .act-note.prog b{{color:var(--warn);}}
  /* .cta is declared later in the sheet, so match specificity to win. */
  .cta.cta2{{background:var(--hair2);color:var(--text);
    border:1px solid var(--hair);cursor:pointer;}}
  .cta.cta2:hover{{opacity:1;background:var(--hair);}}
  .cta.cta2:disabled{{opacity:.5;cursor:default;}}
  /* iOS-style share glyph: tray with an arrow lifting out of it. */
  .shr-ic{{width:17px;height:17px;margin-right:8px;vertical-align:-3px;
    fill:none;stroke:currentColor;stroke-width:1.9;
    stroke-linecap:round;stroke-linejoin:round;}}
  .cta.cta2{{display:inline-flex;align-items:center;justify-content:center;}}

  /* ---------- contact sheet ---------- */
  .contact{{padding:26px 24px 24px;}}
  .ct-lead{{font-size:14.5px;color:var(--muted);margin:10px 0 16px;
    line-height:1.5;}}
  .ct-addr{{font-size:14px;background:var(--hair2);border-radius:10px;
    padding:11px 13px;text-align:center;margin-bottom:14px;user-select:all;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}}
  .ct-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;
    margin-bottom:10px;}}
  .ct-btns .cta{{margin-top:0;font-size:15px;padding:13px;}}
  .ct-prev{{margin-top:8px;}}
  .ct-prev summary{{cursor:pointer;font-size:13px;color:var(--muted);}}
  .ct-prev pre{{white-space:pre-wrap;font-size:12.5px;color:var(--muted);
    background:var(--hair2);border-radius:10px;padding:12px;margin-top:9px;
    max-height:190px;overflow:auto;font-family:inherit;line-height:1.5;}}

  /* ---------- share sheet ---------- */
  .share{{padding:26px 24px 24px;}}
  .story-wrap{{display:flex;justify-content:center;margin:14px 0 16px;}}
  .story-img,.story-ph{{width:min(232px,58vw);aspect-ratio:9/16;border-radius:16px;
    background:var(--hair2);box-shadow:var(--shadow);display:grid;place-items:center;
    color:var(--muted);font-size:13px;object-fit:cover;}}
  .share-url{{font-size:12px;color:var(--muted);background:var(--hair2);
    border-radius:10px;padding:10px 12px;word-break:break-all;text-align:center;
    margin-bottom:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}}
  .share-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .share-btns .cta{{margin-top:0;}}
  .scrim.vis .modal{{transform:none;}}
  /* Photo column spans both right-hand panels and stretches to match their
     combined height, so the photo is tall enough to actually see the dog. */
  /* The RIGHT column sets the height; the photo fills whatever is left after
     the thumbnails. So hero + thumbs always equals the panels beside it, and
     a dog with no thumbnails simply gets a taller photo — the block never
     changes size. Height comes from the grid, never from the image, so a
     portrait photo can't stretch the modal. */
  .m-media{{grid-row:1 / span 2;display:flex;flex-direction:column;gap:9px;
    min-width:0;min-height:0;}}
  .m-hero{{position:relative;flex:1 1 auto;min-height:0;
    background:var(--hair);border-radius:16px;overflow:hidden;}}
  /* Photo and clip are the same thing in the same box: both fill the hero and
     centre-crop, and neither contributes height. Out of flow for both, because
     in flow a 720x1280 portrait clip grows the whole top band the moment you
     tap it — and leaving only ONE of them in flow is worse, because then the
     band changes size depending on which you are looking at (it did: 548px on a
     photo, 528px on a clip). The hero's height comes from the layout around it
     either way. */
  .m-hero img,.m-hero video{{position:absolute;inset:0;width:100%;height:100%;
    object-fit:cover;object-position:center;display:block;}}
  .m-hero video{{background:#000;}}
  .m-close{{position:absolute;top:-12px;right:-12px;width:36px;height:36px;border:none;
    border-radius:50%;cursor:pointer;font-size:17px;line-height:1;
    background:rgba(28,28,30,.72);color:#fff;
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    display:grid;place-items:center;z-index:20;
    box-shadow:0 3px 12px rgba(0,0,0,.3);
    transition:background .2s,transform .2s;}}
  .m-close:active{{transform:scale(.92);}}
  .m-close:hover{{background:rgba(0,0,0,.75);}}
  .thumbs{{display:flex;gap:8px;overflow-x:auto;flex:0 0 auto;
    scrollbar-width:none;}}
  .m-media:has(.thumbs) .m-hero{{min-height:0;}}
  .thumbs::-webkit-scrollbar{{height:0;}}
  /* Videos ride in the same strip as the photos. The thumbnail IS a <video>
     with preload="metadata" and a #t=0.1 fragment, so the browser paints the
     clip's own first frame — a real poster with no server-side frame grab and
     no extra dependency. The rules below therefore have to apply to a <video>
     and to the wrapper that carries the play badge, not just to <img>. */
  .thumbs img,.thumbs .th-v{{width:60px;height:60px;object-fit:cover;
    object-position:center;border-radius:10px;cursor:pointer;flex:0 0 auto;
    opacity:.5;transition:opacity .2s;border:2px solid transparent;}}
  .thumbs .th-v{{position:relative;display:block;overflow:hidden;padding:0;
    background:var(--hair);}}
  .thumbs .th-v video{{width:100%;height:100%;object-fit:cover;display:block;
    pointer-events:none;}}
  .thumbs .th-v:hover,.thumbs .th-v.sel{{opacity:1;border-color:var(--accent);}}
  /* The badge is what says "this one moves" before anything has loaded. */
  .th-play{{position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;pointer-events:none;}}
  .th-play::after{{content:"";width:0;height:0;margin-left:2px;
    border-left:11px solid #fff;border-top:7px solid transparent;
    border-bottom:7px solid transparent;
    filter:drop-shadow(0 1px 3px rgba(0,0,0,.55));}}
  .m-hero video[hidden],.m-hero img[hidden]{{display:none;}}
  .thumbs img{{width:60px;height:60px;object-fit:cover;object-position:center;
    border-radius:10px;cursor:pointer;
    flex:0 0 auto;opacity:.5;transition:opacity .2s;border:2px solid transparent;}}
  .thumbs img:hover,.thumbs img.sel{{opacity:1;border-color:var(--accent);}}
  .m-body{{padding:18px 22px 28px;}}
  /* No photo: content starts at the top, with room for the close button. */
  .m-scroll.no-hero .m-body{{padding-top:30px;}}
  .m-scroll.no-hero .m-close{{background:var(--hair);color:var(--text);}}
  .m-name-row{{display:flex;align-items:center;justify-content:space-between;
    gap:14px;margin-bottom:4px;}}
  .m-name{{font-size:clamp(40px,4.4vw,58px);font-weight:800;letter-spacing:-.035em;
    margin:0;line-height:1;min-width:0;overflow-wrap:anywhere;}}
  /* The rescue reads as attribution under the name, not as another pill.
     When we know the rescue's site it's a link; otherwise plain text. */
  .m-rescue{{font-size:15px;font-weight:600;color:var(--muted);
    margin:0 0 15px;overflow-wrap:anywhere;align-self:flex-start;
    text-decoration:none;transition:color .15s ease;}}
  a.m-rescue:hover{{color:var(--accent);text-decoration:underline;}}
  /* Same control as the cards, sized for the detail view and on a surface
     rather than over a photo. */
  .m-save{{position:static;right:auto;top:auto;flex:0 0 auto;width:44px;height:44px;
    background:var(--hair);}}
  .m-save:hover{{background:var(--hair2);}}
  .m-save .hrt{{width:23px;height:23px;stroke:var(--muted);}}
  .m-save:hover .hrt{{stroke:var(--text);}}
  .m-save.on .hrt{{fill:var(--accent);stroke:var(--accent);}}
  /* Identity on the left, ratings on the right. The left column holds the name
     and chips — content every dog has — so this never collapses to an empty
     box the way a traits-only column did. The bars never needed full width. */
  .topgrid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;
    align-items:stretch;margin-bottom:14px;}}
  /* Both columns share the same grey card so the top of the modal reads as one
     balanced band instead of a floating name next to a panel. */
  .idcol{{min-width:0;background:var(--hair2);border-radius:18px;
    padding:20px 20px 18px;display:flex;flex-direction:column;
    justify-content:center;}}
  .topgrid .scores{{margin:0;}}
  .chips{{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:0;}}
  .chip{{font-size:12.5px;padding:6px 12px;border-radius:980px;background:var(--hair2);
    color:var(--text);font-weight:500;}}
  .chip.wait{{background:var(--warn-soft);color:var(--warn);font-weight:600;}}
  .chip.program{{background:var(--warn-soft);color:var(--warn);font-weight:600;}}
  .m-views{{left:12px;top:12px;}}
  .chip[hidden]{{display:none;}}

  /* Benefits and challenges, spelled out rather than colour-coded confetti. */

  .tl-hd{{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
    color:var(--muted);margin-bottom:13px;}}
  .tlists ul{{list-style:none;margin:0;padding:0;display:grid;
    grid-template-columns:1fr;gap:9px;}}
  .tlists li{{display:flex;align-items:flex-start;gap:9px;font-size:14.5px;
    line-height:1.4;color:var(--text);min-width:0;}}
  .tl-ic{{flex:0 0 auto;display:grid;place-items:center;width:17px;height:17px;
    border-radius:50%;font-size:10.5px;font-weight:800;font-style:normal;
    color:#fff;line-height:1;margin-top:1px;}}
  .tlists li.good .tl-ic{{background:var(--good);}}
  .tlists li.warn .tl-ic{{background:var(--warn);}}

  /* ---------- score bars ---------- */
  .scores{{background:var(--hair2);border-radius:18px;padding:20px 20px 18px;
    margin-bottom:22px;display:flex;flex-direction:column;}}
  .sc-hd{{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
    color:var(--muted);margin-bottom:18px;}}
  /* Spread the three bars through whatever height the panel ends up with,
     so they never bunch at the top of a stretched card. */
  .sc{{margin-bottom:24px;}}
  .sc:last-of-type{{margin-bottom:0;}}
  .sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:9px;}}
  .sc-ic{{font-size:15px;width:20px;text-align:center;}}
  .sc-lb{{font-size:14px;font-weight:600;flex:1;}}
  /* A marker on a named axis, not a fill. The fill was unreadable, and not for
     want of a label: its direction meant three different things down the four
     rows. Energy is neutral, a full Apartment fit is good, a full Experience
     needed is *harder*, a full Home alone is good again. So a long bar was
     "better" on two rows and "more demanding" on a third, with no rule to learn
     — and with both ends unlabelled there was nothing to say what 20% was 20%
     of. A pin has no direction to misread: it says this dog is here, between
     these two things, and the two things are now written underneath.
     It also fixes the middle. At `v*20` a score of 3 filled 60%, which reads as
     "quite a lot of"; centred, 3 sits dead centre and looks like the middle. */
  .sc-track{{position:relative;height:6px;border-radius:980px;
    background:var(--hair);margin:0 11px;}}
  /* The heart from the save button. Same mark doing a second job, and it makes
     the row feel like part of the page rather than a chart dropped into it. */
  .sc-pin{{position:absolute;top:50%;width:22px;height:22px;
    transform:translate(-50%,-50%) scale(.2);opacity:0;
    transition:transform .5s cubic-bezier(.34,1.4,.64,1),opacity .28s ease;
    filter:drop-shadow(0 1px 2px rgba(0,0,0,.22));}}
  /* The wordmark's heart, outline and all: accent fill inside a white edge.
     paint-order:stroke puts the stroke behind the fill so it reads as an outline
     around the shape rather than a line drawn through it — without that, a 3px
     stroke eats 1.5px of the heart from every side and the shape thins out. */
  .sc-pin svg{{width:100%;height:100%;display:block;fill:var(--accent);
    stroke:#fff;stroke-width:3.8;paint-order:stroke;
    stroke-linejoin:round;overflow:visible;}}
  /* Grows in when the modal opens, the same beat the fill used to animate on. */
  .sc-pin.in{{transform:translate(-50%,-50%) scale(1);opacity:1;}}
  .sc-ends{{display:flex;justify-content:space-between;gap:10px;
    margin:9px 11px 0;font-size:11.5px;color:var(--muted);line-height:1.3;}}
  /* The end the dog is actually at. Only ever one of the two, and never both:
     a score of 3 leaves them both quiet, which is the honest answer. */
  .sc-ends .on{{color:var(--text);font-weight:600;}}
  .sc-ends span{{max-width:47%;}}

  /* ---------- size + cost ---------- */
  .sizecost{{margin-bottom:22px;background:var(--hair2);border-radius:18px;}}
  .sc-inner{{display:grid;grid-template-columns:1.1fr 1fr;}}
  .sc-inner > .sc-right{{border-left:1px solid var(--hair);
    display:flex;flex-direction:column;}}
  /* Two stacked blocks on the right, divided rather than gapped. */
  .sc-right > * + *{{border-top:1px solid var(--hair);}}
  .sc-right > *{{flex:1;}}
  .sc-block{{padding:18px 20px 18px;display:flex;flex-direction:column;}}
  .sc-block p{{font-size:14.5px;line-height:1.5;color:var(--text);margin:0;}}
  .gw{{height:8px;border-radius:980px;background:var(--hair);overflow:hidden;
    margin-top:14px;}}
  .gw span{{display:block;height:100%;border-radius:980px;
    background:var(--accent);}}
  .gw-l{{display:flex;justify-content:space-between;font-size:11.5px;
    color:var(--muted);margin-top:6px;font-weight:600;}}
  /* Where this dog sits between a chihuahua and a mastiff. */
  .szscale{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;
    margin-top:18px;}}
  .szb{{display:flex;flex-direction:column;gap:6px;}}
  .szb i{{height:7px;border-radius:980px;background:var(--hair);display:block;}}
  .szb em{{font-style:normal;font-size:10.5px;font-weight:600;
    color:var(--muted);letter-spacing:.01em;}}
  .szb.on i{{background:var(--accent);}}
  .szb.on em{{color:var(--accent);}}
  .szb.from i{{background:var(--accent);opacity:.35;}}
  .szcap{{font-size:12.5px;color:var(--muted);margin-top:11px;line-height:1.45;}}
  .cost-big{{font-size:30px;font-weight:800;letter-spacing:-.03em;
    margin-bottom:12px;}}
  .cost-big span{{font-size:14px;font-weight:600;color:var(--muted);
    letter-spacing:0;}}
  .cost-list{{list-style:none;margin:0 0 12px;padding:0;}}
  .cost-list li{{display:flex;justify-content:space-between;font-size:13.5px;
    padding:5px 0;border-bottom:1px solid var(--hair2);color:var(--muted);}}
  .cost-list li:last-child{{border-bottom:0;}}
  .cost-list b{{color:var(--text);font-weight:600;}}
  .cost-note{{font-size:11.5px !important;color:var(--muted) !important;
    line-height:1.45 !important;}}
  @media (max-width:680px){{
    .sc-inner{{grid-template-columns:1fr;}}
    .sc-inner > .sc-right{{border-left:0;border-top:1px solid var(--hair);}}
  }}

  /* ---------- tabs ---------- */
  .tabs{{display:flex;gap:4px;background:var(--hair2);padding:3px;border-radius:11px;
    margin-bottom:16px;}}
  .tab{{all:unset;cursor:pointer;flex:1;text-align:center;font-size:13px;font-weight:600;
    padding:8px 6px;border-radius:9px;color:var(--muted);transition:all .2s;}}
  .tab.on{{background:var(--surface);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.08);}}
  .pane{{display:none;font-size:15px;line-height:1.62;}}
  .pane.on{{display:block;}}
  .pane h4{{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
    color:var(--muted);margin:18px 0 6px;}}
  .pane h4:first-of-type{{margin-top:0;}}
  .pane p{{margin:0;}}
  .pane .bio{{white-space:pre-wrap;}}
  .breed-tag{{display:block;font-size:23px;font-weight:700;letter-spacing:-.02em;
    color:var(--text);margin:2px 0 14px;line-height:1.2;}}
  /* One scannable line per topic: bold = this dog, plain = breed context. */
  .fact{{padding:13px 0;border-bottom:1px solid var(--hair2);}}
  .fact:last-child{{border-bottom:0;padding-bottom:2px;}}
  .fact h4{{margin:0 0 5px;}}
  .fact p{{font-size:14.5px;line-height:1.58;color:var(--text);margin:0;}}
  .fact p b{{font-weight:650;}}

  .cta{{display:block;width:100%;text-align:center;background:var(--accent);color:#fff;
    text-decoration:none;padding:15px;border-radius:14px;font-weight:600;font-size:16.5px;
    transition:opacity .2s;margin-top:24px;
    /* Also used on <button>, which brings a default border, its own font and
       an iOS appearance. Reset all three. */
    border:none;appearance:none;-webkit-appearance:none;
    font-family:inherit;line-height:normal;cursor:pointer;}}
  .cta:focus-visible{{outline:3px solid var(--accent);outline-offset:3px;}}
  .cta:hover{{opacity:.88;}}
  .cta-sub{{text-align:center;font-size:13px;color:var(--muted);margin-top:11px;}}
  .cta-sub a{{color:var(--muted);}}

  /* ---------- similar dogs ---------- */
  .sim{{margin-top:28px;padding-top:22px;border-top:1px solid var(--hair);}}
  .sim-hd{{font-size:23px;font-weight:700;letter-spacing:-.02em;
    color:var(--text);margin-bottom:6px;text-transform:none;}}
  .sim-note{{font-size:13px;color:var(--muted);margin:0 0 14px;line-height:1.5;}}
  .sim-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
  .sim-card{{all:unset;cursor:pointer;min-width:0;
    transition:transform .25s cubic-bezier(.2,.8,.2,1);}}
  .sim-card:hover{{transform:translateY(-4px);}}
  .sim-ph{{width:100%;aspect-ratio:1/1;border-radius:14px;object-fit:cover;display:block;
    background:var(--hair);}}
  @media (max-width:520px){{ .sim-row{{grid-template-columns:repeat(2,1fr);}} }}
  .sim-ph.noph{{display:grid;place-items:center;font-size:34px;opacity:.35;}}
  .sim-nm{{font-size:13.5px;font-weight:600;margin-top:7px;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis;}}
  .sim-rs{{font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;}}
  .sim-why{{font-size:10.5px;color:var(--accent);font-weight:600;margin-top:3px;
    line-height:1.35;}}

  /* ---------- about modal ---------- */
  /* About is the one modal whose content is not wrapped in .m-scroll, so it
     needs to be its own scroller. Without this it was an unstyled div in a
     .modal capped at min(88vh,900px) with overflow:visible — at 950x775 the
     content is 767px against a 682px cap, and the buttons and the line under
     them rendered *outside* the card, over the backdrop.
     Same three properties .m-scroll uses, for the same reason: .modal is
     already a column flex container, and a flex child will not shrink below
     its content unless min-height says it may. This is the base rule, so it
     holds at every width — the sheet rules further down only handle how the
     content sits inside it once it fits. */
  .about{{flex:1 1 auto;min-height:0;overflow-y:auto;}}
  .about-hero{{background:
      radial-gradient(120% 130% at 50% 0%, var(--accent-soft) 0%, transparent 68%);
    padding:52px 32px 34px;display:flex;justify-content:center;}}
  .about-logo{{width:min(66%,300px);height:auto;display:block;
    animation:heroIn .6s cubic-bezier(.34,1.4,.64,1) both;}}
  @keyframes heroIn{{from{{transform:scale(.86) translateY(10px);opacity:0;}}
    to{{transform:none;opacity:1;}}}}
  .about-body{{padding:4px 34px 34px;}}
  .about h2{{font-size:clamp(23px,3.4vw,30px);letter-spacing:-.025em;line-height:1.22;
    margin:0 0 26px;text-align:center;font-weight:700;}}
  .creed{{list-style:none;margin:0 0 28px;padding:0;}}
  .creed li{{display:flex;gap:14px;align-items:flex-start;padding:14px 0;
    border-top:1px solid var(--hair2);font-size:15.5px;line-height:1.55;
    color:var(--muted);}}
  .creed li:last-child{{border-bottom:1px solid var(--hair2);}}
  .creed .num{{flex:0 0 auto;font-size:11.5px;font-weight:800;letter-spacing:.06em;
    color:var(--accent);padding-top:4px;font-variant-numeric:tabular-nums;}}
  .creed b{{color:var(--text);font-weight:650;}}
  /* Get in touch + Share, side by side under the creed. */
  .about-actions{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:24px;}}
  .about-actions .cta{{margin-top:0;}}
  /* ---------- terms / privacy ---------- */
  .legal{{padding:34px 34px 38px;}}
  .legal-h{{font-size:26px;font-weight:800;letter-spacing:-.02em;margin:0 0 4px;}}
  .legal .upd{{font-size:12.5px;color:var(--muted);margin:0 0 18px;}}
  .legal h3{{font-size:15px;font-weight:700;color:var(--text);margin:22px 0 6px;}}
  .legal p{{font-size:14.5px;line-height:1.62;color:var(--muted);margin:0 0 12px;}}
  .legal ul{{margin:0 0 12px;padding-left:20px;}}
  .legal li{{font-size:14.5px;line-height:1.62;color:var(--muted);margin:0 0 8px;}}
  .legal b{{color:var(--text);font-weight:650;}}
  .legal a{{color:var(--accent);}}
  @media (prefers-reduced-motion:reduce){{ .about-logo{{animation:none;}} }}

  /* ---------- subscribe modal ---------- */
  /* Narrower than the dog modal — one field / one message shouldn't sprawl. */
  .modal.narrow{{width:min(460px,100%);}}
  .modal.mid{{width:min(560px,100%);}}
  .sub-modal{{padding:42px 30px 34px;text-align:center;background:
      radial-gradient(120% 110% at 50% 0%, var(--accent-soft) 0%, transparent 62%);}}
  .sub-logo{{width:min(52%,200px);height:auto;display:block;margin:0 auto 22px;}}
  .sub-modal h2{{font-size:26px;letter-spacing:-.022em;margin:0 0 9px;}}
  .sub-modal p{{color:var(--muted);font-size:15px;margin:0 auto 22px;max-width:400px;
    text-wrap:balance;}}
  body.locked{{overflow:hidden;}}

  /* ---------- mobile ---------- */
  @media (max-width:720px){{
    .wrap{{padding:0 16px;}}
    header{{padding:22px 0 4px;}}
    .brand-wrap{{margin-bottom:8px;}}
    /* Two across beats one giant column — more dogs per scroll. */
    .grid{{grid-template-columns:repeat(2,1fr);gap:13px;padding:16px 0 4px;}}
    .card{{border-radius:15px;}}
    .meta{{padding:11px 12px 13px;}}
    .nm-row{{margin:0 0 8px;}}
    .nm{{font-size:19px;}}
    .new-chip{{right:8px;bottom:8px;font-size:8.5px;padding:3px 7px;
      letter-spacing:.07em;}}
    .save{{width:38px;height:38px;right:7px;top:7px;}}
    .hrt{{width:19px;height:19px;}}
    .waiting{{right:8px;bottom:8px;font-size:9.5px;}}
    .pill{{font-size:10.5px;padding:3px 7px;}}
    /* Two pills fit a half-width card; a third gets sliced. */
    .pills .pill:nth-child(3){{display:none;}}
    .views{{font-size:11.5px;padding:5px 9px;left:8px;top:8px;}}
    .sub-sec{{padding:38px 20px;border-radius:22px;margin-top:38px;}}
    .sub-form{{flex-direction:column;}}
    .hero-sub{{flex-direction:column;gap:8px;}}
    .hero-sub button{{text-align:center;padding:13px;}}
    .sub-form input,.sub-form button{{width:100%;}}

    /* Full-screen on phones — a dog's detail view is the whole task, and a
       floating sheet just wastes the smallest screen we have. */
    .scrim{{padding:0;align-items:stretch;}}
    .modal{{width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0;
      transform:translateY(18px) scale(1);}}
    .m-scroll,.m-foot,.modal:not(:has(.m-foot)) .m-scroll{{border-radius:0;}}
    .scrim.compact .modal{{border-radius:22px;}}
    .scrim.compact .m-scroll,
    .scrim.compact .modal:not(:has(.m-foot)) .m-scroll{{border-radius:22px;}}
    .scrim.vis .modal{{transform:none;}}
    /* The close button rides above the hero image, always top-right. */
    .m-close{{position:fixed;top:max(14px,env(safe-area-inset-top));right:14px;
      width:38px;height:38px;font-size:18px;z-index:20;
      background:rgba(0,0,0,.62);color:#fff;}}
    .m-foot{{padding:12px 18px max(14px,env(safe-area-inset-bottom));}}
    .foot-row{{grid-template-columns:1fr;gap:8px;}}
    .share{{padding:22px 18px 20px;}}
    .modal.narrow{{width:100%;}}
    /* The subscribe and contact sheets stay centred cards — one field each. */
    .scrim.compact{{align-items:center;padding:18px;}}
    .scrim.compact .modal{{height:auto;max-height:92vh;border-radius:22px;}}
    .scrim.compact .m-close{{position:absolute;}}
    /* About is a page of reading, so it goes full screen like a dog does. */
    .scrim.compact.sheet{{align-items:stretch;padding:0;}}
    .scrim.compact.sheet .modal{{width:100%;max-width:100%;height:100%;
      max-height:100%;border-radius:0;}}
    .scrim.compact.sheet .m-close{{position:fixed;
      top:max(14px,env(safe-area-inset-top));right:14px;}}
    /* Centring the content leaves space above the hero, which showed the
       modal surface as a white band. Move the gradient onto the container so
       it covers the whole sheet.
       Centred with auto margins rather than justify-content, and scrollable.
       About is the one sheet with no .m-scroll inside it — Terms and Privacy
       both have one — so the sheet itself has to be the scroller. With
       `justify-content:center` and no scroller it fit a 812px phone by three
       pixels and lost 51px off the bottom on a 667px one, with no way to reach
       it: centring overflow pushes it past BOTH ends of the box, and a flex
       container will not let you scroll back to what it pushed off the start.
       Auto margins centre it while it fits and collapse to zero when it does
       not, which is the behaviour centring was reached for in the first
       place. */
    .scrim.compact.sheet .about{{display:flex;flex-direction:column;
      justify-content:flex-start;min-height:100%;overflow-y:auto;
      background:radial-gradient(120% 60% at 50% 0%,
        var(--accent-soft) 0%, transparent 62%);}}
    .scrim.compact.sheet .about-hero{{margin-top:auto;}}
    .scrim.compact.sheet .about-body{{margin-bottom:auto;}}
    .scrim.compact.sheet .about-hero{{background:none;
      padding-top:max(58px,calc(env(safe-area-inset-top) + 46px));}}
    .scrim.compact.sheet .about-body{{padding-bottom:max(28px,
      env(safe-area-inset-bottom));}}
    .topgrid.with-photo{{grid-template-rows:none;min-height:0;}}
    .m-media{{grid-row:auto;}}
    .m-hero{{aspect-ratio:1/1;flex:0 0 auto;}}
    .m-name{{font-size:40px;}}
    .m-body{{padding:18px 18px 26px;}}
    .thumbs{{padding-left:18px;padding-right:18px;}}
    .about-hero{{padding:36px 20px 22px;}}
    .about-body{{padding:0 20px 26px;}}
    .legal{{padding:26px 20px 28px;}}
    .about h2{{font-size:22px;}}
    .creed li{{font-size:14.5px;gap:11px;}}
    .sub-modal{{padding:34px 20px 28px;}}
    .sim-row{{grid-template-columns:repeat(2,1fr);}}
    .scores{{padding:16px 16px 13px;}}
    .tlists ul{{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px;}}
    /* Stack on phones — 288px of bars beside chips is unreadable. */
    .topgrid{{grid-template-columns:1fr;gap:16px;margin-bottom:16px;}}
  }}
  /* Only the very narrowest phones drop to one column; 375px still fits two. */
  @media (max-width:680px){{
    .filter-bar{{padding:10px 12px;margin-top:20px;}}
    .fb-label{{font-size:14px;}}
    .fb-clear{{font-size:13px;padding:6px 11px;}}
    /* The pills scroll sideways as one row rather than wrapping five of them
       onto three lines and pushing the dogs off the screen. `safe center` keeps
       them centred until they overflow, then falls back to flex-start — plain
       `center` in a scroll container puts the first pill out of reach. */
    .fbar{{margin:22px 0 -4px;}}
    /* The row scrolls sideways again, and that is only safe because an open menu
       no longer lives inside it — see openMenuInLayer(). Read this before
       touching either.
       The menus are position:fixed. WebKit clips a fixed descendant to any
       scrolling ancestor's box, and makes a containing block out of any ancestor
       carrying transform, filter, backdrop-filter, perspective, contain or
       will-change. While the menus were children of this row, that meant each
       one was cut down to the row's own 87px — which on a phone is
       indistinguishable from the menu opening behind the dogs.
       That shipped twice: first from -webkit-overflow-scrolling:touch, then
       straight back from the plain overflow-x:auto left behind, because z-index
       fixes paint ORDER and clipping is not an ordering problem. The row can
       scroll now because the menu is moved to a body-level layer when it opens,
       where nothing above it clips.
       So: scroll and mask this row as much as you like. What must not change is
       that an open menu is NOT a descendant of it.
       tests/test_multicity.py::test_filter_menus_cannot_be_clipped holds the
       pair together — if this row scrolls, the layer and the move must exist. */
    .fbar-pills{{flex-wrap:nowrap;justify-content:safe center;overflow-x:auto;
      padding-bottom:2px;scrollbar-width:none;}}
    .fbar-pills::-webkit-scrollbar{{display:none;}}
    /* The fade that says the row keeps going. A mask, not an overlaid gradient,
       for two reasons: a mask cannot intercept a touch, so the pills under it
       stay tappable and the row stays scrollable; and it fades to *transparent*
       rather than to a colour, so it is correct on whatever background the
       current theme paints without knowing anything about it. The classes are
       set by paintPillFade() — the edge only fades when there is something
       behind it, so the cue disappears at the end of the scroll and never
       appears at all if the pills happen to fit. */
    .fbar-pills.fade-r{{-webkit-mask-image:linear-gradient(to right,#000
      calc(100% - 34px),transparent);mask-image:linear-gradient(to right,#000
      calc(100% - 34px),transparent);}}
    .fbar-meta{{margin:12px 0 -10px;}}
    /* 17px here, against 19px on desktop. 19px is exactly the phone size of the
       card dog names (.nm, 19px/700), so the count sat at the size and weight of
       the very thing it is a heading for: measured at 390px it stopped reading as
       a heading over the grid and competed with the names instead. Desktop keeps
       19px, where .nm is 23px and the count is already a step below it. 19 to 17
       is the same step the rest of the page's type takes across this breakpoint
       — card names 23 to 19, pills 15 to 13.5 — so the count moves with the
       ladder rather than against it. Size is the only thing that moves: the bold,
       the tracking and the left flush all stay, and the <b> carries no size of
       its own so the numeral comes down with the line. */
    .fbar-n{{font-size:17px;}}
    /* No sort override here on purpose: it is 17px at every width from its base
       declaration, so this breakpoint is where the count comes down to meet it
       rather than where the sort moves. */
    /* 14.5px, and desktop stays at 15px. This was 13.5px, chosen because the
       full 15px cost 22px of overflow for no gain anyone could see. Half of that
       still holds and half didn't survive being read on a phone: 13.5px is a
       step below the 14.5px the *menu* rows these pills open are set at, so the
       control read as smaller than its own contents. 14.5px puts the trigger and
       its options on one size and stops the row looking like fine print.
       It is not free. Measured at 375px the row goes from 6px of overflow to
       19px, so a little more of the last pill starts off-screen — but the row has
       been a scroller with a fade cue at this width for a while, so this makes an
       existing scroll slightly longer rather than introducing one. The full 15px
       is still declined: 26px at the same width, and it would flatten the step
       the rest of the page's type takes across this breakpoint (card names 23 to
       19, count 19 to 17) for the sake of matching desktop, which has room this
       breakpoint doesn't. */
    /* 12px of side padding, not the desktop 14. The drawn chevrons are ~5px
       wider each than the text glyph they replaced, which put 15.7px back onto
       a row that had 8.7px of room — enough to reintroduce the overflow the
       "Foster" rename had just removed. Padding is the cheapest place to find
       it back: 2px a side across four pills returns 16px, the pills still look
       generously spaced at this size, and neither the chevron nor the label had
       to shrink to pay for it. */
    .fpill > button,.fpill-t{{font-size:14.5px;padding:8px 12px;}}
    /* The sort deliberately does NOT come down to 14.5px with them: it is 17px
       at every width, and it is now short enough that the width that costs is
       no longer the problem it was when it read "Sort by: Recently added". */
    /* Anchored to the row, not the pill, so a menu on the last pill can't open
       off the edge of a phone. */
    .fmenu{{position:fixed;left:14px;right:14px;min-width:0;
      top:auto;transform:translateY(-6px);}}
    /* Re-asserted: the desktop right-anchor for the sort menu is more specific
       than the rule above and would otherwise defeat this full-width sheet. */
    .fpill.fsort .fmenu{{left:14px;right:14px;}}
    .pick-menu{{position:fixed;left:50%;transform:translateX(-50%) translateY(-6px);
      width:calc(100vw - 28px);max-width:330px;min-width:0;}}
    .pick.open .pick-menu{{transform:translateX(-50%);}}
    .pick-menu button,.pick-menu a{{padding:13px 15px;font-size:16.5px;}}
  }}
  @media (max-width:400px){{
    .tlists ul{{grid-template-columns:1fr;}}
  }}
  /* This used to also strip the sort back to its value alone, with a border, on
     the grounds that "Sort by: Recently added" ran the results row out of line
     below about 340px. The trigger is now "Sort by" and that whole problem is
     gone: measured at 320px, the narrowest phone worth serving, the count and
     the sort leave 123px of slack between them. There is nothing left here to
     fall back to, so the fallback went rather than sitting in the file being
     read as still-needed. One column is all this breakpoint still does. */
  @media (max-width:339px){{
    .grid{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body class="boot">

<nav>
  <div class="nav-in">
    <div class="nav-left">
      <button class="nav-btn saved-chip" id="saved-chip"
              aria-label="Your saved dogs">
        <svg class="hrt sc-hrt" viewBox="0 0 24 24" aria-hidden="true"><path
          d="M12 21C8 18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 12
          8C12.9 6 14.5 4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 16 18 12
          21Z"/></svg><b>0</b></button>
    </div>
    <div class="nav-mid">
      <div class="nav-count" id="nav-count">
        <span class="nc-dot"></span><b id="nc-n">0</b>
        <span class="nc-l">dogs viewed</span>
      </div>
      <a class="nav-logo" id="nav-logo" href="#" aria-label="LUVD">
        <img src="assets/luvd-logo.png" alt="LUVD" width="1400" height="607">
      </a>
    </div>
    <div class="nav-r">
      <button class="nav-btn" id="about-btn">About</button>
      <button class="nav-btn nav-cta" id="sub-btn">Subscribe</button>
    </div>
  </div>
</nav>

<div class="wrap">
  <header>
    <div class="brand-wrap">{LOGO_SVG}</div>
    <h1 class="pick-h1">Adopt a
      <span class="pick" data-kind="species">
        <button type="button" id="pick-species" aria-haspopup="listbox"
                aria-expanded="false">dog{CHEVRON}</button>
        <span class="pick-menu" id="menu-species" role="listbox" hidden>
          <button role="option" data-v="dog" data-ok="1">Dogs</button>
          <button role="option" data-v="cat">Cats</button>
        </span>
      </span>
      in
      <span class="pick" data-kind="city">
        <button type="button" id="pick-city" aria-haspopup="listbox"
                aria-expanded="false">{c.short}{CHEVRON}</button>
        <span class="pick-menu" id="menu-city" role="listbox" hidden>
          {city_options}
        </span>
      </span>
    </h1>
    <div class="soon" id="soon" hidden>
      <p id="soon-msg"></p>
      <form class="hero-sub" id="soon-form">
        <input type="email" id="soon-email" placeholder="you@email.com" required
               autocomplete="email" aria-label="Email address">
        <button type="submit">Tell me when it's ready</button>
      </form>
      <div class="hero-note" id="soon-note">We'll only write when it launches.</div>
    </div>

    <!-- One compact row, not a boxed section: capture the intent without
         pushing the dogs below the fold. -->
    <div class="hero-cap" id="hero-cap">
      <form class="hero-sub" id="hero-form">
        <input type="email" id="hero-email" placeholder="you@email.com" required
               autocomplete="email" aria-label="Email address">
        <button type="submit">Send new dogs</button>
      </form>
      <!-- Empty at rest: the button already says what happens, and a line of
           grey restating it pushed the dogs down for nothing. Kept as an
           element because it's the form's feedback slot — the submit handler
           writes success and error copy into it. -->
      <div class="hero-note" id="hero-note"></div>
    </div>
  </header>

  <div class="filter-bar" id="filter-bar" hidden>
    <span class="fb-label">
      <svg class="hrt fb-hrt" viewBox="0 0 24 24" aria-hidden="true"><path
        d="M12 21C8 18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 12 8C12.9
        6 14.5 4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 16 18 12 21Z"/></svg>
      Saved dogs</span>
    <!-- The other half of ?saved=. A list in localStorage is one device's and
         Safari drops it after seven days without a visit, so this is how it
         leaves: a URL the reader keeps. Nothing is sent to us — the ids travel
         in the link, which is what keeps the privacy page's promise true. -->
    <!-- Right side: the link itself, then the button that takes it. Showing the
         URL is what makes "Copy link" legible — you can see it is your own page
         with your own dogs in it, not an account or an upload. Truncated from
         the left of the id list, since the interesting part is the host.
         No "All dogs ✕": the heart in the nav is already the way in and out, and
         it highlights while you are in here, so a second exit in the bar was a
         third white pill competing with the one action worth taking. -->
    <div class="fb-right">
      <code class="fb-url" id="fb-url" hidden></code>
      <button class="fb-clear fb-copy" id="fb-copy" hidden><svg viewBox="0 0 24 24"
          aria-hidden="true"><path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1
          1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/></svg
        ><span class="fb-copy-t">Copy link</span></button>
    </div>
  </div>

  <!-- Four filter pills, centred under the centred hero, and nothing else on
       this line. Every filter is a fact the rescues actually record: breed
       group, sex, age bucket and whether the dog is here yet. Deliberately no
       "good with kids/cats/dogs" — only 3-14% of listings say, so those filters
       would report our data coverage as if it were the dogs. Options are built
       by script from the roster and carry live counts, so nothing leads to
       zero. -->
  <div class="fbar" id="fbar">
    <div class="fbar-pills" id="fbar-pills">
      <span class="fpill" data-kind="breed">
        <button type="button" aria-haspopup="listbox" aria-expanded="false">
          <span class="fp-t">Breed</span>{CHEVRON}</button>
        <span class="fmenu" role="listbox" aria-label="Filter by breed" hidden></span>
      </span>
      <span class="fpill" data-kind="sex">
        <button type="button" aria-haspopup="listbox" aria-expanded="false">
          <span class="fp-t">Gender</span>{CHEVRON}</button>
        <span class="fmenu" role="listbox" aria-label="Filter by gender" hidden></span>
      </span>
      <span class="fpill" data-kind="age">
        <button type="button" aria-haspopup="listbox" aria-expanded="false">
          <span class="fp-t">Age</span>{CHEVRON}</button>
        <span class="fmenu" role="listbox" aria-label="Filter by age" hidden></span>
      </span>
      <!-- Size sits after Age, which is the order somebody narrows in: what kind
           of dog, then which one fits the life they have. It is the fifth pill on
           a row that already scrolls sideways on a phone, so it lands just off
           the right edge at 375px — reachable, and behind the fade cue that says
           the row keeps going. -->
      <span class="fpill" data-kind="size">
        <button type="button" aria-haspopup="listbox" aria-expanded="false">
          <span class="fp-t">Size</span>{CHEVRON}</button>
        <span class="fmenu" role="listbox" aria-label="Filter by size" hidden></span>
      </span>
      <!-- "Foster", not "Foster-to-adopt". The long form was 158.1px on a phone,
           wider than Breed and Age together and the entire reason the row
           overflowed. Only the pill label is short: the card chip, the modal
           chip and the note above the apply button all still say
           "Foster-to-adopt", and so does the accessible name here, which
           paintFilters() keeps in step with the count. Nothing reads this text
           to decide what the program is — that comes from each dog's
           program_label, set by the scraper. -->
      <button class="fpill-t" id="f-program" type="button" aria-pressed="false"
              aria-label="Foster-to-adopt" hidden>Foster <b></b></button>
    </div>
    <!-- The results header, sitting directly on the grid: the count reads as the
         grid's heading on the left, the sort control on the right. Both are
         permanent, so nothing in this row can arrive and shove the other end.
         Sort is not a filter: it reorders rather than narrows, and something is
         always sorting. So it stays off the pill row, names itself "Sort by"
         and wears no pill, to stop it reading as a fifth filter. Off that row
         also means the phone's horizontal pill scroll can't swallow it — in
         there it sat entirely off-screen.
         The label is written into the markup for the no-JS case; paintSort()
         owns it after that, and owns the aria-label in both states. -->
    <div class="fbar-meta" id="fbar-meta">
      <span class="fbar-n" id="fbar-n" aria-live="polite"></span>
      <span class="fpill fsort" data-sort="1">
        <button type="button" aria-haspopup="listbox" aria-expanded="false"
                aria-label="Sort by: Recently added">
          <span class="fp-t">Sort by</span>{CHEVRON}</button>
        <span class="fmenu" role="listbox" aria-label="Sort dogs" hidden>
          <button type="button" role="option" data-v="new"
                  aria-selected="true"><span>Recently added</span></button>
          <button type="button" role="option" data-v="wait"
                  aria-selected="false"><span>Longest waiting</span></button>
          <button type="button" role="option" data-v="views"
                  aria-selected="false"><span>Most viewed</span></button>
        </span>
      </span>
    </div>
  </div>

  <div class="saved-empty" id="filter-empty" hidden>
    <div class="se-art" aria-hidden="true">
      <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5 21 21"/></svg>
    </div>
    <h2>No dogs match those filters</h2>
    <p>Try loosening one of them — every dog we have today is still here behind
       the filters.</p>
    <button class="cta" id="fe-clear">Show all dogs</button>
  </div>

  <div class="saved-empty" id="saved-empty" hidden>
    <div class="se-art" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d="M12 21C8 18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4
        4.4C9.5 4.4 11.1 6 12 8C12.9 6 14.5 4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21
        14.6 16 18 12 21Z"/></svg>
    </div>
    <h2>No saved dogs yet</h2>
    <p>Tap the heart on any dog to keep them here. Your list stays on this
       device — no account, nothing sent to us.</p>
    <button class="cta" id="se-browse">Browse today's dogs</button>
  </div>

  <!-- Someone arrived on a ?saved= link. There are no accounts and the list was
       never sent to us, so the link IS the list — which means this looks the
       same whether it is your own link on a new phone or one a friend sent you.
       Hidden until shared-list JS finds ids in the URL. -->
  <div class="shared-bar" id="shared-bar" hidden>
    <div class="sb-in">
      <div class="sb-text">
        <div class="sb-h" id="sb-h">A shared list</div>
        <div class="sb-sub" id="sb-sub"></div>
      </div>
      <button class="cta sb-save" id="sb-save" type="button">Save these to my list</button>
    </div>
  </div>

  <main id="dogs">
  {grid}
  {empty}
  </main>

  <section class="sub-sec" id="subscribe">
    <h2>Never miss a good dog</h2>
    <p>One email when new dogs drop from top rescues in your favorite cities.</p>
    <form class="sub-form" id="sub-form">
      <input type="email" id="sub-email" placeholder="you@email.com" required
             autocomplete="email" aria-label="Email address">
      <button type="submit">Subscribe</button>
    </form>
    <fieldset class="sub-cities" id="sub-cities">
      <legend class="vh">Cities to hear about</legend>
      {sub_picks}
    </fieldset>
    <div class="sub-note" id="sub-note">Free. Unsubscribe anytime.</div>
  </section>

  <section class="faq">
    <h2>Adopting a dog in {c.name}</h2>
    <details open>
      <summary>How do I adopt a dog in {c.short}?</summary>
      <p>Open any dog above and use the button at the bottom of its page. Some
         {c.short} rescues take email inquiries; most ask for an adoption application
         first. LUVD sends you to whichever step that rescue actually requires,
         so you don't get bounced.</p>
    </details>
    <details>
      <summary>Which rescues does LUVD cover?</summary>
      <p>{rescue_sentence} We check all of them every morning and show you what's
         new, so you don't have to keep a dozen tabs open.</p>
    </details>
    <details>
      <summary>What does it cost to adopt in {c.short}?</summary>
      <p>Fees are set by each rescue and usually run about $150–$500, typically
         covering spay/neuter, vaccinations and microchipping. Where a rescue
         publishes the fee, it's shown on that dog's page.</p>
    </details>
    <details>
      <summary>Which dogs work in an apartment?</summary>
      <p>Every dog gets an apartment-fit rating alongside energy level and how
         much dog experience it needs. These are estimates drawn from the
         rescue's own write-up and breed tendencies — the rescue knows the
         individual dog best.</p>
    </details>
  </section>

  <footer>
    <div class="date">{for_date.strftime('%A, %B %-d, %Y')}</div>
    <nav class="foot-rescues" aria-label="Rescues on LUVD">
      <span class="foot-hd">Rescues on LUVD</span>
      {footer_rescues} &middot; <a class="foot-all" href="{c.rescues_path}">All {c.short} rescues &rarr;</a>
    </nav>
    <nav class="foot-cities" aria-label="Cities on LUVD">{foot_cities}</nav>
    <div style="margin-top:6px;">
      LUVD · <a href="mailto:{CONTACT_EMAIL}?subject=Hello%20LUVD">Contact</a>
      · <button class="foot-link" id="terms-link" type="button">Terms</button>
      · <button class="foot-link" id="privacy-link" type="button">Privacy</button>
    </div>
  </footer>
</div>

<div class="scrim" id="scrim" role="dialog" aria-modal="true">
  <div class="modal" id="modal"></div>
</div>

<script>
const DOGS = {payload};
const SUBSCRIBE_URL = {json.dumps(subscribe_url)};
// You subscribe to one city, and it's the city whose page you're on. Baked in at
// render time rather than read from the URL, so it's right even on a cached copy
// and cannot be confused by a stray query string.
const CITY = {json.dumps(c.code)};
const RESTING_NOTE = {{
  'hero-note': '',
  'sub-note': 'Free. Unsubscribe anytime.',
  'm-sub-note': 'Free. Unsubscribe anytime.',
}};
const CONTACTS = {json.dumps(RESCUE_CONTACTS)};
const CONTACT = {json.dumps(CONTACT_EMAIL)};
const TERMS_HTML = {json.dumps(_terms_html(CONTACT_EMAIL, for_date))};
const PRIVACY_HTML = {json.dumps(_privacy_html(CONTACT_EMAIL, for_date))};
/*KIT:dom-esc*/const scrim = document.getElementById('scrim');
const modal = document.getElementById('modal');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);/*KIT-END:dom-esc*/

// Five words per row, and only the first and last are on screen — they are the
// ends of the scale the heart sits on, so they carry the whole meaning now that
// the answer is no longer spelled out beside it.
//
// The rule they follow, which the old set broke in three places: both ends
// describe the SAME thing in the SAME voice, and both are about the dog.
// "Needs a job" was working-dog jargon against a plain-English "Couch potato".
// "Seasoned owner" described the reader while its left end described the animal.
// "Needs real space" named an amount nobody can picture. Each row now reads as
// one scale rather than asking you to switch frame halfway along it.
//
// The middle three only ever surface in two places — the pin's aria-label
// ("Energy level: Low key") and the similar-dogs line, which appends ", too" —
// so every word here has to still read as a sentence with that suffix.
const SCALE = {scale_json};

function bars(d) {{
  if (!d.scores || !d.scores.energy) return '';
  const rows = Object.keys(SCALE).map(k => {{
    const v = d.scores[k], s = SCALE[k];
    // Centred on the five stops rather than filled: 1 sits at 0%, 3 at 50%,
    // 5 at 100%. The old v*20 put a 3 at 60%, which looked like most of the way
    // to "needs a job" when it meant the middle.
    const pos = (v - 1) * 25;
    // No value on the right any more. The pin's position IS the answer, and the
    // ends name the axis — saying the word again beside it was the duplication
    // people were reading as two separate claims.
    const lo = v === 1 ? ' class="on"' : '';
    const hi = v === 5 ? ' class="on"' : '';
    return `<div class="sc">
        <div class="sc-top">
          <span class="sc-ic">${{s.icon}}</span>
          <span class="sc-lb">${{s.label}}</span>
        </div>
        <div class="sc-track">
          <span class="sc-pin" data-p="${{pos}}" style="left:${{pos}}%"
                role="img" aria-label="${{esc(s.label)}}: ${{esc(s.words[v-1])}}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21C8 18 3
              14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 12 8C12.9 6 14.5
              4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 16 18 12 21Z"/></svg>
          </span>
        </div>
        <div class="sc-ends">
          <span${{lo}}>${{esc(s.words[0])}}</span>
          <span${{hi}}>${{esc(s.words[4])}}</span>
        </div>
      </div>`;
  }}).join('');
  // No qualifier here and no paragraph under the rows: the owner's call. Worth
  // knowing if this is ever revisited — these four numbers come from the dog's
  // write-up and its breed's tendencies, not from an assessment, so nothing on
  // screen now says they are estimates. enrich._size_outlook and _score are
  // where they are actually derived.
  return `<div class="scores"><div class="sc-hd">Good to know</div>
    ${{rows}}</div>`;
}}

// ---- share ------------------------------------------------------------------
// Builds a 1080x1920 story card on a canvas so it can be saved straight to a
// phone and posted. Photos come back through /img so the canvas stays
// same-origin and can actually be exported.
/*KIT:story-consts*/const STORY_W = 1080, STORY_H = 1920;
const STORY_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif';/*KIT-END:story-consts*/

/*KIT:proxied*/function proxied(url) {{
  return '/img?u=' + encodeURIComponent(url);
}}/*KIT-END:proxied*/

// A hung /img fetch must not strand the modal on "Building…" forever: the
// proxy allows 20s per upstream, and three photos are tried in turn.
/*KIT:loadimg*/function loadImg(src, ms = 8000) {{
  return new Promise((res, rej) => {{
    const im = new Image();
    im.crossOrigin = 'anonymous';
    const stop = setTimeout(() => {{
      im.src = ''; rej(new Error('timed out'));
    }}, ms);
    im.onload = () => {{ clearTimeout(stop); res(im); }};
    im.onerror = () => {{ clearTimeout(stop); rej(new Error('failed to load')); }};
    im.src = src;
  }});
}}/*KIT-END:loadimg*/

/*KIT:drawcover*/function drawCover(ctx, im, x, y, w, h) {{
  const r = Math.max(w / im.width, h / im.height);
  const dw = im.width * r, dh = im.height * r;
  ctx.drawImage(im, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}}/*KIT-END:drawcover*/

// Nine dogs have no photo at all, and a CDN can always fail. Either way the
// card gets the same treatment the photoless tiles get on the page — a big
// initial on an accent wash — because a flat black rectangle reads as broken
// software, and people don't post broken software. The caption still tells the
// two cases apart: "coming soon" on a dog with no photo is true, but on a dog
// whose photo we simply couldn't fetch it hides a broken /img proxy.
/*KIT:drawnophoto*/function drawNoPhoto(ctx, d, failed) {{
  const g = ctx.createLinearGradient(0, 0, STORY_W, STORY_H);
  g.addColorStop(0, '#31101a'); g.addColorStop(.6, '#170d11');
  g.addColorStop(1, '#0b0b0c');
  ctx.fillStyle = g; ctx.fillRect(0, 0, STORY_W, STORY_H);

  ctx.save();
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = 'rgba(255,0,46,.55)';
  ctx.font = '800 400px ' + STORY_FONT;
  ctx.fillText(((d.name || '').trim()[0] || '?').toUpperCase(), STORY_W / 2, 660);
  ctx.font = '600 36px ' + STORY_FONT;
  ctx.fillStyle = 'rgba(255,255,255,.45)';
  ctx.fillText(failed ? "Photo wouldn't load" : 'Photo coming soon',
               STORY_W / 2, 900);
  ctx.restore();
}}/*KIT-END:drawnophoto*/

/*KIT:buildstory*/async function buildStory(d) {{
  const c = document.createElement('canvas');
  c.width = STORY_W; c.height = STORY_H;
  const ctx = c.getContext('2d');

  ctx.fillStyle = '#0b0b0c';
  ctx.fillRect(0, 0, STORY_W, STORY_H);

  // Try a few photos, not just the first: one dead URL shouldn't cost the card
  // its dog. If none of them load, say so on the card rather than shipping a
  // black rectangle.
  let drew = false;
  const tried = (d.photos || []).slice(0, 3);
  for (const u of tried) {{
    try {{
      drawCover(ctx, await loadImg(proxied(u)), 0, 0, STORY_W, STORY_H);
      drew = true;
      break;
    }} catch (e) {{
      // Silence here once cost a day: every card fell back to the placeholder
      // because /img could not reach the photo hosts, and nothing said so.
      console.warn('share card: ' + proxied(u) + ' — ' + e.message);
    }}
  }}
  if (!drew) drawNoPhoto(ctx, d, tried.length > 0);

  // Scrims: darken top and bottom so type stays legible on any photo.
  let g = ctx.createLinearGradient(0, 0, 0, 620);
  g.addColorStop(0, 'rgba(0,0,0,.62)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, STORY_W, 620);
  g = ctx.createLinearGradient(0, STORY_H - 1000, 0, STORY_H);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(.55, 'rgba(0,0,0,.72)');
  g.addColorStop(1, 'rgba(0,0,0,.94)');
  ctx.fillStyle = g; ctx.fillRect(0, STORY_H - 1000, STORY_W, 1000);

  const F = STORY_FONT;

  // Top badge — width measured from the text so the pill hugs it.
  ctx.font = '700 32px ' + F;
  const label = 'ADOPT ME';
  const padX = 34, bh = 74;
  const bw = Math.round(ctx.measureText(label).width) + padX * 2;
  ctx.fillStyle = '#FF002E';
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(80, 96, bw, bh, 37); else ctx.rect(80, 96, bw, bh);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, 80 + padX, 96 + bh / 2 + 1);

  // Name — wrapped, bottom-anchored
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = '#fff';
  let size = 136;
  ctx.font = '800 ' + size + 'px ' + F;
  while (ctx.measureText(d.name).width > STORY_W - 160 && size > 64) {{
    size -= 6; ctx.font = '800 ' + size + 'px ' + F;
  }}
  let y = STORY_H - 430;
  ctx.fillText(d.name, 80, y);

  // Facts line
  const facts = [d.age, d.sex, d.weight, d.breed && !/unknown/i.test(d.breed)
    ? d.breed.split('/')[0].trim() : ''].filter(Boolean).join('  ·  ');
  ctx.font = '500 40px ' + F;
  ctx.fillStyle = 'rgba(255,255,255,.86)';
  if (facts) ctx.fillText(facts, 80, y + 62);

  ctx.font = '600 38px ' + F;
  ctx.fillStyle = '#FF002E';
  ctx.fillText(d.source_label, 80, y + 128);

  // Just the logo. The URL goes on the story as a real Instagram link sticker,
  // which is tappable — burning it into the image only makes it un-clickable.
  try {{
    const lg = await loadImg('assets/luvd-logo.png');
    const lw = 260, lh = lw * (lg.height / lg.width);
    ctx.drawImage(lg, 80, STORY_H - 100 - lh, lw, lh);
  }} catch (e) {{
    ctx.fillStyle = '#FF002E'; ctx.font = '800 60px ' + F;
    ctx.fillText('LUVD', 80, STORY_H - 110);
  }}

  return c;
}}/*KIT-END:buildstory*/

// Every route to the same message, because one of them will be dead for any
// given visitor: Gmail for webmail users, mailto for desktop clients, copy for
// everyone else.
function openContact(d, act) {{
  const gmail = 'https://mail.google.com/mail/?view=cm&fs=1'
    + '&to=' + encodeURIComponent(act.email)
    + '&su=' + encodeURIComponent(act.subject)
    + '&body=' + encodeURIComponent(act.body);
  const mailto = 'mailto:' + act.email
    + '?subject=' + encodeURIComponent(act.subject)
    + '&body=' + encodeURIComponent(act.body);

  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="contact">
      <div class="tl-hd">Email ${{esc(d.source_label)}}</div>
      <p class="ct-lead">We've written the message for you — it names
        ${{esc(d.name)}} and links the listing.</p>
      <div class="ct-addr" id="ct-addr">${{esc(act.email)}}</div>
      <div class="ct-btns">
        <a class="cta" href="${{esc(gmail)}}" target="_blank" rel="noopener">
          Open in Gmail</a>
        <a class="cta cta2" href="${{esc(mailto)}}">Mail app</a>
      </div>
      <div class="ct-btns">
        <button class="cta cta2" id="ct-copy-addr">Copy address</button>
        <button class="cta cta2" id="ct-copy-msg">Copy message</button>
      </div>
      <details class="ct-prev"><summary>Preview the message</summary>
        <pre>${{esc(act.body)}}</pre></details>
      <div class="cta-sub" id="ct-note"></div>
    </div>`, 'narrow');

  const note = document.getElementById('ct-note');
  const copy = async (text, msg) => {{
    try {{ await navigator.clipboard.writeText(text); note.textContent = msg; }}
    catch (e) {{ note.textContent = 'Select the address above and copy it.'; }}
  }};
  document.getElementById('ct-copy-addr').onclick =
    () => copy(act.email, 'Address copied.');
  document.getElementById('ct-copy-msg').onclick =
    () => copy(act.body, 'Message copied — paste it into any email.');
}}

/*KIT:openshare*/async function openShare(d) {{
  const url = dogUrl(d);
  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="share">
      <div class="tl-hd" style="text-align:center;">Share ${{esc(d.name)}}</div>
      <div class="story-wrap"><div class="story-ph" id="story-ph">Building…</div></div>
      <div class="share-url" id="share-url">${{esc(url)}}</div>
      <div class="share-btns">
        <button class="cta cta2" id="copy-link">Copy link</button>
        <button class="cta" id="save-img" disabled>Save image</button>
      </div>
      <div class="cta-sub" id="share-note">
        Save the image, post it to your story, then add the link as a sticker.</div>
    </div>`, 'narrow');

  document.getElementById('copy-link').onclick = async () => {{
    const note = document.getElementById('share-note');
    try {{
      await navigator.clipboard.writeText(url);
      note.textContent = 'Link copied.';
    }} catch (e) {{
      const r = document.createRange();
      r.selectNode(document.getElementById('share-url'));
      getSelection().removeAllRanges(); getSelection().addRange(r);
      note.textContent = 'Press ⌘C to copy the highlighted link.';
    }}
  }};

  let canvas = null;
  try {{
    canvas = await buildStory(d);
    const ph = document.getElementById('story-ph');
    if (ph) {{
      canvas.className = 'story-img';
      ph.replaceWith(canvas);
    }}
    const save = document.getElementById('save-img');
    save.disabled = false;
    save.onclick = () => {{
      canvas.toBlob(b => {{
        if (!b) return;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(b);
        a.download = 'luvd-' + slugFor(d).replace(/:/g, '-') + '.png';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 3000);
        // On phones, offer the OS share sheet as well — that's the path
        // straight into Instagram.
        if (navigator.canShare) {{
          const f = new File([b], a.download, {{type: 'image/png'}});
          if (navigator.canShare({{files: [f]}})) {{
            navigator.share({{files: [f], text: d.name + ' · ' + url}}).catch(() => {{}});
          }}
        }}
      }}, 'image/png');
    }};
  }} catch (e) {{
    const ph = document.getElementById('story-ph');
    if (ph) ph.textContent = "Couldn't build the image — the link still works.";
  }}
}}/*KIT-END:openshare*/

// Two questions people ask after "is it cute": how big will it get, and what
// will it cost me every month. Both are estimates and say so.
function sizeAndCost(d) {{
  const so = d.size_outlook || {{}};
  const mc = d.monthly_cost || {{}};
  if (!so.line && !mc.low) return '';

  let sizeBlock = '';
  if (so.line) {{
    const growing = so.status === 'growing';
    const w = so.adult || so.now;

    // "120 lbs" means nothing without a scale. Showing where a dog lands
    // between a chihuahua and a mastiff is the actually useful part.
    const BANDS = [['Small', 0, 25], ['Medium', 25, 50],
                   ['Large', 50, 90], ['Giant', 90, 1e9]];
    let scale = '';
    if (w) {{
      const idx = BANDS.findIndex(b => w >= b[1] && w < b[2]);
      const nowIdx = so.now ? BANDS.findIndex(b => so.now >= b[1] && so.now < b[2]) : -1;
      scale = `<div class="szscale">${{BANDS.map((b, i) => {{
        const on = i === idx;
        const from = growing && i === nowIdx && nowIdx !== idx;
        return `<span class="szb${{on ? ' on' : ''}}${{from ? ' from' : ''}}">
          <i></i><em>${{b[0]}}</em></span>`;
      }}).join('')}}</div>
      <div class="szcap">${{growing && nowIdx !== idx && nowIdx >= 0
        ? `Now ${{BANDS[nowIdx][0].toLowerCase()}}, growing into a
           ${{BANDS[idx][0].toLowerCase()}} dog`
        : `A ${{BANDS[idx][0].toLowerCase()}} dog by weight`}}</div>`;
    }}

    let bar = '';
    if (so.now && so.adult && so.adult > so.now) {{
      const pct = Math.max(6, Math.min(100, (so.now / so.adult) * 100));
      bar = `<div class="gw"><span style="width:${{pct.toFixed(0)}}%"></span></div>
        <div class="gw-l"><span>${{Math.round(so.now)}} lbs now</span>
        <span>~${{Math.round(so.adult)}} lbs grown</span></div>`;
    }}

    sizeBlock = `
      <div class="sc-block">
        <div class="tl-hd">${{growing ? '📈 Still growing' : '📏 Full size'}}</div>
        <p>${{esc(so.line)}}</p>
        ${{bar}}
        ${{scale}}
      </div>`;
  }}

  let costBlock = '';
  if (mc.low) {{
    const rows = (mc.items || []).map(it =>
      `<li><span>${{esc(it[0])}}</span><b>$${{it[1]}}–${{it[2]}}</b></li>`).join('');
    costBlock = `
      <div class="sc-block">
        <div class="tl-hd">💵 Typical monthly cost</div>
        <div class="cost-big">$${{mc.low}}–${{mc.high}}<span>/month</span></div>
        <ul class="cost-list">${{rows}}</ul>
        <p class="cost-note">A {c.short} estimate for a dog this size and coat.
          Excludes the adoption fee and anything unexpected.</p>
      </div>`;
  }}

  const traits = (d.traits && d.traits.length)
    ? traitLists(d.traits.filter(t => t.kind === 'good'),
                 d.traits.filter(t => t.kind === 'caution'))
    : '';
  const rightCount = (sizeBlock ? 1 : 0) + (traits ? 1 : 0);
  return `<div class="sizecost">
      <div class="sc-inner${{rightCount === 1 ? ' one-right' : ''}}">
        ${{costBlock}}
        <div class="sc-right">${{sizeBlock}}${{traits}}</div>
      </div>
    </div>`;
}}

function traitLists(good, warn) {{
  // Most dogs have no traits at all — render nothing rather than an empty box.
  if (!good.length && !warn.length) return '';
  // One list, greens then ambers. The icon already says which is which, so
  // sub-headings just added chrome and empty space.
  const row = (t, kind, icon) =>
    `<li class="${{kind}}"><i class="tl-ic">${{icon}}</i><span>${{esc(t.text)}}</span></li>`;
  const items = good.map(t => row(t, 'good', '✓'))
    .concat(warn.map(t => row(t, 'warn', '!'))).join('');
  return `<div class="sc-block tlists">
      <div class="tl-hd">🐾 What to expect</div>
      <ul>${{items}}</ul>
    </div>`;
}}

function tabs(d) {{
  const bi = d.breed_info || {{}};
  const bio = d.description
    ? `<p class="bio">${{esc(d.description)}}</p>`
    : `<p style="color:var(--muted)">${{esc(d.source_label)}} hasn't posted a write-up for
       ${{esc(d.name)}} yet — reach out and they'll tell you all about them.</p>`;
  if (!bi.temperament) return `<div class="pane on" data-p="0">${{bio}}</div>`;
  const unknownNote = bi.known ? '' :
    `<p style="color:var(--muted);font-size:14px;margin-bottom:15px;">
       This dog's breed isn't known, so here's general guidance for mixes.</p>`;
  const fr = bi.from_rescue || {{}};
  // One clear line per topic: what the rescue observed about THIS dog comes
  // first, then breed context fills the gap. No callout boxes, no attribution
  // clutter — the verbatim write-up is one tab away for anyone who wants it.
  const firstSentence = t => {{
    const m = String(t).match(/^[^.!?]+[.!?]/);
    return (m ? m[0] : t).trim();
  }};
  const sect = (icon, title, topic, generic) => {{
    const said = fr[topic];
    const context = said ? firstSentence(generic) : generic;
    const line = said
      ? `<b>${{esc(said.replace(/[.]$/, ''))}}.</b> ${{esc(context)}}`
      : esc(context);
    return `<div class="fact">
        <h4>${{icon}} ${{title}}</h4>
        <p>${{line}}</p>
      </div>`;
  }};
  return `
    <div class="tabs">
      <button class="tab on" data-t="0">Breed guide</button>
      <button class="tab" data-t="1">From the rescue</button>
    </div>
    <div class="pane on" data-p="0">
      <span class="breed-tag">${{esc(bi.name)}}</span>
      ${{unknownNote}}
      ${{sect('🧠','Temperament','temperament',bi.temperament)}}
      ${{sect('🎾','Exercise','exercise',bi.exercise)}}
      ${{sect('✂️','Grooming','grooming',bi.grooming)}}
      ${{sect('🏙️','{c.apartment_label}','nyc',bi.nyc)}}
    </div>
    <div class="pane" data-p="1">${{bio}}</div>`;
}}

// ---- similar dogs -----------------------------------------------------------
// Scored against the dog you're looking at: same breed counts most, then how
// closely the three ratings line up, then shared traits and size. Everything is
// computed from data we already have — no extra requests.
function similarTo(d) {{
  const dAttrs = new Set((d.attributes || []).map(a => a.toLowerCase()));
  const dBreed = (d.breed_info || {{}}).name;
  const dKnown = (d.breed_info || {{}}).known;

  return DOGS
    .map((o, i) => {{
      if (o.id === d.id) return null;
      let s = 0;
      const oBreed = (o.breed_info || {{}}).name;
      const sameBreed = dKnown && oBreed && oBreed === dBreed;
      if (sameBreed) s += 6;

      let sameEnergy = false;
      if (d.scores && o.scores) {{
        ['energy', 'apartment', 'experience'].forEach(k => {{
          s += Math.max(0, 2.5 - Math.abs((d.scores[k] || 3) - (o.scores[k] || 3)));
        }});
        sameEnergy = d.scores.energy === o.scores.energy;
      }}

      const sharedAttr = (o.attributes || []).find(a => dAttrs.has(a.toLowerCase()));
      const sharedCount = (o.attributes || [])
        .filter(a => dAttrs.has(a.toLowerCase())).length;
      s += sharedCount * 1.6;

      const sameSize = d.size && o.size && d.size === o.size;
      if (sameSize) s += 1.6;
      if (o.photos && o.photos.length) s += 1;

      // Say the single most concrete thing they have in common.
      let why;
      if (sameBreed) why = 'Also a ' + oBreed;
      else if (sharedAttr) why = sharedAttr;
      else if (sameEnergy && o.scores) why = SCALE.energy.words[o.scores.energy - 1] + ', too';
      else if (sameSize) why = 'Similar size';
      else why = 'Similar overall';

      return {{o: o, i: i, s: s, why: why}};
    }})
    .filter(Boolean)
    .sort((a, b) => b.s - a.s)
    .slice(0, 4);
}}

function simSection(d) {{
  const list = similarTo(d);
  if (!list.length) return '';
  const cards = list.map(x => {{
    const ph = x.o.photos && x.o.photos.length
      ? `<img class="sim-ph" src="${{esc(x.o.photos[0])}}" alt="${{esc(x.o.name)}}" loading="lazy">`
      : `<div class="sim-ph noph">🐾</div>`;
    return `<button class="sim-card" data-i="${{x.i}}" data-id="${{esc(x.o.id)}}">
        ${{ph}}
        <div class="sim-nm">${{esc(x.o.name)}}</div>
        <div class="sim-rs">${{esc(x.o.source_label)}}</div>
        <div class="sim-why">${{esc(x.why)}}</div>
      </button>`;
  }}).join('');
  return `<div class="sim">
      <div class="sim-hd">More dogs like ${{esc(d.name)}}</div>
      <p class="sim-note">Matched on breed, size and the four ratings above.
        Here's what each one shares with ${{esc(d.name)}}:</p>
      <div class="sim-row">${{cards}}</div>
    </div>`;
}}

/*KIT:showmodal*/function showModal(inner, size) {{
  modal.classList.toggle('narrow', size === 'narrow');
  modal.classList.toggle('mid', size === 'mid');
  scrim.classList.remove('sheet');
  // `compact` keeps the small modals (subscribe, about) as centered cards on
  // phones, while a dog's detail view goes full screen.
  scrim.classList.toggle('compact', !!size);
  modal.innerHTML = inner;
  const sc = modal.querySelector('.m-scroll');
  if (sc) sc.scrollTop = 0; else modal.scrollTop = 0;
  scrim.classList.add('on');
  document.body.classList.add('locked');
  requestAnimationFrame(() => {{
    scrim.classList.add('vis');
    // The pins pop in one after another rather than all at once — the row is
    // read top to bottom, and a stagger follows the eye down it.
    modal.querySelectorAll('.sc-pin').forEach((p, i) =>
      setTimeout(() => p.classList.add('in'), 110 + i * 70));
  }});
  const x = modal.querySelector('.m-close');
  if (x) x.onclick = closeModal;
}}/*KIT-END:showmodal*/

// Each rescue's real next step. Where they take email, we open a draft with
// the dog named and the listing linked so nothing gets lost. Where they require
// an application first, we send people there instead — emailing would only get
// them redirected.
function trackOut(d, kind) {{
  try {{
    const body = JSON.stringify({{id: d.id, source: d.source, kind: kind}});
    // Fires reliably even as the browser navigates to the rescue.
    if (navigator.sendBeacon) {{
      navigator.sendBeacon('/outbound', new Blob([body],
        {{type: 'application/json'}}));
    }} else {{
      fetch('/outbound', {{method: 'POST', keepalive: true,
        headers: {{'Content-Type': 'application/json'}}, body: body}});
    }}
  }} catch (e) {{}}
}}

// The rescue's homepage — the root of whatever contact/adopt/listing URL we
// have on file, so the attribution under the name links somewhere useful.
function rescueHome(d) {{
  const c = CONTACTS[d.source] || {{}};
  const src = c.contact_url || c.apply_url || d.cta_url || d.url || '';
  try {{ return new URL(src).origin; }} catch (e) {{ return ''; }}
}}

function contactAction(d) {{
  const c = CONTACTS[d.source] || {{}};
  const url = dogUrl(d);
  // A placement program outranks the rescue's standard route: this dog is
  // placed a different way, on a different form, and d.cta_url already points
  // there. Sending someone to the normal application would be the wrong ask.
  if (d.program && d.program_label) {{
    return {{
      href: d.cta_url,
      label: `Apply to ${{d.program_label.toLowerCase()}} ${{d.name}} →`,
      note: d.program_note || null,
      program: d.program_label
    }};
  }}
  if (c.method === 'email' && c.email) {{
    const subject = `Adoption inquiry: ${{d.name}}`;
    const body =
      `Hi ${{d.source_label}},\n\n` +
      `I'd like to adopt ${{d.name}}${{d.age ? ` (${{d.age}}` +
        (d.sex ? `, ${{d.sex}}` : '') + ')' : ''}}, who I found through LUVD.\n\n` +
      `Your listing: ${{d.url}}\n` +
      `LUVD page: ${{url}}\n\n` +
      `A bit about me:\n` +
      `• Name:\n` +
      `• Neighborhood:\n` +
      `• Home (apartment/house, own or rent):\n` +
      `• Who lives with me (adults, kids, other pets):\n` +
      `• Experience with dogs:\n` +
      `• Typical hours the dog would be alone:\n\n` +
      `Could you let me know the next step?\n\nThank you!`;
    return {{
      href: '#', email: c.email, subject: subject, body: body,
      label: `Email about ${{d.name}} →`,
      note: null
    }};
  }}
  if (c.apply_url) {{
    return {{
      href: c.apply_url,
      label: `Apply to adopt ${{d.name}} →`,
      note: `${{d.source_label}} asks for an application before they can talk about a dog.`
    }};
  }}
  return {{href: d.cta_url, label: `Contact ${{d.source_label}} →`, note: null}};
}}

function renderDog(d) {{
  const act = contactAction(d);
  const factPills = [d.age, d.sex, d.weight, d.location].filter(Boolean)
    .map(f => `<span class="chip">${{esc(f)}}</span>`).join('')
    + (d.waiting_days >= {WAIT_BADGE_DAYS}
        ? `<span class="chip wait">⏳ Listed ${{d.waiting_days}} days</span>` : '')
;
  // Facts stay as neutral chips. Anything that helps or complicates an
  // adoption moves out into its own labelled list, so a glance tells you
  // what's easy about this dog and what you'd be signing up for.
  const traits = (d.traits && d.traits.length)
    ? d.traits
    : (d.attributes || []).map(a => ({{text: a, kind: 'info'}}));
  const goodT = traits.filter(t => t.kind === 'good');
  const warnT = traits.filter(t => t.kind === 'caution');
  const infoT = traits.filter(t => t.kind === 'info');
  const traitPills = infoT.map(t =>
    `<span class="chip">${{esc(t.text)}}</span>`).join('');
  const breedPill = d.breed && !/unknown/i.test(d.breed)
    ? `<span class="chip">${{esc(d.breed)}}</span>` : '';
  const programChip = d.program_label
    ? `<span class="chip program">${{esc(d.program_label)}}</span>` : '';
  const hasPhoto = !!(d.photos && d.photos.length);
  // Photos then clips, one strip. A clip's thumbnail is a muted <video> at
  // #t=0.1 so the browser paints its own first frame as the poster.
  const clips = d.videos || [];
  const tiles = (d.photos || []).map(p =>
      `<img src="${{esc(p)}}" data-src="${{esc(p)}}" data-kind="img" alt="">`)
    .concat(clips.map(v =>
      `<span class="th-v" data-src="${{esc(v)}}" data-kind="vid" role="button"
             tabindex="0" aria-label="Play video of ${{esc(d.name)}}"><video
             src="${{esc(v)}}#t=0.1" preload="metadata" muted playsinline
             ></video><i class="th-play"></i></span>`));
  const thumbs = tiles.length > 1
    ? `<div class="thumbs">${{tiles.map((t, n) =>
        n === 0 ? t.replace(/^(<\w+)/, '$1 class="sel"') : t).join('')}}</div>`
    : '';
  const media = hasPhoto ? `
    <div class="m-media">
      <div class="m-hero"><img id="hero" src="${{esc(d.photos[0])}}"
        alt="${{esc(d.name)}}">
        <video id="hero-v" controls playsinline preload="metadata" hidden></video>
        <span class="views m-views" id="m-views" data-id="${{esc(d.id)}}"${{
          (VIEW_COUNTS[d.id] || 0) >= VIEW_FLOOR ? '' : ' hidden'}}>
          <span class="eyes" aria-hidden="true">👀</span><b>${{VIEW_COUNTS[d.id] || 0}}</b></span>
      </div>
      ${{thumbs}}
    </div>` : '';

  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="m-scroll${{hasPhoto ? '' : ' no-hero'}}">
    <div class="m-body">
      <div class="topgrid${{hasPhoto ? ' with-photo' : ''}}">
        ${{media}}
        <div class="idcol">
          <div class="m-name-row">
            <h2 class="m-name">${{esc(d.name)}}</h2>
            <button class="save m-save" data-id="${{esc(d.id)}}" type="button"
                    aria-pressed="false" aria-label="Save ${{esc(d.name)}}">
              <svg class="hrt" viewBox="0 0 24 24" aria-hidden="true"><path
                d="M12 21C8 18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6
                12 8C12.9 6 14.5 4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 16 18
                12 21Z"/></svg>
              <span class="burst" aria-hidden="true"></span>
            </button>
          </div>
          ${{(() => {{ const home = rescueHome(d); return home
            ? `<a class="m-rescue" href="${{esc(home)}}" target="_blank"
                 rel="noopener">${{esc(d.source_label)}}</a>`
            : `<p class="m-rescue">${{esc(d.source_label)}}</p>`; }})()}}
          <div class="chips">
            ${{programChip}}${{breedPill}}${{factPills}}${{traitPills}}</div>
        </div>
        ${{bars(d)}}
      </div>
      ${{sizeAndCost(d)}}
      ${{tabs(d)}}
      <div class="cta-sub" style="margin-top:18px;">
        <a href="${{esc(d.url)}}" target="_blank" rel="noopener">View original listing</a></div>
      ${{simSection(d)}}
    </div>
    </div>
    <div class="m-foot">
      ${{act.note ? `<div class="act-note${{act.program ? ' prog' : ''}}">${{
        act.program ? `<b>${{esc(act.program)}}.</b> ` : ''}}${{esc(act.note)}}</div>` : ''}}
      <div class="foot-row">
        ${{act.email
          ? `<button class="cta" id="contact-btn">${{esc(act.label)}}</button>`
          : `<a class="cta" href="${{esc(act.href)}}" target="_blank"
               rel="noopener">${{esc(act.label)}}</a>`}}
        <button class="cta cta2" id="share-btn">
          <svg class="shr-ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 15V3M12 3 8.5 6.5M12 3l3.5 3.5"/>
            <path d="M4.5 13.5v4.75A1.75 1.75 0 0 0 6.25 20h11.5a1.75 1.75 0
                     0 0 1.75-1.75V13.5"/>
          </svg>Share ${{esc(d.name)}}</button>
      </div>
      ${{d.fee ? `<div class="cta-sub">Adoption fee ${{esc(d.fee)}}</div>` : ''}}
    </div>`);

  const sb = document.getElementById('share-btn');
  if (sb) sb.onclick = () => {{ trackOut(d, 'share'); openShare(d); }};
  const cb = document.getElementById('contact-btn');
  if (cb) cb.onclick = () => {{ trackOut(d, 'email'); openContact(d, act); }};
  const applyLink = modal.querySelector('.m-foot a.cta');
  if (applyLink) applyLink.addEventListener('click', () => trackOut(d, 'apply'));
  modal.querySelectorAll('.cta-sub a[target="_blank"]').forEach(a =>
    a.addEventListener('click', () => trackOut(d, 'listing')));
  bindSaves(modal);
  paintSaved();

  modal.querySelectorAll('.sim-card').forEach(sc => sc.onclick = () => {{
    openDog(+sc.dataset.i);
    const card = document.querySelector(`.card[data-id="${{CSS.escape(sc.dataset.id)}}"]`);
    if (card) countView(card);
  }});

  // One handler for both kinds: a photo swaps the <img>, a clip reveals the
  // <video> in the same box. Whatever is playing stops when you pick another,
  // so a modal never leaves sound running behind a photo.
  const heroImg = document.getElementById('hero');
  const heroVid = document.getElementById('hero-v');
  const pickTile = t => {{
    modal.querySelectorAll('.thumbs [data-kind]')
      .forEach(o => o.classList.remove('sel'));
    t.classList.add('sel');
    if (t.dataset.kind === 'vid') {{
      heroVid.src = t.dataset.src;
      heroVid.hidden = false; heroImg.hidden = true;
      heroVid.play().catch(() => {{}});
    }} else {{
      heroVid.pause(); heroVid.removeAttribute('src'); heroVid.load();
      heroVid.hidden = true; heroImg.hidden = false;
      heroImg.src = t.dataset.src;
    }}
  }};
  modal.querySelectorAll('.thumbs [data-kind]').forEach(t => {{
    t.onclick = () => pickTile(t);
    t.onkeydown = e => {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); pickTile(t); }}
    }};
  }});
  modal.querySelectorAll('.tab').forEach(tb => tb.onclick = () => {{
    modal.querySelectorAll('.tab').forEach(o => o.classList.remove('on'));
    modal.querySelectorAll('.pane').forEach(o => o.classList.remove('on'));
    tb.classList.add('on');
    modal.querySelector('.pane[data-p="' + tb.dataset.t + '"]').classList.add('on');
  }});
}}

// Three things, not four. These are the actual reasons to use LUVD instead of
// opening a dozen rescue tabs — aggregation, better information, and speed.
const CREED = [
  ['Straight from the source.',
   'We pull from the rescues themselves, then re-check every listing overnight. What you see this morning is really available.'],
  ['The context listings leave out.',
   'Energy, apartment fit, experience needed, time alone. Plus a breed guide, so you know if a dog suits your life.'],
  ['Then we point you the right way.',
   'Most rescues want an application first, a few prefer email. Every dog links to the step that one actually needs.'],
];

// Short, fun, and written so a follower actually taps through. The platform
// pulls the share image from the page's og: tags; on image-first apps we also
// hand over og.png directly.
const SHARE_TEXT =
  'Every new rescue dog in {c.short}, on one page every morning. Go meet your dog 🐶';

async function shareLuvd() {{
  const url = location.origin + location.pathname;
  const note = document.getElementById('about-share-note');
  const say = m => {{ if (note) note.textContent = m; }};
  if (navigator.share) {{
    // Prefer sharing with the OG image so image-first apps (Instagram) get a
    // visual; otherwise a plain link share, which X/LinkedIn unfurl themselves.
    try {{
      const resp = await fetch(location.origin + '/og.png');
      const blob = await resp.blob();
      const file = new File([blob], 'luvd.png', {{type: 'image/png'}});
      if (navigator.canShare && navigator.canShare({{files: [file]}})) {{
        await navigator.share(
          {{files: [file], text: SHARE_TEXT + ' ' + url, title: 'LUVD'}});
        return;
      }}
    }} catch (e) {{}}
    try {{
      await navigator.share({{title: 'LUVD', text: SHARE_TEXT, url}});
      return;
    }} catch (e) {{ if (e && e.name === 'AbortError') return; }}
  }}
  // Desktop or no Web Share API — copy the link so it's ready to paste.
  try {{
    await navigator.clipboard.writeText(url);
    say('Link copied — paste it anywhere.');
  }} catch (e) {{
    say('Copy this link: ' + url);
  }}
}}

// Terms / Privacy — same sheet treatment as About, just static legal copy.
function openLegal(title, bodyHtml) {{
  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="m-scroll">
      <div class="legal">
        <h2 class="legal-h">${{esc(title)}}</h2>
        ${{bodyHtml}}
      </div>
    </div>`, 'mid');
  scrim.classList.add('sheet');
}}
const openTerms = () => openLegal('Terms of Use', TERMS_HTML);
const openPrivacy = () => openLegal('Privacy Policy', PRIVACY_HTML);

function openAbout() {{
  // 'mid' keeps it a 560px card on desktop; on mobile the CSS below takes it
  // full screen, matching the dog detail view.
  const items = CREED.map((c, n) => `
    <li><span class="num">${{String(n + 1).padStart(2, '0')}}</span>
      <span><b>${{esc(c[0])}}</b> ${{esc(c[1])}}</span></li>`).join('');
  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="about">
      <div class="about-hero">
        <img class="about-logo" src="assets/luvd-logo.png" alt="LUVD">
      </div>
      <div class="about-body">
        <h2>Every dog deserves to feel loved<br>and find its forever home.</h2>
        <ul class="creed">${{items}}</ul>
        <div class="about-actions">
          <a class="cta" href="mailto:${{esc(CONTACT)}}?subject=LUVD">Get in touch →</a>
          <button class="cta cta2" id="about-share" type="button">
            <svg class="shr-ic" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 15V3M12 3 8.5 6.5M12 3l3.5 3.5"/>
              <path d="M4.5 13.5v4.75A1.75 1.75 0 0 0 6.25 20h11.5a1.75 1.75 0
                       0 0 1.75-1.75V13.5"/>
            </svg>Share LUVD</button>
        </div>
        <div class="cta-sub" id="about-share-note">We’re not a shelter. We point
          you to the rescues who are.</div>
      </div>
    </div>`, 'mid');
  scrim.classList.add('sheet');
  const asb = document.getElementById('about-share');
  if (asb) asb.onclick = shareLuvd;
}}

/*KIT:closemodal*/function closeModal(fromHash) {{
  if (!fromHash && /^#dog\//.test(location.hash)) {{
    history.pushState(null, '', location.pathname + location.search);
  }}
  // Stop anything playing. The modal keeps its markup until the next open, so
  // a clip left running would go on making noise behind a closed dialog.
  modal.querySelectorAll('video').forEach(v => {{ try {{ v.pause(); }} catch (e) {{}} }});
  scrim.classList.remove('vis');
  document.body.classList.remove('locked');
  setTimeout(() => scrim.classList.remove('on'), 280);
}}/*KIT-END:closemodal*/

// ---- real view counts -------------------------------------------------------
// Counts come from actual clicks into a dog's modal, stored server-side. If the
// backend isn't reachable (pure static hosting) the badges simply never appear —
// we never invent a number.
const VIEW_FLOOR = 1;  // show as soon as a dog has any genuine interest
let VIEW_COUNTS = {{}};

function paintViews(counts) {{
  VIEW_COUNTS = counts || {{}};
  document.querySelectorAll('.card').forEach(c => {{
    const n = counts[c.dataset.id];
    const el = c.querySelector('.views');
    if (!el) return;
    if (n && n >= VIEW_FLOOR) {{
      el.querySelector('b').textContent = n > 999 ? (n / 1000).toFixed(1) + 'k' : n;
      // The emoji is aria-hidden, so without this a screen reader reads a bare
      // number and a sighted visitor has to guess what it counts. Says "views"
      // in words, which is also the honest description of it.
      const label = n === 1 ? '1 person has viewed this dog'
                            : n + ' people have viewed this dog';
      el.title = label;
      el.setAttribute('aria-label', label);
      el.hidden = false;
    }} else {{
      el.hidden = true;
    }}
  }});
}}

function paintTotal(n) {{
  if (typeof n !== 'number' || n < 0) return;
  const wrap = document.getElementById('nav-count');
  const el = document.getElementById('nc-n');
  if (!wrap || !el) return;
  const prev = +el.textContent.replace(/,/g, '') || 0;
  el.textContent = n.toLocaleString('en-US');
  const label = wrap.querySelector('.nc-l');
  if (label) label.textContent = n === 1 ? 'dog viewed' : 'dogs viewed';
  wrap.hidden = false;
  if (n > prev && prev > 0) {{
    el.classList.remove('bump');
    void el.offsetWidth;                 // restart the animation
    el.classList.add('bump');
  }}
}}

fetch('/views').then(r => r.ok ? r.json() : null).then(d => {{
  if (!d) return;
  paintViews(d.dogs || {{}});
  paintTotal(d.total);
  // "Most viewed" is the one order that depends on data the page did not ship
  // with. Somebody can choose it before this resolves — or reload while it is
  // chosen — and would be looking at a grid sorted by nothing. Re-sorted only
  // for that option, because re-appending cards restarts their animation.
  if (sortBy === 'views') applySort();
}}).catch(() => {{}});

function countView(card) {{
  fetch('/view', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{id: card.dataset.id}})
  }}).then(r => r.ok ? r.json() : null).then(d => {{
    if (!d || !d.views) return;
    VIEW_COUNTS[card.dataset.id] = d.views;
    const el = card.querySelector('.views');
    if (el && d.views >= VIEW_FLOOR) {{
      el.querySelector('b').textContent = d.views;
      el.hidden = false;
    }}
    // The modal for this dog is open right now — keep its chip in step.
    const chip = document.getElementById('m-views');
    if (chip && chip.dataset.id === card.dataset.id && d.views >= VIEW_FLOOR) {{
      chip.querySelector('b').textContent = d.views;
      chip.hidden = false;
    }}
    paintTotal(d.total);
  }}).catch(() => {{}});
}}

// ---- one URL per dog --------------------------------------------------------
// Hash routing keeps every dog shareable without needing a server that knows
// about routes, and it survives being copied into an email or a text.
/*KIT:slugfor*/function slugFor(d) {{
  return d.id.replace(/[^a-zA-Z0-9:_-]/g, '');
}}

// The link you hand to somebody else/*KIT-END:slugfor*/: the dog's own page, not a fragment of the
// roster. This used to be `pathname + '#dog/' + id`, which shared and unfurled
// as the whole city page — the recipient landed on 230 dogs and had to find the
// one they were sent, and everything that reads a URL for meaning (link previews,
// a rescue opening an inquiry, an answer engine) saw the roster. The dog's page
// is written by the same run, carries its own title, photo and apply button, and
// is the URL in the sitemap.
//
// `#dog/<id>` is still what the in-page modal pushes to history (see openDog):
// that is view state within a page you are already on, which is a different job
// from a link that leaves the building.
//
// Sharing the *site* is unchanged and still the city page — see shareLuvd().
/*KIT:dogurl*/function dogUrl(d) {{
  return location.origin + (d.path || (location.pathname + '#dog/' + slugFor(d)));
}}/*KIT-END:dogurl*/

function openDog(i, opts) {{
  const d = DOGS[i];
  if (!d) return;
  renderDog(d);
  if (!(opts && opts.silent)) {{
    const h = '#dog/' + slugFor(d);
    if (location.hash !== h) history.pushState(null, '', h);
  }}
}}

function openFromHash() {{
  const m = (location.hash || '').match(/^#dog\\/(.+)$/);
  if (!m) {{ if (scrim.classList.contains('on')) closeModal(true); return; }}
  const i = DOGS.findIndex(d => slugFor(d) === m[1]);
  if (i >= 0) openDog(i, {{silent: true}});
}}

window.addEventListener('popstate', openFromHash);
window.addEventListener('hashchange', openFromHash);
if (location.hash) setTimeout(openFromHash, 0);

// Cards are real links so crawlers reach every dog page. For a normal click
// we keep the visitor here and open the modal; modifier-clicks and middle
// clicks fall through so "open in new tab" still works.
// ---- headline pickers ------------------------------------------------------
// Choosing something we don't cover shows a waitlist rather than a shrug, and
// logs the request so "which city next" is answered with data.
(function () {{
  // Flip to true to let people choose an unsupported city/species and join a
  // waitlist. The /interest endpoint and reporting are already built.
  const ALLOW_SOON = false;
  const state = {{species: 'dog', city: '{c.code}', cityFull: '{c.name}'}};
  const LIVE = {{species: 'dog', city: '{c.code}'}};
  const LABEL = {{dog: 'dog', cat: 'cat'}};

  const soon = document.getElementById('soon');
  const soonMsg = document.getElementById('soon-msg');

  function closeAll() {{
    document.querySelectorAll('.pick').forEach(p => {{
      p.classList.remove('open');
      p.querySelector('.pick-menu').hidden = true;
      p.querySelector('button').setAttribute('aria-expanded', 'false');
    }});
  }}

  function evaluate() {{
    const ok = state.species === LIVE.species && state.city === LIVE.city;
    if (!soon) return;
    if (ok) {{
      soon.hidden = true;
      document.querySelectorAll('.grid, .hero-cap, .fbar')
        .forEach(el => el.style.display = '');
      // Handing the grid back: applyView owns which cards are visible, and it
      // still has pills applied from before the detour.
      if (window.applyView) applyView();
      return;
    }}
    const what = state.species === 'cat' ? 'Cats' : 'Dogs';
    soonMsg.innerHTML = `<b>${{esc(what)}} in ${{esc(state.cityFull || state.city)}}</b> isn't live yet — ` +
      `right now LUVD covers dogs in {live_phrase}. Want to know the day it opens?`;
    soon.hidden = false;
    // Hide the dog grid, so we're never showing dogs that contradict the
    // sentence the visitor just composed. The filter row goes with it — there's
    // nothing left to filter.
    document.querySelectorAll('.grid, .hero-cap, .fbar')
      .forEach(el => el.style.display = 'none');
  }}

  document.querySelectorAll('.pick').forEach(pick => {{
    const trigger = pick.querySelector('button');
    const menu = pick.querySelector('.pick-menu');
    trigger.addEventListener('click', e => {{
      e.stopPropagation();
      const open = pick.classList.contains('open');
      closeAll();
      if (!open) {{
        menu.hidden = false;
        // Fixed on mobile, so the top has to be measured rather than inherited.
        if (window.matchMedia('(max-width:680px)').matches) {{
          menu.style.top = (trigger.getBoundingClientRect().bottom + 10) + 'px';
        }} else {{
          menu.style.top = '';
        }}
        requestAnimationFrame(() => pick.classList.add('open'));
        trigger.setAttribute('aria-expanded', 'true');
      }}
    }});
    menu.querySelectorAll('button').forEach(opt => {{
      if (!ALLOW_SOON && !opt.dataset.ok) {{
        opt.disabled = true;
        opt.setAttribute('aria-disabled', 'true');
      }}
      opt.addEventListener('click', e => {{
        e.stopPropagation();
        if (!ALLOW_SOON && !opt.dataset.ok) return;   // not live yet
        const kind = pick.dataset.kind;
        state[kind] = opt.dataset.v;
        if (kind === 'city') state.cityFull = opt.textContent.trim();
        // Short form in the sentence, full name everywhere we have room.
        trigger.childNodes[0].nodeValue =
          kind === 'species' ? LABEL[opt.dataset.v] : opt.dataset.v;
        closeAll();
        evaluate();
      }});
    }});
  }});
  document.addEventListener('click', closeAll);
  document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeAll(); }});

  const sf = document.getElementById('soon-form');
  if (sf) sf.onsubmit = async e => {{
    e.preventDefault();
    const email = document.getElementById('soon-email').value.trim();
    const note = document.getElementById('soon-note');
    try {{
      const r = await fetch('/interest', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{species: state.species, city: state.city, email}})
      }});
      if (!r.ok) throw new Error();
      note.className = 'hero-note ok';
      note.textContent = "You're on the list — we'll write the day it opens.";
      sf.style.display = 'none';
      if (window.luvdCelebrate) window.luvdCelebrate('noted!');
    }} catch (err) {{
      note.className = 'hero-note';
      note.textContent = "Couldn't save that — try again in a moment.";
    }}
  }};
}})();

// Swap the counter for a small logo once the hero mark has scrolled off.
(function () {{
  const nav = document.querySelector('nav');
  const mark = document.querySelector('.brand-wrap');
  if (!nav || !mark) return;
  const sync = () => {{
    const shrunk = mark.getBoundingClientRect().bottom < 56;
    nav.classList.toggle('shrunk', shrunk);
    document.body.classList.toggle('shrunk', shrunk);
  }};
  sync();
  const io = new IntersectionObserver(([e]) => {{
    const shrunk = !e.isIntersecting;
    nav.classList.toggle('shrunk', shrunk);
    document.body.classList.toggle('shrunk', shrunk);
  }}, {{rootMargin: '-56px 0px 0px 0px', threshold: 0}});
  io.observe(mark);
  const navLogo = document.getElementById('nav-logo');
  if (navLogo) navLogo.onclick = e => {{ e.preventDefault(); openAbout(); }};
}})();

// Stagger only what's plausibly on screen; the rest just appear.
(function () {{
  document.querySelectorAll('.grid .card').forEach((c, n) => {{
    if (n < 12) c.style.setProperty('--i', n);
  }});
  requestAnimationFrame(() => {{
    document.body.classList.remove('boot');
    document.body.classList.add('ready');
  }});
  // Longest card finishes at .22s + 11 * .035s + .45s. Past that, drop the
  // animation so re-sorting the grid doesn't replay it on every tile.
  setTimeout(() => document.body.classList.add('anim-done'), 1200);
}})();

// Double-tap a card on touch to save it, the way you'd expect from a photo
// grid. Only on coarse pointers: on a mouse a double click should just open
// the dog, and there's no ambiguity to resolve.
const COARSE = window.matchMedia('(pointer: coarse)').matches;
const DBL_MS = 280;

function bigHeart(card) {{
  const wrap = card.querySelector('.ph-wrap');
  if (!wrap) return;
  const h = document.createElement('span');
  h.className = 'dbl-heart';
  h.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 21C8 18 3 14.6 3 9.6C3 6.4'
    + ' 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 12 8C12.9 6 14.5 4.4 16.6 4.4C18.9 4.4 21'
    + ' 6.4 21 9.6C21 14.6 16 18 12 21Z"/></svg>';
  wrap.appendChild(h);
  setTimeout(() => h.remove(), 900);
}}

function doubleTapSave(card) {{
  const set = savedSet();
  if (!set.has(card.dataset.id)) {{
    set.add(card.dataset.id);
    writeSaved(set);
    paintSaved();
    const btn = card.querySelector('.save');
    if (btn) floatHearts(btn);
    if (window.luvdBeat) window.luvdBeat();
  }}
  bigHeart(card);                       // confirm even if already saved
  if (navigator.vibrate) navigator.vibrate(12);
}}

document.querySelectorAll('.card').forEach(c => {{
  let tapTimer = null, lastTap = 0;
  c.addEventListener('click', e => {{
    if (e.target.closest('.save')) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();

    if (!COARSE) {{ openDog(+c.dataset.i); countView(c); return; }}

    const now = Date.now();
    if (now - lastTap < DBL_MS) {{     // second tap — save instead of opening
      clearTimeout(tapTimer);
      tapTimer = null;
      lastTap = 0;
      doubleTapSave(c);
      return;
    }}
    lastTap = now;
    tapTimer = setTimeout(() => {{
      tapTimer = null;
      openDog(+c.dataset.i);
      countView(c);
    }}, DBL_MS);
  }});
}});

// ---- saved dogs -------------------------------------------------------------
// Local only. No account, nothing sent to the server — the list never leaves
// this browser.
const SAVE_KEY = 'luvd:saved';

function savedSet() {{
  try {{ return new Set(JSON.parse(localStorage.getItem(SAVE_KEY) || '[]')); }}
  catch (e) {{ return new Set(); }}
}}

function writeSaved(set) {{
  try {{ localStorage.setItem(SAVE_KEY, JSON.stringify([...set])); }} catch (e) {{}}
}}

function paintSaved() {{
  const set = savedSet();
  document.querySelectorAll('.save').forEach(b => {{
    const on = set.has(b.dataset.id);
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  }});
  const n = set.size;
  const chip = document.getElementById('saved-chip');
  if (chip) {{
    chip.querySelector('b').textContent = n;
    chip.classList.toggle('has', n > 0);
    chip.classList.toggle('none', n === 0);
  }}
  // Nothing saved, nothing to link to. Hidden rather than disabled: an empty
  // list already has its own empty state saying what to do, and a dead button
  // beside it is one more thing to read.
  const copy = document.getElementById('fb-copy');
  if (copy) copy.hidden = n === 0;
  const urlEl = document.getElementById('fb-url');
  if (urlEl) {{
    const link = savedLink();
    urlEl.hidden = !link;
    // Without the scheme: it is there to be recognised, not typed.
    if (link) urlEl.textContent = link.replace(/^https?:\/\//, '');
  }}
}}

// Hearts drift up and out of the button. Positioned fixed so they're never
// clipped by the card's overflow:hidden.
function floatHearts(btn) {{
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const r = btn.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  for (let i = 0; i < 7; i++) {{
    const el = document.createElement('span');
    el.className = 'fh';
    el.textContent = '♥';
    const dx = (Math.random() - .5) * 90;
    const dy = -(50 + Math.random() * 70);
    el.style.left = cx + 'px';
    el.style.top = cy + 'px';
    el.style.setProperty('--dx', dx.toFixed(1) + 'px');
    el.style.setProperty('--dy', dy.toFixed(1) + 'px');
    el.style.setProperty('--rot', ((Math.random() - .5) * 70).toFixed(0) + 'deg');
    el.style.fontSize = (11 + Math.random() * 12).toFixed(0) + 'px';
    const dur = 750 + Math.random() * 450;
    el.style.animation = `floatheart ${{dur}}ms cubic-bezier(.2,.7,.3,1) forwards`;
    el.style.animationDelay = (i * 45) + 'ms';
    document.body.appendChild(el);
    setTimeout(() => el.remove(), dur + i * 45 + 80);
  }}
}}

function bindSaves(root) {{
  (root || document).querySelectorAll('.save:not([data-bound])').forEach(b => {{
    b.dataset.bound = '1';
    b.addEventListener('click', e => {{
      e.preventDefault();
      e.stopPropagation();
      const set = savedSet();
      const adding = !set.has(b.dataset.id);
      adding ? set.add(b.dataset.id) : set.delete(b.dataset.id);
      writeSaved(set);
      paintSaved();
      // In the saved view the grid *is* the list of saved dogs, so an unsave has
      // to leave it. Without this the card stayed put wearing an empty heart,
      // and clearing the last save never revealed the "no saved dogs" state.
      // Deliberately only in that view: in the main grid a save must never make
      // the card you just tapped jump out from under you.
      if (showingSaved) applyView();
      if (adding) {{
        b.classList.remove('pop');
        void b.offsetWidth;            // restart the animation
        b.classList.add('pop');
        setTimeout(() => b.classList.remove('pop'), 600);
        floatHearts(b);
        if (window.luvdBeat) window.luvdBeat();
      }}
    }});
  }});
}}
bindSaves();

// ---- filter pills -----------------------------------------------------------
// Four facts, and only facts. There is no "good with kids/cats/dogs" filter on
// purpose: 3-14% of our listings fill those fields in, so the results would
// describe how thoroughly each rescue types rather than which dogs exist, and
// two clicks would land on a confident, false zero.
const FILTERS = {{breed: '', sex: '', age: '', size: ''}};
let fosterOnly = false;

const F_LABEL = {{breed: 'Breed', sex: 'Gender', age: 'Age', size: 'Size'}};
const F_ANY = {{breed: 'Any breed', sex: 'Any gender', age: 'Any age',
              size: 'Any size'}};
// Smallest first, and every row carries its pound range. "Medium" on its own
// means whatever the last dog somebody met weighed; the numbers are the whole
// point of the filter. These are the GROWN weights — see size_bucket() — so a
// puppy sits in the bucket it will end up in, not the one it is in today.
// Unknown last, reading as missing data rather than a size.
//
// Third element is the range, rendered separately and greyed: the word is what
// you are choosing and the number is what tells you whether you chose right, so
// they should not carry the same weight. "< 25" and "50 +" rather than "under
// 25" and "50 and up" — a menu row is scanned, not read, and the symbols say it
// in three characters instead of nine.
const SIZE_ORDER = [
  ['Small', 'Small', '< 25 lbs'],
  ['Medium', 'Medium', '25–50 lbs'],
  ['Large', 'Large', '50 lbs +'],
  ['Unknown', 'Unknown', 'not listed'],
];
// Life order, not popularity: sorting these by count would put Adult above
// Puppy and read as arbitrary. Abbreviated to "yr"/"yrs" so no row wraps to a
// second line — "Senior · 8 years and up" was doing exactly that. Unknown sits
// last and reads as missing data rather than a life stage; it exists so the
// options add up to "Any age" with no dog left unreachable.
const AGE_ORDER = [
  ['Puppy', 'Puppy · under 1 yr'],
  ['Young', 'Young · 1–2 yrs'],
  ['Adult', 'Adult · 3–7 yrs'],
  ['Senior', 'Senior · 8+ yrs'],
  ['Unknown', 'Unknown · not listed'],
];
// The catch-alls are our biggest groups and the least useful thing to pick, so
// they sink to the bottom instead of leading on count.
const OPT_LAST = ['Mixed / unknown', 'Other', 'Unknown'];

// One definition of which bucket a dog is in, used for both counting and
// matching so the two can't disagree. The fallback is what makes each pill's
// options total over the roster: a blank field would otherwise put a dog in
// "Any" and in no option, i.e. in a list you can't click your way to.
const fieldOf = (d, kind) => (kind === 'breed' ? d.breed_group
  : kind === 'age' ? d.age_bucket
  : kind === 'size' ? d.size_bucket : d.sex) || 'Unknown';

// `skip` evaluates a menu's own options as if that pill were cleared. That's
// what makes the counts inside it reachable numbers rather than a column of
// zeroes, and it's the whole reason you can't click your way to an empty page.
function fMatch(d, skip) {{
  for (const kind of ['breed', 'sex', 'age', 'size']) {{
    if (FILTERS[kind] && skip !== kind && fieldOf(d, kind) !== FILTERS[kind]) return false;
  }}
  if (fosterOnly && skip !== 'foster' && d.program !== 'foster-to-adopt') return false;
  return true;
}}

function fOptions(kind) {{
  // Fixed order for the two scales that have one. Sorting these by count would
  // put Adult above Puppy, and Medium above Small, which reads as arbitrary.
  if (kind === 'age' || kind === 'size') {{
    const order = kind === 'age' ? AGE_ORDER : SIZE_ORDER;
    return order.filter(([v]) => DOGS.some(d => fieldOf(d, kind) === v));
  }}
  const counts = new Map();
  DOGS.forEach(d => {{
    const v = fieldOf(d, kind);
    counts.set(v, (counts.get(v) || 0) + 1);
  }});
  return [...counts.entries()]
    .sort((a, b) => (OPT_LAST.indexOf(a[0]) - OPT_LAST.indexOf(b[0])) || b[1] - a[1])
    .map(([v]) => [v, v]);
}}

// Only the pills that filter. The sort pill shares their looks and their
// open/close behaviour, but it has no counts and never narrows the list.
function buildFilterMenus() {{
  document.querySelectorAll('.fpill[data-kind]').forEach(pill => {{
    const kind = pill.dataset.kind;
    const menu = menuOf(pill);
    if (!menu) return;
    // `detail` is the optional third element — the size ranges. Greyed, so the
    // name is what you read and the number is what you check.
    menu.innerHTML = [['', F_ANY[kind]]].concat(fOptions(kind))
      .map(([v, label, detail]) =>
        `<button type="button" role="option" data-v="${{esc(v)}}" aria-selected="false">` +
        `<span>${{esc(label)}}` +
        (detail ? `<i class="opt-d">${{esc(detail)}}</i>` : '') +
        `</span><b></b></button>`).join('');
  }});
}}

function paintFilters(pool) {{
  document.querySelectorAll('.fpill[data-kind]').forEach(pill => {{
    const kind = pill.dataset.kind;
    const cur = FILTERS[kind];
    const base = pool.filter(d => fMatch(d, kind));
    (menuOf(pill) || pill).querySelectorAll('button[data-v]').forEach(opt => {{
      const v = opt.dataset.v;
      const n = v ? base.filter(d => fieldOf(d, kind) === v).length : base.length;
      opt.querySelector('b').textContent = n;
      opt.disabled = !n && v !== cur;
      opt.setAttribute('aria-selected', v === cur ? 'true' : 'false');
    }});
    pill.classList.toggle('on', !!cur);
    const tag = pill.querySelector('.fp-t');
    if (tag) tag.textContent = cur || F_LABEL[kind];
  }});
  const prog = document.getElementById('f-program');
  if (prog) {{
    prog.hidden = !DOGS.some(d => d.program === 'foster-to-adopt');
    const n = pool.filter(d => fMatch(d, 'foster')
      && d.program === 'foster-to-adopt').length;
    prog.querySelector('b').textContent = n;
    // The eye gets "Foster 15", the screen reader gets the program's real name
    // and the same count. Rebuilt here rather than left static so the count
    // doesn't fall out of the accessible name as the other filters change it.
    prog.setAttribute('aria-label', `Foster-to-adopt ${{n}}`);
    prog.classList.toggle('on', fosterOnly);
    prog.setAttribute('aria-pressed', fosterOnly ? 'true' : 'false');
    prog.disabled = !n && !fosterOnly;
  }}
}}

// The four pills fit a 390px phone, but only just, and they stop fitting on a
// narrower one. A row that scrolls with no cue at its edge reads as a row that
// simply ends — which would hide Foster, the one filter here that isn't a
// generic pet-site facet. These classes drive a mask in the stylesheet, and
// nothing below asks how wide the screen is: the fade is keyed on whether this
// row actually overruns, so it shows itself at 320px and stays away at 390px
// without a breakpoint deciding for it. Renaming the pill didn't make this
// dead code; it moved the width where it starts to matter.
const pillRow = document.getElementById('fbar-pills');
// Looked up lazily, not at parse time: this script runs before the end of the
// body, and #fmenu-layer is declared after it. Resolving eagerly gave a silent
// null, openMenuInLayer() returned early every time, and the menus stayed inside
// the scrolling row — the exact bug this was written to fix, with no error to
// show for it.
let _menuLayer = null;
function menuLayerEl() {{
  if (!_menuLayer) _menuLayer = document.getElementById('fmenu-layer');
  return _menuLayer;
}}

// The menu element for a pill, cached the first time it is asked for. Cached
// because an open menu is moved out of its pill and into #fmenu-layer, so
// pill.querySelector('.fmenu') stops finding it precisely while it is open —
// which is exactly when the counts, the close and the aria all need it.
function menuOf(pill) {{
  if (!pill) return null;
  if (!pill._fmenu) pill._fmenu = pill.querySelector('.fmenu');
  return pill._fmenu;
}}

// Why this exists: the pill row scrolls sideways on a phone, and WebKit clips a
// position:fixed descendant to a scrolling ancestor's box. While the menus were
// children of that row every one was cut down to the row's own height and read
// as having opened behind the dogs. No z-index undoes that — clipping is not an
// ordering problem — so an open menu leaves the row for a body-level layer and
// goes back when it closes. The row is then free to scroll and fade as it likes.
function openMenuInLayer(pill, menu) {{
  const layer = menuLayerEl();
  if (!layer || menu.parentElement === layer) return;
  menu._homePill = pill;
  layer.appendChild(menu);
}}

function returnMenuHome(menu) {{
  const home = menu && menu._homePill;
  if (home && menu.parentElement !== home) home.appendChild(menu);
}}
// scrollWidth/clientWidth force layout, so they're read only when something
// could have changed them: a resize, or a repaint that rewrote the pill labels
// (Foster's count changes width as you filter). Scrolling itself reads only
// scrollLeft, which is free.
let pillSlack = 0;
function paintPillFade() {{
  if (!pillRow) return;
  // A mask paints on the element's own box, so anything a descendant draws
  // outside that box is masked away — and an open filter menu is fixed,
  // full-width and far taller than this row, so it vanishes completely. The
  // cue is pointless while a menu is covering the row anyway, so it stands
  // down for as long as one is open. Anything else added here that escapes the
  // row's box needs the same treatment.
  const menuOpen = !!pillRow.querySelector('.fpill.open');
  // The other half of the same problem: the row has to out-rank the grid while
  // the menu is up, or it opens behind the dogs. See .fbar-pills.menu-open.
  pillRow.classList.toggle('menu-open', menuOpen);
  const room = !menuOpen && pillSlack > 1;
  const x = pillRow.scrollLeft;
  pillRow.classList.toggle('fade-r', room && x < pillSlack - 1);
  pillRow.classList.toggle('fade-l', room && x > 1);
}}
function measurePillRow() {{
  if (!pillRow) return;
  pillSlack = pillRow.scrollWidth - pillRow.clientWidth;
  paintPillFade();
}}
if (pillRow) {{
  pillRow.addEventListener('scroll', paintPillFade, {{passive: true}});
  addEventListener('resize', measurePillRow, {{passive: true}});
}}

function closeFilterMenus() {{
  document.querySelectorAll('.fpill').forEach(p => {{
    p.classList.remove('open');
    const menu = menuOf(p);
    if (menu) {{
      menu.classList.remove('open');
      menu.hidden = true;
      returnMenuHome(menu);
    }}
    const trigger = p.querySelector('button');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  }});
  paintPillFade();
}}

function resetFilters() {{
  FILTERS.breed = FILTERS.sex = FILTERS.age = FILTERS.size = '';
  fosterOnly = false;
}}

// ---- sort -------------------------------------------------------------------
// Deliberately not "Newest"/"Oldest": the Age pill sits inches away offering
// "Senior · 8+ yrs", so "Oldest" would read as the oldest dogs. "Longest
// waiting" is unambiguous there and says why you'd pick it — long-listed dogs
// get scrolled past, which is the same reason the ⏳ badge exists.
//
// The two options key on DIFFERENT fields, which looks like a bug until you
// know what each one is answering:
//
//   "Recently added"  -> first_seen,   when LUVD first saw the dog.
//   "Longest waiting" -> waiting_days, how long the RESCUE has had it listed.
//
// waiting_days prefers the rescue's own listed_since and only falls back to
// first_seen, so it is the number printed on the ⏳ badge. Keying "Longest
// waiting" on first_seen instead would let a dog we noticed yesterday sort as
// brand new while its own badge reads "⏳ 300 days" — a contradiction visible
// in one glance. And "Recently added" genuinely means arrival on LUVD, which
// is first_seen and nothing else; a dog can be newly added here and have been
// waiting at its rescue for a year.
const SORT_LABEL = {{new: 'Recently added', wait: 'Longest waiting',
                    views: 'Most viewed'}};
let sortBy = 'new';

// Sorting reorders the cards; applyView still owns which of them are visible.
// The server-rendered data-i indexes stay put — openDog, the similar-dogs cards
// and the view counters all resolve a dog through them.
function applySort() {{
  const grid = document.getElementById('grid');
  if (!grid) return;
  const cards = [...grid.children];
  const dog = c => DOGS[+c.dataset.i] || {{}};
  const seen = c => dog(c).first_seen || '';
  const waited = c => dog(c).waiting_days || 0;
  // Views are not in the page payload — they arrive from /views after load and
  // land in VIEW_COUNTS, so this reads whatever has arrived. See the fetch, which
  // re-runs applySort() once the real numbers are in; sorting on the empty object
  // would otherwise silently order the whole grid by zero.
  const views = c => VIEW_COUNTS[dog(c).id] || 0;
  // Each direction tiebreaks on another field, so the order is total and the
  // result is deterministic rather than leaning on sort stability. Most viewed
  // tiebreaks on arrival, which matters more here than elsewhere: most dogs have
  // no views at all, so without it the entire zero-view tail would be arbitrary.
  const cmp = sortBy === 'wait'
    ? (a, b) => waited(b) - waited(a) || seen(a).localeCompare(seen(b))
    : sortBy === 'views'
    ? (a, b) => views(b) - views(a) || seen(b).localeCompare(seen(a))
    : (a, b) => seen(b).localeCompare(seen(a)) || waited(a) - waited(b);
  const sorted = cards.slice().sort(cmp);
  // Re-appending a node restarts its CSS animation, so don't touch the DOM when
  // the order is already right — which it is on load, the server having
  // rendered newest-first.
  if (sorted.every((c, n) => c === cards[n])) return;
  const frag = document.createDocumentFragment();
  sorted.forEach(c => frag.appendChild(c));
  grid.appendChild(frag);
}}

function paintSort() {{
  const pill = document.querySelector('.fpill[data-sort]');
  if (!pill) return;
  const value = SORT_LABEL[sortBy] || SORT_LABEL.new;
  // The trigger says "Sort by" and nothing else, in both states — the markup
  // already says so, and this function deliberately doesn't touch it. It names
  // the control rather than mirroring the value, which is the opposite of the
  // filter pills, where the gender pill reads "Female" once you pick it. The
  // difference is that there are two orders and one of them is the default, so
  // the value is worth little and costs the widest label in the row. The menu
  // is where the selection lives.
  const btn = pill.querySelector('button');
  // Which makes this the only thing carrying the answer for anyone who can't
  // open the menu and look, so it is never conditional and never omitted.
  if (btn) btn.setAttribute('aria-label', 'Sort by: ' + value);
  // Never filled, unlike the filter pills: something is always sorting, so a
  // filled control here would read as "you've narrowed the list". The menu
  // carries the selection instead, in the accent colour the filter menus
  // already use for theirs.
  (menuOf(pill) || pill).querySelectorAll('button[data-v]').forEach(opt =>
    opt.setAttribute('aria-selected', opt.dataset.v === sortBy ? 'true' : 'false'));
}}

// Filter to saved dogs — a view, not a separate page.
let showingSaved = false;
// What the pills were set to when the saved view took over, held so leaving can
// put them back. Null whenever we're not inside the saved view.
let stashedFilters = null;

// ---- shared lists -----------------------------------------------------------
// A ?saved= link, so a list can leave the browser that made it. localStorage is
// per-device and Safari evicts it after seven days without a visit, so without
// this a saved list quietly disappears — and there is no account to fall back
// on. The ids travel in the URL rather than to us: the privacy page promises the
// list never leaves the device and is never sent to LUVD, and a link the reader
// carries themselves keeps that true.
//
// `null` when this is an ordinary visit. A Set of ids when the URL carried some,
// INCLUDING ids this page has no dog for — which is the point of keeping the raw
// count separately below.
let sharedIds = null;
let sharedAsked = 0;
// Set when the URL turned out to be the reader's own list. Handled at init by
// calling toggleSavedView() rather than by setting showingSaved here, because
// entering that view is more than a flag — it hides the pills, swaps in the
// saved-dogs bar and drops the footer signup.
let openSavedOnLoad = false;

function savedLink() {{
  const ids = [...savedSet()];
  if (!ids.length) return '';
  return location.origin + location.pathname + '?saved=' + ids.join(',');
}}

function readSharedList() {{
  let raw = '';
  try {{ raw = new URLSearchParams(location.search).get('saved') || ''; }}
  catch (e) {{ return; }}
  const ids = raw.split(',').map(s => s.trim()).filter(Boolean);
  if (!ids.length) return;

  // Your own link, opened by you, is just your saved list — so it opens as that,
  // with no "a shared list / save these" bar offering you dogs you already have.
  // The test is whether the link adds anything: every id already saved means
  // there is nothing to adopt and nothing to explain. Same URL, both jobs.
  const mine = savedSet();
  if (ids.every(id => mine.has(id))) {{
    openSavedOnLoad = true;
    return;
  }}
  sharedAsked = new Set(ids).size;
  sharedIds = new Set(ids);
}}

function paintSharedBar() {{
  const bar = document.getElementById('shared-bar');
  if (!bar) return;
  if (!sharedIds) {{ bar.hidden = true; return; }}
  const here = DOGS.filter(d => sharedIds.has(d.id)).length;
  const gone = Math.max(0, sharedAsked - here);
  const h = document.getElementById('sb-h');
  const sub = document.getElementById('sb-sub');
  if (h) h.textContent = 'A shared list';
  if (sub) {{
    // Never "3 adopted": forget_missing() deletes a dog's row rather than
    // recording an outcome, so we know it is no longer listed and genuinely do
    // not know why. Saying the true thing is also the warmer thing here.
    const bits = [here === 1 ? '1 still looking' : `${{here}} still looking`];
    if (gone) bits.push(gone === 1 ? '1 no longer listed'
                                   : `${{gone}} no longer listed`);
    sub.textContent = bits.join(' · ');
  }}
  const btn = document.getElementById('sb-save');
  if (btn) btn.hidden = here === 0;
  bar.hidden = false;
}}

// The single owner of what's on screen. Saved-view and the pills both run
// through here, because two functions each setting card display would take
// turns undoing each other.
function applyView() {{
  const soon = document.getElementById('soon');
  if (soon && !soon.hidden) return;      // a "coming soon" combo owns the grid
  const saved = savedSet();
  // A shared list narrows the grid the same way the saved view does, and takes
  // precedence: somebody who followed a link came to see those dogs.
  const eligible = d => sharedIds ? sharedIds.has(d.id)
                                  : (!showingSaved || saved.has(d.id));
  const pool = DOGS.filter(eligible);

  let shown = 0;
  document.querySelectorAll('.card').forEach(c => {{
    const d = DOGS[+c.dataset.i];
    const ok = !!d && eligible(d) && fMatch(d);
    c.style.display = ok ? '' : 'none';
    if (ok) shown++;
  }});
  paintFilters(pool);
  paintSort();
  const label = document.getElementById('fbar-n');
  // The count is always shown. With the grid flat there's no date heading
  // stating the total any more, so this is the page's only statement of how many
  // dogs there are, and the only confirmation that a filter did anything — on a
  // phone the results are below the fold. Just the number you're looking at, the
  // same sentence either way: the filled pills already say a filter is on and
  // clearing them brings the total back, so "N of M" spent words on something
  // the controls were already saying.
  if (label) label.innerHTML = `<b>${{shown}}</b> dogs`;

  paintSharedBar();
  const noSaves = showingSaved && saved.size === 0;
  const savedEmpty = document.getElementById('saved-empty');
  if (savedEmpty) savedEmpty.hidden = !noSaves;
  const filterEmpty = document.getElementById('filter-empty');
  // A shared list whose dogs have all been placed is not an empty filter result,
  // and "try loosening a filter" would be nonsense advice — the bar above says
  // what happened, so the grid just stays empty under it.
  if (filterEmpty) filterEmpty.hidden = !(shown === 0 && !noSaves && !sharedIds);

  // paintFilters() has just rewritten the option counts inside the pill labels,
  // which changes how far the row overruns, so the edge cue is re-derived here
  // rather than only at load.
  measurePillRow();
}}

function toggleSavedView() {{
  showingSaved = !showingSaved;
  // Deliberately asymmetric. Entering clears the pills, because a saved list is
  // a handful of dogs and leaving filters applied behind a bar we've just hidden
  // would silently shorten it with nothing on screen to explain the gap. Leaving
  // puts them back, because the pills return to view in the same motion — a
  // filter vanishing while you're looking straight at the controls for it is the
  // worse surprise, and it costs someone their place in a 224-dog list.
  if (showingSaved) {{
    stashedFilters = {{...FILTERS, fosterOnly}};
    resetFilters();
  }} else if (stashedFilters) {{
    FILTERS.breed = stashedFilters.breed;
    FILTERS.sex = stashedFilters.sex;
    FILTERS.age = stashedFilters.age;
    FILTERS.size = stashedFilters.size;
    fosterOnly = stashedFilters.fosterOnly;
    stashedFilters = null;
  }}
  const bar = document.getElementById('filter-bar');
  if (bar) bar.hidden = !showingSaved;
  const fbar = document.getElementById('fbar');
  if (fbar) fbar.hidden = showingSaved;
  // Keep the big footer signup for the main feed only.
  const sec = document.getElementById('subscribe');
  if (sec) sec.style.display = showingSaved ? 'none' : '';
  const faq = document.querySelector('.faq');
  if (faq) faq.style.display = showingSaved ? 'none' : '';
  const chip = document.getElementById('saved-chip');
  if (chip) chip.classList.toggle('active', showingSaved);
  applyView();
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}

buildFilterMenus();
document.querySelectorAll('.fpill').forEach(pill => {{
  const trigger = pill.querySelector('button');
  const menu = menuOf(pill);
  if (!trigger || !menu) return;
  trigger.addEventListener('click', e => {{
    e.stopPropagation();
    const open = pill.classList.contains('open');
    closeFilterMenus();
    if (open) return;
    menu.hidden = false;
    const r = trigger.getBoundingClientRect();
    const phone = window.matchMedia('(max-width:680px)').matches;
    if (phone) {{
      // Out of the pill and into the body-level layer. The row it came from
      // scrolls sideways, and WebKit clips a fixed child to a scrolling
      // ancestor — the whole reason the menus kept "opening behind the dogs".
      openMenuInLayer(pill, menu);
      // Fixed, so the top is measured rather than inherited. Left and right come
      // from the mobile stylesheet: a full-width sheet, because a menu anchored
      // to the last pill would otherwise open off the edge of the screen.
      menu.style.top = (r.bottom + 10) + 'px';
      menu.style.left = '';
    }} else {{
      // Desktop keeps it in the pill, where absolute positioning under the
      // trigger is simplest and the row does not scroll, so nothing clips.
      returnMenuHome(menu);
      menu.style.top = '';
      menu.style.left = '';
    }}
    requestAnimationFrame(() => {{
      pill.classList.add('open');
      menu.classList.add('open');
      paintPillFade();
    }});
    trigger.setAttribute('aria-expanded', 'true');
  }});
  menu.addEventListener('click', e => {{
    const opt = e.target.closest('button');
    if (!opt || opt.disabled) return;
    e.stopPropagation();
    if (pill.dataset.sort) {{
      sortBy = opt.dataset.v;
      applySort();
    }} else {{
      FILTERS[pill.dataset.kind] = opt.dataset.v;
    }}
    closeFilterMenus();
    applyView();
  }});
}});
const progPill = document.getElementById('f-program');
if (progPill) progPill.addEventListener('click', () => {{
  fosterOnly = !fosterOnly;
  applyView();
}});
// The only bulk reset on the page, and only in the one state that needs one:
// zero results is the single dead end where clearing pills one at a time isn't
// obviously the way out. Everywhere else each menu's "Any …" row does it.
const feClear = document.getElementById('fe-clear');
if (feClear) feClear.onclick = () => {{ resetFilters(); applyView(); }};
document.addEventListener('click', closeFilterMenus);
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeFilterMenus();
}});

const savedChip = document.getElementById('saved-chip');
if (savedChip) savedChip.onclick = toggleSavedView;
const seBrowse = document.getElementById('se-browse');
if (seBrowse) seBrowse.onclick = toggleSavedView;   // flip back to everything

// Share sheet on a phone, clipboard on a desktop. navigator.share is what puts
// the link into Messages or Mail in one tap, which is how somebody actually
// sends a list to themselves; clipboard is the fallback and the desktop path.
const fbCopy = document.getElementById('fb-copy');
if (fbCopy) fbCopy.onclick = async () => {{
  const url = savedLink();
  if (!url) return;
  // The label lives in its own span: writing to the button's textContent would
  // take the icon with it and never put it back.
  const label = fbCopy.querySelector('.fb-copy-t');
  const say = (msg) => {{
    if (!label) return;
    const was = label.textContent;
    label.textContent = msg;
    setTimeout(() => {{ label.textContent = was; }}, 2200);
  }};
  const n = savedSet().size;
  // Clipboard first, then the share sheet, and the order is the whole point.
  // Safari only allows a clipboard write while it still considers itself inside
  // the tap that started it, and `await navigator.share(...)` spends that: the
  // clipboard fallback after a share sheet the user dismisses is refused as not
  // user-initiated, so the one path that reliably fails is the one somebody
  // reaches by changing their mind. Writing first means the link is always taken
  // — cancelling the sheet still leaves it on the clipboard rather than nothing.
  let copied = false;
  try {{
    await navigator.clipboard.writeText(url);
    copied = true;
  }} catch (e) {{}}
  if (navigator.share) {{
    try {{
      await navigator.share({{title: 'LUVD', url,
        text: n === 1 ? 'A dog I saved on LUVD'
                      : `${{n}} dogs I saved on LUVD`}});
      return;
    }} catch (e) {{ if (e && e.name === 'AbortError') {{
      if (copied) say('Link copied');
      return;
    }} }}
  }}
  // No clipboard and no share sheet is an old browser or a page served over
  // plain http. Showing the link is the last honest option — they can select it.
  if (copied) {{ say('Link copied'); return; }}
  const urlEl = document.getElementById('fb-url');
  if (urlEl) {{ urlEl.hidden = false; urlEl.style.display = 'block'; }}
  say('Copy the link →');
}};

// Merges, never replaces. If somebody sent you their list, adopting it must not
// wipe the hearts you already had — so this adds, then leaves you in your own
// saved view looking at the combined list, with the ?saved= param dropped so a
// refresh doesn't put you back in somebody else's list.
const sbSave = document.getElementById('sb-save');
if (sbSave) sbSave.onclick = () => {{
  if (!sharedIds) return;
  const set = savedSet();
  DOGS.forEach(d => {{ if (sharedIds.has(d.id)) set.add(d.id); }});
  writeSaved(set);
  sharedIds = null;
  sharedAsked = 0;
  try {{ history.replaceState(null, '', location.pathname); }} catch (e) {{}}
  showingSaved = true;
  paintSaved();
  applyView();
  if (window.luvdCelebrate) window.luvdCelebrate('saved!');
}};

readSharedList();
paintSaved();
if (openSavedOnLoad) toggleSavedView(); else applyView();
// ---- logo easter egg --------------------------------------------------------
// Paws drift up while you hover; clicking sets off a burst, and the fifth click
// gets a woof. Purely decorative — nothing depends on it.
(() => {{
  const logo = document.querySelector('.brand-logo');
  const wrap = document.querySelector('.brand-wrap');
  if (!logo || !wrap) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const GLYPHS = ['🐾', '🐶', '❤️', '🦴', '🐕'];
  let drifting = null, clicks = 0;

  function spawn(opts) {{
    const o = opts || {{}};
    const el = document.createElement('span');
    el.className = 'egg';
    el.textContent = o.glyph || GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
    const spread = o.spread || 70;
    const dx = (Math.random() - .5) * spread * 2;
    const dy = o.up ? -(60 + Math.random() * 60) : (Math.random() - .5) * spread * 2 - 40;
    el.style.setProperty('--dx', dx.toFixed(1) + 'px');
    el.style.setProperty('--dy', dy.toFixed(1) + 'px');
    el.style.setProperty('--sc', (o.scale || (.8 + Math.random() * .7)).toFixed(2));
    el.style.setProperty('--rot', ((Math.random() - .5) * 120).toFixed(0) + 'deg');
    el.style.fontSize = ((o.size || 18) + Math.random() * 8).toFixed(0) + 'px';
    const dur = o.dur || (900 + Math.random() * 600);
    el.style.animation = `drift ${{dur}}ms cubic-bezier(.2,.7,.3,1) forwards`;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), dur + 60);
  }}

  logo.addEventListener('mouseenter', () => {{
    spawn({{up: true}});
    drifting = setInterval(() => spawn({{up: true}}), 320);
  }});
  logo.addEventListener('mouseleave', () => clearInterval(drifting));

  // Shared with the subscribe flow — signing up should feel like something.
  // A short beat, no particles — used for the smaller moment of saving a dog,
  // so it doesn't compete with the full subscribe celebration.
  window.luvdBeat = function () {{
    const nav = document.getElementById('nav-logo');
    const shown = (nav && getComputedStyle(nav).opacity === '1')
      ? nav.querySelector('img') : logo;
    if (!shown) return;
    shown.classList.remove('cheer');
    void shown.offsetWidth;
    shown.classList.add('cheer');
    setTimeout(() => shown.classList.remove('cheer'), 900);
  }};

  window.luvdCelebrate = function (msg) {{
    for (let i = 0; i < 22; i++) {{
      setTimeout(() => spawn({{spread: 150, size: 20, dur: 1250}}), i * 22);
    }}
    logo.classList.add('cheer');
    setTimeout(() => logo.classList.remove('cheer'), 900);
    if (msg) {{
      const w = document.createElement('div');
      w.className = 'woof';
      w.textContent = msg;
      wrap.appendChild(w);
      setTimeout(() => w.remove(), 1700);
    }}
  }};

  logo.addEventListener('click', () => {{
    setTimeout(openAbout, 260);      // let the burst read before the modal
    clicks++;
    for (let i = 0; i < 14; i++) {{
      setTimeout(() => spawn({{spread: 130, size: 20, dur: 1100}}), i * 26);
    }}
    if (clicks % 5 === 0) {{
      const w = document.createElement('div');
      w.className = 'woof';
      w.textContent = ['woof!', 'adopt me!', 'good human', 'borf'][
        Math.floor(Math.random() * 4)];
      wrap.appendChild(w);
      setTimeout(() => w.remove(), 1600);
    }}
  }});
}})();

document.getElementById('about-btn').onclick = openAbout;
{{ const _tl = document.getElementById('terms-link');
   if (_tl) _tl.onclick = openTerms;
   const _pl = document.getElementById('privacy-link');
   if (_pl) _pl.onclick = openPrivacy; }}
function openSubscribe() {{
  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="sub-modal">
      <img class="sub-logo" src="assets/luvd-logo.png" alt="LUVD">
      <h2>Never miss a good dog</h2>
      <p>One email when new dogs drop from top rescues in your favorite cities.</p>
      <form class="sub-form" id="m-sub-form">
        <input type="email" id="m-sub-email" placeholder="you@email.com" required
               autocomplete="email" aria-label="Email address">
        <button type="submit">Subscribe</button>
      </form>
      <fieldset class="sub-cities" id="m-sub-cities">
        <legend class="vh">Cities to hear about</legend>
        {msub_picks}
      </fieldset>
      <div class="sub-note" id="m-sub-note">Free. Unsubscribe anytime.</div>
    </div>`, 'narrow');
  setTimeout(() => document.getElementById('m-sub-email').focus(), 340);
  document.getElementById('m-sub-form').onsubmit = e =>
    handleSubscribe(e, 'm-sub-email', 'm-sub-note', 'm-sub-form');
}}

document.getElementById('sub-btn').onclick = openSubscribe;
scrim.onclick = e => {{ if (e.target === scrim) closeModal(); }};
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

// The paw burst and "good human!" are the confirmation — no success copy, no
// layout shift, field stays put for a second address. The one thing the
// animation can't do is reach a screen reader, so we announce it there.
function announce(msg) {{
  let el = document.getElementById('sr-live');
  if (!el) {{
    el = document.createElement('div');
    el.id = 'sr-live';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.className = 'sr-only';
    document.body.appendChild(el);
  }}
  el.textContent = msg;
}}

// Shared by the nav modal and the section at the bottom of the page.
// Which cities this form has ticked. The hero form has no checkboxes at all,
// so it falls back to the page's own city — the behaviour it always had.
function pickedCities(formId) {{
  const box = document.getElementById(
    formId === 'm-sub-form' ? 'm-sub-cities' : 'sub-cities');
  if (!box) return [CITY];
  const on = [...box.querySelectorAll('input[type=checkbox]:checked')]
    .map(i => i.value);
  return on.length ? on : [];
}}

async function handleSubscribe(e, emailId, noteId, formId) {{
  e.preventDefault();
  const email = document.getElementById(emailId).value.trim();
  const note = document.getElementById(noteId);
  if (!email) return;
  note.className = note.id === 'hero-note' ? 'hero-note' : 'sub-note';
  const picked = pickedCities(formId);
  if (!picked.length) {{
    // Nothing ticked is not a default — it is a question. Sending them the
    // page's city anyway would sign them up for a list they just unticked.
    note.textContent = 'Pick at least one city.';
    return;
  }}
  try {{
    const r = await fetch(SUBSCRIBE_URL, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{email: email, cities: picked, city: picked[0]}})
    }});
    if (!r.ok) throw new Error('bad status');
    // Restore the note to its resting copy — no "you're in" line at all.
    note.className = note.id === 'hero-note' ? 'hero-note' : 'sub-note';
    note.textContent = RESTING_NOTE[note.id] || '';
    document.getElementById(emailId).value = '';
    document.getElementById(emailId).blur();
    announce('Subscribed. New dogs will arrive by email each morning.');
    if (window.luvdCelebrate) window.luvdCelebrate('good human!');
    if (formId === 'm-sub-form') setTimeout(closeModal, 2200);
  }} catch (err) {{
    // Static hosting with no backend reachable — fall back to email.
    note.className = note.id === 'hero-note' ? 'hero-note' : 'sub-note';
    note.innerHTML = "Couldn't reach the server. " +
      '<a href="mailto:' + CONTACT + '?subject=Subscribe%20to%20LUVD&body=' +
      encodeURIComponent(email) + '">Email us to subscribe →</a>';
  }}
}}

document.getElementById('sub-form').onsubmit = e =>
  handleSubscribe(e, 'sub-email', 'sub-note', 'sub-form');

const heroForm = document.getElementById('hero-form');
if (heroForm) heroForm.onsubmit = e =>
  handleSubscribe(e, 'hero-email', 'hero-note', 'hero-form');
</script>
  <!-- Where an open filter menu lives. A direct child of <body> on purpose:
       every ancestor between a menu and the document used to be a chance to clip
       it, and one of them (the scrolling pill row) did exactly that on iOS twice.
       Nothing here scrolls, masks or transforms, so a fixed child cannot be cut
       off however the rest of the page is rebuilt. See openMenuInLayer(). -->
  <div class="fmenu-layer" id="fmenu-layer"></div>
</body>
</html>"""


# The wordmark's heart, shared by the save button and the score pins. One copy
# in Python because the per-dog page draws both server-side; the modal has its
# own copies in the script it builds in the browser.
_HEART_PATH = ("M12 21C8 18 3 14.6 3 9.6C3 6.4 5.1 4.4 7.4 4.4C9.5 4.4 11.1 6 "
               "12 8C12.9 6 14.5 4.4 16.6 4.4C18.9 4.4 21 6.4 21 9.6C21 14.6 "
               "16 18 12 21Z")

# Only what a full page needs on top of the city stylesheet it links. Everything
# that makes a dog *look* like a dog — the chips, the score pins, the size bands,
# the cost list, the action bar — is already in that stylesheet and is used here
# under the same class names, so there is nothing to keep in sync.
#
# What is genuinely different is the shell. In the modal the card is a floating
# overlay: `.modal` is capped at 88vh and `.m-scroll` is an inner scroller. On a
# page the page itself scrolls, so neither is used, and the few rules below
# stand in for them.
_DOG_PAGE_CSS = """
  /* Wider than the modal's 880px. The modal is a card floating over a grid and
     has to look like one; this is the whole page, so it can use the room. */
  .dpg{max-width:1040px;margin:0 auto;padding:0 18px 40px;}
  /* No overflow:hidden. It reads as the obvious way to clip the corners, and
     it silently breaks the sticky action bar below: an ancestor that is not
     `overflow:visible` becomes the bar's scroll container, and that container
     never scrolls, so the bar just sits at the end of the page. The children
     that could spill past a rounded corner clip themselves — .m-hero already
     does — and the bar carries the bottom radius itself. */
  .dpg-card{background:var(--surface);border-radius:26px;
    box-shadow:var(--shadow);}
  /* The site nav hides its logo until you scroll (nav.shrunk) and its buttons
     open modals. Neither applies here, so the header is its own small thing:
     a logo that goes home, and the same trip spelled out in words. */
  .dpg-top{max-width:1040px;margin:0 auto;padding:18px 18px 14px;
    display:flex;align-items:center;justify-content:space-between;gap:14px;}
  .dpg-logo{display:block;line-height:0;}
  .dpg-logo img{width:124px;height:auto;display:block;}
  .dpg-all{font-size:13.5px;font-weight:600;color:#fff;background:var(--accent);
    padding:8px 15px;border-radius:980px;text-decoration:none;white-space:nowrap;}
  .dpg-all:hover{opacity:.88;}
  /* In the modal the photo column is capped by the modal's own 88vh, so the
     right-hand panels set the height and the photo fills what is left. A page
     has no such cap, so a portrait photo drove the whole band instead — 700px
     of top section for 626px of content, and the leftover pooled as dead space
     under the last rating. Taking the image out of flow restores the modal's
     intent: the right column decides, the photo fills it. */
  .dpg-card .m-hero{min-height:180px;}
  /* And spread whatever slack is left through the four rows rather than
     letting it collect at the bottom of the panel. */
  .dpg-card .scores{justify-content:space-between;}
  /* The modal pins its action bar so the contact button is never scrolled out
     of reach. The same reasoning applies harder here, because a page is taller
     than a modal: it sticks to the bottom of the viewport while the card is on
     screen, and comes to rest at the end of the card. */
  .dpg-card .m-foot{border-radius:0 0 26px 26px;position:sticky;bottom:0;
    z-index:2;box-shadow:0 -6px 20px rgba(0,0,0,.05);}
  :root[data-theme="dark"] .dpg-card .m-foot{
    box-shadow:0 -6px 20px rgba(0,0,0,.35);}
  /* Compact enough that a pinned bar is not a banner: one row of buttons, and
     nothing else in it. */
  /* nowrap so a label can never become two lines: the bar's height is fixed
     by design and a wrap is what made it look like a banner. */
  .dpg-card .m-foot .cta{padding:11px 16px;font-size:14.5px;white-space:nowrap;}
  .dpg-terms{margin-top:20px;}
  .dpg-terms .act-note{margin-bottom:6px;}
  /* The modal's tabs stretch to fill an 880px card. Here they sit at the top
     of a 1040px page where two full-width buttons look like a form, so they
     shrink to their labels and stay left. */
  .dpg-card .dpg-tabs{display:inline-flex;margin-top:4px;}
  .dpg-card .dpg-tabs .tab{flex:0 0 auto;padding:7px 15px;font-size:12.5px;}
  .dpg-foot{max-width:1040px;margin:0 auto;padding:26px 18px 40px;
    text-align:center;color:var(--muted);font-size:13.5px;}
  .dpg-foot a{color:var(--muted);}
  @media (max-width:720px){
    .dpg{padding:0 0 30px;}
    .dpg-card{border-radius:0;box-shadow:none;}
    .dpg-card .m-foot{border-radius:0;}
    /* Side by side on a phone too: stacked, the two buttons alone were 88px of
       a bar that has to share an 812px screen with the dog. */
    .dpg-card .foot-row{grid-template-columns:1fr 1fr;gap:8px;}
    .dpg-card .m-foot .cta{padding:11px 10px;font-size:13.5px;}
    .dpg-top{padding:14px 16px 12px;}
    .dpg-logo img{width:108px;}
  }
"""


def _dp_other_cities(c) -> str:
    """The other live cities, linked from a dog page's foot.

    A dog page is the most-shared and most-linked page on the site, so it is the
    best place to hand authority to a city section — and a stranger who arrives
    on an LA dog from a text message has no other way to discover New York.
    """
    others = [cities.CITIES[k] for k in cities.live_codes() if k != c.code]
    return "".join(f' &middot; <a href="{o.path}">Dogs in {html.escape(o.short)}</a>'
                   for o in others)


def _dp_breed(d: Dog) -> str:
    """"Mixed breed" rather than "Unknown", which is what the field often says."""
    return (d.breed if d.breed and "unknown" not in d.breed.lower()
            else "Mixed breed")


def _dp_scores(d: Dog) -> str:
    """The four ratings as heart pins. Mirrors `bars()` in the page script.

    Same markup and same SCALE words, so the row reads identically whether it
    was built here or in the browser. The pins are rendered already `in` —
    `.sc-pin` is invisible until that class lands, and on a page with no script
    running they would otherwise be four empty tracks.
    """
    scores = getattr(d, "scores", None) or {}
    if not scores.get("energy"):
        return ""
    rows = []
    for key, s in SCALE.items():
        v = scores.get(key)
        if not v:
            continue
        pos = (v - 1) * 25
        lo = ' class="on"' if v == 1 else ""
        hi = ' class="on"' if v == 5 else ""
        word = html.escape(s["words"][v - 1])
        rows.append(
            f'<div class="sc">'
            f'<div class="sc-top"><span class="sc-ic">{s["icon"]}</span>'
            f'<span class="sc-lb">{html.escape(s["label"])}</span></div>'
            f'<div class="sc-track">'
            f'<span class="sc-pin in" data-p="{pos}" style="left:{pos}%"'
            f' role="img" aria-label="{html.escape(s["label"])}: {word}">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="{_HEART_PATH}"/></svg></span></div>'
            f'<div class="sc-ends"><span{lo}>{html.escape(s["words"][0])}</span>'
            f'<span{hi}>{html.escape(s["words"][4])}</span></div></div>')
    if not rows:
        return ""
    return ('<div class="scores"><div class="sc-hd">Good to know</div>'
            + "".join(rows) + "</div>")


def _dp_trait_lists(good: list, warn: list) -> str:
    """"What to expect" — greens then ambers. Mirrors `traitLists()`."""
    if not good and not warn:
        return ""
    items = "".join(
        f'<li class="{kind}"><i class="tl-ic">{icon}</i>'
        f'<span>{html.escape(t["text"])}</span></li>'
        for group, kind, icon in ((good, "good", "✓"), (warn, "warn", "!"))
        for t in group)
    return ('<div class="sc-block tlists"><div class="tl-hd">🐾 What to expect'
            f'</div><ul>{items}</ul></div>')


def _dp_size_cost(d: Dog, c) -> str:
    """Size outlook and monthly cost. Mirrors `sizeAndCost()`."""
    so = getattr(d, "size_outlook", None) or {}
    mc = getattr(d, "monthly_cost", None) or {}
    traits = getattr(d, "traits", None) or []
    good = [t for t in traits if t.get("kind") == "good"]
    warn = [t for t in traits if t.get("kind") == "caution"]
    tl = _dp_trait_lists(good, warn)
    if not so.get("line") and not mc.get("low") and not tl:
        return ""

    size_block = ""
    if so.get("line"):
        growing = so.get("status") == "growing"
        w = so.get("adult") or so.get("now")
        bands = (("Small", 0, 25), ("Medium", 25, 50),
                 ("Large", 50, 90), ("Giant", 90, 10 ** 9))
        scale = ""
        if w:
            idx = next((i for i, b in enumerate(bands)
                        if b[1] <= w < b[2]), len(bands) - 1)
            now_idx = (next((i for i, b in enumerate(bands)
                             if b[1] <= so["now"] < b[2]), -1)
                       if so.get("now") else -1)
            cells = "".join(
                f'<span class="szb{" on" if i == idx else ""}'
                f'{" from" if growing and i == now_idx and now_idx != idx else ""}">'
                f"<i></i><em>{b[0]}</em></span>"
                for i, b in enumerate(bands))
            cap = (f"Now {bands[now_idx][0].lower()}, growing into a "
                   f"{bands[idx][0].lower()} dog"
                   if growing and now_idx != idx and now_idx >= 0
                   else f"A {bands[idx][0].lower()} dog by weight")
            scale = (f'<div class="szscale">{cells}</div>'
                     f'<div class="szcap">{html.escape(cap)}</div>')
        bar = ""
        if so.get("now") and so.get("adult") and so["adult"] > so["now"]:
            pct = max(6, min(100, (so["now"] / so["adult"]) * 100))
            bar = (f'<div class="gw"><span style="width:{pct:.0f}%"></span></div>'
                   f'<div class="gw-l"><span>{round(so["now"])} lbs now</span>'
                   f'<span>~{round(so["adult"])} lbs grown</span></div>')
        size_block = (
            f'<div class="sc-block"><div class="tl-hd">'
            f'{"📈 Still growing" if growing else "📏 Full size"}</div>'
            f'<p>{html.escape(so["line"])}</p>{bar}{scale}</div>')

    cost_block = ""
    if mc.get("low"):
        rows = "".join(f"<li><span>{html.escape(it[0])}</span>"
                       f"<b>${it[1]}–{it[2]}</b></li>"
                       for it in (mc.get("items") or []))
        cost_block = (
            f'<div class="sc-block"><div class="tl-hd">💵 Typical monthly cost'
            f'</div><div class="cost-big">${mc["low"]}–{mc["high"]}'
            f"<span>/month</span></div>"
            f'<ul class="cost-list">{rows}</ul>'
            f'<p class="cost-note">A {html.escape(c.short)} estimate for a dog '
            f"this size and coat. Excludes the adoption fee and anything "
            f"unexpected.</p></div>")

    right = (1 if size_block else 0) + (1 if tl else 0)
    return (f'<div class="sizecost"><div class="sc-inner'
            f'{" one-right" if right == 1 else ""}">{cost_block}'
            f'<div class="sc-right">{size_block}{tl}</div></div></div>')


def _dp_panes(d: Dog, c, breed: str) -> str:
    """Breed guide and the rescue's own write-up. Mirrors `tabs()`.

    Both are on the page rather than behind tabs. Tabs need a click handler, and
    a crawler that never clicks should still get the write-up — it is the only
    text on the page the rescue actually wrote.
    """
    bi = getattr(d, "breed_info", None) or {}
    if d.description:
        bio = f'<p class="bio">{html.escape(d.description)}</p>'
    else:
        bio = (f'<p style="color:var(--muted)">{html.escape(d.source_label)} '
               f"hasn't posted a write-up for {html.escape(d.name)} yet — reach "
               f"out and they'll tell you all about them.</p>")
    if not bi.get("temperament"):
        return f'<div class="pane on" data-p="0">{bio}</div>'

    unknown = ("" if bi.get("known") else
               '<p style="color:var(--muted);font-size:14px;'
               'margin-bottom:15px;">This dog\'s breed isn\'t known, so here\'s '
               'general guidance for mixes.</p>')
    fr = bi.get("from_rescue") or {}

    def first_sentence(t: str) -> str:
        m = re.match(r"^[^.!?]+[.!?]", str(t))
        return (m.group(0) if m else str(t)).strip()

    def sect(icon: str, title: str, topic: str, generic: str) -> str:
        said = fr.get(topic)
        context = first_sentence(generic) if said else generic
        line = (f"<b>{html.escape(re.sub(r'[.]$', '', said))}.</b> "
                f"{html.escape(context)}" if said else html.escape(generic or ""))
        return f"<div class=\"fact\"><h4>{icon} {title}</h4><p>{line}</p></div>"

    guide = (f'<span class="breed-tag">{html.escape(bi.get("name", breed))}'
             f"</span>{unknown}"
             + sect("🧠", "Temperament", "temperament", bi.get("temperament", ""))
             + sect("🎾", "Exercise", "exercise", bi.get("exercise", ""))
             + sect("✂️", "Grooming", "grooming", bi.get("grooming", ""))
             + sect("🏙️", html.escape(c.apartment_label), "nyc", bi.get("nyc", "")))
    # Tabs, as in the modal: both write-ups are long, and stacking them made the
    # page a wall of copy.
    #
    # The rescue's write-up opens, where the modal opens the breed guide. On a
    # page that is deliberate. This is the URL people share, so it is where a
    # stranger meets this particular dog, and the rescue's own words are the
    # answer to why they clicked. They are also the only text on the page that
    # is unique to it: the breed guide is the same paragraphs on every dog of
    # that breed, and the write-up is truncated to 300 characters in the
    # JSON-LD, so leaving it in a hidden pane would be the one thing worth
    # indexing sitting behind `display:none`. Both panes ship in the HTML
    # either way — hidden, not omitted — so nothing is unreachable.
    return (f'<div class="tabs dpg-tabs">'
            f'<button class="tab on" data-t="0" type="button">'
            f'From {html.escape(d.source_label)}</button>'
            f'<button class="tab" data-t="1" type="button">Breed guide</button>'
            f'</div>'
            f'<div class="pane on" data-p="0">{bio}</div>'
            f'<div class="pane" data-p="1">{guide}</div>')


def _dp_action(d: Dog, site: str) -> dict:
    """Where the adopt button goes. Mirrors `contactAction()`.

    The email branch resolves to a real `mailto:` with the same prefilled
    message the modal composes, rather than the modal's contact sheet — a page
    with no script still has to be able to send someone to the rescue.

    `short` is what the pinned bar says. The modal's labels carry the dog's name
    ("Apply to adopt Timmy →"), which is right in a card you opened deliberately
    but wraps to two lines in half of a 375px bar — and "Contact NYC Second
    Chance Rescue →" wraps on any screen. The bar is two buttons beside the dog
    it belongs to, so naming it again buys nothing and costs the line.
    """
    contact = RESCUE_CONTACTS.get(d.source) or {}
    if getattr(d, "program", "") and d.program_label:
        return {"href": d.cta_url(),
                "label": f"Apply to {d.program_label.lower()} {d.name} →",
                "short": "Apply →",
                "note": d.program_note or "", "program": d.program_label}
    if contact.get("method") == "email" and contact.get("email"):
        age = (f" ({d.age}{', ' + d.sex if d.sex else ''})" if d.age else "")
        body = (
            f"Hi {d.source_label},\n\n"
            f"I'd like to adopt {d.name}{age}, who I found through LUVD.\n\n"
            f"Your listing: {d.url}\n"
            f"LUVD page: {site}{dog_path(d)}\n\n"
            f"A bit about me:\n• Name:\n• Neighborhood:\n"
            f"• Home (apartment/house, own or rent):\n"
            f"• Who lives with me (adults, kids, other pets):\n"
            f"• Experience with dogs:\n"
            f"• Typical hours the dog would be alone:\n\n"
            f"Could you let me know the next step?\n\nThank you!")
        href = (f"mailto:{contact['email']}"
                f"?subject={quote(f'Adoption inquiry: {d.name}')}"
                f"&body={quote(body)}")
        return {"href": href, "label": f"Email about {d.name} →",
                "short": "Email the rescue →", "note": "", "program": ""}
    if contact.get("apply_url"):
        return {"href": contact["apply_url"],
                "label": f"Apply to adopt {d.name} →",
                "short": "Apply to adopt →",
                "note": f"{d.source_label} asks for an application before they "
                        f"can talk about a dog.", "program": ""}
    return {"href": d.cta_url(), "label": f"Contact {d.source_label} →",
            "short": "Contact the rescue →", "note": "", "program": ""}


def _dp_siblings(d: Dog, siblings: List[Dog]) -> str:
    """More dogs from the same rescue, using the modal's `.sim` classes.

    Not the modal's "similar dogs": that scores against every dog in the city,
    and this renderer is handed one rescue's list. Dogs from the same rescue is
    a claim the page can actually support, and it is the link a visitor who
    likes this dog is most likely to want.
    """
    others = [o for o in siblings if o.id != d.id and o.photos][:4]
    if not others:
        return ""
    cards = "".join(
        f'<a class="sim-card" href="{html.escape(dog_path(o))}">'
        f'<img class="sim-ph" src="{html.escape(o.primary_photo())}"'
        f' alt="{html.escape(o.name)}" loading="lazy">'
        f'<div class="sim-nm">{html.escape(o.name)}</div>'
        f'<div class="sim-rs">{html.escape(o.source_label)}</div>'
        f'<div class="sim-why">{html.escape(_dp_breed(o))}</div>'
        f"</a>" for o in others)
    return (f'<div class="sim"><div class="sim-hd">More from '
            f'{html.escape(d.source_label)}</div>'
            f'<div class="sim-row">{cards}</div></div>')


# The pieces of the page script the per-dog page reuses, in dependency order.
# Marked with /*KIT:name*/ … /*KIT-END:name*/ comments in render()'s template and
# lifted out of the RENDERED page, where the braces are already single — slicing
# them from the source would mean un-doubling f-string braces by hand, which is
# how the dog page's CSS ended up empty once already.
#
# Comments are the whole mechanism on purpose: nothing about the city page moves,
# so extracting this cannot change what the city page does. What it buys is that
# the share modal on a dog page is the SAME code as the one in the grid's modal —
# the story canvas, the copy-link fallback, all of it — rather than a second
# implementation that would drift from it.
_SHARE_KIT = ("dom-esc", "slugfor", "dogurl", "showmodal", "closemodal",
              "story-consts", "proxied", "loadimg", "drawcover", "drawnophoto",
              "buildstory", "openshare")


def _share_kit_js(page_html: str, city_code: str) -> str:
    """The share kit, sliced out of a rendered city page."""
    out = []
    for name in _SHARE_KIT:
        open_tag, close_tag = f"/*KIT:{name}*/", f"/*KIT-END:{name}*/"
        i, j = page_html.find(open_tag), page_html.find(close_tag)
        if i < 0 or j < 0 or j < i:
            raise AssertionError(
                f"{city_code}: share kit piece {name!r} not found in the "
                f"rendered page. The dog pages load this file to open their "
                f"share modal, so a missing piece is a share button that "
                f"throws. Check the /*KIT:{name}*/ markers in render().")
        out.append(page_html[i + len(open_tag):j])
    js = "\n\n".join(out)
    for bad in ("/*KIT:", "/*KIT-END:"):
        if bad in js:
            raise AssertionError(f"{city_code}: nested {bad} marker in the kit")
    return ("// Generated from the city page — see page._share_kit_js.\n"
            "// Edit the /*KIT:*/ regions in page.py, never this file.\n"
            + js + "\n")


def _dog_page(d: Dog, site: str, today: date, css_href: str = "/app.css",
              share_href: str = "/share.js",
              siblings: List[Dog] = None) -> str:
    """A standalone, indexable page per dog — the same modules as the modal.

    Server-rendered rather than a hash route, because Google can't index
    fragments. The title leads with rescue and breed — nobody searches a dog's
    name, they search "muddy paws rescue dogs" or "chihuahua adoption nyc".

    It used to be a bare document with 1.5 KB of its own CSS, which was fine
    while it existed only to be crawled. It isn't: a shared LUVD link is a dog
    link, so this page is how most people meet the product, and it looked like a
    different website. It now links the city page's own stylesheet and builds the
    modal's modules — photo, chips, the four ratings, size, cost, what to expect,
    breed guide, the write-up, the adopt bar — under the same class names, so the
    two are styled by the same bytes rather than by two sets of rules that drift.
    """
    c = cities.resolve(getattr(d, "city", ""))
    facts = " · ".join(x for x in (d.age, d.sex, d.weight, d.location) if x)
    breed = _dp_breed(d)
    # "LUVD" alone carries no city, so the title says the city itself — this is
    # the page's only geographic signal, and "adoption ... nyc" is what people
    # search. Rescues whose own name says their city don't need it twice.
    # Whole words only: "LA" as a bare substring hides inside "Lab" and
    # "Playa", which would quietly strip the city out of a title that needs it.
    label_has_city = any(
        re.search(rf"\b{re.escape(alias)}\b", d.source_label.lower())
        for alias in c.aliases)
    where = "" if label_has_city else f" in {c.short}"
    headline = f"{d.name} — {breed} for adoption at {d.source_label}{where}"
    # Brand in the <title>, not in the share tags: og:site_name renders as its
    # own line above og:title, so repeating "LUVD" there says it twice and eats
    # width a dog's name and breed need. Same split as City.share_title.
    title = f"{headline} | LUVD"
    desc = (f"{d.name} is a {breed.lower()} available for adoption from "
            f"{d.source_label} in {c.name}."
            + (f" {facts}." if facts else "")
            + " See photos, temperament and how to apply.")
    photo = d.primary_photo()
    wd = waiting_days(d, today)

    # A graph rather than the bare Product it used to be, for the breadcrumb.
    # These pages are three clicks deep in a structure nothing declared: a dog
    # belongs to a rescue, and the rescue has its own page ranking for its own
    # name. Saying so gives the dog page a parent to inherit authority from, and
    # gives a search result the "luvd.com › Muddy Paws Rescue › Poof" trail
    # instead of a bare URL. Every hop is a page this run actually writes.
    city_url = f"{site}/" if c.path == "/" else f"{site}{c.path}"
    product = {
        "@type": "Product",
        "name": d.name,
        # Ties the dog to the site and the rescue's own entity. Without these
        # the deepest, most-shared pages on the site were three isolated nodes
        # — a crawler could read the dog but had nothing saying whose page it
        # was on or which organisation is placing the animal.
        "isPartOf": {"@id": f"{site}/#website"},
        "seller": {"@id": f"{site}/rescue/{rescue_slug(d)}#rescue"},
        "description": clean_meta(d.description) or desc,
        "category": f"Adoptable dog — {breed}",
        "brand": {"@type": "Organization", "name": d.source_label},
        "url": f"{site}{dog_path(d)}",
    }
    if photo:
        product["image"] = photo
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            product,
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1,
                     "name": f"Adopt a dog in {c.short}", "item": city_url},
                    {"@type": "ListItem", "position": 2,
                     "name": d.source_label,
                     "item": f"{site}/rescue/{rescue_slug(d)}"},
                    {"@type": "ListItem", "position": 3, "name": d.name},
                ],
            },
        ],
    }

    # ---- the card, module by module, same classes as the modal ---------------
    # Photos then clips, in one strip — the same carousel, not a second block.
    # A clip's thumbnail is a muted <video> at #t=0.1, so the browser paints the
    # clip's own first frame and there is no poster to generate server-side.
    photos = list(d.photos or [])
    clips = list(getattr(d, "videos", None) or [])
    tiles = [f'<img src="{html.escape(p)}" data-src="{html.escape(p)}"'
             f' data-kind="img" alt="" loading="lazy">' for p in photos]
    tiles += [f'<span class="th-v" data-src="{html.escape(v)}" data-kind="vid"'
              f' role="button" tabindex="0"'
              f' aria-label="Play video of {html.escape(d.name)}">'
              f'<video src="{html.escape(v)}#t=0.1" preload="metadata" muted'
              f' playsinline></video><i class="th-play"></i></span>'
              for v in clips]
    thumbs = ""
    if len(tiles) > 1:
        first = re.sub(r"^(<\w+)", r'\1 class="sel"', tiles[0], count=1)
        thumbs = '<div class="thumbs">' + first + "".join(tiles[1:]) + "</div>"
    media = ""
    if photo:
        media = (f'<div class="m-media"><div class="m-hero">'
                 f'<img id="hero" src="{html.escape(photo)}"'
                 f' alt="{html.escape(d.name)}, {html.escape(breed)}">'
                 f'<video id="hero-v" controls playsinline preload="metadata"'
                 f" hidden></video>"
                 f"</div>{thumbs}</div>")

    home = rescue_home(d.source)
    rescue_line = (
        f'<a class="m-rescue" href="{html.escape(home)}" target="_blank"'
        f' rel="noopener">{html.escape(d.source_label)}</a>' if home
        else f'<p class="m-rescue">{html.escape(d.source_label)}</p>')

    traits = getattr(d, "traits", None) or []
    chips = "".join([
        f'<span class="chip program">{html.escape(d.program_label)}</span>'
        if d.program_label else "",
        f'<span class="chip">{html.escape(d.breed)}</span>'
        if d.breed and "unknown" not in d.breed.lower() else "",
    ] + [f'<span class="chip">{html.escape(x)}</span>'
         for x in (d.age, d.sex, d.weight, d.location) if x]
      + ([f'<span class="chip wait">⏳ Listed {wd} days</span>']
         if wd is not None and wd >= WAIT_BADGE_DAYS else [])
      + [f'<span class="chip">{html.escape(t["text"])}</span>'
         for t in traits if t.get("kind") == "info"])

    idcol = (f'<div class="idcol"><div class="m-name-row">'
             f'<h1 class="m-name">{html.escape(d.name)}</h1>'
             f'<button class="save m-save" data-id="{html.escape(d.id)}"'
             f' type="button" aria-pressed="false"'
             f' aria-label="Save {html.escape(d.name)}">'
             f'<svg class="hrt" viewBox="0 0 24 24" aria-hidden="true">'
             f'<path d="{_HEART_PATH}"/></svg>'
             f'<span class="burst" aria-hidden="true"></span></button></div>'
             f'{rescue_line}<div class="chips">{chips}</div></div>')

    act = _dp_action(d, site)
    note = ""
    if act["note"]:
        note = (f'<div class="act-note{" prog" if act["program"] else ""}">'
                + (f'<b>{html.escape(act["program"])}.</b> '
                   if act["program"] else "")
                + html.escape(act["note"]) + "</div>")
    fee = (f'<div class="cta-sub">Adoption fee {html.escape(d.fee)}</div>'
           if d.fee else "")
    # What goes in the message body when someone shares this dog. json.dumps so
    # a name with a quote or an apostrophe can't break out of the string.
    share_text = json.dumps(
        f"{d.name} is up for adoption at {d.source_label} in {c.short} — "
        f"found on LUVD 🐶")
    # openShare() and buildStory() take a dog straight out of the page payload,
    # so this is the same dict the city page ships — to_dict() rather than a
    # hand-built object, so the share modal can never be handed a shape the grid
    # would not have handed it. `path` is what dogUrl() shares.
    dog_json = json.dumps(dict(d.to_dict(),
                               waiting_days=(wd or 0),
                               path=dog_path(d)), ensure_ascii=False)

    return f"""<!doctype html>
<html lang="en"><head>
{_theme_script(c)}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{site}{dog_path(d)}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.png" type="image/png">
<meta property="og:type" content="article">
<meta property="og:site_name" content="LUVD">
<meta property="og:title" content="{html.escape(headline)}">
<meta property="og:description" content="{html.escape(desc)}">
{f'<meta property="og:image" content="{html.escape(photo)}">' if photo else ''}
<meta property="og:url" content="{html.escape(site + dog_path(d))}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{html.escape(headline)}">
<meta name="twitter:description" content="{html.escape(desc)}">
{f'<meta name="twitter:image" content="{html.escape(photo)}">' if photo else ''}
<script type="application/ld+json">{json.dumps(ld)}</script>
<!-- The city page's own stylesheet, linked rather than inlined: it is 78 KB and
     identical across every dog page, so linking it means one download for a
     visitor who opens two dogs, and one place where the styling is defined. -->
<link rel="stylesheet" href="{html.escape(css_href)}">
<style>{_DOG_PAGE_CSS}</style>
</head><body>
<div class="dpg-top">
  <a class="dpg-logo" href="{c.path}" aria-label="LUVD — every adoptable dog in {c.short}">
    <img src="/assets/luvd-logo.png" alt="LUVD" width="1400" height="607"></a>
  <a class="dpg-all" href="{c.path}">View {c.short} Dogs</a>
</div>
<main class="dpg">
  <div class="dpg-card">
    <div class="m-body">
      <div class="topgrid{' with-photo' if photo else ''}">
        {media}
        {idcol}
        {_dp_scores(d)}
      </div>
      {_dp_size_cost(d, c)}
      {_dp_panes(d, c, breed)}
      <div class="cta-sub" style="margin-top:18px;">
        <a href="{html.escape(d.url)}" target="_blank" rel="noopener">View original listing</a></div>
      {_dp_siblings(d, siblings or [])}
      <!-- What applying involves, and what it costs. Context rather than
           action, so it reads here at the end of the body instead of riding
           along inside a bar that is pinned to the viewport — where it was
           37px and 19px of a 190px bar on a phone, for two lines nobody needs
           in front of them the whole way down the page. -->
      <div class="dpg-terms">{note}{fee}</div>
    </div>
    <div class="m-foot">
      <div class="foot-row">
        <a class="cta" href="{html.escape(act['href'])}" target="_blank"
           rel="noopener">{html.escape(act['short'])}</a>
        <button class="cta cta2" id="share-btn" type="button">
          <svg class="shr-ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 15V3M12 3 8.5 6.5M12 3l3.5 3.5"/>
            <path d="M4.5 13.5v4.75A1.75 1.75 0 0 0 6.25 20h11.5a1.75 1.75 0
                     0 0 1.75-1.75V13.5"/>
          </svg><span id="share-t">Share</span></button>
      </div>
    </div>
  </div>
</main>
<!-- The modal shell the share kit writes into. Same ids and classes the city
     page uses, because it is the city page's own showModal() doing the writing. -->
<div class="scrim" id="scrim"><div class="modal" id="modal"></div></div>
<div class="dpg-foot">
  <a href="{c.path}">Every adoptable dog in {c.short}, updated every morning</a>
  &middot; <a href="{c.rescues_path}">All {c.short} rescues</a>
  {_dp_other_cities(c)}
</div>
<script src="{share_href}"></script>
<script>
var SHARE_TEXT = {share_text};
var DOG = {dog_json};
// A few small jobs, all of which the stylesheet already assumes someone does.
(function () {{
  // 1. The score pins. `.sc-pin` is invisible until `.in` lands; they ship WITH
  //    it so the page is right with no script at all, and this only takes it
  //    away for a frame to replay the same staggered pop-in the modal does.
  //    The remove happens INSIDE the rAF callback, never before it: a tab that
  //    loads in the background has rAF suspended, and taking the class off
  //    first would leave four empty tracks until the tab was looked at.
  var pins = document.querySelectorAll('.sc-pin');
  requestAnimationFrame(function () {{
    pins.forEach(function (p, i) {{
      p.classList.remove('in');
      setTimeout(function () {{ p.classList.add('in'); }}, 40 + i * 70);
    }});
  }});

  // 2. The heart, against the same localStorage key the grid and the saved
  //    list use — so hearting a dog here shows up on the city page, which is
  //    the whole reason to offer the button rather than a picture of one.
  var KEY = 'luvd:saved';
  function read() {{
    try {{ return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); }}
    catch (e) {{ return new Set(); }}
  }}
  var btn = document.querySelector('.m-save');
  if (!btn) return;
  var id = btn.dataset.id;
  function paint() {{
    var on = read().has(id);
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }}
  btn.addEventListener('click', function () {{
    var set = read();
    if (set.has(id)) set.delete(id); else {{ set.add(id); btn.classList.add('pop'); }}
    try {{ localStorage.setItem(KEY, JSON.stringify([].concat(Array.from(set)))); }}
    catch (e) {{}}
    paint();
    setTimeout(function () {{ btn.classList.remove('pop'); }}, 600);
  }});
  paint();

  // 3. The two write-up tabs, same behaviour as the modal's.
  var tabs = document.querySelectorAll('.dpg-tabs .tab');
  tabs.forEach(function (tb) {{
    tb.addEventListener('click', function () {{
      tabs.forEach(function (o) {{ o.classList.remove('on'); }});
      document.querySelectorAll('.pane').forEach(function (o) {{
        o.classList.remove('on');
      }});
      tb.classList.add('on');
      var pane = document.querySelector('.pane[data-p="' + tb.dataset.t + '"]');
      if (pane) pane.classList.add('on');
    }});
  }});

  // 4. Share opens the real thing — openShare() out of share.js, which is the
  //    city page's own function, so the story card and the copy-link fallback
  //    are the same code rather than a second version of it.
  var share = document.getElementById('share-btn');
  if (share) share.addEventListener('click', function () {{
    if (typeof openShare === 'function') openShare(DOG);
  }});
  // Closing it: the scrim's backdrop and Escape. The kit wires the ✕ itself.
  var scrimEl = document.getElementById('scrim');
  if (scrimEl) scrimEl.addEventListener('click', function (e) {{
    if (e.target === scrimEl && typeof closeModal === 'function') closeModal(true);
  }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape' && scrimEl && scrimEl.classList.contains('on')
        && typeof closeModal === 'function') closeModal(true);
  }});

  // 5. The carousel, same behaviour as the modal's: a photo swaps the <img>,
  //    a clip reveals the <video> in the same box, and picking anything else
  //    stops whatever was playing.
  var heroImg = document.getElementById('hero');
  var heroVid = document.getElementById('hero-v');
  var tiles = document.querySelectorAll('.thumbs [data-kind]');
  function pickTile(t) {{
    tiles.forEach(function (o) {{ o.classList.remove('sel'); }});
    t.classList.add('sel');
    if (!heroImg || !heroVid) return;
    if (t.dataset.kind === 'vid') {{
      heroVid.src = t.dataset.src;
      heroVid.hidden = false; heroImg.hidden = true;
      var p = heroVid.play();
      if (p && p.catch) p.catch(function () {{}});
    }} else {{
      heroVid.pause(); heroVid.removeAttribute('src'); heroVid.load();
      heroVid.hidden = true; heroImg.hidden = false;
      heroImg.src = t.dataset.src;
    }}
  }}
  tiles.forEach(function (t) {{
    t.addEventListener('click', function () {{ pickTile(t); }});
    t.addEventListener('keydown', function (e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); pickTile(t); }}
    }});
  }});
}})();
</script>
</body></html>"""


def _shelter_ld(label: str, source: str, site: str, slug: str,
                city: str = None) -> dict:
    """The rescue as an entity, not just a page heading.

    AnimalShelter is the closest schema.org type to a foster-based rescue,
    and being specific is what lets an answer engine treat these as
    organizations rather than list items. ``url`` points at the rescue's own
    site because that's the canonical home of the entity — our page describes
    it, which is what the CollectionPage ``about`` below says.
    """
    contact = RESCUE_CONTACTS.get(source) or {}
    home = rescue_home(source)
    node = {
        "@type": "AnimalShelter",
        "@id": f"{site}/rescue/{slug}#rescue",
        "name": label,
        "url": home or f"{site}/rescue/{slug}",
        "areaServed": {"@type": "City", "name": cities.resolve(city).name},
    }
    if home:
        node["sameAs"] = home
    if contact.get("email"):
        node["email"] = contact["email"]
    return node


def _rescue_structured_data(label: str, source: str, dogs: List[Dog],
                            site: str, slug: str, desc: str) -> dict:
    items = [
        {
            "@type": "ListItem",
            "position": i,
            "url": f"{site}{dog_path(d)}",
            "name": d.name,
        }
        for i, d in enumerate(dogs[:60], 1)
    ]
    c = cities.resolve(_city_of(dogs))
    home_url = f"{site}/" if c.path == "/" else f"{site}{c.path}"
    # city → that city's rescue index → this rescue. The middle step is the
    # city's own index, so the trail never routes a visitor through another
    # city's list.
    crumbs = [
        {"@type": "ListItem", "position": 1,
         "name": f"Adopt a dog in {c.short}", "item": home_url},
        {"@type": "ListItem", "position": 2, "name": f"{c.short} dog rescues",
         "item": f"{site}{c.rescues_path}"},
        {"@type": "ListItem", "position": 3, "name": label},
    ]
    return {
        "@context": "https://schema.org",
        "@graph": [
            _shelter_ld(label, source, site, slug, c.code),
            {
                "@type": "CollectionPage",
                "@id": f"{site}/rescue/{slug}",
                "url": f"{site}/rescue/{slug}",
                "name": f"{label} — adoptable dogs in {c.short}",
                "description": desc,
                "isPartOf": {"@id": f"{site}/#website"},
                "publisher": {"@id": f"{site}/#org"},
                "about": {"@id": f"{site}/rescue/{slug}#rescue"},
                "mainEntity": {
                    "@type": "ItemList",
                    "name": f"Dogs available for adoption from {label}",
                    "numberOfItems": len(dogs),
                    "itemListElement": items,
                },
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": crumbs,
            },
        ],
    }


def _rescue_page(label: str, dogs: List[Dog], site: str) -> str:
    """One page per rescue — "muddy paws rescue dogs" is a real search."""
    slug = slugify(label)
    source = dogs[0].source if dogs else ""
    c = cities.resolve(_city_of(dogs))
    title = f"{label} — adoptable dogs in {c.short} | LUVD"
    n = len(dogs)
    desc = (f"All {n} dog{'' if n == 1 else 's'} currently available for "
            f"adoption from {label} in {c.name}, updated daily.")
    rows = "".join(
        f'<li><a href="{html.escape(dog_path(d))}">{html.escape(d.name)}</a>'
        f'<span class="b"> — {html.escape(d.breed or "Mixed breed")}'
        f'{" · " + html.escape(d.age) if d.age else ""}</span></li>'
        for d in dogs
    )
    home = rescue_home(source)
    # The outbound link belongs here rather than in the site-wide footer: it's
    # useful in context, and it's the link that ties our page to the real
    # organization.
    out = (f'<a class="out" href="{html.escape(home)}" target="_blank"'
           f' rel="noopener">Visit {html.escape(label)}&rsquo;s own site &rarr;</a>'
           if home else "")
    # Every city has its own index, so this always points at the one for the
    # city this rescue is in — never at another city's list.
    rescues_link = (f'<a href="{c.rescues_path}">All {c.short} rescues on LUVD'
                    f'</a> &middot;')
    ld = json.dumps(_rescue_structured_data(label, source, dogs, site, slug, desc))
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{site}/rescue/{slug}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.png" type="image/png">
<script type="application/ld+json">{ld}</script>
<style>{_STATIC_PAGE_CSS}</style></head><body>
<a class="back" href="{c.path}">&larr; All adoptable dogs in {c.short}</a>
<h1>{html.escape(label)}</h1>
<p class="lead">{html.escape(desc)}</p>
{out}
<ul class="dogs">{rows}</ul>
<footer>
  {rescues_link}
  <a href="{c.path}">Today&rsquo;s new dogs</a>
</footer>
</body></html>"""


def _rescues_page(by_rescue: dict, site: str, for_date: date,
                  city: str = None) -> str:
    """One city's rescue index — a page that answers "which dog rescues are in LA?".

    A footer list can't rank for that and can't be cited; a page with the roster,
    each rescue's dog count and a link to their own site can. It also gives that
    city's rescue pages a single hub to be linked from.

    One page per city rather than a combined one. The question is local, so the
    page that answers it should be too: a single page covering everywhere could
    only be titled something like "Dog rescues in NYC and LA", which competes
    with itself and reads as a worse answer to either question than a dedicated
    page does. See `City.rescues_path`. The cross-links at the foot are what
    give a visitor the whole-site view without asking one page to carry it.
    """
    c = cities.resolve(city)
    labels = sorted(by_rescue)
    total = sum(len(v) for v in by_rescue.values())
    title = f"{c.short} dog rescues — every rescue LUVD tracks | LUVD"
    desc = (f"The {len(labels)} {c.name} dog rescues LUVD checks every "
            f"morning, with all {total} of their adoptable dogs in one place.")
    # The meta description above already says what LUVD does with them, so the
    # on-page lead adds the part a visitor needs instead of repeating it.
    intro = ("Every adoption is handled by the rescue itself &mdash; LUVD just "
             "helps you find the dog.")

    cards = []
    for label in labels:
        dogs = by_rescue[label]
        slug = slugify(label)
        source = dogs[0].source if dogs else ""
        home = rescue_home(source)
        n = len(dogs)
        links = [f'<a href="/rescue/{slug}">See all {n} dog'
                 f'{"" if n == 1 else "s"}</a>']
        if home:
            links.append(f'<a href="{html.escape(home)}" target="_blank"'
                         f' rel="noopener">{html.escape(urlsplit(home).netloc)}</a>')
        cards.append(
            f'<div class="card"><h2><a href="/rescue/{slug}">'
            f'{html.escape(label)}</a></h2>'
            f'<p class="meta">{n} dog{"" if n == 1 else "s"} available today'
            f' &middot; {html.escape(c.name)}</p>'
            f'<p class="links">{" &middot; ".join(links)}</p></div>'
        )

    # The other live cities' indexes. Every live city gets one, so this set is
    # stable and the links can't point at a page that was never written.
    #
    # These are the only links in the foot. There was a "Today's new dogs" here
    # too, pointing at the same place as the "All adoptable dogs in NYC" link at
    # the top of the page — the same destination twice, so it earned nothing.
    others = [cities.CITIES[k] for k in cities.live_codes() if k != c.code]
    also = " &middot; ".join(
        f'<a href="{o.rescues_path}">Also in {html.escape(o.name)} &rarr;</a>'
        for o in others)
    foot = f"\n<footer>{also}</footer>" if also else ""

    # A city mid-launch can have no rescues yet. Keep the page — the city page's
    # footer links to it — but don't ask Google to index an empty roster, and
    # (in write()) don't submit it in the sitemap either.
    robots = "" if labels else '\n<meta name="robots" content="noindex,follow">'

    ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "@id": f"{site}{c.rescues_path}",
                "url": f"{site}{c.rescues_path}",
                "name": f"{c.short} dog rescues on LUVD",
                "description": desc,
                "isPartOf": {"@id": f"{site}/#website"},
                "publisher": {"@id": f"{site}/#org"},
                "dateModified": for_date.isoformat(),
                "mainEntity": {
                    "@type": "ItemList",
                    "name": f"Dog rescues in {c.name}",
                    "numberOfItems": len(labels),
                    "itemListElement": [
                        {"@type": "ListItem", "position": i,
                         "url": f"{site}/rescue/{slugify(label)}",
                         "item": _shelter_ld(
                             label,
                             by_rescue[label][0].source if by_rescue[label] else "",
                             site, slugify(label), c.code)}
                        for i, label in enumerate(labels, 1)
                    ],
                },
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1,
                     "name": f"Adopt a dog in {c.short}",
                     "item": f"{site}/" if c.path == "/" else f"{site}{c.path}"},
                    {"@type": "ListItem", "position": 2,
                     "name": f"{c.short} dog rescues"},
                ],
            },
        ],
    })
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{robots}
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{site}{c.rescues_path}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.png" type="image/png">
<script type="application/ld+json">{ld}</script>
<style>{_STATIC_PAGE_CSS}</style></head><body>
<a class="back" href="{c.path}">&larr; All adoptable dogs in {c.short}</a>
<h1>{c.short} dog rescues</h1>
<p class="lead">{html.escape(desc)} {intro}</p>
{''.join(cards)}{foot}
</body></html>"""


def clean_meta(t: str, limit: int = 300) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t[:limit]


def _not_found_page(dogs: List[Dog], site: str) -> str:
    """404 for dogs that have left the listings.

    Most of these URLs die because the dog was adopted — so the page leads with
    that rather than an error. It stops short of claiming any specific dog found
    a home, because a listing can also be pulled, transferred, or the dog can
    have died, and we have no way to tell which.
    """
    picks = [d for d in dogs if d.photos][:4]
    tiles = "".join(
        f'<a class="nf-dog" href="{html.escape(dog_path(d))}">'
        f'<img src="{html.escape(d.primary_photo())}" alt="{html.escape(d.name)}"'
        f' loading="lazy"><span>{html.escape(d.name)}</span></a>'
        for d in picks
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>This dog has moved on — LUVD</title>
<meta name="robots" content="noindex">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.png" type="image/png">
<style>
  :root{{--bg:#fbfbfd;--surface:#fff;--text:#1d1d1f;--muted:#6e6e73;
    --accent:#FF002E;--hair:rgba(0,0,0,.08);}}
  @media (prefers-color-scheme:dark){{:root{{--bg:#000;--surface:#1c1c1e;
    --text:#f5f5f7;--muted:#98989d;--hair:rgba(255,255,255,.13);}}}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--bg);color:var(--text);min-height:100vh;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    text-align:center;padding:40px 20px;overflow-x:hidden;
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",
    Roboto,sans-serif;}}
  .nf-logo{{width:min(210px,52vw);margin-bottom:26px;
    animation:drop .7s cubic-bezier(.34,1.5,.5,1) both;}}
  @keyframes drop{{from{{transform:translateY(-26px) scale(.9);opacity:0;}}
    to{{transform:none;opacity:1;}}}}
  h1{{font-size:clamp(30px,5vw,46px);letter-spacing:-.03em;margin:0 0 12px;
    line-height:1.1;animation:up .55s cubic-bezier(.2,.8,.25,1) .12s both;}}
  p.lead{{color:var(--muted);font-size:17px;max-width:430px;margin:0 0 30px;
    line-height:1.55;animation:up .55s cubic-bezier(.2,.8,.25,1) .2s both;}}
  @keyframes up{{from{{transform:translateY(12px);opacity:0;}}
    to{{transform:none;opacity:1;}}}}
  .cta{{display:inline-block;background:var(--accent);color:#fff;
    text-decoration:none;padding:15px 26px;border-radius:14px;font-weight:600;
    font-size:16.5px;animation:up .55s cubic-bezier(.2,.8,.25,1) .28s both;}}
  .nf-row{{display:flex;gap:12px;margin-top:44px;flex-wrap:wrap;
    justify-content:center;animation:up .6s cubic-bezier(.2,.8,.25,1) .36s both;}}
  .nf-dog{{text-decoration:none;color:var(--muted);font-size:12.5px;width:96px;
    transition:transform .25s cubic-bezier(.2,.8,.2,1);}}
  .nf-dog:hover{{transform:translateY(-5px);}}
  .nf-dog img{{width:96px;height:96px;object-fit:cover;border-radius:14px;
    display:block;margin-bottom:7px;}}
  .nf-hd{{font-size:11px;font-weight:700;letter-spacing:.09em;
    text-transform:uppercase;color:var(--muted);margin-top:44px;
    animation:up .6s cubic-bezier(.2,.8,.25,1) .32s both;}}
  /* Paws wander across the footer — the dog walked off, that's the joke. */
  .paws{{position:fixed;bottom:26px;left:0;width:100%;pointer-events:none;
    display:flex;gap:44px;justify-content:center;opacity:.28;}}
  .paws span{{font-size:22px;animation:trot 2.6s ease-in-out infinite;}}
  .paws span:nth-child(2){{animation-delay:.22s;}}
  .paws span:nth-child(3){{animation-delay:.44s;}}
  .paws span:nth-child(4){{animation-delay:.66s;}}
  .paws span:nth-child(5){{animation-delay:.88s;}}
  @keyframes trot{{0%,100%{{transform:translateY(0) rotate(-8deg);opacity:.3;}}
    50%{{transform:translateY(-11px) rotate(8deg);opacity:1;}}}}
  @media (prefers-reduced-motion:reduce){{
    .nf-logo,h1,p.lead,.cta,.nf-row,.nf-hd{{animation:none;}}
    .paws span{{animation:none;}}
  }}
</style></head>
<body>
  <img class="nf-logo" src="/assets/luvd-logo.png" alt="LUVD">
  <h1>This pup has moved on</h1>
  <p class="lead">This listing is gone — which usually means they found their
     person. Plenty of others are still waiting.</p>
  <a class="cta" href="/">See dogs available today →</a>
  {f'<div class="nf-hd">Still looking</div><div class="nf-row">{tiles}</div>' if tiles else ''}
  <div class="paws" aria-hidden="true">
    <span>🐾</span><span>🐾</span><span>🐾</span><span>🐾</span><span>🐾</span>
  </div>
</body></html>"""


def _owned_slugs(by_city: dict) -> set:
    """Every rescue slug belonging to the cities in this pass.

    From the registry rather than from the dogs on hand, so it covers a rescue
    that returned nothing this morning as well as one that returned fifty.
    """
    from sources.registry import sources_for_city
    slugs = set()
    for code in by_city:
        for source in sources_for_city(code):
            slugs.add(slugify(source.label))
    # A rescue in the roster that the registry doesn't know about — a source
    # renamed between runs — would otherwise keep its old pages forever.
    for dated in by_city.values():
        for _, group in (dated or ()):
            for d in group:
                slugs.add(rescue_slug(d))
    return slugs


def _carried_sitemap_urls(site: str, owned: set, written_paths: set) -> list:
    """URLs from the previous sitemap that this pass is not responsible for.

    A city left out because its scrapers failed still exists and is still
    serving, so its URLs have to stay in the sitemap. Dropping them would tell
    Google that half the site had been removed, on the strength of one bad
    morning at one rescue.
    """
    previous = OUT_DIR / "sitemap.xml"
    if not previous.exists():
        return []
    try:
        raw = previous.read_text(encoding="utf-8")
    except OSError:
        return []
    keep = []
    for url in re.findall(r"<loc>(.*?)</loc>", raw):
        url = html.unescape(url)
        # Only URLs on this site. Anything else is a leftover from a different
        # SITE_URL — a local render, a staging host — and republishing it would
        # put another origin's URLs in this site's sitemap and keep them there
        # for good, since every later run would carry them again.
        if not url.startswith(site + "/"):
            continue
        path = url[len(site):]
        if path in written_paths:
            continue
        slug = ""
        if path.startswith("/dog/"):
            slug = path.split("/")[2] if len(path.split("/")) > 2 else ""
        elif path.startswith("/rescue/"):
            slug = path[len("/rescue/"):]
        if slug and slug in owned:
            continue                      # this pass has rewritten it, or dropped it
        keep.append(url)
    return keep


def write(pages, for_date: date = None) -> Path:
    """Publish every city in ONE pass. `pages` is {city_code: dated}.

    One pass is not a convenience, it is the requirement. `public/dog/` and
    `public/rescue/` are trees shared by every city and they are cleared here, so
    that adopted dogs stop returning 200 with a stale listing. Calling this once
    per city would therefore have each city delete the previous city's dog pages
    — and each call would publish a `sitemap.xml` describing only its own half of
    the site, telling Google the other half had ceased to exist.

    So: the shared work happens exactly once, from the union of every city. The
    per-city work — the city's own page, its dogs' pages, its rescues' pages —
    happens per city, after the single clear.

    Only the cities actually passed in are touched. A city whose scrapers all
    failed is left out by its caller, and then nothing here can delete its pages
    or drop its URLs from the sitemap — the point being that one city's bad
    morning must not be able to take the other city's page down with it.

    A bare `dated` list is still accepted and means the default city, so any
    caller written before cities keeps working.
    """
    for_date = for_date or date.today()
    site = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
    if isinstance(pages, dict):
        by_city = {cities.canon(k) or cities.DEFAULT_CITY: v
                   for k, v in pages.items()}
    else:
        by_city = {cities.DEFAULT_CITY: pages}
    OUT_DIR.mkdir(exist_ok=True)

    # Clear the stale dog and rescue pages of the cities being written, and only
    # those. Scoped per rescue rather than by deleting public/dog/ wholesale,
    # because that tree is shared: wiping it would delete the other city's pages,
    # and it is exactly the kind of deletion that looks fine until the morning a
    # city is missing from the site.
    #
    # Taken from the registry, not from today's dogs, so a rescue that listed
    # nothing this morning still has its old pages cleared — that is the original
    # job of the clear, stopping an adopted dog from answering 200 forever.
    owned = _owned_slugs(by_city)
    for slug in owned:
        d = OUT_DIR / "dog" / slug
        if d.exists():
            shutil.rmtree(d)
        r = OUT_DIR / "rescue" / f"{slug}.html"
        if r.exists():
            r.unlink()
    rdir = OUT_DIR / "rescue"
    rdir.mkdir(parents=True, exist_ok=True)

    primary, first_written = None, None
    all_flat, urls, per_city = [], [], []
    # Every path this pass rendered, including the ones deliberately kept out of
    # the sitemap. `urls` alone is not enough: a page withheld because it is
    # noindex is also absent from `written_paths`, so the carry-over would find
    # it in the previous sitemap and put it straight back — resubmitting the one
    # page we just decided not to submit.
    rendered = set()
    for code, dated in by_city.items():
        c = cities.resolve(code)
        out = OUT_DIR / c.file
        page_html = render(dated, for_date, c.code)
        out.write_text(page_html, encoding="utf-8")
        rendered.add(c.path)

        # The city page's stylesheet, written out so the per-dog pages can link
        # it instead of carrying their own. Lifted from the page just rendered
        # rather than kept as a separate constant: it lives inside render()'s
        # template, and a second copy is exactly how the dog pages came to look
        # like a different website. 78 KB inlined into 372 dog pages would also
        # be 29 MB of identical bytes and a 78 KB download per shared link.
        css_href = "/app.css" if c.path == "/" else f"{c.path}/app.css"
        css_file = OUT_DIR / css_href.lstrip("/")
        css_file.parent.mkdir(parents=True, exist_ok=True)
        sheets = re.findall(r"<style>(.*?)</style>", page_html, re.S)
        if len(sheets) != 1:
            raise AssertionError(
                f"{c.code}: expected one <style> block in the city page, found "
                f"{len(sheets)} — the dog pages link this file, so a second "
                f"block would silently ship them half a stylesheet.")
        css_file.write_text(sheets[0], encoding="utf-8")
        rendered.add(css_href)

        share_href = "/share.js" if c.path == "/" else f"{c.path}/share.js"
        (OUT_DIR / share_href.lstrip("/")).write_text(
            _share_kit_js(page_html, c.code), encoding="utf-8")
        rendered.add(share_href)
        first_written = first_written or out
        if code == cities.DEFAULT_CITY:
            primary = out

        flat = [d for _, group in dated for d in group]
        all_flat.extend(flat)

        by_rescue = {}
        for d in flat:
            by_rescue.setdefault(d.source_label, []).append(d)

        # After by_rescue, so each dog page can offer the rest of its own
        # rescue's dogs — the link someone who likes this dog actually wants.
        for d in flat:
            path = OUT_DIR / dog_path(d).lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".html").write_text(
                _dog_page(d, site, for_date, css_href=css_href,
                          share_href=share_href,
                          siblings=by_rescue.get(d.source_label, [])),
                encoding="utf-8")
        for label, dogs in by_rescue.items():
            (rdir / f"{slugify(label)}.html").write_text(
                _rescue_page(label, dogs, site), encoding="utf-8")

        # One rescue index per city, at /rescues and /la/rescues, each listing
        # only its own city's rescues.
        rpath = OUT_DIR / c.rescues_file
        rpath.parent.mkdir(parents=True, exist_ok=True)
        rpath.write_text(_rescues_page(by_rescue, site, for_date, c.code),
                         encoding="utf-8")
        rendered.add(c.rescues_path)

        # A city with no dogs is rendered noindex, so it must not also be
        # submitted in the sitemap — that combination asks Google to crawl a page
        # and then tells it not to keep it. Its rescue index is empty for the
        # same reason and gets the same treatment.
        if flat:
            urls.append(f"{site}/" if c.path == "/" else f"{site}{c.path}")
        if by_rescue:
            urls.append(f"{site}{c.rescues_path}")
        urls += [f"{site}/rescue/{slugify(l)}" for l in by_rescue]
        urls += [f"{site}{dog_path(d)}" for d in flat]

        per_city.append(f"{c.code}: {len(flat)} dogs, {len(by_rescue)} rescues")

    # One sitemap, from the union of every city in this pass plus whatever the
    # last one published for a city that is not. A per-city sitemap would be a
    # sitemap announcing that the other city's URLs are gone.
    written_paths = {u[len(site):] or "/" for u in urls} | rendered
    carried = _carried_sitemap_urls(site, owned, written_paths)
    if carried:
        print(f"  sitemap: carrying {len(carried)} URL(s) from the last run "
              f"for cities not in this pass")
    today_iso = for_date.isoformat()
    body = "".join(
        f"<url><loc>{html.escape(u)}</loc><lastmod>{today_iso}</lastmod>"
        f"<changefreq>daily</changefreq></url>" for u in urls + carried)
    (OUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>", encoding="utf-8")

    # One 404, from every city's dogs: a dead link can be arrived at from
    # anywhere, and the tiles on it are "here is something else" rather than a
    # claim about a city.
    (OUT_DIR / "404.html").write_text(_not_found_page(all_flat, site),
                                      encoding="utf-8")

    indexes = ", ".join(cities.resolve(k).rescues_path for k in by_city)
    print(f"  {len(all_flat)} dog pages ({'; '.join(per_city)}), "
          f"{indexes}, sitemap, 404")
    return primary or first_written
