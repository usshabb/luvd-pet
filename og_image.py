"""Generate the social share card for luvd.com (1200x630).

This is what shows up when the link is pasted into iMessage, Slack, Twitter or
a group chat — so it leads with dog faces rather than a bare logo. Rebuilt on
every run so the collage reflects who's actually available.
"""
from pathlib import Path

from PIL import Image, ImageDraw

from imaging import cover, fetch_photo, font

OUT = Path(__file__).parent / "public" / "og.png"
LOGO = Path(__file__).parent / "public" / "assets" / "luvd-logo.png"
W, H = 1200, 630


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
                tile = cover(fetch_photo(d.photos[0]), cw + 2, H)
                canvas.paste(tile, (i * cw, 0))
            except Exception:
                continue

    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).rectangle([0, 0, W, H], fill=(6, 6, 8, 205))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), scrim).convert("RGB")

    # Just the mark, large and centred. The dog faces carry the message; the
    # headline and counts only competed with them at thumbnail size.
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGBA")
        lw = int(W * 0.62)
        lh = int(lw * lg.height / lg.width)
        lg = lg.resize((lw, lh), Image.LANCZOS)
        canvas.paste(lg, ((W - lw) // 2, (H - lh) // 2), lg)
    else:
        d = ImageDraw.Draw(canvas)
        d.text((W // 2, H // 2), "LUVD", font=font(150), fill=(255, 0, 46),
               anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, "PNG", optimize=True)
    return OUT
