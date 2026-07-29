"""Serves the LUVD page and collects subscribers."""
from dotenv import load_dotenv
load_dotenv()

import logging
import os
import re
import threading
from html import escape as html_escape
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import cities
import db

PUBLIC = Path(__file__).parent / "public"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

app = Flask(__name__, static_folder=None)

# Gunicorn leaves the app logger at WARNING, which would hide whether a signup's
# welcome email actually went out. Nothing else here logs below WARNING, so this
# costs a line per subscriber.
app.logger.setLevel(logging.INFO)

# Under gunicorn nothing else opens the database first, so schema work has to
# happen here or a column added by a deploy wouldn't exist until the 05:30
# scrape ran. init_db() is idempotent. It is wrapped because a database problem
# should degrade the endpoints that need it, not stop the site from booting.
try:
    db.init_db()
except Exception as e:                                # pragma: no cover
    app.logger.error("db.init_db() failed at startup: %s: %s",
                     type(e).__name__, e)


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


def _admin_ok() -> bool:
    """Is this request carrying the operator token?

    `/subscribers`, `/report` and `/interest-report` are operator tools that were
    reachable by anyone who typed the URL — the subscriber list was public JSON.
    robots.txt "protected" them with Disallow, which is worse than nothing: it is
    a public file that advertises the paths.

    Fails closed. No ADMIN_TOKEN set means nobody is an operator, because the
    alternative — falling open until someone remembers to configure it — is the
    exact bug being fixed here. compare_digest, not ==, so the check cannot be
    walked character by character with a timer.
    """
    import hmac as _hmac
    expected = os.getenv("ADMIN_TOKEN") or ""
    if not expected:
        return False
    got = (request.args.get("token") or request.headers.get("X-Admin-Token")
           or "")
    return _hmac.compare_digest(got, expected)


def _admin_gate():
    """404 for anyone without the token, or None to proceed.

    404 rather than 403: a 403 confirms the endpoint exists, which tells someone
    probing exactly where to point a token guesser. As far as the internet is
    concerned these routes are not here.
    """
    return None if _admin_ok() else _not_found()


def _in_background(label: str, work):
    """Run work() off the request thread, where it cannot affect the response.

    Everything the subscribe and unsubscribe handlers do after the database
    write — the transactional mail and the subscriber sheet mirror — wants the
    same two guarantees, so they share one mechanism rather than each growing
    its own.

    It must not hold a worker. send_email() allows itself 30 seconds and
    sheet_sync 30 more, and there are only two gunicorn workers, so holding one
    for that long on a form post is enough to stall the site.

    And it must not be able to fail the request. The database write is already
    committed before anything here starts, so every failure — including the
    thread refusing to start — is logged and dropped. That matters most on the
    unsubscribe path: leaving is a compliance promise and cannot be made to
    wait on, or fail because of, a third-party API.

    Daemon threads, so neither job can keep the machine from shutting down. The
    worker lives for the life of the deploy, so seconds of work has time to
    finish. `label` names the thread and heads its log lines.
    """
    def run():
        try:
            work()
        except Exception as e:
            app.logger.warning("%s failed: %s: %s", label, type(e).__name__, e)

    try:
        threading.Thread(target=run, name=label, daemon=True).start()
    except Exception as e:
        app.logger.warning("could not start %s: %s", label, e)


def _mail_in_background(kind: str, email: str):
    """Send emailer.send_<kind>(email) without the visitor waiting on Mandrill."""
    import emailer

    if not emailer.email_configured():
        app.logger.info("%s email skipped for %s — MANDRILL_API_KEY unset",
                        kind, email)
        return
    send = getattr(emailer, f"send_{kind}")

    def work():
        send(email)
        app.logger.info("%s email sent to %s", kind, email)

    _in_background(f"{kind} email to {email}", work)


def _sheet_sync_in_background():
    """Mirror the subscribers table to the backup Google Sheet.

    Fired only where the table actually changed. A skipped or failed sync can
    never lose anything: SQLite is the source of truth, every sync POSTs the
    whole table, and the nightly run re-mirrors it and heals any gap.
    """
    import sheet_sync

    if not sheet_sync.configured():
        return
    _in_background("subscriber sheet sync", sheet_sync.sync_subscribers)


@app.route("/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "invalid email"}), 400
    # You sign up for one city at a time. The page does not send one yet, so the
    # absent case is the live path and it has to mean New York — which is both
    # the status quo and the only answer that can never file someone under a
    # list that does not exist.
    raw_city = (data.get("city") or "").strip()
    city = cities.DEFAULT_CITY if not raw_city else cities.canon(raw_city)
    # Never store free text. This value becomes a digest segment key and a tab
    # name in the backup spreadsheet, so an unrecognised one is a group of people
    # nobody ever mails, and possibly a sync that fails outright.
    if not city:
        app.logger.info("subscribe refused unknown city %r", raw_city[:40])
        return jsonify({"ok": False, "error": "unknown city"}), 400
    # A registered but not-yet-live city would take the signup and then never
    # send anything, because nothing scrapes it and no nightly run covers it.
    # Refusing is the honest answer; `live = True` in cities.py is what opens it.
    if not cities.is_live(city):
        app.logger.info("subscribe refused city %s — not live yet", city)
        return jsonify({"ok": False, "error": "city not open yet"}), 400
    # True only for a new address, someone opting back in after unsubscribing, or
    # an existing subscriber adding a city they were not on — so re-submitting an
    # active address for a city they already have doesn't mail them again.
    if db.add_subscriber(email, city):
        _mail_in_background("welcome", email)
        _sheet_sync_in_background()
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
    # True only for the call that actually took an active row off the list, so
    # a second click on the footer link — or a client firing the one-click
    # endpoint after the reader already used it — sends no second goodbye. The
    # sheet is behind the same test because it is a mirror of the table: a call
    # that changed no row has nothing to mirror, and the payload it would post
    # is the one already there.
    if db.deactivate_subscriber(email):
        _mail_in_background("goodbye", email)
        _sheet_sync_in_background()
    if request.method == "POST":
        return jsonify({"ok": True})
    return f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribed — LUVD</title>
<body style="background:#fbfbfd;margin:0;padding:48px 16px;
             font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
  <div style="max-width:440px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;text-align:center;">
    <div style="font:700 13px inherit;letter-spacing:.2em;text-transform:uppercase;
                color:#FF002E;">LUVD</div>
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
                         headers={"User-Agent": "Mozilla/5.0 (LUVD)"})
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
    """The weekly numbers, on demand. Operator only."""
    denied = _admin_gate()
    if denied:
        return denied
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
    """What people keep asking for — read this before picking city two.

    Aggregates only, no addresses, so this was never the leak — but it is demand
    data about where the product goes next, and that is not the public's.
    """
    denied = _admin_gate()
    if denied:
        return denied
    return jsonify(db.interest_counts())


@app.route("/subscribers")
def subscribers():
    """How many people are signed up, per city. Operator only.

    Counts, never addresses — not even with a valid token. This used to return
    every active subscriber's email as public JSON. The offsite copy of the list
    is the Google Sheet mirror, so nothing needs the addresses here, and keeping
    them out means a leaked token still cannot dump the list.
    """
    denied = _admin_gate()
    if denied:
        return denied
    return jsonify({"total": len(db.list_subscribers()),
                    "by_city": db.subscriber_city_counts()})


@app.route("/cities")
def cities_endpoint():
    """What the server thinks the cities are, and which ones are open.

    The only way to see from outside whether a city is live, which is the switch
    that decides what a nightly run covers and what /subscribe accepts.
    """
    return jsonify([{"code": c.code, "name": c.name, "tz": c.tz, "live": c.live}
                    for c in cities.CITIES.values()])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
