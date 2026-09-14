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


TAB = ROOT / "ios" / "LUVD" / "Assets.xcassets" / "LuvdHeart.imageset"
# Points. A tab bar glyph sits in roughly a 25pt square; the heart fills a hair
# under that so it weighs the same as the SF Symbols beside it.
TAB_BOX = 25
TAB_FILL = 0.94


def tab_heart(mask: Image.Image):
    """The wordmark's heart as a template image for the tab bar.

    Black on transparent, marked template, so the tab bar tints it grey when
    unselected and the accent when selected exactly like a system symbol. Each
    scale is brought down from one large thresholded mask rather than resized
    from the next size up, which is what keeps a 50px glyph's edge clean.
    """
    w, h = mask.size
    big_side = 1400
    k = big_side / max(w, h)
    big = mask.resize((int(w * k), int(h * k)), Image.LANCZOS)
    big = big.point(lambda v: 255 if v >= 128 else 0)
    TAB.mkdir(parents=True, exist_ok=True)
    images = []
    for scale in (2, 3):
        side = TAB_BOX * scale
        inner = int(side * TAB_FILL)
        ratio = inner / max(big.size)
        glyph = big.resize((max(1, int(big.width * ratio)), max(1, int(big.height * ratio))),
                           Image.LANCZOS)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        black = Image.new("RGBA", glyph.size, (0, 0, 0, 255))
        canvas.paste(black, ((side - glyph.width) // 2, (side - glyph.height) // 2), glyph)
        name = f"luvd-heart@{scale}x.png"
        canvas.save(TAB / name, "PNG", optimize=True)
        images.append({"filename": name, "idiom": "universal", "scale": f"{scale}x"})
    images.insert(0, {"idiom": "universal", "scale": "1x"})
    import json
    (TAB / "Contents.json").write_text(json.dumps({
        "images": images,
        "info": {"author": "xcode", "version": 1},
        "properties": {"template-rendering-intent": "template"},
    }, indent=2) + "\n")
    print(f"  tab heart {TAB_BOX}pt @2x/@3x -> {TAB.relative_to(ROOT)}")


def main():
    mask = heart_mask()
    tab_heart(mask)
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
