"""Pillow plumbing shared by the two things that composite dog photos —
og_image.py (the social share card) and montage.py (the welcome email).

These started in og_image.py. They moved here when the montage needed the same
three, rather than the montage importing from a module named for a different
output: both jobs fetch a stranger's photo over HTTP and crop it to fill a box,
and neither cares what the other is drawing.
"""
import io
import os

import requests
from PIL import Image, ImageFont

# macOS first (local runs), then the Debian font we install in the image.
_FONTS_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONTS_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def font(size: int, bold: bool = True):
    """First font on disk that loads, or Pillow's bitmap default.

    Never raises. A card with the fallback font is worse-looking than one with
    Arial; a card that failed to render is worse than both.
    """
    for p in (_FONTS_BOLD if bold else _FONTS_REGULAR):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def fetch_photo(url: str, timeout=12) -> Image.Image:
    """One dog photo as RGB. Raises — callers decide what a miss costs."""
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 (LUVD NYC)"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Crop-to-fill, centred — no squashed dogs."""
    r = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                   Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))
