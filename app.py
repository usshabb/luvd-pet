"""Serves the LUVD NYC page and collects subscribers."""
from dotenv import load_dotenv
load_dotenv()

import os
import re
from html import escape as html_escape
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import db

PUBLIC = Path(__file__).parent / "public"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    if not (PUBLIC / "index.html").exists():
        return ("No page generated yet. Run: .venv/bin/python check.py --dry-run", 404)
    return send_from_directory(PUBLIC, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    """Serve public/, resolving clean URLs to their .html file.

    /dog/muddy-paws-rescue/donny-2754  ->  public/dog/.../donny-2754.html
    Extensionless URLs are what we publish, so they must resolve here.
    """
    target = PUBLIC / filename
    if target.is_file():
        return send_from_directory(PUBLIC, filename)
    pretty = PUBLIC / (filename.rstrip("/") + ".html")
    if pretty.is_file():
        return send_from_directory(PUBLIC, filename.rstrip("/") + ".html")
    return _not_found()


def _not_found():
    """Adopted dogs leave dead URLs behind — land them somewhere useful."""
    f = PUBLIC / "404.html"
    if f.exists():
        return Response(f.read_text(), status=404, mimetype="text/html")
    return ("Not found", 404)


@app.errorhandler(404)
def handle_404(_):
    return _not_found()


@app.route("/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "invalid email"}), 400
    db.add_subscriber(email)
    return jsonify({"ok": True})


@app.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    """Signed one-click unsubscribe. GET is the email footer link; POST is
    the RFC 8058 one-click endpoint mail clients call from their own UI."""
    import hmac as _hmac
    import emailer
    email = (request.values.get("e") or "").strip().lower()
    token = request.values.get("t") or ""
    if not email or not _hmac.compare_digest(token, emailer.unsub_token(email)):
        return ("This unsubscribe link isn't valid.", 400)
    db.deactivate_subscriber(email)
    if request.method == "POST":
        return jsonify({"ok": True})
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribed — LUVD NYC</title>
<body style="background:#fbfbfd;margin:0;padding:48px 16px;
             font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:440px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;text-align:center;">
    <div style="font:700 13px inherit;letter-spacing:.2em;text-transform:uppercase;
                color:#FF002E;">LUVD NYC</div>
    <h1 style="font:700 24px inherit;color:#1d1d1f;margin:16px 0 8px;">
      You're unsubscribed</h1>
    <p style="font:400 15px inherit;color:#6e6e73;margin:0;">
      {html_escape(email)} won't get any more morning emails.<br>
      Changed your mind? Just sign up again on the site.</p>
    <a href="/" style="display:inline-block;margin-top:22px;color:#FF002E;
       font:600 15px inherit;text-decoration:none;">← Back to the dogs</a>
  </div>
</body>"""


@app.route("/robots.txt")
def robots():
    site = os.getenv("SITE_URL", "").rstrip("/")
    body = "User-agent: *\nAllow: /\n"
    # Keep crawlers out of the write/counter endpoints.
    body += ("Disallow: /view\nDisallow: /subscribe\nDisallow: /subscribers\n"
             "Disallow: /unsubscribe\n")
    if site:
        body += f"\nSitemap: {site}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    # check.py writes the real one, listing every dog and rescue page.
    f = PUBLIC / "sitemap.xml"
    if f.exists():
        return Response(f.read_text(), mimetype="application/xml")
    site = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{site}/</loc></url></urlset>", mimetype="application/xml")


@app.route("/views")
def views():
    """Live per-dog counts plus the site-wide total, fetched on page load."""
    return jsonify({"dogs": db.get_views(), "total": db.total_views()})


@app.route("/view", methods=["POST"])
def view():
    """Record a real click into a dog's detail modal."""
    data = request.get_json(silent=True) or {}
    dog_id = (data.get("id") or "").strip()
    if not dog_id or len(dog_id) > 120:
        return jsonify({"ok": False}), 400
    views = db.record_view(dog_id)
    return jsonify({"ok": True, "views": views, "total": db.total_views()})


# Canvas can't export an image drawn from another origin unless that origin
# sends CORS headers — and rescue photo hosts don't. Re-serving them from here
# keeps the share card same-origin. Strictly allowlisted: an open proxy would
# let anyone use this server to fetch arbitrary URLs.
# Exact hostnames only — never suffixes. "s3.amazonaws.com" as a suffix test
# would match any bucket-style host and hand out an open proxy.
_IMG_HOSTS = {
    "photos.smugmug.com",                # Muddy Paws
    "new-s3.shelterluv.com",             # Animal Haven (Shelterluv)
    "s3.us-east-1.amazonaws.com",        # Petstablished: Korean K9, NYC Second
                                         # Chance, Waggytail
    # Deliberately NOT "s3.amazonaws.com": the only thing our sources ever
    # served from the global endpoint was Petstablished's placeholder image,
    # which sources/petstablished.py now drops at ingest. Allowlisting it would
    # open the proxy to every public object in every S3 bucket.
    "www.sugarmuttsrescue.com",
    "sugarmuttsrescue.com",
    "g.petango.com",                     # Sean Casey (Petango)
    "dl5zpyw5k3jeb.cloudfront.net",      # Petfinder CDN
}


@app.route("/img")
def img():
    from urllib.parse import urlparse
    import requests

    raw = request.args.get("u", "")
    p = urlparse(raw)
    if p.scheme != "https" or p.netloc not in _IMG_HOSTS:
        # A new source whose photo host was never allowlisted looks identical to
        # an attack from here, so say which host was refused — otherwise the
        # only symptom is a share card with a black hole where the dog was.
        app.logger.warning("/img refused host %r — add it to _IMG_HOSTS if it "
                           "belongs to one of our sources", p.netloc)
        return ("not allowed", 403)
    try:
        r = requests.get(raw, timeout=20, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (LUVD NYC)"})
        r.raise_for_status()
    except Exception as e:
        app.logger.warning("/img upstream failed for %s: %s", raw, e)
        return ("upstream error", 502)
    ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        return ("not an image", 415)
    return Response(r.content, mimetype=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.route("/outbound", methods=["POST"])
def outbound():
    """A click through to a rescue — the thing LUVD actually delivers."""
    d = request.get_json(silent=True) or {}
    dog_id = (d.get("id") or "").strip()
    source = (d.get("source") or "").strip()
    kind = (d.get("kind") or "").strip()
    if not dog_id or not source or kind not in ("apply", "email",
                                                 "listing", "share"):
        return jsonify({"ok": False}), 400
    db.record_outbound(dog_id, source, kind)
    return jsonify({"ok": True})


@app.route("/report")
def report():
    """The weekly numbers, on demand."""
    return jsonify(db.weekly_report(int(request.args.get("days", 7))))


@app.route("/interest", methods=["POST"])
def interest():
    """Log a request for a species/city we don't cover yet."""
    d = request.get_json(silent=True) or {}
    species = (d.get("species") or "").strip().lower()
    city = (d.get("city") or "").strip()
    email = (d.get("email") or "").strip().lower() or None
    if not species or not city:
        return jsonify({"ok": False}), 400
    if email and not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "invalid email"}), 400
    db.record_interest(species, city, email)
    return jsonify({"ok": True})


@app.route("/interest-report")
def interest_report():
    """What people keep asking for — read this before picking city two."""
    return jsonify(db.interest_counts())


@app.route("/subscribers")
def subscribers():
    """Quick local check of who's signed up."""
    return jsonify(db.list_subscribers())


if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=8000, debug=True)
