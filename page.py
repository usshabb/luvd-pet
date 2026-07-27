"""Render the LUVD NYC daily page.

One job: show every new dog across NYC rescues today, beautifully, with no
filters and nothing to learn. Click a dog -> modal with everything we know ->
one button out to that rescue's own adopt page.
"""
import html
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import List

from sources.base import Dog

OUT_DIR = Path(__file__).parent / "public"
CONTACT_EMAIL = "hello@coryokeefe.com"

# How each rescue actually wants to be approached, verified against their own
# pages. Most require an application FIRST — Muddy Paws says outright that only
# registered adopters may email them — so a blanket "email the rescue" button
# would send people down the wrong path and waste the rescue's time.
_CONTACTS_FILE = Path(__file__).parent / "rescue_contacts.json"
try:
    RESCUE_CONTACTS = json.loads(_CONTACTS_FILE.read_text())
except Exception:
    RESCUE_CONTACTS = {}

def logo_img(cls: str = "brand-logo") -> str:
    """One logo in both themes — the white sticker outline is the brand."""
    return (f'<img class="{cls}" src="assets/luvd-logo.png" '
            f'alt="LUVD" width="1400" height="607">')


LOGO_SVG = logo_img()


def _chip_facts(dog: Dog) -> List[str]:
    """The skimmable pills on the card face."""
    out = []
    if dog.age:
        out.append(dog.age)
    if dog.sex:
        out.append(dog.sex)
    if dog.weight:
        out.append(dog.weight)
    elif dog.size:
        out.append(dog.size.title())
    if dog.breed and "unknown" not in dog.breed.lower():
        out.append(dog.breed.split("/")[0].strip()[:22])
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


def _day_label(iso: str, today: date) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return "Earlier"
    delta = (today - d).days
    if delta <= 0:
        return "New today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return d.strftime("%A")
    return d.strftime("%B %-d")


def _card(d: Dog, i: int, today: date) -> str:
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
    pills = "".join(f'<span class="pill">{html.escape(f)}</span>'
                    for f in _chip_facts(d))

    # Only shown once a wait is long enough to mean something.
    wd = waiting_days(d, today)
    wait = ""
    if wd is not None and wd >= WAIT_BADGE_DAYS:
        wait = f'<span class="waiting" title="Listed {wd} days">⏳ {wd} days</span>'

    # A real href so crawlers can reach every dog; JS intercepts the click and
    # opens the modal instead of navigating.
    return f"""
      <a class="card" href="{html.escape(dog_path(d))}" data-i="{i}"
         data-id="{html.escape(d.id)}">
        <div class="ph-wrap">{media}<span class="badge">{html.escape(d.source_label)}</span>
          <span class="views" hidden><span class="fire">🔥</span><b></b></span>
          {wait}
          <button class="save" data-id="{html.escape(d.id)}" type="button"
                  aria-pressed="false" aria-label="Save {html.escape(d.name)}">
            <svg class="hrt" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4
              S3.6 15.1 3.6 9.3A4.7 4.7 0 0 1 12 6.6a4.7 4.7 0 0 1 8.4 2.7c0 5.8-8.4
              11.1-8.4 11.1Z"/></svg>
            <span class="burst" aria-hidden="true"></span>
          </button></div>
        <div class="meta">
          <h3 class="nm">{html.escape(d.name)}</h3>
          <div class="pills">{pills}</div>
        </div>
      </a>"""


def _structured_data(flat, dated, site, for_date, rescues, meta_desc) -> dict:
    """JSON-LD for search and answer engines.

    Three graphs: what the site is, the actual list of dogs (so an assistant can
    answer "what dogs are up for adoption in NYC today" from real data), and the
    questions people actually ask. Facts here mirror the page — nothing is
    asserted that a visitor can't verify on screen.
    """
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
        items.append({
            "@type": "ListItem",
            "position": i,
            "url": f"{site}/#dog/{d.id}",
            "item": about,
        })

    faq = [
        ("How do I adopt a dog in NYC?",
         "Browse adoptable dogs on LUVD NYC, open the dog you're interested in, "
         "then use the button to contact that rescue directly. Some NYC rescues "
         "take email inquiries; most ask you to submit an adoption application "
         "first. LUVD links you to whichever step that rescue actually requires."),
        ("Which NYC rescues does LUVD cover?",
         "LUVD currently follows " + ", ".join(rescues) + ". New arrivals from "
         "every one of them are collected each morning."),
        ("How much does it cost to adopt a dog in New York City?",
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
         "them available, grouped by the day they first appeared."),
    ]

    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{site}/#website",
                "url": f"{site}/",
                "name": "LUVD NYC",
                "description": meta_desc,
                "inLanguage": "en-US",
                "publisher": {"@id": f"{site}/#org"},
            },
            {
                "@type": "Organization",
                "@id": f"{site}/#org",
                "name": "LUVD NYC",
                "url": f"{site}/",
                "logo": f"{site}/apple-touch-icon.png",
                "email": CONTACT_EMAIL,
                "areaServed": {"@type": "City", "name": "New York City"},
                "description": "LUVD NYC collects every new adoptable dog across "
                               "New York City rescues into one page, updated daily.",
            },
            {
                "@type": "CollectionPage",
                "@id": f"{site}/#page",
                "url": f"{site}/",
                "name": "Adopt a dog in NYC",
                "description": meta_desc,
                "isPartOf": {"@id": f"{site}/#website"},
                "dateModified": for_date.isoformat(),
                "about": {"@type": "Thing", "name": "Dog adoption in New York City"},
                "mainEntity": {
                    "@type": "ItemList",
                    "name": "Adoptable dogs in New York City",
                    "numberOfItems": len(flat),
                    "itemListElement": items,
                },
            },
            {
                "@type": "FAQPage",
                "@id": f"{site}/#faq",
                "mainEntity": [
                    {"@type": "Question", "name": q,
                     "acceptedAnswer": {"@type": "Answer", "text": a}}
                    for q, a in faq
                ],
            },
        ],
    }


def render(dated, for_date: date = None) -> str:
    """`dated` is [(iso_date, [Dog, ...]), ...], newest day first."""
    for_date = for_date or date.today()
    if dated and isinstance(dated[0], Dog):          # tolerate a flat list
        dated = [(for_date.isoformat(), list(dated))]

    flat: List[Dog] = [d for _, group in dated for d in group]
    payload = json.dumps([
        dict(d.to_dict(), waiting_days=(waiting_days(d, for_date) or 0))
        for d in flat
    ])
    subscribe_url = os.getenv("SUBSCRIBE_URL", "/subscribe")

    today_iso = for_date.isoformat()
    new_today = len(dict(dated).get(today_iso, []))
    total = len(flat)

    sections, i = [], 0
    for iso, group in dated:
        cards = []
        for d in group:
            cards.append(_card(d, i, for_date))
            i += 1
        is_today = iso == today_iso
        sections.append(f"""
    <section class="day{' today' if is_today else ''}">
      <div class="day-hd">
        <h2>{html.escape(_day_label(iso, for_date))}</h2>
        <span class="day-n">{len(group)} dog{'' if len(group) == 1 else 's'}</span>
      </div>
      <div class="grid">{''.join(cards)}</div>
    </section>""")

    # An evergreen headline says what the site IS to a first-time visitor and
    # holds up on a day with two arrivals. The count is transient, so it moves
    # to the subhead and to the "New today" section marker.
    head = "Adopt a dog in NYC"

    site = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
    cache_bust = for_date.isoformat()
    rescues = sorted({d.source_label for d in flat})
    meta_desc = (
        f"{total} adoptable dogs from {len(rescues)} New York City rescues, "
        f"updated every morning. Browse today's new arrivals with energy level, "
        f"apartment fit and breed guidance, then contact the rescue directly."
    )
    structured_data = json.dumps(_structured_data(flat, dated, site, for_date,
                                                  rescues, meta_desc))
    if len(rescues) > 1:
        rescue_sentence = ("LUVD follows " + ", ".join(rescues[:-1])
                           + f" and {rescues[-1]}.")
    else:
        rescue_sentence = f"LUVD follows {rescues[0]}." if rescues else ""
    rescue_sentence = html.escape(rescue_sentence)

    empty = "" if flat else """
      <div class="empty">
        <div class="empty-emoji">🦴</div>
        <h2>Nothing listed right now</h2>
        <p>Every rescue we follow is empty at the moment. Check back tomorrow.</p>
      </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<script>
// Dark mode follows the sun over New York, not a fixed clock. A 7pm/7am window
// is wrong for most of the year: NYC sunrise swings from 5:25am in June to
// 7:20am in January. Standard NOAA solar position, run before paint so there
// is no flash of the wrong theme.
(function () {{
  try {{
    var LAT = 40.7128, LON = -74.0060, RAD = Math.PI / 180;
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
    if (cosHa >= 1) {{ theme = 'dark'; }}          // sun never rises
    else if (cosHa <= -1) {{ theme = 'light'; }}   // sun never sets
    else {{
      var ha = Math.acos(cosHa) / RAD;
      var sunrise = 720 - 4 * (LON + ha) - eq;    // minutes UTC
      var sunset  = 720 - 4 * (LON - ha) - eq;
      var mins = now.getUTCHours() * 60 + now.getUTCMinutes();
      theme = (mins >= sunrise && mins < sunset) ? 'light' : 'dark';
    }}
    document.documentElement.setAttribute('data-theme', theme);
  }} catch (e) {{ /* fall back to the OS preference */ }}
}})();
</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Adopt a dog in NYC — LUVD</title>
<meta name="description" content="{meta_desc}">
<link rel="canonical" href="{site}/">
<link rel="icon" href="/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">

<!-- Social scrapers (iMessage, Slack, Twitter) reject relative image paths,
     so these are absolute. og.png is rebuilt nightly with real dog faces. -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="LUVD NYC">
<meta property="og:url" content="{site}/">
<meta property="og:title" content="Adopt a dog in NYC — LUVD">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{site}/og.png?v={cache_bust}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="LUVD NYC — adoptable dogs across New York City rescues">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Adopt a dog in NYC — LUVD">
<meta name="twitter:description" content="{meta_desc}">
<meta name="twitter:image" content="{site}/og.png?v={cache_bust}">
<meta name="theme-color" content="#FF002E">
<meta name="robots" content="index, follow, max-image-preview:large">

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
  @keyframes riseIn{{from{{opacity:0;transform:translateY(12px) scale(.99);}}
    to{{opacity:1;transform:none;}}}}
  @media (prefers-reduced-motion:reduce){{
    .boot .brand-wrap,.boot h1,.boot .hero-cap,.boot .card{{opacity:1;transform:none;}}
    .ready .brand-wrap,.ready h1,.ready .hero-cap,.ready .card{{animation:none;}}
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
    border:1px solid var(--hair);border-radius:980px;padding:5px 12px;}}
  .nav-count[hidden]{{visibility:hidden;}}
  .nav-count b{{color:var(--text);font-weight:700;font-variant-numeric:tabular-nums;}}
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
  @media (max-width:520px){{ .nav-date span{{display:none;}} .nav-count{{display:none;}}
    .nav-logo img{{width:88px;}} }}
  @media (prefers-reduced-motion:reduce){{
    .nc-dot,.nav-count b.bump{{animation:none;}}
  }}
  .logo{{font-size:14px;font-weight:800;letter-spacing:.2em;color:var(--accent);
    text-transform:uppercase;text-decoration:none;}}
  .nav-r{{display:flex;align-items:center;gap:8px;}}
  .nav-btn{{all:unset;cursor:pointer;font-size:13.5px;font-weight:500;color:var(--text);
    padding:7px 13px;border-radius:980px;transition:background .2s,opacity .2s;}}
  .nav-btn:hover{{background:var(--hair2);}}
  .nav-btn[hidden]{{display:none;}}
  .saved-chip{{color:var(--accent);font-weight:700;display:inline-flex;
    align-items:center;gap:6px;}}
  .saved-chip.active{{background:var(--accent-soft);}}
  .sc-hrt{{width:15px;height:15px;stroke:var(--accent);stroke-width:2;fill:none;
    transition:fill .2s ease;}}
  .saved-chip.has .sc-hrt{{fill:var(--accent);}}
  /* Nothing saved yet — present, but clearly not urgent. */
  .saved-chip.none{{color:var(--muted);}}
  .saved-chip.none .sc-hrt{{stroke:var(--muted);}}
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
  .cv{{font-style:normal;font-size:.42em;margin-left:.2em;vertical-align:.24em;
    color:var(--muted);display:inline-block;transition:transform .2s;}}
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
  .pick-menu button{{all:unset;cursor:pointer;font-size:16px;font-weight:500;
    padding:11px 14px;border-radius:10px;text-align:left;color:var(--text);
    display:flex;justify-content:space-between;align-items:center;gap:14px;}}
  .pick-menu button:hover{{background:var(--hair2);}}
  .pick-menu button:disabled{{cursor:default;opacity:.45;}}
  .pick-menu button:disabled:hover{{background:transparent;}}
  .pick-menu button[data-ok]::after{{content:'Live';font-size:11px;
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
  .hero-sub button{{all:unset;cursor:pointer;background:var(--accent);color:#fff;
    font-weight:600;font-size:15px;padding:12px 18px;border-radius:11px;
    white-space:nowrap;transition:opacity .2s;}}
  .hero-sub button:hover{{opacity:.88;}}
  .hero-note{{font-size:12.5px;color:var(--muted);margin-top:9px;}}
  .hero-note.ok{{color:var(--accent);font-weight:700;font-size:14px;}}
  .sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
    overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}}

  /* ---------- brand logo ---------- */
  .brand-wrap{{display:flex;justify-content:center;margin-bottom:10px;
    transition:opacity .3s ease,transform .3s ease;}}
  body.shrunk .brand-wrap{{opacity:0;transform:scale(.9) translateY(-10px);}}
  .brand-logo{{width:clamp(190px,27vw,330px);height:auto;cursor:pointer;display:block;
    transition:transform .45s cubic-bezier(.34,1.56,.64,1),filter .35s ease;
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

  /* ---------- day sections ---------- */
  .day{{padding-top:8px;}}
  .day + .day{{border-top:1px solid var(--hair2);margin-top:18px;padding-top:34px;}}
  .day-hd{{display:flex;align-items:baseline;gap:12px;padding-top:34px;}}
  .day + .day .day-hd{{padding-top:0;}}
  .day-hd h2{{font-size:23px;font-weight:700;letter-spacing:-.022em;margin:0;}}
  /* Same type as the day name, just grey — a tiny caption read as an error. */
  .day-n{{font-size:23px;font-weight:700;letter-spacing:-.022em;color:var(--muted);}}
  .day.today .day-hd h2{{color:var(--accent);}}

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
  .card:hover .ph{{transform:scale(1.045);}}
  .noph{{display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:10px;height:100%;
    background:linear-gradient(150deg,var(--accent-soft),transparent 72%);}}
  .noph-i{{font-size:58px;font-weight:800;letter-spacing:-.04em;
    color:var(--accent);opacity:.55;line-height:1;}}
  .noph-t{{font-size:11.5px;font-weight:600;letter-spacing:.03em;
    color:var(--muted);}}
  .badge{{position:absolute;left:11px;bottom:11px;font-size:11px;font-weight:600;
    max-width:calc(100% - 22px);overflow:hidden;text-overflow:ellipsis;
    white-space:nowrap;
    letter-spacing:.03em;padding:5px 10px;border-radius:980px;color:#fff;
    background:rgba(0,0,0,.55);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);}}
  /* Real click counts, fetched live. Hidden until a dog has genuine interest —
     never a fabricated number. */
  .views{{position:absolute;left:11px;top:11px;display:flex;align-items:center;gap:5px;
    font-size:13px;font-weight:700;padding:6px 11px;border-radius:980px;color:#fff;
    background:rgba(0,0,0,.55);backdrop-filter:blur(10px);
    -webkit-backdrop-filter:blur(10px);animation:pop .35s cubic-bezier(.34,1.56,.64,1);}}
  /* display:flex above would otherwise beat the [hidden] attribute. */
  .views[hidden]{{display:none;}}
  .views .fire{{font-size:13px;line-height:1;}}
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
  .nm{{font-size:23px;font-weight:700;letter-spacing:-.02em;margin:0 0 10px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
  /* nowrap keeps every card the same height so the grid stays aligned */
  .pills{{display:flex;flex-wrap:nowrap;gap:5px;overflow:hidden;}}
  .pill{{font-size:11.5px;font-weight:500;padding:4px 9px;border-radius:980px;
    background:var(--hair2);color:var(--muted);white-space:nowrap;}}


  .empty{{text-align:center;padding:90px 20px;}}
  .empty-emoji{{font-size:52px;margin-bottom:12px;}}
  .empty h2{{font-size:24px;margin:0 0 8px;letter-spacing:-.02em;}}
  .empty p{{color:var(--muted);margin:0;}}

  /* ---------- subscribe ---------- */
  .sub-sec{{background:var(--surface);border-radius:28px;padding:56px 32px;
    margin:56px 0 0;text-align:center;box-shadow:var(--shadow);}}
  .sub-sec h2{{font-size:clamp(26px,3.6vw,36px);letter-spacing:-.022em;margin:0 0 10px;}}
  .sub-sec p{{color:var(--muted);font-size:16.5px;margin:0 auto 26px;max-width:430px;}}
  .sub-form{{display:flex;gap:9px;max-width:430px;margin:0 auto;flex-wrap:wrap;}}
  .sub-form input{{flex:1;min-width:200px;padding:14px 17px;font-size:16px;border-radius:13px;
    border:1px solid var(--hair);background:var(--bg);color:var(--text);font-family:inherit;}}
  .sub-form input:focus{{outline:2px solid var(--accent);outline-offset:-1px;
    border-color:transparent;}}
  .sub-form button{{all:unset;cursor:pointer;background:var(--accent);color:#fff;font-weight:600;
    font-size:16px;padding:14px 26px;border-radius:13px;transition:opacity .2s;}}
  .sub-form button:hover{{opacity:.88;}}
  .sub-note{{font-size:13px;color:var(--muted);margin-top:14px;}}
  .sub-note a{{color:var(--accent);}}
  .sub-ok{{color:var(--accent);font-weight:600;margin-top:14px;font-size:15px;}}

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

  /* ---------- footer ---------- */
  footer{{text-align:center;padding:52px 0 72px;color:var(--muted);font-size:13.5px;}}
  footer .date{{font-weight:600;color:var(--text);font-size:15px;}}
  footer a{{color:var(--muted);}}

  /* ---------- modal shell ---------- */
  .scrim{{position:fixed;inset:0;background:rgba(0,0,0,.42);
    backdrop-filter:saturate(180%) blur(24px);-webkit-backdrop-filter:saturate(180%) blur(24px);
    display:none;align-items:center;justify-content:center;padding:24px;z-index:100;
    opacity:0;transition:opacity .28s ease;}}
  .scrim.on{{display:flex;}} .scrim.vis{{opacity:1;}}
  .modal{{position:relative;background:var(--surface);border-radius:26px;width:min(880px,100%);
    max-height:min(88vh,900px);overflow:hidden;box-shadow:var(--shadow-lg);
    display:flex;flex-direction:column;
    transform:scale(.96) translateY(12px);
    transition:transform .34s cubic-bezier(.2,.9,.25,1);}}
  /* The contact button is the whole point of the page, so it never scrolls
     out of reach — the body scrolls beneath a pinned action bar. */
  .m-scroll{{overflow-y:auto;-webkit-overflow-scrolling:touch;flex:1 1 auto;}}
  .m-foot{{flex:0 0 auto;padding:14px 28px 18px;border-top:1px solid var(--hair);
    background:var(--surface);}}
  .m-foot .cta{{margin-top:0;}}
  .m-foot .cta-sub{{margin-top:9px;}}
  .foot-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .act-note{{font-size:12.5px;color:var(--muted);text-align:center;
    margin-bottom:10px;}}
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
  .m-hero img{{width:100%;height:100%;object-fit:cover;object-position:center;
    display:block;}}
  .m-close{{position:absolute;top:14px;right:14px;width:34px;height:34px;border:none;
    z-index:12;
    border-radius:50%;cursor:pointer;font-size:17px;line-height:1;background:rgba(0,0,0,.5);
    color:#fff;backdrop-filter:blur(12px);display:grid;place-items:center;
    transition:background .2s;z-index:5;}}
  .m-close:hover{{background:rgba(0,0,0,.75);}}
  .thumbs{{display:flex;gap:8px;overflow-x:auto;flex:0 0 auto;
    scrollbar-width:none;}}
  .m-media:has(.thumbs) .m-hero{{min-height:0;}}
  .thumbs::-webkit-scrollbar{{height:0;}}
  .thumbs img{{width:60px;height:60px;object-fit:cover;object-position:center;
    border-radius:10px;cursor:pointer;
    flex:0 0 auto;opacity:.5;transition:opacity .2s;border:2px solid transparent;}}
  .thumbs img:hover,.thumbs img.sel{{opacity:1;border-color:var(--accent);}}
  .m-body{{padding:18px 22px 28px;}}
  /* No photo: content starts at the top, with room for the close button. */
  .m-scroll.no-hero .m-body{{padding-top:30px;}}
  .m-scroll.no-hero .m-close{{background:var(--hair);color:var(--text);}}
  .m-name-row{{display:flex;align-items:center;justify-content:space-between;
    gap:14px;margin-bottom:15px;}}
  .m-name{{font-size:clamp(40px,4.4vw,58px);font-weight:800;letter-spacing:-.035em;
    margin:0;line-height:1;min-width:0;overflow-wrap:anywhere;}}
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
  .chip.rescue{{background:var(--text);color:var(--bg);font-weight:600;}}
  .chip.wait{{background:var(--warn-soft);color:var(--warn);font-weight:600;}}
  .chip.views-chip{{background:var(--hair2);color:var(--muted);font-weight:600;}}
  .chip.views-chip b{{color:var(--text);}}
  .chip[hidden]{{display:none;}}

  /* Benefits and challenges, spelled out rather than colour-coded confetti. */
  .tlists{{background:var(--hair2);border-radius:18px;padding:18px 18px 16px;
    margin-bottom:22px;}}
  .tl-hd{{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
    color:var(--muted);margin-bottom:13px;}}
  /* Three columns — the panel is full width, so a single stacked list left
     most of the row empty and pushed everything else down. */
  .tlists ul{{list-style:none;margin:0;padding:0;
    display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
    gap:11px 20px;}}
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
  .scores .sc-note{{margin-top:auto;}}
  .sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:9px;}}
  .sc-ic{{font-size:15px;width:20px;text-align:center;}}
  .sc-lb{{font-size:14px;font-weight:600;flex:1;}}
  .sc-vl{{font-size:12.5px;color:var(--muted);font-weight:500;}}
  .bar{{height:7px;border-radius:980px;background:var(--hair);overflow:hidden;}}
  .bar span{{display:block;height:100%;border-radius:980px;background:var(--accent);
    width:0;transition:width .85s cubic-bezier(.2,.8,.2,1);}}
  .sc-note{{font-size:11.5px;color:var(--muted);line-height:1.45;padding-top:14px;
    border-top:1px solid var(--hair);margin-top:22px;}}

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
    transition:opacity .2s;margin-top:24px;}}
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
  @media (prefers-reduced-motion:reduce){{ .about-logo{{animation:none;}} }}

  /* ---------- subscribe modal ---------- */
  /* Narrower than the dog modal — one field / one message shouldn't sprawl. */
  .modal.narrow{{width:min(460px,100%);}}
  .modal.mid{{width:min(560px,100%);}}
  .sub-modal{{padding:42px 30px 34px;text-align:center;background:
      radial-gradient(120% 110% at 50% 0%, var(--accent-soft) 0%, transparent 62%);}}
  .sub-logo{{width:min(52%,200px);height:auto;display:block;margin:0 auto 22px;}}
  .sub-modal h2{{font-size:26px;letter-spacing:-.022em;margin:0 0 9px;}}
  .sub-modal p{{color:var(--muted);font-size:15px;margin:0 auto 22px;max-width:360px;}}
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
    .nm{{font-size:19px;margin:0 0 8px;}}
    .save{{width:30px;height:30px;right:8px;top:8px;}}
    .waiting{{right:8px;bottom:8px;font-size:9.5px;}}
    .pill{{font-size:10.5px;padding:3px 7px;}}
    .badge{{font-size:9.5px;padding:4px 8px;left:8px;bottom:8px;}}
    .views{{font-size:11.5px;padding:5px 9px;left:8px;top:8px;}}
    .day-hd{{padding-top:26px;}}
    .day-hd h2,.day-n{{font-size:19px;}}
    .day + .day{{margin-top:12px;padding-top:26px;}}
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
    .scrim.vis .modal{{transform:none;}}
    /* The close button rides above the hero image, always top-right. */
    .m-close{{position:fixed;top:max(14px,env(safe-area-inset-top));right:14px;
      width:38px;height:38px;font-size:18px;z-index:20;
      background:rgba(0,0,0,.62);color:#fff;}}
    .m-foot{{padding:12px 18px max(14px,env(safe-area-inset-bottom));}}
    .foot-row{{grid-template-columns:1fr;gap:8px;}}
    .share{{padding:22px 18px 20px;}}
    .modal.narrow{{width:100%;}}
    /* The subscribe modal stays a centered card — it's one field, not a page. */
    .scrim.compact{{align-items:center;padding:18px;}}
    .scrim.compact .modal{{height:auto;max-height:92vh;border-radius:22px;}}
    .scrim.compact .m-close{{position:absolute;}}
    .topgrid.with-photo{{grid-template-rows:none;min-height:0;}}
    .m-media{{grid-row:auto;}}
    .m-hero{{aspect-ratio:1/1;flex:0 0 auto;}}
    .m-name{{font-size:40px;}}
    .m-body{{padding:18px 18px 26px;}}
    .thumbs{{padding-left:18px;padding-right:18px;}}
    .about-hero{{padding:36px 20px 22px;}}
    .about-body{{padding:0 20px 26px;}}
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
  @media (max-width:400px){{
    .tlists ul{{grid-template-columns:1fr;}}
  }}
  @media (max-width:339px){{
    .grid{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body class="boot">

<nav>
  <div class="nav-in">
    <div class="nav-date">{for_date.strftime('%A')}<span>, {for_date.strftime('%B %-d')}</span></div>
    <div class="nav-mid">
      <div class="nav-count" id="nav-count" hidden>
        <span class="nc-dot"></span><b id="nc-n">0</b>
        <span class="nc-l">dogs viewed</span>
      </div>
      <a class="nav-logo" id="nav-logo" href="#" aria-label="LUVD NYC">
        <img src="assets/luvd-logo.png" alt="LUVD" width="1400" height="607">
      </a>
    </div>
    <div class="nav-r">
      <button class="nav-btn saved-chip" id="saved-chip"
              aria-label="Your saved dogs">
        <svg class="hrt sc-hrt" viewBox="0 0 24 24" aria-hidden="true"><path
          d="M12 20.4S3.6 15.1 3.6 9.3A4.7 4.7 0 0 1 12 6.6a4.7 4.7 0 0 1
          8.4 2.7c0 5.8-8.4 11.1-8.4 11.1Z"/></svg><b>0</b></button>
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
                aria-expanded="false">dog<i class="cv">▾</i></button>
        <span class="pick-menu" id="menu-species" role="listbox" hidden>
          <button role="option" data-v="dog" data-ok="1">Dogs</button>
          <button role="option" data-v="cat">Cats</button>
        </span>
      </span>
      in
      <span class="pick" data-kind="city">
        <button type="button" id="pick-city" aria-haspopup="listbox"
                aria-expanded="false">NYC<i class="cv">▾</i></button>
        <span class="pick-menu" id="menu-city" role="listbox" hidden>
          <button role="option" data-v="NYC" data-ok="1">New York City</button>
          <button role="option" data-v="LA">Los Angeles</button>
          <button role="option" data-v="CHI">Chicago</button>
          <button role="option" data-v="BOS">Boston</button>
          <button role="option" data-v="SF">San Francisco</button>
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
        <button type="submit">Send me dogs</button>
      </form>
      <div class="hero-note" id="hero-note">Get notified when there are new dogs.</div>
    </div>
  </header>

  <div class="saved-empty" id="saved-empty" hidden>
    <div class="se-art" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d="M12 20.4S3.6 15.1 3.6 9.3A4.7 4.7 0 0 1
        12 6.6a4.7 4.7 0 0 1 8.4 2.7c0 5.8-8.4 11.1-8.4 11.1Z"/></svg>
    </div>
    <h2>No saved dogs yet</h2>
    <p>Tap the heart on any dog to keep them here. Your list stays on this
       device — no account, nothing sent to us.</p>
    <button class="cta" id="se-browse">Browse today's dogs</button>
  </div>

  <main id="dogs">
  {''.join(sections)}
  {empty}
  </main>

  <section class="sub-sec" id="subscribe">
    <h2>Never miss a good dog</h2>
    <p>One email each morning with the new dogs across every NYC rescue we follow.
       Nothing on the days there aren't any.</p>
    <form class="sub-form" id="sub-form">
      <input type="email" id="sub-email" placeholder="you@email.com" required
             autocomplete="email" aria-label="Email address">
      <button type="submit">Subscribe</button>
    </form>
    <div class="sub-note" id="sub-note">Free. Unsubscribe anytime.</div>
  </section>

  <section class="faq">
    <h2>Adopting a dog in New York City</h2>
    <details open>
      <summary>How do I adopt a dog in NYC?</summary>
      <p>Open any dog above and use the button at the bottom of its page. Some
         NYC rescues take email inquiries; most ask for an adoption application
         first. LUVD sends you to whichever step that rescue actually requires,
         so you don't get bounced.</p>
    </details>
    <details>
      <summary>Which rescues does LUVD cover?</summary>
      <p>{rescue_sentence} We check all of them every morning and show you what's
         new, so you don't have to keep a dozen tabs open.</p>
    </details>
    <details>
      <summary>What does it cost to adopt in NYC?</summary>
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
    <div style="margin-top:6px;">
      LUVD NYC · <a href="mailto:{CONTACT_EMAIL}?subject=Hello%20LUVD%20NYC">Contact</a>
    </div>
  </footer>
</div>

<div class="scrim" id="scrim" role="dialog" aria-modal="true">
  <div class="modal" id="modal"></div>
</div>

<script>
const DOGS = {payload};
const SUBSCRIBE_URL = {json.dumps(subscribe_url)};
const RESTING_NOTE = {{
  'hero-note': 'Get notified when there are new dogs.',
  'sub-note': 'Free. Unsubscribe anytime.',
  'm-sub-note': 'Free. Unsubscribe anytime.',
}};
const CONTACTS = {json.dumps(RESCUE_CONTACTS)};
const CONTACT = {json.dumps(CONTACT_EMAIL)};
const scrim = document.getElementById('scrim');
const modal = document.getElementById('modal');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);

const SCALE = {{
  energy:     {{icon:'⚡', label:'Energy level',
    words:['Couch potato','Low key','Middle of the road','Active','Needs a job']}},
  apartment:  {{icon:'🏙️', label:'Apartment fit',
    words:['Needs real space','Tight fit','Workable','Good fit','Built for city life']}},
  experience: {{icon:'🎓', label:'Experience needed',
    words:['Great first dog','Beginner friendly','Some experience','Experienced home','Seasoned owner']}},
  alone: {{icon:'🏠', label:'Home alone',
    words:['Needs company','Short days only','Half a day','Most of a workday','Full workday fine']}}
}};

function bars(d) {{
  if (!d.scores || !d.scores.energy) return '';
  const rows = Object.keys(SCALE).map(k => {{
    const v = d.scores[k], s = SCALE[k];
    return `<div class="sc">
        <div class="sc-top">
          <span class="sc-ic">${{s.icon}}</span>
          <span class="sc-lb">${{s.label}}</span>
          <span class="sc-vl">${{esc(s.words[v-1])}}</span>
        </div>
        <div class="bar"><span data-w="${{v*20}}"></span></div>
      </div>`;
  }}).join('');
  return `<div class="scores"><div class="sc-hd">Good to know</div>${{rows}}
    <div class="sc-note">Estimated from this dog's write-up and breed tendencies —
      not a formal assessment. ${{esc(d.source_label)}} knows this dog best.</div></div>`;
}}

// ---- share ------------------------------------------------------------------
// Builds a 1080x1920 story card on a canvas so it can be saved straight to a
// phone and posted. Photos come back through /img so the canvas stays
// same-origin and can actually be exported.
const STORY_W = 1080, STORY_H = 1920;

function proxied(url) {{
  return '/img?u=' + encodeURIComponent(url);
}}

function loadImg(src) {{
  return new Promise((res, rej) => {{
    const im = new Image();
    im.crossOrigin = 'anonymous';
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = src;
  }});
}}

function drawCover(ctx, im, x, y, w, h) {{
  const r = Math.max(w / im.width, h / im.height);
  const dw = im.width * r, dh = im.height * r;
  ctx.drawImage(im, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}}

async function buildStory(d) {{
  const c = document.createElement('canvas');
  c.width = STORY_W; c.height = STORY_H;
  const ctx = c.getContext('2d');

  ctx.fillStyle = '#0b0b0c';
  ctx.fillRect(0, 0, STORY_W, STORY_H);

  if (d.photos && d.photos.length) {{
    try {{
      const im = await loadImg(proxied(d.photos[0]));
      drawCover(ctx, im, 0, 0, STORY_W, STORY_H);
    }} catch (e) {{ /* keep the flat background */ }}
  }}

  // Scrims: darken top and bottom so type stays legible on any photo.
  let g = ctx.createLinearGradient(0, 0, 0, 620);
  g.addColorStop(0, 'rgba(0,0,0,.62)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, STORY_W, 620);
  g = ctx.createLinearGradient(0, STORY_H - 1000, 0, STORY_H);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(.55, 'rgba(0,0,0,.72)');
  g.addColorStop(1, 'rgba(0,0,0,.94)');
  ctx.fillStyle = g; ctx.fillRect(0, STORY_H - 1000, STORY_W, 1000);

  const F = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif';

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
}}

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

async function openShare(d) {{
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
  return `<div class="tlists">
      <div class="tl-hd">What to expect</div>
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
      <button class="tab" data-t="1">Dog story</button>
    </div>
    <div class="pane on" data-p="0">
      <span class="breed-tag">${{esc(bi.name)}}</span>
      ${{unknownNote}}
      ${{sect('🧠','Temperament','temperament',bi.temperament)}}
      ${{sect('🎾','Exercise','exercise',bi.exercise)}}
      ${{sect('✂️','Grooming','grooming',bi.grooming)}}
      ${{sect('🏙️','In a NYC apartment','nyc',bi.nyc)}}
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

function showModal(inner, size) {{
  modal.classList.toggle('narrow', size === 'narrow');
  modal.classList.toggle('mid', size === 'mid');
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
    modal.querySelectorAll('.bar span').forEach(b =>
      setTimeout(() => {{ b.style.width = b.dataset.w + '%'; }}, 90));
  }});
  const x = modal.querySelector('.m-close');
  if (x) x.onclick = closeModal;
}}

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

function contactAction(d) {{
  const c = CONTACTS[d.source] || {{}};
  const url = dogUrl(d);
  if (c.method === 'email' && c.email) {{
    const subject = `Adoption inquiry: ${{d.name}}`;
    const body =
      `Hi ${{d.source_label}},\n\n` +
      `I'd like to adopt ${{d.name}}${{d.age ? ` (${{d.age}}` +
        (d.sex ? `, ${{d.sex}}` : '') + ')' : ''}}, who I found through LUVD NYC.\n\n` +
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
    + `<span class="chip views-chip" id="m-views" data-id="${{esc(d.id)}}"${{
        (VIEW_COUNTS[d.id] || 0) >= VIEW_FLOOR ? '' : ' hidden'}}>🔥 <b>${{
        VIEW_COUNTS[d.id] || 0}}</b> viewed</span>`;
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
  const hasPhoto = !!(d.photos && d.photos.length);
  const thumbs = (d.photos || []).length > 1
    ? `<div class="thumbs">${{d.photos.map((p,n) =>
        `<img src="${{esc(p)}}" class="${{n===0?'sel':''}}" data-src="${{esc(p)}}"
          alt="">`).join('')}}</div>` : '';
  const media = hasPhoto ? `
    <div class="m-media">
      <div class="m-hero"><img id="hero" src="${{esc(d.photos[0])}}"
        alt="${{esc(d.name)}}"></div>
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
                d="M12 20.4S3.6 15.1 3.6 9.3A4.7 4.7 0 0 1 12 6.6a4.7 4.7 0 0 1
                8.4 2.7c0 5.8-8.4 11.1-8.4 11.1Z"/></svg>
              <span class="burst" aria-hidden="true"></span>
            </button>
          </div>
          <div class="chips">
            <span class="chip rescue">${{esc(d.source_label)}}</span>
            ${{breedPill}}${{factPills}}${{traitPills}}</div>
        </div>
        ${{bars(d)}}
      </div>
      ${{traitLists(goodT, warnT)}}
      ${{tabs(d)}}
      <div class="cta-sub" style="margin-top:18px;">
        <a href="${{esc(d.url)}}" target="_blank" rel="noopener">View original listing</a></div>
      ${{simSection(d)}}
    </div>
    </div>
    <div class="m-foot">
      ${{act.note ? `<div class="act-note">${{esc(act.note)}}</div>` : ''}}
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

  modal.querySelectorAll('.thumbs img').forEach(t => t.onclick = () => {{
    document.getElementById('hero').src = t.dataset.src;
    modal.querySelectorAll('.thumbs img').forEach(o => o.classList.remove('sel'));
    t.classList.add('sel');
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

function openAbout() {{
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
        <a class="cta" href="mailto:${{esc(CONTACT)}}?subject=Hello%20LUVD%20NYC">
          Get in touch →</a>
        <div class="cta-sub">We’re not a shelter. We point you to the rescues who are.</div>
      </div>
    </div>`, 'mid');
}}

function closeModal(fromHash) {{
  if (!fromHash && /^#dog\//.test(location.hash)) {{
    history.pushState(null, '', location.pathname + location.search);
  }}
  scrim.classList.remove('vis');
  document.body.classList.remove('locked');
  setTimeout(() => scrim.classList.remove('on'), 280);
}}

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
      el.hidden = false;
    }} else {{
      el.hidden = true;
    }}
  }});
}}

function paintTotal(n) {{
  if (typeof n !== 'number' || n <= 0) return;
  const wrap = document.getElementById('nav-count');
  const el = document.getElementById('nc-n');
  if (!wrap || !el) return;
  const prev = +el.textContent.replace(/,/g, '') || 0;
  el.textContent = n.toLocaleString();
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
function slugFor(d) {{
  return d.id.replace(/[^a-zA-Z0-9:_-]/g, '');
}}

function dogUrl(d) {{
  return location.origin + location.pathname + '#dog/' + slugFor(d);
}}

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
  const state = {{species: 'dog', city: 'NYC', cityFull: 'New York City'}};
  const LIVE = {{species: 'dog', city: 'NYC'}};
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
      document.querySelectorAll('.day, .hero-cap').forEach(el => el.style.display = '');
      return;
    }}
    const what = state.species === 'cat' ? 'Cats' : 'Dogs';
    soonMsg.innerHTML = `<b>${{esc(what)}} in ${{esc(state.cityFull || state.city)}}</b> isn't live yet — ` +
      `right now LUVD covers dogs in NYC. Want to know the day it opens?`;
    soon.hidden = false;
    // Hide the NYC dog grid, so we're never showing dogs that contradict the
    // sentence the visitor just composed.
    document.querySelectorAll('.day, .hero-cap').forEach(el => el.style.display = 'none');
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
  document.querySelectorAll('.day:first-of-type .card').forEach((c, n) => {{
    if (n < 12) c.style.setProperty('--i', n);
  }});
  requestAnimationFrame(() => {{
    document.body.classList.remove('boot');
    document.body.classList.add('ready');
  }});
}})();

document.querySelectorAll('.card').forEach(c => c.addEventListener('click', e => {{
  if (e.target.closest('.save')) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  openDog(+c.dataset.i);
  countView(c);
}}));

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

// Filter to saved dogs — a view, not a separate page.
let showingSaved = false;
function toggleSavedView() {{
  showingSaved = !showingSaved;
  const set = savedSet();
  const empty = document.getElementById('saved-empty');
  if (empty) empty.hidden = !(showingSaved && set.size === 0);
  document.querySelectorAll('.card').forEach(c => {{
    c.style.display = (!showingSaved || set.has(c.dataset.id)) ? '' : 'none';
  }});
  document.querySelectorAll('.day').forEach(sec => {{
    const any = [...sec.querySelectorAll('.card')].some(c => c.style.display !== 'none');
    sec.style.display = any ? '' : 'none';
  }});
  const chip = document.getElementById('saved-chip');
  if (chip) chip.classList.toggle('active', showingSaved);
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}

const savedChip = document.getElementById('saved-chip');
if (savedChip) savedChip.onclick = toggleSavedView;
const seBrowse = document.getElementById('se-browse');
if (seBrowse) seBrowse.onclick = toggleSavedView;   // flip back to everything
paintSaved();
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
function openSubscribe() {{
  showModal(`
    <button class="m-close" aria-label="Close">✕</button>
    <div class="sub-modal">
      <img class="sub-logo" src="assets/luvd-logo.png" alt="LUVD">
      <h2>Never miss a good dog</h2>
      <p>One email each morning with the new dogs across every NYC rescue we
         follow. Nothing on the days there aren't any.</p>
      <form class="sub-form" id="m-sub-form">
        <input type="email" id="m-sub-email" placeholder="you@email.com" required
               autocomplete="email" aria-label="Email address">
        <button type="submit">Subscribe</button>
      </form>
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
async function handleSubscribe(e, emailId, noteId, formId) {{
  e.preventDefault();
  const email = document.getElementById(emailId).value.trim();
  const note = document.getElementById(noteId);
  if (!email) return;
  note.className = note.id === 'hero-note' ? 'hero-note' : 'sub-note';
  try {{
    const r = await fetch(SUBSCRIBE_URL, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{email: email}})
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
      '<a href="mailto:' + CONTACT + '?subject=Subscribe%20to%20LUVD%20NYC&body=' +
      encodeURIComponent(email) + '">Email us to subscribe →</a>';
  }}
}}

document.getElementById('sub-form').onsubmit = e =>
  handleSubscribe(e, 'sub-email', 'sub-note', 'sub-form');

const heroForm = document.getElementById('hero-form');
if (heroForm) heroForm.onsubmit = e =>
  handleSubscribe(e, 'hero-email', 'hero-note', 'hero-form');
</script>
</body>
</html>"""


def _dog_page(d: Dog, site: str, today: date) -> str:
    """A standalone, indexable page per dog.

    Server-rendered rather than a hash route, because Google can't index
    fragments. The title leads with rescue and breed — nobody searches a dog's
    name, they search "muddy paws rescue dogs" or "chihuahua adoption nyc".
    """
    facts = " · ".join(x for x in (d.age, d.sex, d.weight, d.location) if x)
    breed = d.breed if d.breed and "unknown" not in d.breed.lower() else "Mixed breed"
    title = f"{d.name} — {breed} for adoption at {d.source_label} | LUVD NYC"
    desc = (f"{d.name} is a {breed.lower()} available for adoption from "
            f"{d.source_label} in New York City."
            + (f" {facts}." if facts else "")
            + " See photos, temperament and how to apply.")
    photo = d.primary_photo()
    wd = waiting_days(d, today)

    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": d.name,
        "description": clean_meta(d.description) or desc,
        "category": f"Adoptable dog — {breed}",
        "brand": {"@type": "Organization", "name": d.source_label},
        "url": f"{site}{dog_path(d)}",
    }
    if photo:
        ld["image"] = photo

    body_bits = []
    if photo:
        body_bits.append(f'<img class="dp-photo" src="{html.escape(photo)}" '
                         f'alt="{html.escape(d.name)}, {html.escape(breed)}">')
    body_bits.append(f"<h1>{html.escape(d.name)}</h1>")
    body_bits.append(f'<p class="dp-sub">{html.escape(breed)} · '
                     f'{html.escape(d.source_label)}</p>')
    if facts:
        body_bits.append(f'<p class="dp-facts">{html.escape(facts)}</p>')
    if wd is not None and wd >= WAIT_BADGE_DAYS:
        body_bits.append(f'<p class="dp-wait">Listed {wd} days</p>')
    if d.traits:
        items = "".join(f"<li>{html.escape(t['text'])}</li>" for t in d.traits)
        body_bits.append(f"<h2>What to expect</h2><ul>{items}</ul>")
    if d.description:
        body_bits.append("<h2>About " + html.escape(d.name) + "</h2><p>"
                         + html.escape(d.description).replace("\n", "<br>") + "</p>")
    bi = d.breed_info or {}
    if bi.get("temperament"):
        body_bits.append(f"<h2>{html.escape(bi.get('name', breed))} temperament</h2>"
                         f"<p>{html.escape(bi['temperament'])}</p>"
                         f"<h2>Exercise</h2><p>{html.escape(bi.get('exercise',''))}</p>"
                         f"<h2>In a NYC apartment</h2>"
                         f"<p>{html.escape(bi.get('nyc',''))}</p>")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{site}{dog_path(d)}">
<link rel="icon" href="/favicon.png" type="image/png">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
{f'<meta property="og:image" content="{html.escape(photo)}">' if photo else ''}
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>
  body{{{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    max-width:720px;margin:0 auto;padding:28px 20px 60px;line-height:1.6;
    background:#fbfbfd;color:#1d1d1f;}}}}
  a{{{{color:#FF002E;}}}}
  .dp-photo{{{{width:100%;border-radius:18px;margin-bottom:22px;}}}}
  h1{{{{font-size:38px;letter-spacing:-.03em;margin:0 0 6px;}}}}
  h2{{{{font-size:18px;margin:26px 0 6px;}}}}
  .dp-sub{{{{color:#6e6e73;margin:0 0 4px;}}}}
  .dp-facts{{{{color:#6e6e73;margin:0;}}}}
  .dp-wait{{{{color:#a86500;font-weight:600;}}}}
  .dp-cta{{{{display:inline-block;background:#FF002E;color:#fff;text-decoration:none;
    padding:13px 22px;border-radius:12px;font-weight:600;margin-top:26px;}}}}
  .dp-back{{{{display:block;margin-bottom:20px;font-size:14px;}}}}
  @media (prefers-color-scheme:dark){{{{
    body{{{{background:#000;color:#f5f5f7;}}}} .dp-sub,.dp-facts{{{{color:#98989d;}}}}
  }}}}
</style></head><body>
<a class="dp-back" href="/">← All adoptable dogs in NYC</a>
{''.join(body_bits)}
<a class="dp-cta" href="{html.escape(d.cta_url())}" target="_blank" rel="noopener">
  Contact {html.escape(d.source_label)} about {html.escape(d.name)}</a>
<p><a href="/rescue/{rescue_slug(d)}">More dogs from {html.escape(d.source_label)}</a>
 · <a href="{html.escape(d.url)}" target="_blank" rel="noopener">Original listing</a></p>
</body></html>"""


def _rescue_page(label: str, dogs: List[Dog], site: str) -> str:
    """One page per rescue — "muddy paws rescue dogs" is a real search."""
    slug = slugify(label)
    title = f"{label} — adoptable dogs in NYC | LUVD"
    desc = (f"All {len(dogs)} dogs currently available for adoption from "
            f"{label} in New York City, updated daily.")
    cards = "".join(
        f'<li><a href="{html.escape(dog_path(d))}">{html.escape(d.name)}</a>'
        f' — {html.escape(d.breed or "Mixed breed")}'
        f'{" · " + html.escape(d.age) if d.age else ""}</li>'
        for d in dogs
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{site}/rescue/{slug}">
<link rel="icon" href="/favicon.png" type="image/png">
<style>
  body{{{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    max-width:720px;margin:0 auto;padding:28px 20px 60px;line-height:1.6;
    background:#fbfbfd;color:#1d1d1f;}}}}
  a{{{{color:#FF002E;}}}} h1{{{{font-size:32px;letter-spacing:-.025em;}}}}
  ul{{{{padding-left:18px;}}}} li{{{{margin-bottom:8px;}}}}
  @media (prefers-color-scheme:dark){{{{body{{{{background:#000;color:#f5f5f7;}}}}}}}}
</style></head><body>
<a href="/">← All adoptable dogs in NYC</a>
<h1>{html.escape(label)}</h1>
<p>{html.escape(desc)}</p>
<ul>{cards}</ul>
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
<title>This dog has moved on — LUVD NYC</title>
<meta name="robots" content="noindex">
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


def write(dated, for_date: date = None) -> Path:
    for_date = for_date or date.today()
    site = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "index.html"
    out.write_text(render(dated, for_date), encoding="utf-8")

    flat = [d for _, group in dated for d in group]

    # Static per-dog and per-rescue pages. Real URLs Google can index —
    # hash fragments cannot be. Stale files are cleared so adopted dogs stop
    # returning 200 with an out-of-date listing.
    for sub in ("dog", "rescue"):
        target = OUT_DIR / sub
        if target.exists():
            shutil.rmtree(target)

    for d in flat:
        path = OUT_DIR / dog_path(d).lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".html").write_text(_dog_page(d, site, for_date),
                                             encoding="utf-8")

    by_rescue = {}
    for d in flat:
        by_rescue.setdefault(d.source_label, []).append(d)
    rdir = OUT_DIR / "rescue"
    rdir.mkdir(parents=True, exist_ok=True)
    for label, dogs in by_rescue.items():
        (rdir / f"{slugify(label)}.html").write_text(
            _rescue_page(label, dogs, site), encoding="utf-8")

    # Sitemap lists every real URL.
    urls = [f"{site}/"] + [f"{site}/rescue/{slugify(l)}" for l in by_rescue] \
           + [f"{site}{dog_path(d)}" for d in flat]
    today_iso = for_date.isoformat()
    body = "".join(
        f"<url><loc>{html.escape(u)}</loc><lastmod>{today_iso}</lastmod>"
        f"<changefreq>daily</changefreq></url>" for u in urls)
    (OUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>", encoding="utf-8")

    (OUT_DIR / "404.html").write_text(_not_found_page(flat, site),
                                      encoding="utf-8")

    print(f"  {len(flat)} dog pages, {len(by_rescue)} rescue pages, sitemap, 404")
    return out
