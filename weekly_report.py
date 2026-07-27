"""Monday morning digest: how each rescue did on LUVD last week.

The point of this email is to be forwardable. Each rescue block is written so
you can paste it straight into a note to them — that's the relationship that
gets LUVD shared, and eventually gets blocked rescues to allowlist us.

  .venv/bin/python weekly_report.py            # send
  .venv/bin/python weekly_report.py --print    # print to stdout instead
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import db
import emailer
from sources.registry import all_sources

NYC = ZoneInfo("America/New_York")


def _labels() -> dict:
    """source key -> display name, straight from the registry."""
    out = {}
    for s in all_sources():
        out[s.name] = getattr(s, "label", s.name)
    return out


def build(days: int = 7) -> tuple:
    data = db.weekly_report(days)
    labels = _labels()
    today = datetime.now(NYC).date()
    start = today - timedelta(days=days)
    period = f"{start.strftime('%b %-d')} – {today.strftime('%b %-d, %Y')}"

    active = [r for r in data["rescues"] if r["dogs"]]
    total_clicks = sum(r["clicks"] for r in active)
    total_views = sum(r["views"] for r in active)

    rows = ""
    for r in active:
        label = labels.get(r["source"], r["source"])
        kinds = r["by_kind"]
        detail = " · ".join(f"{v} {k}" for k, v in sorted(kinds.items())) or "—"
        rows += f"""
      <tr>
        <td style="padding:11px 0;border-bottom:1px solid #eee;">
          <b style="font:600 15px -apple-system,sans-serif;color:#1d1d1f;">{label}</b><br>
          <span style="font:400 12px -apple-system,sans-serif;color:#8a8a8e;">
            {r['dogs']} dogs listed · {detail}</span>
        </td>
        <td align="right" style="padding:11px 0;border-bottom:1px solid #eee;
            font:700 17px -apple-system,sans-serif;color:#1d1d1f;">{r['views']}</td>
        <td align="right" style="padding:11px 0 11px 18px;
            border-bottom:1px solid #eee;
            font:700 17px -apple-system,sans-serif;color:#FF002E;">{r['clicks']}</td>
      </tr>"""

    top = ""
    if data["top_dogs"]:
        items = "".join(
            f"<li style='margin-bottom:5px;'><b>{d['name'] or d.get('source')}</b>"
            f" — {d['n']} click{'s' if d['n'] != 1 else ''}"
            f" <span style='color:#8a8a8e;'>({labels.get(d['source'], d['source'])})</span></li>"
            for d in data["top_dogs"]
        )
        top = f"""
      <h3 style="font:600 14px -apple-system,sans-serif;color:#1d1d1f;
          margin:26px 0 8px;">Most contacted dogs</h3>
      <ul style="font:400 14px -apple-system,sans-serif;color:#1d1d1f;
          padding-left:18px;margin:0;">{items}</ul>"""

    html = f"""
<div style="background:#fbfbfd;padding:30px 16px;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:18px;
       padding:30px 26px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
    <div style="font:700 12px -apple-system;letter-spacing:.18em;
         text-transform:uppercase;color:#FF002E;">LUVD NYC · Weekly</div>
    <h1 style="font:700 24px -apple-system;color:#1d1d1f;margin:12px 0 4px;">
      {total_clicks} rescue contact{'s' if total_clicks != 1 else ''} this week</h1>
    <p style="font:400 14px -apple-system;color:#6e6e73;margin:0 0 22px;">
      {period} · {total_views} dog views · {data['new_subscribers']} new
      subscriber{'s' if data['new_subscribers'] != 1 else ''}
      ({data['total_subscribers']} total)</p>

    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;">
      <tr>
        <td style="font:600 11px -apple-system;color:#8a8a8e;
            text-transform:uppercase;letter-spacing:.06em;padding-bottom:6px;">
          Rescue</td>
        <td align="right" style="font:600 11px -apple-system;color:#8a8a8e;
            text-transform:uppercase;letter-spacing:.06em;">Views</td>
        <td align="right" style="font:600 11px -apple-system;color:#8a8a8e;
            text-transform:uppercase;letter-spacing:.06em;padding-left:18px;">
          Contacts</td>
      </tr>{rows}
    </table>
    {top}

    <p style="font:400 12.5px -apple-system;color:#8a8a8e;margin:26px 0 0;
       line-height:1.5;border-top:1px solid #eee;padding-top:16px;">
      <b>Views</b> = someone opened that dog on LUVD (lifetime).
      <b>Contacts</b> = someone clicked through to the rescue this week —
      an application, an email, or their own listing.<br><br>
      Worth forwarding: rescues rarely see where their traffic comes from.
    </p>
  </div>
</div>"""

    subject = (f"LUVD weekly · {total_clicks} rescue contacts, "
               f"{data['new_subscribers']} new subscribers")
    return subject, html, data


def send(days: int = 7):
    subject, html, data = build(days)
    to = os.getenv("ALERT_EMAIL") or os.getenv("OPERATOR_EMAIL")
    if not emailer.email_configured() or not to:
        print("No MANDRILL_API_KEY / ALERT_EMAIL — printing instead.\n")
        print(subject)
        for r in data["rescues"]:
            if r["dogs"]:
                print(f"  {r['source']:<14} {r['views']:>5} views  "
                      f"{r['clicks']:>4} contacts")
        return
    emailer.send_email(to, subject, html_body=html)
    print(f"Weekly report sent to {to}")


if __name__ == "__main__":
    db.init_db()
    if "--print" in sys.argv:
        subject, html, data = build()
        print(subject, "\n")
        for r in data["rescues"]:
            if r["dogs"]:
                print(f"  {r['source']:<14} {r['dogs']:>3} dogs  "
                      f"{r['views']:>5} views  {r['clicks']:>4} contacts")
        print(f"\n  subscribers: {data['total_subscribers']} "
              f"(+{data['new_subscribers']} this week)")
    else:
        send()
