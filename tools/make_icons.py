"""Rebuild the favicon set from the wordmark.

The heart is the third glyph of public/assets/luvd-logo.png. Cutting it from
the 1400px original and downscaling once, rather than rescaling whatever the
last favicon happened to be, fixes two things the old set had:

  * aspect. The mark is very nearly square (about 1.03 wide to tall) and the
    old favicon.png held it at 0.857 — squeezed narrow and stretched tall.
    Nothing here resizes a non-square box into a square one.
  * resolution. The old heart filled 56% of its 64px box, so at a 16px tab it
    was about nine pixels of actual mark surrounded by margin. A tab favicon
    has no room to spare, so this runs close to the edge, and every size is
    resampled from the full-resolution crop rather than from the 64px file.

    .venv/bin/python tools/make_icons.py

Only needed if the wordmark changes.
"""
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public" / "assets" / "luvd-logo.png"
PUB = ROOT / "public"

# Tab favicons are tiny, so the mark runs nearly edge to edge. The touch icon
# keeps more room because iOS masks its corners into a rounded square.
FAVICON_PAD = 0.02
TOUCH_PAD = 0.14
# What favicon.ico carries. 16 and 32 are the ones browsers actually pick for a
# tab; the larger two are for Windows surfaces and cost a few hundred bytes.
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)]


def _heart_box(im):
    """Bounding box of the third red glyph — L, U, heart, D."""
    w, h = im.size
    px = im.convert("RGBA").load()
    red = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 140 and r > 150 and r - max(g, b) > 60:
                red[y][x] = True

    seen = [[False] * w for _ in range(h)]
    boxes = []
    for sy in range(h):
        for sx in range(w):
            if not red[sy][sx] or seen[sy][sx]:
                continue
            q, n = deque([(sx, sy)]), 0
            seen[sy][sx] = True
            x0 = x1 = sx
            y0 = y1 = sy
            while q:
                x, y = q.popleft()
                n += 1
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and red[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if n > 500:                       # ignore antialiasing specks
                boxes.append((x0, y0, x1 + 1, y1 + 1))
    boxes.sort(key=lambda b: b[0])
    if len(boxes) != 4:
        raise SystemExit(f"expected 4 glyphs in the wordmark, found {len(boxes)}")
    return boxes[2]


def _square(crop, box, pad):
    """Centre the crop in a transparent square without distorting it.

    The mark is pasted at its own aspect ratio and the square is built around
    it. Resizing the crop straight to (size, size) is what squashed the old
    favicon, and it is the one thing this must never do.
    """
    side = int(round(max(crop.size) / (1 - 2 * pad)))
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2), crop)
    return out.resize((box, box), Image.LANCZOS)


def main():
    logo = Image.open(SRC).convert("RGBA")
    box = _heart_box(logo)
    # Only the red. The wordmark draws a white sticker outline around every
    # glyph, and it falls inside the red bounding box — left in, the icon is a
    # heart wearing a white fringe, and its alpha runs to all four corners so
    # the padding below has nothing to measure against.
    heart = logo.crop(box)
    px = heart.load()
    for y in range(heart.height):
        for x in range(heart.width):
            r, g, b, a = px[x, y]
            if not (a > 40 and r > 130 and r - max(g, b) > 45):
                px[x, y] = (r, g, b, 0)
    heart = heart.crop(heart.split()[3].getbbox())
    w, h = heart.size
    print(f"  heart cut from the wordmark at {w}x{h}, aspect {w / h:.3f}")

    fav = _square(heart, 64, FAVICON_PAD)
    fav.save(PUB / "favicon.png", "PNG", optimize=True)
    # Each size resampled from the full-resolution crop, not from the 64px file.
    fav.save(PUB / "favicon.ico", sizes=ICO_SIZES,
             append_images=[_square(heart, s, FAVICON_PAD) for s, _ in ICO_SIZES])
    _square(heart, 180, TOUCH_PAD).save(PUB / "apple-touch-icon.png", "PNG",
                                        optimize=True)
    for f in ("favicon.png", "favicon.ico", "apple-touch-icon.png"):
        print(f"  public/{f}  {(PUB / f).stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
