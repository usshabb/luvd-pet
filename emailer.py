"""Morning email via Mandrill — a short nudge that links to the day's LUVD NYC page.

Deliberately NOT a full catalog: a few faces, a count, one button. The page is
where you actually browse.

All outbound mail (daily digest, scraper alerts, weekly report) goes through
send_email() so there is exactly one place that knows the provider.
"""
import os
import html
from datetime import date
from typing import List

import requests

from sources.base import Dog

MANDRILL_URL = "https://mandrillapp.com/api/1.0/messages/send.json"
PREVIEW_COUNT = 6


def email_configured() -> bool:
    return bool(os.getenv("MANDRILL_API_KEY"))


def _from_parts():
    """FROM_EMAIL accepts 'Name <addr>' or a bare address."""
    raw = os.getenv("FROM_EMAIL", "LUVD NYC <dogs@luvd.com>")
    if "<" in raw:
        name, _, rest = raw.partition("<")
        return rest.rstrip("> ").strip(), (name.strip() or "LUVD NYC")
    return raw.strip(), "LUVD NYC"


def send_email(to_email: str, subject: str, html_body: str = None, text_body: str = None):
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


def build_html(dogs: List[Dog], for_date: date = None) -> str:
    for_date = for_date or date.today()
    n = len(dogs)
    with_photos = [d for d in dogs if d.photos][:PREVIEW_COUNT]

    rows = ""
    for i in range(0, len(with_photos), 3):
        rows += f"<tr>{''.join(_thumb(d) for d in with_photos[i:i + 3])}</tr>"

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
      You only get this when there are new dogs.</p>
  </div>
</div>"""


def send_digest(to_email: str, dogs: List[Dog], for_date: date = None):
    n = len(dogs)
    return send_email(
        to_email,
        f"🐶 {n} new dog{'' if n == 1 else 's'} in NYC today",
        html_body=build_html(dogs, for_date),
    )
