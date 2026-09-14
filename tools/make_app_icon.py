"""Build the iOS app icon from the wordmark's heart.

    .venv/bin/python tools/make_app_icon.py

White heart on the brand red. Red-on-white is the favicon, and on a home screen
it disappears among every other white icon; a red tile is the thing a thumb
finds. The shape is the wordmark's own V-heart, not a generic one, cut from the
1400px original by the same glyph finder make_icons.py uses.

The heart in the wordmark is ~300px and the icon wants it near 600, so this
does not simply scale the crop — a 2x Lanczos upscale of an antialiased edge
comes out soft. Instead the alpha mask is upscaled 4x, thresholded to a hard
edge (the interpolation puts that edge at sub-pixel accuracy), then brought
down to size, which puts back an antialiased edge that is crisp rather than
blurred.

iOS rejects an icon with an alpha channel, so the output is flattened to RGB.
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from make_icons import SRC, _heart_box  # noqa: E402

OUT = ROOT / "ios" / "LUVD" / "Assets.xcassets" / "AppIcon.appiconset" / "AppIcon-1024.png"
SIZE = 1024
RED = (255, 0, 46)
# Share of the tile the heart's larger side fills. iOS masks the corners into a
# squircle, so the mark needs real margin to not look crowded against the curve.
FILL = 0.56
SUPER = 4


def heart_mask() -> Image.Image:
    logo = Image.open(SRC).convert("RGBA")
    crop = logo.crop(_heart_box(logo))
    mask = Image.new("L", crop.size, 0)
    src, dst = crop.load(), mask.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, a = src[x, y]
            # Redness as coverage, so antialiased edge pixels keep partial
            # alpha instead of being cut to all-or-nothing here.
            red = max(0, min(255, (r - max(g, b)) * 255 // 200)) if a > 20 else 0
            dst[x, y] = red * a // 255
    return mask.crop(mask.getbbox())


def main():
    mask = heart_mask()
    w, h = mask.size
    target = int(SIZE * FILL)
    scale = target / max(w, h)
    big = mask.resize((int(w * scale * SUPER), int(h * scale * SUPER)), Image.LANCZOS)
    big = big.point(lambda v: 255 if v >= 128 else 0)
    small = big.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    icon = Image.new("RGB", (SIZE, SIZE), RED)
    white = Image.new("RGB", small.size, (255, 255, 255))
    # Optical centre sits a touch above the geometric one for a heart: its mass
    # is in the lobes, so a truly centred heart reads as sagging.
    x = (SIZE - small.width) // 2
    y = (SIZE - small.height) // 2 - int(SIZE * 0.015)
    icon.paste(white, (x, y), small)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT, "PNG", optimize=True)
    print(f"  heart {w}x{h} -> {small.width}x{small.height} on {SIZE}px red")
    print(f"  {OUT.relative_to(ROOT)}  {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
