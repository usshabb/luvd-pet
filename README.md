# 🐶 LUVD NYC

**Every new adoptable dog across NYC rescues, on one page, every morning.**

Direct rescue listings are checked first; Petfinder is the fallback. Dogs you've
already been shown never appear again. If there's nothing new, no email goes out.

## How it works

```
check.py
  ├─ fetch     sources in priority order (direct rescues → Petfinder)
  ├─ dedupe    within-run (cross-source) + across-run (stable id in SQLite)
  ├─ normalize one shape for every source, so the UI is consistent
  ├─ enrich    3 at-a-glance scores + breed guide grounded in the rescue's words
  ├─ render    public/index.html — the LUVD NYC page
  └─ email     Resend digest to subscribers, linking to the page
```

## Sources

| Rescue | Priority | How | Status |
|---|---|---|---|
| Muddy Paws Rescue | 10 | public JSON API | ✅ 27 dogs |
| Animal Haven | 11 | server-rendered HTML + detail pages | ✅ 37 dogs |
| Waggytail Rescue | 12 | Petstablished JSON API (via Wix widget) | ✅ 10 dogs |
| Sugar Mutts Rescue | 13 | WordPress | ✅ 6 dogs |
| Sean Casey (24PetConnect) | 14 | server-rendered HTML | ✅ 4 dogs |
| Korean K9 Rescue | 15 | Petfinder org `NY1374` | 🔑 needs Petfinder key |
| Petfinder (city-wide) | 900 | official API | 🔑 needs Petfinder key |

Korean K9's own site sits behind a Cloudflare challenge, so it's pulled through
their sanctioned Petfinder org listing instead of being scraped.

## Setup

```bash
cp .env.example .env
```

Fill in `.env`:

- `PETFINDER_KEY` / `PETFINDER_SECRET` — free at https://www.petfinder.com/developers/
- `RESEND_API_KEY` — free at https://resend.com
- `SITE_URL` — public URL of the page, used in emails
- `ANTHROPIC_API_KEY` — optional; unlocks LLM-graded scores instead of heuristics

## Run

```bash
.venv/bin/python check.py --dry-run
```

Fetch everything and rebuild the page without sending email or recording state.

```bash
.venv/bin/python check.py
```

The real morning run: rebuilds the page, records what was shown, emails subscribers.

```bash
.venv/bin/python app.py
```

Serves the page at http://127.0.0.1:8000 and accepts subscribe POSTs.
`GET /subscribers` lists signups.

## The three scores

Each dog gets **Energy**, **Apartment fit** and **Experience needed** (1–5), shown as
bars in the modal. They're derived from breed tendencies in `breeds.json` adjusted by
keyword signals in the rescue's own write-up — a third of dogs have breed "Unknown",
so the bio does most of the work.

These are **estimates and labelled as such in the UI.** The rescue is the source of
truth on any individual animal.

## View counts (🔥 badges)

Cards show a fire badge with how many people have opened that dog's modal. These
are **real counts**, stored server-side (`POST /view`, read via `GET /views`), and
they only appear once a dog passes `VIEW_FLOOR` (3) so the number means something.

On static hosting with no backend, the badges simply never render — the page never
invents a number. Fake urgency would contradict the product's own promise.

## Similar dogs

Each modal ends with a "More dogs like <name>" row, scored client-side from data
already on the page: same breed weighs most, then how closely the three ratings
line up, then shared traits and size. Each suggestion shows *why* it matched, and
matches cross rescue boundaries — a Muddy Paws dog can surface under an Animal
Haven one.

## Easter egg

Hovering the logo drifts paw prints upward; clicking it sets off a burst, and
every fifth click earns a woof. Respects `prefers-reduced-motion`.

## Adding a rescue

1. Copy `sources/rescues/_template.py` to `sources/rescues/<name>.py`.
2. Return `Dog` objects with a **stable id** (dedup depends on it).
3. Register it in `sources/registry.py` under `_DIRECT` with a priority below 900.

Normalization and scoring happen centrally, so a new scraper only has to fetch.

## Not done yet

- **Hosting.** Runs locally; no cron yet. Needs a host + daily schedule.

- **Petfinder + Korean K9** need API keys before they switch on.
