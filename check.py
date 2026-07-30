"""The overnight job: fetch -> dedupe -> date -> render -> email.

Every adoptable dog stays on the page for as long as its rescue still lists it.
What changes day to day is which group it sits in: today's arrivals lead, and
you scroll back through the dogs that showed up on earlier days. A dog only
disappears when the rescue stops listing it — i.e. it found a home.

  .venv/bin/python check.py                  # real run, the default city
  .venv/bin/python check.py --dry-run        # rebuild the page, no email, no writes
  .venv/bin/python check.py --city NYC       # one city's run

A run belongs to exactly one city. It fetches only that city's sources, records
only that city's dogs, forgets only that city's dogs, and mails only that city's
subscribers — so Los Angeles shelters can never affect what a New York reader
sees, or the other way round.
"""
import argparse
import sys
from dotenv import load_dotenv

load_dotenv()

import cities
import db
import page
from normalize import normalize
from enrich import enrich
from sources.registry import sources_for_city

# If a city's run comes back with less than this share of the dogs already on
# record for it, something broke upstream — don't prune. forget_missing() has no
# lower bound of its own, and the all-sources-failed guard below only fires at
# exactly zero, so four of seven rescues going down would otherwise delete most
# of the city and mail the lot back as "new" tomorrow. Same instinct as that
# guard, just not pinned to zero.
FORGET_FLOOR_SHARE = 0.5


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


def collect(prefs, city=None, verbose=True):
    """Every currently-adoptable dog in one city, deduped across its sources.

    Returns (dogs, failed_source_names).
    """
    city = city or cities.default_run_city()
    dogs, seen_keys, seen_ids, failures = [], set(), set(), []
    for source in sources_for_city(city):
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
            # One stamp, here, is what spares all seven scrapers from knowing
            # cities exist. `or` rather than assignment so a rescue that places
            # dogs in more than one city can set it per dog and keep it, while
            # one that says nothing gets its own class's city.
            dog.city = dog.city or source.city
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


def _group_by_day(dogs, fallback_iso: str):
    """[(iso_date, [Dog, ...]), ...], newest day first — what page.render takes."""
    groups = {}
    for d in dogs:
        groups.setdefault(d.first_seen or fallback_iso, []).append(d)
    for k in groups:
        groups[k] = order_for_feed(groups[k])
    return groups, sorted(groups.items(), key=lambda kv: kv[0], reverse=True)


def _passive_pages(city, prefs) -> dict:
    """The other live cities' rosters, so this run can republish their pages.

    Read-only by construction: no record_seen, no forget_missing, no
    update_photo_state, no digest. Dates come from first_seen_map(), so a dog this
    city has never recorded reads as new on ITS city's page on ITS city's clock —
    and only that city's own run can ever write the date down.

    A city that returns nothing is left out entirely rather than published empty.
    page.write() only clears and rewrites what it is handed, so being left out
    means that city's existing page, dog pages and sitemap URLs survive the
    morning untouched. A rescue outage in one city must not take another city's
    page off the internet.
    """
    out = {}
    for other in cities.live_codes():
        if other == city:
            continue
        try:
            dogs, failures = collect(prefs, other, verbose=False)
        except Exception as e:
            print(f"  {other}: fetch failed ({type(e).__name__}: {e}) — leaving "
                  f"its page as it is")
            continue
        if not dogs:
            print(f"  {other}: no dogs returned — leaving its page as it is")
            _alert(f"LUVD {other}: no dogs while running {city}",
                   f"{city}'s run also fetches {other} so both pages can be "
                   f"published together, and {other} returned nothing. Its "
                   f"existing page was left in place. Check its scrapers.")
            continue
        dogs = enrich(normalize(dogs))
        seen = db.first_seen_map(d.id for d in dogs)
        other_today = cities.today(other).isoformat()
        for d in dogs:
            d.first_seen = seen.get(d.id, other_today)
        _, dated = _group_by_day(dogs, other_today)
        if failures:
            print(f"  {other}: {len(dogs)} dogs ({len(failures)} source(s) "
                  f"failed, republished from the rest)")
        else:
            print(f"  {other}: {len(dogs)} dogs republished")
        out[other] = dated
    return out


def run(dry_run=False, city=None):
    db.init_db()
    city = cities.canon(city) or cities.default_run_city()
    prefs = db.get_prefs()
    # Each city's day is measured on its own clock, so a dog listed at 9pm
    # Pacific is still a Pacific Tuesday. The container's TZ is fixed, so this
    # is read from the city rather than from the ambient one.
    today_d = cities.today(city)
    today = today_d.isoformat()

    print(f"Fetching {city} rescues (own sites first, platform APIs after)...")
    dogs, failures = collect(prefs, city)

    # A scraper breaking is the most likely failure here — rescue sites get
    # redesigned. Fail loudly rather than quietly shipping a thinner page.
    if failures:
        print(f"\n!! {len(failures)} source(s) FAILED: {', '.join(failures)}")
        _alert(f"LUVD {city}: {len(failures)} scraper(s) failed",
               "These sources returned nothing this morning:\n  - "
               + "\n  - ".join(failures)
               + "\n\nThe page was still built from the sources that worked.")

    if not dogs:
        print("No dogs returned by any source — leaving the existing page alone.")
        _alert(f"LUVD {city}: ALL scrapers failed",
               "No source returned a dog. The page was left untouched.")
        return []

    # Second pass for anything still photoless. Rescues photograph new
    # arrivals days after listing them, and a detail-page timeout can also
    # hide an existing photo — this catches both.
    missing = [d for d in dogs if not d.photos]
    if missing:
        recovered = 0
        for source in sources_for_city(city):
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
        # Scoped to this city, so a run can only forget its own dogs. Unscoped,
        # a Los Angeles run would delete every New York row it wasn't handed —
        # losing the first_seen dates the page is built around, and mailing the
        # whole roster back as "new" the next morning.
        recorded = db.count_seen(city)
        if recorded and len(dogs) < recorded * FORGET_FLOOR_SHARE:
            print(f"  !! {city}: only {len(dogs)} dogs found against {recorded} "
                  f"on record — not pruning, this looks like a broken source.")
            _alert(f"LUVD {city}: prune skipped, sources look broken",
                   f"{city} returned {len(dogs)} dogs but has {recorded} on "
                   f"record. Deleting the difference would drop most of the "
                   f"city's timeline and mail it back as new tomorrow, so "
                   f"nothing was deleted. Check the scrapers.")
        else:
            adopted = db.forget_missing((d.id for d in dogs), city=city)
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

    groups, dated = _group_by_day(dogs, today)

    new_today = groups.get(today, [])
    print(f"\n{len(dogs)} adoptable dogs across {len(dated)} day(s); "
          f"{len(new_today)} new today.")

    # Every city is published in one page.write() call, because public/dog/ and
    # sitemap.xml are shared: one call per city would have each city delete the
    # other's dog pages and publish a sitemap describing half the site.
    #
    # So the other live cities are fetched too — read-only. Nothing about them is
    # recorded, their timelines are untouched and no digest of theirs is sent;
    # their dates come from what is already stored, exactly as --dry-run does.
    # That is what keeps this city's run from being able to change anything a
    # reader of another city's page sees.
    pages = {city: dated}
    pages.update(_passive_pages(city, prefs))
    # Default city first, so its URLs lead the sitemap as they always have.
    pages = {k: pages[k] for k in cities.live_codes() if k in pages}

    path = page.write(pages, today_d)
    print(f"Page written: {path}")

    # The social card leads with real dog faces, so it's rebuilt with the page.
    # Never fatal — a stale card is better than a failed run. Still one shared
    # card and one shared montage: a per-city share image is a follow-up, and
    # only the default city's run rebuilds them so a second city cannot quietly
    # replace New York's faces with its own.
    photographed = [d for d in dogs if d.photos]
    if city == cities.DEFAULT_CITY:
        try:
            import og_image
            og = og_image.build(photographed, total=len(dogs))
            print(f"Share card:   {og}")
        except Exception as e:
            print(f"  share card skipped ({type(e).__name__}: {e})")

        # Same deal for the welcome email's montage: rebuilt from dogs listed
        # today so a new subscriber sees dogs actually waiting, and never fatal.
        # The email checks the file exists and simply omits it if this never ran.
        try:
            import montage
            print(f"Montage:      {montage.build(photographed)}")
        except Exception as e:
            print(f"  montage skipped ({type(e).__name__}: {e})")

    if dry_run:
        for d in new_today[:10]:
            print(f"  NEW · {d.name:<18} {d.source_label}")
        print("(dry run: nothing recorded, no email sent)")
        return dogs

    if not new_today:
        print("No new dogs today — no email sent (by design).")
        return dogs

    # Only this city's subscribers, so a New York reader can never be sent a Los
    # Angeles dog: the dogs in `new_today` all came from this city's sources, and
    # the list is filtered to people who asked for this city.
    recipients = db.list_subscribers(city)
    # The operator's own address comes from prefs, outside the subscribers table,
    # so it has no city and gets every live city's digest — which is how a broken
    # scraper in a new city gets noticed at all.
    if prefs.get("email") and prefs["email"] not in recipients:
        recipients.append(prefs["email"])
    if not recipients:
        print(f"No {city} subscribers yet — page generated only.")
        return dogs

    from emailer import send_digest
    sent = 0
    for addr in recipients:
        try:
            send_digest(addr, new_today, city=city)
            sent += 1
        except Exception as e:
            print(f"  email to {addr} failed: {type(e).__name__}: {e}")
    print(f"Emailed {sent}/{len(recipients)} {city} subscriber(s).")
    return dogs


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    # Unchanged in meaning: still writes the page, share card and montage, still
    # takes first_seen_map() instead of record_seen(), still skips
    # forget_missing()/update_photo_state() and still returns before the digest.
    # fly-start.sh's boot render depends on exactly that.
    p.add_argument("--dry-run", action="store_true",
                   help="rebuild the page; record nothing, mail nobody")
    p.add_argument("--city", default=None, metavar="CODE",
                   help="which city to run (default: the live city)")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    dry = args.dry_run
    if args.city and not cities.canon(args.city):
        sys.exit(f"Unknown city {args.city!r}. Known: "
                 f"{', '.join(cities.all_codes())}")
    run(dry_run=dry, city=args.city)
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
