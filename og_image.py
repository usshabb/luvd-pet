"""Generate the social share card for luvd.com (1200x630).

This is what shows up when the link is pasted into iMessage, Slack, Twitter or
a group chat — so it leads with dog faces rather than a bare logo. Rebuilt on
every run so the collage reflects who's actually available.
"""
import io
import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "public" / "og.png"
LOGO = Path(__file__).parent / "public" / "assets" / "luvd-logo.png"
W, H = 1200, 630

# macOS first (local runs), then the Debian font we install in the image.
_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int):
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _fetch(url: str, timeout=12):
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 (LUVD NYC)"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Crop-to-fill, centred — no squashed dogs."""
    r = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                   Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def build(dogs, total: int = None) -> Path:
    total = total if total is not None else len(dogs)
    canvas = Image.new("RGB", (W, H), (10, 10, 11))

    # A 6-across strip of faces behind a heavy scrim. Photo-first, but the
    # wordmark still has to be readable at iMessage thumbnail size.
    picks = [d for d in dogs if d.photos][:6]
    if picks:
        cw = W // len(picks)
        for i, d in enumerate(picks):
            try:
                tile = _cover(_fetch(d.photos[0]), cw + 2, H)
                canvas.paste(tile, (i * cw, 0))
            except Exception:
                continue

    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).rectangle([0, 0, W, H], fill=(6, 6, 8, 205))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), scrim).convert("RGB")

    d = ImageDraw.Draw(canvas)

    # Logo, centred
    y = 132
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGBA")
        lw = 430
        lh = int(lw * lg.height / lg.width)
        lg = lg.resize((lw, lh), Image.LANCZOS)
        canvas.paste(lg, ((W - lw) // 2, y), lg)
        y += lh + 44
    else:
        f = _font(96)
        d.text((W // 2, y), "LUVD", font=f, fill=(255, 0, 46), anchor="mt")
        y += 130

    f_head = _font(62)
    d.text((W // 2, y), "Adopt a dog in NYC", font=f_head,
           fill=(255, 255, 255), anchor="mt")

    f_sub = _font(31)
    sub = (f"{total} dogs waiting across every NYC rescue"
           if total else "Every adoptable dog across NYC rescues")
    d.text((W // 2, y + 88), sub, font=f_sub, fill=(198, 198, 204), anchor="mt")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, "PNG", optimize=True)
    return OUT
