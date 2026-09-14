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


HEADER = ROOT / "ios" / "LUVD" / "Assets.xcassets" / "LogoHeader.imageset"


def header_logo():
    """The wordmark cropped to its sticker outline, for the Dogs header.

    The original carries a wide soft drop shadow for the onboarding screen, and
    most of its canvas is that shadow: fitted to a nav bar's height, the letters
    came out barely a third of it. Cropping at the outline drops the shadow and
    the empty margin, so the same height is nearly all wordmark.
    """
    import json
    logo = Image.open(SRC).convert("RGBA")
    alpha = logo.split()[3].point(lambda v: 255 if v >= 160 else 0)
    box = alpha.getbbox()
    cropped = logo.crop(box)
    HEADER.mkdir(parents=True, exist_ok=True)
    cropped.save(HEADER / "luvd-logo-header.png", "PNG", optimize=True)
    (HEADER / "Contents.json").write_text(json.dumps({
        "images": [{"filename": "luvd-logo-header.png", "idiom": "universal"}],
        "info": {"author": "xcode", "version": 1},
    }, indent=2) + "\n")
    print(f"  header logo {logo.size[0]}x{logo.size[1]} -> {cropped.size[0]}x{cropped.size[1]} "
          f"(aspect {cropped.size[0] / cropped.size[1]:.2f})")


SHAPE_SWIFT = ROOT / "ios" / "LUVD" / "LuvdHeartShape.swift"
LAUNCH_HEART = ROOT / "ios" / "LUVD" / "Assets.xcassets" / "LaunchHeart.imageset"
LAUNCH_COLOR = ROOT / "ios" / "LUVD" / "Assets.xcassets" / "LaunchBackground.colorset"
# The launch screen heart and the splash's first frame must be the same size so
# the handoff from the system's static screen to the animation is invisible.
LAUNCH_PT = 104


def _binary(mask: Image.Image, side: int) -> Image.Image:
    w, h = mask.size
    k = side / max(w, h)
    big = mask.resize((int(w * k), int(h * k)), Image.LANCZOS)
    return big.point(lambda v: 255 if v >= 128 else 0)


def _trace(img: Image.Image):
    """Outer boundary of the one blob, clockwise, by Moore-neighbour tracing."""
    w, h = img.size
    px = img.load()
    inside = lambda x, y: 0 <= x < w and 0 <= y < h and px[x, y] > 0
    start = next((x, y) for y in range(h) for x in range(w) if px[x, y] > 0)
    ring = [(-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1)]
    p, back, out = start, 0, [start]
    for _ in range(200000):
        for i in range(8):
            d = (back + 1 + i) % 8
            n = (p[0] + ring[d][0], p[1] + ring[d][1])
            if inside(*n):
                prev = (d + 7) % 8
                b = (p[0] + ring[prev][0], p[1] + ring[prev][1])
                back = ring.index((b[0] - n[0], b[1] - n[1]))
                p = n
                break
        else:
            break
        if p == start:
            break
        out.append(p)
    return out


def _rdp(pts, eps):
    """Ramer-Douglas-Peucker, iterative, on an open polyline."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        best, idx = 0.0, None
        for i in range(a + 1, b):
            x, y = pts[i]
            dist = abs(dy * x - dx * y + bx * ay - by * ax) / norm
            if dist > best:
                best, idx = dist, i
        if idx is not None and best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [q for q, k in zip(pts, keep) if k]


def heart_shape(mask: Image.Image):
    """The V-heart as a vector SwiftUI Shape, so it stays crisp at any scale.

    The launch animation flies the heart forward until it is thirty times its
    size; a bitmap scaled that far goes soft long before its edges leave the
    screen. Traced from a 4x thresholded mask and simplified to a polygon whose
    facets stay under a pixel at every size the heart is ever drawn crisp.
    """
    img = _binary(mask, 1200)
    w, h = img.size
    ring = _trace(img)
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
    pts = _rdp(ring[: far + 1], 0.9)[:-1] + _rdp(ring[far:] + [ring[0]], 0.9)[:-1]
    side = max(w, h)
    ox, oy = (side - w) / 2, (side - h) / 2
    norm = [((x + ox) / side, (y + oy) / side) for x, y in pts]
    body = ",\n".join("        CGPoint(x: %.5f, y: %.5f)" % q for q in norm)
    SHAPE_SWIFT.write_text(f"""import SwiftUI

// Generated by tools/make_app_icon.py from the wordmark. Do not edit by hand.

/// The LUVD V-heart as a vector shape: the wordmark's own heart, traced, in a
/// unit square and centred, so it stays crisp at any size.
struct LuvdHeartShape: Shape {{
    static let points: [CGPoint] = [
{body}
    ]

    func path(in rect: CGRect) -> Path {{
        let side = min(rect.width, rect.height)
        let ox = rect.midX - side / 2, oy = rect.midY - side / 2
        var path = Path()
        path.addLines(Self.points.map {{ CGPoint(x: ox + $0.x * side, y: oy + $0.y * side) }})
        path.closeSubpath()
        return path
    }}
}}
""")
    print(f"  heart shape: {len(ring)} boundary px -> {len(norm)} points -> {SHAPE_SWIFT.relative_to(ROOT)}")


def launch_assets(mask: Image.Image):
    """A white heart for the static launch screen, at exactly the splash's size."""
    import json
    big = _binary(mask, 1200)
    LAUNCH_HEART.mkdir(parents=True, exist_ok=True)
    images = [{"idiom": "universal", "scale": "1x"}]
    for scale in (2, 3):
        side = LAUNCH_PT * scale
        ratio = side / max(big.size)
        glyph = big.resize((round(big.width * ratio), round(big.height * ratio)), Image.LANCZOS)
        white = Image.new("RGBA", glyph.size, (255, 255, 255, 255))
        canvas = Image.new("RGBA", glyph.size, (255, 255, 255, 0))
        canvas.paste(white, (0, 0), glyph)
        name = f"launch-heart@{scale}x.png"
        canvas.save(LAUNCH_HEART / name, "PNG", optimize=True)
        images.append({"filename": name, "idiom": "universal", "scale": f"{scale}x"})
    (LAUNCH_HEART / "Contents.json").write_text(json.dumps(
        {"images": images, "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    LAUNCH_COLOR.mkdir(parents=True, exist_ok=True)
    (LAUNCH_COLOR / "Contents.json").write_text(json.dumps({
        "colors": [{"color": {"color-space": "srgb", "components": {
            "alpha": "1.000", "blue": "0x2E", "green": "0x00", "red": "0xFF"}}, "idiom": "universal"}],
        "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    print(f"  launch heart {LAUNCH_PT}pt @2x/@3x + LaunchBackground colour")


def main():
    header_logo()
    mask = heart_mask()
    tab_heart(mask)
    heart_shape(mask)
    launch_assets(mask)
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
