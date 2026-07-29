"""The overnight job: fetch -> dedupe -> date -> render -> email.

Every adoptable dog stays on the page for as long as its rescue still lists it.
What changes day to day is which group it sits in: today's arrivals lead, and
you scroll back through the dogs that showed up on earlier days. A dog only
disappears when the rescue stops listing it — i.e. it found a home.

  .venv/bin/python check.py             # real run
  .venv/bin/python check.py --dry-run   # rebuild the page, no email, no writes
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

import db
import page
from normalize import normalize
from enrich import enrich
from sources.registry import all_sources

# One clock for the whole product. SQLite's datetime('now') is UTC, and after
# 8pm Eastern that is already tomorrow — which would make the evening's new
# arrivals invisible. Everything dates off New York instead.
NYC = ZoneInfo("America/New_York")


def nyc_today():
    return datetime.now(NYC).date()


def _alert(subject: str, body: str):
    """Email the operator when something breaks. Silent if Mandrill isn't set up."""
    import os
    import emailer
    to = os.getenv("ALERT_EMAIL") or os.getenv("OPERATOR_EMAIL")
    if not emailer.email_configured() or not to:
        print("  (no MANDRILL_API_KEY/ALERT_EMAIL — alert not sent)")
        return
    try:
        emailer.send_email(to, subject, text_body=body)
        print(f"  alert sent to {to}")
    except Exception as e:
        print(f"  alert failed: {type(e).__name__}: {e}")


def collect(prefs, verbose=True):
    """Every currently-adoptable dog, deduped across sources.

    Returns (dogs, failed_source_names).
    """
    dogs, seen_keys, seen_ids, failures = [], set(), set(), []
    for source in all_sources():
        if not source.enabled(prefs):
            if verbose:
                print(f"  skip  {source.name:<14} (not configured)")
            continue
        try:
            found = source.fetch(prefs)
        except Exception as e:
            if verbose:
                print(f"  ERROR {source.name:<14} {type(e).__name__}: {e}")
            failures.append(f"{source.name} ({type(e).__name__}: {e})")
            continue

        # A source that suddenly returns nothing is usually a broken selector,
        # not an empty shelter — worth an alert either way.
        if not found:
            if verbose:
                print(f"  WARN  {source.name:<14} returned 0 dogs")
            failures.append(f"{source.name} (returned 0 dogs)")

        kept = 0
        # Fuzzy name|breed matching only catches the SAME dog listed by two
        # different rescues. Inside one source the id is authoritative — two
        # dogs there can legitimately share a name, and a quarter of ours have
        # breed "Unknown", so fuzzy-matching within a source would delete one.
        source_keys, source_reprints = set(), set()
        for dog in found:
            if dog.id in seen_ids:
                continue
            reprint = dog.reprint_key()
            if reprint and reprint in source_reprints:
                continue                      # rescue entered this dog twice
            key = dog.dedupe_key()
            if key in seen_keys and key not in source_keys:
                continue                      # same dog, higher-priority source
            seen_ids.add(dog.id)
            seen_keys.add(key)
            source_keys.add(key)
            source_reprints.add(reprint)
            dogs.append(dog)
            kept += 1
        if verbose:
            print(f"  ok    {source.name:<14} {len(found):>3} listed, {kept:>3} kept")
    return dogs, failures


def order_for_feed(dogs):
    """Round-robin across rescues so no single one owns the top of a group.

    Only Petfinder exposes a real published date — Muddy Paws has no intake
    field and Animal Haven returns its listing in rotating order — so a global
    recency sort would be inventing precision. Interleaving keeps every rescue
    visible, and each source's own order (newest-first where it exists) is
    preserved inside its queue.
    """
    withphoto = [d for d in dogs if d.photos]
    nophoto = [d for d in dogs if not d.photos]

    def interleave(items):
        queues = {}
        for d in items:                       # dict preserves insertion order
            queues.setdefault(d.source_label, []).append(d)
        out, lists = [], list(queues.values())
        while lists:
            for q in list(lists):
                out.append(q.pop(0))
                if not q:
                    lists.remove(q)
        return out

    # Photo-first: the page is built around faces, so dogs the rescue never
    # photographed sort last rather than punching holes in the grid.
    return interleave(withphoto) + interleave(nophoto)


def run(dry_run=False):
    db.init_db()
    prefs = db.get_prefs()
    today_d = nyc_today()
    today = today_d.isoformat()

    print("Fetching NYC rescues (own sites first, platform APIs after)...")
    dogs, failures = collect(prefs)

    # A scraper breaking is the most likely failure here — rescue sites get
    # redesigned. Fail loudly rather than quietly shipping a thinner page.
    if failures:
        print(f"\n!! {len(failures)} source(s) FAILED: {', '.join(failures)}")
        _alert(f"LUVD: {len(failures)} scraper(s) failed",
               "These sources returned nothing this morning:\n  - "
               + "\n  - ".join(failures)
               + "\n\nThe page was still built from the sources that worked.")

    if not dogs:
        print("No dogs returned by any source — leaving the existing page alone.")
        _alert("LUVD: ALL scrapers failed",
               "No source returned a dog. The page was left untouched.")
        return []

    # Second pass for anything still photoless. Rescues photograph new
    # arrivals days after listing them, and a detail-page timeout can also
    # hide an existing photo — this catches both.
    missing = [d for d in dogs if not d.photos]
    if missing:
        recovered = 0
        for source in all_sources():
            try:
                recovered += source.recheck_photos(missing)
            except Exception as e:
                print(f"  photo recheck failed for {source.name}: "
                      f"{type(e).__name__}: {e}")
        print(f"  photo recheck: {len(missing)} without photos, "
              f"{recovered} recovered")

    dogs = enrich(normalize(dogs))

    if dry_run:
        seen = db.first_seen_map(d.id for d in dogs)
    else:
        seen = db.record_seen(dogs, today)
        adopted = db.forget_missing(d.id for d in dogs)
        if adopted:
            print(f"  {adopted} dog(s) no longer listed — removed from the timeline.")

    # Report dogs that picked up a photo since we last looked — the most
    # common meaningful change to an existing listing.
    was = db.photo_state(d.id for d in dogs)
    gained = [d for d in dogs if d.photos and was.get(d.id) is False]
    if gained:
        names = ", ".join(d.name for d in gained[:8])
        more = f" (+{len(gained) - 8} more)" if len(gained) > 8 else ""
        print(f"  📸 {len(gained)} dog(s) gained photos: {names}{more}")
    if not dry_run:
        db.update_photo_state(dogs)

    for d in dogs:
        d.first_seen = seen.get(d.id, today)

    groups = {}
    for d in dogs:
        groups.setdefault(d.first_seen, []).append(d)
    for k in groups:
        groups[k] = order_for_feed(groups[k])
    # Newest day first.
    dated = sorted(groups.items(), key=lambda kv: kv[0], reverse=True)

    new_today = groups.get(today, [])
    print(f"\n{len(dogs)} adoptable dogs across {len(dated)} day(s); "
          f"{len(new_today)} new today.")

    path = page.write(dated, today_d)
    print(f"Page written: {path}")

    # The social card leads with real dog faces, so it's rebuilt with the page.
    # Never fatal — a stale card is better than a failed run.
    try:
        import og_image
        og = og_image.build([d for d in dogs if d.photos], total=len(dogs))
        print(f"Share card:   {og}")
    except Exception as e:
        print(f"  share card skipped ({type(e).__name__}: {e})")

    if dry_run:
        for d in new_today[:10]:
            print(f"  NEW · {d.name:<18} {d.source_label}")
        print("(dry run: nothing recorded, no email sent)")
        return dogs

    if not new_today:
        print("No new dogs today — no email sent (by design).")
        return dogs

    recipients = db.list_subscribers()
    if prefs.get("email") and prefs["email"] not in recipients:
        recipients.append(prefs["email"])
    if not recipients:
        print("No subscribers yet — page generated only.")
        return dogs

    from emailer import send_digest
    sent = 0
    for addr in recipients:
        try:
            send_digest(addr, new_today)
            sent += 1
        except Exception as e:
            print(f"  email to {addr} failed: {type(e).__name__}: {e}")
    print(f"Emailed {sent}/{len(recipients)} subscriber(s).")
    return dogs


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
    if not dry:
        # Nightly re-mirror of the subscriber backup sheet, so a webhook that
        # failed at signup time heals within a day. Never fails the scrape.
        import sheet_sync
        if sheet_sync.configured():
            try:
                sheet_sync.sync_subscribers()
                print("Subscriber sheet mirrored.")
            except Exception as e:
                print(f"Sheet sync failed: {type(e).__name__}: {e}")
