# LUVD NYC — handoff

A daily-updating page of every adoptable dog across NYC rescues.
Python + Flask + SQLite, containerised. `DEPLOY.md` is the step-by-step.

## Deploy in one line

```bash
./deploy.sh <server-ip> luvd.com <ssh-key.pem>
```

Targets a fresh Ubuntu box (AWS Lightsail $5/mo recommended). Installs Docker,
uploads, builds, starts Caddy with automatic HTTPS, seeds the first scrape,
verifies. Refuses to run if DNS hasn't propagated — Let's Encrypt rate-limits
failed certificate attempts.

## Architecture

| Piece | What it does |
|---|---|
| `check.py` | The nightly job. Fetch → dedupe → date → enrich → render → email. |
| `sources/` | One module per rescue. Each fails independently. |
| `normalize.py` | Forces every source into one shape so the UI is consistent. |
| `enrich.py` | The four ratings + breed guide, from the rescue's text and `breeds.json`. |
| `page.py` | Renders `public/index.html`. No framework, no build step. |
| `app.py` | Serves the page + `/subscribe`, `/view`, `/img`, `/sitemap.xml`. |
| `og_image.py` | Rebuilds the 1200×630 social card nightly. |
| `db.py` | SQLite. **The only stateful thing here.** |

Three containers: `web` (gunicorn), `cron` (sleeps until 05:30 ET), `caddy` (TLS).

## The one thing that must not be lost

`/data/dogfinder.db` on the `luvd-data` volume. It holds:

- **`first_seen`** — which day each dog appeared. This *is* the timeline; lose
  it and every dog reads as "new today".
- **`subscribers`** — the email list.
- **`dog_views`** — the 🔥 counts.

None of it is reproducible from the rescues. Back it up:

```bash
docker run --rm -v luvd_luvd-data:/d -v $PWD:/b alpine \
  tar czf /b/luvd-backup-$(date +%F).tgz -C /d .
```

## Environment

Copy `.env.example` → `.env`. Required to be fully live:

| Var | Effect if missing |
|---|---|
| `LUVD_DOMAIN` | Caddy won't start |
| `SITE_URL` | Emails and OG tags point at localhost |
| `RESEND_API_KEY` | **No email sends at all** (signups still captured) |
| `PETFINDER_KEY` / `_SECRET` | Korean K9 + city-wide Petfinder stay off |
| `ALERT_EMAIL` | Scraper failures are silent |
| `ANTHROPIC_API_KEY` | Optional — upgrades breed-guide text |

## Adding keys after launch

Both Resend and Petfinder are optional at deploy time and can be added any day
after. No rebuild — `env_file` is read when the container starts:

```bash
nano /opt/luvd/.env          # add the key(s)
docker compose up -d         # recreates containers with the new env
docker compose run --rm cron python check.py   # optional: apply immediately
```

**Until Resend is added:** signups are still captured to the database — they
just don't receive anything yet. Whoever subscribes on day one gets their first
email the morning after the key lands. Nothing is lost. Scraper failure alerts
are also silent until then.

**Until Petfinder is added:** Korean K9 and the city-wide fallback show as
`skip (not configured)`. The other five rescues are unaffected.

Verified: a full nightly run with **no keys at all** exits 0, builds the page
and the share card, and only logs that email couldn't send.

## Known state

**Working:** 5 scrapers, 84 dogs. Muddy Paws (JSON API), Animal Haven (HTML +
detail pages), Waggytail (Petstablished API), Sugar Mutts (HTML), Sean Casey
(HTML).

**Off until keys land:** Korean K9 (their site is behind Cloudflare — we go
through their Petfinder org `NY1374`, which is unverified until a key exists),
city-wide Petfinder.

**Not verified:** the Docker image has never been built — no Docker on the dev
machine. Expect the first `docker compose up --build` to be where any
dependency issue surfaces. The app itself is smoke-tested (all endpoints 200 on
a fresh DB).

## Things that will break, and why

1. **HTML scrapers break when rescues redesign.** Three of five parse HTML.
   Each is isolated in a try/except, logs, and emails `ALERT_EMAIL`; the page
   still builds from whatever worked. A source returning **0 dogs** also
   alerts — that's usually a broken selector, not an empty shelter.
2. **Rescue contact methods change.** `rescue_contacts.json` encodes whether
   each rescue takes email or requires an application first. 4 of 6 require an
   application — sending people to email would get them bounced. Re-verify
   occasionally.
3. **The ratings are estimates.** Derived from the rescue's write-up plus breed
   tendencies, and labelled as such in the UI. Don't let anyone present them as
   assessments of an individual animal.
4. **`/img` is an allowlisted proxy.** It exists so the share canvas can export
   cross-origin photos. Adding a source means adding its photo host to
   `_IMG_HOSTS` in `app.py`. Do not make it open — that's an SSRF hole.

## Deliberate decisions worth not undoing

- **Photoless dogs are shown**, sorted last. They're currently 9 puppies whose
  litters arrived before the camera did. Hiding them would bury the newest
  arrivals and make the count untrue.
- **View counts are real.** No seeding, no inflation. Hidden below 1 view.
- **One NYC clock.** SQLite's `datetime('now')` is UTC; after 8pm Eastern that
  rolls the date and the evening's arrivals stop counting as new. Everything
  dates off `America/New_York`.
- **Dogs are never deleted from the page when they gain a photo or change** —
  only when the rescue stops listing them, which means adopted.
