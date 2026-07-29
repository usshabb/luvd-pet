# 🐶 LUVD NYC

**Every new adoptable dog across NYC rescues, on one page, every morning.**

Each rescue is read from its own site where possible, and from the platform it
adopts on otherwise. Dogs you've already been shown never appear again. If
there's nothing new, no email goes out.

## How it works

```
check.py
  ├─ fetch     sources in priority order (own sites → platform APIs)
  ├─ dedupe    within-run (cross-source) + across-run (stable id in SQLite)
  ├─ normalize one shape for every source, so the UI is consistent
  ├─ enrich    3 at-a-glance scores + breed guide grounded in the rescue's words
  ├─ render    public/ — the daily page plus every crawlable page below
  └─ email     Resend digest to subscribers, linking to the page
```

## Sources

| Rescue | Priority | How | Status |
|---|---|---|---|
| Muddy Paws Rescue | 10 | public JSON API | ✅ 36 dogs |
| Animal Haven | 11 | server-rendered HTML + detail pages | ✅ 33 dogs |
| Waggytail Rescue | 12 | Petstablished JSON API (via Wix widget) | ✅ 9 dogs |
| Sugar Mutts Rescue | 13 | WordPress | ✅ 6 dogs |
| Sean Casey (24PetConnect) | 14 | server-rendered HTML | ✅ 4 dogs |
| Korean K9 Rescue | 15 | Petstablished org `1956188` | ✅ 29 dogs |
| NYC Second Chance Rescue | 16 | Petstablished org `83716` | ✅ 113 dogs |

230 dogs as of the last run. These move every day as rescues list and adopt out,
so treat the per-rescue numbers as a shape rather than a fact to assert
elsewhere — a run's own output is the only current count.

No credentials are needed for any source. Korean K9's own site sits behind a
Cloudflare challenge and NYC Second Chance's adoptable page is just an iframe of
the Petstablished widget, so both are read from `sources/petstablished.py` — the
public search API behind wagtopia.com, which is the same data their own pages
render. Waggytail is on Petstablished too and could move onto that shared class.

Korean K9 is the one source that splits: Petstablished hands back 31 dogs, but
their own site puts 14 on `/adopt` and 15 on `/foster-to-adopt`, with 2 records
on neither page. `current_location` says which is which, so `KoreanK9Source.route`
tags the foster-to-adopt dogs, points their button at the right application, and
drops the 2 strays. Those dogs are still in South Korea and come home on a 7-day
trial, which is too different from a normal adoption to leave unlabelled — see
"Placement programs" below.

There is no city-wide fallback: that was the Petfinder API, **decommissioned on
2 December 2025** in favour of an embed-only widget. `sources/petfinder.py` is
kept unregistered for reference. Every rescue is now listed explicitly above.

## Setup

```bash
cp .env.example .env
```

Fill in `.env`:

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

Layout claims in this README ("the grid does not move when you filter", "the
sort's touch target is 44px") are measured against a real browser rather than
eyeballed, using Playwright driving local Chrome. It is installed in `.venv` and
deliberately **not** in `requirements.txt` — it's a development tool, and the
site never imports it. `.venv/bin/pip install playwright` when you need it.
`HANDOFF.md` has the details, including the one measurement trap that produced a
convincing false positive.

## Pages we publish

Every run writes real, crawlable URLs — hash fragments can't be indexed. Flask
resolves the extensionless paths to their `.html` file, and `sitemap.xml` lists
all of them.

| URL | What it is |
|---|---|
| `/` | the daily page: one flat grid of every adoptable dog, newest first |
| `/rescues` | the roster: every rescue, its dog count, and a link to its own site |
| `/rescue/<slug>` | one rescue's full list — targets "muddy paws rescue dogs" |
| `/dog/<rescue>/<slug>` | one dog, with the rescue's own write-up |

`/` and `/rescue/*` carry JSON-LD; each rescue page declares its rescue as an
`AnimalShelter` so answer engines read them as organizations rather than list
rows. The homepage footer and the "Which rescues does LUVD cover?" answer both
link every rescue page — before that they were reachable only from individual
dog pages, which left them effectively unlinked.

Outbound links to a rescue's own site live on that rescue's page and on
`/rescues`, deliberately not in the site-wide footer: repeating the same seven
external links across 230+ pages is a link-scheme pattern, and footer
boilerplate is discounted anyway.

## Finding a dog on the page

One flat grid, newest arrival first. It used to be a section per day with a date
heading on each. That stopped working the moment filters arrived: the database
accumulates a section per day and only sheds one when a rescue delists a dog, so
within a few weeks a narrow filter scattered its handful of matches across a
dozen headings that each announced "1 dog". The arrival date didn't go anywhere —
it is the default sort, and today's dogs carry a NEW marker.

What did go with the headings is any stated total. **Nothing on the page says how
many dogs there are except the results count above the grid**, which is why that
line is permanent rather than something a filter conjures up.

### The results count

"230 dogs" — and "90 dogs" once a filter is on. Same sentence either way, only
the number changes. It sits left-aligned directly above the first row of cards,
at **19px/700 at every width — one size, no breakpoint**. The numeral is at full
contrast and the unit is grey, the same pairing the date and its "N dogs" had.

That 19px is deliberately one step *down* from the retired date headings, which
were 23px on desktop; it is exactly the size those headings dropped to on
phones. The count inherited their job when the grid was flattened, but not their
row: it now shares a line with the 15px sort trigger across some 790px of gap,
and at 23px the two ends read as unrelated things that happen to share a line
rather than as one results header.

Matching the sort exactly at 15px was tried and rejected. The count is the only
thing on the page that states how many dogs there are, and at control size it
stops reading as a heading and becomes metadata. 19px closes most of the
imbalance while still leading the grid.

**It doesn't say "90 of 230".** The pre-filter total was dropped on purpose: the
pills go solid accent when a filter is on, and clearing one brings the total
straight back, so the second number was spending words on something the controls
were already saying.

It is always on the page. It used to appear only once a filter was applied,
which shoved the entire grid down by the height of the row — roughly 45px — at
the exact instant you clicked, so the confirmation that the filter worked
arrived by moving the thing you were looking at. Permanent means filtering just
changes the number in place.

Nothing in that row comes or goes any more, so there is no shift left to
prevent. For a while it also held a Clear link that appeared with the first
filter, which needed a reserved height to stop the grid dropping as it arrived;
Clear is gone (see below) and the count and the sort are both permanent, so the
row is a constant 44px by construction. Filtering moves the pills, the grid and
the first card by 0.00px, measured at 1440px and 390px.

Sort sits at the right-hand end of that same line. That row is the page's
results header: what you're looking at on the left, the control that reorders it
on the right. The filter pills have the row above to themselves, and within any
one screen width the pills and the sort share a single control size so they read
as one set of controls — 15px on desktop, 13.5px on phones. The two widths
deliberately don't match: a phone row is width-constrained in a way desktop
isn't, and the larger type pushed the last pill further out of reach for no
visible gain. The sort stays the quieter of the two through weight and colour
rather than size, and never fills with accent, because something is always
sorting.

On phones the sort keeps its full "Sort by:" label. It was briefly cut down to
the bare value when the row was more crowded, which left it reading as a caption
rather than a control; the label is the affordance, so it came back as soon as
the line had room. Below 340px there genuinely isn't room, and only there does
it fall back to the value alone inside a thin border — still announced as "Sort
by: Recently added" to a screen reader.

### The filter row scrolls on a phone, and says so

Four pills don't fit a 390px screen. They need 412.7px against 358px available,
and it's one label's doing: "Foster-to-adopt 15" is 158.1px, wider than "Breed"
and "Age" put together. No amount of tightening closes that gap, so the row
scrolls sideways.

A row that scrolls with nothing at its edge just looks like a row that ends,
which would hide the one filter here that isn't a generic pet-site facet. So the
edge with more pills behind it fades out, and the fade disappears when you reach
the end — the same cue in reverse appears on the left once you've scrolled away
from the start. On desktop, where all four fit, it never appears at all.

It's drawn as a mask rather than as a gradient laid over the row, which means it
can't swallow a tap: every pill stays tappable through it. It also fades to
transparent rather than to a specific colour, so it's correct in both light and
dark without knowing which one is in play — and since the theme here follows NYC
sunrise and sunset rather than the operating system, that matters.

### There is no Clear button

Removing it is deliberate. Clear used to sit beside the count, where an
underlined link next to a heading read as a footnote rather than a control.
Nothing became unreachable: every pill menu opens with "Any breed" / "Any
gender" / "Any age", and Foster-to-adopt is a toggle, so each filter is undone
where it was set.

The one bulk reset that remains is **"Show all dogs"**, inside the "No dogs
match those filters" panel — the only place you can be genuinely stuck, because
an empty grid gives you nothing to judge which pill to loosen. In practice you
can't reach it by clicking: menu options that would return nothing are disabled,
so every click lands on at least one dog. It's there for the state, not the
route.

### Filters

Four pills — Breed, Gender, Age, and a Foster-to-adopt toggle. `breed_group` and
`age_bucket` are derived **server-side** in `page.py` (`breed_group()`,
`age_months()`, `age_bucket()`) and shipped on every dog, so the browser filters
against one fixed vocabulary instead of re-reading "approx 6 1/2 years" in JS.

Every option carries a live count, computed against the other active filters but
deliberately not against its own pill, so the numbers in an open menu are
reachable ones and no option can lead to an empty grid. The age buckets carry an
invariant worth keeping: every dog lands in exactly one of Puppy / Young / Adult
/ Senior / **Unknown**, never in none of them, so the options sum to the total
and "Any age" is never larger than its parts. A dog that sits in "Any" and in no
option is a dog you cannot click your way to, and the missing one makes the
arithmetic on screen look broken.

**There are deliberately no behaviour facets** — good with kids, good with dogs,
good with cats, house-trained. Only 3–14% of listings fill those fields in, and
coverage varies wildly across the seven rescues, so a filter on them would report
how thoroughly each rescue types its records rather than which dogs exist. Worse,
hiding a dog because a field is blank misrepresents that dog: absent data is not
a "no". Two clicks would land on a confident, false zero. Petfinder's wall of
facets is the anti-goal, not the target.

### Sort

"Recently added" (default) and "Longest waiting". They key on different fields on
purpose: "Recently added" is `first_seen`, when *LUVD* first saw the dog, and
"Longest waiting" is `waiting_days`, how long the *rescue* has had it listed. A
dog can be new here and have been waiting at its rescue for a year.

**"Longest waiting" silently did nothing for months.** `waiting_days` prefers a
dog's `listed_since` and only falls back to `first_seen`, and `listed_since` was
populated by exactly one thing — the Petfinder integration, decommissioned in
December 2025. After that every dog's `listed_since` was empty, `waiting_days`
was 0 across the board, and the sort reordered nothing at all while looking like
it worked. It is now extracted per source, through one shared parser in
`sources/dates.py`:

| Rescue | `listed_since` comes from |
|---|---|
| Korean K9, NYC Second Chance | Petstablished `created_at` (`sources/petstablished.py`) |
| Waggytail | Petstablished `created_at`, its own org `3856` |
| Sugar Mutts | the WordPress post's publish date |
| Sean Casey | the listing's "Brought to the shelter" field |
| Animal Haven | **nothing** — no date anywhere in the HubSpot/HubDB feed |
| Muddy Paws | **nothing** — the record carries no date field at all |

That's 154 of 230 dogs with a real listing date today. The other 76 are mostly
Animal Haven's and Muddy Paws' rosters, which fall back to `first_seen` — on a
freshly seeded database that is today, so they sort as the *shortest* waits.
That is a floor imposed by missing data, not a claim that those dogs just
arrived, and it's the main caveat on this sort.

`listing_date()` refuses anything it can't stand behind, returning an empty
string rather than a number: unparseable values, dates more than a day in the
future, anything before 2005 (unset columns arrive as the epoch or a placeholder
year), anything older than 12 years (past a large dog's whole life, so it's a
broken record rather than a long wait), and — when the feed also gives a
birthday — a listing date from before the dog was born, which catches a listing
page reused for a second dog of the same name. Petstablished sources also drop
the date for a dog whose previous status was "adopted", since a returned dog's
record long predates the listing you're looking at.

### Badges

Two module-level flags in `page.py` decide what appears on a card:

- **`SHOW_WAIT_BADGE_ON_CARDS = False`.** The hourglass "⏳ Listed N days" badge
  is off on grid cards. Once the scrapers started supplying real listing dates,
  the 60-day threshold put it on 104 of 223 cards and 86 of those were NYC
  Second Chance — three quarters of one rescue's roster. A badge on half the grid
  signals nothing, and concentrated in one rescue it reads as a verdict on them
  rather than a nudge about a dog. It is **still shown** on the dog detail page
  and in the modal, where you're reading one dog and it's a useful fact rather
  than a pattern. Raise `WAIT_BADGE_DAYS` (currently 60) before turning it back
  on; 180 days is still 62 cards.
- **`NEW_MARK_MAX_SHARE = 0.5`.** The NEW marker is suppressed *entirely* when
  more than half the grid arrived today, because a marker on nearly every card
  marks nothing.

**The consequence of that second flag will confuse you at some point:** on a
freshly seeded database every dog is seen for the first time today, so no NEW
marker renders anywhere on the page. That is the flag working, not a bug. Markers
return on the first day the roster is a mix. If you are looking for them and
finding none, check whether every dog's `first_seen` is today before you go
hunting in the rendering code.

The NEW marker sits on the photo itself, bottom-right — the corner the wait badge
vacated — rather than beside the dog's name.

## Saved dogs

Hearts on cards keep a list of dog IDs in `localStorage` (`SAVE_KEY`, currently
`luvd:saved`). No account, nothing sent to the server, nothing that survives
clearing the browser. A chip in the header shows the count and toggles a
saved-only view.

The saved view and the main grid deliberately behave **differently** when you
unsave something. In the saved view the grid *is* the list of saved dogs, so
unsaving a dog removes its card immediately, and unsaving the last one reveals
the "No saved dogs yet" empty state. In the main grid, tapping a heart changes
nothing but the heart: the card you just tapped never moves, reflows or
disappears out from under your finger. That asymmetry is the whole design — the
heart handler calls `applyView()` only when `showingSaved` is true.

Entering the saved view **clears any active filters**; leaving it **puts them
back**. The two directions differ on purpose. Going in, a saved list is a
handful of dogs, and leaving pills applied behind a filter bar that's just been
hidden would silently shorten it — you'd see four of your six saved dogs with
nothing on screen explaining the other two. Coming out, those filters were a
search you were part-way through, and glancing at a saved dog shouldn't cost you
your place in it. The sort order survives throughout; it is never cleared.

## Placement programs

Not every dog is a plain adoption. A `Dog` can carry a `program` (`program_label`
for the chip, `program_note` for the terms), which changes three things in the UI:
an amber pill leads the card ahead of breed, a matching chip leads the modal, and
the note sits directly above the apply button — the one place someone can't miss
it before they click.

The only program today is Korean K9's foster-to-adopt, where the dog hasn't left
South Korea yet: you meet them for the first time at pickup, take them home for a
7-day trial, and keep fostering ~3 weeks if it isn't a fit. The button goes to
their foster-to-adopt page rather than the form behind it, because the arrival
date each application is timed against (applications close 48 hours before) is
only published on the page.

The rule of thumb for adding one: if a listing needs a different application or
asks for a materially different commitment, it's a program, not a trait.

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

- **Breed data.** Roughly a third of dogs come through with breed "Unknown" —
  Muddy Paws in particular. The scores lean on the write-up to compensate.
