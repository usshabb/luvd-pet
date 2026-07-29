"""Morning email via Mandrill — a short nudge that links to the day's LUVD NYC page.

Deliberately NOT a full catalog: a few faces, a count, one button. The page is
where you actually browse.

All outbound mail (signup welcome, daily digest, scraper alerts, weekly report)
goes through send_email() so there is exactly one place that knows the provider.
"""
import hashlib
import hmac
import os
import html
from datetime import date
from typing import List
from urllib.parse import quote

import requests

from sources.base import Dog

MANDRILL_URL = "https://mandrillapp.com/api/1.0/messages/send.json"
PREVIEW_COUNT = 6


def unsub_token(email: str) -> str:
    """Signed token so an unsubscribe link only works for its own address."""
    secret = os.getenv("UNSUB_SECRET", "luvd-dev-secret")
    return hmac.new(secret.encode(), email.strip().lower().encode(),
                    hashlib.sha256).hexdigest()[:20]


def unsub_url(email: str) -> str:
    return f"{_site_url()}/unsubscribe?e={quote(email)}&t={unsub_token(email)}"


def email_configured() -> bool:
    return bool(os.getenv("MANDRILL_API_KEY"))


def _from_parts():
    """FROM_EMAIL accepts 'Name <addr>' or a bare address."""
    raw = os.getenv("FROM_EMAIL", "LUVD NYC <dogs@luvd.com>")
    if "<" in raw:
        name, _, rest = raw.partition("<")
        return rest.rstrip("> ").strip(), (name.strip() or "LUVD NYC")
    return raw.strip(), "LUVD NYC"


def send_email(to_email: str, subject: str, html_body: str = None, text_body: str = None,
               headers: dict = None):
    key = os.getenv("MANDRILL_API_KEY")
    if not key:
        raise RuntimeError("MANDRILL_API_KEY not set")
    from_email, from_name = _from_parts()
    message = {
        "from_email": from_email,
        "from_name": from_name,
        "to": [{"email": to_email}],
        "subject": subject,
    }
    if html_body:
        message["html"] = html_body
    if text_body:
        message["text"] = text_body
    if headers:
        message["headers"] = headers
    resp = requests.post(MANDRILL_URL, json={"key": key, "message": message}, timeout=30)
    body = resp.json()
    # Mandrill signals API-level errors as a dict (often with HTTP 500),
    # per-recipient failures as status "rejected"/"invalid" in a list.
    if isinstance(body, dict) and body.get("status") == "error":
        raise RuntimeError(f"Mandrill error: {body.get('message')}")
    resp.raise_for_status()
    result = body[0]
    if result.get("status") not in ("sent", "queued", "scheduled"):
        raise RuntimeError(
            f"Mandrill {result.get('status')}: {result.get('reject_reason')}")
    return result


def _thumb(dog: Dog) -> str:
    photo = dog.primary_photo()
    if not photo:
        return ""
    return f"""
      <td style="padding:0 6px 12px 0;" width="33%">
        <a href="{html.escape(_site_url())}" style="text-decoration:none;">
          <img src="{html.escape(photo)}" width="168" height="168" alt="{html.escape(dog.name)}"
               style="width:100%;max-width:168px;height:168px;object-fit:cover;
                      border-radius:14px;display:block;">
          <div style="font:600 15px -apple-system,Segoe UI,Roboto,sans-serif;
                      color:#1d1d1f;margin-top:7px;">{html.escape(dog.name)}</div>
          <div style="font:400 12.5px -apple-system,Segoe UI,Roboto,sans-serif;
                      color:#6e6e73;">{html.escape(dog.source_label)}</div>
        </a>
      </td>"""


def _site_url() -> str:
    return os.getenv("SITE_URL", "http://localhost:8000")


def _site_host() -> str:
    """Bare hostname, for reading aloud in body copy rather than linking."""
    host = _site_url().split("//", 1)[-1].strip("/")
    return host.split("/", 1)[0] or "luvd.com"


def build_html(dogs: List[Dog], for_date: date = None, unsubscribe_for: str = None) -> str:
    for_date = for_date or date.today()
    n = len(dogs)
    with_photos = [d for d in dogs if d.photos][:PREVIEW_COUNT]

    rows = ""
    for i in range(0, len(with_photos), 3):
        rows += f"<tr>{''.join(_thumb(d) for d in with_photos[i:i + 3])}</tr>"

    unsub_line = ""
    if unsubscribe_for:
        unsub_line = (f'<br><a href="{html.escape(unsub_url(unsubscribe_for))}" '
                      f'style="color:#98989d;">Unsubscribe</a>')

    more = ""
    if n > len(with_photos):
        more = (f'<p style="font:400 14px -apple-system,Segoe UI,Roboto,sans-serif;'
                f'color:#6e6e73;text-align:center;margin:4px 0 0;">'
                f'+ {n - len(with_photos)} more on the site</p>')

    return f"""
<div style="background:#fbfbfd;padding:32px 16px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    <div style="font:700 13px -apple-system,Segoe UI,Roboto,sans-serif;letter-spacing:.2em;
                text-transform:uppercase;color:#FF002E;text-align:center;">LUVD NYC</div>
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 6px;">
      {n} new dog{'' if n == 1 else 's'} today</h1>
    <p style="font:400 15px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:0 0 26px;">Across every NYC rescue we follow.</p>

    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {rows}
    </table>
    {more}

    <a href="{html.escape(_site_url())}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:24px;">
      See all {n} dog{'' if n == 1 else 's'} →</a>

    <p style="font:400 12px -apple-system,Segoe UI,Roboto,sans-serif;color:#98989d;
              text-align:center;margin:22px 0 0;">
      {for_date.strftime('%A, %B %-d, %Y')}<br>
      You only get this when there are new dogs.{unsub_line}</p>
  </div>
</div>"""


def _bulk_headers(to_email: str) -> dict:
    """One-click unsubscribe headers — Gmail/Yahoo require these for bulk
    senders, and they keep spam-report rates from hurting deliverability."""
    return {
        "List-Unsubscribe": f"<{unsub_url(to_email)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def send_digest(to_email: str, dogs: List[Dog], for_date: date = None):
    n = len(dogs)
    return send_email(
        to_email,
        f"🐶 {n} new dog{'' if n == 1 else 's'} in NYC today",
        html_body=build_html(dogs, for_date, unsubscribe_for=to_email),
        headers=_bulk_headers(to_email),
    )


def build_welcome_html(to_email: str) -> str:
    """The one-time signup confirmation.

    Deliberately reads nothing from the database and shows no dogs: this is the
    first mail an address ever gets, and it must not be able to arrive empty or
    broken because a scrape came back with nothing.
    """
    site = html.escape(_site_url())
    return f"""
<div style="background:#fbfbfd;padding:32px 16px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:20px;
              padding:36px 28px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    <div style="font:700 13px -apple-system,Segoe UI,Roboto,sans-serif;letter-spacing:.2em;
                text-transform:uppercase;color:#FF002E;text-align:center;">LUVD NYC</div>
    <h1 style="font:700 27px -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
               text-align:center;letter-spacing:-.02em;margin:16px 0 6px;">
      You're on the list</h1>
    <p style="font:400 15px -apple-system,Segoe UI,Roboto,sans-serif;color:#6e6e73;
              text-align:center;margin:0 0 20px;">Thanks for signing up.</p>

    <p style="font:400 16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              margin:0 0 14px;">
      Every morning we check the NYC rescues we follow. When new dogs are
      listed, you'll get one short email with their faces and a link to the
      page.</p>
    <p style="font:400 16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;
              margin:0;">
      On days when nothing new comes in, you won't hear from us at all. That's
      the whole thing.</p>

    <a href="{site}"
       style="display:block;background:#FF002E;color:#fff;text-decoration:none;
              text-align:center;padding:15px;border-radius:13px;font:600 16px
              -apple-system,Segoe UI,Roboto,sans-serif;margin-top:26px;">
      See today's dogs →</a>

    <p style="font:400 12px -apple-system,Segoe UI,Roboto,sans-serif;color:#98989d;
              text-align:center;margin:22px 0 0;">
      You're getting this because you signed up at {html.escape(_site_host())}.<br>
      <a href="{html.escape(unsub_url(to_email))}"
         style="color:#98989d;">Unsubscribe</a></p>
  </div>
</div>"""


def build_welcome_text(to_email: str) -> str:
    """Plain-text alternative. A first-contact mail with no text part looks
    materially worse to spam filters than one with it."""
    return f"""You're on the list.

Thanks for signing up to LUVD NYC.

Every morning we check the NYC rescues we follow. When new dogs are listed,
you'll get one short email with their faces and a link to the page.

On days when nothing new comes in, you won't hear from us at all. That's the
whole thing.

See today's dogs: {_site_url()}

--
You're getting this because you signed up at {_site_host()}.
Unsubscribe: {unsub_url(to_email)}
"""


def send_welcome(to_email: str):
    """One-time confirmation that someone is subscribed. Sent at signup only —
    the cadence after this is still 'nothing unless there are new dogs'."""
    return send_email(
        to_email,
        "You're on the list — LUVD NYC",
        html_body=build_welcome_html(to_email),
        text_body=build_welcome_text(to_email),
        headers=_bulk_headers(to_email),
    )
