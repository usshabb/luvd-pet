"""Morning email via Mandrill — a short nudge that links to the day's LUVD page.

Deliberately NOT a full catalog: a few faces, a count, one button. The page is
where you actually browse.

All outbound mail (signup welcome, daily digest, unsubscribe goodbye, scraper
alerts, weekly report) goes through send_email() so there is exactly one place
that knows the provider.
"""
import hashlib
import hmac
import json
import os
import html
import random
import re
from datetime import date
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlsplit

import requests

import cities

from sources.base import Dog

MANDRILL_URL = "https://mandrillapp.com/api/1.0/messages/send.json"
PUBLIC = Path(__file__).parent / "public"

# How many faces each layout shows. Phones get fewer and larger: three across
# a 390px screen is a 95px tile, which is too small to be a face.
PREVIEW_COUNT = 6
PHONE_PREVIEW_COUNT = 4

# The goodbye shows half as many. Six faces is a catalogue and reads as one
# last pitch; three is a wave. Three and two are also the largest counts that
# fill a single complete row in each layout — three across on desktop, two
# across on a phone — so neither ends on an orphan tile, which the grid
# otherwise has to work around and which reads as an image that failed. Two is
# the base, since the phone layout is what a client without media queries gets.
GOODBYE_COUNT = 3
GOODBYE_PHONE_COUNT = 2

# Tile edge lengths, in px. Every tile is EDGE wide and EDGE tall — one number
# feeds both, so a photo cannot come out as a vertical slice the way a fluid
# width against a fixed 168px height did.
#
# Desktop: the card is 560px with 28px of padding, so 504px of content, and
# 3 * 162 + 2 * 9 gutters = 504 exactly.
TILE_DESKTOP = 162
# Phones, stepped so two tiles plus a gutter always fit the narrowest viewport
# in each band rather than overflowing it. TILE_PHONE_TINY is the inline base
# and the other two are stepped UP to from there, because the base is what a
# client that drops the <style> block renders at every width — including a
# 320px phone. Basing on 176 and stepping down looks identical in any client
# that applies the queries, and overflows a 390px screen by 15px in one that
# doesn't, which is the whole failure this layout exists to avoid.
TILE_PHONE_TINY = 124     # base, and <=375px
TILE_PHONE_SMALL = 148    # 376-480px  (a 390px iPhone lands here)
TILE_PHONE = 176          # 481-600px
GUTTER = 9

# Ink fills 1162x364 of the source file, so this box puts the visible wordmark
# at about 125x39 above the 27px headline — a clear step up from the 120x52 it
# was, and still reading as a header rather than a billboard. 150x65 is exactly
# 30:13, which is the source ratio to within 0.05%, so both this box and the
# asset below are whole numbers with nothing rounded into a squash.
LOGO_W, LOGO_H = 150, 65
# The mail-sized asset: 300x130 — 2x this box, for retina — against the site
# logo's 1400x607 and 275KB. It lives in public/assets, so it ships in the same
# deploy as this line, but it 404s on the live domain until that deploy lands,
# so anything sent or rendered from a developer machine has to override this
# first.
LOGO_FILE = "/assets/luvd-logo-email.png"


def unsub_token(email: str) -> str:
    """Signed token so an unsubscribe link only works for its own address."""
    secret = os.getenv("UNSUB_SECRET", "luvd-dev-secret")
    return hmac.new(secret.encode(), email.strip().lower().encode(),
                    hashlib.sha256).hexdigest()[:20]


def unsub_url(email: str) -> str:
    return f"{_site_url()}/unsubscribe?e={quote(email)}&t={unsub_token(email)}"


def email_configured() -> bool:
    return bool(os.getenv("MANDRILL_API_KEY"))


def _from_parts():
    """FROM_EMAIL accepts 'Name <addr>' or a bare address.

    The default has to be a mailbox that actually exists: it is what runs
    whenever the environment variable is missing or stale, which is the
    common case on a fresh box. dogs@luvd.com never did.
    """
    raw = os.getenv("FROM_EMAIL", "LUVD <cory@luvd.com>")
    if "<" in raw:
        name, _, rest = raw.partition("<")
        return rest.rstrip("> ").strip(), (name.strip() or "LUVD")
    return raw.strip(), "LUVD"


def send_email(to_email: str, subject: str, html_body: str = None, text_body: str = None,
               headers: dict = None):
    key = os.getenv("MANDRILL_API_KEY")
    if not key:
        raise RuntimeError("MANDRILL_API_KEY not set")
    from_email, from_name = _from_parts()
    message = {
        "from_email": from_email,
        "from_name": from_name,
        "to": [{"email": to_email}],
        "subject": subject,
    }
    if html_body:
        message["html"] = html_body
    if text_body:
        message["text"] = text_body
    if headers:
        message["headers"] = headers
    resp = requests.post(MANDRILL_URL, json={"key": key, "message": message}, timeout=30)
    body = resp.json()
    # Mandrill signals API-level errors as a dict (often with HTTP 500),
    # per-recipient failures as status "rejected"/"invalid" in a list.
    if isinstance(body, dict) and body.get("status") == "error":
        raise RuntimeError(f"Mandrill error: {body.get('message')}")
    resp.raise_for_status()
    result = body[0]
    if result.get("status") not in ("sent", "queued", "scheduled"):
        raise RuntimeError(
            f"Mandrill {result.get('status')}: {result.get('reject_reason')}")
    return result


def _site_url() -> str:
    return os.getenv("SITE_URL", "http://localhost:8000")


def _abs(path: str) -> str:
    """Absolute URL on whatever site we are rendering for. Email has no
    document base, so every src and href has to be spelled out in full."""
    return f"{_site_url().rstrip('/')}{path}"


def _city_page(city: str = None) -> str:
    """Absolute URL of one city's page — the front page a subscriber means.

    Every "see today's dogs" link in every mail used to be ``_site_url()``,
    which is New York's page, because it was written when New York was the only
    city. That sent an LA subscriber's morning digest, and their welcome, to a
    page of Brooklyn dogs: the right dogs were in the mail and every link out of
    it went to the wrong city.

    ``city=None`` keeps the old answer for callers that genuinely have no city —
    the goodbye, which is sent after someone has been taken off every list, so
    there is no city left to send them to.
    """
    if not city:
        return _site_url()
    return _abs(cities.resolve(city).path).rstrip("/") or _site_url()


def _track(path: str, send_id: int = None, dog_id: str = None) -> str:
    """Wrap a site-relative path in the click counter, or leave it alone.

    The redirect target is never carried as a URL — only as a path this server
    re-attaches its own origin to. That is the whole reason it is shaped this
    way: a `?u=https://...` parameter would make this an open redirect, and an
    open redirect on a domain that sends bulk mail is a gift to whoever finds
    it first.

    No send_id means no tracking, and the plain link is returned. Every mail
    that predates this — the goodbye, the welcome — takes that path and is
    unchanged.
    """
    if not send_id:
        return _abs(path)
    q = f"u={quote(path, safe='/')}"
    if dog_id:
        q += f"&d={quote(dog_id, safe='')}"
    return _abs(f"/c/{int(send_id)}?{q}")


def _pixel(send_id: int = None) -> str:
    """The open counter. Empty when the mail is not being tracked.

    Counts loads, not readers: Apple Mail Privacy Protection and Gmail's image
    proxy fetch this whether or not anybody looked, so the number runs high by
    an amount that cannot be measured. It is trend data, not a rate — see
    db.email_stats(), which refuses to divide by it.
    """
    if not send_id:
        return ""
    return (f'<img src="{html.escape(_abs(f"/px/{int(send_id)}.gif"))}" '
            f'width="1" height="1" alt="" '
            f'style="display:block;width:1px;height:1px;border:0;'
            f'max-height:1px;max-width:1px;opacity:0;overflow:hidden;">')


def _dog_link(dog: Dog, send_id: int = None) -> str:
    """The dog's own page, not the front page.

    A tile is a face; tapping it should land on that face. check.py writes
    every dog's page before it sends the digest, so the file on disk is the
    honest test of whether the page exists — a dog without one falls back to
    the front page rather than to a 404.
    """
    try:
        from page import dog_path
        path = dog_path(dog)
    except Exception:
        return _site_url()
    if (PUBLIC / f"{path.lstrip('/')}.html").is_file():
        return _track(path, send_id, dog.id)
    return _site_url()


# WordPress writes fixed renditions beside the original upload. Two cover the
# 3:4 and 4:3 shapes nearly every rescue photo is in, and both are checked
# before use, so a theme that generates neither costs us nothing.
_WP_UPLOAD = re.compile(
    r"^(https://[^/]+/wp-content/uploads/\d{4}/\d{2}/.+?)(\.(?:jpe?g|png))$", re.I)
_PHOTO_CACHE = {}


def _photo_candidates(url: str):
    m = _WP_UPLOAD.match(url)
    if m and not re.search(r"-\d+x\d+$", m.group(1)):
        for size in ("768x1024", "1024x768"):
            yield f"{m.group(1)}-{size}{m.group(2)}"


def _serves_image(url: str) -> bool:
    try:
        r = requests.head(url, timeout=6, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (LUVD)"})
    except requests.RequestException:
        return False
    return (r.status_code == 200
            and r.headers.get("Content-Type", "").startswith("image/"))


def _email_photo(url: str, width: int = 0) -> str:
    """A smaller rendition of the same photo, when one is addressable.

    A 162px tile has no use for a 2880x3840 original, and six of those is
    ~9.7MB of email. Only rewrite where the URL shape genuinely names a size,
    and only after confirming the rewrite still serves an image — a thumbnail
    that 404s is far worse than an original that merely weighs too much.

    SmugMug (Muddy Paws) is deliberately left alone. The long path segment
    before the size is a signature over that exact size: /4K/ -> /M/, the
    filename suffix on its own, dropping the token, and the older
    /photos/i-KEY/ form all return 403. Petstablished's S3 objects,
    Shelterluv's profile pictures and Petango each publish one rendition and
    ignore width parameters, so there is nothing smaller to ask them for.

    When `width` is given and the host publishes nothing smaller, the last
    resort is our own /img proxy, which resizes. That is the only way to get a
    tile-sized version of the hosts above: one of them served a 3840x2560 PNG at
    16.5 MB, which is 37 KB through the proxy at w=400. Six of those decides
    whether the mail arrives at all — Gmail clips at 102 KB of HTML and no
    client enjoys 100 MB of images.

    Only for allowlisted hosts. /img refuses anything else with a 403, and an
    <img> pointing at a 403 is a broken tile — strictly worse than a photo that
    merely weighs too much, which is the rule the rest of this function follows.
    """
    if not url:
        return url
    key = (url, width)
    if key not in _PHOTO_CACHE:
        smaller = next((c for c in _photo_candidates(url) if _serves_image(c)),
                       None)
        if smaller is None and width:
            smaller = _proxy_photo(url, width)
        _PHOTO_CACHE[key] = smaller or url
    return _PHOTO_CACHE[key]


def _proxy_photo(url: str, width: int) -> Optional[str]:
    """Our own resizing proxy, if it will accept this host and we know our URL."""
    site = _site_url().rstrip("/")
    if not site:
        return None
    try:
        from app import _IMG_HOSTS
    except Exception:
        return None                        # no app context: leave it alone
    host = urlsplit(url).netloc
    if host not in _IMG_HOSTS:
        return None
    return f"{site}/img?u={quote(url, safe='')}&w={int(width)}"


def _tile(dog: Dog, edge: int, img_class: str, cell_class: str,
          pad_right: int, mso_fallback: bool, caption: bool = True,
          send_id: int = None) -> str:
    """One square photo tile. Width and height come from the same number.

    `caption` carries the dog's name and rescue under the photo. The digest
    needs it — that is someone deciding which dog to open. The goodbye doesn't:
    nobody is choosing there, and the photos are the whole point. The name
    still rides in the img alt either way, so a blocked-image render and a
    screen reader both keep it.
    """
    # 2x the tile, so it stays sharp on a retina phone without paying for the
    # original.
    photo = _email_photo(dog.primary_photo(), width=edge * 2)
    if not photo:
        return ""
    src = html.escape(photo)
    alt = html.escape(dog.name)
    square = (f'<img src="{src}" width="{edge}" height="{edge}" alt="{alt}" '
              f'class="{img_class}" style="width:{edge}px;height:{edge}px;'
              f'object-fit:cover;border-radius:14px;display:block;border:0;">')
    if mso_fallback:
        # Outlook on Windows has no object-fit and would stretch a portrait
        # photo to fill the square. Letting it size on width alone keeps the
        # dog in proportion; the row ends up ragged rather than distorted.
        img = (f'<!--[if mso]><img src="{src}" width="{edge}" alt="{alt}" '
               f'style="display:block;border:0;"><![endif]-->'
               f'<!--[if !mso]><!-->{square}<!--<![endif]-->')
    else:
        img = square
    if caption:
        # 14px under the photo is the gap between a caption and the next row.
        pad_bottom, words = 14, f"""
          <div style="font:600 15px -apple-system,Segoe UI,Roboto,sans-serif;
                      color:#1d1d1f;margin-top:7px;">{html.escape(dog.name)}</div>
          <div style="font:400 12.5px -apple-system,Segoe UI,Roboto,sans-serif;
                      color:#6e6e73;">{html.escape(dog.source_label)}</div>"""
    else:
        # With nothing under the photo, 14px is a hole. Matching the gutter
        # makes the gaps between tiles equal in both directions.
        pad_bottom, words = GUTTER, ""
    return f"""
      <td class="{cell_class}" width="{edge}" style="width:{edge}px;
                 padding:0 {pad_right}px {pad_bottom}px 0;vertical-align:top;">
        <a href="{html.escape(_dog_link(dog, send_id))}" style="text-decoration:none;">
          {img}{words}
        </a>
      </td>"""


def _grid(dogs: List[Dog], cols: int, edge: int, table_class: str,
          img_class: str, cell_class: str, hidden: bool,
          mso_fallback: bool, caption: bool = True,
          align: str = "center", send_id: int = None) -> str:
    """A table of square tiles, `cols` across.

    Four dogs go two across rather than three-then-one: a row holding a single
    tile reads as something that failed to load.

    `align` is centre by default, which is right for the digest and the goodbye
    where the grid is the whole content of the mail. An event block is a left
    ragged column — title, date, address, link — and a centred row of photos
    inside it reads as belonging to something else.
    """
    if not dogs:
        return ""
    if cols == 3 and len(dogs) == 4:
        cols = 2
    rows = ""
    for i in range(0, len(dogs), cols):
        chunk = dogs[i:i + cols]
        cells = "".join(
            _tile(d, edge, img_class, cell_class,
                  0 if j == len(chunk) - 1 else GUTTER, mso_fallback, caption,
                  send_id)
            for j, d in enumerate(chunk))
        rows += f"<tr>{cells}</tr>"
    hide = "display:none;mso-hide:all;" if hidden else ""
    # `align="left"` on a table *floats* it — the next element wraps around the
    # photos instead of sitting under them, which put an event's button beside
    # its own faces and the following event's title alongside them. A table is
    # block-level and already sits left, so left alignment is the attribute's
    # absence plus margin:0. Only "center" gets an align attribute.
    if align == "center":
        attrs, margin = ' align="center"', "margin:0 auto;"
    else:
        attrs, margin = "", "margin:0;"
    return (f'<table class="{table_class}" cellpadding="0" cellspacing="0"'
            f'{attrs} style="border-collapse:collapse;{margin}'
            f'{hide}">{rows}</table>')


def _more_line(count: int, cls: str, hidden: bool) -> str:
    """'+ N more on the site', per layout.

    The two layouts show different numbers of dogs, so they need different
    numbers here. Only one is ever visible, and the phone one is the base — a
    client that ignores media queries shows the phone grid, so it has to read
    the phone count or the sum wouldn't add up.
    """
    if count < 1:
        return ""
    hide = "display:none;mso-hide:all;" if hidden else ""
    return (f'<p class="{cls}" style="font:400 14px -apple-system,Segoe UI,'
            f'Roboto,sans-serif;color:#6e6e73;text-align:center;'
            f'margin:4px 0 0;{hide}">+ {count} more on the site</p>')


def _footer(unsubscribe_for: str = None) -> str:
    """The wordmark, and an unsubscribe link under it if the mail carries one.

    Everything that used to sit here — the date, the cadence reminder, the
    "you're getting this because you signed up at luvd.com" line — is gone at
    the owner's request. See HANDOFF.md: with no reason-for-receipt line and no
    postal address, these no longer carry the sender identification CAN-SPAM
    asks of commercial bulk mail.

    #6e6e73 rather than the #98989d this used to be. Both read as quiet grey,
    but #98989d on white is 2.5:1 and #6e6e73 is 5.1:1, which clears the 4.5:1
    minimum. The hierarchy comes from size and weight instead of from being too
    faint to read.
    """
    link = ""
    if unsubscribe_for:
        link = (f'<br><a href="{html.escape(unsub_url(unsubscribe_for))}" '
                f'style="color:#6e6e73;text-decoration:underline;">'
                f'Unsubscribe</a>')
    return (f'<p style="font:700 12px -apple-system,Segoe UI,Roboto,sans-serif;'
            f'color:#6e6e73;text-align:center;letter-spacing:.09em;'
            f'margin:26px 0 0;">LUVD'
            f'<span style="font-weight:400;letter-spacing:0;">{link}</span></p>')


def _logo() -> str:
    """The wordmark, in place of the old text eyebrow.

    Most clients block remote images by default and this is now the only thing
    naming the sender, so the alt text is styled to read as the wordmark: red,
    bold, and sized to sit where the logo would have been.
    """
    return (f'<img src="{html.escape(_abs(LOGO_FILE))}" '
            f'width="{LOGO_W}" height="{LOGO_H}" alt="LUVD" '
            f'style="width:{LOGO_W}px;height:{LOGO_H}px;display:block;'
            f'margin:0 auto;border:0;font:700 32px -apple-system,Segoe UI,'
            f'Roboto,sans-serif;color:#FF002E;letter-spacing:-.01em;'
            f'text-align:center;text-decoration:none;">')


# The phone layout is the base and the desktop layout is the enhancement, which
# is the reverse of the obvious way round. It has to be: the widest grid is the
# one that can overflow, and every client that fails to apply this block gets
# the base. Outlook on Windows ignores media queries, and the Gmail app signed
# into a non-Gmail account strips the whole <style> element — both used to land
# on the three-across grid, which is 548px of content in a 390px screen. Now
# both land on two-across, which fits anything.
#
# The cost, accepted deliberately: Outlook on Windows is a desktop client and
# will show the phone layout on a wide screen. Sparse, not broken.
_STYLE = f"""
    body,table,td,a{{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
    @media only screen and (min-width:601px){{
      .g-desk{{display:table !important;}}
      .m-desk{{display:block !important;}}
      .g-phone,.m-phone{{display:none !important;}}
    }}
    @media only screen and (min-width:376px){{
      .ph-img{{width:{TILE_PHONE_SMALL}px !important;
               height:{TILE_PHONE_SMALL}px !important;}}
      .ph-cell{{width:{TILE_PHONE_SMALL}px !important;}}
    }}
    @media only screen and (min-width:481px){{
      .ph-img{{width:{TILE_PHONE}px !important;
               height:{TILE_PHONE}px !important;}}
      .ph-cell{{width:{TILE_PHONE}px !important;}}
    }}
    @media only screen and (max-width:480px){{
      .card{{padding-left:18px !important;padding-right:18px !important;}}
    }}
    @media only screen and (max-width:375px){{
      .card{{padding-left:14px !important;padding-right:14px !important;}}
    }}"""
# The card's own padding is the one thing still stepped DOWN from an inline
# base rather than up: 28px is right for the 560px card, and a client with no
# media queries is either a phone showing 124px tiles, which fit inside it
# anyway, or a wide desktop client that wants the roomier padding.


def _document(body: str) -> str:
    """Wrap a mail body in the shell the media queries need.

    The grid steps up to the desktop layout at 601px, which needs a real
    <style> block and a viewport meta, and neither works in a bare fragment.
    Losing this block is survivable now — see _STYLE — but it still costs the
    wider layout everywhere. color-scheme is declared light so clients that
    force-invert leave the white card alone.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<style>
    :root{{color-scheme:light;supported-color-schemes:light;}}{_STYLE}
</style>
</head>
<body style="margin:0;padding:0;background:#fbfbfd;">{body}</body>
</html>"""


def _preheader(text: str) -> str:
    """The line clients show next to the subject, before anything is opened.

    Hidden in the body itself: there is no header for it, so the preview is
    simply the first text a client finds, which without this is whatever the
    opening paragraph happens to start with. The trailing zero-width joiners
    are padding — a client takes as much text as it wants for the preview, and
    without them it runs past this line and into the paragraph below.
    """
    pad = "&#847;&zwnj;&nbsp;" * 60
    return (f'<div style="display:none;font-size:1px;line-height:1px;'
            f'max-height:0;max-width:0;opacity:0;overflow:hidden;'
            f'mso-hide:all;">{html.escape(text)}{pad}</div>')


def _city_path(city: str = None) -> str:
    """The site-relative path of a city's page, for links that get tracked."""
    return cities.resolve(city).path if city else "/"


def build_html(dogs: List[Dog], for_date: date = None, unsubscribe_for: str = None,
               city: str = None, send_id: int = None) -> str:
    # for_date is unused since the footer stopped printing the date. It stays
    # in the signature because check.py passes it and a digest is still a thing
    # that happened on a day; dropping it would be a breaking change for the
    # sake of one line.
    #
    # `city` is the digest's own city, and it decides one thing: where the
    # button at the bottom goes. The dogs above it are already this city's —
    # check.py only ever hands us `new_today` from one city's sources — so this
    # is the last place the mail could still point somewhere else.
    n = len(dogs)
    with_photos = [d for d in dogs if d.photos]
    desk = with_photos[:PREVIEW_COUNT]
    phone = with_photos[:PHONE_PREVIEW_COUNT]
    # Two across, an odd number leaves the last dog alone on its own row, which
    # reads as a photo that failed to load. Drop it into "+ N more on the site"
    # instead — the counts still add up and the grid stays a rectangle. Only
    # from three up: one dog is a single row, not an orphaned one.
    if len(phone) > 1 and len(phone) % 2:
        phone = phone[:-1]

    # Both grids point at the same photo URLs, so the one that stays hidden
    # costs no extra bytes on the wire. The phone grid is the visible base and
    # the desktop grid is hidden until the min-width query reveals it; the mso
    # fallback rides with whichever one Outlook ends up showing, which is now
    # the phone one.
    grid_desk = _grid(desk, 3, TILE_DESKTOP, "g-desk", "dk-img", "dk-cell",
                      hidden=True, mso_fallback=False, send_id=send_id)
    grid_phone = _grid(phone, 2, TILE_PHONE_TINY, "g-phone", "ph-img",
                       "ph-cell", hidden=False, mso_fallback=True,
                       send_id=send_id)

    more = (_more_line(n - len(phone), "m-phone", hidden=False)
            + _more_line(n - len(desk), "m-desk", hidden=True))

    # The count moved out of the subject, so the preview carries it. A reader
    # deciding whether to open still gets the number, and the subject stays
    # short enough to survive a phone's truncation.
    face = "face" if n == 1 else "faces"
    return _document(f"""{_preheader(f"{n} new {face}, all looking for a couch to call home")}
<div style="background:#fbfbfd;padding:32px 16px;">
  <div class="card" style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    {_logo()}
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 6px;">
      {n} new dog{'' if n == 1 else 's'} today</h1>
    <p style="font:400 15px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:0 0 26px;">Across every {html.escape(cities.resolve(city).short)} rescue we follow.</p>

    {grid_desk}{grid_phone}
    {more}

    <a href="{html.escape(_track(_city_path(city), send_id))}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:24px;">
      See all {n} dog{'' if n == 1 else 's'} →</a>

    {_footer(unsubscribe_for)}
  </div>
  {_pixel(send_id)}
</div>""")


def _bulk_headers(to_email: str) -> dict:
    """One-click unsubscribe headers — Gmail/Yahoo require these for bulk
    senders, and they keep spam-report rates from hurting deliverability."""
    return {
        "List-Unsubscribe": f"<{unsub_url(to_email)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def build_digest_text(dogs: List[Dog], city: str = None,
                      unsubscribe_for: str = None) -> str:
    """The plain-text half of the digest.

    The welcome, the events digest and the goodbye all had one; the daily
    digest — the only one of the four that goes out every morning to everybody
    — did not, and shipped as HTML alone. A message with no text/plain
    alternative is a long-standing spam signal, because that is what bulk
    senders who do not care look like.

    Deliberately the same facts in the same order as the HTML, not a teaser.
    A filter that scores the two parts against each other treats a text half
    that says less than the HTML as an attempt to hide something.
    """
    # Imported here rather than at module scope, matching build_html: page
    # imports emailer for the digest preview, so a top-level import is a cycle.
    from page import dog_path

    c = cities.resolve(city)
    n = len(dogs)
    lines = [f"{n} new dog in {c.short} today" if n == 1
             else f"{n} new dogs in {c.short} today", ""]
    for d in dogs:
        lines.append(d.name)
        facts = [f for f in (d.breed, d.age, d.sex, d.weight) if f]
        if facts:
            lines.append("  " + " · ".join(facts))
        if d.source_label:
            lines.append(f"  {d.source_label}")
        lines.append(f"  {_site_url()}{dog_path(d)}")
        lines.append("")
    lines += [f"See every {c.short} dog: {_city_page(city)}", "", "--", "LUVD"]
    if unsubscribe_for:
        lines.append(f"Unsubscribe: {unsub_url(unsubscribe_for)}")
    return "\n".join(lines) + "\n"


def send_digest(to_email: str, dogs: List[Dog], for_date: date = None,
                city: str = None, send_id: int = None):
    n = len(dogs)
    return send_email(
        to_email,
        "A new dog just dropped 🐶" if n == 1 else "New dogs just dropped 🐶",
        html_body=build_html(dogs, for_date, unsubscribe_for=to_email, city=city,
                             send_id=send_id),
        text_body=build_digest_text(dogs, city, unsubscribe_for=to_email),
        headers=_bulk_headers(to_email),
    )


SAVED_COUNT = 6
SAVED_PHONE_COUNT = 4


def saved_link(dogs: List[Dog], city: str = None) -> str:
    """The reader's list as a URL — the same address Copy link builds.

    This is the part of the mail that is actually worth keeping. A saved list
    lives in localStorage, which is one browser's and which Safari evicts after
    seven days without a visit; a link in an inbox outlives both, and opens the
    list on any device. The mail is the backup the button is named for.
    """
    ids = ",".join(d.id for d in dogs if d.id)
    path = _city_path(city)
    return _abs(f"{path}?saved={quote(ids, safe=',:')}")


def build_saved_html(dogs: List[Dog], city: str = None,
                     unsubscribe_for: str = None, send_id: int = None) -> str:
    n = len(dogs)
    with_photos = [d for d in dogs if d.photos]
    desk = with_photos[:SAVED_COUNT]
    phone = with_photos[:SAVED_PHONE_COUNT]
    if len(phone) > 1 and len(phone) % 2:
        phone = phone[:-1]

    grid_desk = _grid(desk, 3, TILE_DESKTOP, "g-desk", "dk-img", "dk-cell",
                      hidden=True, mso_fallback=False, send_id=send_id)
    grid_phone = _grid(phone, 2, TILE_PHONE_TINY, "g-phone", "ph-img",
                       "ph-cell", hidden=False, mso_fallback=True,
                       send_id=send_id)
    more = (_more_line(n - len(phone), "m-phone", hidden=False)
            + _more_line(n - len(desk), "m-desk", hidden=True))

    dog_word = "dog" if n == 1 else "dogs"
    link = saved_link(dogs, city)
    return _document(f"""{_preheader(f"Your {n} saved {dog_word}, kept somewhere safer than a browser tab")}
<div style="background:#fbfbfd;padding:32px 16px;">
  <div class="card" style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    {_logo()}
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 6px;">
      Your {n} saved {dog_word}</h1>
    <p style="font:400 15px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:0 0 26px;">
      Keep this email &mdash; the link below reopens your list on any device.</p>

    {grid_desk}{grid_phone}
    {more}

    <a href="{html.escape(_track_saved(link, send_id))}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:24px;">
      Open my saved list &rarr;</a>

    <p style="font:400 13px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:18px 0 0;">
      These dogs are listed by rescues we follow, not by us. Availability can
      change before we see it &mdash; the rescue&rsquo;s own page is always the
      last word.</p>

    {_footer(unsubscribe_for)}
  </div>
  {_pixel(send_id)}
</div>""")


def _track_saved(url: str, send_id: int = None) -> str:
    """The saved link, counted. Split out because unlike every other tracked
    link this one is already absolute — it carries a query string the path
    helper would have to rebuild — so it is turned back into a path here
    rather than teaching _track() a second input shape."""
    if not send_id:
        return url
    site = _site_url().rstrip("/")
    path = url[len(site):] if url.startswith(site) else url
    return _abs(f"/c/{int(send_id)}?u={quote(path, safe='/')}")


def build_saved_text(dogs: List[Dog], city: str = None,
                     unsubscribe_for: str = None) -> str:
    n = len(dogs)
    lines = [f"Your {n} saved dog" + ("" if n == 1 else "s"), ""]
    for d in dogs:
        lines.append(d.name)
        facts = [f for f in (d.breed, d.age, d.sex, d.weight) if f]
        if facts:
            lines.append("  " + " \u00b7 ".join(facts))
        if d.source_label:
            lines.append(f"  {d.source_label}")
        lines.append(f"  {_dog_link(d)}")
        lines.append("")
    lines += [f"Open your list on any device: {saved_link(dogs, city)}", "",
              "These dogs are listed by rescues we follow, not by us.",
              "Availability can change before we see it.", "", "--", "LUVD"]
    if unsubscribe_for:
        lines.append(f"Unsubscribe: {unsub_url(unsubscribe_for)}")
    return "\n".join(lines) + "\n"


def send_saved(to_email: str, dogs: List[Dog], city: str = None,
               send_id: int = None):
    """Mail somebody their own saved list, because they asked for it.

    No List-Unsubscribe headers and no unsubscribe link: this is a one-off
    transactional mail somebody pressed a button to receive, not bulk mail
    they are on a list for. Sending it with an unsubscribe footer would offer
    to remove them from something they may not even be subscribed to.
    """
    n = len(dogs)
    return send_email(
        to_email,
        "Your saved dog on LUVD" if n == 1 else f"Your {n} saved dogs on LUVD",
        html_body=build_saved_html(dogs, city, send_id=send_id),
        text_body=build_saved_text(dogs, city),
    )


def _montage() -> str:
    """The welcome's polaroid strip, or nothing at all.

    Only ever emitted when the file is really on disk. It is written by the
    nightly run, so a box that has deployed but not yet run one has no montage
    — and an <img> pointing at a URL that 404s is worse than a mail without a
    picture in it. Same bargain the goodbye makes with an unreadable roster.

    The alt text has to stand in for the whole block, because most clients
    block remote images by default and this one carries no link and no
    information. It says what the picture is, so it reads as a described image
    rather than a hole.

    Both dimensions come from montage.DISPLAY_* rather than being written out
    here, because the canvas carries bleed around the polaroids so their shadows
    are not clipped: the file is 1080x450 for a 504x210 box, and a width guessed
    from the old aspect ratio would squash it. Outlook uses the attributes and
    ignores the CSS, so the attributes have to be right on their own — and the
    CSS keeps height:auto so a phone narrower than 504px scales it rather than
    holding a fixed height against a fluid width.
    """
    try:
        import montage
        if not montage.exists():
            return ""
        src = f"{_abs('/' + montage.FILENAME)}?v={montage.cache_tag()}"
        w, h = montage.DISPLAY_W, montage.DISPLAY_H
    except Exception:
        return ""
    return (f'<img src="{html.escape(src)}" width="{w}" height="{h}" '
            f'alt="Polaroid snapshots of dogs waiting at New York City rescues" '
            f'style="width:100%;max-width:{w}px;height:auto;display:block;'
            f'margin:24px auto 0;border:0;font:400 14px -apple-system,Segoe UI,'
            f'Roboto,sans-serif;color:#6e6e73;text-align:center;">')


def _welcome_place(city: str = None) -> str:
    """"in Los Angeles", or "in your city" when we genuinely don't know.

    Naming it is the whole point of a per-city list: someone who signed up on
    the LA page and is told about "the top rescues in your city" has no way to
    tell whether we understood which city that was. The fallback survives for
    the one case where it is honest — a caller with no city at all.
    """
    c = cities.get(city) if city else None
    return f"in {c.name}" if c else "in your city"


def build_welcome_html(to_email: str, city: str = None) -> str:
    """The one-time signup confirmation.

    Deliberately reads nothing from the database: this is the first mail an
    address ever gets, and it must not be able to arrive empty or broken
    because a scrape came back with nothing. The montage is a file written by
    last night's run, not a live lookup, and it is omitted if it isn't there.
    """
    site = html.escape(_city_page(city))
    place = html.escape(_welcome_place(city))
    return _document(f"""{_preheader("Let's find you a friend")}
<div style="background:#fbfbfd;padding:32px 16px;">
  <div class="card" style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    {_logo()}
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 18px;">
      You're on the list!</h1>

    <p style="font:400 16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              margin:0 0 14px;">
      Each day we find dogs from the top rescues {place} and share them
      with you. Our goal is to help every animal find their forever home.</p>
    <p style="font:400 16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              margin:0;">
      Thanks for joining!</p>
{_montage()}
    <a href="{site}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:26px;">
      See today's dogs →</a>

    {_footer(to_email)}
  </div>
</div>""")


def build_welcome_text(to_email: str, city: str = None) -> str:
    """Plain-text alternative. A first-contact mail with no text part looks
    materially worse to spam filters than one with it."""
    return f"""You're on the list!

Each day we find dogs from the top rescues {_welcome_place(city)} and share
them with you. Our goal is to help every animal find their forever home.

Thanks for joining!

See today's dogs: {_city_page(city)}

--
LUVD
Unsubscribe: {unsub_url(to_email)}
"""


def _ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 11 -> 11th, 21 -> 21st."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _event_when(ev: dict) -> str:
    """"Saturday August 1st, 2026 · 11 am – 1 pm", or the day alone if no time.

    Written the way somebody says it out loud, with the ordinal and the year.
    The year is redundant on its face — every event in this mail is inside seven
    days — but this line is the one thing a reader may screenshot, forward or put
    in a calendar, and at that point it has left the email that dated it.
    """
    try:
        d = date.fromisoformat(ev["starts_on"])
        day = f"{d.strftime('%A %B')} {_ordinal(d.day)}, {d.year}"
    except (ValueError, KeyError):
        day = ev.get("starts_on") or ""
    start, end = (ev.get("starts_at") or "").strip(), (ev.get("ends_at") or "").strip()
    if start and end:
        clock = f"{start} – {end}"
    else:
        clock = start or end
    return f"{day} · {clock}" if clock else day


def _rescue_page(rescue: str) -> str:
    """The rescue's own page on LUVD, if this run actually wrote one.

    `rescue` on an event is a display label, not a source key — the sheet can
    carry an event run by an organisation LUVD does not scrape — so the page may
    not exist. The file on disk is the honest test, the same one _dog_link()
    uses: a link into a 404 is worse than no link.
    """
    try:
        from page import slugify
        path = f"/rescue/{slugify(rescue)}"
    except Exception:
        return ""
    return _abs(path) if (PUBLIC / f"{path.lstrip('/')}.html").is_file() else ""


def _event_cta(ev: dict) -> str:
    """One small link per event, to whatever is genuinely there to look at.

    A per-event link rather than a rescue logo, and that is a deliberate trade.
    Logos would need one image per row from hosts we do not control: Petstablished
    hands out its own grey placeholder for most rescues, and every major client
    blocks remote images by default — so a logo column would be three empty boxes
    as often as not, in the exact spot the eye lands. A text link always renders.

    Order is what the reader most wants: the event's own page if the sheet gives
    one, otherwise that rescue's dogs on LUVD, otherwise nothing at all rather
    than a link that goes somewhere generic.
    """
    if ev.get("url"):
        return html.escape(ev["url"]), "View Event Details"
    page = _rescue_page(ev.get("rescue") or "")
    if page:
        # Not "See Korean K9 Rescue's dogs": the rescue's name is already on the
        # line above, so repeating it makes the button the longest thing in the
        # block. Two buttons of a fixed width read as a set; two that grow with
        # whatever the sheet typed read as ragged.
        return html.escape(page), "See Adoptable Dogs"
    return "", ""


EVENT_FACE_COUNT = 3
EVENT_FACE_EDGE = 92
# Photos across the whole mail, not per event. Rescue photo hosts mostly publish
# one rendition and ignore width parameters — see _email_photo — so a 92px tile
# can still be a 3MB original, and three faces on each of six events would be a
# mail nobody's phone wants. Nine is what the digest already ships at six tiles
# plus a montage, so it is a weight this list has received before.
EVENT_FACE_TOTAL = 9


def _faces_per_event(count: int) -> int:
    """How many dogs each event may show, given how many events there are.

    Shrinks rather than truncating: a busy week reduces every event to one face
    instead of illustrating the first three and leaving the rest bare, which
    would read as the later events being an afterthought.
    """
    if count <= 0:
        return 0
    return max(1, min(EVENT_FACE_COUNT, EVENT_FACE_TOTAL // count))


def rescue_faces(rescue: str, city: str = None,
                 limit: int = EVENT_FACE_COUNT) -> List[Dog]:
    """A few photographed dogs currently with one rescue, from its city's page.

    Reads the published page rather than the database for the same reason
    roster() does: the page's DOGS payload is the only thing on disk that knows
    photo URLs, and this runs from a job that holds no dogs of its own.

    Per city, unlike roster(), which only ever reads index.html — an LA event
    must not be illustrated with Brooklyn dogs.

    Matched on the rescue's display label, because that is what the sheet
    carries and what the payload records. No match, no faces: the sheet may name
    an organisation LUVD does not follow, and every failure returns [] on
    purpose. A photoless event block is fine; a broken one is not.
    """
    label = " ".join((rescue or "").split()).lower()
    if not label:
        return []
    try:
        page_file = cities.resolve(city).file
        text = (PUBLIC / page_file).read_text(encoding="utf-8")
        m = _DOGS_JSON.search(text)
        if not m:
            return []
        pool = [
            Dog(id=r.get("id") or "", name=r.get("name") or "",
                source=r.get("source") or "",
                source_label=r.get("source_label") or "",
                url=r.get("url") or "", breed=r.get("breed") or "",
                photos=[p for p in (r.get("photos") or []) if p])
            for r in json.loads(m.group(1))
            if " ".join((r.get("source_label") or "").split()).lower() == label
        ]
        pool = [d for d in pool if d.name and d.photos]
        return random.sample(pool, min(limit, len(pool)))
    except Exception:
        return []


def _event_faces(ev: dict, city: str = None, limit: int = EVENT_FACE_COUNT) -> str:
    """Three of that rescue's dogs under the event, or nothing.

    Deliberately *not* captioned "dogs at this event". No rescue publishes which
    animals it brings — that is decided on the morning — so naming these as
    attendees would be the one misdirection this email cannot afford: somebody
    travels across a city for a dog who was never going to be there. The
    disclaimer under the header says what they actually are, once, rather than
    three times.

    They are still worth showing. An event block is a date and an address, and
    these are the reason anybody goes.
    """
    faces = rescue_faces(ev.get("rescue") or "", city, limit)
    if not faces:
        return ""
    return ('<div style="margin-top:10px;">'
            + _grid(faces, len(faces), EVENT_FACE_EDGE, "ev-grid", "ev-img",
                    "ev-cell", hidden=False, mso_fallback=True, caption=False,
                    align="left")
            + '</div>')


def _event_block(ev: dict, city: str = None,
                 faces: int = EVENT_FACE_COUNT) -> str:
    """One event: what it is, when, where, who is running it, and one link."""
    where_bits = [b for b in (ev.get("location"), ev.get("address")) if b]
    where = " · ".join(html.escape(b) for b in where_bits)
    title = html.escape(ev.get("title") or "Adoption event")
    note = (f'<div style="font:400 14px/1.5 -apple-system,Segoe UI,Roboto,'
            f'sans-serif;color:#6e6e73;margin-top:5px;">'
            f'{html.escape(ev["note"])}</div>') if ev.get("note") else ""
    href, label = _event_cta(ev)
    # Outlined, not filled: the solid red button at the foot of the mail is the
    # one action for the whole email, and three filled buttons above it would
    # each compete with it and with each other. Left-aligned with everything
    # else in the block.
    cta = ("" if not href else f"""
      <div style="margin-top:12px;">
        <a href="{href}" style="display:inline-block;font:600 14px
                  -apple-system,Segoe UI,Roboto,sans-serif;color:#FF002E;
                  text-decoration:none;padding:9px 16px;border-radius:980px;
                  border:1.5px solid #FF002E;">{html.escape(label)}</a>
      </div>""")
    return f"""
    <div style="border-top:1px solid #ececf0;padding:16px 0 4px;">
      <div style="font:700 17px -apple-system,Segoe UI,Roboto,sans-serif;
                  color:#1d1d1f;letter-spacing:-.01em;">{title}</div>
      <div style="font:600 14px -apple-system,Segoe UI,Roboto,sans-serif;
                  color:#FF002E;margin-top:4px;">
        {html.escape(_event_when(ev))}</div>
      <div style="font:400 15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
                  color:#1d1d1f;margin-top:4px;">
        {html.escape(ev.get("rescue") or "")}{(" · " + where) if where else ""}</div>
      {note}{_event_faces(ev, city, faces)}{cta}
    </div>"""


def build_events_html(events: List[dict], city: str = None,
                      unsubscribe_for: str = None) -> str:
    """The Monday "what's on this week" mail for one city.

    Never built empty: check_events refuses to send a mail with no events in it,
    because "here is this week's events: none" is worse than silence and trains
    people to ignore the next one.
    """
    c = cities.resolve(city)
    n = len(events)
    site = html.escape(_city_page(city))
    per_event = _faces_per_event(n)
    blocks = "".join(_event_block(e, city, per_event) for e in events)
    # One line, and no city in it: the subject line already carries the city, the
    # button at the foot says it again, and every event under this is in it. The
    # sentences that used to follow — how turning up is the fastest way to meet a
    # dog, and what the photos are — were both explaining things the blocks below
    # already show.
    head = (f"{n} place to meet your future friend this week" if n == 1
            else f"{n} places to meet your future friend this week")
    return _document(f"""{_preheader(head)}
<div style="background:#fbfbfd;padding:32px 16px;">
  <div class="card" style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    {_logo()}
    <h1 style="font:700 26px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 6px;">
      Meet a dog in person</h1>
    <p style="font:400 15.5px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
              color:#6e6e73;text-align:center;margin:0 0 18px;">
      {html.escape(head)}.</p>
    {blocks}
    <a href="{site}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:26px;">
      See every {html.escape(c.short)} dog →</a>
    {_footer(unsubscribe_for)}
  </div>
</div>""")


def build_events_text(events: List[dict], city: str = None,
                      unsubscribe_for: str = None) -> str:
    c = cities.resolve(city)
    n = len(events)
    # Matches the HTML's one line, so the two parts of the same mail do not open
    # with different sentences.
    lines = [f"{n} place to meet your future friend this week" if n == 1
             else f"{n} places to meet your future friend this week", ""]
    for ev in events:
        lines.append(ev.get("title") or "Adoption event")
        lines.append(f"  {_event_when(ev)}")
        who = ev.get("rescue") or ""
        where = " · ".join(b for b in (ev.get("location"), ev.get("address")) if b)
        if who or where:
            lines.append(f"  {who}{(' · ' + where) if where else ''}")
        if ev.get("note"):
            lines.append(f"  {ev['note']}")
        if ev.get("url"):
            lines.append(f"  {ev['url']}")
        lines.append("")
    lines += [f"See every {c.short} dog: {_city_page(city)}", "", "--", "LUVD"]
    if unsubscribe_for:
        lines.append(f"Unsubscribe: {unsub_url(unsubscribe_for)}")
    return "\n".join(lines) + "\n"


def send_events_digest(to_email: str, events: List[dict], city: str = None):
    """This week's in-person events for one city.

    A separate send from the dog digest on purpose. check.py returns before
    mailing when no dogs arrived overnight, so folding events into that mail
    would make them hostage to whether any dog turned up — and a Monday with no
    new dogs is exactly a Monday when an event matters most.
    """
    c = cities.resolve(city)
    n = len(events)
    subject = (f"One place to meet a dog in {c.short} this week 🐶" if n == 1
               else f"{n} places to meet a dog in {c.short} this week 🐶")
    return send_email(
        to_email,
        subject,
        html_body=build_events_html(events, city, unsubscribe_for=to_email),
        text_body=build_events_text(events, city, unsubscribe_for=to_email),
        headers=_bulk_headers(to_email),
    )


def send_welcome(to_email: str, city: str = None):
    """One-time confirmation that someone is subscribed. Sent at signup only —
    the cadence after this is still 'nothing unless there are new dogs'.

    ``city`` is the list they just joined, so the mail can name it and link to
    its page. Someone adding a second city gets a second welcome naming that
    one, which is what ``db.add_subscriber`` returning True for a new city row
    already arranges.
    """
    return send_email(
        to_email,
        "You're on the list! 🐶",
        html_body=build_welcome_html(to_email, city),
        text_body=build_welcome_text(to_email, city),
        headers=_bulk_headers(to_email),
    )


# The dog payload the page renders from, written by page.render().
_DOGS_JSON = re.compile(r"^const DOGS = (\[.*\]);$", re.M)


def _page_dogs(city: str = None) -> dict:
    """Every dog on one city's rendered page, keyed by id.

    The page is the roster for anything running in the web process, which never
    scrapes and holds no dogs of its own. Read rather than cached: this is on a
    path somebody pressed a button for, not a hot loop, and a cache here would
    serve yesterday's dogs the morning after a render.
    """
    name = "index.html" if not city or cities.resolve(city).path == "/" \
        else cities.resolve(city).path.strip("/") + ".html"
    try:
        m = _DOGS_JSON.search((PUBLIC / name).read_text(encoding="utf-8"))
        if not m:
            return {}
        out = {}
        for r in json.loads(m.group(1)):
            if r.get("id"):
                out[r["id"]] = r
        return out
    except Exception:
        return {}


def dogs_by_id(ids, city: str = None) -> List[Dog]:
    """Dog objects for a saved list, in the order the reader saved them.

    Searches the reader's own city first and then every other live one, because
    a saved list is not bound to a city — somebody can heart a dog in Brooklyn,
    open the LA page and heart another, and the list holds both. Ids that match
    nothing are dropped rather than raising: a list can name a dog that has
    since been adopted, and the rest of it is still worth mailing.
    """
    pages, seen = [], set()
    for c in [city] + [c for c in cities.all_codes() if cities.is_live(c)]:
        key = cities.canon(c) if c else ""
        if key in seen:
            continue
        seen.add(key)
        pages.append(_page_dogs(c))

    out = []
    for dog_id in ids:
        row = next((p[dog_id] for p in pages if dog_id in p), None)
        if not row:
            continue
        out.append(Dog(
            id=row.get("id") or "",
            name=row.get("name") or "",
            source=row.get("source") or "",
            source_label=row.get("source_label") or "",
            url=row.get("url") or "",
            photos=[ph for ph in (row.get("photos") or []) if ph],
            breed=row.get("breed") or "",
            age=row.get("age") or "",
            sex=row.get("sex") or "",
            size=row.get("size") or "",
            weight=row.get("weight") or "",
            location=row.get("location") or "",
            description=row.get("description") or "",
            attributes=row.get("attributes") or [],
            fee=row.get("fee") or None,
            adopt_url=row.get("cta_url") or row.get("url") or "",
        ))
    return out


def roster(limit: int) -> List[Dog]:
    """Up to `limit` photographed dogs, picked at random from the last page.

    The goodbye goes out from the web process, which never scrapes and holds no
    dogs of its own. index.html carries the same payload the site renders from
    and is the only thing on disk that knows photo URLs, so it is the roster.

    Every failure returns an empty list on purpose. The digest can assume dogs
    exist because it only runs when there are new ones; this runs whenever
    somebody unsubscribes, which may be the morning the page is missing,
    half-written or empty — and a goodbye that raises, or that arrives full of
    broken images, is worse than a goodbye with no photos in it.
    """
    try:
        m = _DOGS_JSON.search((PUBLIC / "index.html").read_text(encoding="utf-8"))
        if not m:
            return []
        pool = [
            Dog(id=r.get("id") or "", name=r.get("name") or "",
                source=r.get("source") or "",
                source_label=r.get("source_label") or "",
                url=r.get("url") or "", breed=r.get("breed") or "",
                photos=[p for p in (r.get("photos") or []) if p])
            for r in json.loads(m.group(1))
        ]
        pool = [d for d in pool if d.name and d.photos]
        return random.sample(pool, min(limit, len(pool)))
    except Exception:
        return []


def build_goodbye_html(to_email: str, dogs: List[Dog] = None) -> str:
    """The unsubscribe confirmation. Sent once, when someone actually leaves.

    `dogs` is whatever roster() managed to find; an empty list is a supported
    outcome, not a degraded one, and simply drops the grid.

    No unsubscribe link and no List-Unsubscribe headers: they have already
    unsubscribed, and offering it again would suggest it hadn't taken.
    """
    dogs = dogs or []
    site = html.escape(_site_url())
    grid = ""
    if dogs:
        grid = f"""
    <p style="font:400 13px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:26px 0 14px;">
      A few of the dogs still waiting in NYC.</p>
    {_grid(dogs[:GOODBYE_COUNT], 3, TILE_DESKTOP, "g-desk", "dk-img", "dk-cell",
           hidden=True, mso_fallback=False, caption=False)}
    {_grid(dogs[:GOODBYE_PHONE_COUNT], 2, TILE_PHONE_TINY, "g-phone", "ph-img",
           "ph-cell", hidden=False, mso_fallback=True, caption=False)}"""

    return _document(f"""
<div style="background:#fbfbfd;padding:32px 16px;">
  <div class="card" style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    {_logo()}
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 18px;">
      Sorry to see you go</h1>

    <p style="font:400 16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              margin:0;">
      We hope you found a dog you love. If you didn't, or you just miss the
      faces, you can <a href="{site}" style="color:#FF002E;text-decoration:none;
      font-weight:600;">sign up again</a> any time.</p>
{grid}
    <p style="font:400 15px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              text-align:center;margin:28px 0 0;">
      This is the last email you'll get from us.</p>
    {_footer()}
  </div>
</div>""")


def build_goodbye_text(to_email: str, dogs: List[Dog] = None) -> str:
    """Plain-text alternative, and the whole message for anyone reading in
    text — including the closing line, which is the point of the mail.

    The HTML version dropped the names under the photos; this keeps them,
    because here there are no photos and the name plus link is the only thing
    left to drop.
    """
    dogs = dogs or []
    faces = ""
    if dogs:
        faces = "\nA few of the dogs still waiting in NYC:\n" + "".join(
            f"  {d.name} · {d.source_label}\n    {_dog_link(d)}\n"
            for d in dogs[:GOODBYE_COUNT])
    return f"""Sorry to see you go.

We hope you found a dog you love. If you didn't, or you just miss the faces,
you can sign up again any time: {_site_url()}
{faces}
This is the last email you'll get from us.

--
LUVD
"""


def send_goodbye(to_email: str):
    """One transactional goodbye, sent once when an unsubscribe is claimed.

    Deliberately carries no List-Unsubscribe headers: those exist so a client
    can offer a one-click opt-out, and this address has already taken it.
    """
    dogs = roster(GOODBYE_COUNT)
    return send_email(
        to_email,
        "Sorry to see you go 🥹",
        html_body=build_goodbye_html(to_email, dogs),
        text_body=build_goodbye_text(to_email, dogs),
    )
