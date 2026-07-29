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
import math
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from imaging import cover, fetch_photo, font

PUBLIC = Path(__file__).parent / "public"
# Served straight off public/ by app.static_files. Kept as a plain filename so
# emailer can check it exists and build the URL from _site_url().
FILENAME = "welcome-montage.jpg"
OUT = PUBLIC / FILENAME

# The box the email draws this in: 504px is the full content width of the 560px
# card, less its 28px of padding. emailer imports these rather than repeating
# them, because an <img> whose declared size disagrees with the file gets
# stretched, and the two numbers used to be able to drift apart.
DISPLAY_W, DISPLAY_H = 504, 210
# The canvas. Bigger than the polaroids need, deliberately: the shadows and the
# rotated corners have to land inside it with white to spare, or the edge of the
# JPEG cuts a straight line through them — see _ink_box(). 1080x450 is 2.14x the
# display box and exactly 12:5 either way, so both dimensions can be declared
# whole and nothing is resampled unevenly.
W, H = 1080, 450

# Four, in one row. Two rows was the first attempt and it was wrong: the lower
# row lands on the upper row's captions, and pulling it clear makes the image
# 740px tall — a third of a phone screen for a decorative block. One row keeps
# every name visible and the picture wide and short.
#
# Four is the most that leaves a face worth looking at. The email shows this at
# 504px, so each photo lands at ~116px, and at ~69px on a 300px-wide phone
# card. Five would take that to 55px, which is a thumbnail of a dog rather than
# a dog.
COUNT = 4

# Fixed rather than random. The same four angles every night reads as composed;
# re-rolling nightly means the one bad arrangement eventually ships.
#
# Coordinates are relative to the cluster, not to the canvas: build() measures
# what the four cards and their shadows actually cover and centres that in W x H.
# Nudging a card here therefore cannot push a shadow off the edge, which is the
# bug these numbers used to be hand-balanced against.
LAYOUT = [
    # (centre x, centre y, degrees)
    (160, 190, -5.5),
    (387, 178, 2.5),
    (613, 192, -2.5),
    (840, 180, 5.5),
]
PHOTO = 248               # the square photo inside a frame
BORDER = 17               # white frame on three sides
CAPTION_BAND = 62         # the deeper bottom edge a polaroid caption sits in
CAPTION_SIZE = 34         # ~16px as displayed, ~9px on a 300px phone card
# Cards overlap by ~55px. Names are left-aligned, so a neighbour landing on the
# right edge never reaches one — but only if they are truncated to the width
# that stays visible rather than to the full photo.
NAME_WIDTH = PHOTO - 60
# Exactly the background:#fff of the card this sits in — emailer's `.card` div.
# It has to match to the digit, because a JPEG has no transparency: whatever the
# bleed is filled with is what the reader sees, and #fff against the card's #fff
# is the only pair with no seam. The body around the card is #fbfbfd, which is
# the wrong white — the montage never touches it.
CARD_BG = (255, 255, 255)

# Under each card: black at this alpha, this far down, blurred by this much.
SHADOW_ALPHA = 0.30
SHADOW_OFFSET = 7
SHADOW_BLUR = 11


def _blur_reach(sigma: float, passes: int = 3) -> int:
    """The furthest ImageFilter.GaussianBlur can carry a pixel, in px.

    Worth deriving rather than guessing at, because it is exact. Pillow does not
    convolve a real Gaussian — it runs `passes` box blurs whose width comes from
    the sigma (Gwosdek et al. 2011, the same paper its source cites), so the
    kernel has finite support: past this many pixels the result is zero, not
    merely small. That makes it a true bound on how far a shadow can spill, and
    so on how much bleed the canvas needs.
    """
    var = sigma * sigma / passes
    length = math.sqrt(12.0 * var + 1.0)      # [7] box length
    whole = math.floor((length - 1.0) / 2.0)  # [11] integer part of box radius
    frac = ((2 * whole + 1) * (whole * (whole + 1) - 3 * var)
            / (6 * (var - (whole + 1) ** 2)))  # [14] fractional part
    return math.ceil(passes * (whole + frac))


# 32px at sigma 11. The visible spill is shorter — the tail rounds to zero at
# 25px once it is scaled down to SHADOW_ALPHA — but the bleed is sized to the
# bound, so it is provably enough rather than enough as far as anyone looked.
SHADOW_REACH = _blur_reach(SHADOW_BLUR)


def _ink_box(cards):
    """The tight box the cards and their shadows cover, in LAYOUT coordinates.

    The montage is a JPEG, so anything outside the canvas is not clipped
    gracefully, it is sliced off square — and both things that put ink outside
    the upright frame are easy to under-count. Rotating a 282x327 card by 5.5°
    swings its bounding box out to 314x353, and the shadow then adds
    SHADOW_REACH on every side of *that*, plus SHADOW_OFFSET more at the bottom.
    Together that is 29px past the left and right of where the cards used to be
    laid out, 21px past the top and 14px past the bottom, which is exactly what
    was being cut. Measuring it here instead of allowing for it by hand in
    LAYOUT is what keeps it correct when any of those numbers move.
    """
    xs, ys = [], []
    for card, (cx, cy, _) in zip(cards, LAYOUT):
        x, y = cx - card.width // 2, cy - card.height // 2
        xs += [x - SHADOW_REACH, x + card.width + SHADOW_REACH]
        ys += [min(y, y + SHADOW_OFFSET - SHADOW_REACH),
               y + card.height + SHADOW_OFFSET + SHADOW_REACH]
    return min(xs), min(ys), max(xs), max(ys)


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


def _shadow(card: Image.Image) -> Image.Image:
    """A soft drop shadow for an already-rotated card, on its own padded canvas.

    The shadow is the card's own alpha, dimmed and blurred, which is what makes
    the cards look stacked rather than pasted. The SHADOW_REACH of transparent
    margin is the point: blurring on a canvas the size of the card clamps the
    filter at the border, so the falloff never happens and the shadow ends in a
    straight line down the side of every polaroid instead of fading out.
    """
    pad = SHADOW_REACH
    alpha = Image.new("L", (card.width + pad * 2, card.height + pad * 2), 0)
    alpha.paste(card.getchannel("A").point(lambda a: int(a * SHADOW_ALPHA)),
                (pad, pad))
    shadow = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    return shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))


def _drop(canvas: Image.Image, card: Image.Image, x: int, y: int):
    """Lay a rotated card's shadow down, then the card on top of it, with the
    card's top-left at (x, y)."""
    shadow = _shadow(card)
    canvas.alpha_composite(shadow, (x - SHADOW_REACH,
                                    y - SHADOW_REACH + SHADOW_OFFSET))
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

    # Rotate first, then measure, then centre what that came to in the canvas.
    # expand=True keeps the corners a tilt swings outside the upright frame.
    cards = [c.rotate(deg, resample=Image.BICUBIC, expand=True)
             for c, (_, _, deg) in zip(cards, LAYOUT)]
    x0, y0, x1, y1 = _ink_box(cards)
    dx, dy = (W - (x1 - x0)) // 2 - x0, (H - (y1 - y0)) // 2 - y0

    canvas = Image.new("RGBA", (W, H), CARD_BG + (255,))
    for card, (cx, cy, _) in zip(cards, LAYOUT):
        _drop(canvas, card, cx - card.width // 2 + dx, cy - card.height // 2 + dy)

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
