"""Score the subscriber list for signs of automated signup.

Run it where the database is:

    fly ssh console -C "python tools/audit_subscribers.py"
    fly ssh console -C "python tools/audit_subscribers.py --list"

Without --list it prints counts and patterns only, so it can be run and pasted
around without moving anybody's address anywhere. With --list it prints the
addresses it suspects, for a human to make the actual call.

Nothing here deletes anything. Every signal below has honest false positives —
a real person can have a numeric gmail, and twelve colleagues can sign up in
the same hour off one link — so the output is evidence, not a verdict.
"""
import argparse
import collections
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402

# Domains that exist to be thrown away. Not proof of a bot — some people use
# them deliberately — but a real subscriber list has very few.
_DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com",
    "tempmail.com", "temp-mail.org", "trashmail.com", "sharklasers.com",
    "getnada.com", "dispostable.com", "maildrop.cc", "throwawaymail.com",
}
# A local part that is mostly digits, or a long unbroken run of consonants, is
# what a generator produces and what a person almost never chooses.
_MOSTLY_DIGITS = re.compile(r"^[a-z]{0,3}\d{5,}$")
_CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxz]{6,}")
_SEQUENTIAL = re.compile(r"^(.*?)(\d+)$")


def _rows():
    con = db._connect() if hasattr(db, "_connect") else None
    if con is None:
        import sqlite3
        con = sqlite3.connect(db.DB_PATH)
        con.row_factory = sqlite3.Row
    cur = con.execute(
        "SELECT email, created, active FROM subscribers ORDER BY created")
    return [dict(r) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="print the suspect addresses, not just the counts")
    args = ap.parse_args()

    rows = _rows()
    total = len(rows)
    active = [r for r in rows if r.get("active", 1)]
    print(f"\n  {total} addresses on file, {len(active)} active\n")
    if not rows:
        return

    domains = collections.Counter(r["email"].rsplit("@", 1)[-1] for r in rows)
    print("  Top domains")
    for dom, n in domains.most_common(8):
        share = n / total * 100
        flag = "  <-- concentrated" if share > 25 and n > 10 else ""
        print(f"    {n:>5}  {share:>5.1f}%  {dom}{flag}")

    # Signups bunched into one hour. A launch can do this legitimately; a
    # scraper finding the form does it at 3am with no referrer.
    hours = collections.Counter()
    for r in rows:
        c = (r.get("created") or "")[:13]
        if c:
            hours[c] += 1
    print("\n  Busiest hours")
    for hour, n in hours.most_common(5):
        flag = "  <-- burst" if n > 20 else ""
        print(f"    {n:>5}  {hour}:00{flag}")

    suspects = collections.defaultdict(list)
    stems = collections.Counter()
    for r in rows:
        email = r["email"]
        local, _, dom = email.partition("@")
        if dom in _DISPOSABLE:
            suspects["disposable domain"].append(email)
        if _MOSTLY_DIGITS.match(local):
            suspects["mostly digits"].append(email)
        if _CONSONANT_RUN.search(local):
            suspects["random-looking"].append(email)
        m = _SEQUENTIAL.match(local)
        if m and len(m.group(1)) >= 3:
            stems[(m.group(1), dom)] += 1

    # abc1@, abc2@, abc3@ — one generator walking a counter.
    for (stem, dom), n in stems.items():
        if n >= 4:
            suspects["sequential local part"].append(f"{stem}N@{dom} x{n}")

    print("\n  Signals")
    if not suspects:
        print("    nothing stood out")
    for label, hits in sorted(suspects.items(), key=lambda kv: -len(kv[1])):
        print(f"    {len(hits):>5}  {label}")
        if args.list:
            for h in hits[:40]:
                print(f"           {h}")
            if len(hits) > 40:
                print(f"           ... and {len(hits) - 40} more")

    flagged = {e for hits in suspects.values() for e in hits if "@" in e}
    print(f"\n  {len(flagged)} of {total} addresses tripped at least one signal.")
    print("  These are signals, not proof. Read them before removing anybody —\n"
          "  a real person can have a numeric address, and a good day can put\n"
          "  fifty genuine signups in one hour.\n")
    if not args.list:
        print("  Re-run with --list to see the addresses.\n")


if __name__ == "__main__":
    main()
