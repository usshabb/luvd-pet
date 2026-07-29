"""Generate the welcome email's dog montage — four tilted polaroids on white.

Why a flat image and not HTML: email cannot rotate an element or lay text over
a photo with any reliability. Outlook drops CSS transforms entirely and several
clients strip positioning, so an HTML version would degrade into the stacked
photo-with-caption grid the digest already uses. One pre-rendered file renders
identically in every client, and can do the frames, the tilt and the shadows
that make it read as a handful of snapshots rather than a contact sheet.

Rebuilt nightly by check.py from dogs currently listed, so somebody subscribing
today sees dogs actually waiting rather than a frozen launch-day set.
"""
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from imaging import cover, fetch_photo, font

PUBLIC = Path(__file__).parent / "public"
# Served straight off public/ by app.static_files. Kept as a plain filename so
# emailer can check it exists and build the URL from _site_url().
FILENAME = "welcome-montage.jpg"
OUT = PUBLIC / FILENAME

# Rendered at 2x the ~504px the email displays it at, for retina.
W, H = 1000, 392

# Four, in one row. Two rows was the first attempt and it was wrong: the lower
# row lands on the upper row's captions, and pulling it clear makes the image
# 740px tall — a third of a phone screen for a decorative block. One row keeps
# every name visible and the picture wide and short.
#
# Four is the most that leaves a face worth looking at. The email shows this at
# 504px, so each photo lands at ~129px, and at ~77px on a 300px-wide phone
# card. Five would take that to 60px, which is a thumbnail of a dog rather than
# a dog.
COUNT = 4

# Fixed rather than random. The same four angles every night reads as composed;
# re-rolling nightly means the one bad arrangement eventually ships.
# The outer two are held off the edges by more than half their *rotated* width:
# tilting a card pushes a corner out past where the upright frame ended, and a
# clipped corner reads as a crop rather than a composition.
LAYOUT = [
    # (centre x, centre y, degrees) in canvas coordinates
    (160, 190, -5.5),
    (387, 178, 2.5),
    (613, 192, -2.5),
    (840, 180, 5.5),
]
PHOTO = 248               # the square photo inside a frame
BORDER = 17               # white frame on three sides
CAPTION_BAND = 62         # the deeper bottom edge a polaroid caption sits in
CAPTION_SIZE = 34         # ~17px as displayed, ~10px on a 300px phone card
# Cards overlap by ~55px. Names are left-aligned, so a neighbour landing on the
# right edge never reaches one — but only if they are truncated to the width
# that stays visible rather than to the full photo.
NAME_WIDTH = PHOTO - 60
CARD_BG = (255, 255, 255)  # matches the email card, so the frames float on it


def _polaroid(dog, size: int = PHOTO) -> Image.Image:
    """One framed, captioned photo, upright. Raises if the photo won't fetch."""
    frame_w = size + BORDER * 2
    frame_h = size + BORDER + CAPTION_BAND
    card = Image.new("RGBA", (frame_w, frame_h), (255, 255, 255, 255))
    card.paste(cover(fetch_photo(dog.photos[0]), size, size), (BORDER, BORDER))

    # The name in the bottom edge, tucked into the corner — a polaroid caption.
    # Over the photo it would need a scrim to stay legible against an arbitrary
    # picture, and a scrim on four small photos is exactly the clip-art look
    # this is meant to avoid.
    draw = ImageDraw.Draw(card)
    name = (dog.name or "").strip()
    f = font(CAPTION_SIZE, bold=True)
    while len(name) > 1 and draw.textlength(name, font=f) > NAME_WIDTH:
        name = name[:-1]
    if name:
        draw.text((BORDER + 2, size + BORDER + CAPTION_BAND // 2 - 3), name,
                  font=f, fill=(29, 29, 31), anchor="lm")
    return card


def _drop(canvas: Image.Image, card: Image.Image, cx: int, cy: int, deg: float):
    """Rotate a polaroid, lay a soft shadow under it, paste it centred on
    (cx, cy). expand=True keeps the corners; the shadow is the rotated card's
    own alpha, blurred, which is what makes them look stacked rather than
    pasted."""
    card = card.rotate(deg, resample=Image.BICUBIC, expand=True)
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shadow.putalpha(card.getchannel("A").point(lambda a: int(a * 0.30)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(11))
    x, y = cx - card.width // 2, cy - card.height // 2
    canvas.alpha_composite(shadow, (x, y + 7))
    canvas.alpha_composite(card, (x, y))


def build(dogs, out: Path = OUT) -> Path:
    """Write the montage. Raises if it cannot produce a usable one.

    Callers treat that as non-fatal — see check.py. Yesterday's montage, or no
    montage at all, both beat failing the nightly run.
    """
    picks, cards = [d for d in dogs if d.photos], []
    for d in picks:
        if len(cards) == COUNT:
            break
        try:
            cards.append(_polaroid(d))
        except Exception:
            continue
    if len(cards) < COUNT:
        # A gap in the cluster looks like a broken image, not a design. Better
        # to leave whatever ran last night in place.
        raise RuntimeError(
            f"only {len(cards)} of {COUNT} photos fetched; montage not written")

    canvas = Image.new("RGBA", (W, H), CARD_BG + (255,))
    for card, (cx, cy, deg) in zip(cards, LAYOUT):
        _drop(canvas, card, cx, cy, deg)

    out.parent.mkdir(parents=True, exist_ok=True)
    # JPEG, not PNG: this is four photographs. The same picture is 405KB as an
    # optimised PNG against 73KB here, and every welcome email carries it.
    canvas.convert("RGB").save(out, "JPEG", quality=86, optimize=True,
                               progressive=True)
    return out


def exists() -> bool:
    return OUT.is_file()


def cache_tag() -> str:
    """A ?v= value that changes exactly when the file does.

    Gmail and Outlook.com proxy and cache remote images by URL, so a stable
    filename whose contents change nightly can serve a subscriber a montage
    from weeks ago. Dating the *filename* would beat the cache too, but then
    every run leaves another ~90KB on the volume forever and the email has to
    go looking for the current one. The page already busts og.png this way.

    Derived from the file's own mtime rather than today's date: if a run fails
    and the montage is a week old, the URL stays on last week's tag and the
    proxy keeps serving the copy it already has, which is the correct answer.
    """
    try:
        return date.fromtimestamp(OUT.stat().st_mtime).isoformat()
    except OSError:
        return date.today().isoformat()
